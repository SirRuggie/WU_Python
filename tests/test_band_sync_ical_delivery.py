import asyncio
import warnings
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from extensions.tasks import band_monitor
from extensions.tasks import band_sync_ical as sync
from extensions.tasks import band_sync_panel as panel
from extensions.tasks import band_sync_schema as schema


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue

        exists = key in document
        actual = document.get(key)
        if isinstance(expected, dict):
            for operator, operand in expected.items():
                if operator == "$exists" and exists is not bool(operand):
                    return False
                if operator == "$in" and actual not in operand:
                    return False
                if operator == "$ne" and actual == operand:
                    return False
                if operator == "$lte" and (actual is None or actual > operand):
                    return False
            continue
        if actual != expected:
            return False
    return True


class FakeCursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n):
        self.documents = self.documents[:n]
        return self

    def __aiter__(self):
        self._iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    def __init__(self, documents=()):
        self.documents = {document["_id"]: deepcopy(document) for document in documents}

    async def find_one(self, query, projection=None):
        for document in self.documents.values():
            if _matches(document, query):
                if projection:
                    return {key: deepcopy(value) for key, value in document.items()
                            if key == "_id" or projection.get(key)}
                return deepcopy(document)
        return None

    def find(self, query, projection=None):
        return FakeCursor(
            document for document in self.documents.values()
            if _matches(document, query)
        )

    async def insert_one(self, document):
        if document["_id"] in self.documents:
            raise sync.DuplicateKeyError("duplicate")
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update, upsert=False):
        target = None
        for document in self.documents.values():
            if _matches(document, query):
                target = document
                break
        if target is None:
            if upsert:
                new_doc = dict(query)
                for key, value in update.get("$set", {}).items():
                    new_doc[key] = deepcopy(value)
                for key, value in update.get("$setOnInsert", {}).items():
                    new_doc.setdefault(key, deepcopy(value))
                new_doc.setdefault("_id", query.get("_id"))
                self.documents[new_doc["_id"]] = new_doc
                return SimpleNamespace(modified_count=0, upserted_id=new_doc["_id"])
            return SimpleNamespace(modified_count=0, upserted_id=None)

        for key, value in update.get("$set", {}).items():
            target[key] = deepcopy(value)
        for key in update.get("$unset", {}):
            target.pop(key, None)
        for key, instruction in update.get("$addToSet", {}).items():
            values = instruction.get("$each", [])
            target.setdefault(key, [])
            for value in values:
                if value not in target[key]:
                    target[key].append(deepcopy(value))
        return SimpleNamespace(modified_count=1, upserted_id=None)

    async def delete_one(self, query):
        for doc_id, document in list(self.documents.items()):
            if _matches(document, query):
                del self.documents[doc_id]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def delete_many(self, query):
        deleted = 0
        for doc_id, document in list(self.documents.items()):
            if _matches(document, query):
                del self.documents[doc_id]
                deleted += 1
        return SimpleNamespace(deleted_count=deleted)

    async def create_index(self, *args, **kwargs):
        return kwargs.get("name") or "index"


class FakeMongo:
    """Stands in for utils.mongo.MongoClient's four declared fwa_sync_* attributes."""

    def __init__(self, config=(), events=(), responses=(), deliveries=()):
        self.fwa_sync_config = FakeCollection(config)
        self.fwa_sync_events = FakeCollection(events)
        self.fwa_sync_responses = FakeCollection(responses)
        self.fwa_sync_deliveries = FakeCollection(deliveries)

    def get_database(self, _name):
        # Only reached by the legacy-config migration path in these tests.
        return SimpleNamespace(get_collection=lambda _n: self._legacy)


class FakeRest:
    def __init__(self, failures=None):
        self.failures = dict(failures or {})
        self.attempts = []
        self.deleted_messages = []
        self.edits = []
        self.edit_embeds = []
        self.edit_components = []
        self.create_calls = []  # (channel, role_mentions, user_mentions) per create_message
        self._next_message_id = 9000

    async def fetch_user(self, user_id):
        return SimpleNamespace(id=user_id)

    async def create_dm_channel(self, user_id):
        return user_id

    async def create_message(self, channel, embed=None, components=None,
                              role_mentions=None, user_mentions=None):
        self.attempts.append(channel)
        self.create_calls.append((channel, role_mentions, user_mentions))
        remaining = self.failures.get(channel, 0)
        if isinstance(remaining, BaseException):
            raise remaining
        if remaining:
            self.failures[channel] = remaining - 1
            raise RuntimeError("temporary Discord failure")
        self._next_message_id += 1
        return SimpleNamespace(id=self._next_message_id)

    async def edit_message(self, channel_id, message_id, embed=None, components=None):
        self.edits.append((channel_id, message_id))
        self.edit_embeds.append(embed)
        self.edit_components.append(components)
        remaining = self.failures.get(message_id, 0)
        if isinstance(remaining, BaseException):
            raise remaining

    async def delete_message(self, channel_id, message_id):
        remaining = self.failures.get(message_id, 0)
        if isinstance(remaining, BaseException):
            raise remaining
        if remaining:
            self.failures[message_id] = remaining - 1
            raise RuntimeError("temporary Discord failure")
        self.deleted_messages.append((channel_id, message_id))


def _panel_texts(components):
    """The rendered Text content of a panel/DM Container edit - band-sync-panel-restyle
    replaced the plain embed with a Components V2 Container, so an "edited panel says
    the new time" assertion now reads Text.content off the Container's children."""
    container = components[0]
    return [child.content for child in container.components if hasattr(child, "content")]


def _event(uid="sync-1", start=None):
    start = start or datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    return {
        "uid": uid,
        "start": start,
        "end": start + timedelta(minutes=40),
        "summary": "FWA high sync",
        "calendar": "Sync3",
    }


def _config(recipients, legacy_broadcast=True):
    return {
        "dm_user_ids": recipients,
        "offsets": [60, 10],
        "announce_on_discovery": True,
        "legacy_broadcast": legacy_broadcast,
    }


def _deliveries(mongo):
    return list(mongo.fwa_sync_deliveries.documents.values())


def test_base_embed_normalizes_a_naive_start(monkeypatch):
    """refuter-04 noted, non-blocking: _base_embed passed event["start"] straight into
    Embed(timestamp=...) with no normalize_start() call - a naive datetime (e.g. read
    back from Mongo) makes hikari raise HikariWarning under warnings-as-errors."""
    aware_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    event = _event(start=aware_start)
    event["start"] = event["start"].replace(tzinfo=None)  # mimic a naive Mongo read

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        embed = sync.build_embed(event, sync.DISCOVERY_OFFSET)

    assert embed.timestamp == aware_start


def test_delivery_retry_schedule_is_capped():
    assert [sync._retry_delay(attempt) for attempt in range(1, 7)] == [
        timedelta(minutes=5),
        timedelta(minutes=15),
        timedelta(minutes=30),
        timedelta(hours=1),
        timedelta(hours=3),
        timedelta(hours=3),
    ]


def test_dm_all_deduplicates_recipients_in_configured_order(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))

    sent = asyncio.run(sync.dm_all([2, "2", 1, 2], object()))

    assert sent == 2
    assert rest.attempts == [2, 1]


def test_partial_delivery_retries_only_failed_recipient(monkeypatch):
    rest = FakeRest({2: 1})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    mongo = FakeMongo()
    # A pure delivery-queue test - explicitly unconfigure the panel channel so
    # process_event's discovery-time panel post (band-sync-panel-restyle default,
    # schema.new_config_doc) does not add an unrelated create_message to rest.attempts.
    # 0, not None: normalize_config now treats a stored None as "not yet configured"
    # and falls back to NOTIFICATION_CHANNEL_ID (refuter-01 must-fix 3); 0 is the one
    # value post_or_replace_panel's `if not channel_id` still reads as "no panel".
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)
    event = _event()
    state = sync._event_state_doc(event, [sync.DISCOVERY_OFFSET])
    state.update(panel_message_id=111, panel_version=sync._event_version(event))
    mongo.fwa_sync_events = FakeCollection([state])
    now = event["start"] - timedelta(minutes=59)
    _store_response(mongo, event, 1, "in", [60])
    _store_response(mongo, event, 2, "in", [60])

    asyncio.run(sync.process_event(mongo, event, _config([]), now))

    statuses = {document["recipient_id"]: document["status"]
                for document in _deliveries(mongo)}
    assert statuses == {1: "sent", 2: "failed"}
    assert rest.attempts == [1, 2]

    asyncio.run(sync.process_event(
        mongo, event, _config([1, 2]), now + timedelta(minutes=1)
    ))

    statuses = {document["recipient_id"]: document["status"]
                for document in _deliveries(mongo)}
    assert statuses == {1: "sent", 2: "failed"}
    assert rest.attempts == [1, 2]

    asyncio.run(sync.process_event(
        mongo, event, _config([1, 2]), now + timedelta(minutes=5)
    ))

    statuses = {document["recipient_id"]: document["status"]
                for document in _deliveries(mongo)}
    assert statuses == {1: "sent", 2: "sent"}
    assert rest.attempts == [1, 2, 2]


def test_only_numeric_reminder_delivery_uses_countdown_dm(monkeypatch):
    event = _event()
    responses = [
        schema.new_response_doc(
            event["uid"], user_id, event["start"], schema.event_version(event),
            "in", reminders=[10, 0],
        )
        for user_id in (7, 8)
    ]
    deliveries = [
        sync._delivery_doc(event, sync.DISCOVERY_OFFSET, 7),
        sync._delivery_doc(event, "10", 7),
        sync._delivery_doc(event, "0", 7),
        sync._delivery_doc(event, "0", 8, delivery_type="once"),
    ]
    mongo = FakeMongo(responses=responses, deliveries=deliveries)
    render_types = []

    async def fake_load_config(_mongo):
        return {}

    async def fake_send_dm(_mongo, _bot, _event, _response, _url, render_type):
        render_types.append(render_type)
        return SimpleNamespace(sent=True, permanent=False, error_type=None, detail=None)

    monkeypatch.setattr(sync, "load_config", fake_load_config)
    monkeypatch.setattr(panel, "band_url", lambda _event, _config: "https://band.us")
    monkeypatch.setattr(panel, "send_dm", fake_send_dm)

    asyncio.run(sync.deliver_outstanding(mongo, event, event["start"]))

    assert render_types == ["timed_reminder", "timed_reminder", "once"]
    stored = _deliveries(mongo)
    assert stored[0]["status"] == "abandoned"
    assert stored[0]["terminal_reason"] == "opt_in_removed"
    assert all(delivery["status"] == "sent" for delivery in stored[1:])


def test_stale_pending_lease_is_reclaimed(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    delivery = sync._delivery_doc(event, "60", 7)
    delivery.update({
        "status": "pending",
        "lease_until": datetime.now(timezone.utc) - timedelta(seconds=1),
    })
    mongo = FakeMongo(deliveries=[delivery])
    _store_response(mongo, event, 7, reminders=[60])

    asyncio.run(sync.deliver_outstanding(mongo, event))

    assert mongo.fwa_sync_deliveries.documents[delivery["_id"]]["status"] == "sent"
    assert rest.attempts == [7]


def test_at_sync_reminder_is_sent_even_when_absent_from_legacy_config(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    state = sync._event_state_doc(event, [sync.DISCOVERY_OFFSET])
    state.update(panel_message_id=111, panel_version=sync._event_version(event))
    mongo = FakeMongo(events=[state])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)
    _store_response(mongo, event, 7, "in", [0])

    asyncio.run(sync.process_event(
        mongo, event, _config([]), event["start"]
    ))

    sent = [delivery for delivery in _deliveries(mongo) if delivery["offset"] == "0"]
    assert len(sent) == 1
    assert sent[0]["status"] == "sent"
    assert rest.attempts == [7]


def test_reschedule_clears_responses_deliveries_and_reposts_panel_no_change_alert(monkeypatch):
    """builder-06 (DECISIONS.md D009): a time change is handled like a new sync - both
    responses for this uid (with reminders in and maybe alike) and every delivery are
    wiped, their tracked DMs deleted, no "change" delivery is ever enqueued, the old
    panel is deleted, and a fresh one is posted with the role ping."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    state["panel_channel_id"] = 555
    state["panel_message_id"] = 111
    state["panel_version"] = sync._event_version(old_event)
    response_in = schema.new_response_doc(
        old_event["uid"], 77, old_start, "v0", "in", reminders=[60],
        dm_channel_id=10, dm_message_id=20,
    )
    response_maybe = schema.new_response_doc(
        old_event["uid"], 78, old_start, "v0", "maybe", reminders=[0],
        dm_channel_id=30, dm_message_id=40,
    )
    mongo = FakeMongo(events=[state], responses=[response_in, response_maybe])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(
        panel_channel_id=555,
        current_panel={"uid": old_event["uid"], "channel_id": 555, "message_id": 111},
    )
    new_start = old_start + timedelta(hours=2)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    assert mongo.fwa_sync_responses.documents == {}
    assert mongo.fwa_sync_deliveries.documents == {}
    assert (10, 20) in rest.deleted_messages
    assert (30, 40) in rest.deleted_messages
    assert (555, 111) in rest.deleted_messages  # old panel deleted

    stored = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert sync.normalize_start(stored["start_at"]) == new_start
    assert stored["panel_message_id"] is not None
    assert stored["panel_message_id"] != 111
    assert stored["panel_version"] == stored["event_version"]

    channel, role_mentions, user_mentions = rest.create_calls[-1]
    assert channel == 555
    assert role_mentions == [band_monitor.ALLOWED_ROLE_ID]
    assert user_mentions is True

    current_panel = mongo.fwa_sync_config.documents["config"]["current_panel"]
    assert current_panel["uid"] == moved["uid"]
    assert current_panel["message_id"] == stored["panel_message_id"]


def test_reschedule_then_no_reminder_fires_until_someone_opts_in_again(monkeypatch):
    """Responses are wiped by the reschedule, so a poll landing on the offset that used
    to be due for the old responder must send nothing - nobody is opted in yet."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    response = schema.new_response_doc(old_event["uid"], 77, old_start, "v0", "in", reminders=[60])
    mongo = FakeMongo(events=[state], responses=[response])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)
    new_start = old_start + timedelta(hours=2)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))
    assert [d for d in _deliveries(mongo) if d["delivery_type"] == "change"] == []

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(minutes=60)))

    assert [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"] == []


def test_user_who_opts_in_after_reschedule_repost_gets_reminder_at_new_time(monkeypatch):
    """A user opting in against the reposted panel (fresh event_version) still gets
    their chosen reminder once it comes due against the NEW start time."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    mongo = FakeMongo(events=[state])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)
    new_start = old_start + timedelta(hours=2)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    stored_event = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    asyncio.run(panel.upsert_response(mongo, moved["uid"], stored_event, 99, "in", [60]))

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(minutes=60)))

    reminders = [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"]
    assert [d["recipient_id"] for d in reminders] == [99]


def test_reschedule_crash_before_event_update_leaves_old_start_next_poll_completes(monkeypatch):
    """Crash-safety: responses/deliveries are cleared BEFORE start_at moves, so a crash
    raised out of the event-state update leaves the old start_at in place with the
    clearing already done - and simply re-running handle_reschedule (as the next poll
    would, since detect_reschedule still sees the move) completes it."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    response = schema.new_response_doc(old_event["uid"], 77, old_start, "v0", "in", reminders=[60])
    mongo = FakeMongo(events=[state], responses=[response])
    new_start = old_start + timedelta(hours=2)
    moved = _event(start=new_start)

    real_update_one = mongo.fwa_sync_events.update_one
    calls = {"n": 0}

    async def flaky_update_one(query, update, upsert=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crash mid-reschedule")
        return await real_update_one(query, update, upsert=upsert)
    mongo.fwa_sync_events.update_one = flaky_update_one

    with pytest.raises(RuntimeError):
        asyncio.run(sync.handle_reschedule(mongo, moved, state))

    assert mongo.fwa_sync_responses.documents == {}  # cleared before the failing write
    assert mongo.fwa_sync_deliveries.documents == {}
    stored = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert sync.normalize_start(stored["start_at"]) == old_start  # not yet moved

    asyncio.run(sync.handle_reschedule(mongo, moved, stored))  # next poll retries, completes

    stored_again = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert sync.normalize_start(stored_again["start_at"]) == new_start


def test_normal_poll_does_not_refresh_the_panel_when_panel_version_matches(monkeypatch):
    """Once panel_version already equals event_version, a normal poll (no reschedule,
    no lag) must not touch the channel panel at all - exactly one refresh trigger,
    not a refresh on every poll."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    state = sync._event_state_doc(event, [sync.DISCOVERY_OFFSET])
    state["panel_channel_id"] = 555
    state["panel_message_id"] = 111
    state["panel_version"] = sync._event_version(event)
    mongo = FakeMongo(events=[state])
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, event, config, event["start"] - timedelta(hours=5)))

    assert rest.edits == []
    assert 555 not in rest.attempts


def test_discovery_offset_with_no_recipients_retires_silently(monkeypatch, capsys):
    """Test e: "new" with nobody to notify is retired after one poll, with no warning
    log - unlike a numeric offset, which stays open and does warn (refuter-01 noted
    log)."""
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=FakeRest()))
    event = _event()
    mongo = FakeMongo()
    now = event["start"] - timedelta(hours=5)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, event, config, now))

    stored = mongo.fwa_sync_events.documents[sync._event_state_id(event["uid"])]
    assert sync.DISCOVERY_OFFSET in stored["closed_offsets"]
    assert "no recipients" not in capsys.readouterr().out

    asyncio.run(sync.process_event(mongo, event, config, now + timedelta(minutes=1)))

    assert "no recipients" not in capsys.readouterr().out


def test_permanent_dm_failure_is_abandoned_immediately(monkeypatch):
    forbidden = sync.hikari.ForbiddenError(
        "https://discord.test", {}, {}, "Cannot send messages to this user"
    )
    rest = FakeRest({7: forbidden})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    now = event["start"] - timedelta(minutes=59)
    mongo = FakeMongo()
    # A pure delivery-queue test - see test_partial_delivery_retries_only_failed_recipient.
    # 0, not None: normalize_config now treats a stored None as "not yet configured"
    # and falls back to NOTIFICATION_CHANNEL_ID (refuter-01 must-fix 3); 0 is the one
    # value post_or_replace_panel's `if not channel_id` still reads as "no panel".
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)
    state = sync._event_state_doc(event, [sync.DISCOVERY_OFFSET])
    state.update(panel_message_id=111, panel_version=sync._event_version(event))
    mongo.fwa_sync_events = FakeCollection([state])

    _store_response(mongo, event, 7, "in", [60])
    asyncio.run(sync.process_event(mongo, event, _config([]), now))

    delivery = _deliveries(mongo)[0]
    assert delivery["status"] == "abandoned"
    assert delivery["terminal_reason"] == "permanent_discord_error"
    assert delivery["failure_count"] == 1
    assert "next_attempt_at" not in delivery
    assert rest.attempts == [7]

    asyncio.run(sync.process_event(
        mongo, event, _config([7]), now + timedelta(minutes=1)
    ))
    assert rest.attempts == [7]


def test_queued_delivery_without_live_opt_in_is_abandoned_without_dm(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    delivery = sync._delivery_doc(event, "60", 7)
    delivery.update({
        "status": "pending",
        "lease_until": datetime.now(timezone.utc) - timedelta(seconds=1),
        "next_attempt_at": datetime.now(timezone.utc),
    })
    mongo = FakeMongo(deliveries=[delivery])

    asyncio.run(sync.deliver_outstanding(mongo, event))

    stored = mongo.fwa_sync_deliveries.documents[delivery["_id"]]
    assert stored["status"] == "abandoned"
    assert stored["terminal_reason"] == "opt_in_removed"
    assert "lease_until" not in stored
    assert "next_attempt_at" not in stored
    assert rest.attempts == []


@pytest.mark.parametrize(("status", "reminders"), [("no", [60]), ("in", [10])])
def test_queued_delivery_with_withdrawn_or_removed_reminder_is_abandoned(
    monkeypatch, status, reminders
):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    delivery = sync._delivery_doc(event, "60", 7)
    mongo = FakeMongo(deliveries=[delivery])
    _store_response(mongo, event, 7, status, reminders)

    asyncio.run(sync.deliver_outstanding(mongo, event))

    stored = mongo.fwa_sync_deliveries.documents[delivery["_id"]]
    assert stored["status"] == "abandoned"
    assert stored["terminal_reason"] == "opt_in_removed"
    assert rest.attempts == []


def test_transient_dm_failure_stops_at_failure_limit(monkeypatch):
    rest = FakeRest({7: 1})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    now = event["start"] - timedelta(hours=2)
    delivery = sync._delivery_doc(event, "60", 7)
    delivery.update({
        "status": "failed",
        "failure_count": sync.DELIVERY_MAX_FAILURES - 1,
        "first_failed_at": now - timedelta(hours=1),
        "next_attempt_at": now,
    })
    mongo = FakeMongo(deliveries=[delivery])
    _store_response(mongo, event, 7, reminders=[60])

    asyncio.run(sync.deliver_outstanding(mongo, event, now))

    stored = mongo.fwa_sync_deliveries.documents[delivery["_id"]]
    assert stored["status"] == "abandoned"
    assert stored["terminal_reason"] == "failure_limit"
    assert stored["failure_count"] == sync.DELIVERY_MAX_FAILURES
    assert "next_attempt_at" not in stored
    assert rest.attempts == [7]


def test_transient_dm_failure_stops_after_maximum_age(monkeypatch):
    rest = FakeRest({7: 1})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    now = event["start"] - timedelta(hours=2)
    delivery = sync._delivery_doc(event, "60", 7)
    delivery.update({
        "status": "failed",
        "failure_count": 1,
        "first_failed_at": now - sync.DELIVERY_MAX_AGE,
        "next_attempt_at": now,
    })
    mongo = FakeMongo(deliveries=[delivery])
    _store_response(mongo, event, 7, reminders=[60])

    asyncio.run(sync.deliver_outstanding(mongo, event, now))

    stored = mongo.fwa_sync_deliveries.documents[delivery["_id"]]
    assert stored["status"] == "abandoned"
    assert stored["terminal_reason"] == "age_limit"


# ---- band_sync_schema.recipients_for_offset ----
def _response(user_id, status, reminders=()):
    return {"user_id": user_id, "status": status, "reminders": list(reminders)}


def _store_response(mongo, event, user_id, status="in", reminders=()):
    """Seed a complete response row with the same shape as the production upsert."""
    response = schema.new_response_doc(
        event["uid"], user_id, event["start"], schema.event_version(event),
        status, reminders=reminders,
    )
    mongo.fwa_sync_responses.documents[response["_id"]] = response


def test_recipients_for_offset_only_counts_opted_in_users_with_that_reminder():
    """DECISIONS.md D007: maybe counts too, same as in - only no and a not-chosen
    offset exclude a user."""
    config = {"dm_user_ids": [], "legacy_broadcast": False}
    responses = [
        _response(1, "in", [60, 10]),
        _response(2, "maybe", [60]),   # maybe counts, same as in (D007)
        _response(3, "no", [60]),      # no never counts
        _response(4, "in", [10]),      # in, but this offset not chosen
    ]
    assert schema.recipients_for_offset(config, responses, 60) == [1, 2]
    assert schema.recipients_for_offset(config, responses, 10) == [1, 4]


def test_recipients_for_offset_maybe_user_counts_like_in():
    config = {"dm_user_ids": [], "legacy_broadcast": False}
    responses = [_response(7, "maybe", [60])]
    assert schema.recipients_for_offset(config, responses, 60) == [7]


def test_recipients_for_offset_no_user_never_counts():
    config = {"dm_user_ids": [], "legacy_broadcast": False}
    responses = [_response(8, "no", [60])]
    assert schema.recipients_for_offset(config, responses, 60) == []


def test_recipients_for_offset_ignores_retired_fixed_recipient_fields():
    responses = [_response(1, "in", [60])]
    config = {"dm_user_ids": [1, 5], "legacy_broadcast": True}
    assert schema.recipients_for_offset(config, responses, 60) == [1]


def test_recipients_for_offset_without_opt_ins_is_empty_even_with_legacy_ids():
    config = {"dm_user_ids": [0, -1, "not-a-number", 9, 9], "legacy_broadcast": True}
    assert schema.recipients_for_offset(config, [], 60) == []


# ---- Purge ----
def test_purge_deletes_dm_responses_deliveries_and_event_after_start_plus_one_hour(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    event = sync._event_state_doc(_event(uid="finished", start=start))
    response = schema.new_response_doc(
        "finished", 42, start, "v1", "in", reminders=[60],
        dm_channel_id=111, dm_message_id=222, now=start,
    )
    delivery = schema.new_delivery_doc(_event(uid="finished", start=start), "60", 42, now=start)
    mongo = FakeMongo(events=[event], responses=[response], deliveries=[delivery])

    now = start + timedelta(hours=1, minutes=1)
    asyncio.run(sync.purge_finished_events(mongo, now))

    assert mongo.fwa_sync_events.documents == {}
    assert mongo.fwa_sync_responses.documents == {}
    assert mongo.fwa_sync_deliveries.documents == {}
    assert rest.deleted_messages == [(111, 222)]


def test_purge_leaves_event_untouched_before_start_plus_one_hour(monkeypatch):
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=FakeRest()))
    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    event = sync._event_state_doc(_event(uid="not-yet-over", start=start))
    mongo = FakeMongo(events=[event])

    now = start + timedelta(minutes=30)  # still inside the event window
    asyncio.run(sync.purge_finished_events(mongo, now))

    assert "event:not-yet-over" in mongo.fwa_sync_events.documents


def test_purge_ignores_not_found_when_deleting_the_dm(monkeypatch):
    rest = FakeRest()
    async def raise_not_found(channel_id, message_id):
        raise sync.hikari.NotFoundError("https://discord.test", {}, {}, "unknown message")
    rest.delete_message = raise_not_found
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    event = sync._event_state_doc(_event(uid="dm-already-gone", start=start))
    response = schema.new_response_doc(
        "dm-already-gone", 1, start, "v1", "in",
        dm_channel_id=5, dm_message_id=6, now=start,
    )
    mongo = FakeMongo(events=[event], responses=[response])

    now = start + timedelta(hours=2)
    asyncio.run(sync.purge_finished_events(mongo, now))  # must not raise

    assert mongo.fwa_sync_events.documents == {}


# ---- D006 restart backstop: sweep_dm_deletions ----
def test_sweep_dm_deletions_deletes_overdue_and_leaves_future_ones(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 5, 18, 20, tzinfo=timezone.utc)
    overdue = schema.new_response_doc(
        "sync-1", 1, start, "v1", "in",
        dm_channel_id=10, dm_message_id=20, dm_delete_at=now - timedelta(minutes=1),
    )
    future = schema.new_response_doc(
        "sync-1", 2, start, "v1", "in",
        dm_channel_id=30, dm_message_id=40, dm_delete_at=now + timedelta(minutes=5),
    )
    mongo = FakeMongo(responses=[overdue, future])

    asyncio.run(sync.sweep_dm_deletions(mongo, now))

    assert (10, 20) in rest.deleted_messages
    assert (30, 40) not in rest.deleted_messages
    overdue_stored = mongo.fwa_sync_responses.documents[overdue["_id"]]
    assert "dm_message_id" not in overdue_stored
    assert overdue_stored["status"] == "in"  # status/reminders untouched
    future_stored = mongo.fwa_sync_responses.documents[future["_id"]]
    assert future_stored["dm_message_id"] == 40  # not touched


def test_sweep_dm_deletions_ignores_not_found(monkeypatch):
    rest = FakeRest()
    async def raise_not_found(channel_id, message_id):
        raise sync.hikari.NotFoundError("https://discord.test", {}, {}, "unknown message")
    rest.delete_message = raise_not_found
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 5, 18, 20, tzinfo=timezone.utc)
    response = schema.new_response_doc(
        "sync-1", 1, start, "v1", "in",
        dm_channel_id=10, dm_message_id=20, dm_delete_at=now - timedelta(minutes=1),
    )
    mongo = FakeMongo(responses=[response])

    asyncio.run(sync.sweep_dm_deletions(mongo, now))  # must not raise

    stored = mongo.fwa_sync_responses.documents[response["_id"]]
    assert "dm_message_id" not in stored


def test_sweep_dm_deletions_leaves_fields_on_transient_failure(monkeypatch):
    rest = FakeRest()
    async def raise_runtime_error(channel_id, message_id):
        raise RuntimeError("temporary Discord failure")
    rest.delete_message = raise_runtime_error
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 5, 18, 20, tzinfo=timezone.utc)
    response = schema.new_response_doc(
        "sync-1", 1, start, "v1", "in",
        dm_channel_id=10, dm_message_id=20, dm_delete_at=now - timedelta(minutes=1),
    )
    mongo = FakeMongo(responses=[response])

    asyncio.run(sync.sweep_dm_deletions(mongo, now))  # must not raise

    stored = mongo.fwa_sync_responses.documents[response["_id"]]
    assert stored["dm_message_id"] == 20  # retried next pass, not orphaned


# ---- Migration ----
def test_migration_copies_legacy_config_when_new_collection_is_empty():
    legacy_doc = {
        "_id": "config", "enabled": True, "offsets": [60, 10],
        "announce_on_discovery": False, "dm_user_ids": [5, 6],
    }
    mongo = FakeMongo()
    mongo._legacy = FakeCollection([legacy_doc])

    migrated = asyncio.run(sync._migrate_legacy_config(mongo))

    assert migrated is True
    doc = mongo.fwa_sync_config.documents["config"]
    assert doc["enabled"] is True
    assert doc["offsets"] == [60, 10]
    assert doc["announce_on_discovery"] is False
    assert "dm_user_ids" not in doc
    assert "legacy_broadcast" not in doc


def test_migration_is_a_noop_when_no_legacy_doc_exists():
    mongo = FakeMongo()
    mongo._legacy = FakeCollection([])

    migrated = asyncio.run(sync._migrate_legacy_config(mongo))

    assert migrated is False
    assert mongo.fwa_sync_config.documents == {}


# ---- Offset 0 (at event time) ----
def test_due_offsets_now_fires_offset_zero_at_start_per_d011():
    """D006 (offset 0 can never fire) is superseded by D011: due_offsets() now treats
    0 as due in [start, start+10m), and drop_past() (utils/band_ical_parser.py) keeps
    the event visible that long. See tests/test_band_ical_parser.py for the full
    before/at/after/twice coverage of due_offsets() itself; this only proves
    process_event's own offsets list (which defaults to including 0, see
    band_sync_schema.DEFAULT_OFFSETS) reaches it end to end."""
    from utils.band_ical_parser import due_offsets

    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    to_send, to_retire = due_offsets(start, start, claimed=set(), offsets=[60, 10, 0])
    assert "0" in to_send
    assert "0" not in to_retire


def test_recipients_for_offset_zero_still_resolves_reminders_stored_as_zero():
    """The pure recipient helper has no opinion on which offsets are deliverable - that
    is due_offsets()'s job. A response that chose reminder 0 still matches here."""
    responses = [_response(1, "in", [0])]
    config = {"dm_user_ids": [], "legacy_broadcast": False}
    assert schema.recipients_for_offset(config, responses, 0) == [1]


def test_startup_recovers_from_mongo_failure_and_starts_one_poller(monkeypatch):
    class StartupCollection:
        def __init__(self):
            self.find_failures = 1
            self.index_calls = 0

        async def create_index(self, *args, **kwargs):
            self.index_calls += 1
            return "ttl_expire_at"

        async def find_one(self, query, projection=None):
            if self.find_failures:
                self.find_failures -= 1
                raise RuntimeError("Mongo starting")
            return {"_id": sync.CONFIG_ID, "enabled": False}

    collection = StartupCollection()

    class Database:
        def get_collection(self, _name):
            return collection

    class Mongo:
        def __init__(self):
            self.fwa_sync_config = collection
            self.fwa_sync_events = collection
            self.fwa_sync_responses = collection
            self.fwa_sync_deliveries = collection

        def get_database(self, _name):
            return Database()

    loop_started = asyncio.Event()
    loop_calls = 0

    async def fake_poller(_mongo):
        nonlocal loop_calls
        loop_calls += 1
        loop_started.set()
        await asyncio.Event().wait()

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(sync, "mongo_client", Mongo())
    monkeypatch.setattr(sync, "poller_task", None)
    monkeypatch.setattr(sync, "poller_loop", fake_poller)

    reconciler = sync.StartupReconciler(
        "ical_test",
        sync._reconcile_ical_startup,
        retry_delays=(0,),
        sleep=no_wait,
    )

    async def scenario():
        await reconciler.start()
        await loop_started.wait()
        await sync._reconcile_ical_startup()
        assert sync.poller_task and not sync.poller_task.done()
        sync.poller_task.cancel()
        await asyncio.gather(sync.poller_task, return_exceptions=True)
        sync.poller_task = None

    asyncio.run(scenario())

    assert reconciler.health.state == "healthy"
    assert reconciler.health.attempts == 2
    assert loop_calls == 1
    # ensure_indexes creates 5 named indexes per call; 3 reconcile attempts (1 failing +
    # 2 succeeding, the third invoked directly by the scenario) = 15.
    assert collection.index_calls == 15


def test_shutdown_awaits_poller_cancellation(monkeypatch):
    cancelled = asyncio.Event()

    async def poller():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def scenario():
        monkeypatch.setattr(sync, "startup_reconciler", None)
        monkeypatch.setattr(sync, "poller_task", asyncio.create_task(poller()))
        await asyncio.sleep(0)
        await sync.on_bot_stopping(SimpleNamespace())
        assert cancelled.is_set()
        assert sync.poller_task is None

    asyncio.run(scenario())


def test_maybe_user_gets_due_reminder_end_to_end_after_reopting_in(monkeypatch):
    """D007 end to end: the poller's response pre-filter must include "maybe", not
    just "in", or the schema helpers never see the row (builder-05 finding). A
    reschedule wipes the old response (D009), so the maybe user has to opt back in
    against the reposted panel before their reminder can fire again."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    response = schema.new_response_doc(old_event["uid"], 78, old_start, "v0", "maybe", reminders=[60])
    mongo = FakeMongo(events=[state], responses=[response])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)
    new_start = old_start + timedelta(hours=1)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))
    assert mongo.fwa_sync_responses.documents == {}  # wiped, no change alert either
    assert [d for d in _deliveries(mongo) if d["delivery_type"] == "change"] == []

    stored_event = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    asyncio.run(panel.upsert_response(mongo, moved["uid"], stored_event, 78, "maybe", [60]))

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(minutes=60)))
    reminders = [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"]
    assert [d["recipient_id"] for d in reminders] == [78]

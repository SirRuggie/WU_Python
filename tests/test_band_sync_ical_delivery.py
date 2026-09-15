import asyncio
import warnings
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.tasks import band_sync_ical as sync
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
    now = event["start"] - timedelta(hours=2)

    asyncio.run(sync.process_event(mongo, event, _config([1, 2]), now))

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


def test_stale_pending_lease_is_reclaimed(monkeypatch):
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    delivery = sync._delivery_doc(event, sync.DISCOVERY_OFFSET, 7)
    delivery.update({
        "status": "pending",
        "lease_until": datetime.now(timezone.utc) - timedelta(seconds=1),
    })
    mongo = FakeMongo(deliveries=[delivery])

    asyncio.run(sync.deliver_outstanding(mongo, event))

    assert mongo.fwa_sync_deliveries.documents[delivery["_id"]]["status"] == "sent"
    assert rest.attempts == [7]


def test_reschedule_change_alert_retries_after_a_transient_send_failure(monkeypatch):
    rest = FakeRest({9: 1})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_event = _event(start=datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc))
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    mongo = FakeMongo(events=[state])
    # A pure delivery-queue test - see test_partial_delivery_retries_only_failed_recipient.
    # 0, not None: normalize_config now treats a stored None as "not yet configured"
    # and falls back to NOTIFICATION_CHANNEL_ID (refuter-01 must-fix 3); 0 is the one
    # value post_or_replace_panel's `if not channel_id` still reads as "no panel".
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)
    moved = _event(start=old_event["start"] + timedelta(hours=1))
    now = moved["start"] - timedelta(hours=2)

    asyncio.run(sync.process_event(mongo, moved, _config([9]), now))

    state_after_failure = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    delivery = _deliveries(mongo)[0]
    assert sync.normalize_start(state_after_failure["start_at"]) == moved["start"]
    assert delivery["delivery_type"] == "change"
    assert delivery["status"] == "failed"
    assert rest.attempts == [9]

    asyncio.run(sync.process_event(
        mongo, moved, _config([9]), now + timedelta(minutes=5)
    ))

    assert mongo.fwa_sync_deliveries.documents[delivery["_id"]]["status"] == "sent"
    assert rest.attempts == [9, 9]


def test_reschedule_delivers_change_alert_and_rearms_matching_reminder_offset(monkeypatch):
    """refuter-01 bug 1+2 (test a): flag off, user 77 opted in with reminders=[60].
    Before the fix, change-alert recipients were computed via recipients_for_offset with
    key "change:<ver>", which never matches a numeric reminders list, so recipients came
    back empty, handle_reschedule returned False, and start_at never moved. Also proves
    the re-armed 60-min reminder only fires once it is actually due, not immediately."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    response = schema.new_response_doc(
        old_event["uid"], 77, old_start, "v0", "in", reminders=[60],
    )
    mongo = FakeMongo(events=[state], responses=[response])
    new_start = old_start + timedelta(hours=1)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))  # ~14:00

    stored = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert sync.normalize_start(stored["start_at"]) == new_start
    change_deliveries = [d for d in _deliveries(mongo) if d["delivery_type"] == "change"]
    assert len(change_deliveries) == 1
    assert change_deliveries[0]["recipient_id"] == 77
    assert change_deliveries[0]["status"] == "sent"
    assert [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"] == []

    asyncio.run(sync.process_event(  # 18:00, exactly 60 minutes before the new start
        mongo, moved, config, new_start - timedelta(minutes=60)
    ))

    reminder_deliveries = [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"]
    assert len(reminder_deliveries) == 1
    assert reminder_deliveries[0]["recipient_id"] == 77
    assert reminder_deliveries[0]["status"] == "sent"


def test_reschedule_change_alert_only_when_reminders_list_is_empty(monkeypatch):
    """Test b: same as above but the opted-in user chose no reminders. They still get
    the change alert (status=="in" is enough) but never a numeric reminder."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    response = schema.new_response_doc(old_event["uid"], 77, old_start, "v0", "in", reminders=[])
    mongo = FakeMongo(events=[state], responses=[response])
    new_start = old_start + timedelta(hours=1)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    change_deliveries = [d for d in _deliveries(mongo) if d["delivery_type"] == "change"]
    assert len(change_deliveries) == 1
    assert change_deliveries[0]["recipient_id"] == 77

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(minutes=60)))

    assert [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"] == []


def test_reschedule_legacy_broadcast_gets_change_alert_and_due_reminders(monkeypatch):
    """Test c: flag on, dm_user_ids=[9], no responses at all - legacy broadcast alone
    still gets both the change alert and, once due, the reminder."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    mongo = FakeMongo(events=[state])
    new_start = old_start + timedelta(hours=1)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [9], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": True}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    change_deliveries = [d for d in _deliveries(mongo) if d["delivery_type"] == "change"]
    assert len(change_deliveries) == 1
    assert change_deliveries[0]["recipient_id"] == 9
    assert [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"] == []

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(minutes=60)))

    reminder_deliveries = [d for d in _deliveries(mongo) if d["delivery_type"] == "reminder"]
    assert len(reminder_deliveries) == 1
    assert reminder_deliveries[0]["recipient_id"] == 9


def test_reschedule_with_no_legacy_broadcast_and_no_responses_updates_without_retry(monkeypatch):
    """Test d: flag off, no responses - nobody to tell is not a failure. start_at still
    updates and the next poll must not re-trigger a reschedule (no retry loop)."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    mongo = FakeMongo(events=[state])
    new_start = old_start + timedelta(hours=1)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    stored = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert sync.normalize_start(stored["start_at"]) == new_start
    assert _deliveries(mongo) == []

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(minutes=59)))

    stored_again = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert sync.normalize_start(stored_again["start_at"]) == new_start
    assert _deliveries(mongo) == []  # no change alert re-queued: detect_reschedule is False now


def test_reschedule_edits_the_existing_channel_panel_in_place(monkeypatch):
    """builder-06: after a reschedule the channel panel must show the new time without
    waiting for a button click. Before the fix, process_event only posts a panel when
    panel_message_id is unset (extensions/tasks/band_sync_ical.py:717), so a panel that
    already exists is left showing the old time - no edit, no repost."""
    rest = FakeRest()
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    state["panel_channel_id"] = 555
    state["panel_message_id"] = 111
    mongo = FakeMongo(events=[state])
    mongo.fwa_sync_config.documents["config"] = {"_id": "config", "current_panel": {
        "uid": old_event["uid"], "channel_id": 555, "message_id": 111,
    }}
    new_start = old_start + timedelta(hours=2)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    assert rest.edits == [(555, 111)]
    from utils.band_ical_parser import discord_timestamp
    new_tag = discord_timestamp(new_start, "F")
    values = _panel_texts(rest.edit_components[-1])
    # The channel panel carries no time at all (user rule 2026-09-15); the re-render
    # is proven by the edit itself and by panel_version catching up below.
    assert not any("**Sync Time:**" in value for value in values)
    assert not any(new_tag in value for value in values)
    assert 555 not in rest.attempts  # no new panel posted to the channel

    stored = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert stored["panel_channel_id"] == 555
    assert stored["panel_message_id"] == 111  # unchanged - the same message was edited
    assert stored["panel_version"] == stored["event_version"]
    current_panel = mongo.fwa_sync_config.documents["config"]["current_panel"]
    assert current_panel == {"uid": old_event["uid"], "channel_id": 555, "message_id": 111}


def test_reschedule_reposts_the_panel_once_if_it_was_hand_deleted(monkeypatch):
    """The NotFound repost path (D003) must still work when the reschedule is what
    triggers the refresh: edit_message raises NotFound, refresh_panel_message reposts
    once and current_panel is updated to the new message id."""
    rest = FakeRest({111: sync.hikari.NotFoundError("https://discord.test", {}, {}, "gone")})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    state["panel_channel_id"] = 555
    state["panel_message_id"] = 111
    mongo = FakeMongo(events=[state])
    mongo.fwa_sync_config.documents["config"] = {"_id": "config", "current_panel": {
        "uid": old_event["uid"], "channel_id": 555, "message_id": 111,
    }}
    new_start = old_start + timedelta(hours=2)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    assert rest.attempts.count(555) == 1  # reposted exactly once

    stored = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert stored["panel_channel_id"] == 555
    assert stored["panel_message_id"] != 111
    current_panel = mongo.fwa_sync_config.documents["config"]["current_panel"]
    assert current_panel["message_id"] == stored["panel_message_id"]


def test_reschedule_refresh_retries_on_next_poll_after_a_transient_edit_failure(monkeypatch):
    """refuter-06 must-fix: edit_message raising a non-NotFound error must not leave the
    panel stuck on the old time forever. panel_version stays behind event_version when
    the edit fails, so the very next poll retries the refresh - it does not depend on
    detect_reschedule firing again (which is False once start_at has already moved)."""
    rest = FakeRest({111: RuntimeError("temporary Discord failure")})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    old_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    old_event = _event(start=old_start)
    state = sync._event_state_doc(old_event, [sync.DISCOVERY_OFFSET])
    state["panel_channel_id"] = 555
    state["panel_message_id"] = 111
    state["panel_version"] = sync._event_version(old_event)
    response = schema.new_response_doc(old_event["uid"], 77, old_start, "v0", "in", reminders=[])
    mongo = FakeMongo(events=[state], responses=[response])
    mongo.fwa_sync_config.documents["config"] = {"_id": "config", "current_panel": {
        "uid": old_event["uid"], "channel_id": 555, "message_id": 111,
    }}
    new_start = old_start + timedelta(hours=2)
    moved = _event(start=new_start)
    config = {"dm_user_ids": [], "offsets": [60], "announce_on_discovery": True,
              "legacy_broadcast": False}

    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(hours=5)))

    stored = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert rest.edits == [(555, 111)]  # the failed attempt still happened
    assert sync.normalize_start(stored["start_at"]) == new_start  # reschedule still applied
    assert stored["panel_version"] != stored["event_version"]  # refresh failed, stays retryable
    change_deliveries = [d for d in _deliveries(mongo) if d["delivery_type"] == "change"]
    assert len(change_deliveries) == 1
    assert change_deliveries[0]["recipient_id"] == 77
    assert change_deliveries[0]["status"] == "sent"

    rest.failures = {}  # transient failure clears; the next poll's edit succeeds
    asyncio.run(sync.process_event(mongo, moved, config, new_start - timedelta(minutes=59)))

    stored_again = mongo.fwa_sync_events.documents[sync._event_state_id(moved["uid"])]
    assert rest.edits == [(555, 111), (555, 111)]
    assert stored_again["panel_version"] == stored_again["event_version"]
    from utils.band_ical_parser import discord_timestamp
    new_tag = discord_timestamp(new_start, "F")
    values = _panel_texts(rest.edit_components[-1])
    # The channel panel carries no time at all (user rule 2026-09-15); the re-render
    # is proven by the edit itself and by panel_version catching up below.
    assert not any("**Sync Time:**" in value for value in values)
    assert not any(new_tag in value for value in values)


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
    now = event["start"] - timedelta(hours=2)
    mongo = FakeMongo()
    # A pure delivery-queue test - see test_partial_delivery_retries_only_failed_recipient.
    # 0, not None: normalize_config now treats a stored None as "not yet configured"
    # and falls back to NOTIFICATION_CHANNEL_ID (refuter-01 must-fix 3); 0 is the one
    # value post_or_replace_panel's `if not channel_id` still reads as "no panel".
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=0)

    asyncio.run(sync.process_event(mongo, event, _config([7]), now))

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


def test_transient_dm_failure_stops_at_failure_limit(monkeypatch):
    rest = FakeRest({7: 1})
    monkeypatch.setattr(sync, "bot_instance", SimpleNamespace(rest=rest))
    event = _event()
    now = event["start"] - timedelta(hours=2)
    delivery = sync._delivery_doc(event, sync.DISCOVERY_OFFSET, 7)
    delivery.update({
        "status": "failed",
        "failure_count": sync.DELIVERY_MAX_FAILURES - 1,
        "first_failed_at": now - timedelta(hours=1),
        "next_attempt_at": now,
    })
    mongo = FakeMongo(deliveries=[delivery])

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
    delivery = sync._delivery_doc(event, sync.DISCOVERY_OFFSET, 7)
    delivery.update({
        "status": "failed",
        "failure_count": 1,
        "first_failed_at": now - sync.DELIVERY_MAX_AGE,
        "next_attempt_at": now,
    })
    mongo = FakeMongo(deliveries=[delivery])

    asyncio.run(sync.deliver_outstanding(mongo, event, now))

    stored = mongo.fwa_sync_deliveries.documents[delivery["_id"]]
    assert stored["status"] == "abandoned"
    assert stored["terminal_reason"] == "age_limit"


# ---- band_sync_schema.recipients_for_offset ----
def _response(user_id, status, reminders=()):
    return {"user_id": user_id, "status": status, "reminders": list(reminders)}


def test_recipients_for_offset_only_counts_opted_in_users_with_that_reminder():
    config = {"dm_user_ids": [], "legacy_broadcast": False}
    responses = [
        _response(1, "in", [60, 10]),
        _response(2, "maybe", [60]),   # maybe never counts, even with the offset chosen
        _response(3, "no", [60]),      # no never counts
        _response(4, "in", [10]),      # in, but this offset not chosen
    ]
    assert schema.recipients_for_offset(config, responses, 60) == [1]
    assert schema.recipients_for_offset(config, responses, 10) == [1, 4]


def test_recipients_for_offset_legacy_flag_gates_dm_user_ids():
    responses = [_response(1, "in", [60])]
    config_on = {"dm_user_ids": [1, 5], "legacy_broadcast": True}
    config_off = {"dm_user_ids": [1, 5], "legacy_broadcast": False}

    # legacy_broadcast True: response-based recipient 1 is not duplicated, 5 is added.
    assert schema.recipients_for_offset(config_on, responses, 60) == [1, 5]
    # legacy_broadcast False: only the opted-in response counts.
    assert schema.recipients_for_offset(config_off, responses, 60) == [1]


def test_recipients_for_offset_dedupes_and_ignores_invalid_ids():
    config = {"dm_user_ids": [0, -1, "not-a-number", 9, 9], "legacy_broadcast": True}
    assert schema.recipients_for_offset(config, [], 60) == [9]


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
    assert doc["dm_user_ids"] == [5, 6]
    assert doc["legacy_broadcast"] is False


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

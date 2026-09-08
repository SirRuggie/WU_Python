import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from extensions.commands.fwa import points as points_cmd
from extensions.tasks import fwa_points_monitor as monitor


class _PointsCollection:
    def __init__(self, *, find_result=None, find_error=None):
        self.find_result = find_result
        self.find_error = find_error
        self.updates = []

    async def find_one(self, *args, **kwargs):
        if self.find_error is not None:
            raise self.find_error
        return self.find_result

    async def update_one(self, query, update, **kwargs):
        self.updates.append((query, update, kwargs))


class _Mongo:
    def __init__(self, collection, clans=None):
        self.fwa_points = collection
        self.clans = clans


class _FindResult:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs)


class _ClansCollection:
    """Fake mongo.clans - only the find({"type": "FWA"}) shape is used."""

    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, *args, **kwargs):
        return _FindResult(self.docs)


OUR_PAGE_HTML = (
    '<p><b>Clan Name</b>: Edrag Rush<br>'
    '<b>Point Balance</b>: 5<br><br><b>Active FWA</b>: Yes<br></p>'
    '<p class="winner-box">Win Calculator for <a href="/war?id=300">War #300</a> in Sync #20<br><br>'
    'Edrag Rush (<a href="/clan?tag=2PPCL2GYP">2PPCL2GYP</a>) vs. Opponent Clan '
    '(<a href="/clan?tag=OPPONENT">OPPONENT</a>):<br><br>'
    '<b>Edrag Rush</b> should win by points (5 &gt; 3)</p>'
)


def test_retry_cooldown_applies_only_to_the_failed_war_key():
    now = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    record = {
        "last_attempt_status": "failed",
        "last_attempt_war_key": "OLD:20260804",
        "retry_after": (now + timedelta(minutes=30)).isoformat(),
    }

    assert monitor.retry_is_deferred(record, "OLD:20260804", now=now)
    assert not monitor.retry_is_deferred(record, "NEW:20260805", now=now)
    assert not monitor.retry_is_deferred(
        record,
        "OLD:20260804",
        now=now + timedelta(minutes=31),
    )


def test_caught_up_or_malformed_state_never_defers_retry():
    now = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    future = (now + timedelta(hours=1)).isoformat()

    assert not monitor.retry_is_deferred({
        "last_attempt_status": "caught_up",
        "last_attempt_war_key": "WAR",
        "retry_after": future,
    }, "WAR", now=now)
    assert not monitor.retry_is_deferred({
        "last_attempt_status": "error",
        "last_attempt_war_key": "WAR",
        "retry_after": "not-a-date",
    }, "WAR", now=now)


def test_terminal_failure_persists_war_key_and_cooldown(monkeypatch):
    collection = _PointsCollection(find_result=None)
    monkeypatch.setattr(monitor, "mongo_client", _Mongo(collection))
    monkeypatch.setattr(monitor, "bot_instance", None)
    monkeypatch.setattr(monitor, "MAX_CONSECUTIVE_FAILURES", 1)

    async def enabled():
        return True

    async def failed_fetch(_tag):
        return None

    monkeypatch.setattr(monitor, "feature_enabled", enabled)
    monkeypatch.setattr(monitor, "fetch_points_html", failed_fetch)

    asyncio.run(monitor.run_catchup(
        {"tag": "#2PPCL2GYP", "name": "Edrag Rush"},
        "OPPONENT",
        "OPPONENT:WAR-1",
    ))

    assert len(collection.updates) == 1
    query, update, kwargs = collection.updates[0]
    fields = update["$set"]
    assert query == {"_id": "2PPCL2GYP"}
    assert kwargs == {"upsert": True}
    assert fields["status"] == "failed"
    assert fields["last_attempt_status"] == "failed"
    assert fields["last_attempt_war_key"] == "OPPONENT:WAR-1"
    assert datetime.fromisoformat(fields["retry_after"]) > datetime.fromisoformat(fields["last_attempt_at"])


def test_unexpected_catchup_error_is_recorded(monkeypatch):
    collection = _PointsCollection(find_result=None)
    monkeypatch.setattr(monitor, "mongo_client", _Mongo(collection))
    monkeypatch.setattr(monitor, "bot_instance", None)

    async def unexpected():
        raise RuntimeError("boom")

    monkeypatch.setattr(monitor, "feature_enabled", unexpected)

    asyncio.run(monitor.run_catchup(
        {"tag": "#2PPCL2GYP", "name": "Edrag Rush"},
        "OPPONENT",
        "OPPONENT:WAR-2",
    ))

    fields = collection.updates[0][1]["$set"]
    assert fields["status"] == "error"
    assert fields["last_attempt_war_key"] == "OPPONENT:WAR-2"
    assert "RuntimeError: boom" in fields["last_attempt_error"]


def test_effective_watch_list_merges_clan_type_and_extras_deduped(monkeypatch):
    clans_collection = _ClansCollection([
        {"tag": "#2PPCL2GYP", "name": "Edrag Rush", "type": "FWA"},
        {"tag": "#R80L8VYG", "name": "Other FWA Clan", "type": "FWA"},
    ])
    monkeypatch.setattr(
        monitor, "mongo_client", _Mongo(_PointsCollection(), clans_collection)
    )

    config = {
        "enabled": True,
        "watch_list": [
            {"tag": "#EXTRA1", "name": "Extra One"},
            # Same tag as a clan-type entry - the clan-type name must win.
            {"tag": "2PPCL2GYP", "name": "Stale Extra Name"},
        ],
    }

    result = asyncio.run(monitor.effective_watch_list(config))
    by_tag = {c["tag"]: c for c in result}

    assert set(by_tag) == {"2PPCL2GYP", "R80L8VYG", "EXTRA1"}
    assert by_tag["2PPCL2GYP"]["name"] == "Edrag Rush"
    assert by_tag["2PPCL2GYP"]["source"] == "clan_type"
    assert by_tag["R80L8VYG"]["source"] == "clan_type"
    assert by_tag["EXTRA1"]["source"] == "extra"
    assert by_tag["EXTRA1"]["name"] == "Extra One"


def test_opponent_fetch_failure_stores_none_and_does_not_fail_catchup(monkeypatch):
    points_collection = _PointsCollection(find_result=None)
    monkeypatch.setattr(monitor, "mongo_client", _Mongo(points_collection))
    monkeypatch.setattr(monitor, "bot_instance", None)

    async def enabled():
        return True

    async def fake_fetch(tag):
        if tag == "2PPCL2GYP":
            return OUR_PAGE_HTML
        return None  # opponent page fetch fails

    monkeypatch.setattr(monitor, "feature_enabled", enabled)
    monkeypatch.setattr(monitor, "fetch_points_html", fake_fetch)

    asyncio.run(monitor.run_catchup(
        {"tag": "#2PPCL2GYP", "name": "Edrag Rush"},
        "OPPONENT",
        "OPPONENT:WAR-3",
        "2026-09-15T12:00:00",
    ))

    assert len(points_collection.updates) == 1
    query, update, kwargs = points_collection.updates[0]
    fields = update["$set"]
    assert query == {"_id": "2PPCL2GYP"}
    assert kwargs == {"upsert": True}
    assert fields["status"] == "caught_up"
    assert fields["opponent_active_fwa"] is None


def test_store_record_captures_opponent_active_fwa_and_end_time(monkeypatch):
    points_collection = _PointsCollection(find_result=None)
    monkeypatch.setattr(monitor, "mongo_client", _Mongo(points_collection))
    monkeypatch.setattr(monitor, "bot_instance", None)

    async def enabled():
        return True

    opponent_page_html = '<p><b>Active FWA</b>: No<br></p>'

    async def fake_fetch(tag):
        if tag == "2PPCL2GYP":
            return OUR_PAGE_HTML
        if tag == "OPPONENT":
            return opponent_page_html
        return None

    monkeypatch.setattr(monitor, "feature_enabled", enabled)
    monkeypatch.setattr(monitor, "fetch_points_html", fake_fetch)

    asyncio.run(monitor.run_catchup(
        {"tag": "#2PPCL2GYP", "name": "Edrag Rush"},
        "OPPONENT",
        "OPPONENT:WAR-4",
        "2026-09-20T08:00:00",
    ))

    fields = points_collection.updates[0][1]["$set"]
    assert fields["opponent_active_fwa"] is False
    assert fields["coc_war_end_time"] == "2026-09-20T08:00:00"
    assert fields["sync_number"] == 20
    assert fields["war_number"] == 300
    assert fields["our_outcome"] == "win"
    assert fields["predicted_winner_name"] == "Edrag Rush"
    assert fields["opponent_name"] == "Opponent Clan"


def test_watch_add_pipeline_replaces_in_one_atomic_update():
    pipeline = monitor.watch_list_replacement_pipeline("ABC123", "Replacement")

    assert len(pipeline) == 1
    expression = pipeline[0]["$set"]["watch_list"]["$concatArrays"]
    assert expression[0]["$filter"]["cond"] == {"$ne": ["$$clan.tag", "ABC123"]}
    assert expression[1] == [{"tag": "ABC123", "name": "Replacement"}]


def test_startup_recovers_from_mongo_failure_and_starts_one_detector(monkeypatch):
    class FlakyCollection(_PointsCollection):
        def __init__(self):
            super().__init__(find_result={"_id": "config", "enabled": False})
            self.failures = 1

        async def find_one(self, *args, **kwargs):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("Mongo starting")
            return await super().find_one(*args, **kwargs)

    collection = FlakyCollection()
    loop_started = asyncio.Event()
    loop_calls = 0

    async def fake_detector():
        nonlocal loop_calls
        loop_calls += 1
        loop_started.set()
        await asyncio.Event().wait()

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(monitor, "mongo_client", _Mongo(collection))
    monkeypatch.setattr(monitor, "detector_task", None)
    monkeypatch.setattr(monitor, "detector_loop", fake_detector)

    reconciler = monitor.StartupReconciler(
        "points_test",
        monitor._reconcile_points_startup,
        retry_delays=(0,),
        sleep=no_wait,
    )

    async def scenario():
        await reconciler.start()
        await loop_started.wait()
        await monitor._reconcile_points_startup()
        assert monitor.detector_task and not monitor.detector_task.done()
        monitor.detector_task.cancel()
        await asyncio.gather(monitor.detector_task, return_exceptions=True)
        monitor.detector_task = None

    asyncio.run(scenario())

    assert reconciler.health.state == "healthy"
    assert reconciler.health.attempts == 2
    assert loop_calls == 1


# ---------------------------------------------------------------------------
# /fwa points must reflect effective_watch_list(), not config.watch_list alone
# ---------------------------------------------------------------------------

def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _payload_text(payload) -> str:
    return "\n".join(
        str(node.get("content", ""))
        for node in _walk(payload)
        if "content" in node
    )


class _FwaPointsConfigCollection(_PointsCollection):
    """Fake mongo.fwa_points: the config doc, then no stored verdict for any tag."""

    def __init__(self, config):
        super().__init__(find_result=None)
        self._config = config

    async def find_one(self, query, *args, **kwargs):
        if query == {"_id": "config"}:
            return self._config
        return None


class _PointsContext:
    def __init__(self):
        self.responses = []

    async def defer(self, **kwargs):
        pass

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


def test_fwa_points_command_lists_fwa_clans_when_config_watch_list_is_empty(monkeypatch):
    clans_collection = _ClansCollection([
        {"tag": "#2PPCL2GYP", "name": "Edrag Rush", "type": "FWA"},
    ])
    # effective_watch_list() reads mongo.clans off the monitor module's own
    # global, which is what makes this the regression: /fwa points must go
    # through that function rather than trusting config.watch_list alone.
    monkeypatch.setattr(monitor, "mongo_client", _Mongo(_PointsCollection(), clans_collection))

    fwa_points = _FwaPointsConfigCollection({"_id": "config", "watch_list": []})
    mongo = _Mongo(fwa_points, clans_collection)

    ctx = _PointsContext()
    asyncio.run(points_cmd.Points().invoke(ctx, mongo=mongo))

    assert len(ctx.responses) == 1
    payload = [component.build() for component in ctx.responses[0][1]["components"]]
    text = _payload_text(payload)

    assert "Edrag Rush" in text
    assert "No clans are being watched yet." not in text


# ---------------------------------------------------------------------------
# Catch-up stagger: same-pass clans must not retry in lockstep
# ---------------------------------------------------------------------------

def test_run_catchup_sleeps_the_computed_stagger_before_first_fetch(monkeypatch):
    collection = _PointsCollection(find_result=None)
    monkeypatch.setattr(monitor, "mongo_client", _Mongo(collection))
    monkeypatch.setattr(monitor, "bot_instance", None)

    async def enabled():
        return True

    async def failed_fetch(_tag):
        return None

    monkeypatch.setattr(monitor, "feature_enabled", enabled)
    monkeypatch.setattr(monitor, "fetch_points_html", failed_fetch)
    monkeypatch.setattr(monitor, "MAX_CONSECUTIVE_FAILURES", 1)

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with patch.object(monitor.asyncio, "sleep", fake_sleep):
        asyncio.run(monitor.run_catchup(
            {"tag": "#2PPCL2GYP", "name": "Edrag Rush"},
            "OPPONENT", "OPPONENT:WAR-5",
            stagger_seconds=12.5,
        ))

    assert sleeps == [12.5]


def test_run_catchup_skips_the_sleep_when_stagger_is_zero(monkeypatch):
    collection = _PointsCollection(find_result=None)
    monkeypatch.setattr(monitor, "mongo_client", _Mongo(collection))
    monkeypatch.setattr(monitor, "bot_instance", None)

    async def enabled():
        return True

    async def failed_fetch(_tag):
        return None

    monkeypatch.setattr(monitor, "feature_enabled", enabled)
    monkeypatch.setattr(monitor, "fetch_points_html", failed_fetch)
    monkeypatch.setattr(monitor, "MAX_CONSECUTIVE_FAILURES", 1)

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with patch.object(monitor.asyncio, "sleep", fake_sleep):
        asyncio.run(monitor.run_catchup(
            {"tag": "#2PPCL2GYP", "name": "Edrag Rush"},
            "OPPONENT", "OPPONENT:WAR-6",
        ))

    # Single-attempt failure (MAX_CONSECUTIVE_FAILURES=1) returns before the
    # retry-interval sleep, so a zero stagger means no sleep call at all.
    assert sleeps == []

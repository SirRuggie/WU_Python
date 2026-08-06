import asyncio
from datetime import datetime, timedelta, timezone

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
    def __init__(self, collection):
        self.fwa_points = collection


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

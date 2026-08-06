import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.tasks import band_monitor


class _Collection:
    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint
        self.updates = []

    async def find_one(self, query):
        return self.checkpoint

    async def update_one(self, query, update, **kwargs):
        self.updates.append((query, update, kwargs))
        self.checkpoint = {"post_key": update["$set"]["post_key"]}


class _Mongo:
    def __init__(self, checkpoint=None):
        self.fwa_band_data = _Collection(checkpoint)


def _post(key, content="ordinary post"):
    return {"post_key": key, "content": content}


def test_posts_after_checkpoint_processes_every_unseen_post_oldest_first():
    posts = [_post("newest"), _post("middle"), _post("known")]

    result = band_monitor.posts_after_checkpoint(posts, "known")

    assert [post["post_key"] for post in result] == ["middle", "newest"]


def test_first_poll_checkpoints_only_the_latest_post():
    result = band_monitor.posts_after_checkpoint(
        [_post("newest"), _post("older")], None
    )

    assert [post["post_key"] for post in result] == ["newest"]


def test_first_poll_does_not_replay_latest_sync_post(monkeypatch):
    mongo = _Mongo()

    async def stale_delivery(_post):
        raise AssertionError("first poll must establish a baseline without delivery")

    monkeypatch.setattr(band_monitor, "send_war_sync_to_discord", stale_delivery)

    processed = asyncio.run(band_monitor.process_band_posts(
        mongo,
        [_post("newest", band_monitor.WAR_SYNC_MARKER), _post("older")],
    ))

    assert processed == 1
    assert mongo.fwa_band_data.checkpoint == {"post_key": "newest"}


def test_missing_checkpoint_boundary_does_not_replay_unknown_history(monkeypatch):
    mongo = _Mongo({"post_key": "fallen-out-of-feed"})

    async def stale_delivery(_post):
        raise AssertionError("unknown feed history must not be replayed")

    monkeypatch.setattr(band_monitor, "send_war_sync_to_discord", stale_delivery)
    processed = asyncio.run(band_monitor.process_band_posts(
        mongo,
        [_post("newest", band_monitor.WAR_SYNC_MARKER), _post("older")],
    ))

    assert processed == 1
    assert mongo.fwa_band_data.checkpoint == {"post_key": "newest"}


def test_failed_sync_delivery_does_not_advance_checkpoint(monkeypatch):
    mongo = _Mongo({"post_key": "known"})

    async def failed_delivery(_post):
        return False

    monkeypatch.setattr(band_monitor, "send_war_sync_to_discord", failed_delivery)
    processed = asyncio.run(band_monitor.process_band_posts(
        mongo,
        [
            _post("newest"),
            _post("sync", band_monitor.WAR_SYNC_MARKER),
            _post("known"),
        ],
    ))

    assert processed == 0
    assert mongo.fwa_band_data.updates == []
    assert mongo.fwa_band_data.checkpoint == {"post_key": "known"}


def test_checkpoint_advances_through_nonmatching_posts(monkeypatch):
    mongo = _Mongo({"post_key": "known"})

    async def unexpected_delivery(_post):
        raise AssertionError("ordinary posts must not send a Discord notification")

    monkeypatch.setattr(band_monitor, "send_war_sync_to_discord", unexpected_delivery)
    processed = asyncio.run(band_monitor.process_band_posts(
        mongo,
        [_post("newest"), _post("middle"), _post("known")],
    ))

    assert processed == 2
    assert [update[1]["$set"]["post_key"] for update in mongo.fwa_band_data.updates] == [
        "middle",
        "newest",
    ]


def test_sync_delivery_builds_and_sends_components(monkeypatch):
    class _Rest:
        def __init__(self):
            self.calls = []

        async def create_message(self, **kwargs):
            self.calls.append(kwargs)

    class _Bot:
        rest = _Rest()

    bot = _Bot()
    monkeypatch.setattr(band_monitor, "bot_instance", bot)

    delivered = asyncio.run(band_monitor.send_war_sync_to_discord(_post("sync")))

    assert delivered is True
    assert len(bot.rest.calls) == 1
    assert bot.rest.calls[0]["channel"] == band_monitor.NOTIFICATION_CHANNEL_ID
    assert bot.rest.calls[0]["components"]


def test_startup_recovers_key_and_creates_one_monitor_task(monkeypatch):
    class StartupCollection:
        def __init__(self):
            self.index_calls = 0

        async def create_index(self, *args, **kwargs):
            self.index_calls += 1
            return "ttl_expire_at"

    mongo = SimpleNamespace(fwa_band_data=StartupCollection())
    resolver_calls = 0
    loop_calls = 0
    loop_started = asyncio.Event()

    async def flaky_resolver():
        nonlocal resolver_calls
        resolver_calls += 1
        if resolver_calls < 3:
            raise RuntimeError("BAND API starting")
        monkeypatch.setattr(band_monitor, "BAND_KEY", "resolved")
        return True

    async def fake_loop(_mongo):
        nonlocal loop_calls
        loop_calls += 1
        loop_started.set()
        await asyncio.Event().wait()

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(band_monitor, "mongo_client", mongo)
    monkeypatch.setattr(band_monitor, "band_check_task", None)
    monkeypatch.setattr(band_monitor, "resolve_band_key", flaky_resolver)
    monkeypatch.setattr(band_monitor, "band_checker_loop", fake_loop)

    reconciler = band_monitor.StartupReconciler(
        "band_test",
        band_monitor._reconcile_band_startup,
        retry_delays=(0,),
        sleep=no_wait,
    )

    async def scenario():
        await reconciler.start()
        await loop_started.wait()
        await band_monitor._reconcile_band_startup()
        assert band_monitor.band_check_task and not band_monitor.band_check_task.done()
        band_monitor.band_check_task.cancel()
        await asyncio.gather(band_monitor.band_check_task, return_exceptions=True)
        band_monitor.band_check_task = None

    asyncio.run(scenario())

    assert reconciler.health.state == "healthy"
    assert reconciler.health.attempts == 3
    assert resolver_calls == 3
    assert loop_calls == 1
    assert mongo.fwa_band_data.index_calls == 1


def test_poll_failures_are_visible_throttled_and_log_recovery(monkeypatch, capsys):
    results = iter([
        None,
        None,
        {"result_code": 1, "result_data": {"items": []}},
    ])

    async def fetch():
        return next(results)

    monkeypatch.setattr(band_monitor, "fetch_band_posts", fetch)
    monkeypatch.setattr(band_monitor, "poll_health", band_monitor.BandPollHealth())

    async def scenario():
        assert await band_monitor.check_band_once(object()) is False
        assert await band_monitor.check_band_once(object()) is False
        assert await band_monitor.check_band_once(object()) is True

    asyncio.run(scenario())

    output = capsys.readouterr().out
    assert output.count("monitor_poll_failed") == 1
    assert output.count("monitor_poll_recovered") == 1
    assert band_monitor.poll_health.state == "healthy"
    assert band_monitor.poll_health.last_success_at is not None


def test_invalid_runtime_band_key_is_resolved_on_next_poll(monkeypatch):
    results = iter([
        {"result_code": -102, "result_msg": "invalid band key"},
        {"result_code": 1, "result_data": {"items": []}},
    ])
    resolver_calls = 0

    async def fetch():
        return next(results)

    async def resolve():
        nonlocal resolver_calls
        resolver_calls += 1
        monkeypatch.setattr(band_monitor, "BAND_KEY", "fresh-key")
        return True

    monkeypatch.setattr(band_monitor, "BAND_KEY", "stale-key")
    monkeypatch.setattr(band_monitor, "fetch_band_posts", fetch)
    monkeypatch.setattr(band_monitor, "resolve_band_key", resolve)
    monkeypatch.setattr(band_monitor, "poll_health", band_monitor.BandPollHealth())

    async def scenario():
        assert await band_monitor.check_band_once(object()) is False
        assert band_monitor.BAND_KEY is None
        assert await band_monitor.check_band_once(object()) is True

    asyncio.run(scenario())

    assert resolver_calls == 1
    assert band_monitor.BAND_KEY == "fresh-key"


def test_poll_does_not_call_api_when_key_resolution_returns_no_key(monkeypatch):
    fetch_calls = 0

    async def resolve():
        return False

    async def fetch():
        nonlocal fetch_calls
        fetch_calls += 1
        return {"result_code": 1, "result_data": {"items": []}}

    monkeypatch.setattr(band_monitor, "BAND_KEY", None)
    monkeypatch.setattr(band_monitor, "resolve_band_key", resolve)
    monkeypatch.setattr(band_monitor, "fetch_band_posts", fetch)

    async def scenario():
        try:
            await band_monitor.check_band_once(object())
        except band_monitor.BandKeyResolutionError:
            return
        raise AssertionError("missing BAND key was accepted")

    asyncio.run(scenario())

    assert fetch_calls == 0


def test_unchanged_poll_failure_relogs_after_one_hour(monkeypatch, capsys):
    start = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(band_monitor, "poll_health", band_monitor.BandPollHealth())

    band_monitor._record_poll_failure("band_request_failed", start)
    band_monitor._record_poll_failure(
        "band_request_failed",
        start + timedelta(minutes=59),
    )
    band_monitor._record_poll_failure(
        "band_request_failed",
        start + timedelta(hours=1),
    )

    assert capsys.readouterr().out.count("monitor_poll_failed") == 2


def test_shutdown_awaits_band_monitor_task(monkeypatch):
    cancelled = asyncio.Event()

    async def monitor_task():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def scenario():
        monkeypatch.setattr(band_monitor, "startup_reconciler", None)
        monkeypatch.setattr(
            band_monitor,
            "band_check_task",
            asyncio.create_task(monitor_task()),
        )
        monkeypatch.setattr(band_monitor, "poll_health", band_monitor.BandPollHealth())
        await asyncio.sleep(0)
        await band_monitor.on_bot_stopping(SimpleNamespace())
        assert cancelled.is_set()
        assert band_monitor.band_check_task is None

    asyncio.run(scenario())

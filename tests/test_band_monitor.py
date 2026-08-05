import asyncio

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

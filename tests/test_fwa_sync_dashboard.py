"""Private sync controls: read-only feed checks and explicit test DMs."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import fwa_sync_dashboard as dashboard
from extensions.tasks import band_sync_ical as sync


def run(coroutine):
    return asyncio.run(coroutine)


def built(components):
    return str([part.build() for part in components])


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row
        return iterate()


class Config:
    def __init__(self):
        self.value = {
            "enabled": False, "panel_channel_id": 333,
            "band_url": "https://www.band.us/band/123", "offsets": [60, 10, 0],
            "announce_on_discovery": True, "summary_filter": "sync",
        }
        self.updates = []

    async def update_one(self, key, change, upsert=False):
        assert key == {"_id": sync.CONFIG_ID}
        self.updates.append(change)
        self.value.update(change["$set"])


class Deliveries:
    def __init__(self):
        self.rows = [
            {"calendar": "Sync", "offset": "60", "status": "sent", "start_at": "one"},
            {"calendar": "Sync", "offset": "60", "status": "sent", "start_at": "one"},
            {"calendar": "Sync2", "offset": "10", "status": "abandoned",
             "terminal_reason": "DM closed", "start_at": "two"},
        ]

    def find(self, query, *_args):
        rows = self.rows
        if query.get("status") == "abandoned":
            rows = [row for row in rows if row["status"] == "abandoned"]
        return Cursor(list(rows))


def fixture(monkeypatch):
    config = Config()
    mongo = SimpleNamespace(fwa_sync_config=config, fwa_sync_deliveries=Deliveries())
    states = {}

    async def insert_state(_mongo, state, ttl=None):
        assert state["_id"] not in states
        states[state["_id"]] = state

    async def get_state(_mongo, sid):
        return states.get(sid)

    async def load_config(_mongo):
        return config.value

    monkeypatch.setattr(dashboard, "insert_state", insert_state)
    monkeypatch.setattr(dashboard, "get_state", get_state)
    monkeypatch.setattr(sync, "load_config", load_config)
    monkeypatch.setattr(sync, "feed_urls", lambda: {"Sync": "secret", "Sync2": "secret2"})
    monkeypatch.setattr(sync, "poller_task", None)
    monkeypatch.setattr(sync, "startup_reconciler", None)
    member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
    bot = SimpleNamespace(rest=SimpleNamespace(fetch_channel=AsyncMock()))
    interaction = SimpleNamespace(guild_id=100, member=member, app=bot, values=(),
                                  components=(), message=None,
                                  edit_initial_response=AsyncMock(),
                                  create_initial_response=AsyncMock())
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), member=member,
                          interaction=interaction, defer=AsyncMock(),
                          respond=AsyncMock(), respond_with_modal=AsyncMock())
    state = {"_id": "start", "user_id": 1, "guild_id": 100, "manage_token": "home"}
    states["start"] = state
    return SimpleNamespace(mongo=mongo, ctx=ctx, states=states, state=state)


def test_private_status_names_only_and_fixed_timing(monkeypatch):
    env = fixture(monkeypatch)
    output = run(dashboard._panel(env.mongo, env.state))
    text = built(output)
    assert "Sync, Sync2" in text and "secret" not in text
    assert "1 hour before" in text and "At sync time" in text and "Scheduler offsets" not in text
    assert "fwa_sync_offsets:" not in text
    assert "DM closed" in text and "Recent failures" in text
    assert text.count("Sync · 60 · sent") == 1  # duplicate recipient row collapsed
    assert "manage_fwa:home" in text
    assert len(output[0].build()[0]["components"]) <= 40


def test_owner_guild_admin_checked_before_mutations(monkeypatch):
    env = fixture(monkeypatch)
    env.ctx.user.id = 2
    assert "Open your own" in built(run(dashboard.toggle(env.ctx, "start|on", mongo=env.mongo)))
    env.ctx.user.id = 1
    env.ctx.interaction.guild_id = 101
    assert "Open your own" in built(run(dashboard.toggle(env.ctx, "start|on", mongo=env.mongo)))
    env.ctx.interaction.guild_id = 100
    env.ctx.member.permissions = hikari.Permissions.NONE
    assert "Administrator" in built(run(dashboard.toggle(env.ctx, "start|on", mongo=env.mongo)))
    assert not env.mongo.fwa_sync_config.updates


def test_enable_disable_persists_and_open_does_not_poll_or_send(monkeypatch):
    env = fixture(monkeypatch)
    collect = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(sync, "collect_events", collect)
    monkeypatch.setattr(sync, "dm_all", send)
    run(dashboard.open_dashboard(env.ctx, env.mongo, manage_token="home"))
    collect.assert_not_awaited()
    send.assert_not_awaited()
    assert env.ctx.defer.await_count == 1
    assert env.ctx.interaction.edit_initial_response.await_args.kwargs["user_mentions"] is False
    run(dashboard.toggle(env.ctx, "start|on", mongo=env.mongo))
    assert env.mongo.fwa_sync_config.value["enabled"] is True
    run(dashboard.toggle(env.ctx, "start|off", mongo=env.mongo))
    assert env.mongo.fwa_sync_config.value["enabled"] is False
    collect.assert_not_awaited()
    send.assert_not_awaited()


def test_feed_check_is_dry_run_and_test_dm_is_explicit(monkeypatch):
    env = fixture(monkeypatch)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    event = {"calendar": "Sync", "start": now, "end": now + timedelta(minutes=30),
             "summary": "Tie Breaker Sync"}
    collect = AsyncMock(return_value=([event], []))
    send = AsyncMock(return_value=1)
    embed = object()
    build_embed = lambda _event, _offset: embed
    monkeypatch.setattr(sync, "collect_events", collect)
    monkeypatch.setattr(sync, "dm_all", send)
    monkeypatch.setattr(sync, "build_embed", build_embed)
    dry = run(dashboard.check(env.ctx, "start", mongo=env.mongo))
    assert "No DMs sent" in built(dry)
    send.assert_not_awaited()
    assert not env.mongo.fwa_sync_config.updates
    tested = run(dashboard.test_dm(env.ctx, "start", mongo=env.mongo))
    send.assert_awaited_once_with([1], embed)
    assert "Test DM sent" in built(tested)
    assert not env.mongo.fwa_sync_config.updates


def test_channel_select_checks_guild_type_and_bot_permissions(monkeypatch):
    from extensions.commands import content
    env = fixture(monkeypatch)
    env.ctx.interaction.values = (777,)
    target = SimpleNamespace(guild_id=100, type=hikari.ChannelType.GUILD_TEXT,
                             permission_overwrites={})
    env.ctx.interaction.app.rest.fetch_channel.return_value = target
    perms = (hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
             | hikari.Permissions.EMBED_LINKS)
    allowed = AsyncMock(return_value=perms)
    monkeypatch.setattr(content, "destination_permissions", allowed)
    run(dashboard.channel(env.ctx, "start", mongo=env.mongo))
    assert env.mongo.fwa_sync_config.value["panel_channel_id"] == 777
    target.guild_id = 101
    env.ctx.interaction.values = (778,)
    denied = run(dashboard.channel(env.ctx, "start", mongo=env.mongo))
    assert "this server" in built(denied)
    assert env.mongo.fwa_sync_config.value["panel_channel_id"] == 777
    target.guild_id = 100
    allowed.return_value = hikari.Permissions.VIEW_CHANNEL
    denied = run(dashboard.channel(env.ctx, "start", mongo=env.mongo))
    assert "Embed Links" in built(denied)
    assert env.mongo.fwa_sync_config.value["panel_channel_id"] == 777


def test_band_url_modal_validates_public_http_and_rejects_private(monkeypatch):
    env = fixture(monkeypatch)
    run(dashboard.url_modal(env.ctx, "start", mongo=env.mongo))
    assert env.ctx.respond_with_modal.await_args.kwargs["custom_id"] == "fwa_sync_url_submit:start"
    assert not dashboard._valid_public_url("http://localhost/sync")
    assert not dashboard._valid_public_url("https://127.0.0.1/sync")
    assert dashboard._valid_public_url("https://www.band.us/band/123")
    env.ctx.interaction.components = [[SimpleNamespace(custom_id="url", value="https://www.band.us/band/456")]]
    run(dashboard.url_submit(env.ctx, "start", mongo=env.mongo))
    assert env.mongo.fwa_sync_config.value["band_url"] == "https://www.band.us/band/456"
    assert env.ctx.interaction.edit_initial_response.await_args.kwargs["role_mentions"] is False


def test_status_handles_unconfigured_channel_and_zero_minute_delivery(monkeypatch):
    env = fixture(monkeypatch)
    env.mongo.fwa_sync_config.value["panel_channel_id"] = 0
    env.mongo.fwa_sync_deliveries.rows = [
        {"calendar": "Sync3", "offset": 0, "status": "sent", "start_at": "now"}
    ]
    response = run(dashboard._panel(env.mongo, env.state))
    text = built(response)
    assert "Panel channel:** Not configured" in text
    assert "Sync3 · 0 · sent" in text
    assert "<#0>" not in text


def test_feed_check_result_is_bounded_under_discord_limits(monkeypatch):
    env = fixture(monkeypatch)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    events = [{"calendar": "C" * 200, "start": now,
               "summary": "S" * 600} for _ in range(30)]
    errors = ["E" * 500 for _ in range(20)]
    result = dashboard._check_panel(env.state, events, errors)[0].build()[0]
    texts = [part["content"] for part in result["components"]
             if part["type"] == hikari.ComponentType.TEXT_DISPLAY]
    assert len(result["components"]) <= 40
    assert all(len(item) <= 2000 for item in texts)
    assert sum(map(len, texts)) <= 4000
    assert len([item for item in texts if "<t:" in item]) == 10

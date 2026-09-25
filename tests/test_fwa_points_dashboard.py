"""Private FWA points controls and their monitor side effects."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import fwa_points_dashboard as dashboard
from extensions.tasks import fwa_points_monitor as monitor


def run(coroutine):
    return asyncio.run(coroutine)


def built(components):
    return str([component.build() for component in components])


class Collection:
    def __init__(self):
        self.config = {"_id": "config", "enabled": True,
                       "watch_list": [{"tag": "EXTRA1", "name": "Extra One"}]}
        self.records = {"AUTO1": {"raw_verdict": "Win", "war_number": 4,
                                  "sync_number": 7, "point_balance": 0,
                                  "scraped_at": "2026-09-25T12:00:00+00:00"}}
        self.updates = []

    async def find_one(self, query, projection=None):
        return self.config if query["_id"] == "config" else self.records.get(query["_id"])

    async def update_one(self, query, update, upsert=False):
        assert query["_id"] == "config"
        self.updates.append(update)
        if isinstance(update, list):
            expression = update[0]["$set"]["watch_list"]["$concatArrays"][-1][0]
            self.config["watch_list"] = [item for item in self.config["watch_list"]
                                         if item["tag"] != expression["tag"]] + [expression]
        elif "$pull" in update:
            tag = update["$pull"]["watch_list"]["tag"]
            self.config["watch_list"] = [item for item in self.config["watch_list"]
                                         if item["tag"] != tag]
        else:
            self.config.update(update["$set"])


class ClanCollection:
    def __init__(self, clans):
        self.clans = clans

    def find(self, query):
        assert query == {"type": "FWA"}
        return self

    async def to_list(self, length=None):
        return self.clans


def fixture(monkeypatch, *, automatic=1):
    mongo = SimpleNamespace(fwa_points=Collection(), clans=ClanCollection([
        {"type": "FWA", "tag": f"AUTO{i + 1}", "name": f"Auto {i + 1}"}
        for i in range(automatic)
    ]))
    states = {}

    async def insert_state(_mongo, state, ttl=None):
        assert state["_id"] not in states
        states[state["_id"]] = state

    async def get_state(_mongo, token):
        return states.get(token)

    monkeypatch.setattr(dashboard, "insert_state", insert_state)
    monkeypatch.setattr(dashboard, "get_state", get_state)
    monkeypatch.setattr(monitor, "detector_task", None)
    monkeypatch.setattr(monitor, "startup_reconciler", None)
    monkeypatch.setattr(monitor, "active_catchups", {})
    member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
    interaction = SimpleNamespace(guild_id=100, member=member, values=(),
                                  components=(), message=None,
                                  edit_initial_response=AsyncMock(),
                                  create_initial_response=AsyncMock())
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), member=member,
                          interaction=interaction, defer=AsyncMock(),
                          respond=AsyncMock(), respond_with_modal=AsyncMock())
    state = {"_id": "start", "user_id": 1, "guild_id": 100,
             "manage_token": "home", "page": 0}
    states["start"] = state
    return SimpleNamespace(mongo=mongo, ctx=ctx, states=states, state=state)


def test_monitor_loader_keeps_lifecycle_without_public_slash_group():
    assert not any(hasattr(item, "_command") for item in monitor.loader._loadables)
    assert sum(type(item).__name__ == "_ListenerLoadable" for item in monitor.loader._loadables) == 2


def test_status_effective_watch_rows_and_private_navigation(monkeypatch):
    env = fixture(monkeypatch)
    response = run(dashboard._panel(env.mongo, env.state))
    content = built(response)
    assert "Enabled" in content and "Not running" in content
    assert "Automatic FWA" in content and "Extra" in content
    assert "Win" in content and "War #4" in content
    assert "Sync #7" in content and "Balance 0" in content
    assert "<t:1790337600:R>" in content
    assert "https://points.fwafarm.com/clan?tag=AUTO1" in content
    assert "manage_fwa:home" in content and "manage_home:home" in content
    assert len(response[0].build()[0]["components"]) <= 40


def test_private_admin_gate_on_every_mutation(monkeypatch):
    env = fixture(monkeypatch)
    env.ctx.user.id = 2
    denied = run(dashboard.toggle(env.ctx, "start|off", mongo=env.mongo))
    assert "Open your own" in built(denied)
    env.ctx.user.id = 1
    env.ctx.interaction.guild_id = 101
    denied = run(dashboard.remove(env.ctx, "start", mongo=env.mongo))
    assert "Open your own" in built(denied)
    env.ctx.interaction.guild_id = 100
    env.ctx.member.permissions = hikari.Permissions.NONE
    denied = run(dashboard.toggle(env.ctx, "start|off", mongo=env.mongo))
    assert "Administrator" in built(denied)
    assert env.mongo.fwa_points.config["enabled"] is True
    assert not env.mongo.fwa_points.updates


def test_disable_cancels_retry_but_detector_lifecycle_stays_loaded(monkeypatch):
    env = fixture(monkeypatch)

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(60))
        monitor.active_catchups["EXTRA1"] = task
        result = await dashboard.toggle(env.ctx, "start|off", mongo=env.mongo)
        assert task.cancelled()
        assert "stopped 1 active retry" in built(result)

    run(scenario())
    assert env.mongo.fwa_points.config["enabled"] is False
    assert not any(hasattr(item, "_command") for item in monitor.loader._loadables)
    run(dashboard.toggle(env.ctx, "start|on", mongo=env.mongo))
    assert env.mongo.fwa_points.config["enabled"] is True


def test_add_modal_validates_and_uses_atomic_watch_replacement(monkeypatch):
    env = fixture(monkeypatch)
    run(dashboard.add(env.ctx, "start", mongo=env.mongo))
    modal = env.ctx.respond_with_modal.await_args.kwargs
    assert modal["custom_id"] == "fwa_points_add_submit:start"

    def form(tag, name):
        env.ctx.interaction.components = [[SimpleNamespace(custom_id="tag", value=tag)],
                                          [SimpleNamespace(custom_id="name", value=name)]]

    form("BAD!!", "Valid")
    run(dashboard.add_submit(env.ctx, "start", mongo=env.mongo))
    assert len(env.mongo.fwa_points.config["watch_list"]) == 1
    form("#AUTO1", "Duplicate")
    run(dashboard.add_submit(env.ctx, "start", mongo=env.mongo))
    assert len(env.mongo.fwa_points.config["watch_list"]) == 1
    form("#EXTRA2", "Extra Two")
    run(dashboard.add_submit(env.ctx, "start", mongo=env.mongo))
    assert {item["tag"] for item in env.mongo.fwa_points.config["watch_list"]} == {"EXTRA1", "EXTRA2"}
    assert isinstance(env.mongo.fwa_points.updates[-1], list)
    assert env.ctx.interaction.edit_initial_response.await_args.kwargs["user_mentions"] is False


def test_remove_requires_selected_extra_and_automatic_is_protected(monkeypatch):
    env = fixture(monkeypatch)
    env.ctx.interaction.values = ("AUTO1",)
    denied = run(dashboard.select_extra(env.ctx, "start", mongo=env.mongo))
    assert "cannot be removed" in built(denied)
    env.ctx.interaction.values = ("EXTRA1",)
    selected = run(dashboard.select_extra(env.ctx, "start", mongo=env.mongo))
    assert "Remove selected extra" in built(selected)
    current = next(value for value in env.states.values() if value.get("selected_extra") == "EXTRA1")
    removed = run(dashboard.remove(env.ctx, current["_id"], mongo=env.mongo))
    assert "removed" in built(removed)
    assert not env.mongo.fwa_points.config["watch_list"]
    assert "AUTO1" in built(run(dashboard._panel(env.mongo, env.state)))


def test_pagination_caps_watch_rows_and_refresh_rechecks_state(monkeypatch):
    env = fixture(monkeypatch, automatic=18)
    first = run(dashboard._panel(env.mongo, env.state))
    assert "Page 1/4" in built(first)
    assert len(first[0].build()[0]["components"]) <= 40
    later = run(dashboard.page(env.ctx, "start|2", mongo=env.mongo))
    assert "Page 3/4" in built(later)
    fresh = run(dashboard.refresh(env.ctx, "start", mongo=env.mongo))
    assert "Status refreshed" in built(fresh)


def test_clan_source_outage_blocks_extra_mutations(monkeypatch):
    env = fixture(monkeypatch)

    def broken_find(query):
        raise RuntimeError("clan database unavailable")

    env.mongo.clans.find = broken_find
    env.state["selected_extra"] = "EXTRA1"
    result = run(dashboard.remove(env.ctx, "start", mongo=env.mongo))
    assert "no extra was removed" in built(result)
    assert env.mongo.fwa_points.config["watch_list"] == [
        {"tag": "EXTRA1", "name": "Extra One"}
    ]
    env.ctx.interaction.components = [
        [SimpleNamespace(custom_id="tag", value="#EXTRA2")],
        [SimpleNamespace(custom_id="name", value="Extra Two")],
    ]
    run(dashboard.add_submit(env.ctx, "start", mongo=env.mongo))
    assert "no extra was added" in built(
        env.ctx.interaction.edit_initial_response.await_args.kwargs["components"]
    )
    assert not env.mongo.fwa_points.updates


def test_full_extra_page_stays_within_discord_component_limit(monkeypatch):
    env = fixture(monkeypatch, automatic=0)
    env.mongo.fwa_points.config["watch_list"] = [
        {"tag": f"EXTRA{i}", "name": f"Extra {i}"} for i in range(10)
    ]
    payload = run(dashboard._panel(env.mongo, env.state, notice="Refreshed"))[0].build()[0]

    def count(node):
        return 1 + sum(count(child) for child in node.get("components", [])) + (
            count(node["accessory"]) if "accessory" in node else 0
        )

    assert count(payload) <= 40


def test_old_points_subcommand_is_not_registered():
    from extensions.commands.fwa import fwa
    assert "points" not in fwa.subcommands

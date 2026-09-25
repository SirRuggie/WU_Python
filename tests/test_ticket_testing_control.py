"""Boundary tests for the isolated ticket-test control path."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands.tickets import testing_service
from utils import ticket_testing_control as control


class Collection:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.updates = []

    async def find_one(self, query, *_args):
        row = self.rows.get(query.get("_id"))
        if row is None:
            return None
        return dict(row) if all(row.get(key) == value for key, value in query.items()) else None

    async def update_one(self, query, update, **_kwargs):
        self.updates.append((query, update))
        row = self.rows.setdefault(query["_id"], {"_id": query["_id"]})
        row.update(update.get("$setOnInsert", {}))
        row.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1)


class ScopedMongo:
    is_ticket_test_scope = True

    def __init__(self, rows=None):
        self.ticket_automation_state = Collection(rows)
        self.ticket_setup = Collection()
        self.tickets = Collection()
        self.ticket_open_slots = Collection()


class LiveMongo:
    """Production sentinel: any attempted live storage mutation fails the test."""

    def __init__(self):
        self.ticket_setup = self
        self.writes = []

    async def update_one(self, *_args, **_kwargs):
        self.writes.append(True)
        raise AssertionError("control wrote to the production ticket database")


class Context:
    def __init__(self, user_id=30, guild_id=10):
        self.user = SimpleNamespace(id=user_id, username="Tester")
        self.member = SimpleNamespace(id=user_id, guild_id=guild_id, display_name="Tester")
        self.guild_id = guild_id
        self.interaction = SimpleNamespace(guild_id=guild_id, member=self.member)
        self.deferred = []

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)


class Rest:
    def __init__(self, *, member_roles=(), roles=()):
        self.member_roles = member_roles
        self.roles = roles
        self.created = []
        self.edited = []

    async def fetch_member(self, _guild_id, user_id):
        return SimpleNamespace(id=user_id, role_ids=self.member_roles)

    async def fetch_roles(self, _guild_id):
        return self.roles

    async def fetch_channel(self, channel_id):
        return self.channels[channel_id]

    async def create_guild_text_channel(self, guild_id, name, **kwargs):
        self.created.append((guild_id, name, kwargs))
        channel = SimpleNamespace(id=100 + len(self.created), guild_id=guild_id, name=name, topic=kwargs["topic"])
        self.channels[channel.id] = channel
        return channel

    async def edit_channel(self, *args, **kwargs):
        self.edited.append((args, kwargs))


class Bot:
    def __init__(self, rest):
        self.rest = rest

    def get_me(self):
        return SimpleNamespace(id=99)


def run(coro):
    return asyncio.run(coro)


def test_start_window_requires_admin_before_any_test_or_live_write(monkeypatch):
    live = LiveMongo()
    ctx = Context()
    monkeypatch.setattr(control.perms, "is_target_admin", lambda *_args: _false())

    with pytest.raises(ValueError, match="Administrator"):
        run(control.start_window(Bot(Rest()), live, ctx, 60, 60))

    assert live.writes == []


async def _false():
    return False


async def _true():
    return True


def test_start_window_is_explicit_opt_in_and_uses_test_scope_only(monkeypatch):
    scoped = ScopedMongo()
    live = LiveMongo()
    ctx = Context(user_id=31)
    bot = Bot(Rest())
    observed = {}

    monkeypatch.setattr(control.perms, "is_target_admin", lambda *_args: _true())
    monkeypatch.setattr(control.testing_service, "test_mongo", lambda mongo: scoped)
    monkeypatch.setattr(control.testing_service, "active_window", lambda mongo: _none())
    monkeypatch.setattr(control.testing_service, "snapshot_ticket_config", lambda mongo, test: _snapshot(observed, mongo, test))
    monkeypatch.setattr(control, "_ensure_parents", lambda bot, test, guild: _parents(observed, bot, test, guild))
    monkeypatch.setattr(control.testing_service, "open_window", lambda test, **kwargs: _opened(observed, test, kwargs))
    monkeypatch.setattr(control, "sync_parent_access", lambda *_args: _none())

    result = run(control.start_window(bot, live, ctx, 60, 60))

    assert result["mode"] == "test"
    assert observed["snapshot"] == (live, scoped)
    assert observed["open_scope"] is scoped
    assert observed["open"]["allowed_user_ids"] == [31]
    assert live.writes == []


async def _none():
    return None


async def _snapshot(observed, live, scoped):
    observed["snapshot"] = (live, scoped)


async def _parents(observed, _bot, scoped, guild_id):
    observed["parents"] = (scoped, guild_id)
    return {"candidate_parent_id": 20, "staff_parent_id": 21}


async def _opened(observed, scoped, kwargs):
    observed["open_scope"] = scoped
    observed["open"] = kwargs
    return {"mode": "test", **kwargs}


def test_private_parent_rejects_a_channel_without_its_durable_marker():
    marker = "owned-marker"
    scoped = ScopedMongo({control.PARENTS_ID: {
        "_id": control.PARENTS_ID, "mode": "test", "guild_id": 10,
        "marker": marker, "candidate_parent_id": 20,
    }})
    rest = Rest()
    rest.channels = {20: SimpleNamespace(id=20, guild_id=10, topic="forged-marker")}

    with pytest.raises(ValueError, match="changed ownership"):
        run(control._ensure_parents(Bot(rest), scoped, 10))

    assert rest.created == []
    assert scoped.ticket_setup.updates == []


def test_update_access_rejects_everyone_role_without_mutating_scope(monkeypatch):
    opened_at = datetime.now(timezone.utc)
    scoped = ScopedMongo()
    ctx = Context(guild_id=10)
    rest = Rest(roles=[SimpleNamespace(id=10), SimpleNamespace(id=42)])
    bot = Bot(rest)
    window = {"guild_id": 10, "opened_at": opened_at, "allowed_user_ids": [], "allowed_role_ids": []}

    monkeypatch.setattr(control.perms, "is_target_admin", lambda *_args: _true())
    monkeypatch.setattr(control.testing_service, "test_mongo", lambda _mongo: scoped)
    monkeypatch.setattr(control.testing_service, "active_window", lambda _scope: _value(window))

    with pytest.raises(ValueError, match="@everyone"):
        run(control.update_access(bot, LiveMongo(), ctx, role_ids=[10]))

    assert scoped.ticket_automation_state.updates == []


async def _value(value):
    return value


def test_open_test_ticket_loser_never_calls_live_thread_creation(monkeypatch):
    scoped = ScopedMongo()
    live = LiveMongo()
    ctx = Context()
    ctx.interaction.edit_initial_response = _record_edit(ctx)
    bot = Bot(Rest(member_roles=(), roles=[SimpleNamespace(id=10, permissions=hikari.Permissions.NONE)]))
    window = {"mode": "test", "guild_id": 10, "allowed_user_ids": [30], "allowed_role_ids": [], "allow_admins": False}
    seen = {}

    monkeypatch.setattr(control.testing_service, "test_mongo", lambda _mongo: scoped)
    monkeypatch.setattr(control.testing_service, "active_window", lambda _scope: _value(window))
    monkeypatch.setattr(control.testing_service, "claim_test_slot", lambda scope, **kwargs: _claim(seen, scope, kwargs))
    monkeypatch.setattr(control.thread_service, "create_live_thread_ticket", _must_not_create)

    run(control.open_test_ticket(ctx, bot, live, "main"))

    assert ctx.deferred == [{"ephemeral": True}]
    assert seen["scope"] is scoped
    assert seen["kwargs"]["ticket_type"] == "main"
    assert "already open" in ctx.edited_text
    assert live.writes == []


def _record_edit(ctx):
    async def edit_initial_response(*, content, **_kwargs):
        ctx.edited_text = content
    return edit_initial_response


async def _claim(seen, scoped, kwargs):
    seen["scope"] = scoped
    seen["kwargs"] = kwargs
    return SimpleNamespace(won=False, slot={"location_id": 555})


async def _must_not_create(*_args, **_kwargs):
    raise AssertionError("a losing test slot must never start ticket creation")


def test_require_test_access_rejects_expired_and_unauthorized_windows(monkeypatch):
    scoped = ScopedMongo()
    ctx = Context()
    rest = Rest(member_roles=(), roles=[SimpleNamespace(id=10, permissions=hikari.Permissions.NONE)])
    bot = Bot(rest)

    monkeypatch.setattr(control.testing_service, "test_mongo", lambda _mongo: scoped)
    monkeypatch.setattr(control.testing_service, "active_window", lambda _scope: _none())
    with pytest.raises(ValueError, match="ended"):
        run(control.require_test_access(ctx, LiveMongo(), bot))

    window = {"mode": "test", "guild_id": 10, "allowed_user_ids": [], "allowed_role_ids": [], "allow_admins": False}
    monkeypatch.setattr(control.testing_service, "active_window", lambda _scope: _value(window))
    with pytest.raises(ValueError, match="allowlist"):
        run(control.require_test_access(ctx, LiveMongo(), bot))

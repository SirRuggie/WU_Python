import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
from pymongo.errors import DuplicateKeyError

from extensions.commands import content
from extensions.commands.setup import setup
from extensions.components import registered_functions


def run(coro):
    return asyncio.run(coro)


class Config:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query):
        row = self.rows.get(query["_id"])
        return copy.deepcopy(row) if row is not None else None

    async def insert_one(self, row):
        if row["_id"] in self.rows:
            raise DuplicateKeyError("duplicate")
        self.rows[row["_id"]] = copy.deepcopy(row)
        return SimpleNamespace(inserted_id=row["_id"])

    async def update_one(self, query, update, *, upsert=False):
        row = self.rows.get(query["_id"])
        if row is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            row = {"_id": query["_id"]}
            self.rows[row["_id"]] = row
        row.update(copy.deepcopy(update["$set"]))
        return SimpleNamespace(matched_count=1)


def context(*, user=10, guild=20, values=("123",), permissions=hikari.Permissions.MANAGE_GUILD):
    interaction = SimpleNamespace(
        guild_id=guild, values=values,
        member=SimpleNamespace(permissions=permissions),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=user), interaction=interaction, respond=AsyncMock(),
    )


def bot(*, destination_guild=20, destination_type=hikari.ChannelType.GUILD_TEXT,
        overwrites=None, create=None):
    destination = SimpleNamespace(
        guild_id=destination_guild, type=destination_type,
        permission_overwrites={} if overwrites is None else overwrites,
    )
    next_channel = SimpleNamespace(guild_id=20, type=hikari.ChannelType.GUILD_TEXT)
    role_id, _next_id = content.acknowledgement_setup("about-us")
    roles = (
        SimpleNamespace(id=20, position=0, permissions=hikari.Permissions.NONE),
        SimpleNamespace(id=100, position=10, permissions=(
            hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.ATTACH_FILES | hikari.Permissions.MANAGE_ROLES
        )),
        SimpleNamespace(id=role_id, position=5, permissions=hikari.Permissions.NONE, is_managed=False),
    )
    async def fetch_channel(channel_id):
        return destination if int(channel_id) == 123 else next_channel
    rest = SimpleNamespace(
        fetch_channel=AsyncMock(side_effect=fetch_channel),
        fetch_roles=AsyncMock(return_value=roles),
        fetch_my_user=AsyncMock(return_value=SimpleNamespace(id=999)),
        fetch_member=AsyncMock(return_value=SimpleNamespace(id=999, role_ids=(100,))),
        create_message=create or AsyncMock(return_value=SimpleNamespace(id=777)),
    )
    return SimpleNamespace(rest=rest)


def state(monkeypatch, sections):
    states = {}
    initial = {
        "_id": "initial", "user_id": 10, "guild_id": 20, "view": "document",
        "document": "about-us", "sections": sections, "media": {}, "revision": 0,
        "destination_channel_id": None,
    }
    states[initial["_id"]] = initial
    async def get_state(_mongo, token):
        return states.get(token)
    async def insert_state(_mongo, row, ttl=None):
        if row["_id"] in states:
            raise AssertionError("duplicate draft ID")
        states[row["_id"]] = copy.deepcopy(row)
    monkeypatch.setattr(content, "get_state", get_state)
    monkeypatch.setattr(content, "insert_state", insert_state)
    return states


def test_native_channel_select_persists_per_document_and_posts_current_draft_once(monkeypatch):
    document = content.DOCUMENTS["about-us"]
    sections = [node.content for node in content.text_nodes(run(content.baseline(document)))]
    sections[0] = "## Current unsaved draft"
    states = state(monkeypatch, sections)
    before = content.panel(states["initial"])[0].build()[0]
    before_buttons = [button for row in before["components"]
                      if row["type"] == hikari.ComponentType.ACTION_ROW
                      for button in row["components"]
                      if button["type"] == hikari.ComponentType.BUTTON]
    assert next(button for button in before_buttons if button["custom_id"] == "content_send:initial")["disabled"]
    db = SimpleNamespace(bot_config=Config())
    client = bot()
    selector = context()

    selected_panel = run(content.choose_destination(selector, "initial", mongo=db, bot=client))
    destination_row = db.bot_config.rows["content_destination:20:about-us"]
    assert destination_row["channel_id"] == 123
    assert run(content.destination_for(db, 20, "about-us")) == 123
    assert run(content.destination_for(db, 20, "strike-system")) is None
    selected_id = next(key for key, value in states.items() if value.get("destination_channel_id") == 123)
    payload = selected_panel[0].build()[0]
    native = [part["components"][0] for part in payload["components"]
              if part["type"] == hikari.ComponentType.ACTION_ROW
              and part["components"][0]["type"] == hikari.ComponentType.CHANNEL_SELECT_MENU]
    assert len(native) == 1
    assert tuple(native[0]["channel_types"]) == (hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS)
    assert native[0]["min_values"] == 1
    assert "posts this draft" in str(payload)

    result = run(content.send_to_channel(context(), selected_id, mongo=db, bot=client))
    sent = client.rest.create_message.await_args.kwargs
    assert sent["channel"] == 123
    assert sent["user_mentions"] is False and sent["role_mentions"] is False
    assert sent["mentions_everyone"] is False
    assert "Current unsaved draft" in str([item.build() for item in sent["components"]])
    assert content.acknowledgement_id(sent["components"], document)
    _role_id, next_channel_id = content.acknowledgement_setup("about-us")
    assert any(call.args == (next_channel_id,) for call in client.rest.fetch_channel.await_args_list)
    assert "View posted message" in str(result[0].build())
    run(content.send_to_channel(context(), selected_id, mongo=db, bot=client))
    client.rest.create_message.assert_awaited_once()
    assert "content_send:" + selected_id in db.bot_config.rows


def test_invalid_selection_permission_and_cross_guild_state_cannot_send(monkeypatch):
    document = content.DOCUMENTS["about-us"]
    sections = [node.content for node in content.text_nodes(run(content.baseline(document)))]
    states = state(monkeypatch, sections)
    db = SimpleNamespace(bot_config=Config())
    wrong_guild_bot = bot(destination_guild=99)
    run(content.choose_destination(context(), "initial", mongo=db, bot=wrong_guild_bot))
    assert not db.bot_config.rows
    invalid_type = bot(destination_type=hikari.ChannelType.GUILD_FORUM)
    run(content.choose_destination(context(), "initial", mongo=db, bot=invalid_type))
    assert not db.bot_config.rows
    denied = run(content.choose_destination(context(user=999), "initial", mongo=db, bot=bot()))
    assert "Open your own" in str(denied[0].build())
    assert not db.bot_config.rows

    states["initial"]["destination_channel_id"] = 123
    deny_send = hikari.PermissionOverwrite(
        id=20, type=hikari.PermissionOverwriteType.ROLE,
        deny=hikari.Permissions.SEND_MESSAGES,
    )
    client = bot(overwrites={20: deny_send})
    result = run(content.send_to_channel(context(), "initial", mongo=db, bot=client))
    assert "Send Messages" in str(result[0].build())
    client.rest.create_message.assert_not_awaited()
    assert "content_send:initial" not in db.bot_config.rows


def test_retires_only_three_setup_posts_and_keeps_acknowledgements():
    assert set(setup.subcommands) == {"recruit-check"}
    for name in ("aboutus_acknowledge", "strikesystem_acknowledge", "familyparticulars_acknowledge"):
        assert name in registered_functions


def test_admin_destination_uses_bot_member_endpoint_and_bypasses_overwrites():
    app = bot()
    app.rest.fetch_roles.return_value = (
        SimpleNamespace(id=20, permissions=hikari.Permissions.NONE),
        SimpleNamespace(id=100, permissions=hikari.Permissions.ADMINISTRATOR),
    )
    channel = SimpleNamespace(permission_overwrites=None)
    permissions = run(content.destination_permissions(app, 20, channel))
    assert permissions & hikari.Permissions.ADMINISTRATOR
    app.rest.fetch_my_user.assert_awaited_once_with()
    app.rest.fetch_member.assert_awaited_once_with(20, 999)

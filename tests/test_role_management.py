"""Role management callback behavior against a guild and REST-shaped fakes."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import role_management as panel
from extensions.commands.recruit import perms


def run(coroutine):
    return asyncio.run(coroutine)


class Role:
    def __init__(self, role_id, name, position, permissions=hikari.Permissions.NONE,
                 is_managed=False):
        self.id = role_id
        self.name = name
        self.position = position
        self.permissions = permissions
        self.is_managed = is_managed


class Member:
    def __init__(self, member_id, role_ids=(), name=None, is_bot=False):
        self.id = member_id
        self.role_ids = list(role_ids)
        self.display_name = name or f"Member {member_id}"
        self.is_bot = is_bot


class Guild:
    def __init__(self, roles, members):
        self.id = 100
        self.owner_id = 999
        self.roles = {role.id: role for role in roles}
        self.members = {member.id: member for member in members}

    def get_role(self, role_id):
        return self.roles.get(role_id)

    def get_member(self, member_id):
        return self.members.get(member_id)


class Rest:
    def __init__(self, guild):
        self.guild = guild
        self.added = []
        self.removed = []
        self.fail_member_list = False

    async def fetch_member(self, guild_id, member_id):
        assert guild_id == self.guild.id
        return self.guild.members[member_id]

    async def add_role_to_member(self, guild_id, member_id, role_id, *, reason):
        self.added.append((guild_id, member_id, role_id))
        self.guild.members[member_id].role_ids.append(role_id)

    async def remove_role_from_member(self, guild_id, member_id, role_id, *, reason):
        self.removed.append((guild_id, member_id, role_id))
        self.guild.members[member_id].role_ids.remove(role_id)

    def fetch_members(self, guild_id):
        assert guild_id == self.guild.id

        async def members():
            if self.fail_member_list:
                raise hikari.ForbiddenError("https://discord.test", {}, {}, "denied")
            for item in self.guild.members.values():
                yield item

        return members()


class Bot:
    def __init__(self, guild):
        self.cache = SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == guild.id else None)
        self.rest = Rest(guild)
        self.me = SimpleNamespace(id=500)

    def get_me(self):
        return self.me


def fixture(monkeypatch):
    everyone = Role(100, "@everyone", 0)
    actor_role = Role(10, "Recruiter", 50, hikari.Permissions.MANAGE_ROLES)
    bot_role = Role(20, "Bot", 60, hikari.Permissions.MANAGE_ROLES)
    target_role = Role(30, "Member", 10)
    normal = Role(40, "Event", 20)
    privileged = Role(41, "Admin tool", 20, hikari.Permissions.MANAGE_GUILD)
    actor = Member(1, [10])
    target = Member(2, [30])
    bot_member = Member(500, [20], is_bot=True)
    guild = Guild([everyone, actor_role, bot_role, target_role, normal, privileged],
                  [actor, target, bot_member])
    bot = Bot(guild)
    context = SimpleNamespace(
        user=SimpleNamespace(id=1), member=actor,
        interaction=SimpleNamespace(guild_id=100, member=actor, app=bot, values=()),
        defer=AsyncMock(),
    )
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(
        find_one=AsyncMock(return_value={"main_recruiter_role": 10})))
    states = {}

    async def insert_state(_mongo, state, ttl=None):
        assert state["_id"] not in states
        states[state["_id"]] = state

    async def get_state(_mongo, key):
        return states.get(key)

    monkeypatch.setattr(panel, "insert_state", insert_state)
    monkeypatch.setattr(panel, "get_state", get_state)
    base = {
        "_id": "start", "user_id": 1, "guild_id": 100,
        "manage_token": "home", "target_id": 2, "target_label": "Member 2 (2)",
        "role_ids": [40], "role_labels": ["Event"],
    }
    states["start"] = base
    return SimpleNamespace(ctx=context, mongo=mongo, states=states, guild=guild,
                           bot=bot, actor=actor, target=target)


def rendered(components):
    return str([component.build() for component in components])


def test_native_selects_and_selected_identity(monkeypatch):
    env = fixture(monkeypatch)
    built = panel._panel(env.states["start"])[0].build()[0]
    controls = [item for item in built["components"] if item["type"] == hikari.ComponentType.ACTION_ROW]
    types = [part["type"] for row in controls for part in row["components"]]
    assert hikari.ComponentType.USER_SELECT_MENU in types
    assert types.count(hikari.ComponentType.ROLE_SELECT_MENU) == 2
    role_menu = next(part for row in controls for part in row["components"]
                     if part.get("custom_id") == "roles_role:start")
    assert role_menu["max_values"] == 25
    assert "Member 2 (2)" in str(built)
    assert "Event" in str(built)


def test_role_change_is_partial_idempotent_and_rechecks_permissions(monkeypatch):
    env = fixture(monkeypatch)
    state = env.states["start"]
    state["role_ids"] = [40, 41]
    first = run(panel.change(env.ctx, "start|add", mongo=env.mongo))
    assert env.bot.rest.added == [(100, 2, 40)]
    assert "Not permitted" in rendered(first)
    second = run(panel.change(env.ctx, "start|add", mongo=env.mongo))
    assert len(env.bot.rest.added) == 1
    assert "Already correct" in rendered(second)
    run(panel.change(env.ctx, "start|remove", mongo=env.mongo))
    assert env.bot.rest.removed == [(100, 2, 40)]
    assert 40 not in env.target.role_ids
    assert 30 in env.target.role_ids  # No full role-list overwrite.


def test_owner_cross_guild_and_revoked_access_cannot_mutate(monkeypatch):
    env = fixture(monkeypatch)
    env.ctx.user.id = 123
    assert "Open your own" in rendered(run(panel.change(env.ctx, "start|add", mongo=env.mongo)))
    env.ctx.user.id = 1
    env.ctx.interaction.guild_id = 101
    assert "Open your own" in rendered(run(panel.change(env.ctx, "start|add", mongo=env.mongo)))
    env.ctx.interaction.guild_id = 100
    env.actor.role_ids.clear()
    assert "Recruiter access" in rendered(run(panel.change(env.ctx, "start|add", mongo=env.mongo)))
    assert not env.bot.rest.added


def test_actor_target_and_bot_hierarchy_are_rechecked(monkeypatch):
    env = fixture(monkeypatch)
    env.target.role_ids = [10]
    assert "below your highest role" in rendered(run(panel.change(env.ctx, "start|add", mongo=env.mongo)))
    env.target.role_ids = [30]
    env.guild.roles[40].position = 60
    assert "Not permitted" in rendered(run(panel.change(env.ctx, "start|add", mongo=env.mongo)))
    assert not env.bot.rest.added
    env.guild.roles[40].position = 20
    env.guild.members[env.guild.owner_id] = Member(env.guild.owner_id, [30])
    env.states["start"]["target_id"] = env.guild.owner_id
    assert "below your highest role" in rendered(run(panel.change(env.ctx, "start|add", mongo=env.mongo)))


def test_member_browse_exact_count_paging_refresh_and_rest_failure(monkeypatch):
    env = fixture(monkeypatch)
    env.ctx.interaction.values = (40,)
    for i in range(25):
        env.guild.members[1000 + i] = Member(1000 + i, [40], f"Same name {i}", is_bot=i == 0)
    response = run(panel.browse_role(env.ctx, "start", mongo=env.mongo))
    assert "25 total" in rendered(response)
    assert "24 people" in rendered(response)
    assert "1 bots" in rendered(response)
    assert "Page 1/2" in rendered(response)
    browse = next(state for state in env.states.values() if state.get("view") == "browse")
    page_two = run(panel.page(env.ctx, f"{browse['_id']}|1", mongo=env.mongo))
    assert "Page 2/2" in rendered(page_two)
    assert "(`100" in rendered(page_two)  # IDs distinguish duplicate names.
    env.bot.rest.fail_member_list = True
    failed = run(panel.refresh(env.ctx, browse["_id"], mongo=env.mongo))
    assert "previous snapshot" in rendered(failed)
    env.bot.rest.fail_member_list = False
    env.guild.members[1000].role_ids.clear()
    fresh = run(panel.refresh(env.ctx, browse["_id"], mongo=env.mongo))
    assert "24 total" in rendered(fresh)
    env.ctx.interaction.values = (100,)
    everyone = run(panel.browse_role(env.ctx, "start", mongo=env.mongo))
    assert "28 total" in rendered(everyone)  # @everyone includes every guild member.


def test_panel_and_paged_members_stay_within_discord_component_limits(monkeypatch):
    env = fixture(monkeypatch)
    state = env.states["start"]
    state["target_label"] = "T" * 75 + " (123456789012345678)"
    state["role_ids"] = list(range(1, 26))
    state["role_labels"] = ["R" * 40 for _ in range(25)]
    built = panel._panel(state, "N" * 1800)[0].build()[0]
    texts = [part["content"] for part in built["components"]
             if part["type"] == hikari.ComponentType.TEXT_DISPLAY]
    assert len(built["components"]) <= 40
    assert all(len(text) <= 2000 for text in texts)
    assert sum(map(len, texts)) <= 4000
    entries = [(i, "M" * 75, False) for i in range(25)]
    browse = panel._browse_panel({"_id": "x", "manage_token": "home",
                                  "browse_entries": entries, "browse_role_name": "R" * 75}, 0)[0].build()[0]
    names = [part["content"] for part in browse["components"]
             if part["type"] == hikari.ComponentType.TEXT_DISPLAY]
    assert all(len(text) <= 2000 for text in names)
    assert sum(map(len, names)) <= 4000

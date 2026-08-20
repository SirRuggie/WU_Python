import asyncio
from types import SimpleNamespace

import hikari

from extensions.commands import role as role_commands
from extensions.commands.help_catalog import HELP_CATEGORIES, command_paths
from extensions.commands.recruit import perms
from extensions.commands.recruit.dashboard.manage_roles import role_is_manageable


class FakeRole:
    def __init__(
            self,
            role_id,
            position,
            permissions=hikari.Permissions.NONE,
            is_managed=False,
    ):
        self.id = role_id
        self.position = position
        self.permissions = permissions
        self.is_managed = is_managed


class FakeMember:
    def __init__(self, member_id, role_ids):
        self.id = member_id
        self.role_ids = tuple(role_ids)


class FakeGuild:
    def __init__(self, guild_id, owner_id, roles, members=()):
        self.id = guild_id
        self.owner_id = owner_id
        self._roles = {role.id: role for role in roles}
        self._members = {member.id: member for member in members}

    def get_role(self, role_id):
        return self._roles.get(role_id)

    def get_member(self, member_id):
        return self._members.get(member_id)


class FakeCollection:
    def __init__(self, document):
        self.document = document

    async def find_one(self, query):
        return self.document


def test_help_catalog_covers_every_registered_slash_path_after_role_addition():
    paths = command_paths()

    assert len(paths) == 81
    assert sum(len(category["commands"]) for category in HELP_CATEGORIES.values()) == 81
    assert "/accounts" in paths
    assert "/cards" in paths
    assert {"/role add", "/role remove", "/role manage"} <= paths
    assert {"/poll create", "/poll view", "/poll active"} <= paths
    assert "/cwl-reminder list" in paths
    assert "/cwl-reminder add-followup" in paths
    assert "/cwl-reminder remove-followup" in paths
    assert "/cwl-reminder list-jobs" not in paths
    assert "/cwl-reminder followup" not in paths


def test_role_group_registers_the_three_public_subcommands():
    assert set(role_commands.role.subcommands) == {"add", "remove", "manage"}


def test_cached_member_permissions_include_everyone_and_explicit_roles():
    guild = FakeGuild(
        guild_id=1,
        owner_id=999,
        roles=[
            FakeRole(1, 0, hikari.Permissions.VIEW_CHANNEL),
            FakeRole(10, 10, hikari.Permissions.MANAGE_MESSAGES),
        ],
    )
    member = FakeMember(20, [10])

    resolved = perms.guild_permissions(member, guild)

    assert resolved & hikari.Permissions.VIEW_CHANNEL
    assert resolved & hikari.Permissions.MANAGE_MESSAGES


def test_recruiter_authorization_accepts_configured_and_team_roles():
    mongo = SimpleNamespace(ticket_setup=FakeCollection({
        "main_recruiter_role": 101,
        "fwa_recruiter_role": 102,
    }))
    guild = FakeGuild(1, 999, [FakeRole(1, 0)])

    assert asyncio.run(perms.is_recruiter(FakeMember(1, [101]), mongo, guild))
    assert asyncio.run(perms.is_recruiter(FakeMember(2, [102]), mongo, guild))
    assert asyncio.run(perms.is_recruiter(
        FakeMember(3, [perms.RECRUITMENT_TEAM_ROLE_ID]), mongo, guild,
    ))
    assert not asyncio.run(perms.is_recruiter(FakeMember(4, [404]), mongo, guild))


def test_recruiter_authorization_accepts_cached_admin_and_owner():
    admin_role = FakeRole(10, 50, hikari.Permissions.ADMINISTRATOR)
    guild = FakeGuild(1, 999, [FakeRole(1, 0), admin_role])
    mongo = SimpleNamespace(ticket_setup=FakeCollection({}))

    assert asyncio.run(perms.is_recruiter(FakeMember(100, [admin_role.id]), mongo, guild))
    assert asyncio.run(perms.is_recruiter(FakeMember(guild.owner_id, []), mongo, guild))


def test_actor_role_policy_enforces_hierarchy_and_permission_subset():
    actor_role = FakeRole(10, 50, hikari.Permissions.MANAGE_MESSAGES)
    lower_safe_role = FakeRole(11, 20, hikari.Permissions.VIEW_CHANNEL)
    lower_privileged_role = FakeRole(12, 20, hikari.Permissions.MANAGE_GUILD)
    higher_role = FakeRole(13, 60, hikari.Permissions.NONE)
    guild = FakeGuild(
        1,
        999,
        [
            FakeRole(1, 0, hikari.Permissions.VIEW_CHANNEL),
            actor_role,
            lower_safe_role,
            lower_privileged_role,
            higher_role,
        ],
    )
    actor = FakeMember(100, [actor_role.id])

    assert perms.actor_can_manage_role(actor, guild, lower_safe_role)
    assert not perms.actor_can_manage_role(actor, guild, lower_privileged_role)
    assert not perms.actor_can_manage_role(actor, guild, higher_role)


def test_actor_member_policy_blocks_self_higher_members_and_owner():
    low = FakeRole(10, 10)
    recruiter = FakeRole(11, 50)
    high = FakeRole(12, 80)
    guild = FakeGuild(1, 999, [FakeRole(1, 0), low, recruiter, high])
    actor = FakeMember(100, [recruiter.id])

    assert perms.actor_can_manage_member(actor, FakeMember(200, [low.id]), guild)
    assert not perms.actor_can_manage_member(actor, actor, guild)
    assert not perms.actor_can_manage_member(actor, FakeMember(300, [high.id]), guild)
    assert not perms.actor_can_manage_member(actor, FakeMember(guild.owner_id, []), guild)


class FakeBot:
    def __init__(self, bot_id):
        self._me = SimpleNamespace(id=bot_id)

    def get_me(self):
        return self._me


def test_bot_manageability_requires_permission_hierarchy_and_unmanaged_role():
    bot_role = FakeRole(20, 100, hikari.Permissions.MANAGE_ROLES)
    lower_role = FakeRole(21, 20)
    equal_role = FakeRole(22, 100)
    managed_role = FakeRole(23, 10, is_managed=True)
    bot_member = FakeMember(500, [bot_role.id])
    guild = FakeGuild(
        1,
        999,
        [FakeRole(1, 0), bot_role, lower_role, equal_role, managed_role],
        [bot_member],
    )
    bot = FakeBot(bot_member.id)

    assert role_is_manageable(guild, bot, lower_role)
    assert not role_is_manageable(guild, bot, equal_role)
    assert not role_is_manageable(guild, bot, managed_role)
    assert not role_is_manageable(guild, bot, guild.get_role(guild.id))

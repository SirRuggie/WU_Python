"""Permission and complete row equivalence for indexed role membership lookups."""

import asyncio
from contextlib import asynccontextmanager
from random import Random
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import json
import hikari
import pytest
from extensions.warrior import core
from utils.role_hierarchy import RolePositions
from cwl_web import member_timezones as routes
from cwl_web import manage_roles


def legacy_permissions(member, roles, owner_id):
    if int(member.id) == int(owner_id):
        return hikari.Permissions.all_permissions()
    value = hikari.Permissions.NONE
    for role in roles:
        if role.id == member.guild_id or role.id in member.role_ids:
            value |= role.permissions
    return (
        hikari.Permissions.all_permissions()
        if value & hikari.Permissions.ADMINISTRATOR
        else value
    )


def legacy_top(member, roles):
    return max(
        (role.position for role in roles if role.id in member.role_ids), default=0
    )


def test_membership_lookup_matches_legacy_for_mixed_roles_owners_and_admins():
    random = Random(112)
    roles = [
        S(id=1000 + i, position=i // 2, permissions=(1 << (i % 40))) for i in range(245)
    ]
    indexed = RolePositions(roles)
    for count in (0, 1, 5, 25, 100, 220, 245):
        for owner in (False, True):
            for _ in range(20):
                selected = random.sample([r.id for r in roles], count)
                member = S(id=7, guild_id=1000, role_ids=tuple(selected + [999999]))
                assert core.permissions(
                    member, roles, 7 if owner else 8
                ) == legacy_permissions(member, roles, 7 if owner else 8)
                assert core.top(member, roles) == legacy_top(member, roles)
                assert core.top(member, indexed) == legacy_top(member, roles)


@pytest.mark.parametrize("actor_case", ["ordinary", "admin", "owner", "no_roles"])
def test_complete_inventory_rows_and_role_editability_unchanged(
    monkeypatch, actor_case
):
    async def run():
        gid = routes.GUILD_ID
        owner = gid + 9000
        roles = {
            gid: S(id=gid, name="everyone", position=0, permissions=0, is_managed=False)
        }
        for i in range(244):
            roles[gid + 1000 + i] = S(
                id=gid + 1000 + i,
                name=f"Role{i}",
                position=i + 1,
                permissions=(
                    int(
                        hikari.Permissions.MANAGE_NICKNAMES
                        | hikari.Permissions.MANAGE_ROLES
                    )
                    if i == 220
                    else 0
                ),
                is_managed=i == 5,
            )
        if actor_case == "admin":
            roles[gid + 1220].permissions |= int(hikari.Permissions.ADMINISTRATOR)
        acting = S(
            id=owner if actor_case == "owner" else gid + 9001,
            guild_id=gid,
            role_ids=(
                ()
                if actor_case == "no_roles"
                else tuple(gid + 1000 + i for i in range(221))
            ),
        )
        me = S(
            id=gid + 9002,
            guild_id=gid,
            role_ids=tuple(gid + 1000 + i for i in range(244)),
        )
        guild = S(
            id=gid,
            owner_id=owner,
            get_role=roles.get,
            get_member=lambda uid: me if uid == me.id else None,
        )
        bot = S(get_me=lambda: S(id=me.id))
        raw = [
            dict(
                user=dict(id=str(gid + 20000 + i), username=f"Fixture{i}", bot=i == 9),
                roles=[str(gid + 1000 + (i % 244))],
                nick=None,
            )
            for i in range(1450)
        ]
        raw[0]["user"]["id"] = str(owner)
        profiles = {
            str(gid + 20001): dict(
                source="staff",
                zone_id="utc",
                gmt_label="GMT",
                revision=2,
                utc_offset_minutes=0,
            )
        }

        @asynccontextmanager
        async def mongo(*args):
            yield S(member_profiles=None)

        monkeypatch.setattr(
            routes,
            "require_manage",
            AsyncMock(return_value=dict(user_id=str(acting.id))),
        )
        monkeypatch.setattr(routes, "directory", AsyncMock(return_value=raw))
        monkeypatch.setattr(
            routes, "hierarchy", AsyncMock(return_value=(roles, guild, bot, acting))
        )
        monkeypatch.setattr(routes, "mongo", mongo)
        monkeypatch.setattr(
            routes.MemberProfiles, "for_members", AsyncMock(return_value=profiles)
        )
        monkeypatch.setattr(
            manage_roles,
            "dashboard_grant_roles",
            AsyncMock(return_value={str(gid + 1002)}),
        )
        optimized = json.loads((await routes.members_overview(S())).body)
        monkeypatch.setattr(core, "permissions", legacy_permissions)
        monkeypatch.setattr(core, "top", legacy_top)
        expected = json.loads((await routes.members_overview(S())).body)
        assert optimized == expected
        assert optimized["members"][0]["role_editable"] is False
        assert optimized["members"][9]["role_editable"] is False
        assert str(gid + 1002) not in {r["id"] for r in optimized["manageable_roles"]}

    asyncio.run(run())


def test_role_index_preserves_duplicate_unknown_and_negative_position_rules():
    roles = [S(id=1, position=-2), S(id=1, position=-1), S(id=2, position=0)]
    index = RolePositions(roles)
    for ids in [(), (1,), (1, 1), (1, 999), (1, 2), (999,)]:
        member = S(role_ids=ids)
        assert core.top(member, index) == legacy_top(member, roles)

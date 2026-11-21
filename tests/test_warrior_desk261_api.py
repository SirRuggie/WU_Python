"""261 read-only type scope; no live Discord/API/DB."""
from cwl_web import ticket_browser as api
import pytest
from aiohttp import web


@pytest.mark.parametrize('scope,expected',[
    ('recruit',{'main','fwa'}),('account',{'account'}),('staff',{'staff'}),
    ('all',{'main','fwa','account','staff'}),
])
def test_new_type_filter_is_not_ignored(scope,expected):
    query = api.filters({'type':scope})
    value = query.get('ticket_type')
    actual = set(value['$in']) if isinstance(value,dict) else {value}
    assert actual == expected


def test_explicit_forbidden_type_is_403_and_all_intersects_actor_types():
    with pytest.raises(web.HTTPForbidden):
        api.filters({'type':'staff'},allowed_types={'main','fwa','account'})
    assert api.filters({'type':'all'},allowed_types={'account'})['ticket_type']=={'$in':['account']}
    assert api.filters({'kind':'fwa'})['ticket_type']=='fwa'


@pytest.mark.parametrize('actor', ['admin','main','fwa','account','staff','none'])
def test_http_and_discord_share_exact_config_scope(monkeypatch, actor):
    import asyncio
    import hikari
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from tests.test_warrior_desk261_permissions import CONFIG, EXPECTED
    from extensions.commands.tickets import perms
    role={'main':100,'fwa':101,'account':102,'staff':103}.get(actor)
    member=NS(guild_id=api.GUILD_ID,id=50,role_ids=[role] if role else [],
              permissions=hikari.Permissions.ADMINISTRATOR if actor=='admin' else hikari.Permissions.NONE)
    config={**CONFIG,'ticket_target_guild_id':api.GUILD_ID}
    db=NS(ticket_setup=NS(find_one=AsyncMock(return_value=config)))
    monkeypatch.setattr(api,'identity',AsyncMock(return_value=dict(user_id='50',role_ids=member.role_ids,permissions=member.permissions)))
    monkeypatch.setattr(api,'allowed',AsyncMock(return_value=True))
    async def run():
        scope=await perms.allowed_ticket_types(member,db)
        assert set(scope)==EXPECTED[actor]
        if scope:
            http=await api.authorize(NS(),db)
            assert set(http['_ticket_types'])==set(scope)
        else:
            with pytest.raises(web.HTTPForbidden):await api.authorize(NS(),db)
    asyncio.run(run())

"""Current-main integration seams required by the261 review."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import hikari
import pytest
from extensions.commands.tickets import link_review, player_info, store
from extensions.warrior import core
from tests.test_ticket_runtime import Collection
from tests.test_warrior_desk261_permissions import CONFIG, GUILD


def member(role):
    return NS(id=50, guild_id=GUILD, role_ids=[role], permissions=hikari.Permissions.NONE)


def test_account_staff_can_finish_own_link_review(monkeypatch):
    data={'type':'ticket_link_review','owner_id':50,'guild_id':GUILD,'ticket_id':'ticket_account'}
    ticket={'_id':'ticket_account',**store.RUNTIME_FILTER,'ticket_type':'account','guild_id':GUILD,'user_id':70,'status':'open'}
    monkeypatch.setattr(link_review,'get_state',AsyncMock(return_value=data))
    mongo=NS(ticket_setup=Collection([CONFIG]),tickets=Collection([ticket]))
    ctx=NS(user=NS(id=50),member=member(102),guild_id=GUILD)
    assert asyncio.run(link_review.session(ctx,mongo,'session'))==data


def test_recruit_and_account_roles_keep_link_account_access_separate_from_weight_permission(monkeypatch):
    from extensions.commands.tickets import link_account
    ticket={'_id':'ticket_account',**store.RUNTIME_FILTER,'ticket_type':'account','guild_id':GUILD,'user_id':70,'status':'open'}
    mongo=NS(ticket_setup=Collection([CONFIG]),tickets=Collection([ticket]))
    for role in [100,101,102]:
        ctx=NS(user=NS(id=50),member=member(role),guild_id=GUILD)
        monkeypatch.setattr(link_account,'_allowed',AsyncMock(return_value=link_account.NO_PERMISSION))
        result,error=asyncio.run(link_account._guard(ctx,mongo,'ticket_account'))
        assert result is None and error is not None
        link_account._allowed.assert_awaited_once()
        monkeypatch.setattr(link_account,'_allowed',AsyncMock(return_value=None))
        result,error=asyncio.run(link_account._guard(ctx,mongo,'ticket_account'))
        assert result is not None and result["_id"]==ticket["_id"] and result["ticket_type"]=="account" and error is None


@pytest.mark.parametrize('explicit',[False,True])
def test_desk_requests_never_become_onboarding_ticket(explicit):
    def ticket(kind):
        return {'_id':'ticket_'+kind,**store.RUNTIME_FILTER,'ticket_type':kind,'guild_id':GUILD,'user_id':70,'status':'open','venue':'thread'}
    recruit=ticket('main');account=ticket('account');staff=ticket('staff')
    mongo=NS(tickets=Collection([recruit,account,staff]))
    if explicit:
        with pytest.raises(core.SetupError):
            asyncio.run(core.open_ticket(mongo,GUILD,70,ticket_id='ticket_account'))
    else:
        assert asyncio.run(core.open_ticket(mongo,GUILD,70))==recruit

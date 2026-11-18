"""Expected fallbacks and cancellation at the eleven former bare catches."""
import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import coc
import hikari
import pytest

from utils import background
from extensions.events.message import how_to_ping, goblin_challenge
from extensions.commands import family_links
from extensions.commands.clan.info_hub import handlers as hub
from extensions.commands.tickets_legacy import handlers as tickets


@pytest.fixture(autouse=True)
def bounded_failure_cache():
    background._errors.clear()
    yield
    background._errors.clear()


def error(kind):
    if kind=='expected':return hikari.ForbiddenError(url='',headers={},raw_body=b'',code=50013)
    if kind=='cancel':return asyncio.CancelledError()
    return RuntimeError('synthetic-sensitive-provider-value')


def event(content='how to ping', mentions=()):
    return NS(is_bot=False,channel_id=44,author_id=22,content=content,
              message=NS(user_mentions_ids=list(mentions),add_reaction=AsyncMock(),respond=AsyncMock()))


@pytest.mark.parametrize('kind',['expected','cancel','unexpected'])
def test_ping_optional_reaction_fallback_never_hides_cancellation(monkeypatch,kind,caplog):
    async def run():
        value=event();value.message.add_reaction.side_effect=error(kind)
        monkeypatch.setattr(how_to_ping,'bot_instance',object())
        monkeypatch.setattr(how_to_ping,'mongo_client',NS(recruit_challenges=NS(find_one=AsyncMock(return_value={'active':True}))))
        send=AsyncMock();monkeypatch.setattr(how_to_ping,'send_ping_explanation',send)
        if kind=='expected':assert await how_to_ping.check_how_to_ping(value) is True
        else:
            with pytest.raises(asyncio.CancelledError if kind=='cancel' else RuntimeError):
                await how_to_ping.check_how_to_ping(value)
        send.assert_awaited_once_with(44,22)
    asyncio.run(run())
    assert 'synthetic-sensitive-provider-value' not in caplog.text


@pytest.mark.parametrize('branch',['complete','missing-ping','missing-word'])
@pytest.mark.parametrize('kind',['expected','cancel','unexpected'])
def test_goblin_optional_acknowledgements_keep_side_effect_ownership(monkeypatch,branch,kind):
    async def run():
        content='Goblin' if branch!='missing-word' else 'Hello'
        mentions=[33] if branch!='missing-ping' else []
        value=event(content,mentions);value.message.add_reaction.side_effect=error(kind)
        mongo=NS(recruit_challenges=NS(find_one=AsyncMock(return_value={'user_id':22,'recruiter_id':33})))
        monkeypatch.setattr(goblin_challenge,'mongo_client',mongo)
        claim=AsyncMock(return_value='synthetic-claim');complete=AsyncMock()
        monkeypatch.setattr(goblin_challenge.storage,'claim',claim)
        monkeypatch.setattr(goblin_challenge.storage,'complete',complete)
        sent=AsyncMock(return_value=NS(id=55));monkeypatch.setattr(goblin_challenge,'send_success_message',sent)
        if kind=='expected':assert await goblin_challenge.check_goblin_challenge(value) is True
        else:
            with pytest.raises(asyncio.CancelledError if kind=='cancel' else RuntimeError):
                await goblin_challenge.check_goblin_challenge(value)
        value.message.respond.assert_not_awaited()
        if branch=='complete':
            claim.assert_awaited_once();complete.assert_awaited_once();sent.assert_awaited_once()
        else:
            claim.assert_not_awaited();complete.assert_not_awaited();sent.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('panel,default',[('tactical','⚔️'),('flexible','🎮'),('fwa','🏳️'),('cwl','🏆')])
@pytest.mark.parametrize('kind',['expected','cancel','unexpected'])
def test_each_custom_emoji_fallback_is_narrow(monkeypatch,panel,default,kind):
    class BadEmoji:
        def __init__(self,value):pass
        @property
        def partial_emoji(self):
            if kind=='expected':raise ValueError('synthetic-malformed-emoji')
            raise error(kind)
    import utils.emoji
    monkeypatch.setattr(utils.emoji,'EmojiType',BadEmoji)
    async def run():
        clan={'tag':'#P2Y','name':'Synthetic clan','emoji':'<:malformed:value>'}
        lists=([clan],[]) if panel=='tactical' else (([],[clan]) if panel=='flexible' else ([clan],))
        queries=iter(lists)
        mongo=NS(clans=NS(find=lambda q:NS(to_list=AsyncMock(return_value=next(queries)))))
        ctx=NS(respond=AsyncMock());captured=[];original=family_links.SelectOption
        def option(**kwargs):captured.append(kwargs);return original(**kwargs)
        monkeypatch.setattr(family_links,'SelectOption',option)
        fn=(family_links.family_links_war_clans_handler if panel in ('tactical','flexible') else
            family_links.family_links_fwa_clans_handler if panel=='fwa' else family_links.family_links_cwl_clans_handler)
        if kind=='expected':
            await fn(ctx,'synthetic',mongo=mongo,bot=object())
            ctx.respond.assert_awaited_once();assert captured[0]['emoji']==default
        else:
            with pytest.raises(asyncio.CancelledError if kind=='cancel' else RuntimeError):
                await fn(ctx,'synthetic',mongo=mongo,bot=object())
            ctx.respond.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('kind',['expected','cancel','unexpected','partial'])
def test_optional_category_name_does_not_change_capacity_or_hide_unexpected(monkeypatch,kind):
    async def run():
        fetch=AsyncMock(return_value=NS()) if kind=='partial' else AsyncMock(side_effect=error(kind))
        rest=NS(fetch_guild_channels=AsyncMock(return_value=[]),fetch_channel=fetch,fetch_user=AsyncMock())
        if kind in ('expected','partial'):
            assert await tickets.check_category_space(NS(rest=rest),1,'synthetic',2,3)==50
        else:
            with pytest.raises(asyncio.CancelledError if kind=='cancel' else RuntimeError):
                await tickets.check_category_space(NS(rest=rest),1,'synthetic',2,3)
        rest.fetch_user.assert_not_awaited()
    asyncio.run(run())


def test_malformed_category_membership_fails_closed_without_warning_send():
    rest=NS(fetch_guild_channels=AsyncMock(return_value=[NS(parent_id='malformed')]),fetch_channel=AsyncMock(),fetch_user=AsyncMock())
    assert asyncio.run(tickets.check_category_space(NS(rest=rest),1,'synthetic',2,3))==-1
    rest.fetch_user.assert_not_awaited()


@pytest.mark.parametrize('trial',[False,True])
@pytest.mark.parametrize('kind',['expected','cancel','unexpected','partial'])
def test_each_clan_lookup_fallback_and_cancellation(monkeypatch,trial,kind):
    async def run():
        clan=NS(tag='#P2Y',name='Synthetic clan',emoji='',th_requirements=[],th_attribute=None,thread_id=None)
        monkeypatch.setattr(hub,'get_clans_by_type',AsyncMock(return_value=[clan]))
        monkeypatch.setattr(hub,'Clan',lambda data:clan)
        monkeypatch.setattr(hub,'format_th_requirement',lambda *args:'Synthetic requirement')
        upstream=(coc.Maintenance(503,{'reason':'inMaintenance'}) if kind=='expected' else
                  KeyError('synthetic-missing-field') if kind=='partial' else error(kind))
        client=NS(get_clan=AsyncMock(side_effect=upstream))
        mongo=NS(clans=NS(find=lambda q:NS(to_list=AsyncMock(return_value=[{}]))))
        ctx=NS(guild_id=1,respond=AsyncMock())
        async def call():
            if trial:
                await hub.show_trial_clans(ctx,'synthetic',mongo=mongo,coc_client=client,bot=object())
                return ctx.respond.call_args.kwargs['components']
            return await hub.build_clan_list_components(ctx,'Competitive',hikari.Color(1),mongo,client,object())
        if kind in ('expected','partial'):
            parts=await call()
            text=' '.join(c.content for part in parts for c in part.components if hasattr(c,'content'))
            assert 'Unranked' in text
        else:
            with pytest.raises(asyncio.CancelledError if kind=='cancel' else RuntimeError):await call()
    asyncio.run(run())


def test_no_bare_catches_remain_in_the_five_scoped_handlers():
    for name in ('extensions/events/message/how_to_ping.py','extensions/events/message/goblin_challenge.py',
                 'extensions/commands/family_links.py','extensions/commands/tickets_legacy/handlers.py',
                 'extensions/commands/clan/info_hub/handlers.py'):
        tree=ast.parse(Path(name).read_text())
        assert not any(isinstance(n,ast.ExceptHandler) and n.type is None for n in ast.walk(tree)),name

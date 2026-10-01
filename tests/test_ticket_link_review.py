import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from extensions.commands.tickets import account_sync, link_review, console, store
from utils import recruit_links
from tests.test_ticket_storage_foundation import _mongo, _ticket, NOW
from tests.test_recruit_links import providers


def setup():
    ticket=_ticket()
    ticket['linked_accounts']={'revision':1,'conflict_key':'key','conflicting_tags':['#PYY','#QCC'],'unavailable_sources':[]}
    data={'ticket_id':ticket['_id'],'user_id':ticket['user_id'],'conflict_key':'key','conflicting_tags':['#PYY','#QCC'],'ticket_rev':ticket['rev'],'status':'open'}
    return _mongo(ticket), ticket, data


def test_review_saves_all_accounts_and_audit_once():
    mongo,ticket,data=setup()
    async def run():
        assert await link_review.save_review(mongo,data,reason='Reviewed old Discord links',actor_id=99,actor_name='Staff')
        assert not await link_review.save_review(mongo,data,reason='duplicate review',actor_id=99,actor_name='Staff')
    asyncio.run(run())
    saved=mongo.tickets.documents[ticket['_id']]
    assert saved['status']=='open'
    assert saved['linked_accounts']['conflict_review']['tags']==['#PYY','#QCC']
    assert saved['linked_accounts']['conflict_review']['reviewed_by']==99
    assert saved['account_identity_audit'][-1]['event']=='linked_account_conflicts_reviewed'


@pytest.mark.parametrize('change',[{'user_id':999},{'rev':99},{'status':'denied'},{'key':'changed'},{'unavailable':['ClashKing']}])
def test_changed_ticket_or_conflicts_cannot_be_reviewed(change):
    mongo,ticket,data=setup();saved=mongo.tickets.documents[ticket['_id']]
    if 'key' in change: saved['linked_accounts']['conflict_key']=change['key']
    elif 'unavailable' in change: saved['linked_accounts']['unavailable_sources']=change['unavailable']
    else: saved.update(change)
    assert not asyncio.run(link_review.save_review(mongo,data,reason='Reviewed all accounts',actor_id=99,actor_name='Staff'))


@pytest.mark.parametrize('reason',['','  ','a'*1001])
def test_invalid_reason_does_not_save(reason):
    mongo,ticket,data=setup()
    assert not asyncio.run(link_review.save_review(mongo,data,reason=reason,actor_id=99,actor_name='Staff'))


def test_exact_owner_fingerprint_changes_even_when_tags_same(monkeypatch):
    providers(monkeypatch,lambda q: [] if 'discord_ids' in q else [{'player_tag':'#PYY','user_id':'456'}],[{'tag':'#PYY','userId':'123'}])
    first=asyncio.run(recruit_links.resolve(123))
    providers(monkeypatch,lambda q: [] if 'discord_ids' in q else [{'player_tag':'#PYY','user_id':'789'}],[{'tag':'#PYY','userId':'123'}])
    second=asyncio.run(recruit_links.resolve(123))
    assert first.conflicts==second.conflicts
    assert first.conflict_key!=second.conflict_key


@pytest.mark.parametrize('key,user,unavailable,accepted',[('key',123,(),True),('changed',123,(),False),('key',999,(),False),('key',123,('ClashKing',),False)])
def test_only_exact_complete_review_restores_disputed_accounts(monkeypatch,key,user,unavailable,accepted):
    links=recruit_links.LinksResult(sources={'#QCC':('ClashPerk',)},conflicts=('#PYY',),conflict_key='key',disputed_sources={'#PYY':('ClashPerk',)},unavailable=unavailable)
    async def lookup(*a,**kw): return links
    async def load(*a,linked_result,**kw): return linked_result
    monkeypatch.setattr(recruit_links,'resolve',lookup)
    monkeypatch.setattr(account_sync,'_load_accounts',load)
    result=asyncio.run(account_sync.load_accounts(None,123,conflict_review={'conflict_key':key,'user_id':user}))
    assert ('#PYY' in result.sources)==accepted
    assert bool(result.conflicts)!=accepted


def test_changed_external_mapping_invalidates_saved_review():
    mongo,ticket,data=setup();ticket['linked_accounts']['conflict_review']={'conflict_key':'old'}
    update,_,_=account_sync._success_update(ticket,source='automatic_retry',at=NOW,accounts=[],conflict_key='new')
    assert 'linked_accounts.conflict_review' in update['$unset']


@pytest.mark.parametrize('owner,guild,allowed',[(99,10,True),(98,10,True),(99,11,True),(99,10,False)])
def test_session_checks_owner_guild_and_current_permission(monkeypatch,owner,guild,allowed):
    async def get(*a): return {'type':'ticket_link_review','owner_id':99,'guild_id':10}
    async def auth(*a): return allowed
    monkeypatch.setattr(link_review,'get_state',get);monkeypatch.setattr(link_review.perms,'is_recruiter',auth)
    ctx=SimpleNamespace(user=SimpleNamespace(id=owner),guild_id=guild,member=object())
    assert bool(asyncio.run(link_review.session(ctx,None,'token')))==(owner==99 and guild==10 and allowed)


def test_console_result_routes_to_review_prompt(monkeypatch):
    async def prompt(*a): return ['review']
    monkeypatch.setattr(link_review,'prompt',prompt)
    result=store.Transition(store.BLOCKED,{'_id':'ticket'},link_review.REASON)
    assert asyncio.run(console._transition_result_panel(result,verb='approved',mongo=None,owner_id=99,guild_id=10))==['review']


def test_slash_approve_routes_to_same_review(monkeypatch):
    from extensions.commands.tickets import close, resolve
    calls=[]
    async def auth(*a): return True
    async def find(*a): return {'_id':'ticket'}
    async def approve(*a,**kw): return store.Transition(store.BLOCKED,{'_id':'ticket'},link_review.REASON)
    async def prompt(*a): return ['review']
    async def defer(**kw): pass
    async def respond(*a,**kw): calls.append(kw)
    monkeypatch.setattr(close.perms,'is_recruiter',auth)
    monkeypatch.setattr(close.store,'find_by_location',find)
    monkeypatch.setattr(resolve,'approve_ticket',approve)
    monkeypatch.setattr(link_review,'prompt',prompt)
    ctx=SimpleNamespace(defer=defer,respond=respond,member=object(),channel_id=1,guild_id=10,user=SimpleNamespace(id=99,username='Staff'))
    asyncio.run(close.Approve().invoke(ctx,mongo=object(),bot=object()))
    assert calls[-1]['components']==['review']


def test_modal_continues_shared_approval_and_disables_mentions(monkeypatch):
    from extensions.commands.tickets import resolve
    calls=[]
    async def sess(*a): return {'ticket_id':'ticket'}
    async def save(*a,**kw): calls.append(('reason',kw['reason']));return True
    async def approve(*a,**kw): calls.append(('approve',kw['ticket_id']));return store.Transition(store.BLOCKED,{'_id':'ticket'},'blacklist')
    async def render(*a,**kw): return ['result']
    async def defer(**kw): assert kw['ephemeral']
    async def edit(**kw): calls.append(('edit',kw))
    monkeypatch.setattr(link_review,'session',sess);monkeypatch.setattr(link_review,'save_review',save)
    monkeypatch.setattr(resolve,'approve_ticket',approve)
    monkeypatch.setattr(console,'_modal_value',lambda *a:'Reviewed all old links')
    monkeypatch.setattr(console,'_transition_result_panel',render)
    ctx=SimpleNamespace(defer=defer,interaction=SimpleNamespace(edit_initial_response=edit),user=SimpleNamespace(id=99,username='Staff'),member=object(),guild_id=10)
    asyncio.run(link_review.submit(ctx,'token',mongo=object(),bot=object()))
    assert ('approve','ticket') in calls
    assert calls[-1][1]['mentions_everyone'] is False


def test_no_does_not_save_review_or_approve(monkeypatch):
    async def sess(*a): return {'ticket_id':'ticket'}
    async def forbidden(*a,**kw): raise AssertionError('No must not mutate review')
    async def defer(**kw): pass
    async def edit(**kw): pass
    monkeypatch.setattr(link_review,'session',sess);monkeypatch.setattr(link_review,'save_review',forbidden)
    asyncio.run(link_review.no(SimpleNamespace(defer=defer,interaction=SimpleNamespace(edit_initial_response=edit)),'token',mongo=object()))

import asyncio
from types import SimpleNamespace

import pytest

from utils import recruit_links, clashperk_links
from extensions.commands.tickets import account_sync, player_info
from extensions.commands.accounts import AccountEntry, AccountsData
from tests.test_ticket_storage_foundation import _mongo, _ticket as _base_ticket, NOW


def _ticket(**values):
    ticket = _base_ticket()
    ticket.update(values)
    return ticket


def providers(monkeypatch, ck, cp):
    async def king(**kwargs):
        return ck(kwargs) if callable(ck) else ck
    async def perk(**kwargs):
        return cp(kwargs) if callable(cp) else cp
    monkeypatch.setattr(recruit_links.clash_links,'_lookup_shared_links',king)
    monkeypatch.setattr(recruit_links.clashperk_links,'lookup',perk)


def test_union_dedup_and_verification(monkeypatch):
    providers(monkeypatch,[{'user_id':'123','player_tag':'#PYY'}],
        [{'userId':'123','tag':'#PYY','verified':False},{'userId':'123','tag':'#QCC','verified':True},{'userId':'999','tag':'#GCC'}])
    result=asyncio.run(recruit_links.resolve(123))
    assert result.sources == {'#PYY':('ClashKing','ClashPerk'),'#QCC':('ClashPerk',)}
    assert result.verified == {'#PYY':False,'#QCC':True}
    assert not result.unavailable and not result.conflicts


def test_reverse_conflict_is_quarantined(monkeypatch):
    providers(monkeypatch,lambda kw: [] if 'discord_ids' in kw else [{'user_id':'999','player_tag':'#PYY'}],
        [{'userId':'123','tag':'#PYY'}])
    result=asyncio.run(recruit_links.resolve(123))
    assert result.sources == {}
    assert result.conflicts == ('#PYY',)


@pytest.mark.parametrize('ck,cp,unavailable',[(None,[],('ClashKing',)),([],None,('ClashPerk',)),(None,None,('ClashKing','ClashPerk'))])
def test_empty_is_distinct_from_outage(monkeypatch,ck,cp,unavailable):
    providers(monkeypatch,ck,cp)
    assert asyncio.run(recruit_links.resolve(123)).unavailable == unavailable


def test_reject_foreign_and_malformed_tags(monkeypatch):
    providers(monkeypatch,[],[{'userId':'123','tag':'#BAD<script>'},{'userId':'999','tag':'#PYY'},{'userId':'123','tag':'#'}])
    assert not asyncio.run(recruit_links.resolve(123)).sources


def test_partial_preserves_history_and_requests_retry():
    ticket=_ticket(linked_accounts={'state':'ready','current':[{'tag':'#PYY','link_sources':['ClashPerk']}], 'current_tags':['#PYY']})
    update,added,removed=account_sync._success_update(ticket,source='recruiter_refresh',at=NOW,accounts=[{'tag':'#QCC','link_sources':['ClashKing']}],unavailable=('ClashPerk',))
    assert set(update['$set']['linked_accounts.current_tags']) == {'#PYY','#QCC'}
    assert not removed
    assert update['$set']['linked_accounts.retry_required']
    assert update['$set']['linked_accounts.context_refresh_required']


def test_recovery_removes_unlinked_but_keeps_history():
    ticket=_ticket(player_tags=['#PYY'],linked_accounts={'state':'ready','current':[{'tag':'#PYY'}],'current_tags':['#PYY']})
    update,added,removed=account_sync._success_update(ticket,source='automatic_retry',at=NOW,accounts=[])
    assert removed == ('#PYY',)
    assert update['$set']['linked_accounts.state']=='empty'
    assert 'player_tags' not in update['$set']


def test_conflict_not_retained_as_current_during_outage():
    ticket=_ticket(linked_accounts={'state':'ready','current':[{'tag':'#PYY'}],'current_tags':['#PYY']})
    update,_,_=account_sync._success_update(ticket,source='automatic_retry',at=NOW,accounts=[],unavailable=('ClashKing',),conflicts=('#PYY',))
    assert not update['$set']['linked_accounts.current_tags']
    assert update['$set']['linked_accounts.state']=='failed'


def test_persist_provenance_and_clan(monkeypatch):
    ticket=_ticket(); mongo=_mongo(ticket)
    profile=SimpleNamespace(name='Player',town_hall=17,clan_name='WU',clan_tag='#QCC')
    async def load(*a,**kw):
        return AccountsData(entries=(AccountEntry('#PYY','loaded',profile,('ClashPerk',),False),))
    monkeypatch.setattr(account_sync,'load_accounts',load)
    result=asyncio.run(account_sync.sync_ticket_accounts(mongo,None,ticket['_id'],source='recruiter_refresh'))
    account=result.snapshot.current_accounts[0]
    assert account.link_sources==('ClashPerk',)
    assert account.clan_name=='WU' and account.town_hall==17
    assert account.clashperk_verified is False


def test_player_pages_fit_and_expose_all_accounts():
    accounts=[{'tag':'#P'+str(i).zfill(3),'name':'*'*100,'town_hall':18,'clan_name':'*'*100,'profile_status':'loaded','link_sources':['ClashKing','ClashPerk']} for i in range(46)]
    ticket=_ticket(linked_accounts={'state':'ready','current':accounts,'current_tags':[a['tag'] for a in accounts]})
    def texts(node):
        if isinstance(node,dict):
            return ([node['content']] if 'content' in node else []) + sum((texts(v) for v in node.values()),[])
        if isinstance(node,(list,tuple)): return sum((texts(v) for v in node),[])
        return []
    for page in range(1,7):
        content=texts([c.build() for c in player_info.panel(ticket,page)])
        assert sum(map(len,content)) <= 4000
        assert all(len(t)<=4000 for t in content)


def test_unauthorized_cannot_read_ticket(monkeypatch):
    async def denied(*a,**k): return False
    async def forbidden(*a,**k): raise AssertionError('DB lookup before authorization')
    monkeypatch.setattr(player_info.perms,'is_recruiter',denied)
    monkeypatch.setattr(player_info.store,'find_one',forbidden)
    assert asyncio.run(player_info._get_ticket(SimpleNamespace(member=None),None,'ticket')) is None


class Response:
    def __init__(self,status,payload): self.status,self.payload=status,payload
    async def __aenter__(self): return self
    async def __aexit__(self,*a): pass
    async def json(self): return self.payload


class Session:
    def __init__(self,responses): self.responses=list(responses);self.calls=[]
    async def __aenter__(self): return self
    async def __aexit__(self,*a): pass
    def post(self,url,**kwargs):
        assert kwargs['allow_redirects'] is False
        self.calls.append((url,kwargs))
        return self.responses.pop(0)


def setup_session(monkeypatch,responses):
    monkeypatch.setenv('CLASHPERK_PASSKEY','test-only-key')
    monkeypatch.setattr(clashperk_links,'_token','')
    monkeypatch.setattr(clashperk_links,'_lock',asyncio.Lock())
    session=Session(responses)
    monkeypatch.setattr(clashperk_links.aiohttp,'ClientSession',lambda **kw:session)
    return session


def test_token_401_refresh_and_batching(monkeypatch):
    session=setup_session(monkeypatch,[Response(201,{'accessToken':'first'}),Response(401,{}),Response(201,{'accessToken':'second'}),Response(200,[]),Response(200,[])])
    result=asyncio.run(clashperk_links.lookup(discord_ids=[str(i) for i in range(101)]))
    assert result == []
    queries=[body for url,body in session.calls if url.endswith('/query')]
    assert [len(b['json']['userIds']) for b in queries]==[100,100,1]
    assert queries[-1]['headers']['Authorization']=='Bearer second'


def test_failed_second_batch_is_not_partial_success(monkeypatch):
    setup_session(monkeypatch,[Response(200,{'accessToken':'token'}),Response(200,[{'tag':'#PYY'}]),Response(429,{})])
    assert asyncio.run(clashperk_links.lookup(discord_ids=[str(i) for i in range(101)])) is None


@pytest.mark.parametrize('payload',[{},'unexpected',[1]])
def test_malformed_response_is_unavailable(monkeypatch,payload):
    setup_session(monkeypatch,[Response(200,{'accessToken':'token'}),Response(200,payload)])
    assert asyncio.run(clashperk_links.lookup(discord_ids=['123'])) is None


@pytest.mark.parametrize('unavailable,conflicts,expected',[((),(),True),(('ClashKing',),(),False),((),('#QCC',),False)])
def test_approval_uses_combined_completeness(monkeypatch,unavailable,conflicts,expected):
    from extensions.commands.tickets import resolve, store
    from tests.test_ticket_resolution_identity_races import _patch_approval, LockCollection
    transitions=[]
    mongo,ticket=_patch_approval(monkeypatch,LockCollection(),blacklisted=lambda:False,transitions=transitions)
    async def sync(*a,**kw):
        return account_sync.AccountSyncResult(ticket,account_sync.AccountSnapshot(
            state='ready',current_accounts=(account_sync.LinkedAccount('#PYY',link_sources=('ClashPerk',)),),current_tags=('#PYY',),observed_tags=('#PYY',),retry_required=bool(unavailable or conflicts),unavailable_sources=unavailable,conflicting_tags=conflicts))
    monkeypatch.setattr(account_sync,'sync_ticket_accounts',sync)
    result=asyncio.run(resolve.approve_ticket(object(),mongo,ticket_id=ticket['_id'],member=SimpleNamespace(id=9),actor_name='Recruiter'))
    assert (result.outcome==store.WON)==expected
    assert bool(transitions)==expected


def test_staff_context_with_profiles_flags_history_fits(monkeypatch):
    from extensions.commands.tickets import console
    from tests.test_ticket_console import _ticket as fixture_ticket, _assert_component_limits
    ticket=fixture_ticket(19)
    ticket['linked_accounts']={'state':'ready','current':[{'tag':'#PYY','name':'*'*100,'clan_name':'*'*100,'profile_status':'loaded','link_sources':['ClashKing','ClashPerk']}] * 3}
    async def flags(*a,**kw):
        return [{'_id':str(i),'kind':console.flag_store.FLAG_NOT_LOYAL,'active':True,'reason':'r'*500} for i in range(8)]
    async def history(*a,**kw):
        return [fixture_ticket(i,status='denied',denial_reason='d'*100) for i in range(1,6)]
    monkeypatch.setattr(console.flag_store,'list_for_identity',flags)
    monkeypatch.setattr(console.store,'history_for',history)
    _assert_component_limits(asyncio.run(console.build_staff_identity_context(object(),ticket)))


def test_no_key_does_not_attempt_authentication(monkeypatch):
    monkeypatch.delenv('CLASHPERK_PASSKEY',raising=False)
    class NoNetwork:
        def post(self,*a,**kw): raise AssertionError('Must not send an empty credential')
    assert asyncio.run(clashperk_links._login(NoNetwork())) is None


def test_login_cache_and_key_rotation(monkeypatch):
    session=setup_session(monkeypatch,[Response(200,{'accessToken':'one'}),Response(200,{'accessToken':'two'})])
    async def run():
        assert await clashperk_links._login(session)=='one'
        assert await clashperk_links._login(session)=='one'
        monkeypatch.setenv('CLASHPERK_PASSKEY','rotated')
        assert await clashperk_links._login(session)=='two'
    asyncio.run(run())
    assert len(session.calls)==2

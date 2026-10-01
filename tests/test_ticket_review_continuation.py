import asyncio
from types import SimpleNamespace

import pytest
from extensions.commands.tickets import resolve, account_sync, store
from tests.test_ticket_resolution_identity_races import _patch_approval, LockCollection


def document():
    return {'user_id':30,'linked_accounts':{
        'conflict_key':'exact','current_tags':['#PYY','#QCC'],
        'conflict_review':{'conflict_key':'exact','tags':['#PYY'],'user_id':30,'reason':'Reviewed old links','reviewed_by':99}}}


@pytest.mark.parametrize('change', ['none','new_tag','key','user','unavailable','conflicts','no_reason','missing_current'])
def test_review_only_covers_exact_confirmed_accounts(change):
    ticket=document();linked=ticket['linked_accounts'];review={'new_tags':['#PYY']}
    if change=='new_tag': review['new_tags'].append('#QCC')
    if change=='key': linked['conflict_key']='changed'
    if change=='user': linked['conflict_review']['user_id']=31
    if change=='unavailable': linked['unavailable_sources']=['ClashKing']
    if change=='conflicts': linked['conflicting_tags']=['#PYY']
    if change=='no_reason': linked['conflict_review']['reason']=''
    if change=='missing_current': linked['current_tags']=[]
    assert resolve._conflict_review_covers_fwa_accounts(ticket,review)==(change=='none')


@pytest.mark.parametrize('blacklisted',[False,True])
def test_confirmed_accounts_continue_without_duplicate_prompt_but_keep_blacklist(monkeypatch,blacklisted):
    transitions=[]
    mongo,ticket=_patch_approval(monkeypatch,LockCollection(),blacklisted=lambda:blacklisted,transitions=transitions)
    ticket['ticket_type']='fwa'
    details=document()['linked_accounts']
    details['conflict_review']['user_id']=ticket['user_id']
    details['approval_review']={'state':'pending','new_tags':['#PYY'],'account_revision':1}
    ticket['linked_accounts']=details
    async def sync(*a,**k):
        return account_sync.AccountSyncResult(ticket,account_sync.AccountSnapshot(
            state='ready',current_accounts=(account_sync.LinkedAccount('#PYY'),),current_tags=('#PYY',),observed_tags=('#PYY',),retry_required=False,revision=1))
    async def duplicate(*a,**k): raise AssertionError('Must not ask for the same review again')
    monkeypatch.setattr(account_sync,'sync_ticket_accounts',sync)
    monkeypatch.setattr(resolve,'_staff_context_is_fresh_for_review',duplicate)
    result=asyncio.run(resolve.approve_ticket(object(),mongo,ticket_id=ticket['_id'],member=SimpleNamespace(id=99),actor_name='Staff'))
    assert result.outcome==(store.BLOCKED if blacklisted else store.WON)
    assert bool(transitions)==(not blacklisted)

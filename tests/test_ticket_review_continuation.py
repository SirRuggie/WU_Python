import asyncio
from types import SimpleNamespace

import pytest
from extensions.commands.tickets import resolve, account_sync, store
from tests.test_ticket_resolution_identity_races import _patch_approval, LockCollection


def document():
    return {'user_id':30,'linked_accounts':{
        'conflict_key':'exact','current_tags':['#PYY','#QCC'],
        'conflict_review':{'conflict_key':'exact','tags':['#PYY'],'user_id':30,'reason':'Reviewed old links','reviewed_by':99}}}


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
    monkeypatch.setattr(account_sync,'sync_ticket_accounts',sync)
    result=asyncio.run(resolve.approve_ticket(object(),mongo,ticket_id=ticket['_id'],member=SimpleNamespace(id=99),actor_name='Staff'))
    assert result.outcome==(store.BLOCKED if blacklisted else store.WON)
    assert bool(transitions)==(not blacklisted)


@pytest.mark.parametrize('linked', [False, True])
@pytest.mark.parametrize('condition', ['new', 'unavailable', 'conflict', 'lookup_failed', 'context_failed', 'flags_pending'])
def test_only_missing_links_block_account_approval(monkeypatch, linked, condition):
    transitions = []
    mongo, ticket = _patch_approval(
        monkeypatch, LockCollection(), blacklisted=lambda: False,
        transitions=transitions,
    )
    ticket['ticket_type'] = 'fwa'
    ticket['linked_accounts'] = {
        'revision': 1,
        'approval_review': {'state': 'pending', 'account_revision': 1},
        'context_refresh_required': condition == 'context_failed',
        'flag_refresh_required': condition == 'flags_pending',
    }

    async def sync(*args, **kwargs):
        return account_sync.AccountSyncResult(ticket, account_sync.AccountSnapshot(
            state='failed' if condition == 'lookup_failed' else 'ready',
            current_accounts=(account_sync.LinkedAccount('#PYY'),) if linked else (),
            current_tags=('#PYY',) if linked else (),
            observed_tags=('#PYY',), retry_required=condition == 'lookup_failed',
            revision=1,
            unavailable_sources=('ClashKing',) if condition == 'unavailable' else (),
            conflicting_tags=('#QCC',) if condition == 'conflict' else (),
        ))

    async def context_failed(*args, **kwargs):
        raise RuntimeError('staff context unavailable')

    monkeypatch.setattr(account_sync, 'sync_ticket_accounts', sync)
    monkeypatch.setattr(resolve.account_sync, 'confirm_staff_context_queued', context_failed)
    from extensions.commands.tickets import console
    monkeypatch.setattr(console, 'queue_staff_identity_context', context_failed)
    result = asyncio.run(resolve.approve_ticket(
        object(), mongo, ticket_id=ticket['_id'],
        member=SimpleNamespace(id=99), actor_name='Staff',
    ))
    assert result.outcome == (store.WON if linked else store.BLOCKED)
    assert bool(transitions) == linked
    if not linked:
        assert result.reason == 'approval requires at least one linked Clash account'

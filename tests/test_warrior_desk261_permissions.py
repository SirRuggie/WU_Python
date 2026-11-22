"""261 accepted per-type action matrix; isolated fixtures only."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest
from extensions.commands.tickets import perms

GUILD = 644963518025826315
CONFIG = {
    '_id': 'config', 'ticket_target_guild_id': GUILD,
    'main_thread_recruiter_role': 100,
    'fwa_thread_recruiter_role': 101,
    'account_thread_recruiter_role': 102,
    'staff_thread_recruiter_role': 103,
}
EXPECTED = {
    'admin': {'main', 'fwa', 'account', 'staff'},
    'main': {'main', 'fwa', 'account'},
    'fwa': {'main', 'fwa', 'account'},
    'account': {'account'},
    'staff': {'staff'},
    'none': set(),
}

@pytest.mark.parametrize('actor', EXPECTED)
@pytest.mark.parametrize('kind', ['main', 'fwa', 'account', 'staff'])
def test_261_accepted_action_and_console_matrix(actor, kind):
    role = {'main': 100, 'fwa': 101, 'account': 102, 'staff': 103}.get(actor)
    member = SimpleNamespace(id=50, guild_id=GUILD,
        permissions=hikari.Permissions.ADMINISTRATOR if actor=='admin' else hikari.Permissions.NONE,
        role_ids=[role] if role else [])
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value=CONFIG)))
    assert asyncio.run(perms.can_handle(member, mongo, kind)) is (kind in EXPECTED[actor])
    assert asyncio.run(perms.is_ticket_staff(member, mongo)) is bool(EXPECTED[actor])

@pytest.mark.parametrize('actor', EXPECTED)
def test_261_other_guild_never_inherits_ticket_access(actor):
    role = {'main':100,'fwa':101,'account':102,'staff':103}.get(actor)
    member = SimpleNamespace(id=50, guild_id=GUILD+1,
        permissions=hikari.Permissions.ADMINISTRATOR if actor=='admin' else hikari.Permissions.NONE,
        role_ids=[role] if role else [])
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value=CONFIG)))
    assert not asyncio.run(perms.is_ticket_staff(member, mongo))
    for kind in ['main','fwa','account','staff']:
        assert not asyncio.run(perms.can_handle(member, mongo, kind))


@pytest.mark.parametrize('kind,expected', [
    ('main', {100,101}), ('fwa', {100,101}),
    ('account', {100,101,102}), ('staff', {103}),
])
def test_shared_staff_parent_never_unions_other_ticket_roles(kind, expected):
    from extensions.commands.tickets import thread_service
    config={**CONFIG,'main_candidate_parent':20,'fwa_candidate_parent':20,
        'main_staff_parent':21,'fwa_staff_parent':21,'desk_channel_id':30,
        'desk_staff_parent':21,'ticket_staff_viewer_role_ids':[999]}
    parents=thread_service.parents_from_config(config,GUILD,kind)
    from utils.ticket_access import ticket_type_role_ids
    actual=set(ticket_type_role_ids(config,kind))
    assert actual==expected
    assert parents.staff_viewer_role_ids == (999,)

class Members:
    def __init__(self, items):
        self.items = items
    def limit(self, count):
        return Members(self.items[:count])
    def __aiter__(self):
        async def iterate():
            for item in self.items:
                yield item
        return iterate()


def test_private_role_recovery_does_not_reassign_roles_to_other_types():
    from extensions.commands.tickets import thread_service
    state = {'candidate_parent_id':30,'staff_parent_id':21,'recruiter_role_id':103,
        'staff_thread_private':True,'staff_role_config':{'main':100,'fwa':101,'account':102,'staff':103},
        'shared_staff_role_ids':[100,101,102],'staff_viewer_role_ids':[999]}
    cfg = thread_service._recovery_config(state,'staff',GUILD)
    parents = thread_service.parents_from_config(cfg,GUILD,'staff')
    assert parents.recruiter_role_id == 103
    assert parents.staff_parent_id == 21
    assert parents.staff_viewer_role_ids == (999,)


@pytest.mark.parametrize('private',[True,False])
def test_existing_staff_pair_is_retained_without_enumeration_or_reparent(monkeypatch,private):
    from extensions.commands.tickets import thread_service
    state={'_id':'creation','ticket_number':1,'candidate_name':'fixture-candidate','staff_name':'fixture-staff',
        'guild_id':GUILD,'user_id':10,'username':'Fixture','ticket_type':'account',
        'candidate_parent_id':20,'staff_parent_id':99,'staff_thread_private':private,
        'candidate_thread_id':201,'staff_thread_id':202}
    channels=[SimpleNamespace(id=201,is_archived=False,is_locked=False),
              SimpleNamespace(id=202,is_archived=False,is_locked=False)]
    fetch=AsyncMock(side_effect=channels)
    monkeypatch.setattr(thread_service,'_fetch_or_recover_thread',fetch)
    monkeypatch.setattr(thread_service,'_unarchive_if_needed',AsyncMock(side_effect=lambda rest,ch:ch))
    async def update(mongo,creation,owner,**values):state.update(values);return dict(state)
    monkeypatch.setattr(thread_service,'_state_update',update)
    rest=SimpleNamespace(create_thread=AsyncMock(),add_thread_member=AsyncMock(),fetch_members=AsyncMock())
    asyncio.run(thread_service._ensure_live_thread_pair(rest=rest,mongo=SimpleNamespace(),state=state,owner='owner',bot_user_id=99))
    rest.create_thread.assert_not_awaited();rest.fetch_members.assert_not_called()
    rest.add_thread_member.assert_awaited_once_with(201,10)
    assert state['staff_parent_id']==99 and state['staff_thread_private'] is private


@pytest.mark.parametrize('admin',[False,True])
def test_guided_private_readiness_checks_actual_role_combinations(monkeypatch,admin):
    from tests.test_ticket_creation import _valid_parent_rest
    from extensions.commands.tickets import thread_service
    rest=_valid_parent_rest(mentionable=True,bot_can_mention=True)
    original=rest.fetch_roles
    async def roles(guild):
        items=await original(guild)
        for role in items:
            if int(role.id)==40:role.permissions &= ~hikari.Permissions.MANAGE_THREADS
        items.append(SimpleNamespace(id=51,permissions=hikari.Permissions.MANAGE_THREADS,is_managed=False))
        return items
    rest.fetch_roles=roles
    member=SimpleNamespace(id=3,guild_id=10,display_name='Unapproved member',role_ids=[70] if admin else [50,51])
    rest.fetch_members=lambda guild:Members([member])
    parents=thread_service.ThreadParents(10,20,21,40,desk_permission_policy=True)
    if admin:
        channels=asyncio.run(thread_service.validate_thread_parents(rest,parents,bot_user_id=99))
        assert [channel.id for channel in channels]==[20,21]
    else:
        with pytest.raises(thread_service.ThreadConfigurationError,match='non-admin member Unapproved member bypasses'):
            asyncio.run(thread_service.validate_thread_parents(rest,parents,bot_user_id=99))


@pytest.mark.parametrize('role_config', [None, {'staff': 'invalid'}, {'unknown': 103}])
def test_malformed_desk_recovery_does_not_abort_later_valid_creation(monkeypatch, role_config):
    from extensions.commands.tickets import thread_service
    from extensions.commands import ticket_runtime
    state=dict(_id='thread:50:staff',kind='thread_ticket_creation',state='creating',
        guild_id=GUILD,user_id=50,ticket_type='staff',candidate_parent_id=30,
        staff_parent_id=21,recruiter_role_id=103,staff_thread_private=True,
        open_slot_id='ticket-open:50:staff',creation_workflow_id='thread:50:staff')
    if role_config is not None:state['staff_role_config']=role_config
    valid={**state,'_id':'thread:51:main','user_id':51,'ticket_type':'main',
        'recruiter_role_id':100,'open_slot_id':'ticket-open:51:main',
        'creation_workflow_id':'thread:51:main','staff_role_config':{'main':100,'fwa':101}}
    class Cursor:
        def sort(self,*args):return self
        def limit(self,n):assert n==50;return self
        async def to_list(self,*,length):assert length==50;return [state,valid]
    db=SimpleNamespace(ticket_creation_state=SimpleNamespace(find=lambda q:Cursor()),
        ticket_open_slots=SimpleNamespace(find_one=AsyncMock(return_value={'state':ticket_runtime.SLOT_RESERVED})))
    monkeypatch.setattr(thread_service,'ensure_creation_indexes',AsyncMock())
    resume=AsyncMock(return_value=ticket_runtime.SlotClaim(True,'owner',{'_id':valid['open_slot_id']}))
    monkeypatch.setattr(ticket_runtime,'resume_open_slot',resume)
    create=AsyncMock(return_value=thread_service.CreatedThreadTicket({'_id':'ticket_261'},resumed=True))
    monkeypatch.setattr(thread_service,'create_live_thread_ticket',create)
    counts=asyncio.run(thread_service.recover_pending_thread_ticket_creations(bot=object(),mongo=db))
    assert counts=={'processed':2,'completed':1,'degraded':0,'failed':1}
    db.ticket_open_slots.find_one.assert_awaited_once_with({'_id':valid['open_slot_id']})
    resume.assert_awaited_once()
    assert resume.await_args.kwargs['workflow_id']==valid['_id']
    create.assert_awaited_once()
    assert create.await_args.kwargs['ticket_type']=='main'
    assert create.await_args.kwargs['config']['main_thread_recruiter_role']==100

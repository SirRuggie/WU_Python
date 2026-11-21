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
    actual=set(parents.staff_thread_role_ids)
    assert actual==expected
    assert parents.staff_viewer_role_ids == (999,)
    assert parents.private_staff

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


def test_private_invites_remove_stale_roles_before_adding_exact_handlers():
    from extensions.commands.tickets import thread_service
    members = [SimpleNamespace(id=key, guild_id=GUILD, role_ids=roles, is_bot=False)
               for key, roles in [(1, [100]), (2, [102]), (3, [103]), (4, [999])]]
    actions = []
    async def remove(thread, member): actions.append(('remove', thread, member))
    async def add(thread, member): actions.append(('add', thread, member))
    async def fresh(guild, key): return next(member for member in members if member.id == key)
    rest = SimpleNamespace(fetch_members=lambda guild: Members(members),
        fetch_thread_members=lambda thread: Members([SimpleNamespace(user_id=3), SimpleNamespace(user_id=99)]),
        fetch_member=fresh, remove_thread_member=remove, add_thread_member=add)
    asyncio.run(thread_service.sync_private_staff_members(rest, guild_id=GUILD,
        thread_id=45, role_ids={100,101,102}, bot_user_id=99))
    assert actions == [('remove',45,3),('add',45,1),('add',45,2)]


def test_private_invites_role_loss_during_scan_does_not_grant_access():
    from extensions.commands.tickets import thread_service
    old = SimpleNamespace(id=1, guild_id=GUILD, role_ids=[103], is_bot=False)
    rest = SimpleNamespace(fetch_members=lambda guild: Members([old]),
        fetch_thread_members=lambda thread: Members([]),
        fetch_member=AsyncMock(return_value=SimpleNamespace(id=1, guild_id=GUILD, role_ids=[])),
        remove_thread_member=AsyncMock(), add_thread_member=AsyncMock())
    asyncio.run(thread_service.sync_private_staff_members(rest,guild_id=GUILD,
        thread_id=45,role_ids={103},bot_user_id=99))
    rest.add_thread_member.assert_not_awaited()


def test_private_member_scan_bound_fails_before_any_permission_write(monkeypatch):
    from extensions.commands.tickets import thread_service
    monkeypatch.setattr(thread_service, 'STAFF_MEMBER_SCAN_LIMIT', 1)
    rest = SimpleNamespace(fetch_members=lambda guild: Members([
        SimpleNamespace(id=1), SimpleNamespace(id=2)]),
        remove_thread_member=AsyncMock(), add_thread_member=AsyncMock())
    with pytest.raises(thread_service.ThreadConfigurationError, match='safe bound'):
        asyncio.run(thread_service.sync_private_staff_members(rest,guild_id=GUILD,
            thread_id=45,role_ids={103},bot_user_id=99))
    rest.remove_thread_member.assert_not_awaited()
    rest.add_thread_member.assert_not_awaited()


def test_cleared_handler_configuration_revokes_explicit_private_invites():
    from extensions.commands.tickets import thread_service
    rest = SimpleNamespace(fetch_members=lambda guild: Members([]),
        fetch_thread_members=lambda thread: Members([SimpleNamespace(user_id=3),SimpleNamespace(user_id=99)]),
        remove_thread_member=AsyncMock(), add_thread_member=AsyncMock())
    asyncio.run(thread_service.sync_private_staff_members(rest,guild_id=GUILD,
        thread_id=45,role_ids=(),bot_user_id=99))
    rest.remove_thread_member.assert_awaited_once_with(45,3)
    rest.add_thread_member.assert_not_awaited()


def test_private_role_recovery_does_not_reassign_roles_to_other_types():
    from extensions.commands.tickets import thread_service
    state = {'candidate_parent_id':30,'staff_parent_id':21,'recruiter_role_id':103,
        'staff_thread_private':True,'staff_role_config':{'main':100,'fwa':101,'account':102,'staff':103},
        'shared_staff_role_ids':[100,101,102],'staff_viewer_role_ids':[999]}
    cfg = thread_service._recovery_config(state,'staff',GUILD)
    parents = thread_service.parents_from_config(cfg,GUILD,'staff')
    assert parents.private_staff
    assert parents.staff_thread_role_ids == (103,)
    assert parents.staff_viewer_role_ids == (999,)


@pytest.mark.parametrize('private',[True,False])
def test_live_pair_uses_exact_private_invites_and_preserves_old_public_staff_pairs(monkeypatch,private):
    from extensions.commands.tickets import thread_service
    state={'_id':'creation','ticket_number':1,'candidate_name':'fixture-candidate','staff_name':'fixture-staff',
        'guild_id':GUILD,'user_id':10,'username':'Fixture','ticket_type':'account',
        'candidate_parent_id':20,'staff_parent_id':21,'staff_thread_private':private,
        'staff_thread_role_ids':[100,101,102]}
    async def update(mongo,creation,owner,**values):
        state.update(values);return dict(state)
    monkeypatch.setattr(thread_service,'_state_update',update)
    monkeypatch.setattr(thread_service,'_fetch_or_recover_thread',AsyncMock(return_value=None))
    members=[SimpleNamespace(id=key,guild_id=GUILD,role_ids=roles,is_bot=False)
        for key,roles in [(1,[100]),(2,[101]),(3,[102]),(4,[103]),(5,[999]),(10,[])]]
    created=[]
    async def create(parent,kind,name,**kwargs):
        created.append((parent,kind,kwargs))
        return SimpleNamespace(id=200+len(created),is_archived=False,is_locked=False)
    def invited(thread):
        return Members([SimpleNamespace(user_id=99),*([SimpleNamespace(user_id=10)] if thread==201 else [])])
    rest=SimpleNamespace(create_thread=create,add_thread_member=AsyncMock(),remove_thread_member=AsyncMock(),
        fetch_members=lambda guild:Members(members),fetch_thread_members=invited,
        fetch_member=AsyncMock(side_effect=lambda guild,key:next(member for member in members if member.id==key)))
    asyncio.run(thread_service._ensure_live_thread_pair(rest=rest,mongo=SimpleNamespace(),state=state,owner='owner',bot_user_id=99))
    assert created[0][1]==hikari.ChannelType.GUILD_PRIVATE_THREAD
    assert created[1][1]==(hikari.ChannelType.GUILD_PRIVATE_THREAD if private else hikari.ChannelType.GUILD_PUBLIC_THREAD)
    calls=[call.args for call in rest.add_thread_member.await_args_list]
    if private:
        assert calls==[(201,10),(201,1),(201,2),(201,3),(202,1),(202,2),(202,3)]
        assert created[1][2]['invitable'] is False
        rest.remove_thread_member.assert_not_awaited()
    else:
        assert calls==[(201,10)]


def test_role_loss_event_revokes_both_new_private_spaces(monkeypatch):
    from extensions.commands.tickets import staff_access,store
    row={'_id':'ticket_1','guild_id':GUILD,'ticket_type':'account','user_id':10,
        'staff_thread_private':True,'location':{'id':201,'staff_space_id':202}}
    monkeypatch.setattr(store,'private_staff_tickets',AsyncMock(return_value=[row]))
    monkeypatch.setattr(store,'find_one',AsyncMock(return_value=row))
    member=SimpleNamespace(id=3,guild_id=GUILD,role_ids=[])
    rest=SimpleNamespace(fetch_member=AsyncMock(return_value=member),
        fetch_channel=AsyncMock(side_effect=lambda cid:SimpleNamespace(id=cid,guild_id=GUILD,owner_id=99,type=hikari.ChannelType.GUILD_PRIVATE_THREAD)),
        fetch_thread_member=AsyncMock(return_value=SimpleNamespace(user_id=3)),
        remove_thread_member=AsyncMock(),add_thread_member=AsyncMock())
    db=SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value=CONFIG)))
    asyncio.run(staff_access.member_changed(SimpleNamespace(rest=rest,get_me=lambda:SimpleNamespace(id=99)),db,member))
    assert [call.args for call in rest.remove_thread_member.await_args_list]==[(202,3),(201,3)]
    rest.add_thread_member.assert_not_awaited()


def test_foreign_guild_role_event_never_enumerates_private_tickets(monkeypatch):
    from extensions.commands.tickets import staff_access,store
    rows=AsyncMock();monkeypatch.setattr(store,'private_staff_tickets',rows)
    db=SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value=CONFIG)))
    asyncio.run(staff_access.member_changed(SimpleNamespace(get_me=lambda:SimpleNamespace(id=99)),db,
        SimpleNamespace(id=3,guild_id=GUILD+1,role_ids=[100])))
    rows.assert_not_awaited()


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
    member=SimpleNamespace(id=3,guild_id=10,role_ids=[70] if admin else [40,51])
    rest.fetch_members=lambda guild:Members([member])
    parents=thread_service.ThreadParents(10,20,21,40,staff_thread_role_ids=(40,),private_staff=True)
    if admin:
        channels=asyncio.run(thread_service.validate_thread_parents(rest,parents,bot_user_id=99))
        assert [channel.id for channel in channels]==[20,21]
    else:
        with pytest.raises(thread_service.ThreadConfigurationError,match='non-admin member 3 bypasses'):
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

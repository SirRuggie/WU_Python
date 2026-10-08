import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import hikari
import pytest
from extensions.commands.tickets import settings, console, perms, testing
from extensions.commands import manage, ticket_runtime


def ctx():
    return NS(user=NS(id=1),guild_id=2,member=NS(guild_id=2,permissions=hikari.Permissions.ADMINISTRATOR),
              interaction=NS(guild_id=2,values=[],edit_initial_response=AsyncMock()),respond=AsyncMock(),defer=AsyncMock())


def data():
    cfg={'_id':'config','ticket_target_guild_id':2,'main_candidate_parent':3,'main_staff_parent':4,'main_thread_recruiter_role':5,
         'fwa_candidate_parent':3,'fwa_staff_parent':4,'fwa_thread_recruiter_role':6,'ticket_staff_viewer_role_ids':[], 'ticket_inactivity_minutes':10080}
    return {'_id':'a'*32,'type':'ticket_settings','user_id':1,'guild_id':2,'baseline':deepcopy(cfg),'draft':deepcopy(cfg),'manage_token':'b'*32}


def walk(v):
    if isinstance(v,dict):
        yield v
        for x in v.values():yield from walk(x)
    elif isinstance(v,(list,tuple)):
        for x in v:yield from walk(x)


@pytest.mark.parametrize('view',['home','timers','routing','tools','main','fwa','access','panels'])
def test_settings_page_discord_limits_and_registered_actions(view):
    from extensions.components import registered_functions
    d=data();d['view']=view
    nodes=list(walk([c.build() for c in settings.page(d)]))
    assert sum('type' in x for x in nodes)<=40
    for x in nodes:
        if 'custom_id' in x:
            assert len(x['custom_id'])<=100
            assert x['custom_id'].split(':')[0] in registered_functions


@pytest.mark.parametrize('change',[{'user_id':9},{'guild_id':9},{'type':'other'},None])
def test_settings_rejects_wrong_owner_guild_type_and_expiry(monkeypatch,change):
    d=data();d.update(change or {})
    monkeypatch.setattr(settings,'get_state',AsyncMock(return_value=d if change else None))
    monkeypatch.setattr(perms,'is_target_admin',AsyncMock(return_value=True))
    with pytest.raises(ValueError):asyncio.run(settings.session(ctx(),NS(),'token'))


def test_settings_rechecks_admin_permission(monkeypatch):
    monkeypatch.setattr(settings,'get_state',AsyncMock(return_value=data()))
    monkeypatch.setattr(perms,'is_target_admin',AsyncMock(return_value=False))
    with pytest.raises(ValueError):asyncio.run(settings.session(ctx(),NS(),'token'))


@pytest.mark.parametrize('matched',[0,1])
def test_save_uses_cas_audit_and_changes_only_selected_settings(monkeypatch,matched):
    d=data();d['draft']['main_thread_recruiter_role']=99
    audit=NS(insert_one=AsyncMock(),update_one=AsyncMock())
    collection=NS(update_one=AsyncMock(return_value=NS(matched_count=matched)),database=NS(get_collection=Mock(return_value=audit)))
    m=NS(ticket_setup=collection)
    monkeypatch.setattr(settings,'validate',AsyncMock())
    if matched:asyncio.run(settings.save(ctx(),m,NS(),d))
    else:
        with pytest.raises(ValueError,match='changed'):asyncio.run(settings.save(ctx(),m,NS(),d))
    filt,update=collection.update_one.call_args.args
    assert filt['main_thread_recruiter_role']==5 and filt['fwa_thread_recruiter_role']==6
    assert filt['ticket_settings_revision']=={'$exists':False}
    assert update['$set']=={'main_thread_recruiter_role':99}
    assert audit.update_one.call_args.args[1]['$set']['state']==('committed' if matched else 'conflict')


def test_invalid_permissions_never_write_settings(monkeypatch):
    d=data();d['draft']['main_thread_recruiter_role']=99
    m=NS(ticket_setup=NS(update_one=AsyncMock()))
    monkeypatch.setattr(settings,'validate',AsyncMock(side_effect=ValueError('bad permissions')))
    with pytest.raises(ValueError):asyncio.run(settings.save(ctx(),m,NS(),d))
    m.ticket_setup.update_one.assert_not_awaited()


def test_validation_checks_both_types_and_keeps_bound_parent(monkeypatch):
    rest=NS(fetch_my_user=AsyncMock(return_value=NS(id=12)))
    check=AsyncMock();monkeypatch.setattr(settings.thread_service,'validate_thread_parents',check)
    monkeypatch.setattr(ticket_runtime,'get_rollout',AsyncMock(return_value=NS(valid=True,thread_intake=NS(guild_id=2,channel_id=3))))
    d=data();asyncio.run(settings.validate(NS(),rest,d['draft'],2));assert check.await_count==2
    d['draft']['main_candidate_parent']=99
    with pytest.raises(ValueError,match='Candidate channels'):asyncio.run(settings.validate(NS(),rest,d['draft'],2))


def test_history_submit_checks_ownership_before_read(monkeypatch):
    d={'type':'ticket_member_history','owner_id':9,'guild_id':2}
    monkeypatch.setattr(console,'get_state',AsyncMock(return_value=d))
    read=AsyncMock();monkeypatch.setattr(console.store,'history_for',read)
    c=ctx();c.interaction.values=['123']
    asyncio.run(console.member_history_pick(c,'token',mongo=NS()))
    read.assert_not_awaited();c.respond.assert_awaited_once()


def test_history_submit_uses_selected_user_and_private_panel(monkeypatch):
    monkeypatch.setattr(console,'get_state',AsyncMock(return_value={'type':'ticket_member_history','owner_id':1,'guild_id':2}))
    monkeypatch.setattr(perms,'is_recruiter',AsyncMock(return_value=True))
    read=AsyncMock(return_value=[]);monkeypatch.setattr(console.store,'history_for',read)
    c=ctx();c.interaction.values=['123'];m=NS()
    asyncio.run(console.member_history_pick(c,'token',mongo=m))
    read.assert_awaited_once_with(m,user_id=123,limit=console.MAX_HISTORY_RESULTS)
    assert c.interaction.edit_initial_response.call_args.kwargs['user_mentions'] is False


def test_manage_settings_requires_target_admin_not_manage_server(monkeypatch):
    c=ctx();c.member.permissions=hikari.Permissions.MANAGE_GUILD
    monkeypatch.setattr(perms,'is_target_admin',AsyncMock(return_value=False))
    assert not asyncio.run(manage._can_access(c,NS(),'ticket_settings'))


def test_manage_allows_invited_tester_without_admin(monkeypatch):
    from extensions.commands.tickets import testing_service
    c=ctx();c.member.permissions=hikari.Permissions.NONE
    monkeypatch.setattr(perms,'is_target_admin',AsyncMock(return_value=False))
    monkeypatch.setattr(testing_service,'test_mongo',lambda m:m)
    monkeypatch.setattr(testing_service,'active_window',AsyncMock(return_value={'guild_id':2}))
    monkeypatch.setattr(testing_service,'user_allowed',lambda *a,**kw:True)
    assert asyncio.run(manage._can_access(c,NS(),'ticket_testing'))


def test_interval_rejects_invalid_value_without_save(monkeypatch):
    monkeypatch.setattr(settings,'session',AsyncMock(return_value=data()))
    monkeypatch.setattr(testing,'_modal_value',lambda *a:'0')
    save=AsyncMock();monkeypatch.setattr(settings,'save',save)
    c=ctx();asyncio.run(settings.interval_submit(c,'token',mongo=NS(),bot=NS()))
    save.assert_not_awaited()


@pytest.mark.parametrize('missing',[False,True])
def test_entry_repair_updates_owned_post_or_rebinds_replacement(monkeypatch,missing):
    state=NS(valid=True,revision=8,thread_intake=ticket_runtime.IntakeSource(2,3,10),
             legacy_intake=ticket_runtime.IntakeSource(99,98,97),pilot_intake=ticket_runtime.IntakeSource(2,4,11),
             pilot_user_ids=(22,),pilot_role_ids=(23,),pilot_ticket_types=('main','fwa'))
    monkeypatch.setattr(settings,'validate',AsyncMock())
    monkeypatch.setattr(ticket_runtime,'get_rollout',AsyncMock(return_value=state))
    monkeypatch.setattr(settings.setup,'saved_public_ticket_embed',AsyncMock(return_value=[]))
    configure=AsyncMock();monkeypatch.setattr(ticket_runtime,'configure_rollout',configure)
    missing_error=hikari.NotFoundError(url='https://discord.com',headers={},raw_body=b'',message='missing')
    rest=NS(fetch_my_user=AsyncMock(return_value=NS(id=12)),fetch_message=AsyncMock(side_effect=missing_error if missing else None,return_value=NS(author=NS(id=12))),
            edit_message=AsyncMock(),create_message=AsyncMock(return_value=NS(id=20)),delete_message=AsyncMock())
    m=NS(ticket_setup=NS(find_one=AsyncMock(return_value=data()['draft'])))
    asyncio.run(settings.repair_entry(ctx(),m,NS(rest=rest)))
    if missing:
        configure.assert_awaited_once()
        args=configure.call_args.kwargs
        assert args['expected_revision']==8 and args['thread_intake'].message_id==20
        assert args['pilot']['ticket_types']==['main','fwa'] and args['pilot']['user_ids']==[22]
        rest.edit_message.assert_not_awaited()
    else:
        rest.edit_message.assert_awaited_once();rest.create_message.assert_not_awaited();configure.assert_not_awaited()


def test_entry_repair_wont_edit_another_author(monkeypatch):
    monkeypatch.setattr(settings,'validate',AsyncMock())
    monkeypatch.setattr(ticket_runtime,'get_rollout',AsyncMock(return_value=NS(thread_intake=NS(channel_id=3,message_id=4))))
    monkeypatch.setattr(settings.setup,'saved_public_ticket_embed',AsyncMock(return_value=[]))
    rest=NS(fetch_my_user=AsyncMock(return_value=NS(id=12)),fetch_message=AsyncMock(return_value=NS(author=NS(id=999))),edit_message=AsyncMock())
    m=NS(ticket_setup=NS(find_one=AsyncMock(return_value={})))
    with pytest.raises(ValueError,match='not owned'):asyncio.run(settings.repair_entry(ctx(),m,NS(rest=rest)))
    rest.edit_message.assert_not_awaited()


def test_home_is_a_plain_language_overview():
    nodes=list(walk([c.build() for c in settings.page(data())]))
    text=' '.join(str(n.get('content','')) for n in nodes)
    labels=[n['label'] for n in nodes if n.get('type')==2]
    assert 'thread_default' not in text and '10,080' not in text
    assert '7 days' in text and '1 day' in text
    assert labels[:3]==['Manage inactivity & archiving','Manage channels & staff','Open troubleshooting']


def test_timer_page_explains_review_versus_archive():
    d=data();d['view']='timers'
    text=' '.join(str(n.get('content','')) for n in walk([c.build() for c in settings.page(d)]))
    assert 'does not automatically deny or archive' in text
    assert 'archives both threads' in text
    assert '0 to turn automatic archiving off' in text


def test_open_ticket_review_form_saves_days_as_minutes(monkeypatch):
    monkeypatch.setattr(settings,'session',AsyncMock(return_value=data()))
    monkeypatch.setattr(testing,'_modal_value',lambda *a:'7')
    save=AsyncMock(return_value='Saved');monkeypatch.setattr(settings,'save',save)
    monkeypatch.setattr(settings,'fresh',AsyncMock(return_value=data()))
    c=ctx();asyncio.run(settings.interval_submit(c,'token',mongo=NS(),bot=NS(rest=NS())))
    assert save.call_args.args[3]['draft']['ticket_inactivity_minutes']==10080

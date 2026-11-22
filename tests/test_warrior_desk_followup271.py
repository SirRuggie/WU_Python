"""271 contracts exercised only with isolated storage and Discord fakes."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest
from cwl_web import manage_tickets, ticket_browser
from extensions.commands.tickets import console, handlers, setup, thread_service
from tests.test_ticket_creation import _ticket, _PinRest
from tests.test_warrior_desk import CONFIG, GUILD
from utils import ticket_access, ticket_settings
from tests.ticket_followup271_fixtures import opening_mongo

NEW_CONFIG = {**CONFIG, 'account_main_thread_recruiter_role':104,
              'account_fwa_thread_recruiter_role':105}


def texts(parts):
    return [text for part in parts for text in ([str(getattr(part,'content',''))] + texts(getattr(part,'components',()) or ())) if text]


@pytest.mark.parametrize('kind',['main','fwa','account','staff'])
def test_all_types_use_public_staff_pair_and_only_add_the_owner(monkeypatch,kind):
    async def check():
        parents=thread_service.parents_from_config(NEW_CONFIG,GUILD,kind)
        state={'_id':'creation','guild_id':GUILD,'user_id':50,'username':'Tester','ticket_type':kind,
               'ticket_number':12,'candidate_parent_id':parents.candidate_parent_id,'staff_parent_id':parents.staff_parent_id,
               'staff_thread_private':getattr(parents,'private_staff',False),
               'staff_thread_role_ids':getattr(parents,'staff_thread_role_ids',()),'account_clan':'main' if kind=='account' else None}
        channels=[NS(id=101),NS(id=102)]
        rest=NS(create_thread=AsyncMock(side_effect=channels),add_thread_member=AsyncMock())
        monkeypatch.setattr(thread_service,'_fetch_or_recover_thread',AsyncMock(return_value=None))
        monkeypatch.setattr(thread_service,'_unarchive_if_needed',AsyncMock(side_effect=lambda _rest,channel:channel))
        async def update(_mongo,_sid,_owner,**values):state.update(values);return dict(state)
        monkeypatch.setattr(thread_service,'_state_update',update)
        snapshot=AsyncMock(return_value=[]);sync=AsyncMock()
        monkeypatch.setattr(thread_service,'staff_member_snapshot',snapshot,raising=False)
        monkeypatch.setattr(thread_service,'sync_private_staff_members',sync,raising=False)
        await thread_service._ensure_live_thread_pair(rest=rest,mongo=NS(),state=state,owner='owner',bot_user_id=7)
        assert rest.create_thread.await_args_list[0].args[1]==hikari.ChannelType.GUILD_PRIVATE_THREAD
        assert rest.create_thread.await_args_list[1].args[1]==hikari.ChannelType.GUILD_PUBLIC_THREAD
        rest.add_thread_member.assert_awaited_once_with(101,50)
        snapshot.assert_not_awaited();sync.assert_not_awaited()
    asyncio.run(check())


@pytest.mark.parametrize('kind',['account','staff'])
def test_pinned_desk_role_message_has_exact_member_wording_and_no_extra_mentions(kind):
    ticket=_ticket();ticket.update(ticket_type=kind,recruiter_role_id=104,candidate_recruiter_notification=True)
    rest=_PinRest()
    asyncio.run(thread_service._notify_candidate_recruiters(rest,ticket,bot_id=7))
    asyncio.run(thread_service._notify_candidate_recruiters(rest,ticket,bot_id=7))
    assert len(rest.sends)==1
    assert rest.sends[0][1]['content']=='<@&104> a member opened a request.'
    assert rest.sends[0][1]['role_mentions']==[104]
    assert rest.sends[0][1]['user_mentions'] is False
    assert rest.sends[0][1]['mentions_everyone'] is False


@pytest.mark.parametrize('kind',['main','fwa','account','staff'])
def test_creation_has_one_plain_owner_ping_and_welcome_has_no_duplicate_mention(monkeypatch,kind):
    class Rest:
        def __init__(self):self.messages={};self.sent=[]
        def fetch_messages(self,channel):
            async def collect():return self.messages.get(channel,[])[:]
            return NS(to_list=collect)
        async def create_message(self,channel,**kwargs):
            self.sent.append((channel,kwargs));message=NS(id=len(self.sent),author=NS(id=7),content=kwargs.get('content',''),components=kwargs.get('components',[]),is_pinned=False)
            self.messages.setdefault(channel,[]).append(message);return message
        async def pin_message(self,*_):pass
    ticket=_ticket();ticket.update(ticket_type=kind,user_id=50,recruiter_role_id=104,candidate_recruiter_notification=True)
    monkeypatch.setattr(thread_service,'_questionnaire_exists',AsyncMock(return_value=True))
    monkeypatch.setattr(thread_service,'_deliver_staff_talking_points',AsyncMock())
    rest=Rest();mongo=opening_mongo(ticket,new_notification=True)
    async def check():
        await thread_service._deliver_opening_messages(rest,ticket,mongo=mongo,bot_id=7)
        await thread_service._deliver_opening_messages(rest,ticket,mongo=mongo,bot_id=7)
    asyncio.run(check())
    pings=[kwargs for channel,kwargs in rest.sent if '<@50>' in kwargs.get('content','')]
    assert len(pings)==1
    assert pings[0]['user_mentions']==[50] and pings[0]['role_mentions'] is False and pings[0]['mentions_everyone'] is False
    assert sum('<@50>' in '\n'.join(texts(kwargs.get('components',[]))) for _,kwargs in rest.sent)==0


@pytest.mark.parametrize('kind',['account','staff'])
@pytest.mark.parametrize('resumed',[False,True])
def test_desk_uses_the_common_member_thread_link_reply(kind,resumed):
    ctx=NS(guild_id=11,interaction=NS(edit_initial_response=AsyncMock()))
    ticket={'guild_id':11,'ticket_type':kind,'ticket_number':12,'location':{'id':99,'staff_space_id':100}}
    asyncio.run(handlers._show_created_ticket(ctx,ticket,resumed=resumed))
    payload=ctx.interaction.edit_initial_response.await_args.kwargs
    assert payload['components'][0].components[0].url=='https://discord.com/channels/11/99'
    assert payload['components'][0].components[0].label=='Open your request'
    assert '100' not in str(payload)
    assert payload['user_mentions'] is False and payload['role_mentions'] is False


def test_account_button_opens_clan_chooser_before_any_slot_or_creation(monkeypatch):
    ctx=NS(guild_id=11,channel_id=22,user=NS(id=50,username='Tester'),member=NS(role_ids=(),display_name='Tester'),
           defer=AsyncMock(),interaction=NS(message=NS(id=32),edit_initial_response=AsyncMock()))
    ticket={'guild_id':11,'ticket_type':'account','ticket_number':12,'location':{'id':99}}
    monkeypatch.setattr(handlers,'thread_intake_ready',lambda:True)
    monkeypatch.setattr(handlers.ticket_runtime,'route_public_intake',AsyncMock(return_value=NS(allowed=True,route='thread',revision=1)))
    slot=AsyncMock(return_value=NS(won=True));create=AsyncMock(return_value=NS(ticket=ticket,resumed=False,delivery_pending=False))
    monkeypatch.setattr(handlers.ticket_runtime,'claim_open_slot',slot)
    monkeypatch.setattr(handlers.thread_service,'create_live_thread_ticket',create)
    handlers.user_cooldowns.clear()
    from extensions.commands.tickets import rite
    monkeypatch.setattr(rite,'insert_state',AsyncMock())
    mongo=NS(ticket_setup=NS(find_one=AsyncMock(return_value={})))
    asyncio.run(handlers.handle_create_ticket(ctx,'public:account',bot=NS(rest=NS()),mongo=mongo))
    slot.assert_not_awaited();create.assert_not_awaited()
    rendered=str(ctx.interaction.edit_initial_response.await_args.kwargs)
    assert 'Main clan' in rendered and 'FWA clan' in rendered
    handlers.user_cooldowns.clear()


def test_both_new_account_roles_have_account_authority_without_recruit_authority():
    for role in (104,105,100,101):
        allowed=ticket_access.allowed_types_from_config(NEW_CONFIG,guild_id=GUILD,role_ids=[role],administrator=False)
        assert 'account' in allowed
        if role in (104,105):assert allowed=={'account'}
    assert ticket_access.allowed_types_from_config(NEW_CONFIG,guild_id=999,role_ids=[104],administrator=True)==set()


def test_new_account_settings_keys_and_legacy_fallback_without_mutation():
    keys={'account_main_thread_recruiter_role','account_fwa_thread_recruiter_role'}
    assert keys.issubset(ticket_settings.FIELDS)
    legacy=deepcopy(CONFIG);before=deepcopy(legacy)
    values=ticket_settings.history_values(legacy,'desk')
    assert {key:values.get(key) for key in keys}=={key:'102' for key in keys}
    assert legacy==before
    clean=ticket_settings.validated_settings({key:'123456789012345678' for key in keys})
    assert set(clean)==keys
    with pytest.raises(ValueError):ticket_settings.validated_settings({'account_main_thread_recruiter_role':''})


@pytest.mark.parametrize('clan,role',[('main',104),('fwa',105)])
def test_account_parent_role_matches_selected_clan(clan,role):
    parents=thread_service.parents_from_config(NEW_CONFIG,GUILD,'account',account_clan=clan)
    assert parents.recruiter_role_id==role


@pytest.mark.parametrize('clan',['main','fwa'])
def test_account_names_and_console_labels_include_clan_without_changing_type(clan):
    ticket=_ticket();ticket.update(ticket_type='account',account_clan=clan,ticket_number=12,username='name')
    names=asyncio.run(thread_service.thread_names_for_ticket(NS(),ticket))
    assert names==('🆕 add-account-'+clan+'-12-name','🆕 staff-add-account-'+clan+'-12-name')
    assert console._ticket_label(ticket,username=True,markdown=False)=='Account #12 · name · '+clan.upper().replace('MAIN','Main')
    assert ticket_browser.public_ticket(ticket).get('account_clan')==clan


def test_staff_new_names_and_legacy_account_names_remain_distinct():
    staff=_ticket();staff.update(ticket_type='staff',ticket_number=4,username='name')
    assert asyncio.run(thread_service.thread_names_for_ticket(NS(),staff))==('🆕 contact-staff-4-name','🆕 staff-contact-staff-4-name')
    account=_ticket();account.update(ticket_type='account',ticket_number=12,username='name')
    assert asyncio.run(thread_service.thread_names_for_ticket(NS(),account))==('🆕 account-12-name','🆕 staff-account-12-name')


def test_new_desk_parent_always_uses_main_without_config_rewrite():
    config={**NEW_CONFIG,'desk_staff_parent':999}
    before=deepcopy(config)
    for kind in ('account','staff'):
        assert thread_service.parents_from_config(config,GUILD,kind).staff_parent_id==21
    assert config==before


def test_web_desk_settings_show_two_role_fields_and_shared_parent_line(monkeypatch):
    import json
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def database(_):yield NS(ticket_setup=NS(find_one=AsyncMock(return_value=deepcopy(CONFIG))))
    monkeypatch.setattr(manage_tickets,'mongo',database)
    monkeypatch.setattr(manage_tickets,'require_manage',AsyncMock())
    monkeypatch.setattr(manage_tickets,'get_rollout',AsyncMock(return_value=NS(phase='thread_default',valid=True,desk_intake=None)))
    response=asyncio.run(manage_tickets.settings(NS(match_info={'part':'desk'})))
    document=__import__('json').loads(response.text)
    labels={field['key']:field['label'] for field in document['fields']}
    assert labels.get('account_main_thread_recruiter_role')=='Add account role (Main)'
    assert labels.get('account_fwa_thread_recruiter_role')=='Add account role (FWA)'
    assert 'Staff threads use the Main staff channel.' in str(document)


def test_missing_new_role_defaults_and_explicit_empty_does_not_fall_back():
    base={key:value for key,value in CONFIG.items() if key!='account_thread_recruiter_role'}
    values=ticket_settings.history_values(base,'desk')
    assert values.get('account_main_thread_recruiter_role')=='100'
    assert values.get('account_fwa_thread_recruiter_role')=='101'
    values=ticket_settings.history_values({**CONFIG,'account_main_thread_recruiter_role':''},'desk')
    assert values.get('account_main_thread_recruiter_role')==''


@pytest.mark.parametrize('name',['🆕 account-1-name','🆕 staff-account-1-name','🆕 staff-1-name','🆕 staff-staff-1-name',
                                 '🆕 add-account-main-12-name','🆕 staff-add-account-fwa-12-name',
                                 '🆕 contact-staff-4-name','🆕 staff-contact-staff-4-name'])
def test_recovery_name_variants_accept_legacy_and_new_shapes(name):
    variants=thread_service._name_variants(name)
    assert name in variants and len(variants)>1


class MemberPingRest:
    def __init__(self, messages=(), *, failure=None, history_failure=None):
        self.messages=list(messages);self.sent=[];self.failure=failure;self.history_failure=history_failure;self.reads=0
    def fetch_messages(self,channel):
        async def collect():
            self.reads+=1
            if self.history_failure:raise self.history_failure
            return self.messages[:]
        return NS(to_list=collect)
    async def create_message(self,channel,**kwargs):
        self.sent.append((channel,kwargs))
        message=NS(id=987,author=NS(id=7),content=kwargs.get('content',''),components=[])
        self.messages.append(message)
        if self.failure:raise self.failure
        return message


def notification_ticket():
    ticket=_ticket();ticket.update(ticket_type='account',account_clan='main',user_id=50)
    return ticket


@pytest.mark.parametrize('failure',[OSError('accepted response unavailable'),asyncio.CancelledError()])
def test_member_ping_claim_survives_unknown_acceptance_restart_and_ttl_expiry(failure):
    async def check():
        ticket=notification_ticket();mongo=opening_mongo(ticket,new_notification=True)
        rest=MemberPingRest(failure=failure)
        if isinstance(failure,asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await thread_service._notify_opening_member_once(rest,mongo,ticket,bot_id=7)
        else:
            await thread_service._notify_opening_member_once(rest,mongo,ticket,bot_id=7)
        assert len(rest.sent)==1
        row=mongo.tickets.documents[ticket['_id']]
        assert row['opening_member_notification']['state']=='attempted'
        restarted=MemberPingRest(history_failure=RuntimeError('history unavailable'))
        # A new process has only the permanent ticket collection, not TTL state.
        await thread_service._notify_opening_member_once(restarted,NS(tickets=mongo.tickets),ticket,bot_id=7)
        assert restarted.sent==[] and restarted.reads==0
    asyncio.run(check())


def test_member_ping_concurrent_claims_allow_one_send():
    async def check():
        ticket=notification_ticket();mongo=opening_mongo(ticket,new_notification=True)
        entered=0;ready=asyncio.Event()
        class RacingRest(MemberPingRest):
            def fetch_messages(self,channel):
                async def collect():
                    nonlocal entered
                    entered+=1
                    if entered==2:ready.set()
                    await ready.wait()
                    return []
                return NS(to_list=collect)
        rest=RacingRest()
        await asyncio.gather(*(thread_service._notify_opening_member_once(rest,mongo,ticket,bot_id=7) for _ in range(2)))
        assert len(rest.sent)==1
        assert mongo.tickets.documents[ticket['_id']]['opening_member_notification']['state']=='sent'
    asyncio.run(check())


@pytest.mark.parametrize('has_old_card',[True,False])
def test_historical_ticket_never_receives_retroactive_plain_ping(has_old_card):
    async def check():
        ticket=notification_ticket();mongo=opening_mongo(ticket)
        components=thread_service._candidate_welcome_components(ticket)
        if has_old_card:
            components=[*components,NS(content='<@50> Old welcome',components=[])]
        messages=[NS(id=321,author=NS(id=7),content='',components=components)] if has_old_card else []
        rest=MemberPingRest(messages)
        await thread_service._notify_opening_member_once(rest,mongo,ticket,bot_id=7)
        assert rest.sent==[]
        receipt=mongo.tickets.documents[ticket['_id']].get('opening_member_notification')
        if has_old_card:assert receipt['state']=='legacy-confirmed' and receipt['message_id']==321
        else:assert receipt is None
    asyncio.run(check())


@pytest.mark.parametrize('owner_text',['','<@500> someone else'])
def test_new_welcome_title_or_another_member_mention_does_not_prove_owner_ping(owner_text):
    async def check():
        ticket=notification_ticket();mongo=opening_mongo(ticket,new_notification=True)
        components=[*thread_service._candidate_welcome_components(ticket),NS(content=owner_text,components=[])]
        rest=MemberPingRest([NS(id=321,author=NS(id=7),content='',components=components)])
        await thread_service._notify_opening_member_once(rest,mongo,ticket,bot_id=7)
        assert len(rest.sent)==1
        assert rest.sent[0][1]['user_mentions']==[50]
    asyncio.run(check())


def test_member_history_failure_does_not_infer_absence_or_claim_send():
    async def check():
        ticket=notification_ticket();mongo=opening_mongo(ticket,new_notification=True)
        rest=MemberPingRest(history_failure=RuntimeError('history unavailable'))
        with pytest.raises(RuntimeError,match='history unavailable'):
            await thread_service._notify_opening_member_once(rest,mongo,ticket,bot_id=7)
        assert rest.sent==[]
        assert mongo.tickets.documents[ticket['_id']]['opening_member_notification']['state']=='pending'
    asyncio.run(check())


@pytest.mark.parametrize('choice',['main','fwa','cancel'])
def test_account_choice_is_owner_bound_atomic_and_keeps_original_binding(monkeypatch,choice):
    from datetime import datetime, timedelta, timezone
    from extensions.commands.tickets import rite
    from tests import test_ticket_runtime as fake
    original=fake._condition
    def condition(actual,expected):
        if isinstance(expected,dict) and '$gt' in expected:
            return actual is not fake.MISSING and actual>expected['$gt']
        return original(actual,expected)
    monkeypatch.setattr(fake,'_condition',condition)
    class Collection(fake.Collection):
        async def update_one(self,*args,**kwargs):
            result=await super().update_one(*args,**kwargs)
            result.upserted_id=None
            return result
    state={'_id':'choice','type':'ticket_account_clans','owner_id':50,'guild_id':11,
        'channel_id':22,'source_message_id':32,'expires_at':datetime.now(timezone.utc)+timedelta(minutes=1)}
    db=NS(component_state=Collection([state]),button_store=Collection())
    def context():return NS(user=NS(id=50),guild_id=11,channel_id=22,respond=AsyncMock(),defer=AsyncMock(),
        interaction=NS(message=NS(id=999),edit_initial_response=AsyncMock()))
    create=AsyncMock();monkeypatch.setattr(handlers,'handle_create_ticket',create)
    async def check():
        first,second=context(),context()
        await asyncio.gather(rite.choose_account_clan(first,'choice:'+choice,mongo=db,bot=NS()),
                             rite.choose_account_clan(second,'choice:fwa',mongo=db,bot=NS()))
        assert db.component_state.documents['choice']['choice']==choice
        assert sum(ctx.respond.await_count for ctx in (first,second))==1
    asyncio.run(check())
    if choice=='cancel':create.assert_not_awaited()
    else:
        create.assert_awaited_once()
        assert create.await_args.kwargs['_source_message_id']==32
        assert create.await_args.kwargs['_account_clan']==choice
        assert create.await_args.kwargs['action_id']=='public:account'


@pytest.mark.parametrize('bad',['owner','guild','channel','expired','invalid'])
def test_account_choice_rejects_foreign_expired_or_invalid_without_creation(monkeypatch,bad):
    from datetime import datetime,timedelta,timezone
    from extensions.commands.tickets import rite
    from tests.test_ticket_runtime import Collection
    state={'_id':'choice','type':'ticket_account_clans','owner_id':50,'guild_id':11,'channel_id':22,
        'source_message_id':32,'expires_at':datetime.now(timezone.utc)+timedelta(minutes=1)}
    ctx=NS(user=NS(id=51 if bad=='owner' else 50),guild_id=12 if bad=='guild' else 11,
        channel_id=23 if bad=='channel' else 22,respond=AsyncMock())
    if bad=='expired':state['expires_at']-=timedelta(minutes=2)
    db=NS(component_state=Collection([state]),button_store=Collection())
    create=AsyncMock();monkeypatch.setattr(handlers,'handle_create_ticket',create)
    asyncio.run(rite.choose_account_clan(ctx,'choice:'+('other' if bad=='invalid' else 'main'),mongo=db,bot=NS()))
    create.assert_not_awaited();ctx.respond.assert_awaited_once()
    assert 'choice' not in db.component_state.documents.get('choice',{})


def test_chosen_account_rechecks_binding_before_claiming_slot(monkeypatch):
    ctx=NS(guild_id=11,channel_id=22,user=NS(id=50,username='Tester'),member=NS(role_ids=()),
        defer=AsyncMock(),interaction=NS(message=NS(id=999),edit_initial_response=AsyncMock()))
    monkeypatch.setattr(handlers,'thread_intake_ready',lambda:True)
    route=AsyncMock(return_value=NS(allowed=False,route='thread'));monkeypatch.setattr(handlers.ticket_runtime,'route_public_intake',route)
    slot=AsyncMock();create=AsyncMock()
    monkeypatch.setattr(handlers.ticket_runtime,'claim_open_slot',slot)
    monkeypatch.setattr(handlers.thread_service,'create_live_thread_ticket',create)
    asyncio.run(handlers.handle_create_ticket(ctx,'public:account',bot=NS(rest=NS()),mongo=NS(),_source_message_id=32,_account_clan='main'))
    assert route.await_args.kwargs['message_id']==32
    slot.assert_not_awaited();create.assert_not_awaited()


def test_old_pinned_desk_role_message_is_reused_without_new_ping():
    rest=_PinRest();ticket=_ticket();ticket.update(ticket_type='staff',recruiter_role_id=104,candidate_recruiter_notification=True)
    message=NS(id=100,author=NS(id=7),content='<@&104> — a new applicant ticket is ready for your review.',is_pinned=True)
    rest.messages=[message]
    asyncio.run(thread_service._notify_candidate_recruiters(rest,ticket,bot_id=7))
    assert not rest.sends


@pytest.mark.parametrize('kind,clan',[('main',None),('fwa',None),('account','main'),('account','fwa'),('staff',None)])
def test_actual_creation_initializes_permanent_owner_receipt_and_account_subtype(monkeypatch,kind,clan):
    from tests.test_ticket_creation import _slot_claim
    from utils import gauntlet_tracking
    db=NS(ticket_creation_state=NS(find_one=AsyncMock(return_value=None)))
    state={'_id':'creation','guild_id':GUILD,'user_id':30,'username':'Applicant','ticket_type':kind,
        'ticket_number':12,'candidate_parent_id':30 if kind in ('account','staff') else 20,
        'staff_parent_id':21,'recruiter_role_id':104 if clan=='main' else 105 if clan=='fwa' else 103,
        'account_clan':clan,'desk_permission_policy':True}
    async def claim(_mongo,**kwargs):
        assert kwargs['account_clan']==clan
        return 'owner',deepcopy(state),False
    insert=AsyncMock(side_effect=lambda mongo,row:deepcopy(row))
    monkeypatch.setattr(thread_service,'ensure_creation_indexes',AsyncMock())
    monkeypatch.setattr(thread_service,'validate_thread_parents',AsyncMock())
    monkeypatch.setattr(thread_service.store,'find_open_for_applicant',AsyncMock(return_value=None))
    monkeypatch.setattr(thread_service,'_committed_ticket_for_creation_state',AsyncMock(return_value=None))
    monkeypatch.setattr(thread_service,'_claim_creation',claim)
    monkeypatch.setattr(thread_service,'_ensure_live_thread_pair',AsyncMock(return_value=(NS(id=101),NS(id=102),state)))
    monkeypatch.setattr(thread_service.store,'insert_one',insert)
    monkeypatch.setattr(thread_service.ticket_staff_content,'load',AsyncMock(return_value=None))
    monkeypatch.setattr(thread_service.ticket_runtime,'bind_open_slot',AsyncMock())
    monkeypatch.setattr(thread_service,'_finish_committed_creation',AsyncMock(return_value=False))
    monkeypatch.setattr(thread_service,'notify_console_after_change',AsyncMock())
    monkeypatch.setattr(thread_service.account_sync,'configured_coc_client',lambda:None)
    monkeypatch.setattr(gauntlet_tracking,'ticket_opened',AsyncMock())
    created=asyncio.run(thread_service.create_live_thread_ticket(bot=NS(get_me=lambda:NS(id=7),rest=NS()),mongo=db,
        guild_id=GUILD,user_id=30,username='Applicant',display_name=None,ticket_type=kind,
        config=NEW_CONFIG,account_clan=clan,open_slot_claim=_slot_claim(guild_id=GUILD,ticket_type=kind)))
    assert created.ticket['opening_member_notification']=={'state':'pending','user_id':30,'channel_id':101}
    assert created.ticket.get('account_clan')==clan
    assert created.ticket['desk_permission_policy'] is True
    assert 'staff_thread_private' not in created.ticket
    insert.assert_awaited_once()


@pytest.mark.parametrize('clan',['main','fwa'])
def test_account_subtype_is_preserved_in_committed_recovery_and_old_private_parent(clan):
    ticket=_ticket();ticket.update(ticket_type='account',account_clan=clan,staff_thread_private=True,
        recruiter_role_id=104 if clan=='main' else 105,
        staff_role_config={'main':100,'fwa':101,'account_main':104,'account_fwa':105,'staff':103})
    # The old pair's recorded staff parent wins over the new Main default.
    ticket['location']['staff_parent_id']=999
    state={'candidate_parent_id':30,'staff_parent_id':999,'recruiter_role_id':ticket['recruiter_role_id'],
        'staff_role_config':ticket['staff_role_config'],'account_clan':clan,'staff_thread_private':True}
    cfg=thread_service._recovery_config(state,'account',GUILD)
    parents=thread_service.parents_from_config(cfg,GUILD,'account',account_clan=clan)
    assert parents.staff_parent_id==999 and parents.recruiter_role_id==ticket['recruiter_role_id']


@pytest.mark.parametrize('matched',[0,1])
def test_new_account_role_explicit_save_keeps_cas_audit_and_legacy_fallback(monkeypatch,matched):
    from extensions.commands.tickets import settings
    from tests.test_ticket_settings import ctx
    from unittest.mock import Mock
    baseline={**NEW_CONFIG,'ticket_target_guild_id':2}
    draft={**baseline,'account_main_thread_recruiter_role':106}
    audit=NS(insert_one=AsyncMock(),update_one=AsyncMock())
    collection=NS(update_one=AsyncMock(return_value=NS(matched_count=matched)),database=NS(get_collection=Mock(return_value=audit)))
    monkeypatch.setattr(settings,'validate',AsyncMock())
    if matched:asyncio.run(settings.save(ctx(),NS(ticket_setup=collection),NS(),{'baseline':baseline,'draft':draft}))
    else:
        with pytest.raises(ValueError,match='changed'):
            asyncio.run(settings.save(ctx(),NS(ticket_setup=collection),NS(),{'baseline':baseline,'draft':draft}))
    query,update=collection.update_one.await_args.args
    assert query['account_main_thread_recruiter_role']==104 and query['account_fwa_thread_recruiter_role']==105
    assert query['ticket_settings_revision']=={'$exists':False}
    assert query['account_thread_recruiter_role']==102
    assert update['$set']=={'account_main_thread_recruiter_role':106}
    assert baseline['account_thread_recruiter_role']==102
    assert audit.insert_one.await_args.args[0]['before']=={'account_main_thread_recruiter_role':104}
    assert audit.insert_one.await_args.args[0]['after']=={'account_main_thread_recruiter_role':106}
    assert audit.update_one.await_args.args[1]['$set']['state']==('committed' if matched else 'conflict')


@pytest.mark.parametrize('failure',['lost_response','crash_after_intent','intent_cas','unavailable','ambiguous'])
def test_old_private_missing_half_has_durable_public_intent_before_discord(monkeypatch,failure):
    state={'_id':'old-private','ticket_number':12,'guild_id':GUILD,'user_id':50,
        'username':'Applicant','ticket_type':'account','candidate_parent_id':20,
        'staff_parent_id':99,'candidate_thread_id':101,'staff_thread_private':True,
        'candidate_name':'🆕 account-12-applicant','staff_name':'🆕 staff-account-12-applicant',
        'staff_role_config':{'account':102},'recruiter_role_id':102}
    def channel(key,parent,name,kind):
        return NS(id=key,guild_id=GUILD,parent_id=parent,name=name,type=kind,
            owner_id=7,is_archived=False,is_locked=False)
    candidate=channel(101,20,state['candidate_name'],hikari.ChannelType.GUILD_PRIVATE_THREAD)
    channels={101:candidate};created=[];intent_attempts=[]
    if failure=='ambiguous':
        for key in (201,202):channels[key]=channel(key,99,state['staff_name'],hikari.ChannelType.GUILD_PRIVATE_THREAD)
    async def fetch_channel(key):return channels[key]
    async def active(guild):
        assert guild==GUILD
        if failure=='unavailable':raise OSError('private lookup unavailable')
        return [value for value in channels.values() if not value.is_archived]
    def archived(parent,kind):
        async def collect():return [value for value in channels.values() if value.parent_id==parent and value.type==kind and value.is_archived]
        return NS(to_list=collect)
    async def edit(key,**values):
        for key_name,value in values.items():
            if key_name=='archived':channels[key].is_archived=value
            if key_name=='locked':channels[key].is_locked=value
        return channels[key]
    async def update(mongo,sid,owner,**values):
        assert sid=='old-private' and owner=='owner'
        if 'staff_thread_private' in values:
            intent_attempts.append(False)
            if failure=='intent_cas':raise thread_service.ThreadCreationBusy('lease lost')
            state.update(values)
            if failure=='crash_after_intent' and len(intent_attempts)==1:raise asyncio.CancelledError()
        else:state.update(values)
        return deepcopy(state)
    async def create(parent,kind,name,**kwargs):
        assert state['staff_thread_private'] is False  # Durable before any side effect.
        assert parent==99 and kind==hikari.ChannelType.GUILD_PUBLIC_THREAD
        created.append((parent,kind,name))
        value=channel(203,parent,name,kind);channels[203]=value
        if failure=='lost_response' and len(created)==1:raise OSError('accepted response lost')
        return value
    rest=NS(fetch_channel=fetch_channel,fetch_active_threads=active,
        fetch_private_archived_threads=lambda parent:archived(parent,hikari.ChannelType.GUILD_PRIVATE_THREAD),
        fetch_public_archived_threads=lambda parent:archived(parent,hikari.ChannelType.GUILD_PUBLIC_THREAD),
        create_thread=create,edit_channel=edit,add_thread_member=AsyncMock())
    monkeypatch.setattr(thread_service,'_state_update',update)
    async def attempt():
        return await thread_service._ensure_live_thread_pair(rest=rest,mongo=NS(),state=deepcopy(state),owner='owner',bot_user_id=7)
    async def check():
        error=asyncio.CancelledError if failure=='crash_after_intent' else thread_service.ThreadCreationBusy if failure=='intent_cas' else thread_service.ThreadTicketError if failure=='ambiguous' else OSError
        with pytest.raises(error):await attempt()
        if failure in {'lost_response','crash_after_intent'}:
            assert state['staff_thread_private'] is False
            assert state['desk_permission_policy'] is True
            assert thread_service._recovery_config(state,'account',GUILD)['_desk_permission_policy'] is True
            if 203 in channels:channels[203].is_archived=True  # Restart after auto-archive.
            member,staff,fresh=await attempt()
            assert member.id==101 and staff.id==203 and fresh['staff_thread_id']==203
            assert len(created)==1 and intent_attempts==[False]
            assert all(call.args==(101,50) for call in rest.add_thread_member.await_args_list)
        else:
            assert not created and state['staff_thread_private'] is True
            assert intent_attempts==([False] if failure=='intent_cas' else [])
    asyncio.run(check())


@pytest.mark.parametrize('kind',['main','fwa'])
@pytest.mark.parametrize('desk',[False,True])
@pytest.mark.parametrize('case',['recruiter_mt','staff_reader','candidate_reader','candidate_overwrite'])
def test_permission_policy_preserves_non_desk_recruit_contract(monkeypatch,kind,desk,case):
    from tests.test_ticket_creation import _valid_parent_rest
    config={'ticket_target_guild_id':10,'main_candidate_parent':20,'fwa_candidate_parent':20,
        'main_staff_parent':21,'fwa_staff_parent':21,'main_thread_recruiter_role':40,'fwa_thread_recruiter_role':40}
    if desk:config['desk_channel_id']=30
    parents=thread_service.parents_from_config(config,10,kind)
    assert parents.desk_permission_policy is desk
    rest=_valid_parent_rest(mentionable=True,bot_can_mention=True)
    original_roles,original_channel,original_member=rest.fetch_roles,rest.fetch_channel,rest.fetch_member
    async def roles(guild):
        items=await original_roles(guild)
        if case=='recruiter_mt':
            for item in items:
                if item.id==40:item.permissions &= ~hikari.Permissions.MANAGE_THREADS
        elif case!='candidate_overwrite':
            items.append(NS(id=888,name='Unrelated observer',permissions=hikari.Permissions.VIEW_CHANNEL|hikari.Permissions.MANAGE_THREADS,is_managed=False))
        return items
    async def channel(key):
        value=await original_channel(key)
        if case in {'staff_reader','candidate_reader'}:
            hidden=20 if case=='staff_reader' else 21
            if key==hidden:value.permission_overwrites.append(NS(id=888,type=hikari.PermissionOverwriteType.ROLE,allow=hikari.Permissions.NONE,deny=hikari.Permissions.VIEW_CHANNEL))
        if case=='candidate_overwrite' and key==20:
            value.permission_overwrites.append(NS(id=666,type=hikari.PermissionOverwriteType.MEMBER,
                allow=hikari.Permissions.VIEW_CHANNEL|hikari.Permissions.MANAGE_THREADS,deny=hikari.Permissions.NONE))
        return value
    async def member(guild,key):
        if key==666:return NS(id=666,display_name='Candidate observer',role_ids=(),is_bot=False)
        return await original_member(guild,key)
    snapshot=AsyncMock(return_value=[])
    monkeypatch.setattr(thread_service,'permission_member_snapshot',snapshot)
    rest.fetch_roles,rest.fetch_channel,rest.fetch_member=roles,channel,member
    rejects=(not desk) if case in {'recruiter_mt','staff_reader'} else desk
    if rejects:
        with pytest.raises(thread_service.ThreadConfigurationError):
            asyncio.run(thread_service.validate_thread_parents(rest,parents,bot_user_id=99))
    else:asyncio.run(thread_service.validate_thread_parents(rest,parents,bot_user_id=99))
    if not desk:snapshot.assert_not_awaited()
    rest_calls=getattr(rest,'add_thread_member',None)
    assert rest_calls is None  # Validator has no invitation transport in either mode.


@pytest.mark.parametrize('kind',['main','fwa'])
@pytest.mark.parametrize('old',[False,True,None])
def test_recovery_mode_uses_legacy_boolean_and_survives_config_change(kind,old):
    state={'candidate_parent_id':20,'staff_parent_id':21,'recruiter_role_id':40,'staff_role_config':{'main':40,'fwa':40}}
    if old is not None:state['staff_thread_private']=old
    before=deepcopy(state)
    cfg=thread_service._recovery_config(state,kind,10)
    cfg['desk_channel_id']=0 if old else 30  # A later config change cannot replace receipt policy.
    assert thread_service.parents_from_config(cfg,10,kind).desk_permission_policy is bool(old)
    assert state==before
    state.update(desk_permission_policy=True,staff_thread_private=False)
    assert thread_service._recovery_config(state,kind,10)['_desk_permission_policy'] is True


@pytest.mark.parametrize('bad',['false',0,1,None,{}])
def test_malformed_recorded_mode_is_not_coerced_or_inferred(bad):
    with pytest.raises(thread_service.ThreadConfigurationError,match='permission policy'):
        thread_service._recovery_config({'desk_permission_policy':bad},'main',10)


@pytest.mark.parametrize('kind',['main','fwa'])
@pytest.mark.parametrize('old',[False,True])
def test_claim_and_committed_recovery_keep_original_policy(monkeypatch,kind,old):
    monkeypatch.setattr(thread_service,'ensure_creation_indexes',AsyncMock())
    from tests.test_ticket_creation import CreationStateCollection,_slot_claim,NOW
    collection=CreationStateCollection({'_id':'thread:30:'+kind,'state':'retry','ticket_number':1,
        'guild_id':10,'candidate_parent_id':20,'staff_parent_id':21,'recruiter_role_id':40,
        'staff_thread_private':old})
    db=NS(ticket_creation_state=collection)
    parents=thread_service.ThreadParents(10,20,21,40,desk_permission_policy=not old)
    _,state,_=asyncio.run(thread_service._claim_creation(db,guild_id=10,user_id=30,username='Applicant',
        display_name=None,ticket_type=kind,parents=parents,open_slot_claim=_slot_claim(ticket_type=kind),now=NOW))
    assert state['desk_permission_policy'] is old
    ticket=_ticket();ticket.update(ticket_type=kind,desk_permission_policy=old,staff_thread_private=False)
    # Real committed-state write projects the separate policy, not replacement type.
    calls=[]
    async def update(query,change,**kwargs):calls.append(change);return NS(matched_count=1)
    collection.update_one=update
    asyncio.run(thread_service._set_committed_creation_state(db,ticket,state='delivery_retry'))
    assert calls[-1]['$set']['desk_permission_policy'] is old


@pytest.mark.parametrize('fresh',[False,True])
def test_lost_retry_cas_then_completed_generation_uses_fresh_config(monkeypatch,fresh):
    monkeypatch.setattr(thread_service,'ensure_creation_indexes',AsyncMock())
    from tests.test_ticket_creation import CreationStateCollection,_slot_claim,NOW
    class CompletingCollection(CreationStateCollection):
        async def find_one_and_update(self,query,update,**kwargs):
            assert update['$set']['desk_permission_policy'] is not fresh
            self.document.update(state='complete',ticket_id='old-ticket')
            return None  # Another worker completed after our read; retry anew.
    collection=CompletingCollection({'_id':'thread:30:main','state':'retry','ticket_number':1,
        'guild_id':10,'candidate_parent_id':20,'staff_parent_id':21,'recruiter_role_id':40,
        'staff_thread_private':not fresh})
    parents=thread_service.ThreadParents(10,20,21,40,desk_permission_policy=fresh)
    _,state,resumed=asyncio.run(thread_service._claim_creation(NS(ticket_creation_state=collection),
        guild_id=10,user_id=30,username='Applicant',display_name=None,ticket_type='main',
        parents=parents,open_slot_claim=_slot_claim(),now=NOW))
    assert resumed is False
    assert state['desk_permission_policy'] is fresh
    assert collection.document['desk_permission_policy'] is fresh

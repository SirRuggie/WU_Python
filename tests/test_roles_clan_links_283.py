"""Offline fixture contracts for separate role storage and protected grants."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bson import BSON
import hikari
import pytest
from utils import town_halls, server_roles
from utils.role_permissions import role_is_self_selectable
from test_town_halls import registry


def run(value):
    return asyncio.run(value)


@pytest.mark.parametrize('roles', [{'19':'44','12':'44'}, {'00':'44'}, {'19':44}, {'19':'0'}, {'19':True}])
def test_role_owner_rejects_malformed_duplicate_roles(roles):
    with pytest.raises(ValueError):
        town_halls.validate_roles(roles)


def owner(monkeypatch, roles=None):
    doc = registry()
    doc['schema_version'] = 2
    collection = SimpleNamespace(find_one=AsyncMock(return_value=roles), insert_one=AsyncMock(), find_one_and_update=AsyncMock())
    monkeypatch.setattr(server_roles, 'load', AsyncMock(return_value={'revision':0,'roles':[],'exists':False}))
    monkeypatch.setattr(town_halls, '_roles_collection', lambda mongo: collection)
    monkeypatch.setattr(town_halls, 'load', AsyncMock(return_value=doc))
    return doc, collection


def test_role_save_never_changes_old_reader_document_or_legacy_settings(monkeypatch):
    doc, collection = owner(monkeypatch)
    before = BSON.encode(doc)
    result = run(town_halls.save_roles(object(), 123, {'19':'44'}, 12, 0))
    assert result['roles'] == {'19':'44'}
    assert result['revision'] == 1
    collection.insert_one.assert_awaited_once()
    assert BSON.encode(doc) == before
    town_halls.validate(doc)  # The unchanged schema2 reader accepts exactly these bytes.
    assert 'role' not in doc['levels']['19']


def test_role_owner_stale_revision_has_no_write(monkeypatch):
    _, collection = owner(monkeypatch, {'schema_version':1, 'revision':2, 'roles':{}})
    with pytest.raises(town_halls.TownHallsConflict):
        run(town_halls.save_roles(object(), 123, {'19':'44'}, 12, 1))
    collection.insert_one.assert_not_awaited()
    collection.find_one_and_update.assert_not_awaited()


def test_roles_hidden_removed_levels_retained_and_reader_filters_them(monkeypatch):
    doc, collection = owner(monkeypatch, {'schema_version':1, 'revision':2, 'roles':{'18':'55','19':'44'}})
    collection.find_one_and_update.return_value = {'revision':3}
    result = run(town_halls.save_roles(object(), 123, {'19':''}, 12, 2))
    assert result['roles'] == {'18':'55'}
    assert run(town_halls.role_choices(object(), 123)) == [{'level':19,'role_id':'44','emoji':doc['levels']['19']['emoji']}]
    with pytest.raises(ValueError):
        run(town_halls.save_roles(object(), 123, {'18':'66'}, 12, 2))


@pytest.mark.parametrize('permissions,managed,position,identifier,safe', [
    (0,False,1,44,True), (hikari.Permissions.ADMINISTRATOR,False,1,44,False),
    (hikari.Permissions.SEND_MESSAGES,False,1,44,False), (0,True,1,44,False),
    (0,False,5,44,False), (0,False,1,123,False)])
def test_shared_role_rule_no_permissions_or_hierarchy_escape(permissions,managed,position,identifier,safe):
    role=SimpleNamespace(id=identifier,permissions=permissions,is_managed=managed,position=position)
    own_role=SimpleNamespace(id=50,permissions=hikari.Permissions.MANAGE_ROLES,position=5)
    own=SimpleNamespace(id=9,role_ids=[50])
    guild=SimpleNamespace(id=123,owner_id=1,get_role=lambda rid:own_role if rid==50 else None,get_member=lambda uid:own)
    bot=SimpleNamespace(get_me=lambda:SimpleNamespace(id=9))
    assert role_is_self_selectable(guild,bot,role) is safe


@pytest.mark.parametrize('bad', [[], [{'role_id':'44','label':'x','short_line':'','order':1}], [{'role_id':'44','label':'x'*41,'short_line':'','order':0}]])
def test_server_role_validation_and_empty_supported(bad):
    if bad == []:
        assert server_roles.validate(bad) == []
    else:
        with pytest.raises(ValueError): server_roles.validate(bad)


def test_server_role_cas_never_upserts(monkeypatch):
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':0,'roles':{}}))
    collection=SimpleNamespace(find_one=AsyncMock(return_value={'revision':2,'roles':[]}),find_one_and_update=AsyncMock(return_value=None))
    mongo=SimpleNamespace(bot_config=collection)
    with pytest.raises(server_roles.ServerRolesConflict):
        run(server_roles.save(mongo,123,[],12,2))
    assert collection.find_one_and_update.call_args.args[0]=={'_id':'server_roles:123','revision':2}
    assert collection.find_one_and_update.call_args.kwargs['upsert'] is False


def test_zero_permission_dashboard_grant_role_is_excluded_at_http_save(monkeypatch):
    from cwl_web import server_roles as api
    role=SimpleNamespace(id=44,name='Dashboard admin',color=0)
    monkeypatch.setattr(api,'hierarchy',AsyncMock(return_value=({44:role},object(),object(),object())))
    monkeypatch.setattr(api,'role_is_self_selectable',lambda *_:True)
    monkeypatch.setattr(api,'actor_can_manage_role',lambda *_:True)
    monkeypatch.setattr(api,'dashboard_grant_roles',AsyncMock(return_value={'44'}))
    assert run(api.role_choices(object(),{}))[0]==[]
    from aiohttp import web
    with pytest.raises(web.HTTPBadRequest): run(api.require_safe_roles(object(),{},['44']))


def transport(monkeypatch, *, held=(17,18,999), selected=('17','18','19'), fail=None, protected=(), kind='th'):
    from datetime import timedelta
    from utils.component_state import utcnow
    from extensions.commands import family_links as panel
    member=SimpleNamespace(role_ids=set(held))
    rows=[dict(role_id=str(level),label=f'TH{level}',short_line='',level=level,emoji='') for level in (19,18,17)]
    async def add(_guild,_user,rid,**_kwargs):
        if fail == rid: raise RuntimeError('provider-private-text')
        member.role_ids.add(rid)
    async def remove(_guild,_user,rid,**_kwargs): member.role_ids.discard(rid)
    bot=SimpleNamespace(rest=SimpleNamespace(add_role_to_member=AsyncMock(side_effect=add),remove_role_from_member=AsyncMock(side_effect=remove)))
    instance='1'*32
    ctx=SimpleNamespace(interaction=SimpleNamespace(guild_id=123,values=selected,custom_id=f'family_links_select_{kind}:{instance}',message=SimpleNamespace(id=700,flags=hikari.MessageFlag.EPHEMERAL)),user=SimpleNamespace(id=4),respond=AsyncMock(return_value=700),fetch_response=AsyncMock(return_value=SimpleNamespace(id=700,flags=hikari.MessageFlag.EPHEMERAL)))
    offered={kind:['19','18','17'],('server' if kind=='th' else 'th'):[]}
    record={'_id':panel.role_session_key(123,4,700,instance),'type':'family_roles','guild_id':123,'user_id':4,'message_id':700,'instance':instance,'active':True,'offered':offered,'held':{key:[value for value in values if int(value) in held] for key,values in offered.items()},'submissions':{},'expires_at':utcnow()+timedelta(minutes=15)}
    ctx.sessions={record['_id']:record}
    ctx.session=record
    async def insert(_mongo,document,**kwargs):
        saved=deepcopy(document);saved['expires_at']=utcnow()+kwargs['ttl'];ctx.sessions[saved['_id']]=saved
    async def read(_mongo,key): return deepcopy(ctx.sessions.get(key))
    missing=object()
    def nested(document,path):
        for part in path.split('.'):
            if not isinstance(document,dict) or part not in document:return missing
            document=document[part]
        return document
    async def update(_mongo,query,change,**_kwargs):
        current=ctx.sessions.get(query['_id'])
        if current is None:return SimpleNamespace(matched_count=0)
        for key,value in query.items():
            actual=nested(current,key)
            if isinstance(value,dict):
                if '$exists' in value and (actual is not missing)!=value['$exists']:return SimpleNamespace(matched_count=0)
                if '$gt' in value and not actual>value['$gt']:return SimpleNamespace(matched_count=0)
            elif actual!=value:return SimpleNamespace(matched_count=0)
        for path,value in change.get('$set',{}).items():
            target=current;parts=path.split('.')
            for part in parts[:-1]:target=target.setdefault(part,{})
            target[parts[-1]]=deepcopy(value)
        return SimpleNamespace(matched_count=1)
    monkeypatch.setattr(panel,'choices',AsyncMock(side_effect=lambda _mongo,_guild,menu: rows if menu == kind else []))
    monkeypatch.setattr(panel,'fresh_context',AsyncMock(return_value=(object(),{level:object() for level in (19,18,17)},member)))
    monkeypatch.setattr(panel,'role_is_self_selectable',lambda *_:True)
    monkeypatch.setattr(panel,'dashboard_role_grants',AsyncMock(return_value=set(protected)))
    monkeypatch.setattr(panel,'_locks',{})
    monkeypatch.setattr(panel,'insert_state',AsyncMock(side_effect=insert))
    monkeypatch.setattr(panel,'get_state',AsyncMock(side_effect=read))
    monkeypatch.setattr(panel,'update_state',AsyncMock(side_effect=update))
    return panel,ctx,bot,member


def response_text(ctx):
    return ' '.join(getattr(item,'content','') for item in ctx.respond.call_args.kwargs['components'][0].components)


def test_preselected_existing_th_roles_survive_and_double_submit_is_noop(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch)
    async def scenario():
        await panel.select_roles(ctx,object(),bot,'th')
        await panel.select_roles(ctx,object(),bot,'th')
    run(scenario())
    assert member.role_ids == {17,18,19,999}
    assert bot.rest.add_role_to_member.await_count == 1
    bot.rest.remove_role_from_member.assert_not_awaited()
    assert 'These roles were already saved.' in response_text(ctx)


def test_deselect_removes_only_current_list_role_and_ignores_stale_ids(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,selected=('17','888'))
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids == {17,999}
    bot.rest.remove_role_from_member.assert_awaited_once_with(123,4,18,reason='Roles and clan links')
    bot.rest.add_role_to_member.assert_not_awaited()


def test_grant_time_dashboard_grant_protected_even_zero_discord_permissions(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,protected=('19',))
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids == {17,18,999}
    bot.rest.add_role_to_member.assert_not_awaited()
    assert 'Your roles did not change.' in response_text(ctx)


def test_uncertain_discord_operation_never_retried_or_secret_printed(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,fail=19)
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert bot.rest.add_role_to_member.await_count == 1
    bot.rest.remove_role_from_member.assert_not_awaited()
    assert response_text(ctx).strip()=='## My roles Your roles may have changed. Select My roles again to check.'
    assert 'provider-private-text' not in response_text(ctx)


def test_public_panel_grey_fixed_ids_and_no_runtime_legacy_role_tables():
    from utils.family_links_content import panel_components
    from extensions.commands import family_links
    buttons=[button for row in panel_components()[0].components if hasattr(row,'components') for button in row.components]
    assert len(buttons)==4
    assert all(button.style == hikari.ButtonStyle.SECONDARY for button in buttons)
    assert all(button.custom_id.endswith(':') for button in buttons)
    assert not hasattr(family_links,'TH_LEVELS') and not hasattr(family_links,'SERVER_ROLES')
    assert not family_links.loader._loadables


def test_combined_save_registry_first_role_conflict_explicit_partial(monkeypatch):
    from contextlib import asynccontextmanager
    import json
    from aiohttp import web
    from cwl_web import town_halls as api, server_roles as choices_api, change_history
    from test_cwl_web_town_halls import fixture, request
    order=[]
    original=fixture()
    saved=deepcopy(original);saved['revision']+=1
    async def persist(*args,**kwargs): order.append('registry');return saved
    async def conflict(*args,**kwargs): order.append('role');raise town_halls.TownHallsConflict('changed')
    @asynccontextmanager
    async def mongo(_request): yield object()
    monkeypatch.setattr(api.shared,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    monkeypatch.setattr(api.shared,'mongo',mongo)
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':0,'roles':[]}))
    monkeypatch.setattr(api,'required',AsyncMock(return_value=original))
    monkeypatch.setattr(api.bases,'permissions',AsyncMock(return_value=(True,False)))
    monkeypatch.setattr(choices_api,'role_choices',AsyncMock(return_value=([{'value':'44','label':'TH19'}],{'44':'TH19'})))
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':0,'roles':{}}))
    monkeypatch.setattr(town_halls,'save',persist)
    monkeypatch.setattr(town_halls,'save_roles',conflict)
    monkeypatch.setattr(api.shared,'queue_action',AsyncMock(return_value=web.json_response({})))
    monkeypatch.setattr(change_history,'record_committed',AsyncMock())
    req=request(values={'emoji':'','role':'44','min':181000,'max':190000})
    body=run(req.json());body['role_revision']=0;req.json=AsyncMock(return_value=body)
    result=json.loads(run(api.save(req)).text)
    assert order==['registry','role']
    assert result['revision']==8 and result['role_revision']==0
    assert result['partial_result']['registry_saved'] is True
    assert result['partial_result']['role_saved'] is False
    assert next(field['value'] for field in result['fields'] if field['key']=='role')==''


def test_migration_roles_dry_run_then_apply_idempotent_preserves_sources(monkeypatch):
    from tools import migrate_town_halls as migration
    current=registry()
    current['levels']={str(level):{'emoji':''} for level in range(1,20)}
    current['levels']['12']['weight']={'min':1,'max':10}
    legacy={'_id':'warrior_settings:123','townhalls':{'19':44}}
    stored={'schema_version':1,'revision':0,'roles':{},'exists':False}
    writes=[]
    mongo=SimpleNamespace(warrior_settings=SimpleNamespace(find_one=AsyncMock(return_value=legacy)))
    monkeypatch.setattr(town_halls,'load',AsyncMock(return_value=current))
    async def load(*_): return deepcopy(stored)
    async def save(_mongo,_guild,changes,_actor,revision):
        assert revision==stored['revision'];writes.append(changes);stored.update(revision=revision+1,roles=dict(changes),exists=True);return deepcopy(stored)
    monkeypatch.setattr(town_halls,'load_roles',load)
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':0,'roles':[]}))
    monkeypatch.setattr(town_halls,'save_roles',save)
    safe=set(migration.LEGACY_ROLE_DEFAULTS.values())|{'44'}
    before=(BSON.encode(current),BSON.encode(legacy))
    first=run(migration.migrate_roles(mongo,123,safe_role_ids=safe))
    assert first['status']=='dry run' and writes==[]
    assert first['roles_proposed']['19']=='44'
    assert run(migration.migrate_roles(mongo,123,safe_role_ids=safe,apply=True))['applied']
    assert run(migration.migrate_roles(mongo,123,safe_role_ids=safe,apply=True))['status']=='already migrated'
    assert len(writes)==1
    assert before==(BSON.encode(current),BSON.encode(legacy))
    legacy['townhalls']['19']=55
    with pytest.raises(ValueError,match='conflicts'):
        run(migration.migrate_roles(mongo,123,safe_role_ids=safe|{'55'},apply=True))
    assert len(writes)==1


def test_role_gains_permission_after_open_is_skipped_and_reported(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch)
    monkeypatch.setattr(panel,'role_is_self_selectable',lambda *_:False)
    run(panel.select_roles(ctx,object(),bot,'th'))
    bot.rest.add_role_to_member.assert_not_awaited()
    assert member.role_ids=={17,18,999}
    assert 'Your roles did not change.' in response_text(ctx)


def test_context_outage_after_success_preserves_confirmed_change(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(999,),selected=('17','19'))
    monkeypatch.setattr(panel,'fresh_context',AsyncMock(side_effect=[(object(),{17:object(),19:object()},member),OSError('private upstream'),(object(),{17:object(),19:object()},member)]))
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={17,999}
    assert 'Added: TH17.' in response_text(ctx)
    assert 'Your other roles did not change. Try again in a minute.' in response_text(ctx)
    assert 'private upstream' not in response_text(ctx)


def test_family_content_document_has_one_banner_slot_and_fixed_footer():
    from extensions.commands import content
    document=content.DOCUMENTS['family-links']
    components=run(content.render(document,list(__import__('utils.family_links_content',fromlist=['DEFAULT_SECTIONS']).DEFAULT_SECTIONS)))
    assert len(components)==1 and len(content.media_galleries(components))==2
    assert content.MEDIA_SLOTS['family-links']==(('banner','Welcome banner'),)
    assert content.has_posting_channel('family-links')
    assert content.editable_media(document,['https://example.invalid/banner','https://example.invalid/footer'])=={'banner':'https://example.invalid/banner'}
    assert content.editable_media(document,['https://example.invalid/old-banner'])=={}


def test_clan_large_list_uses_select_and_legacy_clan_lookup_uses_current_reader(monkeypatch):
    from extensions.commands import family_links as panel
    rows=[{'name':f'Clan {index:02}','tag':f'#P{index}','emoji':''} for index in range(26)]
    monkeypatch.setattr(panel,'load_family_clans',AsyncMock(return_value={'Tactical':rows,'Flexible Fun':[],'FWA':[],'CWL':[]}))
    ctx=SimpleNamespace(respond=AsyncMock())
    run(panel.clan_links(ctx,object(),'war'))
    box=ctx.respond.call_args.kwargs['components'][0]
    menus=[child for row in box.components if hasattr(row,'components') for child in row.components if isinstance(child,hikari.impl.TextSelectMenuBuilder)]
    assert len(menus)==1 and len(menus[0].options)==25
    assert menus[0].custom_id=='family_links_clan_select:war'
    assert panel.load_family_clans.call_args.kwargs=={'include_cwl':True,'require_nonempty':False}


def test_legacy_role_values_only_open_private_new_menu(monkeypatch):
    from extensions.commands import family_links as panel
    from extensions.components import registered_functions
    opened=AsyncMock()
    monkeypatch.setattr(panel,'private_roles',opened)
    ctx=SimpleNamespace(interaction=SimpleNamespace(values=['th19:888']),respond=AsyncMock())
    run(panel.open_roles(ctx,mongo=object(),bot=object()))
    opened.assert_awaited_once()
    assert {'family_links_th','family_links_server_roles','family_links_war_clans','family_links_fwa_clans','family_links_cwl_clans','view_clan_info'} <= registered_functions.keys()


def test_architecture_no_runtime_hardcoded_th_role_ids():
    from pathlib import Path
    from tools.migrate_town_halls import LEGACY_ROLE_DEFAULTS
    identifiers=set(LEGACY_ROLE_DEFAULTS.values())
    root=Path(__file__).resolve().parents[1]
    found=[]
    for folder in ('extensions','utils','cwl_web','web/cwl/src'):
        for path in (root/folder).rglob('*'):
            if path.suffix not in ('.py','.ts','.tsx') or '.test.' in path.name:
                continue
            contents=path.read_text()
            if any(identifier in contents for identifier in identifiers): found.append(str(path.relative_to(root)))
    assert found==[]


@pytest.mark.parametrize('kind',['th','server'])
def test_protected_dashboard_role_cannot_be_self_selected_in_either_menu(monkeypatch,kind):
    panel,ctx,bot,member=transport(monkeypatch,protected=('19',),kind=kind)
    run(panel.select_roles(ctx,object(),bot,kind))
    bot.rest.add_role_to_member.assert_not_awaited()
    assert 19 not in member.role_ids


def test_private_menu_preselects_all_current_roles_and_uses_registry_emoji(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch)
    rows=[dict(role_id=str(level),label=f'TH{level}',short_line='',level=level,emoji='') for level in (19,18,17)]
    server_rows=[dict(role_id=str(role),label=f'Server {role}',short_line='Fixture',order=index) for index,role in enumerate((20,21))]
    member.role_ids.add(20)
    monkeypatch.setattr(panel,'choices',AsyncMock(side_effect=lambda _mongo,_guild,kind: rows if kind=='th' else server_rows))
    run(panel.private_roles(ctx,object(),bot))
    box=ctx.respond.call_args.kwargs['components'][0]
    menus=[child for row in box.components if hasattr(row,'components') for child in row.components if isinstance(child,hikari.impl.TextSelectMenuBuilder)]
    assert len(menus)==2
    assert [menu.max_values for menu in menus]==[3,2]
    assert all(menu.min_values==0 for menu in menus)
    assert [option.value for option in menus[0].options if option.is_default]==['18','17']
    assert [option.value for option in menus[1].options if option.is_default]==['20']
    assert box.components[-1].items[0].media=='assets/Gold_Footer.png'


def test_roles_25_cap_and_missing_registry_level_are_rejected():
    with pytest.raises(ValueError,match='at most 25'):
        town_halls.validate_roles({str(index):str(index+1000) for index in range(1,27)})
    with pytest.raises(ValueError,match='not in the registry'):
        town_halls.validate_roles({'18':'44'},registry())


def test_seed_is_dry_by_default_insert_only_and_preserves_existing_list(monkeypatch):
    from tools import seed_server_roles as seed
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':0,'roles':{}}))
    collection=SimpleNamespace(find_one=AsyncMock(return_value=None),insert_one=AsyncMock())
    mongo=SimpleNamespace(bot_config=collection)
    safe={entry['role_id'] for entry in seed.SEED_ROLES}
    result=run(seed.seed(mongo,123,safe_role_ids=safe))
    assert result['status']=='dry run' and not result['applied']
    collection.insert_one.assert_not_awaited()
    assert run(seed.seed(mongo,123,safe_role_ids=safe,apply=True))['applied']
    collection.find_one.return_value={'revision':1,'roles':seed.SEED_ROLES}
    assert run(seed.seed(mongo,123,safe_role_ids=safe,apply=True))['status']=='already migrated'
    assert collection.insert_one.await_count==1


def test_legacy_family_post_shape_can_be_linked_without_adopting_old_text_or_footer():
    from extensions.commands import content
    from hikari.impl import ContainerComponentBuilder as Box, TextDisplayComponentBuilder as Text, SectionComponentBuilder as Section, ThumbnailComponentBuilder as Thumbnail, SeparatorComponentBuilder as Separator, MessageActionRowBuilder as Row, TextSelectMenuBuilder as Menu, InteractiveButtonBuilder as Button, MediaGalleryComponentBuilder as Media, MediaGalleryItemBuilder as Item
    menu=lambda name:Row(components=[Menu(custom_id=name+':old',options=[hikari.impl.SelectOptionBuilder(label='Legacy',value='old')])])
    components=[Box(components=[Section(components=[Text(content='Old heading')],accessory=Thumbnail(media='https://example.invalid/icon')),Separator(),Text(content='TH'),Text(content='Old TH copy'),menu('family_links_th'),Separator(),Text(content='Server'),Text(content='Old roles copy'),menu('family_links_server_roles'),Separator(),Text(content='Clans'),Row(components=[Button(style=hikari.ButtonStyle.PRIMARY,custom_id='old:'+kind,label=kind) for kind in ('war','fwa','cwl')]),Media(items=[Item(media='https://example.invalid/old-banner')])])]
    doc=content.DOCUMENTS['family-links']
    assert run(content.supported_post_shape(doc,components))
    from utils.family_links_content import DEFAULT_SECTIONS
    assert [node.content for node in content.editable_text_nodes(doc,components)]==list(DEFAULT_SECTIONS)
    assert content.editable_media(doc,content.media_snapshot(components))=={}


@pytest.mark.parametrize('kind',['th','server'])
def test_role_newly_added_to_current_list_but_never_displayed_is_not_removed(monkeypatch,kind):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,18,19,999),selected=('17',),kind=kind)
    ctx.session['offered'][kind]=['17']
    ctx.session['held'][kind]=['17']
    run(panel.select_roles(ctx,object(),bot,kind))
    assert member.role_ids=={17,18,19,999}
    bot.rest.remove_role_from_member.assert_not_awaited()


def test_legacy_shared_role_is_controlled_and_removable_only_by_th_menu(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(19,999),selected=())
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={999}
    bot.rest.remove_role_from_member.assert_awaited_once_with(123,4,19,reason='Roles and clan links')


def test_server_menu_owner_hides_legacy_cross_list_duplicate_without_deletion(monkeypatch):
    rows=[dict(role_id='19',label='Shared',short_line='',order=0),dict(role_id='20',label='Only server',short_line='',order=1)]
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':2,'roles':rows}))
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':1,'roles':{'19':'19'}}))
    before=deepcopy(rows)
    assert run(server_roles.panel_roles(object(),123))==[rows[1]]
    assert rows==before


@pytest.mark.parametrize('broken',['missing','user','guild','message','expired','public','no_expiry'])
def test_private_session_is_bound_to_member_guild_message_and_expiry(monkeypatch,broken):
    from datetime import timedelta
    from utils.component_state import utcnow
    from extensions.commands import family_links as panel
    ctx=SimpleNamespace(interaction=SimpleNamespace(guild_id=123,custom_id='family_links_select_th:'+('1'*32),message=SimpleNamespace(id=700,flags=hikari.MessageFlag.EPHEMERAL)),user=SimpleNamespace(id=4))
    row={'type':'family_roles','guild_id':123,'user_id':4,'message_id':700,'instance':'1'*32,'active':True,'offered':{'th':['17'],'server':[]},'held':{'th':['17'],'server':[]},'submissions':{},'expires_at':utcnow()+timedelta(minutes=15)}
    if broken=='missing': row=None
    elif broken=='user': row['user_id']=5
    elif broken=='guild': row['guild_id']=124
    elif broken=='message': row['message_id']=701
    elif broken=='expired': row['expires_at']=utcnow()-timedelta(seconds=1)
    elif broken=='no_expiry': row.pop('expires_at')
    elif broken=='public': ctx.interaction.message.flags=hikari.MessageFlag.NONE
    reader=AsyncMock(return_value=row)
    monkeypatch.setattr(panel,'get_state',reader)
    assert run(panel.role_session(ctx,object())) is None
    if broken!='public': reader.assert_awaited_once_with(__import__('unittest.mock',fromlist=['ANY']).ANY,'family-roles:123:4:700:'+('1'*32))


def test_missing_displayed_options_fails_closed_before_discord_reads(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch)
    monkeypatch.setattr(panel,'role_session',AsyncMock(return_value=None))
    run(panel.select_roles(ctx,object(),bot,'th'))
    panel.fresh_context.assert_not_awaited()
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()
    assert 'Open My roles again' in response_text(ctx)


def test_actor_hierarchy_excludes_zero_permission_role_from_choices_and_save(monkeypatch):
    from cwl_web import server_roles as api
    role=SimpleNamespace(id=44,name='Higher role',color=0,position=5,permissions=0)
    own=SimpleNamespace(id=55,position=2,permissions=0)
    person=SimpleNamespace(id=8,role_ids=[55])
    guild=SimpleNamespace(id=123,owner_id=99,get_role=lambda identifier:{44:role,55:own}.get(identifier))
    monkeypatch.setattr(api,'hierarchy',AsyncMock(return_value=({44:role},guild,object(),person)))
    monkeypatch.setattr(api,'role_is_self_selectable',lambda *_:True)
    monkeypatch.setattr(api,'dashboard_grant_roles',AsyncMock(return_value=set()))
    assert run(api.role_choices(object(),{}))[0]==[]
    from aiohttp import web
    with pytest.raises(web.HTTPBadRequest): run(api.require_safe_roles(object(),{},['44']))


def test_combined_role_commit_then_transport_error_reports_unknown_without_retry(monkeypatch):
    from contextlib import asynccontextmanager
    import json
    from aiohttp import web
    from cwl_web import town_halls as api, server_roles as choices_api, change_history
    from test_cwl_web_town_halls import fixture, request
    original=fixture()
    saved=deepcopy(original);saved['revision']+=1
    actual_roles={'revision':0,'roles':{}}
    @asynccontextmanager
    async def mongo(_): yield object()
    async def commit_then_timeout(*_args,**_kwargs):
        actual_roles.update(revision=1,roles={'19':'44'})
        raise OSError('private transport error')
    writer=AsyncMock(side_effect=commit_then_timeout)
    monkeypatch.setattr(api.shared,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    monkeypatch.setattr(api.shared,'mongo',mongo)
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':0,'roles':[]}))
    monkeypatch.setattr(api,'required',AsyncMock(return_value=original))
    monkeypatch.setattr(api.bases,'permissions',AsyncMock(return_value=(True,False)))
    monkeypatch.setattr(choices_api,'role_choices',AsyncMock(return_value=([{'value':'44','label':'TH19'}],{'44':'TH19'})))
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':0,'roles':{}}))
    monkeypatch.setattr(town_halls,'save',AsyncMock(return_value=saved))
    monkeypatch.setattr(town_halls,'save_roles',writer)
    monkeypatch.setattr(api.shared,'queue_action',AsyncMock(return_value=web.json_response({})))
    monkeypatch.setattr(change_history,'record_committed',AsyncMock())
    req=request(values={'emoji':'','role':'44','min':181000,'max':190000})
    body=run(req.json());body['role_revision']=0;req.json=AsyncMock(return_value=body)
    result=json.loads(run(api.save(req)).text)
    assert actual_roles=={'revision':1,'roles':{'19':'44'}}
    assert result['partial_result']['role_saved'] is None
    assert result['partial_result']['role_outcome']=='unknown'
    assert 'could not be confirmed' in result['partial_result']['role_error']
    assert 'private transport error' not in json.dumps(result)
    writer.assert_awaited_once()


def test_actual_private_response_binding_persists_immutable_offered_sets(monkeypatch):
    from datetime import timedelta
    panel,ctx,bot,member=transport(monkeypatch)
    run(panel.private_roles(ctx,object(),bot))
    ctx.fetch_response.assert_awaited_once_with(700)
    call=panel.insert_state.call_args
    assert call.args[1]['_id']=='family-roles:123:4:700:'+call.args[1]['instance']
    assert call.args[1]['guild_id']==123 and call.args[1]['user_id']==4
    assert call.args[1]['message_id']==700
    assert call.args[1]['offered']=={'th':['19','18','17'],'server':[]}
    assert call.kwargs['ttl']==timedelta(minutes=15)
    for row in ctx.respond.call_args.kwargs['components'][0].components:
        for child in getattr(row,'components',[]):
            assert getattr(child,'custom_id','').split(':')[1]==call.args[1]['instance']


def test_real_session_validation_allows_only_the_matching_private_panel(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch)
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={17,18,19,999}
    bot.rest.add_role_to_member.assert_awaited_once_with(123,4,19,reason='Roles and clan links')


def test_th_role_save_rejects_server_duplicate_before_any_write(monkeypatch):
    doc, collection=owner(monkeypatch)
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':1,'roles':[{'role_id':'44','label':'Server','short_line':'','order':0}]}))
    before=BSON.encode(doc)
    with pytest.raises(town_halls.TownHallRoleOverlap,match='This role is already a server role.'):
        run(town_halls.save_roles(object(),123,{'19':'44'},12,0))
    collection.insert_one.assert_not_awaited()
    collection.find_one_and_update.assert_not_awaited()
    assert BSON.encode(doc)==before


def test_server_save_rejects_th_duplicate_before_any_write(monkeypatch):
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':1,'roles':{'19':'44'}}))
    collection=SimpleNamespace(find_one=AsyncMock(return_value=None),insert_one=AsyncMock(),find_one_and_update=AsyncMock())
    mongo=SimpleNamespace(bot_config=collection)
    with pytest.raises(server_roles.ServerRoleOverlap,match='This role is already used for a Town Hall.'):
        run(server_roles.save(mongo,123,[{'role_id':'44','label':'Server','short_line':'','order':0}],12,0))
    collection.insert_one.assert_not_awaited()
    collection.find_one_and_update.assert_not_awaited()


def test_seed_dry_run_enumerates_every_overlap_and_apply_has_no_write(monkeypatch):
    from tools import seed_server_roles as seed
    roles={'19':seed.SEED_ROLES[0]['role_id'],'12':seed.SEED_ROLES[1]['role_id']}
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':1,'roles':roles}))
    collection=SimpleNamespace(find_one=AsyncMock(return_value=None),insert_one=AsyncMock())
    mongo=SimpleNamespace(bot_config=collection)
    safe={row['role_id'] for row in seed.SEED_ROLES}
    result=run(seed.seed(mongo,123,safe_role_ids=safe))
    assert result['status']=='conflict' and not result['applied']
    assert {row['role_id'] for row in result['conflicts']}==set(roles.values())
    with pytest.raises(server_roles.ServerRoleOverlap) as error:
        run(seed.seed(mongo,123,safe_role_ids=safe,apply=True))
    assert len(error.value.conflicts)==2
    collection.insert_one.assert_not_awaited()


def test_roles_migration_reports_all_cross_duplicates_and_stops_apply(monkeypatch):
    from tools import migrate_town_halls as migration
    doc=registry();doc['levels']={str(level):{'emoji':''} for level in range(1,20)}
    doc['levels']['12']['weight']={'min':1,'max':10}
    monkeypatch.setattr(town_halls,'load',AsyncMock(return_value=doc))
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':0,'roles':{}}))
    writer=AsyncMock();monkeypatch.setattr(town_halls,'save_roles',writer)
    entries=[{'role_id':migration.LEGACY_ROLE_DEFAULTS[level],'label':f'Server {level}','short_line':'','order':index} for index,level in enumerate(('18','17'))]
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':1,'roles':entries}))
    mongo=SimpleNamespace(warrior_settings=SimpleNamespace(find_one=AsyncMock(return_value=None)))
    safe=set(migration.LEGACY_ROLE_DEFAULTS.values())
    result=run(migration.migrate_roles(mongo,123,safe_role_ids=safe))
    assert result['status']=='conflict' and {row['level'] for row in result['conflicts']}=={18,17}
    with pytest.raises(town_halls.TownHallRoleOverlap) as error:
        run(migration.migrate_roles(mongo,123,safe_role_ids=safe,apply=True))
    assert len(error.value.conflicts)==2
    writer.assert_not_awaited()


def test_same_process_concurrent_cross_list_saves_cannot_both_claim_role(monkeypatch):
    async def scenario():
        th={'schema_version':1,'revision':0,'roles':{},'exists':False}
        sr={'revision':0,'roles':[],'exists':False}
        writes=[]
        async def read_th(*_):
            await asyncio.sleep(0)
            return deepcopy(th)
        async def read_sr(*_):
            await asyncio.sleep(0)
            return deepcopy(sr)
        async def insert_th(row):
            writes.append('th');th.update(deepcopy(row),exists=True)
        async def insert_sr(row):
            writes.append('server');sr.update(deepcopy(row),exists=True)
        monkeypatch.setattr(town_halls,'load',AsyncMock(return_value=registry()))
        monkeypatch.setattr(town_halls,'load_roles',read_th)
        monkeypatch.setattr(server_roles,'load',read_sr)
        monkeypatch.setattr(town_halls,'_roles_collection',lambda _:SimpleNamespace(insert_one=insert_th))
        mongo=SimpleNamespace(bot_config=SimpleNamespace(insert_one=insert_sr))
        results=await asyncio.gather(
            town_halls.save_roles(mongo,123,{'19':'44'},12,0),
            server_roles.save(mongo,123,[{'role_id':'44','label':'Server','short_line':'','order':0}],12,0),
            return_exceptions=True)
        assert len(writes)==1
        assert sum(isinstance(result,(town_halls.TownHallRoleOverlap,server_roles.ServerRoleOverlap)) for result in results)==1
        assert not town_halls.cross_role_conflicts(th['roles'],sr['roles'])
    run(scenario())


def test_legacy_overlap_visible_only_in_th_private_menu_and_deselect_removes(monkeypatch):
    from extensions.commands import family_links
    source_choices=family_links.choices
    panel,ctx,bot,member=transport(monkeypatch,held=(19,999),selected=())
    rows=[{'role_id':'19','label':'Legacy duplicate','short_line':'','order':0},
          {'role_id':'20','label':'Server only','short_line':'','order':1}]
    monkeypatch.setattr(panel,'choices',source_choices)
    monkeypatch.setattr(town_halls,'role_choices',AsyncMock(return_value=[{'level':19,'role_id':'19','emoji':''}]))
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':1,'roles':{'19':'19'}}))
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':1,'roles':rows}))
    run(panel.private_roles(ctx,object(),bot))
    offered=panel.insert_state.call_args.args[1]['offered']
    assert offered=={'th':['19'],'server':['20']}
    current=panel.insert_state.call_args.args[1]
    ctx.interaction.custom_id='family_links_select_server:'+current['instance']
    run(panel.select_roles(ctx,object(),bot,'server'))
    assert member.role_ids=={19,999}
    bot.rest.remove_role_from_member.assert_not_awaited()
    current=panel.insert_state.call_args.args[1]
    ctx.interaction.custom_id='family_links_select_th:'+current['instance']
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={999}
    bot.rest.remove_role_from_member.assert_awaited_once_with(123,4,19,reason='Roles and clan links')


def test_combined_th_duplicate_is_rejected_before_registry_or_role_write(monkeypatch):
    from contextlib import asynccontextmanager
    from aiohttp import web
    from cwl_web import town_halls as api, server_roles as choices_api, change_history
    from test_cwl_web_town_halls import fixture, request
    @asynccontextmanager
    async def mongo(_): yield object()
    monkeypatch.setattr(api.shared,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    monkeypatch.setattr(api.shared,'mongo',mongo)
    monkeypatch.setattr(api,'required',AsyncMock(return_value=fixture()))
    monkeypatch.setattr(api.bases,'permissions',AsyncMock(return_value=(True,False)))
    monkeypatch.setattr(choices_api,'role_choices',AsyncMock(return_value=([{'value':'44','label':'Candidate'}],{'44':'Candidate'})))
    monkeypatch.setattr(town_halls,'load_roles',AsyncMock(return_value={'revision':0,'roles':{}}))
    monkeypatch.setattr(server_roles,'load',AsyncMock(return_value={'revision':1,'roles':[{'role_id':'44','label':'Server','short_line':'','order':0}]}))
    writers=[AsyncMock(),AsyncMock(),AsyncMock(),AsyncMock()]
    monkeypatch.setattr(town_halls,'save',writers[0]);monkeypatch.setattr(town_halls,'save_roles',writers[1])
    monkeypatch.setattr(change_history,'record_committed',writers[2]);monkeypatch.setattr(api.shared,'queue_action',writers[3])
    req=request(values={'emoji':'','role':'44','min':181000,'max':190000})
    body=run(req.json());body['role_revision']=0;req.json=AsyncMock(return_value=body)
    with pytest.raises(web.HTTPBadRequest) as error: run(api.save(req))
    assert error.value.text=='This role is already a server role.'
    for writer in writers: writer.assert_not_awaited()


def test_private_reply_never_displays_a_role_twice_when_reads_disagree(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(19,),selected=())
    row=dict(role_id='19',label='Shared',short_line='',level=19,emoji='')
    monkeypatch.setattr(panel,'choices',AsyncMock(return_value=[row]))
    run(panel.private_roles(ctx,object(),bot))
    offered=panel.insert_state.call_args.args[1]['offered']
    assert offered=={'th':['19'],'server':[]}


@pytest.mark.parametrize('version',[True,False,'1',2])
def test_roles_owner_rejects_noninteger_or_unknown_schema(monkeypatch,version):
    collection=SimpleNamespace(find_one=AsyncMock(return_value={'schema_version':version,'revision':0,'roles':{}}))
    monkeypatch.setattr(town_halls,'_roles_collection',lambda _:collection)
    with pytest.raises(ValueError,match='schema version 1'):
        run(town_halls.load_roles(object(),123))


@pytest.mark.parametrize('staff_action', ['add', 'remove'])
def test_1401_unchanged_selection_preserves_staff_changes(monkeypatch, staff_action):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('17',))
    if staff_action=='add':member.role_ids.add(18)
    else:member.role_ids.remove(17)
    expected=set(member.role_ids)
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids==expected
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()
    successor=panel.insert_state.call_args.args[1]
    assert set(map(int,successor['held']['th']))==expected
    assert successor['instance']!=ctx.session['instance']
    assert ctx.respond.call_args.kwargs['edit'] is True
    assert ctx.respond.call_args.kwargs['components'][0].components[0].content=='No change.'


def test_1401_replay_after_staff_add_and_restart_preserves_successor(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('17','19'))
    run(panel.select_roles(ctx,object(),bot,'th'))
    member.role_ids.add(18)
    monkeypatch.setattr(panel,'_locks',{})
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={17,18,19}
    assert bot.rest.add_role_to_member.await_count==1
    bot.rest.remove_role_from_member.assert_not_awaited()
    assert panel.insert_state.await_count==1
    assert panel.ALREADY_SAVED in response_text(ctx)
    assert 'edit' not in ctx.respond.call_args.kwargs


def test_1401_successor_baseline_supports_later_removal(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('17','19'))
    run(panel.select_roles(ctx,object(),bot,'th'))
    successor=panel.insert_state.call_args.args[1]
    assert set(successor['held']['th'])=={'17','19'}
    ctx.interaction.custom_id='family_links_select_th:'+successor['instance']
    ctx.interaction.values=('17',)
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={17}
    bot.rest.remove_role_from_member.assert_awaited_once_with(123,4,19,reason='Roles and clan links')
    assert len(ctx.sessions)==3


@pytest.mark.parametrize('boundary', ['claim', 'receipt', 'provider'])
def test_1401_ambiguous_commit_no_successor_or_retry(monkeypatch,boundary):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('17','19'))
    original=panel.update_state.side_effect
    calls=0
    async def update(*args,**kwargs):
        nonlocal calls
        calls+=1
        result=await original(*args,**kwargs)
        if calls==({'claim':1,'receipt':2}.get(boundary,-1)):raise OSError('private transport')
        return result
    monkeypatch.setattr(panel,'update_state',AsyncMock(side_effect=update))
    if boundary=='provider':
        async def add(*args,**kwargs):
            member.role_ids.add(args[2])
            raise TimeoutError('private provider')
        bot.rest.add_role_to_member.side_effect=add
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert panel.UNCERTAIN_ROLES in response_text(ctx)
    panel.insert_state.assert_not_awaited()
    before=bot.rest.add_role_to_member.await_count
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert bot.rest.add_role_to_member.await_count==before
    assert before==(0 if boundary=='claim' else 1)
    assert 'private' not in response_text(ctx)


def test_1401_claim_loser_no_writes(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('19',))
    monkeypatch.setattr(panel,'update_state',AsyncMock(return_value=SimpleNamespace(matched_count=0)))
    run(panel.select_roles(ctx,object(),bot,'th'))
    query=panel.update_state.call_args.args[1]
    assert {key:query[key] for key in ('guild_id','user_id','message_id','instance')}==dict(guild_id=123,user_id=4,message_id=700,instance='1'*32)
    assert query['submissions.th']=={'$exists':False}
    assert '$gt' in query['expires_at'] and query['active'] is True
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()


def test_1401_staff_add_during_mutation_survives(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('19',))
    async def add(*args,**kwargs):member.role_ids.update((18,args[2]))
    bot.rest.add_role_to_member.side_effect=add
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={18,19}
    bot.rest.remove_role_from_member.assert_awaited_once_with(123,4,17,reason='Roles and clan links')


def test_1401_missing_baseline_fails_closed(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch)
    del ctx.session['held']
    run(panel.select_roles(ctx,object(),bot,'th'))
    panel.update_state.assert_not_awaited()
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()


def test_1401_known_partial_failure_has_successor(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(),selected=('17','19'))
    async def add(*args,**kwargs):
        if args[2]==19:raise hikari.ForbiddenError(url='',headers={},raw_body=b'',code=50013)
        member.role_ids.add(args[2])
    bot.rest.add_role_to_member.side_effect=add
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert member.role_ids=={17}
    assert panel.insert_state.call_args.args[1]['held']['th']==['17']
    assert ctx.respond.call_args.kwargs['components'][0].components[0].content=='Added: TH17. Your other roles did not change. Try again in a minute.'


def test_1401_already_target_avoids_mutation_even_after_authority_tightens(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(),selected=('19',))
    member.role_ids.add(19)
    monkeypatch.setattr(panel,'role_is_self_selectable',lambda *_:False)
    run(panel.select_roles(ctx,object(),bot,'th'))
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()
    assert ctx.respond.call_args.kwargs['components'][0].components[0].content=='No change.'


def test_1401_receipt_failure_before_commit_blocks_replay(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('17','19'))
    original=panel.update_state.side_effect
    async def update(mongo,query,change):
        if 'submissions.th.token' in query:raise OSError('private persistence detail')
        return await original(mongo,query,change)
    monkeypatch.setattr(panel,'update_state',AsyncMock(side_effect=update))
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert ctx.session['submissions']['th']['status']=='claimed'
    assert panel.UNCERTAIN_ROLES in response_text(ctx)
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert bot.rest.add_role_to_member.await_count==1
    panel.insert_state.assert_not_awaited()
    assert panel.UNCERTAIN_ROLES in response_text(ctx)


@pytest.mark.parametrize('disappearance', ['expired', 'missing_receipt'])
def test_1401_claim_without_receipt_never_claims_saved(monkeypatch,disappearance):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('19',))
    async def lose(*_args,**_kwargs):
        if disappearance=='expired':ctx.sessions.clear()
        return SimpleNamespace(matched_count=0)
    monkeypatch.setattr(panel,'update_state',AsyncMock(side_effect=lose))
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert panel.STALE_ROLES in response_text(ctx)
    assert panel.ALREADY_SAVED not in response_text(ctx)
    assert ctx.respond.call_args.kwargs['components'][0].accent_color==panel.WU_RED
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()
    panel.insert_state.assert_not_awaited()


def test_1401_other_menu_retirement_is_stale_not_saved(monkeypatch):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('19',))
    ctx.session['active']=False
    ctx.session['submissions']['server']={'status':'done'}
    run(panel.select_roles(ctx,object(),bot,'th'))
    assert panel.STALE_ROLES in response_text(ctx)
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()
    panel.insert_state.assert_not_awaited()


@pytest.mark.parametrize('outcome', ['success','noop','uncertain','partial'])
def test_d2_role_result_accents(monkeypatch,outcome):
    panel,ctx,bot,member=transport(monkeypatch,held=(17,),selected=('17','19'))
    if outcome=='noop':ctx.interaction.values=('17',)
    elif outcome=='uncertain':
        bot.rest.add_role_to_member.side_effect=TimeoutError('private upstream')
    elif outcome=='partial':
        ctx.interaction.values=('18','19')
        async def add(*args,**kwargs):
            if args[2]==19:raise hikari.ForbiddenError(url='',headers={},raw_body=b'',code=50013)
            member.role_ids.add(args[2])
        bot.rest.add_role_to_member.side_effect=add
    run(panel.select_roles(ctx,object(),bot,'th'))
    expected=panel.WU_RED if outcome in ('uncertain','partial') else panel.WU_GOLD
    assert ctx.respond.call_args.kwargs['components'][0].accent_color==expected
    if outcome=='uncertain':panel.insert_state.assert_not_awaited()
    else:panel.insert_state.assert_awaited_once()


@pytest.mark.parametrize('emoji,expected',[('🎯','🎯'),('invalid','🎮')])
def test_c5_current_clan_uses_registry_or_type_emoji(monkeypatch,emoji,expected):
    from extensions.commands import family_links as panel
    groups={name:[] for name in ('Tactical','Flexible Fun','FWA','CWL')}
    groups['Flexible Fun']=[{'name':'Fixture clan','tag':'#P0Y','emoji':emoji}]
    monkeypatch.setattr(panel,'load_family_clans',AsyncMock(return_value=groups))
    ctx=SimpleNamespace(interaction=SimpleNamespace(values=['#P0Y']),respond=AsyncMock())
    run(panel.current_clan(ctx,object()))
    links=[child for row in ctx.respond.call_args.kwargs['components'][0].components if hasattr(row,'components') for child in row.components if isinstance(child,hikari.impl.LinkButtonBuilder)]
    assert len(links)==1 and str(links[0].emoji)==expected

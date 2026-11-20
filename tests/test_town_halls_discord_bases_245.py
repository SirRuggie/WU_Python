"""Registry-only Discord menus, shared media and retired edit/upload controls."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import hikari
import pytest
from utils import town_halls
from utils.town_hall_base_views import base_menu, base_choice, GUILD_ID
from test_town_halls_bases import registry, LINK
from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE
from utils.manage_operations_runtime import publish_base_image_snapshot


def bases_doc():
    doc=registry();doc['_id']=str(GUILD_ID)
    for path,value in [('merged.link',LINK),('non_merged.link',LINK),('war_image','https://example.org/war.jpg'),('active_image','https://example.org/active.jpg'),('merged.instructions','Merged instructions'),('non_merged.instructions','Non-merged instructions'),('merged.upgrade_notes','Upgrade notes')]:
        doc=town_halls.set_base_field(doc,19,path,value)
    return doc


@pytest.fixture
def snapshot(monkeypatch):
    doc=bases_doc()
    monkeypatch.setattr(town_halls,'_snapshot',doc)
    monkeypatch.setattr(town_halls,'_snapshot_guild',str(GUILD_ID))
    return doc


def walk(value):
    if isinstance(value,list):
        for item in value:yield from walk(item)
    elif isinstance(value,dict):
        yield value
        for item in value.get('components',[]):yield from walk(item)


def built(parts):return [part.build()[0] for part in parts]


def context(allowed=True):
    member=NS(mention='<@222>',get_roles=lambda:[NS(id=993015846442127420)] if allowed else [])
    return NS(guild_id=GUILD_ID,channel_id=333,member=member,respond=AsyncMock(),interaction=NS(id=999,custom_id='dashboard_image_submit:old',values=['th19_new'],member=member))


def test_menus_have_linked_registry_variants_newest_first_and_saved_emoji(snapshot):
    payload=base_menu('fixture').build()[0]
    assert [item['label'] for item in payload['options']]==['TH19 Merged','TH19 Non-merged']
    assert [item['value'] for item in payload['options']]==['th19','th19_new']
    assert payload['options'][0]['emoji']['id']=='123456789012345678'
    del snapshot['levels']['19']['bases']['non_merged']['link']
    assert [item['value'] for item in base_menu('fixture').build()[0]['options']]==['th19']


def test_legacy_variant_values_resolve_shared_images_and_current_visibility(snapshot):
    merged,nonmerged=base_choice('th19'),base_choice('th19_new')
    assert merged['war_image']==nonmerged['war_image']=='https://example.org/war.jpg'
    assert merged['active_image']==nonmerged['active_image']=='https://example.org/active.jpg'
    assert merged['friendly_name']=='Town Hall 19 Merged'
    assert nonmerged['friendly_name']=='Town Hall 19 Non-merged'
    assert base_choice('th019') is None and base_choice('th11') is None
    del snapshot['levels']['19']['bases']['non_merged']['link']
    assert base_choice('th19_new') is None


def test_empty_snapshot_has_no_command_menu_and_stable_disabled_recruit_selector(monkeypatch):
    from utils.recruit_question_native import native_components
    monkeypatch.setattr(town_halls,'_snapshot',None)
    assert base_menu('fixture') is None and base_choice('th19') is None
    payload=built(native_components('fwa_bases_upon_approval',recruit_mention='<@1>',recruiter_mention='<@2>'))
    menu=next(item for item in walk(payload) if item['type']==hikari.ComponentType.TEXT_SELECT_MENU)
    assert menu['disabled'] and menu['options'][0]['label']=='No base links are set.'
    assert len([item for item in walk(payload) if item['type']==hikari.ComponentType.TEXT_DISPLAY])==3


def test_management_card_only_lists_fwa_levels_and_no_edit_controls(snapshot):
    from extensions.commands.clan.dashboard.fwa_data import town_hall_base_card
    payload=built(town_hall_base_card());nodes=list(walk(payload))
    links=[item for item in nodes if item['type']==hikari.ComponentType.BUTTON]
    assert [item['label'] for item in links]==['Open Town Hall 19','Open Town Hall 12']
    assert all(item['url'].startswith('https://dash.warriorsunited.cc/manage/town-halls/') for item in links)
    assert not any('custom_id' in item for item in nodes)
    assert 'Town Hall bases are managed on the dashboard.' in str(payload)


def test_base_posts_keep_mention_scope_and_old_values_without_mongo_reads(snapshot):
    from extensions.commands.fwa.bases import fwa_bases_th_select
    ctx=context();rest=NS(fetch_member=AsyncMock(return_value=NS(id=111,mention='<@111>')),create_message=AsyncMock())
    mongo=NS(fwa_data=NS(find_one=AsyncMock(side_effect=AssertionError('No legacy reads')),update_one=AsyncMock()))
    asyncio.run(fwa_bases_th_select.__wrapped__._func(user_id=111,base_only=False,bot=NS(rest=rest),mongo=mongo,ctx=ctx))
    sent=rest.create_message.await_args.kwargs
    assert sent['user_mentions']==[111] and sent['role_mentions'] is True
    text=str(built(sent['components']))
    assert 'Town Hall 19 Non-merged' in text and 'Non-merged instructions' in text
    assert 'https://example.org/war.jpg' in text and 'https://example.org/active.jpg' in text
    mongo.fwa_data.find_one.assert_not_awaited();mongo.fwa_data.update_one.assert_not_awaited()


def test_retired_upload_never_opens_modal_downloads_or_writes(snapshot):
    from extensions.commands.clan.dashboard import image_uploads
    ctx=context();ctx.respond_with_modal=AsyncMock();mongo=NS(fwa_data=NS(update_one=AsyncMock()))
    asyncio.run(image_uploads.fwa_image_upload.__wrapped__._func(ctx=ctx,action_id='war:th19_new',mongo=mongo))
    ctx.respond_with_modal.assert_not_awaited();mongo.fwa_data.update_one.assert_not_awaited()
    assert 'Town Hall bases are managed' in str(built(ctx.respond.await_args.kwargs['components']))
    ctx=context(False)
    asyncio.run(image_uploads.fwa_image_upload.__wrapped__._func(ctx=ctx,action_id='war:th19',mongo=mongo))
    assert 'role required' in ctx.respond.await_args.args[0]


def test_image_snapshot_publishes_both_old_keys_and_drops_stale_entries(snapshot):
    old_war,old_active=dict(FWA_WAR_BASE),dict(FWA_ACTIVE_WAR_BASE)
    try:
        FWA_WAR_BASE['th11']='stale'
        publish_base_image_snapshot(snapshot)
        assert FWA_WAR_BASE=={'th19':'https://example.org/war.jpg','th19_new':'https://example.org/war.jpg'}
        assert FWA_ACTIVE_WAR_BASE=={'th19':'https://example.org/active.jpg','th19_new':'https://example.org/active.jpg'}
        before=dict(FWA_WAR_BASE)
        invalid=deepcopy(snapshot);invalid['levels']['19']['bases']['war_image']='bad'
        with pytest.raises(ValueError):publish_base_image_snapshot(invalid)
        assert FWA_WAR_BASE==before
        assert publish_base_image_snapshot(None) is False
    finally:
        FWA_WAR_BASE.clear();FWA_WAR_BASE.update(old_war);FWA_ACTIVE_WAR_BASE.clear();FWA_ACTIVE_WAR_BASE.update(old_active)



def test_transport_menu_keeps_the_owner_highest25_cap(snapshot,caplog):
    for level in range(20,34):
        updated=town_halls.add_level(snapshot,level)
        updated=town_halls.set_base_field(updated,level,'merged.link',LINK)
        updated=town_halls.set_base_field(updated,level,'non_merged.link',LINK)
        snapshot.clear();snapshot.update(updated)
    payload=base_menu('fixture').build()[0]
    assert len(payload['options'])==25
    assert payload['options'][0]['value']=='th33'
    assert len([row for row in caplog.records if 'highest25' in row.message])==1


def test_base_manager_can_refresh_snapshot_without_admin_write_permission(snapshot):
    from utils import manage_operations_runtime as runtime
    row=dict(guild_id=GUILD_ID,section='town_halls',action='refresh',values={},revision=snapshot['revision'])
    async def allowed(actor,section,mongo,write=False):return section=='fwa_bases' and write
    with patch('utils.dashboard_access.dashboard_allowed',allowed),patch.object(town_halls,'load',AsyncMock(return_value=snapshot)),patch.object(runtime,'refresh_town_halls_cache',AsyncMock(return_value=True)) as refresh:
        result=asyncio.run(runtime.apply_town_halls_refresh(object(),row,{'user_id':'123'}))
        assert result['revision']==snapshot['revision']
        refresh.assert_awaited_once()


def test_levels_below_th16_show_no_merged_word(snapshot):
    from test_town_halls_bases import LINK
    doc = town_halls.set_base_field(snapshot, 12, 'merged.link', LINK)
    town_halls._snapshot = doc
    labels = [item['label'] for item in base_menu('fixture').build()[0]['options']]
    assert labels == ['TH19 Merged', 'TH19 Non-merged', 'TH12']
    assert base_choice('th12')['friendly_name'] == 'Town Hall 12'
    assert base_choice('th12')['display_name'] == 'TH12'
    assert base_choice('th19')['friendly_name'] == 'Town Hall 19 Merged'
    assert town_halls.variant_label(15, 'merged') == '' and town_halls.variant_label(16, 'merged') == 'Merged'

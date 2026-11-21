"""Historical renderer and real old web-save layouts; fixture-only transport."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from cwl_web import manage_content
from extensions.commands import content
from fixtures import info_posts_pre270 as old
from test_cwl_web_manage_content import db
from utils.gauntlet_content import (
    AMBIGUOUS_NOTICE, COMPACT_BODY_SLOTS, LAYOUT_VERSION, layout_for,
    logical_sections, sections_for, validate_sections,
)

FIXTURE = json.loads((Path(__file__).parent/'fixtures/info_posts_pre270.json').read_text())
BUILDERS = {'about-us':old.build_aboutus,'strike-system':old.build_strikesystem,'family-particulars':old.build_familyparticulars}


def raw(key='family-particulars'):
    return FIXTURE['documents'][key][:]


def compact():
    item=manage_content.descriptor('gauntlet--family-particulars')
    loaded={'sections':raw(),'media':{},'revision':3}
    # The real old schema enumerates semantic labels into physical0..19.
    descriptor=old.schema(item,loaded)
    defaults=sections_for('family-particulars')
    semantic=[defaults[i] for i in (0,1,2,4,5,7,8,10,11,12,14,15,17,18,20,21,23,24,26,27)]
    values={f['key']:v for f,v in zip([f for f in descriptor['fields'] if f['key'].startswith('sections.')],semantic,strict=True)}
    return old.candidate(item,loaded,{'revision':3,'values':values})['sections']


@pytest.mark.parametrize('key',BUILDERS)
def test_actual_historical_renderer_and_extractor_order_and_old_web_flow(key):
    fields=raw(key)
    components=BUILDERS[key](fields)
    # Actual old renderer traversed by the same supported legacy extraction path.
    extracted=[n.content for n in old.editable_text_nodes(content.DOCUMENTS[key],components)]
    assert extracted==fields
    item=manage_content.descriptor('gauntlet--'+key)
    loaded={'sections':fields[:],'media':{},'revision':4}
    schema=old.schema(item,loaded)
    indexes=[int(f['key'].split('.')[1]) for f in schema['fields'] if f['key'].startswith('sections.')]
    assert indexes==list(range(20 if key=='family-particulars' else 12))
    result=old.candidate(item,loaded,{'revision':4,'values':{f'sections.{i}':f'body {i}' for i in indexes}})
    assert result['sections'][len(indexes):]==fields[len(indexes):]
    assert loaded['sections']==fields
    if key!='family-particulars':
        # All12 old web labels match the actual renderer extraction; no remap.
        assert layout_for(key,fields)=='standard'
        assert sections_for(key,fields)[:12]==fields


@pytest.mark.parametrize('canonical',[False,True])
def test_genuine_renderer_layout_keeps_each_body_and_hidden_bytes(canonical):
    fields=raw()
    if canonical:fields=sections_for('family-particulars',fields)
    before=fields[:]
    view=logical_sections('family-particulars',fields)
    assert layout_for('family-particulars',fields)=='standard'
    assert [view[i] for i in COMPACT_BODY_SLOTS]==[before[i] for i in COMPACT_BODY_SLOTS]
    assert fields==before


def test_compact_old_save_reproduces_phone_then_maps_every_body_without_expanding():
    fields=compact();before=fields[:]
    assert all(word in fields[index].upper() for index,word in ((5,'CLAN GAMES'),(8,'WAR STATUS'),(12,'BATTLE DAY')))
    assert layout_for('family-particulars',fields)=='compact'
    assert len(sections_for('family-particulars',fields))==28
    view=logical_sections('family-particulars',fields)
    for logical,physical in COMPACT_BODY_SLOTS.items():assert view[logical]==before[physical]
    assert fields==before
    assert validate_sections('family-particulars',fields)==before


@pytest.mark.parametrize('case',['compact34','partial','partial34','custom','other-title','other-title34'])
def test_ambiguous_rows_are_not_guessed_or_presented_as_another_topic_body(case):
    fields=compact() if case=='compact34' else raw()
    if case in ('compact34','partial34','other-title34'):fields+=sections_for('family-particulars')[28:]
    if case.startswith('partial'):fields[5]='### 🛡 CLAN GAMES'
    if case=='custom':fields[3]='Custom text in a former decoration slot'
    if case.startswith('other-title'):fields[5]='## 🛡 Family War Rules'
    before=fields[:]
    assert layout_for('family-particulars',fields)=='ambiguous'
    with pytest.raises(ValueError,match='ambiguous'):logical_sections('family-particulars',fields)
    doc=manage_content.schema(manage_content.descriptor('gauntlet--family-particulars'),{'sections':fields,'media':{},'revision':2})
    assert doc['action_only'] and not doc.get('readonly') and not doc['preview_supported'] and doc['publish_endpoint'] is None
    raw_fields=[f for f in doc['fields'] if f['key'].startswith('sections.')]
    assert [f['value'] for f in raw_fields]==before
    assert all(f['label']==f'Raw saved field {i+1}' for i,f in enumerate(raw_fields))
    assert fields==before


def test_compact_editor_keys_are_editable_and_old_form_revision_is_rejected():
    fields=compact();loaded={'sections':fields[:],'media':{},'revision':3}
    item=manage_content.descriptor('gauntlet--family-particulars');doc=manage_content.schema(item,loaded)
    assert not doc.get('action_only') and not doc.get('readonly') and doc['preview_supported'] and doc['publish_endpoint']
    assert all(not f.get('readonly') for f in doc['fields'])
    values={f['key']:f['value'] for f in doc['fields']}
    with pytest.raises(web.HTTPConflict):manage_content.candidate(item,loaded,{'revision':3,'values':values})
    result=manage_content.candidate(item,loaded,{'revision':doc['revision'],'values':values})
    assert layout_for('family-particulars',result['sections'])=='standard'
    assert len(result['sections'])==34
    assert loaded['sections']==fields and len(loaded['sections'])==28
    values['sections.5']='Changed Friendly body'
    preview=manage_content.candidate(item,loaded,{'revision':doc['revision'],'values':values},preview_only=True)
    assert preview['sections'][5]=='Changed Friendly body' and loaded['sections']==fields


@pytest.mark.parametrize('transport',['web','native'])
def test_explicit_save_canonicalizes_once_and_history_retains_original_raw28(transport):
    async def check():
        from contextlib import asynccontextmanager
        from cwl_web import server_management
        mongo=db();fields=compact();guild=manage_content.GUILD_ID
        row={'_id':f'content:family-particulars:{guild}','sections':fields[:],'media':{},'revision':3}
        mongo.bot_config.rows[row['_id']]=copy.deepcopy(row)
        item=manage_content.descriptor('gauntlet--family-particulars')
        loaded=await manage_content.load(mongo,item)
        assert loaded['sections']==fields and len(loaded['sections'])==28
        token=manage_content.schema(item,loaded)['revision']
        values={'sections.5':'Changed Friendly body'}
        @asynccontextmanager
        async def database(_):yield mongo
        if transport=='web':
            request=NS(match_info={'item':item['id']},method='PATCH',path='/api/cwl/manage/content/'+item['id'],json=AsyncMock(return_value={'revision':token,'values':values}))
            with patch.object(server_management,'mongo',database),patch.object(server_management,'require_manage',AsyncMock(return_value={'user_id':'7'})):
                await manage_content.item_handler(request)
        else:
            edited=manage_content.candidate(item,loaded,{'revision':token,'values':values})
            assert await content._save(NS(user=NS(id=7)),dict(edited,document='family-particulars',guild_id=guild),mongo)
        stored=mongo.bot_config.rows[row['_id']]
        assert stored['revision']==4 and len(stored['sections'])==34
        assert layout_for('family-particulars',stored['sections'])=='standard'
        assert stored['sections'][:3]==fields[:3]
        for target,source in COMPACT_BODY_SLOTS.items():
            assert stored['sections'][target]==('Changed Friendly body' if target==5 else fields[source])
        for target,source in {4:3,7:5,10:7,11:8,14:10,17:12,20:14,23:16,26:18}.items():
            assert stored['sections'][target]==fields[source]
        history=[r for r in mongo.bot_config.rows.values() if r.get('kind')=='dashboard_history']
        assert len(history)==1 and history[0]['status']=='saved'
        assert history[0]['raw_before']['sections']==fields
        assert history[0]['raw_after']['sections']==stored['sections']
        fresh=await manage_content.load(mongo,item)
        assert fresh['sections']==stored['sections']
        before=copy.deepcopy(mongo.bot_config.rows)
        with pytest.raises(web.HTTPConflict):manage_content.candidate(item,fresh,{'revision':token,'values':values})
        assert not await content._save_untracked(NS(user=NS(id=7)),dict(loaded,document='family-particulars',guild_id=guild),mongo)
        assert mongo.bot_config.rows==before
        second=manage_content.candidate(item,fresh,{'revision':4,'values':{'sections.5':'Second Friendly edit'}})
        assert await content._save_untracked(NS(user=NS(id=7)),dict(second,document='family-particulars',guild_id=guild),mongo)
        twice=await manage_content.load(mongo,item)
        assert twice['sections'][5]=='Second Friendly edit' and layout_for('family-particulars',twice['sections'])=='standard'
    asyncio.run(check())


@pytest.mark.parametrize('fields',[raw(),compact()])
def test_pre272_native_modal_must_reopen_without_writes(fields):
    async def check():
        state={'document':'family-particulars','sections':fields,'user_id':7,'guild_id':20,'selected_fields':[[15,'Prep Day','full']]}
        ctx=NS(user=NS(id=7),interaction=NS(guild_id=20))
        with patch.object(content,'get_state',AsyncMock(return_value=state)),patch.object(content,'can_edit',return_value=True):
            _,problem=await content.load(ctx,NS(), 'old')
        assert 'Reopen' in problem and 'layout_version' not in state
    asyncio.run(check())


def test_readonly_back_action_and_raw_pages_keep_all_text_under_budget():
    fields=compact()+sections_for('family-particulars')[28:]
    state={'_id':'state','document':'family-particulars','sections':fields,'media':{},'revision':3,'layout_version':LAYOUT_VERSION}
    controls=content.component_custom_ids(content.panel(state)) if hasattr(content,'component_custom_ids') else None
    # Walk SDK children directly, including action rows.
    def ids(nodes):
        return [value for node in nodes for value in ([getattr(node,'custom_id',None)] + ids(getattr(node,'components',()) or ())) if value]
    assert 'content_back_root:state' in ids(content.panel(state))
    text='Raw saved field 25\n'+'x'*8000
    pages=[]
    for page in range(3):
        components=content.raw_view_panel(dict(state,raw_view_text=text,raw_view_page=page))
        values=[n.content for n in content.text_nodes(components)]
        assert sum(map(len,values))<4000
        pages.append(values[-1])
    assert ''.join(pages)==text


@pytest.mark.parametrize('transport',['web','native'])
def test_compact_update_uses_correct_bodies_without_template_save(transport):
    async def check():
        from contextlib import asynccontextmanager
        from cwl_web import manage_delivery, server_management
        from test_cwl_web_manage_delivery import fixture
        from test_content_dashboard_runtime import _as_discord_models
        row,mongo,bot,ctx=fixture()
        fields=compact();guild=manage_delivery.GUILD_ID;key='family-particulars'
        old_models=_as_discord_models(old.build_familyparticulars(raw()))
        saved={'_id':f'content:{key}:{guild}','sections':fields[:],'media':{},'revision':3}
        mongo.bot_config.documents[saved['_id']]=copy.deepcopy(saved)
        target={'channel_id':456,'message_id':789}
        mongo.bot_config.documents[f'content_destination:{guild}:{key}']={'_id':f'content_destination:{guild}:{key}','guild_id':guild,'document':key,'channel_id':456}
        mongo.bot_config.documents[f'content_published:{guild}:{key}']={'_id':f'content_published:{guild}:{key}','guild_id':guild,'document':key,**target}
        bot.rest.fetch_message=AsyncMock(return_value=NS(author=NS(id=555),components=old_models,attachments=[]))
        if transport=='web':
            @asynccontextmanager
            async def database(_):yield mongo
            async def discord(*_):return {'components':old_models}
            with patch.object(server_management,'mongo',database),patch.object(server_management,'discord',discord):
                reviewed=await manage_delivery.review(NS(),key)
            row.update(action='update',document=key,values=reviewed)
            await manage_delivery.publish(bot,mongo,row,ctx)
        else:
            state={'document':key,'sections':fields[:],'media':{},'revision':3,'guild_id':guild,'destination_channel_id':456,
                   'target':dict(target,original=[n.content for n in content.text_nodes(old_models)],original_media=content.media_snapshot(old_models))}
            result=await content.publish_state(ctx,state,mongo,bot,return_outcome=True)
            assert result['ok'],result
        bot.rest.edit_message.assert_awaited_once();bot.rest.create_message.assert_not_awaited()
        texts='\n'.join(n.content for n in content.text_nodes(bot.rest.edit_message.await_args.kwargs['components']))
        for logical,physical in COMPACT_BODY_SLOTS.items():assert fields[physical] in texts
        assert '**Friendly Challenges**\n'+fields[4] in texts
        assert '**Clan Games**\n'+fields[6] in texts
        assert '**War Status**\n'+fields[9] in texts
        assert mongo.bot_config.documents[saved['_id']]==saved
        assert bot.rest.edit_message.await_args.kwargs['user_mentions'] is False
    asyncio.run(check())


def test_ambiguous_stale_publish_page_cannot_queue_or_touch_discord():
    async def check():
        from contextlib import asynccontextmanager
        from cwl_web import manage_delivery, server_management
        mongo=db();fields=compact()+sections_for('family-particulars')[28:]
        key=f'content:family-particulars:{manage_delivery.GUILD_ID}'
        mongo.bot_config.rows[key]={'_id':key,'sections':fields[:],'revision':3,'media':{}}
        before=copy.deepcopy(mongo.bot_config.rows)
        @asynccontextmanager
        async def database(_):yield mongo
        request=NS(match_info={'document':'family-particulars','action':'update'},json=AsyncMock(return_value={'revision':'stale270'}))
        with patch.object(server_management,'mongo',database),patch.object(server_management,'require_manage',AsyncMock()),patch.object(server_management,'discord',AsyncMock()) as discord,patch.object(server_management,'queue_action',AsyncMock()) as queue:
            with pytest.raises(web.HTTPBadRequest) as refused:
                await manage_delivery.queue(request)
            assert 'ambiguous' in refused.value.text
            queue.assert_not_awaited();discord.assert_not_awaited();request.json.assert_not_awaited()
        assert mongo.bot_config.rows==before
    asyncio.run(check())


def test_ambiguous_artwork_upload_is_denied_before_external_upload():
    async def check():
        from contextlib import asynccontextmanager
        from cwl_web import server_management
        mongo=db();fields=compact()+sections_for('family-particulars')[28:];key=f'content:family-particulars:{manage_content.GUILD_ID}'
        mongo.bot_config.rows[key]={'_id':key,'sections':fields[:],'revision':3,'media':{}}
        before=copy.deepcopy(mongo.bot_config.rows)
        @asynccontextmanager
        async def database(_):yield mongo
        request=NS(match_info={'item':'gauntlet--family-particulars','slot':'media.welcome'},query={'revision':'272:compact:3'})
        with patch.object(server_management,'mongo',database),patch.object(server_management,'require_manage',AsyncMock()),patch('utils.media_store.MediaStore.from_env') as media:
            with pytest.raises(web.HTTPBadRequest) as refused:
                await manage_content.upload(request)
            assert 'ambiguous' in refused.value.text
            media.assert_not_called()
        assert mongo.bot_config.rows==before
    asyncio.run(check())


def test_native_compact_modal_edits_correct_logical_body_before_explicit_save():
    async def check():
        fields=compact();state={'_id':'old','document':'family-particulars','sections':fields[:],'revision':3,'media':{},'layout_version':LAYOUT_VERSION}
        ctx=NS(interaction=NS(values=['1']),respond_with_modal=AsyncMock())
        async def draft(_mongo,value):return dict(value,_id='modal')
        with patch.object(content,'load',AsyncMock(return_value=(state,None))),patch.object(content,'new_draft',AsyncMock(side_effect=draft)) as created:
            await content.choose_block.__wrapped__._func(ctx=ctx,action_id='old',mongo=NS())
        opened=created.await_args.args[1]
        assert len(opened['sections'])==34 and layout_for('family-particulars',opened['sections'])=='standard'
        modal=ctx.respond_with_modal.await_args.kwargs['components']
        assert modal[1].components[0].value==fields[4]
        assert modal[2].components[0].value==fields[6]
        assert opened['selected_fields'][1][:2]==[5,'Friendly Challenges']
        assert state['sections']==fields and len(state['sections'])==28
    asyncio.run(check())


def test_compact_copy_from_discord_is_only_a_canonical_edit_draft():
    from utils.gauntlet_content import merge_public
    fields=compact();before=fields[:]
    imported=sections_for('family-particulars');imported[5]='Explicit imported Friendly body'
    merged=merge_public('family-particulars',fields,imported)
    assert layout_for('family-particulars',merged)=='standard' and merged[5]==imported[5]
    assert fields==before

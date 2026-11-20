import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
import hikari
from cwl_web import manage_delivery as delivery
from cwl_web.manage_content import fingerprint
from test_cwl_dashboard_integration import MemoryCollection
from extensions.commands import content


def fixture():
    sections=['Test']; media={}
    row={'_id':'request1','action':'send','user_id':'123','values':{'document':'about-us','template_revision':1,'template':fingerprint({'sections':sections,'media':media}),'destination':456,'target':None,'post':None,'rendered_snapshot':{'text':[],'media':[]}}}
    collection = MemoryCollection()
    async def insert_one(row):
        from pymongo.errors import DuplicateKeyError
        if row['_id'] in collection.documents:
            raise DuplicateKeyError('duplicate')
        collection.documents[row['_id']] = row
    collection.insert_one = insert_one
    db=NS(bot_config=collection)
    bot=NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=delivery.GUILD_ID,type=hikari.ChannelType.GUILD_TEXT)),create_message=AsyncMock(return_value=NS(id=789)),edit_message=AsyncMock()))
    ctx=NS(interaction=NS(application_id=555))
    return row,db,bot,ctx


def test_send_claim_prevents_replayed_dispatch_and_native_gates_run():
    async def scenario():
        row,db,bot,ctx=fixture()
        with patch.object(content,'template_for',AsyncMock(return_value=(['Test'],{},1))), patch.object(content,'destination_for',AsyncMock(return_value=456)), patch.object(content,'published_for',AsyncMock(return_value=None)), patch.object(content,'destination_permissions',AsyncMock(return_value=hikari.Permissions.ADMINISTRATOR)), patch.object(content,'_ready_for_destination',AsyncMock(return_value=(True,None))) as ready, patch.object(content,'render',AsyncMock(return_value=[])), patch.object(content,'remember_published',AsyncMock()):
            result=await delivery.publish(bot,db,row,ctx)
            assert result['url'].endswith('/456/789')
            ready.assert_awaited()
            with pytest.raises(ValueError,match='already attempted'):
                await delivery.publish(bot,db,row,ctx)
            assert bot.rest.create_message.await_count==1
    asyncio.run(scenario())


def test_changed_template_cannot_send():
    async def scenario():
        row,db,bot,ctx=fixture()
        with patch.object(content,'template_for',AsyncMock(return_value=(['Changed'],{},2))):
            with pytest.raises(ValueError,match='saved message changed'):
                await delivery.publish(bot,db,row,ctx)
            bot.rest.create_message.assert_not_awaited()
    asyncio.run(scenario())


def test_update_rejects_changed_live_post_under_native_lease():
    async def scenario():
        row,db,bot,ctx=fixture()
        target={'channel_id':456,'message_id':789}
        row['action']='update';row['values'].update(target=target,post={'text':['old'],'media':[]})
        bot.rest.fetch_message=AsyncMock(return_value=NS(author=NS(id=555),components=[{'type':17,'components':[{'type':10,'content':'new'}]}]))
        with patch.object(content,'template_for',AsyncMock(return_value=(['Test'],{},1))), patch.object(content,'destination_for',AsyncMock(return_value=456)), patch.object(content,'published_for',AsyncMock(return_value=target)), patch.object(content,'loaded_published_target',AsyncMock(return_value=target)), patch.object(content,'component_shape',return_value='same'), patch.object(content,'acknowledgement_id',return_value='ack'), patch.object(content,'baseline',AsyncMock(return_value=[])):
            with pytest.raises(ValueError,match='Discord post changed'):
                await delivery.publish(bot,db,row,ctx)
            bot.rest.edit_message.assert_not_awaited()
            assert not await db.bot_config.find_one({'_id':'content_publish:456:789'})
    asyncio.run(scenario())


def test_publish_page_names_new_and_existing_channels_separately():
    async def scenario():
        import json
        from cwl_web import server_management as shared
        data={'sections':['Saved']*len(content.BLOCK_LABELS['about-us']), 'destination':456, 'target':{'channel_id':789,'message_id':123}}
        async def lookup(request,method,path):
            return {'guild_id':str(delivery.GUILD_ID),'name':'new-posts' if path.endswith('/456') else 'existing-posts'}
        request=NS(match_info={'document':'about-us'})
        with patch.object(shared,'require_manage',AsyncMock()),patch.object(shared,'discord',lookup),patch.object(delivery,'review',AsyncMock(return_value=data)):
            result=json.loads((await delivery.page(request)).text)
            assert result['posting_channel']=='#new-posts'
            assert result['existing_channel']=='#existing-posts'
            assert result['destination_editor'].endswith('destination--about-us')
            assert {a['id'] for a in result['actions']}=={'send','update'}
    asyncio.run(scenario())


def test_stale_publish_review_never_queues_delivery():
    async def scenario():
        from aiohttp import web
        from cwl_web import server_management as shared
        request=NS(match_info={'document':'about-us','action':'send'},json=AsyncMock(return_value={'revision':'old'}))
        with patch.object(shared,'require_manage',AsyncMock()),patch.object(delivery,'review',AsyncMock(return_value={'destination':456})),patch.object(shared,'queue_action',AsyncMock()) as queue:
            with pytest.raises(web.HTTPConflict):await delivery.queue(request)
            queue.assert_not_awaited()
    asyncio.run(scenario())


def test_family_rules_forged_publish_is_rejected_before_database_or_discord():
    async def scenario():
        row,db,bot,ctx=fixture()
        row['values']['document']='family-rules'
        with pytest.raises(ValueError,match='public onboarding'):
            await delivery.publish(bot,db,row,ctx)
        assert not db.bot_config.documents
        bot.rest.create_message.assert_not_awaited();bot.rest.edit_message.assert_not_awaited()
    asyncio.run(scenario())


def test_wu_faq_update_uses_context_and_needs_no_acknowledgement_button():
    async def scenario():
        row,db,bot,ctx=fixture();row['action']='update'
        row['values']['document']='wu-faq'
        sections=['## Questions','Body'];row['values']['template']=fingerprint({'sections':sections,'media':{}})
        target={'channel_id':456,'message_id':789}
        components=await content.baseline(content.DOCUMENTS['wu-faq'])
        row['values'].update(target=target,post=delivery.snapshot(components),rendered_snapshot=delivery.snapshot(components))
        message=NS(author=NS(id=555),components=components,attachments=[])
        bot.rest.fetch_message=AsyncMock(return_value=message)
        with patch.object(content,'template_for',AsyncMock(return_value=(sections,{},1))), patch.object(content,'destination_for',AsyncMock(return_value=456)), patch.object(content,'published_for',AsyncMock(return_value=target)), patch.object(content,'loaded_published_target',AsyncMock(return_value=target)), patch.object(content,'render',AsyncMock(return_value=components)) as renderer:
            result=await delivery.publish(bot,db,row,ctx)
            assert result['message']=='Existing post updated.'
            assert renderer.await_args.kwargs['mongo'] is db
            assert renderer.await_args.kwargs['guild_id']==delivery.GUILD_ID
            assert renderer.await_args.kwargs['action_id']=='public'
            bot.rest.create_message.assert_not_awaited();bot.rest.edit_message.assert_awaited_once()
            assert all(bot.rest.edit_message.await_args.kwargs[key] is False for key in content.NO_MENTIONS)
    asyncio.run(scenario())


def _derived_db():
    from test_content_grouped_publish import _info_database
    db=_info_database()
    key='content:family-rules:'+str(delivery.GUILD_ID)
    row=db.bot_config.documents.pop('content:family-rules:20');row['_id']=key;db.bot_config.documents[key]=row
    return db


def test_reviewed_composition_rejects_changed_rules_and_registry_but_allows_exact_payload():
    async def scenario():
        from utils.info_channel_content import about_us_defaults
        db=_derived_db();document=content.DOCUMENTS['about-us'];sections=about_us_defaults()
        rendered=await content.render(document,sections,mongo=db,guild_id=delivery.GUILD_ID)
        values={'rendered_snapshot':delivery.snapshot(rendered)}
        checked=await delivery.reviewed_render(document,sections,{},db,values,action_id='test')
        assert delivery.snapshot(checked)==values['rendered_snapshot']
        rule=db.bot_config.documents['content:family-rules:'+str(delivery.GUILD_ID)]
        old=list(rule['sections']);rule['sections']=[old[0],old[1]+' Changed']
        with pytest.raises(ValueError,match='Reload and review'):
            await delivery.reviewed_render(document,sections,{},db,values,action_id='test')
        rule['sections']=old
        db.clans.rows[0]['name']+='X'
        with pytest.raises(ValueError,match='clan registry changed'):
            await delivery.reviewed_render(document,sections,{},db,values,action_id='test')
        with pytest.raises(ValueError,match='Reload and review'):
            await delivery.reviewed_render(document,sections,{},db,{},action_id='old-queue')
    asyncio.run(scenario())


def test_send_rechecks_dependencies_after_durable_claim_and_never_sends_changed_payload():
    async def scenario():
        row,db,bot,ctx=fixture()
        before=[hikari.impl.TextDisplayComponentBuilder(content='Reviewed')]
        changed=[hikari.impl.TextDisplayComponentBuilder(content='Changed later')]
        row['values']['rendered_snapshot']=delivery.snapshot(before)
        with patch.object(content,'template_for',AsyncMock(return_value=(['Test'],{},1))), patch.object(content,'destination_for',AsyncMock(return_value=456)), patch.object(content,'published_for',AsyncMock(return_value=None)), patch.object(content,'destination_permissions',AsyncMock(return_value=hikari.Permissions.ADMINISTRATOR)), patch.object(content,'_ready_for_destination',AsyncMock(return_value=(True,None))), patch.object(content,'render',AsyncMock(side_effect=[before,changed])):
            with pytest.raises(ValueError,match='Reload and review'):
                await delivery.publish(bot,db,row,ctx)
        bot.rest.create_message.assert_not_awaited();bot.rest.edit_message.assert_not_awaited()
        assert 'content_send:request1' in db.bot_config.documents
    asyncio.run(scenario())


def test_queue_review_fingerprint_includes_shared_rules_and_actual_preview():
    async def scenario():
        from contextlib import asynccontextmanager
        from cwl_web import server_management
        db=_derived_db()
        @asynccontextmanager
        async def database(_request):yield db
        with patch.object(server_management,'mongo',database):
            first=await delivery.review(NS(),'wu-faq')
            assert first['rendered_preview'] and first['rendered_snapshot']['text']
            row=db.bot_config.documents['content:family-rules:'+str(delivery.GUILD_ID)]
            row['sections']=[row['sections'][0],row['sections'][1]+' Changed']
            row['revision']=2
            second=await delivery.review(NS(),'wu-faq')
        assert first['template_revision']==second['template_revision']
        assert first['template']==second['template']
        assert fingerprint(first)!=fingerprint(second)
    asyncio.run(scenario())

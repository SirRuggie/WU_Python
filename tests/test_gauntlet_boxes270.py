"""Lossless legacy mapping and actual saved-template Update regressions."""
import asyncio
import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
import hikari
from cwl_web import manage_content, manage_delivery, server_management
from extensions.commands import content
from test_cwl_web_manage_content import db
from test_cwl_web_manage_delivery import fixture
from test_content_dashboard_runtime import _as_discord_models
from test_info_channel_content import Clans
from utils.gauntlet_content import BOXES, LEGACY_LENGTHS, LENGTHS, sections_for, validate_sections, visible_indexes
from utils.constants import WU_GOLD, WU_GREEN, WU_RED


def run(value):
    return asyncio.run(value)


@pytest.mark.parametrize('key', ['about-us','strike-system','family-particulars'])
def test_legacy_prefix_is_lossless_through_explicit_save_and_reopen(key):
    async def check():
        mongo = db()
        legacy = [f'Legacy {key} field {index}\nexact spaces  ' for index in range(LEGACY_LENGTHS[key])]
        if key == 'strike-system':
            legacy[1] = 'Custom how.\n### ✅ Remove your strikes\nCustom removal.'
        original = copy.deepcopy(legacy)
        row = {'_id':f'content:{key}:20','sections':legacy,'media':{},'revision':4}
        mongo.bot_config.rows[row['_id']] = copy.deepcopy(row)
        fields, _, revision = await content.template_for(mongo, content.DOCUMENTS[key],20)
        assert fields[:len(legacy)] == original and revision == 4
        assert mongo.bot_config.rows[row['_id']] == row
        changed = fields[:]
        # Edit an appended heading: no historical prefix field is overwritten.
        changed[LEGACY_LENGTHS[key]] += ' Staff edit'
        assert await content._save_untracked(NS(user=NS(id=7)),dict(document=key,guild_id=20,revision=4,sections=changed,media={}),mongo)
        loaded, _, revision = await content.template_for(mongo,content.DOCUMENTS[key],20)
        assert loaded == changed and loaded[:len(legacy)] == original and revision == 5
        assert sections_for(key,loaded) == loaded  # Never remap raw over saved canonical fields.
        assert set(visible_indexes(key)).issubset(range(len(loaded)))
    run(check())


@pytest.mark.parametrize('key', ['about-us','strike-system','family-particulars'])
def test_truncated_intermediate_layout_fails_closed(key):
    legacy = sections_for(key)[:LEGACY_LENGTHS[key]]
    for length in range(LEGACY_LENGTHS[key]+1,LENGTHS[key]):
        with pytest.raises(ValueError,match='incomplete field layout'):
            sections_for(key,legacy+['partial']*(length-len(legacy)))


@pytest.mark.parametrize('body', ['Custom policy without a removal heading.',
    'Text mentioning ### ✅ Remove your strikes inside a sentence.',
    'How\n### ✅ Remove your strikes\nFirst\n### ✅ Remove your strikes\nSecond'])
def test_ambiguous_strike_text_remains_visible_and_requires_explicit_repair(body):
    async def check():
        mongo=db();raw=sections_for('strike-system')[:12];raw[1]=body
        mongo.bot_config.rows['content:strike-system:20']={'_id':'content:strike-system:20','sections':raw[:],'revision':8}
        fields,_,revision=await content.template_for(mongo,content.DOCUMENTS['strike-system'],20)
        assert fields[1] == fields[12] == body and fields[13] == '' and revision == 8
        with pytest.raises(ValueError,match='Review the saved How Strikes Work'):
            validate_sections('strike-system',fields)
        fields[13]='Staff explicitly supplied removal policy.'
        assert await content._save_untracked(NS(user=NS(id=7)),dict(document='strike-system',guild_id=20,revision=8,sections=fields,media={}),mongo)
        fresh,_,_=await content.template_for(mongo,content.DOCUMENTS['strike-system'],20)
        assert fresh[1] == body and fresh[13] == fields[13]
    run(check())


def test_recognized_strike_split_keeps_original_marker_and_whitespace_in_storage():
    raw=sections_for('strike-system')[:12]
    raw[1]='Before\n\n### ✅ Remove your strikes\nAfter\n  '
    fields=sections_for('strike-system',raw)
    assert fields[1] == raw[1] and fields[12] == 'Before' and fields[13] == 'After\n  '


def test_native_and_web_screens_follow_boxes_and_particulars_cwl_mapping_is_correct():
    async def check():
        for key in BOXES:
            item=manage_content.descriptor('gauntlet--'+key)
            mongo=db();loaded=await manage_content.load(mongo,item)
            doc=await manage_content.editor_document(item,loaded,mongo=mongo)
            ordered=list(dict.fromkeys(field.get('group') for field in doc['fields']))
            assert ordered == [box for box,_ in BOXES[key]] + (['Images'] if content.MEDIA_SLOTS[key] else [])
            assert [name for name,_ in content.editable_groups(content.DOCUMENTS[key],loaded['sections'])] == [box for box,_ in BOXES[key]]
            assert all(len(fields)<=5 for _,fields in content.editable_groups(content.DOCUMENTS[key],loaded['sections']))
        item=manage_content.descriptor('gauntlet--family-particulars');loaded=await manage_content.load(db(),item)
        schema=manage_content.schema(item,loaded)
        assert next(f for f in schema['fields'] if f['group']=='Clan War League' and f['label']=='Overview')['key']=='sections.21'
        changed=manage_content.candidate(item,loaded,{'revision':loaded['revision'],'values':{'sections.21':'New CWL text'}})
        assert changed['sections'][21]=='New CWL text'
        assert changed['sections'][15]==loaded['sections'][15]  # Former schema mislabeled Prep Day as CWL.
        fixed={1,2,3,6,9,13,16,19,22,25}
        assert all(changed['sections'][index]==loaded['sections'][index] for index in fixed)
    run(check())


@pytest.mark.parametrize('key,accents,media_count', [
    ('about-us',[WU_GOLD,WU_GREEN,WU_RED,WU_GOLD],1),
    ('strike-system',[WU_RED,WU_GREEN,WU_RED,None,WU_GOLD],3),
    ('family-particulars',[WU_GOLD,WU_GREEN,WU_GREEN,WU_GREEN,WU_GOLD],2),
    ('wu-faq',[WU_GOLD,WU_GREEN,WU_RED,None],0),
])
def test_public_boxes_components_media_and_acknowledgements(key,accents,media_count):
    async def check():
        mongo=db();document=content.DOCUMENTS[key]
        fields=sections_for(key)
        before=copy.deepcopy(fields)
        rendered=await content.render(document,fields,mongo=mongo,guild_id=20,action_id='kept')
        assert [box.accent_color for box in rendered if int(box.type)==17]==accents
        assert content.component_count(rendered)<=40
        assert all(len(getattr(box,'components',()))<=10 for box in rendered if int(box.type)==17)
        assert len(content.media_snapshot(rendered))==media_count
        assert fields==before
        assert content.acknowledgement_id(rendered,document)==('kept' if document.acknowledgement else None)
        text='\n'.join(node.content for node in content.text_nodes(rendered))
        assert 'ᨖ' not in text and '<:warriorcat:' not in text
        assert sum(len(node.content) for node in content.text_nodes(rendered))<=4000
        if key=='family-particulars':
            assert 'GOLDEN RULE' not in text and 'READ THIS FIRST' not in text
        if key=='wu-faq':
            assert '**Tactical**\nserious wars, 3-star attacks' in text
            assert fields[5]=='**🎯 Tactical:** serious wars, 3-star attacks'
    run(check())


def legacy_post(key, fields):
    """Concrete pre-270 layouts from the base builders, with live-shaped saved text.

    About has 12 editable + 2 shared-rule text nodes. Strikes has 12;
    Particulars has all 28 including its eight decorative nodes. These are
    actual nested Hikari payloads, not mocked supported_post_shape results.
    """
    from utils.info_channel_defaults import FAMILY_RULES
    Text=hikari.impl.TextDisplayComponentBuilder
    Container=hikari.impl.ContainerComponentBuilder
    Media=hikari.impl.MediaGalleryComponentBuilder
    Item=hikari.impl.MediaGalleryItemBuilder
    def image(path):return Media(items=[Item(media=path)])
    def text(index):return Text(content=fields[index])
    def separator():return hikari.impl.SeparatorComponentBuilder(divider=True)
    def box(children):return Container(accent_color=WU_GOLD,components=children)
    row=hikari.impl.MessageActionRowBuilder()
    row.add_interactive_button(hikari.ButtonStyle.SUCCESS,content.DOCUMENTS[key].acknowledgement+':existing',label='I understand - Continue')
    if key=='about-us':
        return [image('assets/branding/banners/Warriors_United.gif'),
            box([text(0),separator(),text(1),separator(),text(2),text(3)]),box([text(4),text(5)]),
            box([text(6),text(7),separator(),text(8),text(9)]),
            box([Text(content=value) for value in FAMILY_RULES]),box([text(10),text(11),row])]
    if key=='strike-system':
        return [image('assets/recruit/strikes/WU_Strikes.gif'),
            box([text(0),separator(),text(1)]),box([text(2),separator(),text(3)]),
            box([text(4),separator(),text(5),image('assets/recruit/strikes/WU_Main_Strikes.jpg')]),
            box([text(6),separator(),text(7),image('assets/recruit/strikes/WU_FWA_Strikes.jpg')]),
            box([text(8),separator(),text(9)]),box([text(10),separator(),text(11),row])]
    return [image('assets/recruit/static/WU_FamilyParticulars.gif'),
        box([text(0),separator(),*[text(i) for i in range(1,10)]]),
        box([text(10),separator(),*[text(i) for i in range(11,20)]]),
        box([text(20),separator(),*[text(i) for i in range(21,26)],image('assets/branding/banners/warriors_united_.gif')]),
        box([text(26),separator(),text(27),row])]


@pytest.mark.parametrize('key,index', [('about-us',1),('strike-system',12),('family-particulars',21)])
def test_web_saved_current_sections_are_the_exact_queued_update_payload(key,index):
    async def check():
        row,mongo,bot,ctx=fixture();mongo.clans=Clans()
        document=content.DOCUMENTS[key];guild=manage_delivery.GUILD_ID
        saved=sections_for(key)[:LEGACY_LENGTHS[key]]
        old_models=_as_discord_models(legacy_post(key,saved))
        assert await content.supported_post_shape(document,old_models)
        media=dict(zip((slot for slot,_ in content.MEDIA_SLOTS[key]),content.media_snapshot(old_models),strict=True))
        target={'channel_id':456,'message_id':789}
        mongo.bot_config.documents[f'content:{key}:{guild}']={'_id':f'content:{key}:{guild}','sections':saved[:],'media':media,'revision':1}
        mongo.bot_config.documents[f'content_destination:{guild}:{key}']={'_id':f'content_destination:{guild}:{key}','guild_id':guild,'document':key,'channel_id':456}
        mongo.bot_config.documents[f'content_published:{guild}:{key}']={'_id':f'content_published:{guild}:{key}','guild_id':guild,'document':key,**target}
        item=manage_content.descriptor('gauntlet--'+key)
        loaded=await manage_content.load(mongo,item)
        marker=f'CURRENT SAVED {key} policy'
        updated=manage_content.candidate(item,loaded,{'revision':1,'values':{f'sections.{index}':marker}})
        assert await content._save_untracked(NS(user=NS(id=123)),dict(updated,document=key,guild_id=guild),mongo)
        stored=mongo.bot_config.documents[f'content:{key}:{guild}']['sections']
        assert all(stored[i]==saved[i] for i in range(len(saved)) if i not in visible_indexes(key))
        @asynccontextmanager
        async def database(_request):yield mongo
        async def discord(_request,method,path):
            assert method=='GET';return {'components':old_models}
        with patch.object(server_management,'mongo',database),patch.object(server_management,'discord',discord):
            reviewed=await manage_delivery.review(NS(),key)
        row.update(action='update',values=reviewed)
        attachments=[NS(id=content.discord_attachment_id(url),url=url) for url in media.values() if content.discord_attachment_id(url)]
        bot.rest.fetch_message=AsyncMock(return_value=NS(author=NS(id=555),components=old_models,attachments=attachments))
        result=await manage_delivery.publish(bot,mongo,row,ctx)
        bot.rest.edit_message.assert_awaited_once();bot.rest.create_message.assert_not_awaited()
        payload=bot.rest.edit_message.await_args.kwargs['components']
        assert marker in '\n'.join(node.content for node in content.text_nodes(payload))
        assert content.acknowledgement_id(payload,document)=='existing'
        assert bot.rest.edit_message.await_args.kwargs['attachments']==attachments
        assert result['message']==f'{document.label}: Existing post updated.'
        assert result['url']==f'https://discord.com/channels/{guild}/456/789'
        assert all(bot.rest.edit_message.await_args.kwargs[flag] is False for flag in content.NO_MENTIONS)
    run(check())


@pytest.mark.parametrize('key',['about-us','strike-system','family-particulars'])
def test_malformed_legacy_post_is_rejected_before_update(key):
    async def check():
        models=list(_as_discord_models(legacy_post(key,sections_for(key))))
        original=models[1]
        models[1]=hikari.ContainerComponent(type=original.type,id=original.id,accent_color=original.accent_color,
            is_spoiler=original.is_spoiler,components=original.components[:-1])
        assert not await content.supported_post_shape(content.DOCUMENTS[key],models)
    run(check())


def test_native_five_field_box_submit_preserves_other_boxes(monkeypatch):
    async def check():
        fields=sections_for('wu-faq')
        selected=content.editable_groups(content.DOCUMENTS['wu-faq'],fields)[1][1]
        state={'_id':'faq-box','user_id':10,'guild_id':20,'document':'wu-faq','sections':fields,
               'revision':0,'selected_fields':[list(field) for field in selected]}
        captured=[]
        async def draft(_db,value):captured.append(value);return dict(value,_id='next')
        monkeypatch.setattr(content,'load',AsyncMock(return_value=(state,None)))
        monkeypatch.setattr(content,'new_draft',draft)
        values=[f'Explicit clan field {i}' for i in range(5)]
        interaction=NS(message=NS(id=1),components=tuple((NS(custom_id=f'content_{i}',value=value),) for i,value in enumerate(values)),
                       create_initial_response=AsyncMock(),edit_initial_response=AsyncMock())
        ctx=NS(interaction=interaction,defer=AsyncMock(),user=NS(id=10))
        await content.submit_block.__wrapped__._func(ctx=ctx,action_id='faq-box',mongo=NS())
        assert captured and captured[-1]['sections'][4:9]==values
        assert captured[-1]['sections'][:4]==fields[:4]
        interaction.edit_initial_response.assert_awaited_once()
    run(check())


def test_apply_default_changes_only_unsaved_default_text():
    from extensions.commands.tickets import setup
    default=[node.content for node in content.text_nodes(setup.create_public_ticket_embed())]
    assert default[1]=='Begin your Rite of Passage. Select the path you want: Main or FWA.\nA Recruiter replies in your ticket. Open only one ticket.'
    saved=['Custom heading','Exact saved body.  ']
    assert [node.content for node in content.text_nodes(setup.create_public_ticket_embed(saved))]==saved


def test_about_legacy_key_expands_for_native_and_web_then_saves_new_key_only():
    async def check():
        mongo=db();guild=manage_content.GUILD_ID
        raw=sections_for('about-us')[:12]
        raw[1]='Exact legacy-only overview.  '
        row={'_id':f'recruit_aboutus:{guild}','sections':raw[:],'revision':19}
        mongo.bot_config.rows[row['_id']]=copy.deepcopy(row)
        native,_,revision=await content.template_for(mongo,content.DOCUMENTS['about-us'],guild)
        assert native[:12]==raw and len(native)==16 and revision==0
        item=manage_content.descriptor('gauntlet--about-us')
        loaded=await manage_content.load(mongo,item)
        doc=await manage_content.editor_document(item,loaded,mongo=mongo)
        assert any(field['key']=='sections.15' for field in doc['fields'])
        assert loaded['sections']==native and mongo.bot_config.rows=={row['_id']:row}
        assert await content._save_untracked(NS(user=NS(id=123)),dict(loaded,document='about-us',guild_id=guild),mongo)
        assert mongo.bot_config.rows[row['_id']]==row
        assert mongo.bot_config.rows[f'content:about-us:{guild}']['sections']==native
        assert mongo.bot_config.rows[f'content:about-us:{guild}']['revision']==1
    run(check())


def test_strike_slash_entry_never_posts_defaults_for_ambiguous_saved_policy(monkeypatch):
    async def check():
        from extensions.commands.setup import recruit_strikesystem as strikes
        mongo=db();raw=sections_for('strike-system')[:12];raw[1]='Custom policy without a removal heading.'
        mongo.bot_config.rows['content:strike-system:20']={'_id':'content:strike-system:20','sections':raw[:],'revision':6}
        monkeypatch.setattr(strikes,'require_manage_server',AsyncMock(return_value=True))
        monkeypatch.setattr(strikes,'require_ready',AsyncMock(return_value=True))
        ctx=NS(guild_id=20,channel_id=30,defer=AsyncMock(),respond=AsyncMock())
        rest=NS(create_message=AsyncMock())
        await strikes.RecruitStrikeSystem().invoke(ctx,bot=NS(rest=rest),mongo=mongo)
        rest.create_message.assert_not_awaited()
        assert 'Review the saved How Strikes Work' in ctx.respond.await_args.args[0]
        assert mongo.bot_config.rows['content:strike-system:20']['sections']==raw
    run(check())

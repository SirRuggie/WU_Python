"""270 public render, legacy editor and no-write preview contracts."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import hikari
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from cwl_web import manage_content as web_content
from extensions.commands import content
from test_content_dashboard_runtime import _as_discord_models
from test_cwl_web_manage_content import db
from test_info_channel_content import Clans, registry_rows
from utils.constants import WU_GOLD, WU_GREEN, WU_RED
from utils.info_channel_content import about_us_defaults, wu_faq_sections
from utils.info_channel_defaults import FAMILY_RULES, WU_FAQ_NEW_FIELDS, WU_FAQ_QUESTIONS


def run(value):
    return asyncio.run(value)


def test_approved_questions_and_seven_new_defaults_are_exact():
    approved = json.loads((Path(__file__).parent / 'fixtures/wu_faq270_copy.json').read_text())
    assert list(WU_FAQ_QUESTIONS) == approved['questions']
    assert list(WU_FAQ_NEW_FIELDS) == [
        '## 🛡️ Warriors United',
        'An adult, English-speaking Clash of Clans family. Members play from all over the world. Banter is welcome.\n**Want to join?** Go to <#1553107113062965279>.',
        '## 🏰 Our Clans', '**🎯 Tactical:** serious wars, 3-star attacks',
        '**🎉 Flexible Fun:** relaxed wars, no heroes needed',
        '**💰 FWA:** farm wars, easy loot', '🏆 CWL every month, for every member.',
    ]


def test_four_containers_use_shared_single_registry_read_and_project_only_editable_fields():
    async def check():
        mongo = db()
        rows = registry_rows()
        rows[0]['name'] = 'A **bold** [link]'
        rows += [{'name': 'Excluded', 'tag': '#PPPPPPP', 'type': 'CWL'},
                 {'name': 'Archived', 'tag': '#PYYYYYY', 'type': 'FWA', 'archived': True}]
        mongo.clans = Clans(list(reversed(rows)))
        before = copy.deepcopy(rows)
        document = content.DOCUMENTS['wu-faq']
        rendered = await content.render(document, wu_faq_sections(), mongo=mongo, guild_id=20)
        assert [box.accent_color for box in rendered] == [WU_GOLD, WU_GREEN, WU_RED, None]
        texts = [node.content for node in content.text_nodes(rendered)]
        assert len(texts) == 11
        assert texts[0:2] == list(WU_FAQ_NEW_FIELDS[:2])
        assert texts[7:9] == list(FAMILY_RULES)
        assert texts[9:] == list(WU_FAQ_QUESTIONS)
        assert r'**A \*\*bold\*\* \[link\]**' in texts[3]
        assert 'Excluded' not in ''.join(texts) and 'Archived' not in ''.join(texts)
        assert len(mongo.clans.queries) == 1 and rows == before
        assert [node.content for node in content.editable_text_nodes(document, rendered)] == wu_faq_sections()
        assert len(content.editable_groups(document, wu_faq_sections())) == 4
        assert not mongo.bot_config.rows
    run(check())


@pytest.mark.parametrize('failure', ['empty', 'missing_type', 'unavailable'])
def test_registry_failure_blocks_public_render_and_preview_without_writes(failure):
    async def check():
        mongo = db()
        if failure == 'unavailable':
            mongo.clans = Clans(error=ServerSelectionTimeoutError('private details'))
        else:
            mongo.clans = Clans([] if failure == 'empty' else [r for r in registry_rows() if r['type'] != 'FWA'])
        item = web_content.descriptor('gauntlet--wu-faq')
        loaded = await web_content.load(mongo, item)
        assert not mongo.clans.queries
        for operation in [content.render(content.DOCUMENTS['wu-faq'], loaded['sections'], mongo=mongo, guild_id=20),
                          web_content.preview(item, loaded, mongo=mongo)]:
            with pytest.raises(ValueError) as raised:
                await operation
            assert 'private details' not in str(raised.value)
        assert not mongo.bot_config.rows
    run(check())


def test_legacy_saved_questions_expand_without_write_or_revision_change():
    async def check():
        mongo = db()
        questions = ['## Custom Questions  ', 'My exact old body.\n\nWhat is Warriors United?  ']
        row = {'_id': 'content:wu-faq:20', 'sections': questions[:], 'media': {}, 'revision': 17}
        mongo.bot_config.rows[row['_id']] = copy.deepcopy(row)
        sections, media, revision = await content.template_for(mongo, content.DOCUMENTS['wu-faq'], 20)
        assert sections[:2] == questions and sections[2:] == list(WU_FAQ_NEW_FIELDS)
        assert revision == 17 and media == {}
        assert mongo.bot_config.rows[row['_id']] == row
        rendered = await content.render(content.DOCUMENTS['wu-faq'], sections, mongo=mongo, guild_id=20)
        assert [node.content for node in content.text_nodes(rendered)][-2:] == questions
        assert mongo.bot_config.rows[row['_id']] == row
    run(check())


def test_historic_published_two_box_faq_keeps_questions_and_imports_defaults():
    async def check():
        questions = ['## Saved questions', 'Historic body\nunchanged.']
        old = [hikari.impl.ContainerComponentBuilder(components=[hikari.impl.TextDisplayComponentBuilder(content=text) for text in FAMILY_RULES]),
               hikari.impl.ContainerComponentBuilder(components=[hikari.impl.TextDisplayComponentBuilder(content=text) for text in questions])]
        models = _as_discord_models(old)
        document = content.DOCUMENTS['wu-faq']
        assert await content.supported_post_shape(document, models)
        assert [node.content for node in content.editable_text_nodes(document, models)] == [*questions, *WU_FAQ_NEW_FIELDS]
        assert len(old) == 2
    run(check())


def test_all_four_boxes_count_toward_size_guard_and_about_rules_are_red():
    async def check():
        mongo = db()
        fields = wu_faq_sections()
        rendered = await content.render(content.DOCUMENTS['wu-faq'], fields, mongo=mongo, guild_id=20)
        size = sum(len(node.content) for node in content.text_nodes(rendered))
        exact = fields[:]
        exact[3] += 'a' * (4000 - size)
        assert sum(len(node.content) for node in content.text_nodes(await content.render(content.DOCUMENTS['wu-faq'], exact, mongo=mongo, guild_id=20))) == 4000
        exact[3] += 'a'
        with pytest.raises(ValueError, match='4,001'):
            await content.render(content.DOCUMENTS['wu-faq'], exact, mongo=mongo, guild_id=20)
        about = await content.render(content.DOCUMENTS['about-us'], about_us_defaults(), mongo=mongo, guild_id=20)
        assert about[-2].accent_color == WU_RED
        assert [node.content for node in content.text_nodes([about[-2]])] == list(FAMILY_RULES)
    run(check())


def test_faq_editor_get_defers_registry_but_explicit_preview_reads_once():
    async def check():
        mongo = db()
        item = web_content.descriptor('gauntlet--wu-faq')
        loaded = await web_content.load(mongo, item)
        doc = await web_content.editor_document(item, loaded, mongo=mongo)
        assert doc['preview_supported'] is True and 'preview' not in doc
        assert not mongo.clans.queries
        assert [field['key'] for field in doc['fields'] if not field.get('readonly')] == [f'sections.{i}' for i in (2,3,4,5,6,7,8,0,1)]
        assert await web_content.preview(item, loaded, mongo=mongo)
        assert len(mongo.clans.queries) == 1
        assert not mongo.bot_config.rows
    run(check())

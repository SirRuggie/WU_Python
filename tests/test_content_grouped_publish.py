import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands import content
from test_content_dashboard_runtime import _ConfigCollection, _Context, _as_discord_models


def run(coro):
    return asyncio.run(coro)


def test_all_documents_group_headings_and_bodies_without_exposing_family_decorations():
    async def check():
        expected = {"join-family": 3, "about-us": 6, "strike-system": 6, "family-particulars": 11}
        for key, group_count in expected.items():
            document = content.DOCUMENTS[key]
            sections = [node.content for node in content.editable_text_nodes(document, await content.baseline(document))]
            groups = content.editable_groups(document, sections)
            assert len(groups) == group_count
            assert all(1 <= len(fields) <= 2 for _, fields in groups)
            indexes = [field[0] for _, fields in groups for field in fields]
            assert set(indexes) == {index for index, _ in content.editable_blocks(document, sections)}
    run(check())


def test_join_combined_sections_split_and_reassemble_title_body():
    async def check():
        document = content.DOCUMENTS["join-family"]
        sections = [node.content for node in content.editable_text_nodes(document, await content.baseline(document))]
        groups = content.editable_groups(document, sections)
        assert groups[1][1] == ((2, "Title", "title"), (2, "Body", "body"))
        assert content.modal_field_value(sections[2], "title").startswith("###")
        assert content.modal_field_value(sections[2], "body") == (
            "Select the button below to unlock the family welcome area. From there, learn who we are, "
            "read the required steps, and continue through recruitment. When you have completed the "
            "Recruit Gauntlet, open an application ticket to apply."
        )
    run(check())


def test_saved_target_load_keeps_template_draft_and_checks_owner_and_guild(monkeypatch):
    async def check():
        document = content.DOCUMENTS["about-us"]
        models = _as_discord_models(await content.baseline(document))
        live_sections = [node.content for node in content.text_nodes(models)]
        template_sections = [node.content for node in content.editable_text_nodes(document, models)]
        template_sections[0] += " Saved template"
        db = SimpleNamespace(bot_config=_ConfigCollection({
            "content:about-us:20": {"_id": "content:about-us:20", "sections": template_sections, "revision": 2},
            "content_published:20:about-us": {"_id": "content_published:20:about-us", "guild_id": 20, "document": "about-us", "channel_id": 30, "message_id": 40},
        }))
        captured = []
        monkeypatch.setattr(content, "load", AsyncMock(return_value=({"_id": "root", "user_id": 10, "guild_id": 20, "view": "root"}, None)))
        async def next_draft(_mongo, state):
            captured.append(state)
            return dict(state, _id="draft")
        monkeypatch.setattr(content, "new_draft", next_draft)
        ctx = _Context()
        ctx.interaction.values = ("about-us",)
        client = SimpleNamespace(rest=SimpleNamespace(
            fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),
            fetch_message=AsyncMock(return_value=SimpleNamespace(author=SimpleNamespace(id=999), components=models)),
        ))
        await content.choose_document.__wrapped__._func(ctx, "root", mongo=db, bot=client)
        assert captured[-1]["sections"] == template_sections
        assert captured[-1]["target"]["original"] == live_sections
        assert captured[-1]["destination_channel_id"] == 30
        assert content.target_matches_destination(captured[-1])
        client.rest.fetch_message.return_value.author.id = 123
        result = await content.choose_document.__wrapped__._func(ctx, "root", mongo=db, bot=client)
        assert captured[-1]["target"] is None
        assert "The saved message is not supported now." in str(result[0].build())
        client.rest.fetch_channel.return_value.guild_id = 99
        result = await content.choose_document.__wrapped__._func(ctx, "root", mongo=db, bot=client)
        assert captured[-1]["target"] is None
        assert "outside this server" in str(result[0].build())
    run(check())


def test_changed_destination_disables_old_post_update():
    assert not content.target_matches_destination({"target": {"channel_id": 30, "message_id": 40}, "destination_channel_id": 31})


def test_saved_target_rejects_deleted_post():
    async def check():
        document = content.DOCUMENTS["about-us"]
        client = SimpleNamespace(rest=SimpleNamespace(
            fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),
            fetch_message=AsyncMock(side_effect=hikari.NotFoundError(url="https://discord.com", headers={}, raw_body=b"", message="gone", code=10008)),
        ))
        with pytest.raises(ValueError) as error:
            await content.loaded_published_target(client, 20, document, {"channel_id": 30, "message_id": 40}, 999)
        assert str(error.value) == "The saved post cannot be found or opened. Check the channel. If you need a new post, select Send to channel."
    run(check())


def test_loading_published_copy_preserves_saved_template_snapshot(monkeypatch):
    async def check():
        document = content.DOCUMENTS["strike-system"]
        template = [node.content for node in content.text_nodes(await content.baseline(document))]
        live = list(template)
        live[0] += " visible now"
        media = content.media_snapshot(_as_discord_models(await content.baseline(document)))
        state = {
            "_id": "draft", "user_id": 10, "guild_id": 20, "document": "strike-system", "view": "document",
            "sections": template, "media": {}, "revision": 1, "destination_channel_id": 30,
            "target": {"channel_id": 30, "message_id": 40, "original": live, "original_media": media},
        }
        state["saved_snapshot"] = content.draft_snapshot(state)
        monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
        captured = []
        async def save_draft(_db, row):
            captured.append(row)
            return dict(row, _id="next")
        monkeypatch.setattr(content, "new_draft", save_draft)
        panel = await content.load_published_copy.__wrapped__._func(ctx=_Context(), action_id="draft", mongo=SimpleNamespace())
        assert captured[-1]["sections"] == live
        assert captured[-1]["saved_snapshot"]["sections"] == template
        assert captured[-1]["media"]["rules"] == media[0]
        assert "Published text and images loaded" in str(panel[0].build())
    run(check())


@pytest.mark.parametrize("saved", [True, False])
def test_save_and_update_only_publishes_after_successful_template_save(monkeypatch, saved):
    async def check():
        document = content.DOCUMENTS["strike-system"]
        sections = [node.content for node in content.editable_text_nodes(document, await content.baseline(document))]
        state = {"_id": "draft", "user_id": 10, "guild_id": 20, "document": "strike-system",
                 "view": "document", "sections": sections, "media": {}, "revision": 3,
                 "destination_channel_id": 30, "target": {"channel_id": 30, "message_id": 40, "original": sections}}
        monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
        save = AsyncMock(return_value=saved)
        publish = AsyncMock(return_value=[])
        monkeypatch.setattr(content, "_save", save)
        monkeypatch.setattr(content, "publish_state", publish)
        await content.save_and_publish.__wrapped__._func(_Context(), "draft", mongo=SimpleNamespace(), bot=SimpleNamespace())
        save.assert_awaited_once()
        if saved:
            publish.assert_awaited_once()
            passed = publish.call_args.args[1]
            assert passed["revision"] == 4
            assert passed["saved_snapshot"] == content.draft_snapshot(passed)
            assert publish.call_args.kwargs["saved_template"] is True
        else:
            publish.assert_not_awaited()
    run(check())


def test_published_pointer_failures_keep_draft_and_exact_recovery(monkeypatch):
    async def check():
        document = content.DOCUMENTS['about-us']
        coordinates = {'channel_id': 30, 'message_id': 40}
        rest = SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=99)),
                               fetch_message=AsyncMock())
        client = SimpleNamespace(rest=rest)
        with pytest.raises(ValueError) as error:
            await content.loaded_published_target(client, 20, document, coordinates, 999)
        assert str(error.value) == 'The published post is outside this server. Check the channel. If you need a new post, select Send to channel.'
        rest.fetch_message.assert_not_awaited()
        rest.fetch_channel.return_value.guild_id = 20
        rest.fetch_message.side_effect = OSError('offline')
        with pytest.raises(ValueError) as error:
            await content.loaded_published_target(client, 20, document, coordinates, 999)
        assert str(error.value) == 'I cannot read the published post right now. Your draft is still available.'
        rest.fetch_message.side_effect = None
        rest.fetch_message.return_value = SimpleNamespace(author=SimpleNamespace(id=999), components=[])
        monkeypatch.setattr(content, 'baseline', AsyncMock(return_value=[]))
        monkeypatch.setattr(content, 'component_shape', lambda _components: ())
        monkeypatch.setattr(content, 'acknowledgement_id', lambda *_args: 'present')
        monkeypatch.setattr(content, 'media_snapshot', lambda _components: [])
        with pytest.raises(ValueError) as error:
            await content.loaded_published_target(client, 20, document, coordinates, 999)
        assert str(error.value) == "The saved post's images changed. Check the channel. If you need a new post, select Send to channel."
    run(check())


def test_published_update_requires_matching_target_without_save_or_send(monkeypatch):
    async def check():
        state = {'document': 'about-us', 'target': {'channel_id': 30, 'message_id': 40}, 'destination_channel_id': 31}
        monkeypatch.setattr(content, 'load', AsyncMock(return_value=(state, None)))
        monkeypatch.setattr(content, 'panel', lambda _state, notice: notice)
        save = AsyncMock()
        publish = AsyncMock()
        monkeypatch.setattr(content, '_save', save)
        monkeypatch.setattr(content, 'publish_state', publish)
        result = await content.save_and_publish.__wrapped__._func(_Context(), 'draft', mongo=object(), bot=object())
        assert result == 'The published post is unavailable in this posting channel. Your draft is unchanged.'
        save.assert_not_awaited()
        publish.assert_not_awaited()
        state['target'] = None
        result = await content.publish.__wrapped__._func(_Context(), 'draft', mongo=object(), bot=object())
        assert result == 'Select a published post before updating it.'
        publish.assert_not_awaited()
    run(check())


class _InfoStateCollection:
    def __init__(self, rows=None):
        import copy
        self.rows = copy.deepcopy(rows or {})

    async def insert_one(self, row):
        import copy
        self.rows[row['_id']] = copy.deepcopy(row)
        return SimpleNamespace(inserted_id=row['_id'])

    async def find_one(self, query, *args):
        import copy
        return copy.deepcopy(self.rows.get(query['_id']))

    async def update_one(self, query, update, **kwargs):
        import copy
        row = self.rows.get(query['_id'])
        if not row:
            return SimpleNamespace(matched_count=0, upserted_id=None)
        for key, value in query.items():
            if isinstance(value, dict) and '$ne' in value:
                if row.get(key) == value['$ne']:
                    return SimpleNamespace(matched_count=0, upserted_id=None)
            elif row.get(key) != value:
                return SimpleNamespace(matched_count=0, upserted_id=None)
        row.update(copy.deepcopy(update['$set']))
        return SimpleNamespace(matched_count=1, upserted_id=None)


class _InfoConfigCollection(_ConfigCollection):
    async def update_one(self, query, update, *, upsert=False):
        if query['_id'].startswith('content_published:') and upsert:
            self.updates.append((query, update, upsert))
            self.documents[query['_id']] = dict(update['$set'], _id=query['_id'])
            return SimpleNamespace(matched_count=0, upserted_id=query['_id'])
        return await super().update_one(query, update, upsert=upsert)


def _info_database():
    from utils.info_channel_defaults import FAMILY_RULES
    from test_info_channel_content import Clans
    return SimpleNamespace(
        bot_config=_InfoConfigCollection({'content:family-rules:20': {
            '_id': 'content:family-rules:20', 'sections': list(FAMILY_RULES), 'media': {}, 'revision': 1,
        }}),
        clans=Clans(), component_state=_InfoStateCollection(),
    )


def test_composed_faq_and_about_us_use_saved_rules_and_actual_render_budget():
    async def check():
        from utils.info_channel_content import about_us_defaults
        from utils.info_channel_defaults import WU_FAQ_QUESTIONS
        db = _info_database()
        about = await content.render(content.DOCUMENTS['about-us'], about_us_defaults(), mongo=db, guild_id=20)
        texts = [node.content for node in content.text_nodes(about)]
        assert sum(map(len, texts)) == 3831
        assert len(texts) == 14 and len(content.editable_text_nodes(content.DOCUMENTS['about-us'], about)) == 12
        assert texts[-4:-2] == db.bot_config.documents['content:family-rules:20']['sections']
        assert texts[-2] == '## ⏩ Next Step'
        faq = await content.render(content.DOCUMENTS['wu-faq'], list(WU_FAQ_QUESTIONS), mongo=db, guild_id=20)
        assert len(faq) == 2
        assert [node.content for node in content.text_nodes(faq)][:2] == texts[-4:-2]
        assert content.DOCUMENTS['wu-faq'].acknowledgement is None
        assert all(not getattr(node, 'custom_id', None) for item in faq for node in item.components)
        assert len(db.clans.queries) == 1
        assert not db.bot_config.updates and not db.bot_config.inserts
    run(check())


def test_rules_editor_has_no_channel_send_images_or_role_control():
    async def check():
        from utils.info_channel_defaults import FAMILY_RULES
        state = dict(_id='rules', user_id=10, guild_id=20, document='family-rules', sections=list(FAMILY_RULES), media={}, revision=1)
        state['saved_snapshot'] = content.draft_snapshot(state)
        rendered = str(content.panel(state)[0].build())
        assert 'content_destination:' not in rendered
        assert 'content_send:' not in rendered
        assert 'content_media:' not in rendered
        assert not content.has_posting_channel('family-rules')
        with pytest.raises(ValueError):
            content.destination_key(20, 'family-rules')
        preview = await content.preview_panel(state, _info_database())
        assert 'content_back_document:rules' in str(preview[-1].build())
        assert 'acknowledge' not in str(preview)
    run(check())


def test_two_rules_editors_use_existing_template_revision_cas():
    async def check():
        from utils.info_channel_defaults import FAMILY_RULES
        db = _info_database()
        first = dict(document='family-rules', guild_id=20, revision=1, sections=[FAMILY_RULES[0], FAMILY_RULES[1]+' First'], media={})
        second = dict(first, sections=[FAMILY_RULES[0], FAMILY_RULES[1]+' Second'])
        result = await asyncio.gather(content._save_untracked(_Context(), first, db), content._save_untracked(_Context(), second, db))
        assert sorted(result) == [False, True]
        assert db.bot_config.documents['content:family-rules:20']['revision'] == 2
        assert len(db.bot_config.updates) == 2
        assert all(call[0] == {'_id':'content:family-rules:20','revision':1} for call in db.bot_config.updates)
    run(check())


def test_rules_fanout_reports_partial_results_and_does_not_repeat_after_restart(monkeypatch):
    async def check():
        import copy
        from utils.info_channel_content import about_us_defaults
        from utils.info_channel_defaults import WU_FAQ_QUESTIONS, FAMILY_RULES
        db = _info_database()
        faq = _as_discord_models(await content.render(content.DOCUMENTS['wu-faq'], list(WU_FAQ_QUESTIONS), mongo=db, guild_id=20))
        about = _as_discord_models(await content.render(content.DOCUMENTS['about-us'], about_us_defaults(), mongo=db, guild_id=20))
        messages = {40:SimpleNamespace(author=SimpleNamespace(id=999),components=faq,attachments=[]),
                    41:SimpleNamespace(author=SimpleNamespace(id=999),components=about,attachments=[])}
        for key, mid in [('wu-faq',40),('about-us',41)]:
            db.bot_config.documents[f'content_published:20:{key}'] = {'_id':f'content_published:20:{key}','guild_id':20,'document':key,'channel_id':30,'message_id':mid}
        async def fetch(_channel, mid): return messages[mid]
        bot = SimpleNamespace(rest=SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),fetch_message=AsyncMock(side_effect=fetch),edit_message=AsyncMock(),create_message=AsyncMock()))
        targets, errors = await content.shared_rule_targets(db, bot, 20, 999)
        assert not errors and set(targets) == {'wu-faq','about-us'}
        assert len(db.clans.queries) == 1  # Offer reads posts, never registry.
        rules = [FAMILY_RULES[0], FAMILY_RULES[1]+' Updated']
        db.bot_config.documents['content:family-rules:20'].update(sections=rules,revision=2)
        state = dict(user_id=10,guild_id=20,document='family-rules',sections=rules,media={},revision=2,shared_targets=targets)
        state['saved_snapshot'] = content.draft_snapshot(state)
        draft = await content.new_draft(db,state)
        # External AboutUs edit after offer: only that target must fail.
        messages[41] = copy.deepcopy(messages[41])
        messages[41].components[1].components[0].content += ' External edit'
        monkeypatch.setattr(content,'panel',lambda state,notice=None:dict(state,notice=notice))
        result = await content.publish_shared_rules.__wrapped__._func(_Context(),draft['_id'],mongo=db,bot=bot)
        outcomes = result['shared_update_results']
        assert outcomes['wu-faq']['ok'] is True
        assert outcomes['about-us']['ok'] is False and 'changed' in outcomes['about-us']['message']
        bot.rest.edit_message.assert_awaited_once()
        assert bot.rest.edit_message.await_args.args[:2] == (30,40)
        assert all(bot.rest.edit_message.await_args.kwargs[key] is False for key in content.NO_MENTIONS)
        bot.rest.create_message.assert_not_awaited()
        assert db.bot_config.documents['content:family-rules:20']['sections'] == rules
        # A new process/session loads persisted claim/results, not a module flag.
        restarted = SimpleNamespace(bot_config=db.bot_config,clans=db.clans,component_state=_InfoStateCollection(db.component_state.rows))
        again = await content.publish_shared_rules.__wrapped__._func(_Context(),draft['_id'],mongo=restarted,bot=bot)
        assert 'already started' in again['notice']
        bot.rest.edit_message.assert_awaited_once()
    run(check())


@pytest.mark.parametrize('restriction',['permission','user','guild'])
def test_new_shared_update_rechecks_permission_and_draft_ownership(restriction):
    async def check():
        from utils.info_channel_defaults import FAMILY_RULES
        db = _info_database()
        state = dict(user_id=10,guild_id=20,document='family-rules',sections=list(FAMILY_RULES),media={},revision=1)
        state['saved_snapshot'] = content.draft_snapshot(state)
        draft = await content.new_draft(db,state)
        ctx = _Context()
        if restriction == 'permission':ctx.interaction.member.permissions = hikari.Permissions.NONE
        elif restriction == 'user':ctx.user.id = 11
        else:ctx.interaction.guild_id = 21
        bot = SimpleNamespace(rest=SimpleNamespace(edit_message=AsyncMock(),fetch_message=AsyncMock(),create_message=AsyncMock()))
        await content.publish_shared_rules.__wrapped__._func(ctx,draft['_id'],mongo=db,bot=bot)
        bot.rest.fetch_message.assert_not_awaited();bot.rest.edit_message.assert_not_awaited();bot.rest.create_message.assert_not_awaited()
        assert not db.bot_config.updates
    run(check())


def test_plain_live_faq_cannot_be_adopted_as_new_v2_faq():
    async def check():
        client=SimpleNamespace(rest=SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),fetch_message=AsyncMock(return_value=SimpleNamespace(author=SimpleNamespace(id=999),components=[]))))
        with pytest.raises(ValueError,match='not supported'):
            await content.loaded_published_target(client,20,content.DOCUMENTS['wu-faq'],{'channel_id':30,'message_id':40},999)
    run(check())


def test_wu_faq_send_has_no_acknowledgement_or_role_grant_and_blocks_mentions(monkeypatch):
    async def check():
        from utils.info_channel_defaults import WU_FAQ_QUESTIONS
        db=_info_database();ctx=_Context()
        draft=await content.new_draft(db,dict(user_id=10,guild_id=20,document='wu-faq',sections=list(WU_FAQ_QUESTIONS),media={},revision=0,destination_channel_id=30))
        rest=SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20,type=hikari.ChannelType.GUILD_TEXT)),create_message=AsyncMock(return_value=SimpleNamespace(id=50)),add_role_to_member=AsyncMock(),fetch_roles=AsyncMock())
        monkeypatch.setattr(content,'destination_permissions',AsyncMock(return_value=hikari.Permissions.ADMINISTRATOR))
        await content.send_to_channel.__wrapped__._func(ctx,draft['_id'],mongo=db,bot=SimpleNamespace(rest=rest))
        rest.create_message.assert_awaited_once();rest.add_role_to_member.assert_not_awaited();rest.fetch_roles.assert_not_awaited()
        kwargs=rest.create_message.await_args.kwargs
        assert all(kwargs[key] is False for key in content.NO_MENTIONS)
        assert content.component_count(kwargs['components'])==6
        assert not content.acknowledgement_id(kwargs['components'],content.DOCUMENTS['wu-faq'])
        assert db.bot_config.documents['content_published:20:wu-faq']['message_id']==50
    run(check())


def test_forged_rules_send_or_destination_cannot_write_or_call_discord():
    async def check():
        from utils.info_channel_defaults import FAMILY_RULES
        db=_info_database();draft=await content.new_draft(db,dict(user_id=10,guild_id=20,document='family-rules',sections=list(FAMILY_RULES),media={},revision=1,destination_channel_id=30,destination_baseline=None))
        ctx=_Context();ctx.interaction.values=('30',)
        rest=SimpleNamespace(fetch_channel=AsyncMock(),create_message=AsyncMock(),edit_message=AsyncMock())
        for handler in (content.choose_destination,content.send_to_channel):
            await handler.__wrapped__._func(ctx,draft['_id'],mongo=db,bot=SimpleNamespace(rest=rest))
        rest.fetch_channel.assert_not_awaited();rest.create_message.assert_not_awaited();rest.edit_message.assert_not_awaited()
        assert not db.bot_config.inserts and not db.bot_config.updates
    run(check())


def test_registry_failure_blocks_about_us_send_before_durable_claim_or_message(monkeypatch):
    async def check():
        from pymongo.errors import ServerSelectionTimeoutError
        from test_info_channel_content import Clans
        from utils.info_channel_content import about_us_defaults
        db=_info_database();db.clans=Clans(error=ServerSelectionTimeoutError('private'))
        draft=await content.new_draft(db,dict(user_id=10,guild_id=20,document='about-us',sections=about_us_defaults(),media={},revision=0,destination_channel_id=30))
        rest=SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20,type=hikari.ChannelType.GUILD_TEXT)),create_message=AsyncMock())
        monkeypatch.setattr(content,'destination_permissions',AsyncMock(return_value=hikari.Permissions.ADMINISTRATOR))
        monkeypatch.setattr(content,'_ready_for_destination',AsyncMock(return_value=(True,None)))
        result=await content.send_to_channel.__wrapped__._func(_Context(),draft['_id'],mongo=db,bot=SimpleNamespace(rest=rest))
        assert 'cannot read the clan registry' in str(result[0].build())
        rest.create_message.assert_not_awaited()
        assert not db.bot_config.inserts
    run(check())


def test_rules_revision_change_after_offer_blocks_all_public_edits():
    async def check():
        from utils.info_channel_defaults import FAMILY_RULES
        db=_info_database();state=dict(user_id=10,guild_id=20,document='family-rules',sections=list(FAMILY_RULES),media={},revision=1,shared_targets={'wu-faq':{'channel_id':30,'message_id':40}})
        state['saved_snapshot']=content.draft_snapshot(state);draft=await content.new_draft(db,state)
        db.bot_config.documents['content:family-rules:20']['revision']=2
        rest=SimpleNamespace(fetch_message=AsyncMock(),edit_message=AsyncMock(),create_message=AsyncMock())
        result=await content.publish_shared_rules.__wrapped__._func(_Context(),draft['_id'],mongo=db,bot=SimpleNamespace(rest=rest))
        assert 'Family Rules changed' in str(result[0].build())
        rest.fetch_message.assert_not_awaited();rest.edit_message.assert_not_awaited();rest.create_message.assert_not_awaited()
        assert not db.bot_config.updates
    run(check())


async def _rules_job_fixture():
    from utils.info_channel_defaults import FAMILY_RULES, WU_FAQ_QUESTIONS
    from utils.info_channel_content import about_us_defaults
    db=_info_database()
    targets={}
    for key,mid,sections,media in [('wu-faq',40,list(WU_FAQ_QUESTIONS),[]),('about-us',41,about_us_defaults(),['https://example.com/banner.png'])]:
        db.bot_config.documents[f'content_published:20:{key}']={'_id':f'content_published:20:{key}','guild_id':20,'document':key,'channel_id':30,'message_id':mid}
        targets[key]={'channel_id':30,'message_id':mid,'original':sections,'editable_original':sections,'original_media':media,'tracked':True}
    state=dict(user_id=10,guild_id=20,document='family-rules',sections=list(FAMILY_RULES),media={},revision=1,shared_targets=targets)
    state['saved_snapshot']=content.draft_snapshot(state)
    return db,await content.new_draft(db,state)


def test_pointer_read_failure_keeps_first_result_and_reports_second_separately(monkeypatch):
    async def check():
        from pymongo.errors import ServerSelectionTimeoutError
        db,draft=await _rules_job_fixture();original=db.bot_config.find_one
        async def find(query):
            if query['_id']=='content_published:20:about-us':raise ServerSelectionTimeoutError('private')
            return await original(query)
        db.bot_config.find_one=find
        publish=AsyncMock(return_value={'ok':True,'uncertain':False,'message':'Updated.'})
        monkeypatch.setattr(content,'publish_state',publish)
        monkeypatch.setattr(content,'panel',lambda state,notice=None:dict(state,notice=notice))
        result=await content.publish_shared_rules.__wrapped__._func(_Context(),draft['_id'],mongo=db,bot=SimpleNamespace())
        assert result['shared_update_results']['wu-faq']['ok'] is True
        assert result['shared_update_results']['about-us']['ok'] is False
        assert result['shared_update_results']['about-us']['uncertain'] is True
        publish.assert_awaited_once()
        assert 'private' not in result['shared_update_results']['about-us']['message']
    run(check())


def test_result_storage_failure_stops_next_edit_and_shows_acknowledged_first_result(monkeypatch):
    async def check():
        from pymongo.errors import ServerSelectionTimeoutError
        db,draft=await _rules_job_fixture();original=content.update_state;calls=0
        async def store(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==3:raise ServerSelectionTimeoutError('private')
            return await original(*args,**kwargs)
        monkeypatch.setattr(content,'update_state',store)
        publish=AsyncMock(return_value={'ok':True,'uncertain':False,'message':'Updated.'})
        monkeypatch.setattr(content,'publish_state',publish)
        monkeypatch.setattr(content,'panel',lambda state,notice=None:dict(state,notice=notice))
        result=await content.publish_shared_rules.__wrapped__._func(_Context(),draft['_id'],mongo=db,bot=SimpleNamespace())
        assert result['shared_update_results']['wu-faq']['ok'] is True
        assert 'Not attempted' in result['shared_update_results']['about-us']['message']
        assert 'could not all be persisted' in result['notice']
        publish.assert_awaited_once()
        assert db.component_state.rows[draft['_id']]['shared_update_started'] is True
    run(check())

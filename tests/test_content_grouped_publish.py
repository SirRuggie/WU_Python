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
            sections = [node.content for node in content.text_nodes(await content.baseline(document))]
            groups = content.editable_groups(document, sections)
            assert len(groups) == group_count
            assert all(1 <= len(fields) <= 2 for _, fields in groups)
            indexes = [field[0] for _, fields in groups for field in fields]
            assert set(indexes) == {index for index, _ in content.editable_blocks(document, sections)}
    run(check())


def test_join_combined_sections_split_and_reassemble_title_body():
    async def check():
        document = content.DOCUMENTS["join-family"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
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
        template_sections = list(live_sections)
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
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
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

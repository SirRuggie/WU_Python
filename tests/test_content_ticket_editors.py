import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from extensions.commands import content, ticket_runtime
from test_content_dashboard_runtime import _Context, _ConfigCollection, _custom_ids, _panel_texts


def run(coro):
    return asyncio.run(coro)


def draft(key):
    document = content.DOCUMENTS[key]
    sections = [node.content for node in content.text_nodes(content.document_renderer(document)())]
    state = {
        "_id": "draft", "guild_id": 20, "user_id": 10, "view": "document",
        "document": key, "sections": sections, "media": {}, "revision": 0,
        "destination_channel_id": 30,
        "target": {"channel_id": 30, "message_id": 40, "original": sections},
    }
    state["saved_snapshot"] = content.draft_snapshot(state)
    return state


def test_ticket_documents_have_expected_edit_fields_and_preview_controls():
    apply = draft("apply")
    rite = draft("rite-of-passage")
    assert len(apply["sections"]) == 2
    assert len(rite["sections"]) == 5
    assert len(content.editable_groups(content.DOCUMENTS["apply"], apply["sections"])) == 1
    groups = content.editable_groups(content.DOCUMENTS["rite-of-passage"], rite["sections"])
    assert len(groups) == 4
    assert all(len(fields) == 2 for _, fields in groups)
    assert len(content.media_galleries(run(content.baseline(content.DOCUMENTS["apply"])))) == 1
    assert len(content.media_galleries(run(content.baseline(content.DOCUMENTS["rite-of-passage"])))) == 1
    for state in (apply, rite):
        preview = run(content.preview_panel(state))
        assert f"content_back_document:{state['_id']}" in _custom_ids(preview)


def test_ticket_panels_expose_only_authorized_post_actions():
    apply = draft("apply")
    rite = draft("rite-of-passage")
    apply_ids = _custom_ids(content.panel(apply))
    rite_ids = _custom_ids(content.panel(rite))
    assert "content_publish:draft" in apply_ids
    assert "content_send:draft" not in apply_ids
    assert "content_destination:draft" not in apply_ids
    assert "content_publish:draft" not in rite_ids
    assert "content_send:draft" not in rite_ids
    assert "content_destination:draft" not in rite_ids
    assert any("future private" in text for text in _panel_texts(content.panel(rite)))


def test_apply_published_pointer_comes_only_from_matching_rollout(monkeypatch):
    async def check():
        rollout = ticket_runtime.RolloutState(
            "thread_default", 3, True,
            thread_intake=ticket_runtime.IntakeSource(20, 30, 40),
        )
        get_rollout = AsyncMock(return_value=rollout)
        monkeypatch.setattr(ticket_runtime, "get_rollout", get_rollout)
        db = SimpleNamespace(bot_config=_ConfigCollection({
            "content_published:20:apply": {
                "channel_id": 99, "message_id": 100, "guild_id": 20, "document": "apply"
            }
        }))
        assert await content.published_for(db, 20, "apply") == {"channel_id": 30, "message_id": 40}
        assert await content.published_for(db, 21, "apply") is None
        assert await content.published_for(db, 20, "rite-of-passage") is None
        get_rollout.assert_awaited()
    run(check())


def test_direct_send_and_destination_invocations_reject_ticket_panels(monkeypatch):
    async def check():
        db = SimpleNamespace(bot_config=_ConfigCollection())
        bot = SimpleNamespace(rest=SimpleNamespace(
            fetch_channel=AsyncMock(), create_message=AsyncMock()
        ))
        for key in ("apply", "rite-of-passage"):
            state = draft(key)
            monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
            ctx = _Context()
            ctx.interaction.values = ("123",)
            sent = await content.send_to_channel.__wrapped__._func(ctx, "draft", mongo=db, bot=bot)
            destination = await content.choose_destination.__wrapped__._func(ctx, "draft", mongo=db, bot=bot)
            assert any("cannot send a new post" in text for text in _panel_texts(sent))
            assert any("does not support a posting channel" in text for text in _panel_texts(destination))
        bot.rest.fetch_channel.assert_not_awaited()
        bot.rest.create_message.assert_not_awaited()
        assert db.bot_config.updates == []
    run(check())


def test_rite_direct_publish_routes_reject_without_saving(monkeypatch):
    async def check():
        state = draft("rite-of-passage")
        monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
        save = AsyncMock()
        monkeypatch.setattr(content, "_save", save)
        db = SimpleNamespace()
        bot = SimpleNamespace()
        for handler in (content.publish, content.save_and_publish):
            result = await handler.__wrapped__._func(_Context(), "draft", mongo=db, bot=bot)
            assert any("Rite of Passage is private" in text for text in _panel_texts(result))
        save.assert_not_awaited()
    run(check())


def test_apply_save_publish_rechecks_binding_before_template_save(monkeypatch):
    async def check():
        state = draft("apply")
        monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
        monkeypatch.setattr(content, "published_for", AsyncMock(return_value={"channel_id": 30, "message_id": 41}))
        save = AsyncMock()
        monkeypatch.setattr(content, "_save", save)
        result = await content.save_and_publish.__wrapped__._func(
            _Context(), "draft", mongo=SimpleNamespace(), bot=SimpleNamespace()
        )
        assert any("active public Apply post changed" in text for text in _panel_texts(result))
        save.assert_not_awaited()
    run(check())

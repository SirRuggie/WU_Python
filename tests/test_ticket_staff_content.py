import asyncio
from copy import deepcopy
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import hikari
import pytest
from pymongo.errors import DuplicateKeyError
from utils import ticket_staff_content as content
from extensions.commands import recruitment_staff_thread as editor, manage
from extensions.commands.tickets import thread_service


def test_defaults_and_rendering_keep_types_separate():
    main, fwa = content.defaults("main"), content.defaults("fwa")
    assert "donations" not in main["sections"]
    assert "donations" in fwa["sections"]
    main["sections"]["hook"] = {"title": "Interest", "body": "Custom Main question"}
    assert (
        list(content.messages("main", main, 10))[2][1]
        == "**Interest**\nCustom Main question"
    )
    assert "Custom Main" not in repr(fwa)
    assert list(content.messages("fwa", fwa, 20))[0][1].startswith("<@&20> ")


def test_load_and_save_use_guild_type_key_and_conflict_guard():
    coll = S(
        find_one=AsyncMock(return_value=None),
        update_one=AsyncMock(return_value=S(matched_count=0, upserted_id="10:main")),
    )
    mongo = S(ticket_staff_templates=coll)
    template = asyncio.run(content.load(mongo, 10, "main"))
    coll.find_one.assert_awaited_once_with({"_id": "10:main"})
    saved = asyncio.run(content.save(mongo, 10, "main", template, 30))
    assert (
        saved["guild_id"] == 10 and saved["updated_by"] == 30 and saved["revision"] == 1
    )
    coll.update_one.side_effect = DuplicateKeyError("already saved")
    with pytest.raises(ValueError, match="Another editor"):
        asyncio.run(content.save(mongo, 10, "main", template, 30))


def test_editor_permission_and_session_ownership(monkeypatch):
    ctx = S(
        user=S(id=20),
        interaction=S(
            guild_id=10, member=S(permissions=hikari.Permissions.MANAGE_GUILD)
        ),
    )
    doc = dict(type="staff_thread_editor", user_id=21, guild_id=10)
    monkeypatch.setattr(editor, "get_state", AsyncMock(return_value=doc))
    with pytest.raises(ValueError, match="own editor"):
        asyncio.run(editor.state(ctx, object(), "token"))
    doc["user_id"] = 20
    ctx.interaction.member.permissions = hikari.Permissions.NONE
    with pytest.raises(ValueError, match="Manage Server"):
        asyncio.run(editor.state(ctx, object(), "token"))


def test_editor_has_grouped_sections_and_navigation():
    data = dict(
        _id="token", manage_token="manage", kind="fwa", template=content.defaults("fwa")
    )
    payload = editor.page(data)[0].build()[0]
    assert "Recruitment Staff Thread" in repr(payload)
    assert "Donations and clan chat" in repr(payload)
    assert "Save template" in repr(payload) and "Return to Management Home" in repr(
        payload
    )
    assert any(key == "recruitment_staff_thread" for _, key, _ in manage.DESTINATIONS)


def test_staff_delivery_uses_snapshot_without_pings_or_live_template_reads(monkeypatch):
    template = content.defaults("fwa")
    template["sections"]["hook"] = {"title": "Custom heading", "body": "Saved message"}
    sent = []

    async def send(*args, **kwargs):
        sent.append((args, kwargs))

    monkeypatch.setattr(thread_service, "_send_once", send)
    asyncio.run(
        thread_service._deliver_staff_talking_points(
            object(),
            102,
            "fwa",
            recruiter_role=40,
            bot_id=7,
            template=deepcopy(template),
        )
    )
    assert len(sent) == 4
    assert all(
        args[1] == 102 and not kw["role_mentions"] and not kw["user_mentions"]
        for args, kw in sent
    )
    assert sent[2][0][3] == "**Custom heading**\nSaved message"
    assert sent[0][0][3].startswith("<@&40> ")


def test_message_lengths_reject_overflow():
    template = content.defaults("main")
    template["sections"]["hook"]["body"] = "x" * 1801
    with pytest.raises(ValueError):
        content.validate("main", template)

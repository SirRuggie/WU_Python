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


def test_additional_messages_are_independent_and_delivered_in_order(monkeypatch):
    main, fwa = content.defaults("main"), content.defaults("fwa")
    key = "custom_0123456789abcdef"
    main["sections"][key] = {"title": "Availability", "body": "When can you join us?"}
    content.validate("main", main)
    assert key not in fwa["sections"]
    sent = []

    async def send(*args, **kwargs):
        sent.append((args, kwargs))

    monkeypatch.setattr(thread_service, "_send_once", send)
    asyncio.run(
        thread_service._deliver_staff_talking_points(
            object(), 102, "main", recruiter_role=40, bot_id=7, template=main
        )
    )
    assert sent[-1][0][2] == "ticket-setup:staff:" + key
    assert sent[-1][0][3] == "**Availability**\nWhen can you join us?"
    assert all(not kw["user_mentions"] and not kw["role_mentions"] for _, kw in sent)
    assert list(content.messages("fwa", fwa, 40))[-1][0] == "donations"


def test_maximum_editor_template_is_paginated_within_discord_limits():
    template = content.defaults("fwa")
    for index in range(content.MAX_SECTIONS - len(template["sections"])):
        template["sections"][f"custom_{index:016x}"] = {
            "title": "Question " + str(index),
            "body": "Body",
        }
    content.validate("fwa", template)

    def walk(components):
        for component in components:
            yield component
            yield from walk(getattr(component, "components", ()) or ())

    for page in range(5):
        view = editor.page(
            dict(
                _id="token",
                manage_token="manage",
                kind="fwa",
                template=template,
                section_page=page,
            )
        )
        nodes = list(walk(view))
        assert len(nodes) <= 40
        assert (
            len([n for n in nodes if ":edit:" in str(getattr(n, "custom_id", ""))]) == 5
        )
        add = next(
            n for n in nodes if str(getattr(n, "custom_id", "")).endswith(":add")
        )
        assert add.is_disabled
        assert any(getattr(n, "label", None) == "Next" for n in nodes)
    template["sections"]["custom_ffffffffffffffff"] = {
        "title": "Overflow",
        "body": "Body",
    }
    with pytest.raises(ValueError, match="at most"):
        content.validate("fwa", template)


def test_add_form_creates_only_selected_type_draft(monkeypatch):
    async def run():
        data = dict(
            _id="token",
            manage_token="manage",
            kind="main",
            template=content.defaults("main"),
        )
        original = deepcopy(data["template"])
        monkeypatch.setattr(editor, "state", AsyncMock(return_value=data))

        async def new_state(_mongo, old, **changes):
            return {**old, **changes}

        monkeypatch.setattr(editor, "new_state", new_state)
        ctx = S(
            interaction=S(
                create_initial_response=AsyncMock(),
                edit_initial_response=AsyncMock(),
                components=[
                    S(
                        components=[
                            S(custom_id="title", value="Availability"),
                            S(custom_id="body", value="When can you join us?"),
                        ]
                    )
                ],
            )
        )
        await editor.form(ctx, "token:new", mongo=object())
        view = repr(
            ctx.interaction.edit_initial_response.call_args.kwargs["components"]
        )
        assert "Availability" in view and "When can you join us?" in view
        assert data["template"] == original
        assert "Availability" not in repr(content.defaults("fwa"))

    asyncio.run(run())


def test_custom_sections_save_under_only_selected_kind_key():
    template = content.defaults("fwa")
    template["sections"]["custom_0123456789abcdef"] = {
        "title": "Extra",
        "body": "Extra FWA question",
    }
    coll = S(update_one=AsyncMock(return_value=S(matched_count=1, upserted_id=None)))
    saved = asyncio.run(
        content.save(S(ticket_staff_templates=coll), 10, "fwa", template, 30)
    )
    assert coll.update_one.call_args.args[0]["_id"] == "10:fwa"
    assert saved["sections"]["custom_0123456789abcdef"]["body"] == "Extra FWA question"

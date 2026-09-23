import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import cwl_dashboard as dashboard
from extensions.components import registered_functions


def _campaign():
    messages = {}
    for key, _label in dashboard.MESSAGE_CHOICES:
        messages[key] = {
            "variants": {
                audience: {
                    "enabled": True, "title": f"{key} {audience}", "body": "Copy",
                    "media_url": "https://example.test/image.png", "buttons": [], "role_ids": [],
                }
                for audience in dashboard.AUDIENCES
            }
        }
    return {
        "timezone": "America/New_York", "signup_deadline": {"day": 30, "hour": 17, "minute": 0},
        "messages": messages, "schedules": {"signup": {"mode": "monthly", "day": 20, "time": "17:00"}},
    }


def _draft():
    return {"_id": "cwl:draft:2:" + "f" * 32, "token": "f" * 32, "user_id": 1, "guild_id": 2, "cycle": "2026-10", "base_revision": 4, "campaign": _campaign()}


def _ctx(user_id=1, permissions=hikari.Permissions.MANAGE_GUILD):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        interaction=SimpleNamespace(guild_id=2, member=SimpleNamespace(permissions=permissions)),
        respond=AsyncMock(),
    )


def test_templates_use_the_backend_variants_shape_without_losing_copy():
    campaign = _campaign()
    main = dashboard._template(campaign, "signup", "main")
    main["body"] = "Edited Main copy"
    assert campaign["messages"]["signup"]["variants"]["main"]["body"] == "Edited Main copy"
    assert campaign["messages"]["signup"]["variants"]["lazy"]["body"] == "Copy"


def test_dashboard_actions_use_modal_and_state_contracts():
    modal = {"cwl_text", "cwl_image", "cwl_delivery", "cwl_schedule_mode", "cwl_settings", "cwl_deadline_mode", "cwl_button_add", "cwl_button_edit"}
    submit = {"cwl_submit_text", "cwl_submit_links", "cwl_submit_delivery", "cwl_submit_schedule", "cwl_submit_settings", "cwl_image_submit"}
    for name in modal:
        action = registered_functions[name]
        assert action.opens_modal and action.no_return and not action.preload_state
    for name in submit:
        action = registered_functions[name]
        assert action.is_modal and action.no_return and not action.preload_state


def test_panel_has_all_five_private_workspaces(monkeypatch):
    monkeypatch.setattr(dashboard.cwl_campaign, "resolve_schedule", lambda *_args, **_kwargs: [])
    built = asyncio.run(dashboard.panel(_draft()))[0].build()[0]
    encoded = str(built)
    for label in ("Overview", "Messages", "Schedule", "Settings", "History"):
        assert label in encoded
    assert "Pause campaign" in encoded


def test_message_editor_exposes_copy_artwork_buttons_delivery_and_safe_preview():
    built = dashboard.message_editor(_draft(), "signup", "main")[0].build()[0]
    encoded = str(built)
    for label in ("Edit text", "Upload replacement", "Edit buttons", "Delivery", "Preview", "Current image in this draft"):
        assert label in encoded


def test_image_editor_matches_content_dashboard_upload_and_default_restore_ux():
    draft = _draft()
    default = dashboard.cwl_campaign.default_campaign()["messages"]["signup"]["variants"]["main"]["media_url"]
    draft["campaign"]["messages"]["signup"]["variants"]["main"]["media_url"] = default
    built = dashboard.message_editor(draft, "signup", "main")[0].build()[0]
    encoded = str(built)
    assert "Upload replacement" in encoded
    assert "Restore default image" in encoded
    # Native/default artwork cannot be restored again, so the action is disabled.
    restore = next(
        child for row in built["components"] for child in row.get("components", ())
        if child.get("label") == "Restore default image"
    )
    assert restore["disabled"] is True

    draft["campaign"]["messages"]["signup"]["variants"]["main"]["media_url"] = "https://example.test/new.png"
    changed = dashboard.message_editor(draft, "signup", "main", "Artwork uploaded to this draft.")[0].build()[0]
    restore = next(
        child for row in changed["components"] for child in row.get("components", ())
        if child.get("label") == "Restore default image"
    )
    assert restore["disabled"] is False
    assert default != "https://example.test/new.png"


def test_every_dashboard_load_rechecks_permission_owner_and_guild(monkeypatch):
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=_draft()))
    denied = _ctx(permissions=hikari.Permissions.NONE)
    draft, problem = asyncio.run(dashboard._load(denied, object(), "draft"))
    assert draft is None and "Manage Server" in problem
    wrong_user = _ctx(user_id=99)
    draft, problem = asyncio.run(dashboard._load(wrong_user, object(), "draft"))
    assert draft is None and "own" in problem


def test_native_image_modal_encodes_its_immutable_target_without_mutating_draft(monkeypatch):
    draft = _draft()
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    patch = AsyncMock()
    monkeypatch.setattr(dashboard.cwl_campaign, "patch_draft", patch)
    context = _ctx()
    context.respond_with_modal = AsyncMock()
    asyncio.run(dashboard.edit_image(context, "f" * 32 + "|reminder:1|lazy", mongo=object()))
    assert context.respond_with_modal.await_args.kwargs["custom_id"] == "cwl_image_submit:" + "f" * 32 + "|reminder:1|lazy"
    patch.assert_not_awaited()


def test_preview_uses_service_renderer_and_adds_only_navigation_card(monkeypatch):
    draft = _draft()
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    rendered = [hikari.impl.ContainerComponentBuilder(components=[hikari.impl.TextDisplayComponentBuilder(content="Exact renderer")])]
    renderer = AsyncMock(return_value=rendered)
    monkeypatch.setattr(dashboard.cwl_campaign, "render_message", renderer)
    output = asyncio.run(dashboard.preview(_ctx(), "f" * 32 + "|signup|main", mongo=object()))
    assert output[0] is rendered[0] and len(output) == 2
    assert renderer.await_args.kwargs == {"preview": True}


def test_apply_uses_the_campaign_base_revision_not_a_draft_edit_revision(monkeypatch):
    draft = _draft() | {"revision": 22}
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    monkeypatch.setattr(dashboard.cwl_campaign, "patch_draft", AsyncMock(return_value=draft))
    monkeypatch.setattr(dashboard.cwl_campaign, "new_draft", AsyncMock(return_value=draft))
    apply = AsyncMock(return_value={"message": "Saved"})
    monkeypatch.setattr(dashboard.cwl_campaign, "apply_draft", apply)
    monkeypatch.setattr(dashboard.cwl_campaign, "resolve_schedule", lambda *_args, **_kwargs: [])
    asyncio.run(dashboard.apply_cycle(_ctx(), "f" * 32, mongo=object()))
    assert apply.await_args.kwargs["expected_revision"] == 4


def test_modal_submission_acknowledges_before_reading_or_saving_draft(monkeypatch):
    draft = _draft()
    context = _ctx()
    context.defer = AsyncMock()
    context.interaction.message = None
    context.interaction.components = [
        [SimpleNamespace(custom_id="title", value="New title")],
        [SimpleNamespace(custom_id="body", value="New copy")],
    ]
    context.interaction.edit_initial_response = AsyncMock()

    async def load(_mongo, _token):
        assert context.defer.await_count == 1
        return draft

    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", load)
    monkeypatch.setattr(dashboard.cwl_campaign, "patch_draft", AsyncMock(return_value=draft))
    asyncio.run(dashboard.submit_text(context, "f" * 32 + "|signup|main", mongo=object()))
    assert context.defer.await_count == 1


def test_pause_rebases_only_the_immediately_preceding_draft_revision(monkeypatch):
    context = _ctx()
    monkeypatch.setattr(dashboard.cwl_campaign, "set_paused", AsyncMock(return_value={"revision": 2}))
    monkeypatch.setattr(dashboard, "panel", AsyncMock(return_value=[]))

    async def exercise(base_revision):
        draft = _draft() | {"base_revision": base_revision, "cycle_base_revision": base_revision}
        monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
        patch = AsyncMock(return_value=draft)
        monkeypatch.setattr(dashboard.cwl_campaign, "patch_draft", patch)
        await dashboard.pause(context, "f" * 32, mongo=object())
        return patch.await_args.args[2]

    current = asyncio.run(exercise(1))
    assert current["base_revision"] == current["cycle_base_revision"] == 2
    stale = asyncio.run(exercise(0))
    assert "base_revision" not in stale and "cycle_base_revision" not in stale


def test_rendered_custom_ids_fit_discords_100_character_limit(monkeypatch):
    draft = _draft()
    campaign = draft["campaign"]
    long_key = dashboard._duplicate_key(campaign, "a" * 80)
    campaign["messages"][long_key] = campaign["messages"]["signup"]
    monkeypatch.setattr(dashboard.cwl_campaign, "resolve_schedule", lambda *_args, **_kwargs: [])
    containers = asyncio.run(dashboard.panel(draft, "messages")) + dashboard.message_editor(draft, long_key, "main")
    ids = []
    def walk(value):
        for child in getattr(value, "components", ()):
            custom_id = getattr(child, "custom_id", None)
            if custom_id:
                ids.append(custom_id)
            walk(child)
    for item in containers:
        walk(item)
    assert ids and max(map(len, ids)) <= 100

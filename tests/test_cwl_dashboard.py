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


def _ctx(user_id=1, permissions=hikari.Permissions.ADMINISTRATOR):
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


def test_panel_has_three_workspaces_without_duplicate_settings(monkeypatch):
    monkeypatch.setattr(dashboard.cwl_campaign, "resolve_schedule", lambda *_args, **_kwargs: [])
    built = asyncio.run(dashboard.panel(_draft()))[0].build()[0]
    encoded = str(built)
    for label in ("Overview", "Messages", "Signup Reminders"):
        assert label in encoded
    assert "'label': 'Settings'" not in encoded
    assert "Publish Final Roster" in encoded and "Save posts" not in encoded
    assert "Management › CWL › Overview" in encoded
    tabs = dashboard._tabs("draft", "overview").components
    assert all(button.emoji == dashboard.button_emoji(button.label) for button in tabs)


def test_discord_component_nesting_for_all_dashboard_panels():
    draft = _draft()
    draft["campaign"] = dashboard.cwl_campaign.default_campaign()

    def validate(node, custom_ids):
        if "custom_id" in node:
            assert node["custom_id"] not in custom_ids
            custom_ids.add(node["custom_id"])
        kind = node["type"]
        children = node.get("components", ())
        if kind == 17:
            assert all(child["type"] in {1, 9, 10, 12, 13, 14} for child in children)
        elif kind == 1:
            assert 1 <= len(children) <= 5
            assert all(child["type"] in {2, 3, 5, 6, 7, 8} for child in children)
            if any(child["type"] != 2 for child in children):
                assert len(children) == 1
        for child in children:
            validate(child, custom_ids)

    panels = [asyncio.run(dashboard.panel(draft, tab)) for tab in (
        "overview", "messages", "schedule", "settings", "history",
    )]
    for key in draft["campaign"]["messages"]:
        panels.append(dashboard.schedule_editor(draft, key))
        panels.append(dashboard.monthly_editor(draft, key))
        for audience in dashboard.AUDIENCES:
            panels.append(dashboard.message_editor(draft, key, audience))
            panels.append(dashboard.links_editor(draft, key, audience))
    for components in panels:
        custom_ids = set()
        for component in components:
            validate(component.build()[0], custom_ids)


def test_message_editor_exposes_copy_artwork_buttons_delivery_and_safe_preview():
    built = dashboard.message_editor(_draft(), "signup", "main")[0].build()[0]
    encoded = str(built)
    for label in ("Edit text", "Upload replacement", "Edit buttons", "Select a channel", "Select roles to ping", "Preview", "Post image"):
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
    assert draft is None and "administrators" in problem
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
    monkeypatch.setattr(dashboard, "panel", AsyncMock(return_value=[]))
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
    monkeypatch.setattr(dashboard.cwl_campaign, "load_campaign", AsyncMock(return_value={"campaign": draft["campaign"], "activated": True}))
    monkeypatch.setattr(dashboard.cwl_campaign, "apply_draft", AsyncMock(return_value={"draft": draft}))
    asyncio.run(dashboard.submit_text(context, "f" * 32 + "|signup|main", mongo=object()))
    assert context.defer.await_count == 1


def test_pause_rebases_only_the_immediately_preceding_draft_revision(monkeypatch):
    context = _ctx()
    monkeypatch.setattr(dashboard.cwl_campaign, "load_campaign", AsyncMock(return_value={"campaign": {"paused": False}, "activated": True}))
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


def test_active_selection_panels_use_select_guidance():
    draft = _draft()
    draft['campaign']['messages']['signup']['variants']['main']['buttons'] = [
        {'label': 'Guide', 'url': 'https://example.test/guide'}
    ]
    messages = str(asyncio.run(dashboard.panel(draft, 'messages'))[0].build()[0])
    assert 'Select a Main CWL post' in messages
    panel = asyncio.run(dashboard.panel(draft, 'messages'))[0].build()[0]
    assert any(part.get('content') == '### Main CWL posts' for part in panel['components'])
    buttons = [child for row in panel['components'] for child in row.get('components', ()) if child.get('type') == 2]
    assert any(button.get('label') == 'Main CWL' and button.get('custom_id') == f"cwl_tab:{draft['token']}|messages_main" for button in buttons)
    closing = str(dashboard.closing_editor(draft)[0].build()[0])
    assert '### 2. Signups close\\nSelect a monthly rule for the close date. Or select one date.' in closing
    links = str(dashboard.links_editor(draft, 'signup', 'main')[0].build()[0])
    assert 'Select one to edit it, or add a new link button.' in links
    assert 'Select a button' in links
    assert 'cwl_button_choose:' in links


def test_invalid_selection_guidance_does_not_save(monkeypatch):
    draft = _draft()
    token = draft['token']
    monkeypatch.setattr(dashboard, '_load', AsyncMock(return_value=(draft, None)))
    save = AsyncMock()
    monkeypatch.setattr(dashboard, '_save_campaign', save)
    monkeypatch.setattr(dashboard, 'panel', AsyncMock(side_effect=lambda _draft, _tab, notice, **_kwargs: notice))
    monkeypatch.setattr(dashboard, 'message_editor', lambda _draft, _key, _audience, notice: notice)
    ctx = _ctx()
    ctx.interaction.values = []
    assert asyncio.run(dashboard.reminder_audience(ctx, token, mongo=object())) == 'Select Main CWL, Lazy CWL, or Both.'
    assert asyncio.run(dashboard.choose_message(ctx, token, mongo=object())) == 'Select one message version.'
    assert asyncio.run(dashboard.choose_schedule(ctx, token, mongo=object())) == 'Select one message schedule.'
    assert asyncio.run(dashboard.choose_channel(ctx, f'{token}|signup|main', mongo=object())) == 'Select one text or announcement channel.'
    ctx.interaction.values = ['invalid']
    assert asyncio.run(dashboard.choose_roles(ctx, f'{token}|signup|main', mongo=object())) == 'Select up to ten server roles.'
    save.assert_not_awaited()


def test_monthly_editor_selection_guidance():
    rendered = str(dashboard.monthly_editor(_draft(), 'signup')[0].build()[0])
    assert 'Select one way to set the date each month. Then enter the number and the send time.' in rendered
    assert '**Day of the month:** a number from 1 to 31. A shorter month uses its last day.' in rendered
    assert '**Days before month end:** 0 to 27 days before the last day of the month. 0 means the last day.' in rendered
    assert 'Day of the month' in rendered and 'Days before month end' in rendered


def test_header_uses_approved_monthly_repetition_copy():
    rows = dashboard._header(_draft(), 'overview')
    assert rows[1].content == 'For **October 2026** · **America/New_York**\nRepeats each month until you change it.'


def test_closing_and_monthly_panels_use_complete_approved_copy():
    closing = [node.content for node in dashboard.closing_editor(_draft())[0].components if hasattr(node, 'content')]
    assert '### 2. Signups close\nSelect a monthly rule for the close date. Or select one date.' in closing
    built = dashboard.closing_editor(_draft())[0].build()[0]
    buttons = [child for row in built['components'] for child in row.get('components', ()) if child.get('type') == 2]
    assert any(button.get('label') == 'Day of the month' and button.get('custom_id') == f"cwl_edit_closing_mode:{_draft()['token']}|day" for button in buttons)
    monthly = [node.content for node in dashboard.monthly_editor(_draft(), 'signup')[0].components if hasattr(node, 'content')]
    assert ('### Monthly · Signups open\nSelect one way to set the date each month. Then enter the number and the send time.\n'
            '**Day of the month:** a number from 1 to 31. A shorter month uses its last day.\n'
            '**Days before month end:** 0 to 27 days before the last day of the month. 0 means the last day.') in monthly


def test_message_editor_copy_labels_name_other_pool_without_changing_callbacks():
    draft = _draft()
    for audience, expected_copy, expected_image in (
        ('main', 'Copy text to Lazy', 'Use image for Lazy'),
        ('lazy', 'Copy text to Main', 'Use image for Main'),
    ):
        built = dashboard.message_editor(draft, 'signup', audience)[0].build()[0]
        buttons = [button for row in built['components'] for button in row.get('components', ())
                   if button.get('type') == 2]
        by_id = {button['custom_id']: button['label'] for button in buttons if 'custom_id' in button}
        ref = f"{draft['token']}|signup|{audience}"
        assert by_id[f'cwl_copy_text:{ref}'] == expected_copy
        assert by_id[f'cwl_share_image:{ref}'] == expected_image


def test_stale_cwl_controls_show_exact_recovery_without_loading_or_saving(monkeypatch):
    load = AsyncMock()
    save = AsyncMock()
    monkeypatch.setattr(dashboard, '_load', load)
    monkeypatch.setattr(dashboard, '_save_campaign', save)
    monkeypatch.setattr(dashboard, 'error_panel', lambda text: text)
    ctx = _ctx()
    editor_text = 'This editor panel is old. Open it again from `/manage`.'
    for action in (dashboard.edit_links, dashboard.choose_button, dashboard.choose_channel,
                   dashboard.choose_roles, dashboard.toggle, dashboard.copy_text,
                   dashboard.duplicate_message, dashboard.share_image, dashboard.reset_image,
                   dashboard.queue_manual, dashboard.preview, dashboard.open_message):
        assert asyncio.run(action(ctx, '', mongo=object())) == editor_text
    for action in (dashboard.tab, dashboard.skip):
        assert asyncio.run(action(ctx, '', mongo=object())) == 'This dashboard panel is old. Open it again from `/manage`.'
    assert asyncio.run(dashboard.remove_button(ctx, '', mongo=object())) == 'That action is old. Use the controls in this panel.'
    load.assert_not_awaited()
    save.assert_not_awaited()


def test_stale_cwl_modal_controls_show_exact_recovery_without_loading_or_saving(monkeypatch):
    load = AsyncMock()
    save = AsyncMock()
    modal_source = AsyncMock()
    monkeypatch.setattr(dashboard, '_load', load)
    monkeypatch.setattr(dashboard, '_save_campaign', save)
    monkeypatch.setattr(dashboard, '_modal_source', modal_source)
    monkeypatch.setattr(dashboard, '_ack_modal', AsyncMock())
    monkeypatch.setattr(dashboard, 'error_panel', lambda text: text)
    ctx = _ctx()
    ctx.interaction.edit_initial_response = AsyncMock()
    expected = 'This editor panel is old. Open it again from `/manage`.'
    for action in (dashboard.edit_image, dashboard.submit_button, dashboard.edit_schedule, dashboard.submit_schedule, dashboard.submit_sequence):
        asyncio.run(action(ctx, '', mongo=object()))
        modal_source.assert_awaited_with(ctx, expected)
        modal_source.reset_mock()
    asyncio.run(dashboard._button_modal(ctx, '', object(), index=None))
    modal_source.assert_awaited_once_with(ctx, expected)
    modal_source.reset_mock()
    asyncio.run(dashboard._submit_message(ctx, '', object(), 'text'))
    modal_source.assert_awaited_once_with(ctx, expected)
    asyncio.run(dashboard.submit_image(ctx, '', mongo=object(), media=object()))
    ctx.interaction.edit_initial_response.assert_awaited_once_with(components=expected, **dashboard.NO_MENTIONS)
    load.assert_not_awaited()
    save.assert_not_awaited()


def test_text_modal_invalid_reference_acknowledges_and_shows_recovery(monkeypatch):
    load = AsyncMock()
    monkeypatch.setattr(dashboard, '_load', load)
    monkeypatch.setattr(dashboard, 'error_panel', lambda text: text)
    ctx = _ctx()
    ctx.defer = AsyncMock()
    ctx.respond_with_modal = AsyncMock()
    ctx.interaction.edit_initial_response = AsyncMock()
    asyncio.run(dashboard.edit_text(ctx, '', mongo=object()))
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    ctx.interaction.edit_initial_response.assert_awaited_once_with(
        components='This editor panel is old. Open it again from `/manage`.',
        **dashboard.NO_MENTIONS,
    )
    ctx.respond_with_modal.assert_not_awaited()
    load.assert_not_awaited()


def test_settings_modal_invalid_reference_acknowledges_once_without_loading(monkeypatch):
    load = AsyncMock()
    save = AsyncMock()
    monkeypatch.setattr(dashboard, '_load', load)
    monkeypatch.setattr(dashboard, '_save_timing', save)
    monkeypatch.setattr(dashboard, 'error_panel', lambda text: text)
    ctx = _ctx()
    ctx.defer = AsyncMock()
    ctx.respond_with_modal = AsyncMock()
    ctx.interaction.edit_initial_response = AsyncMock()
    asyncio.run(dashboard.submit_settings(ctx, 'invalid|too|many', mongo=object()))
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    ctx.interaction.edit_initial_response.assert_awaited_once_with(
        components='This editor panel is old. Open it again from `/manage`.',
        **dashboard.NO_MENTIONS,
    )
    ctx.respond_with_modal.assert_not_awaited()
    load.assert_not_awaited()
    save.assert_not_awaited()


def test_schedule_mode_displays_menu_label_without_changing_selection_or_draft(monkeypatch):
    import copy

    save = AsyncMock()
    monkeypatch.setattr(dashboard, '_save_campaign', save)
    choices = [('monthly', 'Monthly'), ('after_open', 'After signups open'),
               ('before_close', 'Before signups close'), ('specific', 'One-time date'),
               ('legacy_chain', 'After previous reminder'), ('manual', 'Manual')]
    for mode, label in choices + [('unexpected_mode', 'unexpected_mode')]:
        draft = _draft()
        draft['campaign']['messages']['signup']['schedule'] = {'mode': mode}
        before = copy.deepcopy(draft)
        panel = dashboard.schedule_editor(draft, 'signup')[0].build()[0]
        texts = [part['content'] for part in panel['components'] if 'content' in part]
        descriptions = {'monthly': 'Monthly · day ? at 00:00',
                        'after_open': '0 minutes after signups open',
                        'before_close': '0 minutes before signup close',
                        'specific': 'One-time date · not set',
                        'legacy_chain': 'After previous · 0 minutes',
                        'manual': 'Manual', 'unexpected_mode': 'Manual'}
        assert f'### Signups open\n**{descriptions[mode]}**\nMode: {label}' in texts
        menus = [child for row in panel['components'] for child in row.get('components', ())
                 if child.get('custom_id', '').startswith('cwl_schedule_mode:')]
        assert len(menus) == 1
        assert menus[0]['custom_id'] == f"cwl_schedule_mode:{draft['token']}|signup"
        assert [(o['value'], o['label']) for o in menus[0]['options']] == choices
        assert [o['value'] for o in menus[0]['options'] if o.get('default')] == ([mode] if mode != 'unexpected_mode' else [])
        assert draft == before
    save.assert_not_awaited()


def test_more_options_and_published_roster_use_exact_approved_copy(monkeypatch):
    draft = _draft()
    draft['campaign'] = dashboard.cwl_campaign.default_campaign()
    monkeypatch.setattr(dashboard, '_load', AsyncMock(return_value=(draft, None)))
    advanced = asyncio.run(dashboard.advanced(_ctx(), draft['token'], mongo=object()))[0].build()[0]
    assert any(part.get('content') == '### More options\nChange the timing of one message. Or remove your edits and load the saved settings.' for part in advanced['components'])
    live = {'campaign': draft['campaign'], 'sent_occurrences': [
        dashboard.cwl_campaign.occurrence_id('2026-10', 'roster', audience) for audience in ('main', 'lazy')
    ]}
    monkeypatch.setattr(dashboard.cwl_campaign, 'load_campaign', AsyncMock(return_value=live))
    publication = asyncio.run(dashboard.publication_panel(draft, object()))[0].build()[0]
    assert any(part.get('content') == '## Publish Final Roster\nYour saved announcements and spreadsheet links are used.' for part in publication['components'])
    buttons = [child for row in publication['components'] for child in row.get('components', ()) if child.get('type') == 2]
    assert any(button.get('label') == 'Already published' and button.get('disabled') for button in buttons)


def test_posting_channel_save_keeps_destination_and_exact_notice(monkeypatch):
    draft = _draft()
    monkeypatch.setattr(dashboard, '_load', AsyncMock(return_value=(draft, None)))
    save = AsyncMock(return_value=draft)
    monkeypatch.setattr(dashboard, '_save_campaign', save)
    monkeypatch.setattr(dashboard, 'message_editor', lambda _draft, _key, _audience, notice: notice)
    ctx = _ctx()
    ctx.interaction.values = ['123456789']
    result = asyncio.run(dashboard.choose_channel(ctx, f"{draft['token']}|signup|main", mongo=object()))
    assert result == 'Posting channel updated.'
    save.assert_awaited_once()
    campaign = save.await_args.args[2]
    assert campaign['messages']['signup']['variants']['main']['destination_channel_id'] == 123456789
    assert campaign['messages']['signup']['variants']['lazy'] == draft['campaign']['messages']['signup']['variants']['lazy']

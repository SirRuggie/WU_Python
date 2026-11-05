from datetime import datetime, timedelta, timezone
import asyncio
from types import SimpleNamespace

import hikari

from hikari.impl import ContainerComponentBuilder as Container
from extensions.commands import lazycwl_dashboard as dashboard

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
def _clan(i): return {"tag": f"#A{i}", "name": f"Clan {i}"}
def _doc(i=1): return {"_id": f"saved-{i}", "clan_tag": f"#A{i}", "clan_name": f"Clan {i}", "status": "active", "saved_at": NOW, "expires_at": NOW + timedelta(days=7), "players": [{"tag": "#P1", "name": "Player"}], "reminders": {"enabled": False}}
def _nodes(components):
    for container in components:
        assert isinstance(container, Container)
        for component in container.components:
            yield component
            yield from getattr(component, "components", [])
def _text(components): return "\n".join(getattr(node, "content", "") for node in _nodes(components))

def test_rosters_command_opens_fwa_dashboard_directly(monkeypatch):
    seen = []
    async def home(mongo, selected_tag=None, note=None, *, token, tab="overview"):
        seen.append(dashboard._sessions[token]["section"])
        return ["dashboard"]
    monkeypatch.setattr(dashboard, "build_home", home)

    class Ctx:
        member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
        user = SimpleNamespace(id=44)
        interaction = SimpleNamespace(guild_id=55)
        async def defer(self, **kwargs): pass
    ctx = Ctx()
    async def edit_initial_response(**kwargs):
        assert kwargs["components"] == ["dashboard"]
    ctx.interaction.edit_initial_response = edit_initial_response
    asyncio.run(dashboard.open_dashboard(ctx, object()))
    assert seen == ["FWA"]


def test_dashboard_starts_without_a_clan_or_implicit_bulk_scope():
    rendered = dashboard.render_home([_doc()], [_clan(1)], None, NOW, token="preview")
    assert "Select a clan" in _text(rendered)
    assert "Captured:" not in _text(rendered)

def test_overview_has_explicit_capture_facts_and_no_internal_list_id():
    rendered = dashboard.render_home([_doc()], [_clan(1)], "#A1", NOW, {"#A1": 1}, token="preview")
    text = _text(rendered)
    assert all(label in text for label in ("Captured:", "Players captured:", "Players away:", "Status:", "Expires:"))
    assert "saved-1" not in text

def test_selector_is_limited_to_24_clans_plus_explicit_bulk_option():
    rendered = dashboard.render_home([], [_clan(i) for i in range(30)], None, NOW, token="preview")
    select = next(node for node in _nodes(rendered) if hasattr(node, "options"))
    assert len(select.options) == 25 and select.options[0].value == "ALL"


def test_selector_exposes_clans_on_later_pages_without_exceeding_discord_limit():
    token = dashboard._session(44, 55)
    clans = [_clan(i) for i in range(30)]
    first = dashboard.render_home([], clans, None, NOW, token=token)
    paging = [node for node in _nodes(first) if getattr(node, "label", "").startswith(("Previous clans", "Next clans"))]
    assert [node.label for node in paging] == ["Previous clans", "Next clans"]
    assert all(node.emoji == dashboard.button_emoji(node.label) for node in paging)
    assert any("Page 1 of 2" in getattr(node, "content", "") for node in _nodes(first))
    dashboard._sessions[token]["clan_page"] = 1
    second = dashboard.render_home([], clans, None, NOW, token=token)
    select = next(node for node in _nodes(second) if hasattr(node, "options"))
    assert [option.value for option in select.options] == ["ALL", "#A24", "#A25", "#A26", "#A27", "#A28", "#A29"]

def test_rendered_component_ids_are_short_and_component_count_is_safe():
    rendered = dashboard.render_home([_doc(i) for i in range(1, 25)], [_clan(i) for i in range(1, 25)], "ALL", NOW, token="preview", tab="reminders")
    nodes = list(_nodes(rendered))
    assert len(nodes) < 40
    assert all(len(node.custom_id) <= 100 for node in nodes if getattr(node, "custom_id", None))

def test_review_scope_uses_a_short_server_side_nonce_and_is_one_shot():
    token = dashboard._session(1, 1)
    nonce = dashboard._bind(token, "ALL", [_doc(1), _doc(2)], operation="send")
    assert "saved-1" not in nonce and "saved-2" not in nonce
    assert dashboard._parse_bound(token, nonce)["operation"] == "send"
    assert dashboard._parse_bound(token, nonce) is None

def test_reminder_controls_are_explicit_enable_and_disable():
    rendered = dashboard.render_home([_doc()], [_clan(1)], "#A1", NOW, token="preview", tab="reminders")
    labels = [node.label for node in _nodes(rendered) if getattr(node, "label", None)]
    assert "Start Return Pings" in labels and "Pause Return Pings" in labels


class _Ctx:
    def __init__(self, token, values=None):
        self.user = SimpleNamespace(id=44)
        self.member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
        self.interaction = SimpleNamespace(guild_id=55, values=values or [], components=[])
        self.token = token
        self.responses = []
    async def respond(self, message, ephemeral=False): self.responses.append((message, ephemeral))


def _bound_session(operation, docs, *, capture_tags=None):
    token = dashboard._session(44, 55)
    nonce = dashboard._bind(token, "ALL", docs, operation=operation)
    if capture_tags is not None:
        dashboard._sessions[token]["pending"][nonce]["capture_tags"] = capture_tags
    return token, nonce, _Ctx(token)


def test_capture_confirmation_saves_each_reviewed_single_or_bulk_clan_once(monkeypatch):
    calls, screens = [], []
    async def save(tag, saved_by, *, section):
        assert section == "FWA"
        calls.append((tag, saved_by)); return {"ok": True, "player_count": 2}
    async def home(mongo, selected_tag=None, note=None, **kwargs):
        screens.append((selected_tag, note)); return ["home"]
    monkeypatch.setattr(dashboard.service, "save_list", save)
    monkeypatch.setattr(dashboard, "build_home", home)
    async def clans(mongo, token): return [_clan(1), _clan(2)]
    monkeypatch.setattr(dashboard, "_clans", clans)
    token, nonce, ctx = _bound_session("capture", [], capture_tags=["#A1", "#A2"])
    result = asyncio.run(dashboard.handle_capture_yes(ctx=ctx, action_id=f"{token}|{nonce}", mongo=object()))
    assert result == ["home"]
    assert calls == [("#A1", 44), ("#A2", 44)]
    assert screens[0][0] == "ALL" and "2" in screens[0][1]
    # A confirmation nonce cannot capture a second time.
    asyncio.run(dashboard.handle_capture_yes(ctx=ctx, action_id=f"{token}|{nonce}", mongo=object()))
    assert len(calls) == 2


def test_capture_reports_partial_failure_without_claiming_success(monkeypatch):
    async def save(tag, saved_by, *, section): return {"ok": tag == "#A1", "error": "already captured"}
    async def home(mongo, selected_tag=None, note=None, **kwargs): return [note]
    monkeypatch.setattr(dashboard.service, "save_list", save)
    monkeypatch.setattr(dashboard, "build_home", home)
    async def clans(mongo, token): return [_clan(1), _clan(2)]
    monkeypatch.setattr(dashboard, "_clans", clans)
    token, nonce, ctx = _bound_session("capture", [], capture_tags=["#A1", "#A2"])
    result = asyncio.run(dashboard.handle_capture_yes(ctx=ctx, action_id=f"{token}|{nonce}", mongo=object()))
    assert result[0] == "Saved lists captured: 1. 1 could not be captured. Refresh the page to check."


def test_apply_confirmation_passes_raw_expected_list_ids_and_keeps_per_clan_results(monkeypatch):
    docs = [_doc(1), _doc(2)]
    docs[0]["_id"] = object(); docs[1]["_id"] = object()
    token, nonce, ctx = _bound_session("send", docs)
    sent = []
    async def active(mongo, *, section):
        assert section == "FWA"
        return docs
    async def remind(tag, *, expected_list_id, section, expected_channel=None):
        assert section == "FWA"
        sent.append((tag, expected_list_id)); return {"ok": tag == "#A1", "error": "failed"}
    monkeypatch.setattr(dashboard.store, "list_active", active)
    monkeypatch.setattr(dashboard.service, "remind_now", remind)
    from unittest.mock import AsyncMock
    monkeypatch.setattr(dashboard, "build_home", AsyncMock(return_value=[]))
    result = asyncio.run(dashboard._apply_bound(object(), token, nonce, "send", ctx))
    assert sent == [("#A1", docs[0]["_id"]), ("#A2", docs[1]["_id"])]
    assert "Needs attention" in _text(result) and "Clan 2" in _text(result)


def test_enable_and_disable_reviews_remain_explicit_and_use_selected_frequency(monkeypatch):
    docs = [_doc()]
    async def active(mongo, *, section): return docs
    monkeypatch.setattr(dashboard.store, "list_active", active)
    token = dashboard._session(44, 55)
    rendered = asyncio.run(dashboard._review(object(), token, "#A1", "enable", minutes=60))
    assert "Frequency: every 60 minutes" in _text(rendered)
    assert "Enable reminders?" in _text(rendered)
    rendered = asyncio.run(dashboard._review(object(), token, "#A1", "disable"))
    assert "Disable reminders?" in _text(rendered)


def test_player_page_clamps_and_marks_away_status(monkeypatch):
    doc = _doc(); doc["players"] = [{"tag": f"#P{i}", "name": f"P{i}"} for i in range(50)]
    async def active(mongo, tag, *, section): return doc
    async def active_lists(mongo, *, section): return [doc]
    async def clans(mongo): return [_clan(1)]
    async def away(saved): return [doc["players"][0]]
    monkeypatch.setattr(dashboard.store, "get_active", active)
    monkeypatch.setattr(dashboard.store, "list_active", active_lists)
    monkeypatch.setattr(dashboard, "_fwa_clans", clans)
    monkeypatch.setattr(dashboard.service, "away_players", away)
    token = dashboard._session(44, 55)
    rendered = asyncio.run(dashboard._player_page(object(), token, "#A1", 999))
    text = _text(rendered)
    assert "page 3 of 3" in text and "Returned" in text


def test_player_add_button_uses_a_live_add_nonce(monkeypatch):
    """The player header must bind the add action to the displayed saved list."""
    doc = _doc()
    async def active(mongo, tag, *, section): return doc
    async def active_lists(mongo, *, section): return [doc]
    async def clans(mongo): return [_clan(1)]
    async def away(saved): return []
    monkeypatch.setattr(dashboard.store, "get_active", active)
    monkeypatch.setattr(dashboard.store, "list_active", active_lists)
    monkeypatch.setattr(dashboard, "_fwa_clans", clans)
    monkeypatch.setattr(dashboard.service, "away_players", away)
    token = dashboard._session(44, 55)
    rendered = asyncio.run(dashboard._player_page(object(), token, "#A1", 0))
    add = next(node for node in _nodes(rendered) if getattr(node, "custom_id", "").startswith("lazycwl_add:"))
    _, payload = add.custom_id.split(":", 1)
    received_token, nonce = dashboard._split(payload)
    bound = dashboard._sessions[received_token]["pending"][nonce]
    assert bound["operation"] == "add" and bound["ids"] == [doc["_id"]]


def test_clan_dropdown_shows_saved_and_expiry_dates_in_plain_text():
    rendered = dashboard.render_home([_doc()], [_clan(1), _clan(2)], "ALL", NOW, token="preview")
    select = next(node for node in _nodes(rendered) if hasattr(node, "options"))
    descriptions = {option.value: option.description for option in select.options}
    assert descriptions["#A1"] == "Saved 12 Sep 2026 · expires 19 Sep 2026 (UTC)"
    assert descriptions["#A2"] == "No saved roster"
    assert all(len(description) <= 100 for description in descriptions.values())


def test_clan_dropdown_normalizes_dates_to_utc():
    doc = _doc()
    doc["saved_at"] = datetime(2026, 9, 11, 23, tzinfo=timezone(timedelta(hours=-4)))
    doc["expires_at"] = datetime(2026, 9, 16)
    assert dashboard._roster_description(doc) == "Saved 12 Sep 2026 · expires 16 Sep 2026 (UTC)"


def test_main_rendering_is_scoped_and_has_manual_reminders_only():
    token = dashboard._session(44, 55)
    dashboard._sessions[token]["section"] = "MAIN"
    fwa, main = _doc(1), _doc(2)
    main["section"] = "MAIN"
    rendered = dashboard.render_home([fwa, main], [_clan(1), _clan(2)], "#A2", NOW,
                                     {"#A2": 3}, token=token, tab="reminders")
    text = _text(rendered)
    labels = [node.label for node in _nodes(rendered) if getattr(node, "label", None)]
    assert "CWL Return Pings · Main · Overview" in text
    assert "Clan 2" in text and "Clan 1" not in text
    assert "Players away:" not in text and "Return reminders" not in labels
    assert "Send Ping Now" in labels
    assert "Start Return Pings" not in labels and "Pause Return Pings" not in labels


def test_main_send_review_and_confirmation_are_section_scoped(monkeypatch):
    token = dashboard._session(44, 55)
    dashboard._sessions[token]["section"] = "MAIN"
    doc = _doc()
    doc["section"] = "MAIN"
    async def active(mongo, *, section):
        assert section == "MAIN"
        return [doc]
    async def recipients(saved):
        return [{"tag": "#P1", "discord_id": 123}]
    calls = []
    async def remind(tag, *, expected_list_id, section, expected_channel=None):
        calls.append((tag, expected_list_id, section))
        return {"ok": True, "sent": True}
    async def home(mongo, selected_tag=None, note=None, **kwargs):
        assert kwargs["tab"] == "overview"
        return [note]
    monkeypatch.setattr(dashboard.store, "list_active", active)
    monkeypatch.setattr(dashboard.service, "reminder_recipients", recipients)
    monkeypatch.setattr(dashboard.service, "remind_now", remind)
    monkeypatch.setattr(dashboard, "build_home", home)

    review = asyncio.run(dashboard._review(object(), token, "#A1", "send"))
    assert f"Destination: <#{dashboard.service.MAIN_CWL_CHANNEL}>" in _text(review)
    assert "1 linked Discord accounts" in _text(review)
    assert "The recipients are checked again when you confirm." in _text(review)
    nonce = next(iter(dashboard._sessions[token]["pending"]))
    result = asyncio.run(dashboard._apply_bound(object(), token, nonce, "send", _Ctx(token)))
    assert calls == [("#A1", doc["_id"], "MAIN")]
    assert "Ping sent for 1 clans" in result[0]


def test_switching_section_rotates_token_and_invalidates_old_confirmation(monkeypatch):
    token = dashboard._session(44, 55)
    dashboard._sessions[token]["section"] = "FWA"
    nonce = dashboard._bind(token, "#A1", [_doc()], operation="close")
    seen = []
    async def home(mongo, *args, token=None, **kwargs):
        seen.append(token)
        return ["home"]
    monkeypatch.setattr(dashboard, "build_home", home)
    ctx = _Ctx(token)
    result = asyncio.run(dashboard.handle_section(ctx=ctx, action_id=f"{token}|MAIN", mongo=object()))
    assert result == ["home"]
    assert token not in dashboard._sessions and seen[0] != token
    assert dashboard._parse_bound(token, nonce) is None
    assert dashboard._sessions[seen[0]]["section"] == "MAIN"


def test_replace_confirmation_calls_section_scoped_service_with_reviewed_id(monkeypatch):
    doc = _doc()
    doc["_id"] = object()
    token = dashboard._session(44, 55)
    dashboard._sessions[token]["section"] = "MAIN"
    nonce = dashboard._bind(token, "#A1", [doc], operation="replace")
    calls = []
    async def active(mongo, *, section):
        assert section == "MAIN"
        return [doc]
    async def replace_list(tag, *, saved_by, expected_list_id, section):
        calls.append((tag, saved_by, expected_list_id, section))
        return {"ok": True}
    async def home(*args, **kwargs): return []
    monkeypatch.setattr(dashboard.store, "list_active", active)
    monkeypatch.setattr(dashboard.service, "replace_list", replace_list)
    monkeypatch.setattr(dashboard, "build_home", home)
    asyncio.run(dashboard._apply_bound(object(), token, nonce, "replace", _Ctx(token)))
    assert calls == [("#A1", 44, doc["_id"], "MAIN")]


def test_capture_confirmation_skips_clan_that_left_the_reviewed_section(monkeypatch):
    calls = []
    async def save(tag, saved_by, *, section): calls.append((tag, section)); return {"ok": True}
    async def home(*args, note=None, **kwargs): return [note]
    async def clans(mongo, token): return [_clan(1)]
    monkeypatch.setattr(dashboard.service, "save_list", save)
    monkeypatch.setattr(dashboard, "build_home", home)
    monkeypatch.setattr(dashboard, "_clans", clans)
    token, nonce, ctx = _bound_session("capture", [], capture_tags=["#A1", "#A2"])
    result = asyncio.run(dashboard.handle_capture_yes(ctx=ctx, action_id=f"{token}|{nonce}", mongo=object()))
    assert calls == []
    assert "Clan assignments changed" in _text(result)


def test_send_confirmation_rejects_changed_destination(monkeypatch):
    from unittest.mock import AsyncMock
    doc = _doc()
    token, nonce, ctx = _bound_session("send", [doc])
    monkeypatch.setattr(dashboard, "_active", AsyncMock(return_value=[doc]))
    monkeypatch.setattr(dashboard.service, "effective_reminder_channel", AsyncMock(return_value=999))
    send = AsyncMock()
    monkeypatch.setattr(dashboard.service, "remind_now", send)
    result = asyncio.run(dashboard._apply_bound(object(), token, nonce, "send", ctx))
    assert "Return channel changed" in _text(result)
    send.assert_not_awaited()


def test_invalid_reminder_frequency_does_not_open_review(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(dashboard, '_handler_ok', AsyncMock(return_value=('token', '#CLAN')))
    review = AsyncMock()
    monkeypatch.setattr(dashboard, '_review', review)
    ctx = SimpleNamespace(interaction=SimpleNamespace(values=['invalid']))
    result = asyncio.run(dashboard.handle_frequency(ctx=ctx, action_id='token|#CLAN', mongo=object()))
    assert 'Select a frequency' in _text(result)
    assert 'Select one of the offered reminder frequencies.' in _text(result)
    review.assert_not_awaited()


def test_replace_review_exactly_explains_preserving_old_roster(monkeypatch):
    from unittest.mock import AsyncMock
    token = dashboard._session(44, 55)
    monkeypatch.setattr(dashboard, '_active', AsyncMock(return_value=[_doc()]))
    review = asyncio.run(dashboard._review(object(), token, '#A1', 'replace'))
    assert 'If the new roster does not save, the current roster stays.' in _text(review).splitlines()
    assert any(getattr(node, 'label', '') == 'Confirm' for node in _nodes(review))


def test_expired_capture_exactly_requests_new_review(monkeypatch):
    from unittest.mock import AsyncMock
    token = dashboard._session(44, 55)
    monkeypatch.setattr(dashboard, '_handler_ok', AsyncMock(return_value=(token, 'old')))
    save = AsyncMock()
    monkeypatch.setattr(dashboard.service, 'save_list', save)
    result = asyncio.run(dashboard.handle_capture_yes(ctx=_Ctx(token), action_id='ignored', mongo=object()))
    assert 'Refresh the page. Then review the capture again.' in _text(result).splitlines()
    save.assert_not_awaited()


def test_uncertain_reminder_result_uses_exact_guidance_without_retry(monkeypatch):
    from unittest.mock import AsyncMock
    doc = _doc()
    token, nonce, ctx = _bound_session('send', [doc])
    monkeypatch.setattr(dashboard, '_active', AsyncMock(return_value=[doc]))
    monkeypatch.setattr(dashboard.service, 'effective_reminder_channel', AsyncMock(return_value=dashboard._sessions[token]['pending'][nonce]['destination']))
    monkeypatch.setattr(dashboard.service, 'remind_now', AsyncMock(side_effect=OSError('offline')))
    monkeypatch.setattr(dashboard, 'build_home', AsyncMock(return_value=[]))
    result = asyncio.run(dashboard._apply_bound(object(), token, nonce, 'send', ctx))
    assert '• Clan 1: Could not confirm the result. Check Discord and the saved list before you try again.' in _text(result).splitlines()
    assert not any(getattr(node, 'label', '') == 'Retry Failed Clans' for node in _nodes(result))


def test_frequency_copy_keeps_enabled_and_paused_states(monkeypatch):
    from unittest.mock import AsyncMock
    token = dashboard._session(44, 55)
    docs = [_doc(1), _doc(2)]
    docs[0]['reminders']['enabled'] = True
    monkeypatch.setattr(dashboard, '_handler_ok', AsyncMock(return_value=(token, 'ALL')))
    monkeypatch.setattr(dashboard, '_active', AsyncMock(return_value=docs))
    save = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(dashboard.service, 'set_reminders', save)
    home = AsyncMock(return_value=['home'])
    monkeypatch.setattr(dashboard, 'build_home', home)
    ctx = _Ctx(token, ['60'])
    assert asyncio.run(dashboard.handle_frequency_save(ctx=ctx, action_id='ignored', mongo=object())) == ['home']
    assert [call.args[:3] for call in save.await_args_list] == [('#A1', True, 60), ('#A2', False, 60)]
    assert [call.kwargs['expected_list_id'] for call in save.await_args_list] == ['saved-1', 'saved-2']
    assert home.await_args.args[2] == 'Frequency saved. Running pings are updated. Paused pings stay paused.'


def test_bulk_overview_names_save_action_and_existing_rosters():
    doc = _doc()
    doc['legacy_snapshot_id'] = 'old-roster'
    rendered = dashboard.render_home([doc], [_clan(1), _clan(2)], 'ALL', NOW, {'#A1': 1}, token='preview')
    summary = next(node.content for node in _nodes(rendered)
                   if getattr(node, 'content', '').startswith('### All FWA clans'))
    assert summary == (
        '### All FWA clans\nSaved rosters: 1 · **Clans to capture: 1.**\n'
        'Save Current Members saves the current members of the clans without a roster. Existing rosters are kept.\n'
        'Your previous saved rosters were carried over to this dashboard.\n'
        '**Need a fresh roster?** Select that clan and select **Replace Saved Members** to review the change.\n'
        'Players away: 1'
    )
    assert any(getattr(node, 'label', '') == 'Save Current Members (1 clans)' for node in _nodes(rendered))


def test_unselected_roster_views_preserve_existing_scope_copy():
    empty = dashboard.render_home([], [_clan(1)], None, NOW, token='preview')
    assert '### Select a clan\nSelect one clan above to inspect its saved-list status.' in [n.content for n in _nodes(empty) if hasattr(n, 'content')]
    players = dashboard.render_home([], [_clan(1)], None, NOW, token='preview', tab='players')
    assert 'Select one clan with a saved list to view or edit players.' in [n.content for n in _nodes(players) if hasattr(n, 'content')]
    reminders = dashboard.render_home([], [_clan(1)], None, NOW, token='preview', tab='reminders')
    assert 'No saved lists are selected.' in [n.content for n in _nodes(reminders) if hasattr(n, 'content')]


def test_capture_review_preserves_scope_and_never_saves_before_confirmation(monkeypatch):
    from unittest.mock import AsyncMock
    token = dashboard._session(44, 55)
    active = AsyncMock(return_value=[])
    monkeypatch.setattr(dashboard, '_active', active)
    monkeypatch.setattr(dashboard, '_clans', AsyncMock(return_value=[_clan(1)]))
    save = AsyncMock()
    monkeypatch.setattr(dashboard.service, 'save_list', save)
    review = asyncio.run(dashboard._review(object(), token, '#A1', 'capture'))
    assert 'This creates saved lists from members currently in those clans.' in _text(review).splitlines()
    assert any(getattr(node, 'label', '') == 'Confirm' for node in _nodes(review))
    active.return_value = [_doc()]
    unavailable = asyncio.run(dashboard._review(object(), token, '#A1', 'capture'))
    assert 'Select a clan without an active saved list.' in _text(unavailable).splitlines()
    active.return_value = []
    missing = asyncio.run(dashboard._review(object(), token, '#A1', 'send'))
    assert 'There are no active saved lists in this scope.' in _text(missing).splitlines()
    save.assert_not_awaited()


def test_expired_player_roster_is_not_edited(monkeypatch):
    from unittest.mock import AsyncMock
    token = dashboard._session(44, 55)
    monkeypatch.setattr(dashboard.store, 'get_active', AsyncMock(return_value=None))
    home = AsyncMock(return_value=['home'])
    monkeypatch.setattr(dashboard, 'build_home', home)
    assert asyncio.run(dashboard._player_page(object(), token, '#A1', 0)) == ['home']
    assert home.await_args.args[2] == 'The saved list is no longer active.'


def test_remove_roster_review_and_stale_confirmation_keep_list_identity(monkeypatch):
    from unittest.mock import AsyncMock
    token = dashboard._session(44, 55)
    ctx = _Ctx(token, ['#P1'])
    monkeypatch.setattr(dashboard, '_handler_ok', AsyncMock(return_value=(token, '#A1,0')))
    monkeypatch.setattr(dashboard.store, 'get_active', AsyncMock(return_value=_doc()))
    remove = AsyncMock(side_effect=dashboard.store.StaleListError())
    monkeypatch.setattr(dashboard.store, 'remove_players', remove)
    review = asyncio.run(dashboard.handle_remove_pick(ctx=ctx, action_id='ignored', mongo=object()))
    assert 'They will be removed from this saved list.' in _text(review).splitlines()
    remove.assert_not_awaited()
    nonce = next(iter(dashboard._sessions[token]['pending']))
    monkeypatch.setattr(dashboard, '_handler_ok', AsyncMock(return_value=(token, nonce)))
    page = AsyncMock(return_value=['stale'])
    monkeypatch.setattr(dashboard, '_player_page', page)
    assert asyncio.run(dashboard.handle_remove_yes(ctx=ctx, action_id='ignored', mongo=object())) == ['stale']
    assert remove.await_args.kwargs['expected_list_id'] == 'saved-1'
    assert page.await_args.args[4] == 'The saved list changed. Refresh and try again.'


def test_expired_roster_actions_give_exact_recovery_without_writes(monkeypatch):
    from unittest.mock import AsyncMock
    ctx = _Ctx('expired')
    assert not asyncio.run(dashboard._allow(ctx, 'expired'))
    assert ctx.responses == [('This dashboard has expired. Run /manage. Then select CWL Return Pings.', True)]
    monkeypatch.setattr(dashboard, '_handler_ok', AsyncMock(return_value=(None, None)))
    save = AsyncMock()
    remove = AsyncMock()
    monkeypatch.setattr(dashboard.service, 'save_list', save)
    monkeypatch.setattr(dashboard.store, 'remove_players', remove)
    for action in (dashboard.handle_section, dashboard.handle_clans_page, dashboard.handle_pick,
                   dashboard.handle_cancel, dashboard.handle_tab, dashboard.handle_home,
                   dashboard.handle_capture, dashboard.handle_capture_yes, dashboard.handle_replace,
                   dashboard.handle_close, dashboard.handle_disable, dashboard.handle_enable,
                   dashboard.handle_send_yes, dashboard.handle_replace_yes, dashboard.handle_close_yes,
                   dashboard.handle_enable_yes, dashboard.handle_disable_yes, dashboard.handle_players_page,
                   dashboard.handle_remove, dashboard.handle_remove_pick, dashboard.handle_remove_yes):
        result = asyncio.run(action(ctx=ctx, action_id='expired', mongo=object()))
        assert 'Run /manage. Then select CWL Return Pings.' in _text(result).splitlines()
    save.assert_not_awaited()
    remove.assert_not_awaited()

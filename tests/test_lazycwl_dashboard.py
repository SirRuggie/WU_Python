import ast
import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import hikari
from hikari.impl import (
    ContainerComponentBuilder as Container,
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
)

from extensions.commands import lazycwl_dashboard as dashboard
from tests.test_lazy_cwl_store import _Collection

MODULE_PATH = Path(__file__).resolve().parent.parent / "extensions" / "commands" / "lazycwl_dashboard.py"
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

BANNED_WORDS = {
    "snapshot", "ping", "sync", "fwa", "cwl", "th",
    "cadence", "interval", "roster", "reset",
}
# "Lazy CWL" is the one allowed title exception.
ALLOWED_CWL_STRINGS = {"Lazy CWL", "## Lazy CWL"}

RENDER_FACING_CALL_KEYWORDS = {"content", "label", "placeholder", "description"}


def _clan(tag, name):
    return {"tag": tag, "name": name}


def _list_doc(clan_tag="#ABC", clan_name="Alpha", *, reminders=None, expires_at=None, players=None):
    return {
        "_id": f"id-{clan_tag}",
        "clan_tag": clan_tag,
        "clan_name": clan_name,
        "status": "active",
        "players": players if players is not None else [{"tag": "#P1", "name": "One", "town_hall": 10, "discord_id": None}],
        "reminders": reminders or {"enabled": False, "every_minutes": None},
        "expires_at": expires_at or (NOW + timedelta(days=3)),
    }


def _buttons(components):
    """Flatten every InteractiveButtonBuilder out of a render_home() result."""
    found = []
    for container in components:
        assert isinstance(container, Container)
        for item in container.components:
            if isinstance(item, ActionRow):
                for sub in item.components:
                    if hasattr(sub, "is_disabled"):
                        found.append(sub)
    return found


def _button_by_action(components, action):
    for button in _buttons(components):
        if button.custom_id.split(":", 1)[0] == action:
            return button
    raise AssertionError(f"no button for action {action!r}")


def _texts(components):
    lines = []
    for container in components:
        for item in container.components:
            if hasattr(item, "content"):
                lines.append(item.content)
    return lines


def _walk_payload(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_payload(child)


def _component_count(components):
    """Discord's Components V2 count: every nested node with a `type` field.
    Select options are data, not components, and carry no `type`. Mirrors
    tests/test_cards.py's _assert_discord_payload."""
    payload = [component.build() for component in components]
    nodes = list(_walk_payload(payload))
    return len([node for node in nodes if "type" in node])


def _compact_text(components):
    """The single compact-table Text's content (D010: ALL/nothing-selected
    view is exactly one Text component after the select's overflow note)."""
    texts = _texts(components)
    # The compact table is whichever Text line is not a fixed chrome line.
    chrome = {"## Lazy CWL", "Pick a clan, then press a button.", dashboard.COMING_SOON_NOTE}
    candidates = [t for t in texts if t not in chrome and not t.startswith("Showing the first")]
    assert candidates, "no compact table Text found"
    return candidates[-1]


def _select(components):
    for container in components:
        for item in container.components:
            if isinstance(item, ActionRow):
                for sub in item.components:
                    if isinstance(sub, TextSelectMenu):
                        return sub
    raise AssertionError("no select menu found")


# --------------------------------------------------------------- disabled matrix


def test_no_selection_disables_every_action_button_except_refresh():
    clans = [_clan("#ABC", "Alpha")]
    components = dashboard.render_home([], clans, None, NOW)

    for action in ("lazycwl_save", "lazycwl_remind", "lazycwl_auto", "lazycwl_players", "lazycwl_add", "lazycwl_finish"):
        assert _button_by_action(components, action).is_disabled is True
    assert _button_by_action(components, "lazycwl_home").is_disabled is False


def test_clan_with_list_disables_save_enables_the_rest():
    clans = [_clan("#ABC", "Alpha")]
    doc = _list_doc("#ABC")
    components = dashboard.render_home([doc], clans, "#ABC", NOW)

    assert _button_by_action(components, "lazycwl_save").is_disabled is True
    for action in ("lazycwl_remind", "lazycwl_auto", "lazycwl_players", "lazycwl_add", "lazycwl_finish"):
        assert _button_by_action(components, action).is_disabled is False


def test_clan_without_list_enables_save_disables_the_rest():
    clans = [_clan("#ABC", "Alpha")]
    components = dashboard.render_home([], clans, "#ABC", NOW)

    assert _button_by_action(components, "lazycwl_save").is_disabled is False
    for action in ("lazycwl_remind", "lazycwl_auto", "lazycwl_players", "lazycwl_add", "lazycwl_finish"):
        assert _button_by_action(components, action).is_disabled is True


def test_all_selected_disables_players_and_add_enables_the_rest_if_any_qualifies():
    clans = [_clan("#ABC", "Alpha"), _clan("#DEF", "Beta")]
    doc = _list_doc("#ABC")
    components = dashboard.render_home([doc], clans, "ALL", NOW)

    # ABC has a list, DEF does not -> save enabled (DEF qualifies), remind/auto/finish enabled (ABC qualifies)
    assert _button_by_action(components, "lazycwl_save").is_disabled is False
    assert _button_by_action(components, "lazycwl_remind").is_disabled is False
    assert _button_by_action(components, "lazycwl_auto").is_disabled is False
    assert _button_by_action(components, "lazycwl_finish").is_disabled is False
    assert _button_by_action(components, "lazycwl_players").is_disabled is True
    assert _button_by_action(components, "lazycwl_add").is_disabled is True


def test_all_selected_with_nothing_qualifying_disables_everything_but_save():
    clans = [_clan("#ABC", "Alpha")]
    doc = _list_doc("#ABC")
    components = dashboard.render_home([doc], clans, "ALL", NOW)

    # Only clan already has a list -> save disabled (nothing to save), rest enabled.
    assert _button_by_action(components, "lazycwl_save").is_disabled is True
    assert _button_by_action(components, "lazycwl_remind").is_disabled is False


# --------------------------------------------------------------- select options


def test_select_slices_to_24_clans_plus_all_option_and_notes_overflow():
    clans = [_clan(f"#{n}", f"Clan {n}") for n in range(30)]
    components = dashboard.render_home([], clans, None, NOW)

    menu = _select(components)
    assert len(menu.options) == 25
    assert menu.options[0].value == "ALL"
    assert "Showing the first 24 clans." in _texts(components)


def test_select_no_overflow_note_when_25_or_fewer_options():
    clans = [_clan(f"#{n}", f"Clan {n}") for n in range(24)]
    components = dashboard.render_home([], clans, None, NOW)

    menu = _select(components)
    assert len(menu.options) == 25
    assert "Showing the first 24 clans." not in _texts(components)


def test_select_option_descriptions_reflect_saved_state():
    clans = [_clan("#ABC", "Alpha"), _clan("#DEF", "Beta")]
    doc = _list_doc("#ABC")
    components = dashboard.render_home([doc], clans, None, NOW)

    menu = _select(components)
    by_value = {opt.value: opt.description for opt in menu.options if opt.value != "ALL"}
    assert by_value["#ABC"] == "✅ list saved"
    assert by_value["#DEF"] == "no list yet"


# --------------------------------------------------------------- card text


def test_card_text_reminders_on():
    clans = [_clan("#ABC", "Alpha")]
    doc = _list_doc("#ABC", reminders={"enabled": True, "every_minutes": 45})
    components = dashboard.render_home([doc], clans, "#ABC", NOW, away_counts={"#ABC": 2})

    lines = _texts(components)
    assert "\U0001F514 Auto reminders: On, every 45 minutes" in lines
    assert "\U0001F6AA 2 away now" in lines
    assert "\U0001F465 1 players saved" in lines


def test_card_text_reminders_off():
    clans = [_clan("#ABC", "Alpha")]
    doc = _list_doc("#ABC", reminders={"enabled": False, "every_minutes": None})
    components = dashboard.render_home([doc], clans, "#ABC", NOW)

    lines = _texts(components)
    assert "\U0001F514 Auto reminders: Off" in lines


def test_card_text_missing_away_count_shows_question_mark():
    clans = [_clan("#ABC", "Alpha")]
    doc = _list_doc("#ABC")
    components = dashboard.render_home([doc], clans, "#ABC", NOW, away_counts={})

    assert "\U0001F6AA ? away now" in _texts(components)


def test_card_text_no_list_saved_yet():
    clans = [_clan("#ABC", "Alpha")]
    components = dashboard.render_home([], clans, "#ABC", NOW)

    assert "No list saved yet." in _texts(components)


def test_expiry_date_format():
    clans = [_clan("#ABC", "Alpha")]
    doc = _list_doc("#ABC", expires_at=datetime(2026, 9, 16, 0, 10, tzinfo=timezone.utc))
    components = dashboard.render_home([doc], clans, "#ABC", NOW)

    assert "⏰ Expires 16 September" in _texts(components)


# --------------------------------------------------------------- D010 layout


def test_no_chr_obfuscation():
    """refuter-06 MUST-FIX 1: the Mongo filter value must be a plain
    literal, not chr()-obfuscated to dodge the banned-word scan."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "chr(" not in source
    assert dashboard._FWA_CLAN_TYPE == "FWA"


def _clans_with_lists(n):
    clans = [_clan(f"#C{i:03d}", f"Clan {i:03d}") for i in range(n)]
    docs = [_list_doc(f"#C{i:03d}", f"Clan {i:03d}") for i in range(n)]
    return clans, docs


def test_component_ceiling_24_clans_all_selected():
    clans, docs = _clans_with_lists(24)
    components = dashboard.render_home(docs, clans, "ALL", NOW)
    assert _component_count(components) <= 30


def test_component_ceiling_24_clans_one_selected():
    clans, docs = _clans_with_lists(24)
    components = dashboard.render_home(docs, clans, "#C000", NOW)
    assert _component_count(components) <= 30


def test_compact_text_stays_under_char_budget_for_24_clans():
    clans, docs = _clans_with_lists(24)
    components = dashboard.render_home(docs, clans, None, NOW)
    assert len(_compact_text(components)) < 3800


def test_compact_text_truncates_with_more_count_for_40_clans():
    """100 clans (~49 chars/row) comfortably clears COMPACT_TEXT_BUDGET
    (3800), so truncation is actually exercised, not just under budget
    with room to spare (D010 MUST-FIX 2's "… and {k} more")."""
    clans, docs = _clans_with_lists(100)
    components = dashboard.render_home(docs, clans, None, NOW)
    text = _compact_text(components)
    match = re.search(r"… and (\d+) more$", text)
    assert match, text
    # Every included row plus the "more" line accounts for all 100 clans.
    # text is N included rows + 1 "more" line, joined by "\n" -> N newlines.
    included_rows = text.count("\n")
    assert included_rows + int(match.group(1)) == 100
    assert len(text) < 3800


def test_orphan_list_shown_and_selectable():
    """MUST-FIX 3: a list whose clan_tag is not in mongo.clans still shows
    (tagged) and is reachable through the select."""
    clans = [_clan("#ABC", "Alpha")]
    orphan_doc = _list_doc("#ZZZ", "Ghost")
    components = dashboard.render_home([orphan_doc], clans, None, NOW)

    text = _compact_text(components)
    assert "**Ghost** (not in clan table)" in text

    menu = _select(components)
    orphan_option = next(opt for opt in menu.options if opt.value == "#ZZZ")
    assert orphan_option.label == "Ghost"
    assert orphan_option.description == "(not in clan table)"

    # Selecting it renders its full card, so Finish becomes reachable.
    selected = dashboard.render_home([orphan_doc], clans, "#ZZZ", NOW)
    assert "### Ghost (not in clan table)" in _texts(selected)
    assert _button_by_action(selected, "lazycwl_finish").is_disabled is False


def test_lowercase_hashless_clan_tag_matches_normalized_store_doc():
    """NOTED item 6: mongo.clans tags must be normalised before comparing
    against the store's #+UPPER tags."""
    clans = [_clan("abc", "Alpha")]  # lowercase, no leading '#'
    doc = _list_doc("#ABC", "Alpha")
    components = dashboard.render_home([doc], clans, None, NOW)

    menu = _select(components)
    by_value = {opt.value: opt.description for opt in menu.options if opt.value != "ALL"}
    assert by_value["abc"] == "✅ list saved"

    selected = dashboard.render_home([doc], clans, "abc", NOW)
    assert _button_by_action(selected, "lazycwl_save").is_disabled is True


# --------------------------------------------------------------- source-level checks


def _string_parts(value):
    """A Constant str or a JoinedStr's literal (non-interpolated) parts."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, ast.JoinedStr):
        return [
            part.value for part in value.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
    return []


def _render_facing_literals():
    """String literals actually shown to a user:
      1. the content/label/placeholder/description keyword of a component
         builder call;
      2. the argument of any `rows.append(...)` call (S1/S2/S3's row text);
      3. every string literal inside a function whose name ends in `_row`
         or `_line` (any helper that builds one display line, present or
         future - refuter-08 NOTED 4).
    Deliberately narrower than every string literal in the file - the
    module's docstring and the Mongo clan-type query also contain plain
    text that the design's word-ban (design-01-main.md §2) was never meant
    to police. See D009."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    literals = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in RENDER_FACING_CALL_KEYWORDS:
                    literals.extend(_string_parts(keyword.value))
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "rows"
            ):
                for arg in node.args:
                    literals.extend(_string_parts(arg))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.endswith(("_row", "_line")):
            for inner in ast.walk(node):
                literals.extend(_string_parts(inner) if isinstance(inner, (ast.Constant, ast.JoinedStr)) else [])

    return literals


def test_banned_words_grep():
    for literal in _render_facing_literals():
        if literal in ALLOWED_CWL_STRINGS:
            continue
        lowered = literal.lower()
        for word in BANNED_WORDS:
            # word-boundary match so "th" does not flag "the" / "month" etc.
            assert not re.search(rf"\b{re.escape(word)}\b", lowered), (word, literal)


def test_custom_id_single_colon_rule():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    ids = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
            "Button", "TextSelectMenu",
        }:
            for keyword in node.keywords:
                if keyword.arg == "custom_id" and isinstance(keyword.value, ast.Constant):
                    ids.append(keyword.value.value)
    # Also cover the f-string-built custom_ids on buttons (custom_id=f"{action}:{...}")
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant):
                    parts.append(value.value)
                else:
                    parts.append("X")
            joined = "".join(parts)
            if ":" in joined:
                ids.append(joined)

    assert ids, "expected at least one custom_id literal/f-string in the module"
    for custom_id in ids:
        assert custom_id.count(":") == 1, custom_id


# --------------------------------------------------------------- admin gate


class _FakeMember:
    def __init__(self, permissions):
        self.permissions = permissions


class _FakeCtx:
    def __init__(self, member):
        self.member = member
        self.responded = []
        self.deferred = False

    async def respond(self, message, ephemeral=False):
        self.responded.append((message, ephemeral))

    async def defer(self, ephemeral=False):
        self.deferred = True


def test_admin_gate_denies_non_admin():
    ctx = _FakeCtx(_FakeMember(hikari.Permissions.NONE))
    command = dashboard.LazyCwl()

    asyncio.run(command.invoke(ctx, mongo=None))

    assert ctx.deferred is False
    assert ctx.responded == [("Only server admins can use this.", True)]


# --------------------------------------------------------------- StartedEvent idempotency


def test_started_event_calls_service_start_once_even_if_fired_twice(monkeypatch):
    calls = []

    async def fake_start(bot, coc_api, mongo):
        calls.append((bot, coc_api, mongo))

    monkeypatch.setattr(dashboard.service, "start", fake_start)
    monkeypatch.setattr(dashboard, "_started", False)

    async def main():
        event = SimpleNamespace()
        await dashboard.on_started(event, bot=object(), coc_api=object(), mongo=object())
        await dashboard.on_started(event, bot=object(), coc_api=object(), mongo=object())

    asyncio.run(main())

    assert len(calls) == 1
    monkeypatch.setattr(dashboard, "_started", False)


# --------------------------------------------------------------- placeholder handlers


class _FakeInteraction:
    def __init__(self, values=None):
        self.values = values


class _FakeHandlerCtx:
    def __init__(self, values=None, user_id=999):
        self.interaction = _FakeInteraction(values)
        self.user = SimpleNamespace(id=user_id)


class _FakeClansCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query):
        clan_type = query.get("type")
        return _FakeCursor([d for d in self._docs if d.get("type") == clan_type])


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeMongo:
    def __init__(self, clan_docs, list_docs):
        self.clans = _FakeClansCollection(clan_docs)
        self.lazy_cwl_lists = _Collection(list_docs)


def test_placeholder_handlers_keep_the_selected_tag(monkeypatch):
    """refuter-06 MUST-FIX 4: proven with TWO clans, so a handler that drops
    the selection would render a different (or every) card, and asserting
    the custom_id's tag - not just card presence - actually exercises the
    tag being carried through, not just re-rendered from a single-clan
    fixture regardless of selected_tag. Save/remind are covered separately
    below (builder-08: no longer placeholders)."""
    async def fake_away_players(doc):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)

    mongo = _FakeMongo(
        clan_docs=[
            {"tag": "#ABC", "name": "Alpha", "type": "FWA"},
            {"tag": "#DEF", "name": "Beta", "type": "FWA"},
        ],
        list_docs=[],
    )
    ctx = _FakeHandlerCtx()

    async def run_all():
        results = []
        for handler in (
            dashboard.handle_players, dashboard.handle_add, dashboard.handle_finish,
        ):
            results.append(await handler.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
        return results

    for components in asyncio.run(run_all()):
        assert dashboard.COMING_SOON_NOTE in _texts(components)
        # Only the selected clan's card is rendered - the other clan's name
        # never appears (single-clan fixtures cannot tell this apart).
        assert "### Alpha" in _texts(components)
        assert "### Beta" not in _texts(components)
        # The custom_id is the actual mechanism carrying the tag forward.
        for action in (
            "lazycwl_save", "lazycwl_remind", "lazycwl_auto",
            "lazycwl_players", "lazycwl_add", "lazycwl_finish", "lazycwl_home",
        ):
            assert _button_by_action(components, action).custom_id.endswith(":#ABC")


def test_pick_handler_reads_selection_from_interaction_values(monkeypatch):
    async def fake_away_players(doc):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)

    mongo = _FakeMongo(
        clan_docs=[
            {"tag": "#ABC", "name": "Alpha", "type": "FWA"},
            {"tag": "#DEF", "name": "Beta", "type": "FWA"},
        ],
        list_docs=[],
    )
    ctx = _FakeHandlerCtx(values=["#ABC"])
    components = asyncio.run(dashboard.handle_pick.__wrapped__(ctx=ctx, action_id="home", mongo=mongo))
    assert "### Alpha" in _texts(components)
    assert "### Beta" not in _texts(components)


# --------------------------------------------------------------- S1 save list / S2 remind now


def test_no_tag_clan_skipped_from_select_options():
    """refuter-07 NOTED (lazycwl_dashboard.py:262-269): a clan doc with no
    tag must be skipped, never emit a null select value."""
    clans = [_clan("#ABC", "Alpha"), {"name": "No Tag Clan"}]
    components = dashboard.render_home([], clans, None, NOW)
    select = _select(components)
    values = [option.value for option in select.options]
    assert None not in values
    assert "#ABC" in values
    assert len(values) == 2  # "ALL" + Alpha only


def test_render_save_result_single_clan_happy_row():
    results = [{
        "ok": True, "clan_name": "Alpha", "clan_tag": "#ABC",
        "player_count": 12, "linked_count": 9, "already_saved": False,
        "existing_saved_at": None, "error": None,
    }]
    components = dashboard.render_save_result(results, "#ABC")
    texts = _texts(components)
    assert "## \U0001F4BE Save list" in texts
    assert any("Alpha" in t and "12 players saved" in t and "9 linked to Discord" in t for t in texts)
    assert not any(t.startswith(("0 saved", "1 saved")) for t in texts)  # no ALL summary for a single clan


def test_render_save_result_already_saved_row():
    results = [{
        "ok": False, "clan_name": "Alpha", "clan_tag": "#ABC",
        "player_count": 0, "linked_count": 0, "already_saved": True,
        "existing_saved_at": NOW, "error": "This clan already has a saved list.",
    }]
    texts = _texts(dashboard.render_save_result(results, "#ABC"))
    assert any("already saved on 12 September" in t for t in texts)


def test_render_save_result_error_row():
    results = [{
        "ok": False, "clan_name": None, "clan_tag": "#ABC",
        "player_count": 0, "linked_count": 0, "already_saved": False,
        "existing_saved_at": None, "error": "Clan #ABC not found.",
    }]
    texts = _texts(dashboard.render_save_result(results, "#ABC"))
    assert any(t.startswith("❌ **#ABC**") and "Clan #ABC not found." in t for t in texts)


def test_render_save_result_all_fanout_summary_counts():
    results = [
        {"ok": True, "clan_name": "Alpha", "clan_tag": "#ABC", "player_count": 5,
         "linked_count": 5, "already_saved": False, "existing_saved_at": None, "error": None},
        {"ok": False, "clan_name": "Beta", "clan_tag": "#DEF", "player_count": 0,
         "linked_count": 0, "already_saved": True, "existing_saved_at": NOW, "error": "already"},
        {"ok": False, "clan_name": "Gamma", "clan_tag": "#GHI", "player_count": 0,
         "linked_count": 0, "already_saved": False, "existing_saved_at": None, "error": "boom"},
    ]
    texts = _texts(dashboard.render_save_result(results, "ALL"))
    assert "1 saved · 1 already saved · 1 failed" in texts


def test_build_save_result_all_calls_service_once_per_clan(monkeypatch):
    calls = []

    async def fake_save_list(clan_tag, saved_by):
        calls.append((clan_tag, saved_by))
        return {
            "ok": True, "clan_name": f"Clan {clan_tag}", "clan_tag": clan_tag,
            "player_count": 1, "linked_count": 0, "already_saved": False,
            "existing_saved_at": None, "error": None,
        }

    monkeypatch.setattr(dashboard.service, "save_list", fake_save_list)
    mongo = _FakeMongo(
        clan_docs=[
            {"tag": "#ABC", "name": "Alpha", "type": "FWA"},
            {"tag": "#DEF", "name": "Beta", "type": "FWA"},
        ],
        list_docs=[],
    )
    components = asyncio.run(dashboard.build_save_result(mongo, "ALL", 777))
    assert calls == [("#ABC", 777), ("#DEF", 777)]
    texts = _texts(components)
    assert "2 saved · 0 already saved · 0 failed" in texts


def test_build_save_result_service_exception_becomes_error_row(monkeypatch):
    async def fake_save_list(clan_tag, saved_by):
        raise RuntimeError("coc outage")

    monkeypatch.setattr(dashboard.service, "save_list", fake_save_list)
    mongo = _FakeMongo(clan_docs=[{"tag": "#ABC", "name": "Alpha", "type": "FWA"}], list_docs=[])
    components = asyncio.run(dashboard.build_save_result(mongo, "#ABC", 777))
    texts = _texts(components)
    assert any(t.startswith("❌ **#ABC**") and "coc outage" in t for t in texts)


def test_save_result_back_button_carries_selected_tag():
    components = dashboard.render_save_result([], "#ABC")
    back = _button_by_action(components, "lazycwl_home")
    assert back.custom_id == "lazycwl_home:#ABC"


def test_save_result_component_ceiling_24_clans():
    results = [
        {"ok": True, "clan_name": f"Clan {i:03d}", "clan_tag": f"#C{i:03d}", "player_count": 30,
         "linked_count": 20, "already_saved": False, "existing_saved_at": None, "error": None}
        for i in range(24)
    ]
    components = dashboard.render_save_result(results, "ALL")
    assert _component_count(components) <= 30


def test_render_remind_result_sent_row():
    results = [{"ok": True, "clan_name": "Alpha", "clan_tag": "#ABC", "away_count": 3,
                "total_count": 10, "sent": True, "error": None}]
    texts = _texts(dashboard.render_remind_result(results, "#ABC"))
    assert any("3 of 10 away" in t and "message sent" in t for t in texts)


def test_render_remind_result_everyone_here_row():
    results = [{"ok": True, "clan_name": "Alpha", "clan_tag": "#ABC", "away_count": 0,
                "total_count": 10, "sent": False, "error": None}]
    texts = _texts(dashboard.render_remind_result(results, "#ABC"))
    assert any("everyone is here" in t for t in texts)


def test_render_remind_result_error_row():
    results = [{"ok": False, "clan_name": None, "clan_tag": "#ABC", "away_count": 0,
                "total_count": 0, "sent": False, "error": "No saved list for this clan."}]
    texts = _texts(dashboard.render_remind_result(results, "#ABC"))
    assert any(t.startswith("❌ **#ABC**") and "No saved list for this clan." in t for t in texts)


def test_build_remind_result_all_calls_service_once_per_clan(monkeypatch):
    calls = []

    async def fake_remind_now(clan_tag):
        calls.append(clan_tag)
        return {"ok": True, "clan_name": f"Clan {clan_tag}", "clan_tag": clan_tag,
                "away_count": 0, "total_count": 5, "sent": False, "error": None}

    monkeypatch.setattr(dashboard.service, "remind_now", fake_remind_now)
    mongo = _FakeMongo(
        clan_docs=[
            {"tag": "#ABC", "name": "Alpha", "type": "FWA"},
            {"tag": "#DEF", "name": "Beta", "type": "FWA"},
        ],
        list_docs=[],
    )
    components = asyncio.run(dashboard.build_remind_result(mongo, "ALL"))
    assert calls == ["#ABC", "#DEF"]
    texts = _texts(components)
    assert "0 sent · 2 everyone home · 0 failed" in texts


def test_build_remind_result_service_exception_becomes_error_row(monkeypatch):
    async def fake_remind_now(clan_tag):
        raise RuntimeError("coc outage")

    monkeypatch.setattr(dashboard.service, "remind_now", fake_remind_now)
    mongo = _FakeMongo(clan_docs=[{"tag": "#ABC", "name": "Alpha", "type": "FWA"}], list_docs=[])
    components = asyncio.run(dashboard.build_remind_result(mongo, "#ABC"))
    texts = _texts(components)
    assert any(t.startswith("❌ **#ABC**") and "coc outage" in t for t in texts)


def test_remind_result_back_button_carries_selected_tag():
    components = dashboard.render_remind_result([], "ALL")
    back = _button_by_action(components, "lazycwl_home")
    assert back.custom_id == "lazycwl_home:ALL"


def test_remind_result_component_ceiling_24_clans():
    results = [
        {"ok": True, "clan_name": f"Clan {i:03d}", "clan_tag": f"#C{i:03d}", "away_count": 2,
         "total_count": 10, "sent": True, "error": None}
        for i in range(24)
    ]
    components = dashboard.render_remind_result(results, "ALL")
    assert _component_count(components) <= 30


def test_handle_save_uses_ctx_user_id(monkeypatch):
    calls = []

    async def fake_save_list(clan_tag, saved_by):
        calls.append((clan_tag, saved_by))
        return {"ok": True, "clan_name": "Alpha", "clan_tag": clan_tag, "player_count": 1,
                "linked_count": 0, "already_saved": False, "existing_saved_at": None, "error": None}

    monkeypatch.setattr(dashboard.service, "save_list", fake_save_list)
    mongo = _FakeMongo(clan_docs=[], list_docs=[])
    ctx = _FakeHandlerCtx(user_id=555)
    asyncio.run(dashboard.handle_save.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert calls == [("#ABC", 555)]


def test_handle_remind_calls_service_with_action_id_tag(monkeypatch):
    """refuter-08 NOTED 5: no test exercised handle_remind at all."""
    calls = []

    async def fake_remind_now(clan_tag):
        calls.append(clan_tag)
        return {"ok": True, "clan_name": "Alpha", "clan_tag": clan_tag,
                "away_count": 1, "total_count": 5, "sent": True, "error": None}

    monkeypatch.setattr(dashboard.service, "remind_now", fake_remind_now)
    mongo = _FakeMongo(clan_docs=[], list_docs=[])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_remind.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert calls == ["#ABC"]
    assert "## \U0001F4E3 Remind now" in _texts(components)


# --------------------------------------------------------------- _chunk_rows (NOTED 1)


def test_chunk_rows_empty_list_never_emits_empty_chunk():
    assert dashboard._chunk_rows([]) == []


def test_chunk_rows_oversized_single_row_is_truncated_under_budget():
    row = "x" * 5000
    chunks = dashboard._chunk_rows([row], budget=3800)
    assert len(chunks) == 1
    assert len(chunks[0]) <= 3800
    assert chunks[0].endswith("…")


def test_chunk_rows_never_exceeds_budget_across_multiple_large_rows():
    rows = ["x" * 3000 for _ in range(4)]
    chunks = dashboard._chunk_rows(rows, budget=3800)
    assert all(len(chunk) <= 3800 for chunk in chunks)
    assert all(chunk for chunk in chunks)  # no empty chunk
    # every row is present in exactly one chunk
    assert sum(chunk.count("x" * 3000) for chunk in chunks) == 4


# --------------------------------------------------------------- _fwa_clans (NOTED 3)


def test_fwa_clans_filters_untagged_and_sorts_by_name():
    mongo = _FakeMongo(
        clan_docs=[
            {"tag": "#DEF", "name": "Beta", "type": "FWA"},
            {"name": "No Tag Clan", "type": "FWA"},
            {"tag": "#ABC", "name": "Alpha", "type": "FWA"},
            {"tag": "#GHI", "name": "Gamma", "type": "NOT_FWA"},
        ],
        list_docs=[],
    )
    clans = asyncio.run(dashboard._fwa_clans(mongo))
    assert [clan["tag"] for clan in clans] == ["#ABC", "#DEF"]


# --------------------------------------------------------------- S3 Auto reminders


def test_auto_how_often_screen_shown_when_off():
    mongo = _FakeMongo(clan_docs=[], list_docs=[_list_doc("#ABC", "Alpha")])
    components = asyncio.run(dashboard.build_auto(mongo, "#ABC"))
    texts = _texts(components)
    assert "## \U0001F514 Auto reminders" in texts
    assert "How often should the bot remind players?" in texts
    menu = _select(components)
    assert menu.custom_id == "lazycwl_auto_every:#ABC"
    assert {opt.value for opt in menu.options} == {"30", "60", "120"}
    recommended = next(opt for opt in menu.options if opt.value == "60")
    assert recommended.label == "Every hour (recommended)"


def test_auto_confirm_off_screen_shown_when_on():
    doc = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    components = asyncio.run(dashboard.build_auto(mongo, "#ABC"))
    texts = _texts(components)
    assert "## \U0001F515 Turn off auto reminders?" in texts
    assert "Clans: **Alpha**" in texts
    yes = _button_by_action(components, "lazycwl_auto_off")
    assert yes.custom_id == "lazycwl_auto_off:#ABC"


def test_auto_all_mixed_state_shows_how_often_with_note():
    on_doc = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    off_doc = _list_doc("#DEF", "Beta", reminders={"enabled": False, "every_minutes": None})
    mongo = _FakeMongo(clan_docs=[], list_docs=[on_doc, off_doc])
    components = asyncio.run(dashboard.build_auto(mongo, "ALL"))
    texts = _texts(components)
    assert "## \U0001F514 Auto reminders" in texts
    assert "1 clans already on. Turning on the rest." in texts


def test_auto_all_every_active_on_shows_confirm_off_with_all_names():
    on1 = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    on2 = _list_doc("#DEF", "Beta", reminders={"enabled": True, "every_minutes": 30})
    mongo = _FakeMongo(clan_docs=[], list_docs=[on1, on2])
    components = asyncio.run(dashboard.build_auto(mongo, "ALL"))
    texts = _texts(components)
    assert "## \U0001F515 Turn off auto reminders?" in texts
    assert "Clans: **Alpha, Beta**" in texts


def test_auto_every_select_leads_to_confirm_on_with_dash_m_action_id():
    mongo = _FakeMongo(clan_docs=[], list_docs=[_list_doc("#ABC", "Alpha")])
    ctx = _FakeHandlerCtx(values=["120"])
    components = asyncio.run(dashboard.handle_auto_every.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    texts = _texts(components)
    assert "## \U0001F514 Turn on auto reminders?" in texts
    assert "Clans: **Alpha**" in texts
    assert "Every 120 minutes, for up to 7 days." in texts
    yes = _button_by_action(components, "lazycwl_auto_on")
    assert yes.custom_id == "lazycwl_auto_on:#ABC-120"


def test_auto_confirm_on_all_lists_only_off_clans_with_note():
    on_doc = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    off_doc = _list_doc("#DEF", "Beta", reminders={"enabled": False, "every_minutes": None})
    mongo = _FakeMongo(clan_docs=[], list_docs=[on_doc, off_doc])
    components = asyncio.run(dashboard.build_auto_confirm_on(mongo, "ALL", 30))
    texts = _texts(components)
    assert "Clans: **Beta**" in texts
    assert "1 clans already on. Turning on the rest." in texts
    yes = _button_by_action(components, "lazycwl_auto_on")
    assert yes.custom_id == "lazycwl_auto_on:ALL-30"


def test_auto_on_yes_calls_set_reminders_with_tag_true_m(monkeypatch):
    calls = []

    async def fake_set_reminders(clan_tag, enabled, every_minutes=None):
        calls.append((clan_tag, enabled, every_minutes))
        return {"ok": True, "error": None}

    monkeypatch.setattr(dashboard.service, "set_reminders", fake_set_reminders)
    mongo = _FakeMongo(clan_docs=[], list_docs=[_list_doc("#ABC", "Alpha")])
    components = asyncio.run(dashboard.build_auto_turn_on(mongo, "#ABC-60"))
    assert calls == [("#ABC", True, 60)]
    texts = _texts(components)
    assert any("Alpha" in t and "on, every 60 minutes" in t for t in texts)


def test_auto_off_yes_calls_set_reminders_with_tag_false_none(monkeypatch):
    calls = []

    async def fake_set_reminders(clan_tag, enabled, every_minutes=None):
        calls.append((clan_tag, enabled, every_minutes))
        return {"ok": True, "error": None}

    monkeypatch.setattr(dashboard.service, "set_reminders", fake_set_reminders)
    doc = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    components = asyncio.run(dashboard.build_auto_turn_off(mongo, "#ABC"))
    assert calls == [("#ABC", False, None)]
    texts = _texts(components)
    assert any("Alpha" in t and t.endswith("off") for t in texts)


def test_auto_all_turn_on_only_calls_off_clans(monkeypatch):
    calls = []

    async def fake_set_reminders(clan_tag, enabled, every_minutes=None):
        calls.append((clan_tag, enabled, every_minutes))
        return {"ok": True, "error": None}

    monkeypatch.setattr(dashboard.service, "set_reminders", fake_set_reminders)
    on_doc = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    off_doc = _list_doc("#DEF", "Beta", reminders={"enabled": False, "every_minutes": None})
    mongo = _FakeMongo(clan_docs=[], list_docs=[on_doc, off_doc])
    components = asyncio.run(dashboard.build_auto_turn_on(mongo, "ALL-30"))
    assert calls == [("#DEF", True, 30)]
    texts = _texts(components)
    assert "1 on · 0 failed" in texts


def test_auto_all_turn_off_calls_every_active_list(monkeypatch):
    calls = []

    async def fake_set_reminders(clan_tag, enabled, every_minutes=None):
        calls.append((clan_tag, enabled, every_minutes))
        return {"ok": True, "error": None}

    monkeypatch.setattr(dashboard.service, "set_reminders", fake_set_reminders)
    on1 = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    on2 = _list_doc("#DEF", "Beta", reminders={"enabled": True, "every_minutes": 30})
    mongo = _FakeMongo(clan_docs=[], list_docs=[on1, on2])
    components = asyncio.run(dashboard.build_auto_turn_off(mongo, "ALL"))
    assert calls == [("#ABC", False, None), ("#DEF", False, None)]
    texts = _texts(components)
    assert "2 off · 0 failed" in texts


def test_auto_service_exception_becomes_error_row(monkeypatch):
    async def fake_set_reminders(clan_tag, enabled, every_minutes=None):
        raise RuntimeError("coc outage")

    monkeypatch.setattr(dashboard.service, "set_reminders", fake_set_reminders)
    mongo = _FakeMongo(clan_docs=[], list_docs=[_list_doc("#ABC", "Alpha")])
    components = asyncio.run(dashboard.build_auto_turn_on(mongo, "#ABC-60"))
    texts = _texts(components)
    assert any(t.startswith("❌ **Alpha**") and "coc outage" in t for t in texts)


def test_auto_back_buttons_carry_selected_tag():
    how_often = dashboard.render_auto_how_often("#ABC")
    assert _button_by_action(how_often, "lazycwl_home").custom_id == "lazycwl_home:#ABC"

    confirm_on = dashboard.render_auto_confirm_on("ALL", "Alpha", 60)
    assert _button_by_action(confirm_on, "lazycwl_home").custom_id == "lazycwl_home:ALL"

    confirm_off = dashboard.render_auto_confirm_off("#ABC", "Alpha")
    assert _button_by_action(confirm_off, "lazycwl_home").custom_id == "lazycwl_home:#ABC"

    result = dashboard.render_auto_result([], "#ABC", turning_on=True)
    assert _button_by_action(result, "lazycwl_home").custom_id == "lazycwl_home:#ABC"


def test_auto_result_component_ceiling_24_clans():
    results = [
        {"ok": True, "clan_name": f"Clan {i:03d}", "clan_tag": f"#C{i:03d}", "error": None}
        for i in range(24)
    ]
    components = dashboard.render_auto_result(results, "ALL", turning_on=True, every_minutes=60)
    assert _component_count(components) <= 30


def test_handle_auto_off_state_routes_to_how_often(monkeypatch):
    mongo = _FakeMongo(clan_docs=[], list_docs=[_list_doc("#ABC", "Alpha")])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_auto.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert "How often should the bot remind players?" in _texts(components)


def test_handle_auto_on_state_routes_to_confirm_off(monkeypatch):
    doc = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_auto.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert "## \U0001F515 Turn off auto reminders?" in _texts(components)


def test_custom_ids_still_single_colon_with_s3_added():
    """S3 adds custom_ids built with an action_id containing '-' (not ':') -
    re-run the single-colon check to prove that didn't add a second colon."""
    ids = [
        f"lazycwl_auto_every:{dashboard._encode_tag('#ABC')}",
        f"lazycwl_auto_on:{dashboard._encode_auto_on('#ABC', 60)}",
        f"lazycwl_auto_on:{dashboard._encode_auto_on('ALL', 120)}",
        f"lazycwl_auto_off:{dashboard._encode_tag('ALL')}",
    ]
    for custom_id in ids:
        assert custom_id.count(":") == 1, custom_id


def test_component_action_names_still_pass():
    import subprocess
    import sys

    repo_root = MODULE_PATH.resolve().parent.parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_component_action_names.py"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

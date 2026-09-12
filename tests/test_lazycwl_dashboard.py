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
from tests.lazycwl_wording import BANNED_WORDS, ALLOWED_CWL_STRINGS

MODULE_PATH = Path(__file__).resolve().parent.parent / "extensions" / "commands" / "lazycwl_dashboard.py"
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

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
    chrome = {"## Lazy CWL", "Pick a clan, then press a button."}
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


def test_all_six_action_buttons_carry_the_selected_tag():
    """refuter-12 MUST-FIX: with a multi-clan fixture and selected_tag
    "#ABC", every S0 action button's custom_id must end with ":#ABC" so
    the selection is never silently dropped (lazycwl_dashboard.py:320-327).
    Proven with TWO clans so a handler that renders regardless of
    selected_tag cannot pass by accident."""
    clans = [_clan("#ABC", "Alpha"), _clan("#DEF", "Beta")]
    doc = _list_doc("#ABC")
    components = dashboard.render_home([doc], clans, "#ABC", NOW)

    for action in (
        "lazycwl_save", "lazycwl_remind", "lazycwl_auto",
        "lazycwl_players", "lazycwl_add", "lazycwl_finish",
    ):
        assert _button_by_action(components, action).custom_id.endswith(":#ABC")


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


def test_is_admin_none_member():
    """refuter-15 NOTED 5: `is_admin` is the one predicate shared by
    LazyCwl.invoke and lazy_cwl._redirect - a missing member (e.g. a DM
    interaction) is never an admin."""
    assert dashboard.is_admin(None) is False


def test_is_admin_member_without_administrator_permission():
    assert dashboard.is_admin(_FakeMember(hikari.Permissions.NONE)) is False


def test_is_admin_member_with_administrator_permission():
    assert dashboard.is_admin(_FakeMember(hikari.Permissions.ADMINISTRATOR)) is True


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


def test_no_coming_soon_or_placeholder_string_remains():
    """SUCCESS criterion (brief builder-12): S6 is real now, `_placeholder`
    and COMING_SOON_NOTE are gone."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "_placeholder" not in source
    assert "Coming soon" not in source


# --------------------------------------------------------------- S6 Finish


def test_finish_confirm_single_clan_wording_and_buttons():
    doc = _list_doc("#ABC", "Alpha")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    components = asyncio.run(dashboard.build_finish_confirm(mongo, "#ABC"))
    texts = _texts(components)
    assert "## \U0001F3C1 Finish Alpha?" in texts
    assert "This clears the saved list." in texts
    assert "Auto reminders stop." in texts
    assert "You can save a new list any time." in texts
    yes = _button_by_action(components, "lazycwl_finish_yes")
    assert yes.custom_id == "lazycwl_finish_yes:#ABC"
    no = _button_by_action(components, "lazycwl_home")
    assert no.custom_id == "lazycwl_home:#ABC"


def test_finish_confirm_all_lists_clan_names():
    doc1 = _list_doc("#ABC", "Alpha")
    doc2 = _list_doc("#DEF", "Beta")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc1, doc2])
    components = asyncio.run(dashboard.build_finish_confirm(mongo, "ALL"))
    texts = _texts(components)
    assert "## \U0001F3C1 Finish all clans?" in texts
    assert "Clans: **Alpha, Beta**" in texts
    yes = _button_by_action(components, "lazycwl_finish_yes")
    assert yes.custom_id == "lazycwl_finish_yes:ALL"


def test_finish_confirm_all_no_lists_shows_plain_screen():
    mongo = _FakeMongo(clan_docs=[], list_docs=[])
    components = asyncio.run(dashboard.build_finish_confirm(mongo, "ALL"))
    texts = _texts(components)
    assert "No saved lists to finish." in texts
    home = _button_by_action(components, "lazycwl_home")
    assert home.custom_id == "lazycwl_home:ALL"
    for container in components:
        for item in container.components:
            if isinstance(item, ActionRow):
                for sub in item.components:
                    assert sub.custom_id != "lazycwl_finish_yes:ALL"


def test_finish_press_never_calls_service_finish(monkeypatch):
    """DO NOT: pressing lazycwl_finish must never call service.finish -
    only lazycwl_finish_yes does."""
    async def fake_finish(clan_tag):
        raise AssertionError("service.finish must not be called by handle_finish")

    monkeypatch.setattr(dashboard.service, "finish", fake_finish)
    doc = _list_doc("#ABC", "Alpha")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_finish.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert "## \U0001F3C1 Finish Alpha?" in _texts(components)


def test_finish_yes_calls_service_finish_single_clan(monkeypatch):
    calls = []

    async def fake_finish(clan_tag):
        calls.append(clan_tag)
        return {"ok": True, "clan_name": "Alpha", "error": None}

    monkeypatch.setattr(dashboard.service, "finish", fake_finish)
    doc = _list_doc("#ABC", "Alpha")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    components = asyncio.run(dashboard.build_finish_yes(mongo, "#ABC"))
    assert calls == ["#ABC"]
    texts = _texts(components)
    assert "## \U0001F3C1 Finished" in texts
    assert any("Alpha" in t and "list cleared" in t for t in texts)
    home = _button_by_action(components, "lazycwl_home")
    assert home.custom_id == "lazycwl_home:#ABC"


def test_finish_yes_all_calls_every_active_list_sequential(monkeypatch):
    calls = []

    async def fake_finish(clan_tag):
        calls.append(clan_tag)
        return {"ok": True, "clan_name": None, "error": None}

    monkeypatch.setattr(dashboard.service, "finish", fake_finish)
    doc1 = _list_doc("#ABC", "Alpha")
    doc2 = _list_doc("#DEF", "Beta")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc1, doc2])
    components = asyncio.run(dashboard.build_finish_yes(mongo, "ALL"))
    assert calls == ["#ABC", "#DEF"]
    texts = _texts(components)
    assert "2 finished · 0 failed" in texts


def test_finish_yes_service_exception_becomes_error_row_not_crash(monkeypatch):
    async def fake_finish(clan_tag):
        raise RuntimeError("mongo outage")

    monkeypatch.setattr(dashboard.service, "finish", fake_finish)
    doc = _list_doc("#ABC", "Alpha")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    components = asyncio.run(dashboard.build_finish_yes(mongo, "#ABC"))
    texts = _texts(components)
    assert any(t.startswith("❌ **Alpha**") and "mongo outage" in t for t in texts)


def test_finish_yes_orphan_list_included_in_all(monkeypatch):
    """Orphan lists (clan_tag not in mongo.clans) still get finished for
    ALL, same as S3's auto-off (store.list_active is not filtered against
    mongo.clans)."""
    async def fake_finish(clan_tag):
        return {"ok": True, "clan_name": None, "error": None}

    monkeypatch.setattr(dashboard.service, "finish", fake_finish)
    orphan = _list_doc("#ORPH", "Ghost Clan")
    mongo = _FakeMongo(clan_docs=[], list_docs=[orphan])
    components = asyncio.run(dashboard.build_finish_yes(mongo, "ALL"))
    texts = _texts(components)
    assert any("Ghost Clan" in t and "list cleared" in t for t in texts)


def test_finish_yes_all_row_prefixes_and_real_failed_count(monkeypatch):
    """refuter-12 NOTED: ok rows must start with the finish emoji, error
    rows with X, and the ALL summary must count real outcomes, not just
    len(results) - proven with one ok and one raising target."""
    async def fake_finish(clan_tag):
        if clan_tag == "#DEF":
            raise RuntimeError("mongo outage")
        return {"ok": True, "clan_name": "Alpha", "error": None}

    monkeypatch.setattr(dashboard.service, "finish", fake_finish)
    doc1 = _list_doc("#ABC", "Alpha")
    doc2 = _list_doc("#DEF", "Beta")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc1, doc2])
    components = asyncio.run(dashboard.build_finish_yes(mongo, "ALL"))
    texts = _texts(components)
    lines = [line for t in texts for line in t.split("\n")]
    assert any(line.startswith("\U0001F3C1 **Alpha**") for line in lines)
    assert any(line.startswith("❌ **Beta**") for line in lines)
    assert "1 finished · 1 failed" in texts


def test_handle_finish_yes_registered_and_routes(monkeypatch):
    async def fake_finish(clan_tag):
        return {"ok": True, "clan_name": "Alpha", "error": None}

    monkeypatch.setattr(dashboard.service, "finish", fake_finish)
    doc = _list_doc("#ABC", "Alpha")
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_finish_yes.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert "## \U0001F3C1 Finished" in _texts(components)


def test_finish_result_component_ceiling_24_clans():
    results = [
        {"ok": True, "clan_name": f"Clan {i:03d}", "clan_tag": f"#C{i:03d}", "error": None}
        for i in range(24)
    ]
    components = dashboard.render_finish_result(results, "ALL")
    assert _component_count(components) <= 30


def test_finish_confirm_component_ceiling_24_clans():
    docs = [_list_doc(f"#C{i:03d}", f"Clan {i:03d}") for i in range(24)]
    mongo = _FakeMongo(clan_docs=[], list_docs=docs)
    components = asyncio.run(dashboard.build_finish_confirm(mongo, "ALL"))
    assert _component_count(components) <= 30


def _text_char_budget_ok(components):
    return all(len(t) <= dashboard.COMPACT_TEXT_BUDGET for t in _texts(components))


def test_finish_confirm_clans_line_capped_at_200_clans():
    """refuter-12 NOTED: the ALL confirm's "Clans: **{names}**" line must
    be capped like every other multi-row screen - uncapped, 200 clans
    measured 4409 chars, over Discord's 4000-char Text limit."""
    docs = [_list_doc(f"#C{i:03d}", f"The Very Long Clan Name Number {i:03d}") for i in range(200)]
    mongo = _FakeMongo(clan_docs=[], list_docs=docs)
    components = asyncio.run(dashboard.build_finish_confirm(mongo, "ALL"))
    assert _text_char_budget_ok(components)
    assert "… and" in " ".join(_texts(components))


def test_auto_confirm_off_clans_line_capped_at_200_clans():
    docs = [
        _list_doc(f"#C{i:03d}", f"The Very Long Clan Name Number {i:03d}", reminders={"enabled": True, "every_minutes": 60})
        for i in range(200)
    ]
    mongo = _FakeMongo(clan_docs=[], list_docs=docs)
    components = asyncio.run(dashboard.build_auto(mongo, "ALL"))
    assert _text_char_budget_ok(components)
    assert "… and" in " ".join(_texts(components))


def test_auto_confirm_on_clans_line_capped_at_200_clans():
    docs = [
        _list_doc(f"#C{i:03d}", f"The Very Long Clan Name Number {i:03d}", reminders={"enabled": False, "every_minutes": None})
        for i in range(200)
    ]
    mongo = _FakeMongo(clan_docs=[], list_docs=docs)
    components = asyncio.run(dashboard.build_auto_confirm_on(mongo, "ALL", 30))
    assert _text_char_budget_ok(components)
    assert "… and" in " ".join(_texts(components))


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


def test_render_remind_result_all_fanout_summary_counts():
    """refuter-12 NOTED (mirrors test_render_save_result_all_fanout_summary_counts):
    the ALL summary must count real per-row outcomes, not len(results),
    proven with one of each category."""
    results = [
        {"ok": True, "clan_name": "Alpha", "clan_tag": "#ABC", "away_count": 3,
         "total_count": 10, "sent": True, "error": None},
        {"ok": True, "clan_name": "Beta", "clan_tag": "#DEF", "away_count": 0,
         "total_count": 10, "sent": False, "error": None},
        {"ok": False, "clan_name": "Gamma", "clan_tag": "#GHI", "away_count": 0,
         "total_count": 0, "sent": False, "error": "boom"},
    ]
    texts = _texts(dashboard.render_remind_result(results, "ALL"))
    assert "1 sent · 1 everyone home · 1 failed" in texts


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
    assert "1 clan already on. Turning on the rest." in texts


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
    assert "1 clan already on. Turning on the rest." in texts
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


# --------------------------------------------------------------- S4 Player list


def _player(tag, name, th, *, added_manually=False):
    return {"tag": tag, "name": name, "town_hall": th, "discord_id": None, "added_manually": added_manually}


def _players_doc(n, clan_tag="#ABC", clan_name="Alpha"):
    players = [_player(f"#P{i:03d}", f"Player {i:03d}", 10 + (i % 5)) for i in range(n)]
    return {"_id": "id-1", "clan_tag": clan_tag, "clan_name": clan_name, "status": "active", "players": players}


def test_player_page_count_matrix():
    assert dashboard._player_page_count(0) == 1
    assert dashboard._player_page_count(20) == 1
    assert dashboard._player_page_count(21) == 2
    assert dashboard._player_page_count(45) == 3


def test_players_sorted_by_town_hall_desc_then_name():
    players = [
        {"tag": "#A", "name": "Zed", "town_hall": 10},
        {"tag": "#B", "name": "Amy", "town_hall": 12},
        {"tag": "#C", "name": "Bob", "town_hall": 12},
    ]
    sorted_players = dashboard._sorted_players(players)
    assert [p["name"] for p in sorted_players] == ["Amy", "Bob", "Zed"]


def test_render_players_page_math_and_title():
    doc = _players_doc(45)
    components = dashboard.render_players(doc, "Alpha", "#ABC", 1, away_set=set())
    texts = _texts(components)
    assert "## \U0001F465 Player list · Alpha" in texts
    assert "45 players · 0 away · page 2 of 3" in texts


def test_render_players_zero_players():
    components = dashboard.render_players(None, "Alpha", "#ABC", 0, away_set=set())
    texts = _texts(components)
    assert "0 players · 0 away · page 1 of 1" in texts
    assert "No players saved yet." in texts


def test_render_players_prev_disabled_on_first_page():
    doc = _players_doc(45)
    components = dashboard.render_players(doc, "Alpha", "#ABC", 0, away_set=set())
    prev = _button_by_action(components, "lazycwl_players")
    buttons = _buttons(components)
    prev_btn = buttons[0]
    next_btn = buttons[1]
    assert prev_btn.label == "⬅️ Prev"
    assert prev_btn.is_disabled is True
    assert next_btn.label == "➡️ Next"
    assert next_btn.is_disabled is False


def test_render_players_next_disabled_on_last_page():
    doc = _players_doc(45)
    components = dashboard.render_players(doc, "Alpha", "#ABC", 2, away_set=set())
    buttons = _buttons(components)
    prev_btn, next_btn = buttons[0], buttons[1]
    assert prev_btn.is_disabled is False
    assert next_btn.is_disabled is True


def test_render_players_prev_custom_id_stays_at_page_0_not_negative():
    """refuter-11 NOTED: page 0's disabled Prev built page -1 into its
    custom_id (`_decode_players_page` happened to tolerate it, but a
    disabled button should not encode a page number outside the valid
    range at all)."""
    doc = _players_doc(45)
    components = dashboard.render_players(doc, "Alpha", "#ABC", 0, away_set=set())
    buttons = _buttons(components)
    prev_btn = buttons[0]
    assert prev_btn.is_disabled is True
    assert prev_btn.custom_id == "lazycwl_players:#ABC-0"


def test_render_players_next_custom_id_stays_at_last_page_not_overflow():
    doc = _players_doc(45)
    components = dashboard.render_players(doc, "Alpha", "#ABC", 2, away_set=set())
    buttons = _buttons(components)
    next_btn = buttons[1]
    assert next_btn.is_disabled is True
    assert next_btn.custom_id == "lazycwl_players:#ABC-2"


def test_render_players_away_marks():
    doc = _players_doc(2)
    away_set = {"#P000"}
    components = dashboard.render_players(doc, "Alpha", "#ABC", 0, away_set=away_set, away_ok=True)
    text = _texts(components)
    joined = "\n".join(text)
    assert "🚪 away" in joined
    assert "🏠 here" in joined


def test_render_players_away_failure_shows_no_marks_and_note():
    doc = _players_doc(2)
    components = dashboard.render_players(doc, "Alpha", "#ABC", 0, away_set=set(), away_ok=False)
    texts = _texts(components)
    joined = "\n".join(texts)
    assert "Could not check who is away." in texts
    assert "🚪" not in joined
    assert "🏠" not in joined


def test_render_players_manual_add_marker():
    doc = _players_doc(0)
    doc["players"] = [_player("#P1", "Manual", 10, added_manually=True)]
    components = dashboard.render_players(doc, "Alpha", "#ABC", 0, away_set=set())
    joined = "\n".join(_texts(components))
    assert "➕ added by hand" in joined


def test_build_players_away_failure_falls_back(monkeypatch):
    async def fake_away_players(doc):
        raise RuntimeError("coc outage")

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)
    mongo = _FakeMongo(clan_docs=[], list_docs=[_players_doc(3)])
    components = asyncio.run(dashboard.build_players(mongo, "#ABC-0"))
    assert "Could not check who is away." in _texts(components)


def test_build_players_bare_tag_defaults_to_page_zero(monkeypatch):
    """S0's Player list button's custom_id has no page (DO NOT: unchanged
    custom_id format) - `lazycwl_players:{tag}` alone must still work."""
    async def fake_away_players(doc):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)
    mongo = _FakeMongo(clan_docs=[], list_docs=[_players_doc(3)])
    components = asyncio.run(dashboard.build_players(mongo, "#ABC"))
    assert "page 1 of 1" in "\n".join(_texts(components))


def test_render_players_component_ceiling():
    doc = _players_doc(20)
    components = dashboard.render_players(doc, "Alpha", "#ABC", 0, away_set=set())
    assert _component_count(components) <= 30


def test_render_add_result_component_ceiling():
    result = {"ok": True, "name": "Ace", "town_hall": 15, "discord_id": 1, "away_now": False, "error": None, "reason": None}
    components = dashboard.render_add_result(result, "#ABC")
    assert _component_count(components) <= 30


def test_handle_players_routes_through_build_players(monkeypatch):
    async def fake_away_players(doc):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)
    mongo = _FakeMongo(clan_docs=[], list_docs=[_players_doc(3)])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_players.__wrapped__(ctx=ctx, action_id="#ABC-0", mongo=mongo))
    assert "## \U0001F465 Player list · Alpha" in _texts(components)


# --------------------------------------------------------------- S4 Remove


def test_remove_pick_options_are_current_page():
    doc = _players_doc(25)
    components = asyncio.run(dashboard.build_remove(_FakeMongo([], [doc]), "#ABC-0"))
    menu = _select(components)
    assert len(menu.options) == 20
    values = {opt.value for opt in menu.options}
    page0_tags = {p["tag"] for p in dashboard._sorted_players(doc["players"])[:20]}
    assert values == page0_tags


def test_remove_pick_select_custom_id_and_min_max():
    doc = _players_doc(5)
    components = asyncio.run(dashboard.build_remove(_FakeMongo([], [doc]), "#ABC-0"))
    menu = _select(components)
    assert menu.custom_id == "lazycwl_remove_pick:#ABC-0"
    assert menu.min_values == 1
    assert menu.max_values == 5


def test_remove_pick_cap_at_8_and_under_100_chars_for_realistic_tags():
    """brief: cap the selection so the yes-button's custom_id can never
    exceed Discord's 100-char limit, checked with realistic (#2PP0V9Y8L
    style, 9-char) tags - the literal "8" alone does not fit at that tag
    length, so the cap must be computed, not hard-coded (see D014)."""
    page_tags = [f"#{i}PP0V9Y8L"[:10] for i in range(20)]
    cap = dashboard._remove_pick_cap("#2PP0V9Y8L", 0, page_tags)
    assert cap <= 8
    worst = sorted((t.lstrip("#") for t in page_tags), key=len, reverse=True)[:cap]
    custom_id = f"lazycwl_remove_yes:{dashboard._encode_remove_yes('#2PP0V9Y8L', 0, ['#' + t for t in worst])}"
    assert len(custom_id) <= 100


def test_remove_pick_cap_zero_for_absurd_clan_tag():
    """refuter-11 NOTED: the old `while cap > 1` floor meant cap could
    never drop to 0 even when a single player's tag would not fit - not
    reachable with real clan/player tags, but the loop should say so
    honestly. A 60-char clan tag (the brief's own figure) still leaves room
    for one 14-char (D014's realistic max) player tag under the 100-char
    budget, so an even longer (70-char) tag is used here to actually reach
    cap 0, not just prove it does not crash at 60."""
    absurd_tag = "#" + "A" * 69
    page_tags = ["#" + "P" * 14]
    cap = dashboard._remove_pick_cap(absurd_tag, 0, page_tags)
    assert cap == 0


def test_remove_pick_absurd_clan_tag_shows_pick_up_to_screen_with_no_select():
    absurd_tag = "#" + "A" * 69
    doc = _players_doc(3, clan_tag=absurd_tag)
    doc["players"] = [_player("#" + "P" * 14, "Long Tag Player", 10)]
    mongo = _FakeMongo([], [doc])
    components = asyncio.run(dashboard.build_remove(mongo, f"{absurd_tag}-0"))
    joined = "\n".join(_texts(components))
    assert "Pick up to 0" in joined
    for container in components:
        for item in container.components:
            if isinstance(item, ActionRow):
                for sub in item.components:
                    assert not isinstance(sub, TextSelectMenu)


def test_remove_pick_shows_cap_note_when_capped():
    # Force long realistic tags (#2PP0V9Y8L style) so the page needs capping
    # below the full page size to stay under the 100-char custom_id limit.
    doc = _players_doc(20, clan_tag="#2PP0V9Y8L")
    doc["players"] = [_player(f"#{i}PP0V9Y8L", f"Player {i}", 10) for i in range(20)]
    components = asyncio.run(dashboard.build_remove(_FakeMongo([], [doc]), "#2PP0V9Y8L-0"))
    menu = _select(components)
    assert menu.max_values < 20
    joined = "\n".join(_texts(components))
    assert f"Pick up to {menu.max_values} at a time." in joined


def test_remove_pick_no_active_list_shows_message_no_select_no_exception():
    """refuter-10 MUST-FIX 1: the list expired (store.get_active -> None)
    out from under a still-open panel - render_remove_pick must not build
    a zero-option select (Discord 400s on that)."""
    components = asyncio.run(dashboard.build_remove(_FakeMongo([], []), "#ABC-0"))
    joined = "\n".join(_texts(components))
    assert "No saved list for this clan." in joined
    for container in components:
        for item in container.components:
            if isinstance(item, ActionRow):
                for sub in item.components:
                    assert not isinstance(sub, TextSelectMenu)


def test_remove_pick_empty_player_list_shows_message_no_select():
    doc = _players_doc(0)
    components = asyncio.run(dashboard.build_remove(_FakeMongo([], [doc]), "#ABC-0"))
    joined = "\n".join(_texts(components))
    assert "No players to remove." in joined
    for container in components:
        for item in container.components:
            if isinstance(item, ActionRow):
                for sub in item.components:
                    assert not isinstance(sub, TextSelectMenu)


def test_remove_pick_stale_page_beyond_range_clamps_to_last_page_with_options():
    """A page number from before another admin removed players down to one
    page - the pick screen must clamp, not build an empty select."""
    doc = _players_doc(3)
    components = asyncio.run(dashboard.build_remove(_FakeMongo([], [doc]), "#ABC-5"))
    menu = _select(components)
    assert len(menu.options) == 3


def test_remove_pick_cap_holds_end_to_end_through_confirm_custom_id():
    """Renders the real pick screen for 20 players with 14-char tag bodies
    (the modal's max_length is 15), reads the real menu's max_values, picks
    that many of the page's longest tags, and renders the confirm screen
    through build_remove_confirm - the same code path the handler uses.
    The rendered Yes button's custom_id must stay under Discord's 100-char
    limit (refuter-10 MUST-FIX 2). Proof this actually guards the cap:
    hard-coding render_remove_pick's cap to REMOVE_MAX_PICK (bypassing
    _remove_pick_cap) makes this fail while the existing flat-cap
    assertions in test_remove_pick_cap_at_8_and_under_100_chars_for_realistic_tags
    keep passing, because that test only checks _remove_pick_cap in
    isolation, not the render+confirm round trip."""
    doc = _players_doc(20, clan_tag="#ABC")
    doc["players"] = [
        _player("#" + (f"P{i:02d}" + "X" * 20)[:14], f"Player {i}", 10)
        for i in range(20)
    ]
    mongo = _FakeMongo([], [doc])
    components = asyncio.run(dashboard.build_remove(mongo, "#ABC-0"))
    menu = _select(components)
    page_players = dashboard._sorted_players(doc["players"])[:20]
    longest = sorted(page_players, key=lambda p: len(p["tag"]), reverse=True)[:menu.max_values]
    chosen_tags = [p["tag"] for p in longest]
    confirm = asyncio.run(dashboard.build_remove_confirm(mongo, "#ABC-0", chosen_tags))
    yes = _button_by_action(confirm, "lazycwl_remove_yes")
    assert len(yes.custom_id) <= 100


def test_remove_confirm_rows_and_back_button():
    doc = _players_doc(3)
    mongo = _FakeMongo([], [doc])
    chosen_tags = [doc["players"][0]["tag"], doc["players"][1]["tag"]]
    components = asyncio.run(dashboard.build_remove_confirm(mongo, "#ABC-0", chosen_tags))
    texts = _texts(components)
    assert "## \U0001F5D1️ Remove 2 players?" in texts
    joined = "\n".join(texts)
    assert doc["players"][0]["name"] in joined and doc["players"][0]["tag"] in joined
    assert "They will not get reminders any more." in texts
    back = _button_by_action(components, "lazycwl_players")
    assert back.custom_id == "lazycwl_players:#ABC-0"
    yes = _button_by_action(components, "lazycwl_remove_yes")
    assert yes.custom_id.startswith("lazycwl_remove_yes:#ABC-0-")


def test_handle_remove_pick_reads_values_and_builds_confirm(monkeypatch):
    doc = _players_doc(3)
    mongo = _FakeMongo([], [doc])
    ctx = _FakeHandlerCtx(values=[doc["players"][0]["tag"]])
    components = asyncio.run(dashboard.handle_remove_pick.__wrapped__(ctx=ctx, action_id="#ABC-0", mongo=mongo))
    assert "## \U0001F5D1️ Remove 1 player?" in _texts(components)


def test_remove_yes_calls_store_with_hash_prefixed_tags(monkeypatch):
    doc = _players_doc(3)
    mongo = _FakeMongo([], [doc])
    calls = []
    real_remove_players = dashboard.store.remove_players

    async def spy_remove_players(mongo_arg, clan_tag, tags):
        calls.append((clan_tag, list(tags)))
        return await real_remove_players(mongo_arg, clan_tag, tags)

    monkeypatch.setattr(dashboard.store, "remove_players", spy_remove_players)

    async def fake_away_players(d):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)

    chosen = [doc["players"][0]["tag"], doc["players"][1]["tag"]]
    action_id = dashboard._encode_remove_yes("#ABC", 0, chosen)
    components = asyncio.run(dashboard.build_remove_yes(mongo, action_id))
    assert calls == [("#ABC", [doc["players"][0]["tag"], doc["players"][1]["tag"]])]
    assert all(t.startswith("#") for _, tags in calls for t in tags)
    joined = "\n".join(_texts(components))
    assert "\U0001F5D1️ Removed 2 players." in joined


def test_remove_yes_mismatch_message(monkeypatch):
    doc = _players_doc(3)
    mongo = _FakeMongo([], [doc])

    async def fake_away_players(d):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)

    action_id = dashboard._encode_remove_yes("#ABC", 0, [doc["players"][0]["tag"], "#GONE123"])
    components = asyncio.run(dashboard.build_remove_yes(mongo, action_id))
    joined = "\n".join(_texts(components))
    assert "\U0001F5D1️ Removed 1 player." in joined
    assert "1 were already gone." in joined


def test_remove_yes_clamps_page_after_removing_last_item_on_last_page(monkeypatch):
    doc = _players_doc(21)  # page 0: 20 players, page 1: 1 player
    mongo = _FakeMongo([], [doc])

    async def fake_away_players(d):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)

    last_player_tag = dashboard._sorted_players(doc["players"])[20]["tag"]
    action_id = dashboard._encode_remove_yes("#ABC", 1, [last_player_tag])
    components = asyncio.run(dashboard.build_remove_yes(mongo, action_id))
    joined = "\n".join(_texts(components))
    assert "page 1 of 1" in joined


def test_remove_yes_malformed_action_id_renders_error_not_raises():
    """refuter-10 NOTED: `_decode_remove_yes` malformed input should land
    on the same render_error screen its S3 siblings use, not raise."""
    mongo = _FakeMongo([], [])
    for action_id in ("#ABC-0", "#ABC-abc-111"):
        components = asyncio.run(dashboard.build_remove_yes(mongo, action_id))
        assert "## ❌ Error" in _texts(components)


def test_handle_remove_and_handle_remove_yes_registered(monkeypatch):
    mongo = _FakeMongo([], [_players_doc(3)])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_remove.__wrapped__(ctx=ctx, action_id="#ABC-0", mongo=mongo))
    assert "Pick the players to remove from the list." in _texts(components)


# --------------------------------------------------------------- S5 Add player


def test_add_modal_opens_with_expected_fields():
    class _FakeModalOpenCtx:
        def __init__(self):
            self.modal_calls = []

        async def respond_with_modal(self, title, custom_id, components):
            self.modal_calls.append((title, custom_id, components))

    ctx = _FakeModalOpenCtx()
    asyncio.run(dashboard.handle_add.__wrapped__(ctx=ctx, action_id="#ABC"))
    assert len(ctx.modal_calls) == 1
    title, custom_id, components = ctx.modal_calls[0]
    assert title == "Add a player"
    assert custom_id == "lazycwl_add_submit:#ABC"
    row = components[0]
    field = row.components[0]
    assert field.custom_id == "player_tag"
    assert field.placeholder == "#ABC123"
    assert field.min_length == 3
    assert field.max_length == 15
    assert field.is_required is True


def test_add_result_ok_with_link():
    result = {"ok": True, "name": "Ace", "town_hall": 15, "discord_id": 123, "away_now": True, "error": None, "reason": None}
    texts = _texts(dashboard.render_add_result(result, "#ABC"))
    joined = "\n".join(texts)
    assert "✅ **Ace** · Town Hall 15 · 🚪 away now" in joined
    assert "Linked to <@123>" in joined


def test_add_result_ok_without_link():
    result = {"ok": True, "name": "Ace", "town_hall": 15, "discord_id": None, "away_now": False, "error": None, "reason": None}
    texts = _texts(dashboard.render_add_result(result, "#ABC"))
    joined = "\n".join(texts)
    assert "🏠 here" in joined
    assert "No Discord link found." in joined


def test_add_result_link_service_down():
    result = {"ok": True, "name": "Ace", "town_hall": 15, "discord_id": None, "away_now": False, "error": None, "reason": "link_service_down"}
    joined = "\n".join(_texts(dashboard.render_add_result(result, "#ABC")))
    assert "Could not check the Discord link. Try again later." in joined


def test_add_result_every_error_reason():
    cases = {
        "invalid_tag": "That does not look like a player tag. Example: #ABC123",
        "not_found": "No player has that tag.",
        "no_list": "No saved list for this clan.",
    }
    for reason, expected in cases.items():
        result = {"ok": False, "name": None, "error": "generic", "reason": reason}
        joined = "\n".join(_texts(dashboard.render_add_result(result, "#ABC")))
        assert expected in joined


def test_add_result_already_listed_uses_name():
    result = {"ok": False, "name": "Ace", "error": "Ace is already on the list.", "reason": "already_listed"}
    joined = "\n".join(_texts(dashboard.render_add_result(result, "#ABC")))
    assert "**Ace** is already on the list." in joined


def test_add_result_falls_back_to_service_error():
    result = {"ok": False, "name": None, "error": "Something odd happened.", "reason": None}
    joined = "\n".join(_texts(dashboard.render_add_result(result, "#ABC")))
    assert "Something odd happened." in joined


def test_add_result_buttons():
    components = dashboard.render_add_result({"ok": False, "error": "x", "reason": None}, "#ABC")
    assert _button_by_action(components, "lazycwl_add").custom_id == "lazycwl_add:#ABC"
    assert _button_by_action(components, "lazycwl_players").custom_id == "lazycwl_players:#ABC-0"
    assert _button_by_action(components, "lazycwl_home").custom_id == "lazycwl_home:#ABC"


def test_build_add_result_calls_service_with_clan_and_player_tag(monkeypatch):
    calls = []

    async def fake_add_player_by_tag(clan_tag, tag):
        calls.append((clan_tag, tag))
        return {"ok": True, "name": "Ace", "town_hall": 10, "discord_id": None, "away_now": False, "error": None, "reason": None}

    monkeypatch.setattr(dashboard.service, "add_player_by_tag", fake_add_player_by_tag)
    components = asyncio.run(dashboard.build_add_result("#ABC", "#P1"))
    assert calls == [("#ABC", "#P1")]
    assert "## ➕ Add player" in _texts(components)


def test_build_add_result_service_exception_becomes_error(monkeypatch):
    async def fake_add_player_by_tag(clan_tag, tag):
        raise RuntimeError("coc outage")

    monkeypatch.setattr(dashboard.service, "add_player_by_tag", fake_add_player_by_tag)
    components = asyncio.run(dashboard.build_add_result("#ABC", "#P1"))
    assert "coc outage" in "\n".join(_texts(components))


def test_build_add_result_empty_or_whitespace_skips_service_call(monkeypatch):
    """refuter-10 NOTED: an empty/whitespace modal submission should never
    hit the service - the recording fake below asserts zero calls."""
    calls = []

    async def fake_add_player_by_tag(clan_tag, tag):
        calls.append((clan_tag, tag))
        return {"ok": True, "name": "Ace", "town_hall": 10, "discord_id": None, "away_now": False, "error": None, "reason": None}

    monkeypatch.setattr(dashboard.service, "add_player_by_tag", fake_add_player_by_tag)
    for value in ("", "   "):
        components = asyncio.run(dashboard.build_add_result("#ABC", value))
        joined = "\n".join(_texts(components))
        assert "That does not look like a player tag. Example: #ABC123" in joined
    assert calls == []


def test_handle_add_submit_reads_modal_field_and_edits_response(monkeypatch):
    class _FakeModalField:
        def __init__(self, custom_id, value):
            self.custom_id = custom_id
            self.value = value

    class _FakeModalInteraction:
        def __init__(self, fields):
            self.components = [[_FakeModalField(cid, val) for cid, val in fields]]
            self.deferred_type = None
            self.edited = []

        async def create_initial_response(self, response_type):
            self.deferred_type = response_type

        async def edit_initial_response(self, components):
            self.edited.append(components)

    class _FakeModalSubmitCtx:
        def __init__(self, fields):
            self.interaction = _FakeModalInteraction(fields)

    async def fake_add_player_by_tag(clan_tag, tag):
        assert clan_tag == "#ABC"
        assert tag == "#P1"
        return {"ok": True, "name": "Ace", "town_hall": 10, "discord_id": None, "away_now": False, "error": None, "reason": None}

    monkeypatch.setattr(dashboard.service, "add_player_by_tag", fake_add_player_by_tag)

    ctx = _FakeModalSubmitCtx([("player_tag", "#P1")])
    mongo = _FakeMongo([], [])
    asyncio.run(dashboard.handle_add_submit.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert ctx.interaction.deferred_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    assert len(ctx.interaction.edited) == 1
    assert "Ace" in "\n".join(_texts(ctx.interaction.edited[0]))


# --------------------------------------------------------------- refuter-09 cleanup


def test_decode_auto_on_malformed_returns_none():
    assert dashboard._decode_auto_on("ALL") is None
    assert dashboard._decode_auto_on("#ABC-") is None
    assert dashboard._decode_auto_on("#ABC-abc") is None
    assert dashboard._decode_auto_on("#ABC-999") is None  # not in AUTO_REMINDER_CHOICES


def test_build_auto_turn_on_malformed_action_id_renders_error_screen():
    mongo = _FakeMongo([], [])
    components = asyncio.run(dashboard.build_auto_turn_on(mongo, "malformed"))
    joined = "\n".join(_texts(components))
    assert "Something went wrong. Press Home." in joined


def test_handle_auto_every_rejects_non_choice_value():
    mongo = _FakeMongo([], [_list_doc("#ABC", "Alpha")])
    ctx = _FakeHandlerCtx(values=["999"])
    components = asyncio.run(dashboard.handle_auto_every.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    joined = "\n".join(_texts(components))
    assert "Something went wrong. Press Home." in joined


def test_handle_auto_on_handler_level(monkeypatch):
    calls = []

    async def fake_set_reminders(clan_tag, enabled, every_minutes=None):
        calls.append((clan_tag, enabled, every_minutes))
        return {"ok": True, "error": None}

    monkeypatch.setattr(dashboard.service, "set_reminders", fake_set_reminders)
    mongo = _FakeMongo(clan_docs=[], list_docs=[_list_doc("#ABC", "Alpha")])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_auto_on.__wrapped__(ctx=ctx, action_id="#ABC-60", mongo=mongo))
    assert calls == [("#ABC", True, 60)]
    assert "on, every 60 minutes" in "\n".join(_texts(components))


def test_handle_auto_off_handler_level(monkeypatch):
    calls = []

    async def fake_set_reminders(clan_tag, enabled, every_minutes=None):
        calls.append((clan_tag, enabled, every_minutes))
        return {"ok": True, "error": None}

    monkeypatch.setattr(dashboard.service, "set_reminders", fake_set_reminders)
    doc = _list_doc("#ABC", "Alpha", reminders={"enabled": True, "every_minutes": 60})
    mongo = _FakeMongo(clan_docs=[], list_docs=[doc])
    ctx = _FakeHandlerCtx()
    components = asyncio.run(dashboard.handle_auto_off.__wrapped__(ctx=ctx, action_id="#ABC", mongo=mongo))
    assert calls == [("#ABC", False, None)]
    assert "off" in "\n".join(_texts(components))


def test_render_auto_result_uses_result_name_helper():
    """refuter-09 NOTED 3: render_auto_result must not re-inline the
    clan_name-or-clan_tag fallback that _result_name already does."""
    results = [{"ok": True, "clan_name": None, "clan_tag": "#XYZ", "error": None}]
    joined = "\n".join(_texts(dashboard.render_auto_result(results, "#XYZ", turning_on=False)))
    assert "**#XYZ**" in joined

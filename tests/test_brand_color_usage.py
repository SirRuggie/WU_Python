"""Live bot cards use the brand colors (WU_GOLD, WU_GREEN, WU_RED), not the old accents."""

import re
from pathlib import Path

import hikari

from extensions.commands import todo
from utils import recruit_question_content as content
from utils.constants import GOLDENROD_ACCENT, WU_GOLD, WU_RED
from utils.emoji import emojis

ROOT = Path(__file__).resolve().parents[1]
OLD = re.compile(r"\b(RED|GOLD|BLUE|GREEN|MAGENTA|GOLDENROD)_ACCENT\b")

# Code the running bot does not load or reach (retired, disabled previews,
# unregistered slash commands, legacy tickets), plus the one deliberate
# read of the old goldenrod for templates saved before the change.
ALLOWED = {
    "extensions/commands/cards.py",
    "extensions/commands/cards_bulk_preview.py",
    "extensions/commands/cards_preview.py",
    "extensions/commands/clan/info_hub/explanations.py",
    "extensions/commands/clan/info_hub/handlers.py",
    "extensions/commands/clan/info_hub/info.py",
    "extensions/commands/clan/list.py",
    "extensions/commands/lazyprep.py",
    "extensions/commands/poll_bar_preview.py",
    "extensions/commands/tickets/manage.py",
    "extensions/commands/tickets/migrate.py",
    "extensions/commands/tickets/setup.py",
    "extensions/commands/tickets_legacy/close.py",
    "extensions/commands/tickets_legacy/config.py",
    "extensions/commands/tickets_legacy/handlers.py",
    "extensions/commands/tickets_legacy/manage.py",
    "extensions/commands/tickets_legacy/migrate.py",
    "extensions/commands/tickets_legacy/setup.py",
    "extensions/tasks/cards_deadlines.py",
    "extensions/tasks/cards_sticky.py",
    "utils/constants.py",
    "utils/recruit_question_content.py",
}


def test_live_code_does_not_use_old_accent_constants():
    offenders = []
    for folder in ("extensions", "utils"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if relative not in ALLOWED and OLD.search(path.read_text(encoding="utf-8")):
                offenders.append(relative)
    if OLD.search((ROOT / "main.py").read_text(encoding="utf-8")):
        offenders.append("main.py")
    assert offenders == []


def test_todo_urgency_uses_red_gold_or_no_accent():
    assert todo._urgency_accent(None) is hikari.UNDEFINED


def test_saved_goldenrod_and_new_gold_templates_both_get_gold_arrows():
    text = f"{emojis.red_arrow_right} Step"
    for accent in (int(WU_GOLD), int(GOLDENROD_ACCENT)):
        assert str(emojis.gold_arrow_right) in content._accent_arrows(text, accent)
    assert content._accent_arrows(text, int(WU_RED)) == text


def test_todo_urgency_red_within_two_hours_gold_within_twelve():
    import time
    from types import SimpleNamespace

    def view(seconds):
        row = SimpleNamespace(state="inWar", ends_at=int(time.time()) + seconds)
        return SimpleNamespace(ok=True, rows=[row])

    assert todo._urgency_accent(view(60 * 60)) == WU_RED
    assert todo._urgency_accent(view(6 * 60 * 60)) == WU_GOLD
    assert todo._urgency_accent(view(24 * 60 * 60)) is hikari.UNDEFINED


def test_todo_failure_notices_are_red_and_plain_notices_gold():
    source = (ROOT / "extensions/commands/todo.py").read_text(encoding="utf-8")
    for title in ("Link service not available", "Clash is in maintenance", "Couldn't load your accounts"):
        call = source[source.index(title):].split("), None", 1)[0]
        assert "accent=WU_RED" in call, title
    no_links = source[source.index('"No linked accounts"'):].split("), None", 1)[0]
    assert "accent=" not in no_links
    assert todo._notice("T", "B")[0].accent_color == WU_GOLD


def test_lazycwl_refusals_and_expired_reviews_are_red():
    source = (ROOT / "extensions/commands/lazycwl_dashboard.py").read_text(encoding="utf-8")
    calls = re.findall(r'_notice\("(?:Access denied|Retry expired|Review expired)"[^\n]*', source)
    assert len(calls) > 10
    assert all("accent=WU_RED" in call for call in calls)


def test_destructive_confirms_are_red():
    from extensions.commands import warrior

    panel = warrior.confirm({"_id": "s"}, "clear_clans:t", "Remove every clan role?")
    assert panel[0].accent_color == WU_RED
    for path, marker in (
        ("extensions/commands/goldrush.py", "Confirm Gold Rush schedule"),
        ("extensions/commands/cwl_member.py", 'WU_RED if session.screen == "withdraw_confirm"'),
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert marker in source
    goldrush = (ROOT / "extensions/commands/goldrush.py").read_text(encoding="utf-8")
    head = goldrush[: goldrush.index("Confirm Gold Rush schedule")]
    assert head.rstrip().rsplit("Container(", 1)[1].startswith("accent_color=WU_RED")


def test_error_panels_are_red():
    loot = (ROOT / "extensions/commands/loot_leaderboard.py").read_text(encoding="utf-8")
    head = loot[: loot.index("saved gold loot test data is not available")]
    assert head.rsplit("Container(", 1)[1].startswith("accent_color=WU_RED")
    member = (ROOT / "extensions/commands/cwl_member.py").read_text(encoding="utf-8")
    assert member.count("accent=WU_RED)") == 3


def test_todo_footer_matches_card_accent():
    assert todo._footer_for(WU_RED) == "assets/Red_Footer.png"
    assert todo._footer_for(WU_GOLD) == "assets/Gold_Footer.png"
    assert todo._footer_for(hikari.UNDEFINED) == "assets/Gold_Footer.png"
    source = (ROOT / "extensions/commands/todo.py").read_text(encoding="utf-8")
    assert source.count('MediaItem(media=_footer_for(accent))') == 1
    assert "Gold_Footer.png\")]" not in source


def test_strikes_and_weight_failures_are_red():
    from extensions.commands import strikes

    assert strikes.panel("Strike", "x")[0].accent_color == WU_GOLD
    assert strikes.panel("Strike", "x", accent=WU_RED)[0].accent_color == WU_RED
    source = (ROOT / "extensions/commands/strikes.py").read_text(encoding="utf-8")
    for text in ("This view expired", "This selection expired", "Player lookup is unavailable",
                 "Account links changed", "Select FWA clans only"):
        line = next(line for line in source.splitlines() if text in line and "panel(" in line)
        assert "accent=WU_RED" in line, text
    weight = (ROOT / "extensions/commands/fwa/weight_save.py").read_text(encoding="utf-8")
    assert "card(str(exc), accent=WU_RED)" in weight and "card(str(error), accent=WU_RED)" in weight


def test_templates_saved_with_old_default_footers_still_load_as_gold():
    import copy

    checked = 0
    for variant in content.VARIANTS:
        default = content.default_template(variant)
        for legacy in ("assets/Red_Footer.png", "assets/Blue_Footer.png"):
            saved = copy.deepcopy(default)
            if saved.get("footer_url") == "assets/Gold_Footer.png":
                saved["footer_url"] = legacy
            for slot, value in (saved.get("media") or {}).items():
                if value == "assets/Gold_Footer.png":
                    saved["media"][slot] = legacy
            if saved == default:
                continue
            checked += 1
            loaded = content.validate_template(variant, saved)
            assert loaded.get("footer_url") in (None, default.get("footer_url"))
            assert loaded.get("media", {}) == default.get("media", {})
    assert checked >= 12  # leaders_checking_you_out plus the native layouts


def test_other_local_artwork_is_still_rejected():
    import copy

    import pytest

    saved = copy.deepcopy(content.default_template("leaders_checking_you_out"))
    saved["footer_url"] = "assets/Green_Footer.png"
    with pytest.raises(ValueError):
        content.validate_template("leaders_checking_you_out", saved)

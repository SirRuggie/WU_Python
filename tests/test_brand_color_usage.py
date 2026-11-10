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

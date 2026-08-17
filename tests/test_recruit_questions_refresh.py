"""The questions-panel refresh: one shared delay, safely inside Discord's window.

Each of the four dropdown handlers in /recruit questions deletes and re-sends
the ephemeral panel after a wait. That wait runs on the component interaction's
token, which Discord invalidates 15 minutes after the click - so the delay must
stay under that ceiling, and all four sections are meant to move together.
"""

import re
from pathlib import Path

from extensions.commands.recruit.questions import PANEL_REFRESH_DELAY_SECONDS

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_SOURCE = ROOT / "extensions" / "commands" / "recruit" / "questions.py"


def test_refresh_delay_is_ten_minutes_inside_the_token_window():
    assert PANEL_REFRESH_DELAY_SECONDS == 600
    # 15-minute token lifetime, minus margin for the pre-sleep work.
    assert PANEL_REFRESH_DELAY_SECONDS <= 14 * 60


def test_every_panel_refresh_uses_the_shared_delay():
    source = QUESTIONS_SOURCE.read_text(encoding="utf-8")
    assert source.count("asyncio.sleep(PANEL_REFRESH_DELAY_SECONDS)") == 4
    # No handler may drift back to a literal per-section delay.
    assert re.findall(r"asyncio\.sleep\(\s*\d", source) == []

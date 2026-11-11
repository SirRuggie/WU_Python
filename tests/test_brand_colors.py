"""The bot's primary brand colors must match the dashboard tokens."""

import re
from pathlib import Path

from utils import constants

TOKENS = Path(__file__).resolve().parents[1] / "web" / "cwl" / "src" / "tokens.css"


def _token(name: str) -> int:
    match = re.search(rf"--{name}:\s*#([0-9a-fA-F]{{6}})\s*;", TOKENS.read_text())
    assert match, f"--{name} not found in tokens.css"
    return int(match.group(1), 16)


def test_brand_colors_match_dashboard_tokens():
    assert int(constants.WU_GOLD) == _token("wu-accent")
    assert int(constants.WU_GREEN) == _token("wu-success")
    assert int(constants.WU_GREEN) == _token("wu-success-border")
    assert int(constants.WU_RED) == _token("wu-brand-red")

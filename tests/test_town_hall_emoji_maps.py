import re
from pathlib import Path

from utils.emoji import emojis

ROOT = Path(__file__).resolve().parents[1]


def _bot_ids() -> dict[int, str]:
    ids = {}
    for level in range(2, 30):
        entry = getattr(emojis, f"TH{level}", None)
        if entry is not None:
            ids[level] = str(entry).rsplit(":", 1)[1].rstrip(">")
    return ids


def test_th19_uses_the_wu_wizard_emoji():
    assert str(emojis.TH19) == "<:TH_19:1571021740375806063>"
    assert emojis.TH19.partial_emoji.name == "TH_19"


def test_dashboard_town_hall_ids_match_the_bot():
    source = (ROOT / "web/cwl/src/TownHallIcon.tsx").read_text()
    dashboard = {int(level): emoji_id for level, emoji_id in re.findall(r'"(\d+)":\s*"(\d+)"', source)}
    assert dashboard == _bot_ids()

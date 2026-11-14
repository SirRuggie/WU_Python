import re
from pathlib import Path

import hikari

from utils.emoji import emojis

ROOT = Path(__file__).resolve().parents[1]


def _bot_ids() -> dict[int, str]:
    ids = {}
    for level in range(2, 30):
        entry = getattr(emojis, f"TH{level}", None)
        if entry is not None:
            ids[level] = str(entry).rsplit(":", 1)[1].rstrip(">")
    return ids


def test_th19_uses_the_th_19a_emoji():
    assert str(emojis.TH19) == "<:TH_19A:1571025137896005783>"
    assert emojis.TH19.partial_emoji.name == "TH_19A"


def test_configured_th19a_wins_over_other_th_19_emojis():
    from utils import war_weight

    config = war_weight.edit_entry(war_weight.defaults(), 19, 181000, 190000)
    server = hikari.CustomEmoji(id=1571022253431459922, name="TH_19", is_animated=False)
    chosen = hikari.CustomEmoji(id=1571025137896005783, name="TH_19A", is_animated=False)
    assert war_weight.emoji_for(19, config, [server, chosen]) == str(chosen)
    assert war_weight.emoji_for(19, config, [server]) == str(server)


def test_dashboard_town_hall_ids_match_the_bot():
    source = (ROOT / "web/cwl/src/TownHallIcon.tsx").read_text()
    dashboard = {int(level): emoji_id for level, emoji_id in re.findall(r'"(\d+)":\s*"(\d+)"', source)}
    assert dashboard == _bot_ids()

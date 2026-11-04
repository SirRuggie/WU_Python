"""Plain staff errors keep the capture category and safe diagnostic reason."""
import asyncio
from copy import deepcopy
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cwl_web import participation_sync as sync


@pytest.mark.parametrize("field,value,message,reason", [
    ("rounds", None, "Clash has not sent the rounds for this CWL group yet.", "invalid_rounds"),
    ("rounds", [{}], "Clash has not sent the war tags for this round yet.", "invalid_round_tags"),
    ("clans", None, "Clash has not sent the clan list for this CWL group yet.", "invalid_clan_roster"),
])
def test_invalid_group_keeps_its_category_and_exact_safe_reason(field, value, message, reason, caplog):
    group = {"state": "PREPARATION", "season": "2026-11", "rounds": [], "clans": [{"tag": "#C2Y", "members": []}]}
    group[field] = value
    original = deepcopy(group)
    with pytest.raises(ValueError, match="^" + __import__("re").escape(message) + "$"):
        sync._valid_group(group, "2026-11", "#C2Y")
    provider = SimpleNamespace(league_group=AsyncMock(return_value=group))
    with caplog.at_level(logging.INFO, logger="cwl_web.participation_sync"):
        rows = asyncio.run(sync._fetch_groups(provider, ["#C2Y"], "2026-11"))
    assert rows == [("#C2Y", None, "unavailable")]
    assert f"reason={reason} " in caplog.text
    assert "category=unavailable" in caplog.text
    assert message not in caplog.text  # Diagnostics never log external prose.
    assert group == original
    provider.league_group.assert_awaited_once_with("#C2Y")


def test_month_error_says_which_month_to_check():
    with pytest.raises(ValueError, match="The CWL month from Clash does not match the month set here"):
        sync._valid_group({"season": "2026-10"}, "2026-11", "#C2Y")

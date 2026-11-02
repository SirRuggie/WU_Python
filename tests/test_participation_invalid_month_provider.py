"""Real league_group parsing over injected HTTP bodies; no live API calls."""

import asyncio
import logging
from copy import deepcopy
from unittest.mock import patch
import pytest
from cwl_web import participation_sync as sync
from cwl_web.providers import LiveProviders
from test_cwl_web_league_provider import Response
from test_participation_waiting import November

ABSENT = object()
VALUES = [ABSENT, None, "", " ", "2026-11-01", "202611", "November", "2026-13"]


def body(state, season):
    result = {
        "state": state,
        "rounds": [{"warTags": ["#Y2Y"]}],
        "clans": [
            {
                "tag": "#C2Y",
                "name": "Fixture",
                "members": [{"tag": "#P2Y", "name": "Fixture", "townHallLevel": 16}],
            }
        ],
    }
    if season is not ABSENT:
        result["season"] = season
    return result


async def capture(raw, *, cycle="2026-11", known=None):
    original = deepcopy(raw)
    calls = []

    class HTTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def get(self, url, **kwargs):
            calls.append(url)
            return Response(
                raw
                if url.endswith("/leaguegroup")
                else {"tag": "#C2Y", "name": "Fixture"}
            )

    provider = LiveProviders(coc_token="fixture", mongo_uri="", routes={})
    with patch(
        "cwl_web.providers.aiohttp.ClientSession", side_effect=lambda **kw: HTTP()
    ), patch.object(sync, "datetime", November):
        result = (await sync._fetch_groups(provider, ["#C2Y"], cycle, known))[0]
    assert raw == original, "Provider evidence must stay unchanged"
    assert calls and calls[0].endswith("/currentwar/leaguegroup")
    return result


@pytest.mark.parametrize("state", ["PREPARATION", "inWar", "warEnded", "ended"])
@pytest.mark.parametrize(
    "season",
    VALUES,
    ids=["absent", "null", "empty", "space", "date", "compact", "word", "badmonth"],
)
def test_real_parser_unreadable_month_active_infers_but_ended_waits(
    state, season, caplog
):
    with caplog.at_level(logging.INFO):
        row = asyncio.run(capture(body(state, season)))
    if state in {"warEnded", "ended"} and season != "2026-11-01":
        assert row[1] is None and row[2] == "no_group"
    else:
        assert row[1] is not None and row[2] is None
    text = caplog.text
    kind = (
        "none"
        if season is ABSENT or season is None
        else (
            "empty" if season == "" else "date" if season == "2026-11-01" else "invalid"
        )
    )
    assert "season_kind=" + kind in text
    if kind == "invalid":
        expected = "".join(
            "d" if c.isdigit() else "a" if c.isalpha() else "x" for c in season[:12]
        )
        assert "season_shape=" + expected in text
        assert "season_shape=" + season not in text


@pytest.mark.parametrize("season", [value for value in VALUES if value != "2026-11-01"])
def test_real_parser_unreadable_ended_requires_own_tag_containment(season):
    raw = body("warEnded", season)
    known = {"#C2Y": {"rounds": [{"war_tags": ["#Y2Y"]}]}}
    row = asyncio.run(capture(raw, known=known))
    assert row[1] is not None and row[1][2] == "ENDED" and row[2] is None
    for tags in [[], ["#V2Y"], ["#Y2Y", "#V2Y"]]:
        row = asyncio.run(
            capture(raw, known={"#C2Y": {"rounds": [{"war_tags": tags}]}})
        )
        assert row[1] is None and row[2] == "no_group"


@pytest.mark.parametrize("state", ["PREPARATION", "inWar", "warEnded", "ended"])
def test_real_parser_valid_older_month_always_wins(state, caplog):
    with caplog.at_level(logging.INFO):
        row = asyncio.run(capture(body(state, "2026-10")))
    assert row[1] is None and row[2] == "season_older"
    assert (
        "season_kind=valid" in caplog.text
        and "inferred_current=True" not in caplog.text
    )


@pytest.mark.parametrize("state", ["PREPARATION", "inWar", "warEnded", "ended"])
def test_real_parser_future_unreadable_month_waits_without_inference(state):
    row = asyncio.run(capture(body(state, "not-a-month"), cycle="2026-12"))
    assert row[1] is None and row[2] == "no_group"


def test_invalid_shape_is_masked_capped_and_raw_text_never_logged(caplog):
    secret = "2026-November-RAW/@everyone\nprivate"
    with caplog.at_level(logging.INFO):
        row = asyncio.run(capture(body("PREPARATION", secret)))
    assert row[1] is not None
    text = caplog.text
    assert (
        secret not in text
        and "RAW" not in text
        and "@everyone" not in text
        and "private" not in text
    )
    assert "season_shape=ddddxaaaaaaa" in text
    assert sync._group_season_diagnostic(secret) == ("invalid", "ddddxaaaaaaa")


@pytest.mark.parametrize("season", [False, 0, [], {}])
def test_real_provider_rejects_non_string_month_without_inference(season, caplog):
    with caplog.at_level(logging.INFO):
        row = asyncio.run(capture(body("PREPARATION", season)))
    assert row[1] is None and row[2] == "unavailable"
    assert "inferred_current=True" not in caplog.text


@pytest.mark.parametrize(
    "season,category", [("2026-11", None), ("2026-12", "season_later")]
)
def test_real_provider_valid_current_and_later_month_win(season, category):
    row = asyncio.run(capture(body("PREPARATION", season)))
    assert row[2] == category
    assert (row[1] is not None) == (category is None)

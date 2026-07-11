"""Tests for the FWA points page parser, against real captured markup."""

import pytest
from utils.fwa_points_parser import parse_clan_points, sanitize_tag, is_newer_war, FwaPointsParseError

FIXTURE = (
    '<!doctype html><html><head><title>FWA Points: Clan Edrag Rush</title></head><body>'
    '<h3>Viewing Clan</h3>'
    '<p><b>Clan Name</b>: Edrag Rush<br>'
    '<b>Clan Tag</b>: 2PPCL2GYP (<a href="https://cc.fwafarm.com/cc_n/clan.php?tag=2PPCL2GYP">ChocolateClash</a>)<br><br>'
    '<b>Point Balance</b>: 11<br><br><b>Active FWA</b>: Yes<br></p>'
    '<p class="winner-box">Win Calculator for <a href="/war?id=119224">War #119224</a> in Sync #532<br><br>'
    'Edrag Rush (<a href="/clan?tag=2PPCL2GYP">2PPCL2GYP</a>) vs. DARK EMPIRE™! '
    '(<a href="/clan?tag=R80L8VYG">R80L8VYG</a>):<br><br>'
    '<b>Edrag Rush</b> should win by points (11 &gt; 9)</p>'
    '<div class="current-box"><b>Last Known War State</b>: preparation<br><br></div>'
    '</body></html>'
)


def test_extracts_all_fields():
    d = parse_clan_points(FIXTURE, "2PPCL2GYP")
    assert d["opponent_tag"] == "R80L8VYG"          # the hard-gate field
    assert d["war_number"] == 119224
    assert d["sync_number"] == 532
    assert d["point_balance"] == 11
    assert d["active_fwa"] is True
    assert d["clan_name"] == "Edrag Rush"
    assert d["last_war_state"] == "preparation"
    assert d["raw_verdict"] == "Edrag Rush should win by points (11 > 9)"
    assert d["opponent_name"] == "DARK EMPIRE™!"


@pytest.mark.parametrize("our", ["2PPCL2GYP", "#2ppcl2gyp", " 2PPCL2GYP "])
def test_opponent_is_the_non_ours_tag(our):
    # Opponent is identified as the box tag that is not ours, regardless of #/case.
    assert parse_clan_points(FIXTURE, our)["opponent_tag"] == "R80L8VYG"


def test_missing_winner_box_raises():
    with pytest.raises(FwaPointsParseError):
        parse_clan_points("<html><body><p>no calculator here</p></body></html>", "2PPCL2GYP")


@pytest.mark.parametrize("raw,expected", [
    ("#R80L8VYG", "R80L8VYG"), ("r80l8vyg", "R80L8VYG"), ("", ""), (None, ""),
])
def test_sanitize_tag(raw, expected):
    assert sanitize_tag(raw) == expected


@pytest.mark.parametrize("prev,parsed,expected", [
    (None, {"war_number": 119224}, True),                    # nothing stored yet
    ({"war_number": None}, {"war_number": 119224}, True),    # prior had no number
    ({"war_number": 119224}, {"war_number": 119225}, True),  # genuinely newer war
    ({"war_number": 119224}, {"war_number": 119224}, False), # same war (back-to-back same opponent)
    ({"war_number": 119224}, {"war_number": 119223}, False), # older war on the page
    ({"war_number": 119224}, {"war_number": None}, False),   # unreadable number, cannot confirm
])
def test_is_newer_war(prev, parsed, expected):
    assert is_newer_war(prev, parsed) is expected

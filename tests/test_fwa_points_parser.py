"""Tests for the FWA points page parser, against real captured markup."""

import pytest
from utils.fwa_points_parser import (
    parse_clan_points, parse_active_fwa, sanitize_tag, is_newer_war, FwaPointsParseError,
)

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


LOSE_FIXTURE = (
    '<p><b>Clan Name</b>: Edrag Rush<br>'
    '<b>Active FWA</b>: Yes<br></p>'
    '<p class="winner-box">Win Calculator for <a href="/war?id=200">War #200</a> in Sync #10<br><br>'
    'Edrag Rush (<a href="/clan?tag=2PPCL2GYP">2PPCL2GYP</a>) vs. Opponent Clan '
    '(<a href="/clan?tag=OPPTAG01">OPPTAG01</a>):<br><br>'
    '<b>Opponent Clan</b> should win by points (9 &gt; 5)</p>'
)

UNKNOWN_FIXTURE = (
    '<p><b>Clan Name</b>: Edrag Rush<br>'
    '<b>Active FWA</b>: Yes<br></p>'
    '<p class="winner-box">Win Calculator for <a href="/war?id=201">War #201</a> in Sync #11<br><br>'
    'Edrag Rush (<a href="/clan?tag=2PPCL2GYP">2PPCL2GYP</a>) vs. Opponent Clan '
    '(<a href="/clan?tag=OPPTAG01">OPPTAG01</a>):<br><br>'
    '<b>Draw</b> - both clans tied (10 = 10)</p>'
)


def test_our_outcome_win_when_our_clan_is_bolded():
    d = parse_clan_points(FIXTURE, "2PPCL2GYP")
    assert d["predicted_winner_name"] == "Edrag Rush"
    assert d["our_outcome"] == "win"


def test_our_outcome_lose_when_opponent_is_bolded():
    d = parse_clan_points(LOSE_FIXTURE, "2PPCL2GYP")
    assert d["predicted_winner_name"] == "Opponent Clan"
    assert d["our_outcome"] == "lose"


def test_our_outcome_unknown_when_neither_name_matches():
    d = parse_clan_points(UNKNOWN_FIXTURE, "2PPCL2GYP")
    assert d["predicted_winner_name"] == "Draw"
    assert d["our_outcome"] == "unknown"


# No Clan Name field at all, and the verdict's <b> tag is empty - both sides of
# the win/lose comparison would normalize to "" and falsely compare equal
# unless empties are excluded outright.
EMPTY_WINNER_NO_CLAN_NAME_FIXTURE = (
    '<p><b>Active FWA</b>: Yes<br></p>'
    '<p class="winner-box">Win Calculator for <a href="/war?id=202">War #202</a> in Sync #12<br><br>'
    'Edrag Rush (<a href="/clan?tag=2PPCL2GYP">2PPCL2GYP</a>) vs. Opponent Clan '
    '(<a href="/clan?tag=OPPTAG01">OPPTAG01</a>):<br><br>'
    '<b></b> could not be determined</p>'
)


def test_our_outcome_unknown_when_winner_name_and_clan_name_are_both_empty():
    d = parse_clan_points(EMPTY_WINNER_NO_CLAN_NAME_FIXTURE, "2PPCL2GYP")
    assert d["predicted_winner_name"] == ""
    assert d["clan_name"] is None
    assert d["our_outcome"] == "unknown"


def test_parse_active_fwa_yes():
    assert parse_active_fwa('<p><b>Active FWA</b>: Yes<br></p>') is True


def test_parse_active_fwa_no():
    assert parse_active_fwa('<p><b>Active FWA</b>: No<br></p>') is False


def test_parse_active_fwa_missing_field_returns_none():
    assert parse_active_fwa('<p><b>Clan Name</b>: Some Clan<br></p>') is None


def test_parse_active_fwa_does_not_require_winner_box():
    # No winner-box anywhere on the page - still readable independently.
    html = "<html><body><p><b>Active FWA</b>: Yes<br></p></body></html>"
    assert parse_active_fwa(html) is True


@pytest.mark.parametrize("body", [
    "Clan not found.", "  Clan not found.  ", "CLAN NOT FOUND.", "clan not found.",
])
def test_parse_active_fwa_clan_not_found_body_is_false(body):
    # points.fwafarm.com answers HTTP 200 with exactly this body for a tag it
    # does not know - that must render as "not FWA", not as "unknown".
    assert parse_active_fwa(body) is False


def test_parse_active_fwa_label_present_without_winner_box_still_true():
    html = "<p><b>Active FWA</b>: Yes<br></p>"
    assert parse_active_fwa(html) is True


def test_parse_active_fwa_label_present_without_winner_box_still_false():
    html = "<p><b>Active FWA</b>: No<br></p>"
    assert parse_active_fwa(html) is False


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

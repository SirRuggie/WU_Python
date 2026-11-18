"""Tag-formatting regressions over isolated data; no provider or DB client."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extensions.commands import cards, lazycwl_dashboard
from extensions.commands.fwa import chocolate_links
from utils import account_links, clan_history, clash_links, fwa_blacklist
from utils import fwa_points_parser, fwa_war_plan_store, lazy_cwl_store, strike_store
from utils.clash_tags import normalize


@pytest.mark.parametrize("raw", ["#P0LYQ", "#polyq", " #pOlyq "])
def test_existing_canonical_tags_have_one_format_across_feature_boundaries(raw):
    assert normalize(raw) == "#P0LYQ"
    for formatter in (cards._normalize_tag, clash_links._normalize_tag,
                      lazy_cwl_store._normalize_tag, lazycwl_dashboard._tag,
                      clan_history._tag, strike_store.tag, fwa_war_plan_store.clan_tag):
        assert formatter(raw) == "#P0LYQ"
    # These public helpers intentionally retain their existing no-hash boundary.
    assert fwa_points_parser.sanitize_tag(raw) == "P0LYQ"
    assert chocolate_links.normalize_tag(raw) == "P0LYQ"


@pytest.mark.parametrize("raw", ["P0LYQ", "polyq", " pOlyq "])
def test_hashless_user_tags_gain_hash_except_documented_legacy_key_boundaries(raw):
    for formatter in (normalize, cards._normalize_tag, clash_links._normalize_tag,
                      lazy_cwl_store._normalize_tag, lazycwl_dashboard._tag,
                      strike_store.tag, fwa_war_plan_store.clan_tag):
        assert formatter(raw) == "#P0LYQ"
    assert clan_history._tag(raw) == "P0LYQ"


def test_legacy_composite_ids_keep_prefix_shape_and_normalize_components():
    assert clan_history._candidate_id("p0lyq", "clan2") == "P0LYQ:CLAN2"
    assert clan_history._candidate_id(" #p0lyq ", " #clan2 ") == "#P0LYQ:#CLAN2"
    assert clan_history._candidate_id(" #pOlyq ", "clan2") == "#P0LYQ:CLAN2"
    assert clan_history._candidate_id("#P0LYQ", "#CLAN2") == "#P0LYQ:#CLAN2"


@pytest.mark.parametrize("value", ["", " ", None])
def test_missing_tags_keep_feature_validation_and_markers(value):
    assert normalize(value) == ""
    assert cards._normalize_tag(value) == ""
    assert clash_links._normalize_tag(value) == ""
    assert clan_history._tag(value) == ""
    assert lazycwl_dashboard._tag(value) == ""
    with pytest.raises(ValueError, match="valid Clash"):
        strike_store.tag(value)
    with pytest.raises(ValueError, match="Missing clan identity"):
        fwa_war_plan_store.clan_tag(value)
    assert fwa_points_parser.sanitize_tag(value) == ""


def test_legacy_empty_store_marker_and_dashboard_all_sentinel_are_unchanged():
    assert lazy_cwl_store._normalize_tag("") == "#"
    assert lazycwl_dashboard._tag("ALL") == "ALL"
    assert lazycwl_dashboard._tag("all") == "#ALL"


@pytest.mark.parametrize("raw", ["#AB!", "P", "#P0LYQ" * 4, "#P 0LYQ", "# P0LYQ", "## P0LYQ", "#\tP0LYQ"])
def test_strike_store_still_rejects_invalid_alphabet_length_and_internal_space(raw):
    with pytest.raises(ValueError, match="valid Clash"):
        strike_store.tag(raw)


def test_chocolate_keeps_lenient_extraction_and_length_validation():
    assert chocolate_links.chocolate_url(" ##p O l y q ").endswith("?tag=P0LYQ")
    for raw in ("!", "a", "#" + "P" * 16):
        with pytest.raises(ValueError, match="2 to 15"):
            chocolate_links.chocolate_url(raw)


def test_points_parser_keeps_token_extraction_and_no_hash_storage_key():
    assert fwa_points_parser.sanitize_tag(" #p-O_l.yq ") == "P0LYQ"
    assert fwa_points_parser.sanitize_tag("!!!") == ""


def test_account_link_owner_validation_and_conflicts_keep_canonical_tag():
    rows = account_links.normalize_records([
        [{"player_tag": " #pOlyq ", "user_id": "123", "is_verified": True},
         {"player_tag": "#INVALID!", "user_id": "123"}],
        [{"tag": "polyq", "userId": "456", "verified": False}],
    ])
    assert rows == [("#P0LYQ", "123", True), ("#P0LYQ", "456", False)]
    assert account_links.normalize_records([[{"player_tag": "#P0LYQ", "user_id": "bad"}], []]) == []


def test_blacklist_normalized_lookup_reuses_existing_no_hash_row_without_rewrite():
    row = {"_id": "P0LYQ", "name": "Existing"}
    collection = SimpleNamespace(find_one=AsyncMock(return_value=row), update_one=AsyncMock())
    assert asyncio.run(fwa_blacklist.is_blacklisted(SimpleNamespace(fwa_blacklist=collection), " #pOlyq ")) is True
    collection.find_one.assert_awaited_once_with({"_id": "P0LYQ"})
    collection.update_one.assert_not_awaited()


def test_points_html_names_and_verdict_match_normalized_link_identities():
    page = (
        '<p><b>Clan Name</b>: Our Name<br></p>'
        '<p class="winner-box">War #1 in Sync #2<br><br>'
        'Our Name (<a href="/clan?tag=POLYQ">POLYQ</a>) vs. '
        'Other Name (<a href="/clan?tag=R0LYQ">R0LYQ</a>):<br><br>'
        '<b>Other Name</b> should win</p>'
    )
    result = fwa_points_parser.parse_clan_points(page, "#P0LYQ")
    assert result["clan_tags_in_box"] == ["P0LYQ", "R0LYQ"]
    assert result["our_name_in_box"] == "Our Name"
    assert result["opponent_name"] == "Other Name"
    assert result["our_outcome"] == "lose"


def test_catchup_normalizes_opponent_but_preserves_existing_war_key(monkeypatch):
    from extensions.tasks import fwa_points_monitor as monitor
    page = (
        '<p><b>Clan Name</b>: Our Name<br></p>'
        '<p class="winner-box">War #1 in Sync #2<br><br>'
        'Our Name (<a href="/clan?tag=P0LYQ">P0LYQ</a>) vs. '
        'Other Name (<a href="/clan?tag=ROLYQ">ROLYQ</a>):<br><br>'
        '<b>Our Name</b> should win</p>'
    )
    fetch = AsyncMock(side_effect=[page, None])
    store = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor, "mongo_client", SimpleNamespace(fwa_points=SimpleNamespace(find_one=AsyncMock(return_value=None))))
    monkeypatch.setattr(monitor, "feature_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(monitor, "fetch_points_html", fetch)
    monkeypatch.setattr(monitor, "store_record", store)
    monkeypatch.setattr(monitor, "log_outcome", AsyncMock())
    asyncio.run(monitor.run_catchup({"tag": "#P0LYQ", "name": "Our Name"}, "#rOlyq", "ROLYQ:EXISTING-WAR"))
    assert [call.args[0] for call in fetch.await_args_list] == ["P0LYQ", "R0LYQ"]
    assert store.await_args.args[3:5] == ("R0LYQ", "ROLYQ:EXISTING-WAR")


def test_war_plan_keeps_legacy_after_hash_whitespace_and_single_hash_shape():
    assert fwa_war_plan_store.clan_tag(" ##pOlyq ") == "#P0LYQ"
    assert fwa_war_plan_store.clan_tag("# P0LYQ") == "# P0LYQ"
    assert fwa_war_plan_store.clan_tag("# #P0LYQ") == "# #P0LYQ"
    assert strike_store.tag("##P0LYQ") == "#P0LYQ"


@pytest.mark.parametrize("raw", ["# #P0LYQ", "#\t#P0LYQ", "## #P0LYQ"])
def test_chocolate_keeps_malformed_nested_hash_instead_of_widening_validation(raw):
    assert chocolate_links.normalize_tag(raw) == "#P0LYQ"
    assert chocolate_links.is_valid_tag(raw) is False

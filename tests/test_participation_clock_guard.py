"""Owner489 narrow clock allowance; no operational reader or database access."""

from copy import deepcopy
from datetime import timedelta
import pytest
from tools.release_automatic_state import compare_sqlite_snapshots
from test_release_automatic_state import sql_fixture
from test_release_protected_state import NOW

CLOCKS = ("last_checked_at", "last_success_at")


def snapshots():
    before, after = sql_fixture()
    row = {
        "season_id": 1,
        "cycle": "2026-11",
        "enabled": 1,
        "status": "complete",
        "warning": None,
        "last_checked_at": (NOW - timedelta(minutes=1)).isoformat(),
        "last_success_at": (NOW - timedelta(minutes=1)).isoformat(),
        "updated_by": "staff",
        "updated_at": (NOW - timedelta(days=1)).isoformat(),
    }
    before["tables"]["participation_sync_settings"] = [deepcopy(row)]
    after["tables"]["participation_sync_settings"] = [deepcopy(row)]
    return before, after


def setting(snapshot):
    return snapshot["tables"]["participation_sync_settings"][0]


@pytest.mark.parametrize("clocks", [(), CLOCKS, (CLOCKS[0],), (CLOCKS[1],)])
def test_clock_only_each_both_and_equal_pass(clocks):
    before, after = snapshots()
    for clock in clocks:
        setting(after)[clock] = NOW.isoformat()
    report = compare_sqlite_snapshots(before, after)
    assert report["table_counts"]["participation_sync_settings"] == int(bool(clocks))
    assert before["tables"]["participation_sync_settings"][0]["updated_by"] == "staff"


def test_unchanged_nulls_allowed_without_inventing_forward_transition():
    before, after = snapshots()
    for snap in [before, after]:
        for clock in CLOCKS:
            setting(snap)[clock] = None
    assert (
        compare_sqlite_snapshots(before, after)["table_counts"][
            "participation_sync_settings"
        ]
        == 0
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("season_id", 2),
        ("cycle", "2026-12"),
        ("enabled", 0),
        ("status", "partial"),
        ("warning", "new warning"),
        ("updated_by", "sync"),
        ("updated_at", NOW.isoformat()),
        ("enabled", True),
        ("season_id", True),
        ("enabled", 1.0),
    ],
)
def test_clock_plus_every_neighbour_and_equal_python_numeric_type_changes_deny(
    field, value
):
    before, after = snapshots()
    setting(after)["last_success_at"] = NOW.isoformat()
    setting(after)[field] = value
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize(
    "change",
    [
        "added",
        "removed",
        "duplicate",
        "missing_identity",
        "bad_identity",
        "new_column",
        "missing_column",
        "stripped_checked",
    ],
)
def test_row_membership_identity_columns_and_complete_reader_contract(change):
    before, after = snapshots()
    rows = after["tables"]["participation_sync_settings"]
    if change == "added":
        rows.append(dict(rows[0], season_id=2))
    elif change == "removed":
        rows.clear()
    elif change == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif change == "missing_identity":
        rows[0].pop("season_id")
    elif change == "bad_identity":
        rows[0]["season_id"] = "1"
    elif change == "new_column":
        rows[0]["other"] = "new"
    elif change == "missing_column":
        rows[0].pop("warning")
    elif change == "stripped_checked":
        for snap in [before, after]:
            setting(snap).pop("last_checked_at")
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize("clock", CLOCKS)
@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        True,
        "bad",
        "2026-11-02",
        "2026-11-01T00:00:00",
        "2026-11-01T01:00:00+01:00",
        "2026-10-31T19:00:00-05:00",
        "2026-11-01X00:00:00+00:00",
        "2026-13-02T12:00:00+00:00",
    ],
)
def test_changed_clock_null_type_malformed_naive_and_nonutc_deny(clock, value):
    before, after = snapshots()
    setting(after)[clock] = value
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize("clock", CLOCKS)
@pytest.mark.parametrize(
    "value", ["bad", "2026-11-01T00:00:00", "2026-11-01T01:00:00+01:00", 1]
)
def test_equal_but_invalid_clock_never_sneaks_through(clock, value):
    before, after = snapshots()
    setting(before)[clock] = setting(after)[clock] = value
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize("clock", CLOCKS)
def test_null_to_timestamp_transition_is_fail_closed(clock):
    before, after = snapshots()
    setting(before)[clock] = None
    setting(after)[clock] = NOW.isoformat()
    with pytest.raises(ValueError, match="NULL transition"):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize("clock", CLOCKS)
@pytest.mark.parametrize(
    "kind", ["backward", "before_interval", "after_interval", "unchanged_future"]
)
def test_clock_monotonicity_and_capture_interval(clock, kind):
    before, after = snapshots()
    if kind == "backward":
        setting(after)[clock] = (NOW - timedelta(minutes=2)).isoformat()
    elif kind == "before_interval":
        setting(after)[clock] = (NOW - timedelta(seconds=2)).isoformat()
    elif kind == "after_interval":
        setting(after)[clock] = (NOW + timedelta(seconds=2)).isoformat()
    elif kind == "unchanged_future":
        setting(before)[clock] = setting(after)[clock] = (
            NOW + timedelta(seconds=2)
        ).isoformat()
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize("endpoint", ["started", "ended"])
def test_changed_clock_interval_endpoints_are_inclusive_and_z_is_utc(endpoint):
    before, after = snapshots()
    stamp = before["started"] if endpoint == "started" else after["ended"]
    setting(after)["last_success_at"] = stamp.replace("+00:00", "Z")
    assert (
        compare_sqlite_snapshots(before, after)["table_counts"][
            "participation_sync_settings"
        ]
        == 1
    )


def test_observed_interval_is_whole_before_start_to_post_end_not_only_post_read():
    before, after = snapshots()
    setting(after)["last_success_at"] = NOW.isoformat()
    assert before["ended"] < NOW.isoformat() < after["started"]
    assert (
        compare_sqlite_snapshots(before, after)["table_counts"][
            "participation_sync_settings"
        ]
        == 1
    )


def test_other_sql_changes_and_staff_proof_remain_strict_when_clocks_change():
    for table in ["player_weights", "signups", "roster_entries", "roster_publications"]:
        before, after = snapshots()
        setting(after)["last_success_at"] = NOW.isoformat()
        after["tables"][table][0]["unexpected"] = "mutation"
        with pytest.raises(ValueError):
            compare_sqlite_snapshots(before, after)
    before, after = snapshots()
    setting(after)["last_success_at"] = NOW.isoformat()
    after["proof"]["roster_audit"] = [{"action": "staff"}]
    with pytest.raises(ValueError, match="proof changed"):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize("clock", CLOCKS)
def test_backwards_clock_with_both_values_inside_interval_still_denies(clock):
    before, after = snapshots()
    setting(before)[clock] = (NOW - timedelta(milliseconds=750)).isoformat()
    setting(after)[clock] = (NOW - timedelta(milliseconds=900)).isoformat()
    with pytest.raises(ValueError, match="backwards"):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize("old,new", [({"value": 1}, {"value": True}), (-0.0, 0.0)])
def test_unknown_neighbour_value_must_remain_byte_equal(old, new):
    before, after = snapshots()
    setting(before)["future_column"] = old
    setting(after)["future_column"] = new
    setting(after)["last_success_at"] = NOW.isoformat()
    with pytest.raises(ValueError, match="Nonclock"):
        compare_sqlite_snapshots(before, after)


def test_complete_synthetic_971_shaped_capture_not_a_historical_reconstruction():
    # Synthetic only: old971 images stripped last_checked_at, so they cannot
    # supply a complete actual pair. Four old observation clocks plus these
    # two settings clocks move; every other field/proof remains unchanged.
    before, after = snapshots()
    for clock in CLOCKS:
        setting(after)[clock] = NOW.isoformat()
    frozen = deepcopy((before, after))
    report = compare_sqlite_snapshots(before, after)
    assert report["changed_rows"] == 5
    assert report["table_counts"]["participation_sync_settings"] == 1
    fields = next(
        item["fields"]
        for item in report["automatic_changes"]
        if item["table"] == "participation_sync_settings"
    )
    assert {item["column"] for item in fields} == set(CLOCKS)
    assert (before, after) == frozen

"""Automatic release allowances never hide neighbouring or staff mutations."""

from copy import deepcopy
from datetime import timedelta
import pytest
from tools.release_automatic_state import (
    CAPTURE_FIELDS,
    PROOF_TABLES,
    SQL_REQUIRED_TABLES,
    compare_mongo_snapshots,
    compare_sqlite_snapshots,
)
from test_release_protected_state import fixture, NOW


def mongo(items):
    return compare_mongo_snapshots(
        *items, started=NOW - timedelta(seconds=1), ended=NOW + timedelta(seconds=1)
    )


def returned():
    old, new, p, q = fixture()
    current = deepcopy(p)
    current[("1", "#P")].update(
        roster_seen_at=NOW + timedelta(milliseconds=100),
        roster_observed_at=NOW + timedelta(milliseconds=100),
    )
    return new, old, q, current


def test_exact_departure_return_and_clock_refresh_have_per_field_proof():
    report = mongo(fixture())
    assert report["changed_rows"] == 1
    assert report["automatic_changes"][0]["collection"] == "strike_profiles"
    assert report["replacement_totals"][0]["departed_before"] == 0
    assert report["replacement_totals"][0]["departed_after"] == 1
    report = mongo(returned())
    assert report["replacement_totals"][0]["departed_before"] == 1
    assert report["replacement_totals"][0]["departed_after"] == 0
    assert {r["column"] for r in report["automatic_changes"][0]["fields"]} == {
        "current_clan_tag",
        "roster_seen_at",
        "roster_observed_at",
        "departed_clan_tag",
        "departed_last_seen_at",
    }
    old, _, p, _ = fixture()
    q = deepcopy(p)
    q[("1", "#P")].update(roster_seen_at=NOW, roster_observed_at=NOW)
    report = mongo((old, deepcopy(old), p, q))
    assert (
        report["changed_rows"] == 1
        and report["replacement_totals"][0]["proven_flag_changes"] == 0
    )
    assert mongo((old, deepcopy(old), p, deepcopy(p)))["changed_rows"] == 0


@pytest.mark.parametrize(
    "field",
    [
        "weight",
        "player_name",
        "town_hall",
        "updated_by",
        "updated_at",
        "replacement_note",
        "replacement_priority",
        "filler",
        "member_id",
        "streak_count",
    ],
)
def test_neighbouring_profile_and_staff_fields_stop_even_when_metrics_equal(field):
    old, _, p, _ = fixture()
    q = deepcopy(p)
    q[("1", "#P")].update(roster_seen_at=NOW, roster_observed_at=NOW)
    values = {
        "weight": 200,
        "player_name": "Different name",
        "town_hall": 17,
        "updated_by": 2,
        "updated_at": NOW,
        "replacement_note": "Staff note",
        "replacement_priority": "high",
        "filler": True,
        "member_id": 2,
        "streak_count": 4,
    }
    q[("1", "#P")][field] = values[field]
    with pytest.raises(ValueError):
        mongo((old, deepcopy(old), p, q))


@pytest.mark.parametrize(
    "change",
    [
        "added",
        "removed",
        "active",
        "priority",
        "listed",
        "unproven_flag",
        "late",
        "backwards",
        "wrong_return",
        "clock_mismatch",
        "same_flag_no_raw_proof",
    ],
)
def test_profile_rows_totals_and_invalid_presence_proof_stop(change):
    old, new, p, q = returned()
    if change == "added":
        q[("1", "#OTHER")] = deepcopy(next(iter(q.values())))
    elif change == "removed":
        q.clear()
    elif change == "active":
        new["active"][0][2] += 1
    elif change == "priority":
        new["replacement"]["1"][0][3] += 1
    elif change == "listed":
        new["replacement"]["1"][0][2] = False
    elif change == "unproven_flag":
        new["replacement"]["1"][0][4] = True
    elif change == "late":
        q[("1", "#P")]["roster_observed_at"] = NOW + timedelta(minutes=1)
    elif change == "backwards":
        q[("1", "#P")].update(
            roster_seen_at=NOW - timedelta(minutes=1),
            roster_observed_at=NOW - timedelta(minutes=1),
        )
    elif change == "wrong_return":
        q[("1", "#P")]["current_clan_tag"] = "#OTHER"
    elif change == "clock_mismatch":
        q[("1", "#P")]["roster_seen_at"] = NOW
    elif change == "same_flag_no_raw_proof":
        q = deepcopy(p)
    with pytest.raises(ValueError):
        mongo((old, new, p, q))


def sql_fixture():
    tables = {k: [] for k in SQL_REQUIRED_TABLES}
    tables["counts"] = [dict(season_id=1, pool="main", signups=1, assigned=1, locks=1)]
    tables["player_weights"] = [dict(tag="#P", weight=100)]
    tables["roster_entries"] = [dict(tag="#P", assigned_clan_tag="#C")]
    tables["roster_publications"] = [dict(id=1, version=1)]
    tables["signups"] = [dict(tag="#P", pool="main")]
    for table, (keys, column) in CAPTURE_FIELDS.items():
        row = {
            key: 1 if key == "season_id" else "2026-11" if key == "cycle" else "#P"
            for key in keys
        }
        row[column] = (NOW - timedelta(minutes=1)).isoformat()
        row.update(
            {
                "participation_source_results": dict(
                    attacks=None,
                    stars=None,
                    status="preparation",
                    complete=0,
                    warning=None,
                    roster_token="fixture",
                ),
                "participation_group_observations": dict(
                    season="2026-11",
                    state="PREPARATION",
                    war_tags_json="[]",
                    members_json="[]",
                ),
                "participation_war_observations": dict(
                    state="WAR", ended=0, attacks_json="{}"
                ),
                "participation_war_fetches": dict(ended=0, scanned_clans_json="[]"),
            }[table]
        )
        tables[table] = [row]
    before = dict(
        started=(NOW - timedelta(seconds=1)).isoformat(),
        ended=(NOW - timedelta(milliseconds=500)).isoformat(),
        tables=tables,
        proof={k: [] for k in PROOF_TABLES},
    )
    after = deepcopy(before)
    after.update(
        started=(NOW + timedelta(milliseconds=500)).isoformat(),
        ended=(NOW + timedelta(seconds=1)).isoformat(),
    )
    for table, (_, column) in CAPTURE_FIELDS.items():
        after["tables"][table][0][column] = NOW.isoformat()
    return before, after


def test_only_four_named_capture_timestamps_pass_with_exact_counts():
    before, after = sql_fixture()
    report = compare_sqlite_snapshots(before, after)
    assert report["changed_rows"] == 4 and report["table_counts"] == {
        **{k: 1 for k in CAPTURE_FIELDS},
        "participation_sync_settings": 0,
    }
    assert {r["fields"][0]["column"] for r in report["automatic_changes"]} == {
        "checked_at",
        "observed_at",
    }
    assert (
        before["tables"]["participation_source_results"][0]["checked_at"]
        != after["tables"]["participation_source_results"][0]["checked_at"]
    )


@pytest.mark.parametrize("table", list(CAPTURE_FIELDS))
@pytest.mark.parametrize(
    "change",
    [
        "neighbour",
        "added",
        "removed",
        "late",
        "backwards",
        "missing_column",
        "duplicate",
    ],
)
def test_timestamp_allowance_never_accepts_neighbours_or_row_changes(table, change):
    before, after = sql_fixture()
    rows = after["tables"][table]
    column = CAPTURE_FIELDS[table][1]
    if change == "neighbour":
        neighbour = {
            "participation_source_results": "status",
            "participation_group_observations": "state",
            "participation_war_observations": "ended",
            "participation_war_fetches": "ended",
        }[table]
        rows[0][neighbour] = 1 if neighbour == "ended" else "different"
    elif change == "added":
        r = deepcopy(rows[0])
        r["season_id"] = 2
        rows.append(r)
    elif change == "removed":
        rows.clear()
    elif change == "late":
        rows[0][column] = (NOW + timedelta(minutes=1)).isoformat()
    elif change == "backwards":
        rows[0][column] = (NOW - timedelta(minutes=2)).isoformat()
    elif change == "missing_column":
        rows[0].pop(column)
    elif change == "duplicate":
        rows.append(deepcopy(rows[0]))
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


@pytest.mark.parametrize(
    "table", ["player_weights", "roster_entries", "roster_publications", "signups"]
)
def test_weight_roster_publication_and_staff_edits_stop(table):
    before, after = sql_fixture()
    field, value = {
        "player_weights": ("weight", 101),
        "roster_entries": ("assigned_clan_tag", "#D"),
        "roster_publications": ("version", 2),
        "signups": ("pool", "lazy"),
    }[table]
    after["tables"][table][0][field] = value
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


def test_staff_receipt_or_missing_table_does_not_authorize_another_change():
    before, after = sql_fixture()
    after["proof"]["roster_audit"].append(dict(id=1, action="publish"))
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)
    before, after = sql_fixture()
    before["tables"].pop("player_weights")
    after["tables"].pop("player_weights")
    with pytest.raises(ValueError):
        compare_sqlite_snapshots(before, after)


def test_file_comparisons_bind_independent_captures_and_private_reports(tmp_path):
    import json
    from bson import json_util
    from tools.release_automatic_state import compare_mongo_files, compare_sqlite_files

    old, new, p, q = returned()
    for name, metrics, profiles, start, end in [
        (
            "before",
            old,
            p,
            NOW - timedelta(seconds=1),
            NOW - timedelta(milliseconds=500),
        ),
        (
            "after",
            new,
            q,
            NOW + timedelta(milliseconds=500),
            NOW + timedelta(seconds=1),
        ),
    ]:
        (tmp_path / (name + ".json")).write_text(json.dumps(metrics))
        (tmp_path / (name + "-profiles.json")).write_text(
            json_util.dumps(
                dict(started=start, ended=end, profiles=list(profiles.values()))
            )
        )
    result = compare_mongo_files(tmp_path, "before", "after")
    report = tmp_path / "after-automatic-comparison.json"
    assert (
        result["changed_rows"] == 1
        and len(json.loads(report.read_text())["input_sha256"]) == 4
    )
    assert report.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="independent"):
        compare_mongo_files(tmp_path, "before", "before")
    before, after = sql_fixture()
    for name, value in [("sql-before", before), ("sql-after", after)]:
        (tmp_path / (name + ".json")).write_text(json.dumps(value))
    sqlreport = tmp_path / "sql-proof.json"
    result = compare_sqlite_files(
        tmp_path / "sql-before.json", tmp_path / "sql-after.json", sqlreport
    )
    assert (
        result["changed_rows"] == 4
        and len(json.loads(sqlreport.read_text())["input_sha256"]) == 2
    )
    assert sqlreport.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="overwrite"):
        compare_sqlite_files(
            tmp_path / "sql-before.json",
            tmp_path / "sql-after.json",
            tmp_path / "sql-before.json",
        )


def test_equal_metrics_without_profile_proof_still_fail_closed():
    old, _, _, _ = fixture()
    with pytest.raises(ValueError, match="missing"):
        mongo((old, deepcopy(old), {}, {}))

"""Narrow, read-only release proof for two ordinary automatic update families.

No row membership changes or staff writes are accepted. The existing stricter
departure-only API remains available; coordinators must explicitly opt into this
reviewed comparison and retain its per-field evidence.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile

from bson import json_util

from tools.release_protected_state import compare_protected

PRESENCE_FIELDS = frozenset(
    {
        "current_clan_tag",
        "roster_seen_at",
        "roster_observed_at",
        "departed_clan_tag",
        "departed_last_seen_at",
    }
)
CAPTURE_FIELDS = {
    "participation_source_results": (("season_id", "cycle", "tag"), "checked_at"),
    "participation_group_observations": (
        ("season_id", "cycle", "clan_tag"),
        "observed_at",
    ),
    "participation_war_observations": (
        ("season_id", "cycle", "war_tag", "clan_tag"),
        "observed_at",
    ),
    "participation_war_fetches": (("season_id", "cycle", "war_tag"), "observed_at"),
}
SQL_REQUIRED_TABLES = frozenset(
    (
        "cwl_pool_role_settings",
        "cwl_pool_role_jobs",
        "cwl_pool_role_clock",
        "cwl_pool_role_audit",
        "roster_publications",
        "member_season",
        "manage_campaign_bindings",
        "roster_image_posts",
        "roster_image_requests",
        "roster_image_channels",
        "roster_player_marks",
        "roster_player_mark_audit",
        "roster_entries",
        "lineup_rules",
        "player_weights",
        "signups",
        "signup_activity_reviews",
        "clan_player_weights",
        "clan_player_weight_history",
        "clan_weight_war_lineups",
        "participation_records",
        "participation_source_results",
        "participation_sync_settings",
        "participation_group_observations",
        "participation_war_observations",
        "participation_war_fetches",
        "bonus_allowance_leagues",
        "bonus_allowance_wars",
        "bonus_reviews",
        "bonus_batches",
        "bonus_confirmations",
        "bonus_audit",
        "counts",
        "unreviewed_signup_activity",
    )
)
PROOF_TABLES = frozenset(
    {"roster_audit", "publication_accounts", "roster_meta", "seasons", "grants"}
)
MISSING = object()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    require(isinstance(value, datetime), "A capture timestamp is required")
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def interval(started, ended):
    start, end = utc(started), utc(ended)
    require(start <= end, "Capture interval reversed")
    return start, end


def observed(prior, current, start, end):
    stamp = utc(current)
    require(start <= stamp <= end, "Automatic observation outside capture interval")
    if prior is not None:
        require(utc(prior) <= stamp, "Automatic observation moved backwards")
    return stamp


def changed_fields(before, after):
    return sorted(
        k
        for k in set(before) | set(after)
        if before.get(k, MISSING) != after.get(k, MISSING)
    )


def field_evidence(before, after, fields):
    def value(item):
        return item.isoformat() if isinstance(item, datetime) else item

    return [
        {
            "column": k,
            "before_present": k in before,
            "after_present": k in after,
            "before": value(before.get(k)),
            "after": value(after.get(k)),
        }
        for k in fields
    ]


def departed(profile):
    """The unweighted replacement view's exact presence projection."""
    old = profile.get("departed_clan_tag")
    marked = old and old in (
        profile.get("replacement_clan_tag"),
        profile.get("filler_clan_tag"),
    )
    return bool(
        old
        and profile.get("current_clan_tag") != old
        and (marked or not profile.get("current_clan_tag"))
    )


def presence_change(prior, current, start, end):
    fields = changed_fields(prior, current)
    require(set(fields) <= PRESENCE_FIELDS, "Non-presence strike profile field changed")
    if not fields:
        return []
    stamp = observed(
        prior.get("roster_observed_at") or prior.get("roster_seen_at"),
        current.get("roster_observed_at"),
        start,
        end,
    )
    expected = deepcopy(prior)
    clan = current.get("current_clan_tag")
    if clan:
        require(isinstance(clan, str), "Malformed current clan")
        require(
            current.get("roster_seen_at") == current.get("roster_observed_at"),
            "Returning roster clocks differ",
        )
        expected.update(
            current_clan_tag=clan,
            roster_seen_at=current["roster_seen_at"],
            roster_observed_at=current["roster_observed_at"],
        )
        if prior.get("departed_clan_tag") == clan:
            expected.pop("departed_clan_tag", None)
            expected.pop("departed_last_seen_at", None)
        elif (
            prior.get("current_clan_tag")
            and prior["current_clan_tag"] != clan
            and (
                not prior.get("departed_clan_tag")
                or prior["departed_clan_tag"]
                not in (prior.get("replacement_clan_tag"), prior.get("filler_clan_tag"))
            )
        ):
            expected.update(
                departed_clan_tag=prior["current_clan_tag"],
                departed_last_seen_at=prior.get("roster_seen_at")
                or current["roster_observed_at"],
            )
    else:
        require(bool(prior.get("current_clan_tag")), "Departure has no previous clan")
        old_clan = expected.pop("current_clan_tag")
        previous = prior.get("departed_clan_tag")
        preserve = previous and previous in (
            prior.get("replacement_clan_tag"),
            prior.get("filler_clan_tag"),
        )
        expected.update(
            departed_clan_tag=previous if preserve else old_clan,
            roster_observed_at=current["roster_observed_at"],
            departed_last_seen_at=(
                prior.get("departed_last_seen_at")
                if preserve
                else prior.get("roster_seen_at")
            )
            or current["roster_observed_at"],
        )
    require(expected == current, "Profile differs from exact sync_roster update")
    return field_evidence(prior, current, fields)


def compare_mongo_snapshots(
    before, after, profiles_before, profiles_after, *, started, ended
):
    """Accept exact StrikeService.sync_roster updates, never arbitrary flags."""
    start, end = interval(started, ended)
    # Reuse the established nonempty/shape checks without granting its exception.
    compare_protected(
        before, before, profiles_before, profiles_before, started=start, ended=end
    )
    compare_protected(
        after, after, profiles_after, profiles_after, started=start, ended=end
    )
    keys = {(str(r[0]), r[1]) for r in before["streaks"]}
    require(
        len(keys) == len(before["streaks"])
        and keys == set(profiles_before) == set(profiles_after),
        "Strike profile rows added, removed or missing",
    )
    evidence = []
    for key in sorted(keys):
        p, q = profiles_before[key], profiles_after[key]
        require(
            isinstance(p, dict) and isinstance(q, dict), "Malformed profile evidence"
        )
        require(
            (str(p.get("guild_id")), p.get("player_tag"))
            == key
            == (str(q.get("guild_id")), q.get("player_tag")),
            "Profile identity mismatch",
        )
        fields = presence_change(p, q, start, end)
        if fields:
            evidence.append(
                {"collection": "strike_profiles", "key": list(key), "fields": fields}
            )
    normalized = deepcopy(after)
    require(
        set(before["replacement"]) == set(after["replacement"]),
        "Replacement guild changed",
    )
    totals = []
    for guild, rows in before["replacement"].items():
        a = {r[0]: r for r in rows}
        b = {r[0]: r for r in normalized["replacement"][guild]}
        require(
            len(a) == len(rows)
            and len(b) == len(normalized["replacement"][guild])
            and set(a) == set(b),
            "Replacement rows added or removed",
        )
        changes = 0
        for tag, old in a.items():
            new = b[tag]
            require(old[:4] == new[:4], "Non-departure replacement field changed")
            require(
                type(old[4]) is bool and type(new[4]) is bool,
                "Malformed departure flag",
            )
            require(
                old[4] == departed(profiles_before[(str(guild), tag)])
                and new[4] == departed(profiles_after[(str(guild), tag)]),
                "Unproven departure flag",
            )
            changes += old[4] != new[4]
            new[4] = old[4]
        totals.append(
            {
                "guild_id": str(guild),
                "rows_before": len(a),
                "rows_after": len(b),
                "departed_before": sum(r[4] for r in rows),
                "departed_after": sum(r[4] for r in after["replacement"][guild]),
                "proven_flag_changes": changes,
            }
        )
    require(
        before == normalized, "Protected state changed outside named presence fields"
    )
    return {
        "automatic_changes": evidence,
        "changed_rows": len(evidence),
        "replacement_totals": totals,
    }


SYNC_CLOCK_TABLE = "participation_sync_settings"
SYNC_CLOCK_FIELDS = ("last_checked_at", "last_success_at")


def _sync_clock(value):
    require(
        isinstance(value, str)
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value
        ),
        "Sync clock must be an ISO UTC string",
    )
    stamp = datetime.fromisoformat(value)
    require(
        stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0,
        "Sync clock must be aware UTC",
    )
    return stamp


def _compare_sync_clocks(before, after, start, end):
    def index(rows):
        require(isinstance(rows, list), "Malformed sync settings rows")
        result = {}
        for row in rows:
            require(
                isinstance(row, dict)
                and type(row.get("season_id")) is int
                and row["season_id"] > 0
                and all(field in row for field in SYNC_CLOCK_FIELDS),
                "Sync settings identity or clocks missing",
            )
            require(row["season_id"] not in result, "Duplicate sync settings rows")
            result[row["season_id"]] = row
        return result

    old, new = index(before), index(after)
    require(old.keys() == new.keys(), "Sync settings rows added or removed")
    evidence = []
    for key, prior in old.items():
        current = new[key]
        require(prior.keys() == current.keys(), "Sync settings columns changed")
        require(
            all(
                type(prior[field]) is type(current[field])
                and json.dumps(prior[field], sort_keys=True, allow_nan=False)
                == json.dumps(current[field], sort_keys=True, allow_nan=False)
                for field in prior.keys() - set(SYNC_CLOCK_FIELDS)
            ),
            "Nonclock sync settings field changed",
        )
        changed = []
        for field in SYNC_CLOCK_FIELDS:
            p, q = prior[field], current[field]
            if p is None and q is None:
                continue
            require(
                p is not None and q is not None,
                "Sync clock NULL transition is unproved",
            )
            previous, stamp = _sync_clock(p), _sync_clock(q)
            require(
                previous <= stamp <= end, "Sync clock moved backwards or beyond capture"
            )
            if p != q:
                require(start <= stamp, "Sync clock outside capture interval")
                changed.append(field)
        if changed:
            evidence.append(
                {
                    "table": SYNC_CLOCK_TABLE,
                    "key": {"season_id": key},
                    "fields": field_evidence(prior, current, changed),
                }
            )
    return evidence


def compare_sqlite_snapshots(before, after):
    """Only reviewed capture clocks vary; all neighbouring/staff fields stay strict."""
    require(before is not after, "Independent captures required")
    start, end = interval(before["started"], after["ended"])
    require(
        start <= utc(before["ended"]) <= utc(after["started"]) <= end,
        "Capture order invalid",
    )
    a, b = before["tables"], after["tables"]
    require(
        isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys(),
        "Protected tables changed",
    )
    require(SQL_REQUIRED_TABLES <= a.keys(), "Protected capture incomplete")
    require(
        isinstance(before["proof"], dict) and PROOF_TABLES <= before["proof"].keys(),
        "Missing staff proof tables",
    )
    require(before["proof"] == after["proof"], "Staff or publication proof changed")
    evidence = []
    for table, rows in a.items():
        if table == SYNC_CLOCK_TABLE:
            evidence.extend(_compare_sync_clocks(rows, b[table], start, end))
            continue
        if table not in CAPTURE_FIELDS:
            require(rows == b[table], "Nonautomatic protected table changed: " + table)
            continue
        keys, column = CAPTURE_FIELDS[table]

        def index(items):
            require(
                isinstance(items, list)
                and all(
                    isinstance(r, dict) and all(k in r for k in (*keys, column))
                    for r in items
                ),
                "Malformed capture rows: " + table,
            )
            indexed = {tuple(r[k] for k in keys): r for r in items}
            require(len(indexed) == len(items), "Duplicate capture rows: " + table)
            return indexed

        old, new = index(rows), index(b[table])
        require(old.keys() == new.keys(), "Capture rows added or removed: " + table)
        for key, p in old.items():
            q = new[key]
            fields = changed_fields(p, q)
            require(
                not fields or fields == [column],
                "Neighbouring capture field changed: " + table,
            )
            if fields:
                observed(p[column], q[column], start, end)
                evidence.append(
                    {
                        "table": table,
                        "key": dict(zip(keys, key)),
                        "fields": field_evidence(p, q, fields),
                    }
                )
    counts = {
        name: sum(r["table"] == name for r in evidence)
        for name in (*CAPTURE_FIELDS, SYNC_CLOCK_TABLE)
    }
    return {
        "automatic_changes": evidence,
        "changed_rows": len(evidence),
        "table_counts": counts,
    }


def independent_paths(before, after):
    before, after = Path(before), Path(after)
    require(
        before.resolve() != after.resolve() and not before.samefile(after),
        "Two independent capture files required",
    )
    return before, after


def write_report(path, report, inputs):
    path = Path(path)
    require(
        all(path.resolve() != p.resolve() for p in inputs),
        "Report would overwrite capture",
    )
    report["input_sha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def compare_mongo_files(directory, before_name, after_name):
    """Compare independent metrics and contemporaneous raw BSON profile proofs."""
    directory = Path(directory)
    before_path, after_path = independent_paths(
        directory / (before_name + ".json"), directory / (after_name + ".json")
    )
    inputs = [before_path, after_path]

    def load(name):
        proof_path = directory / (name + "-profiles.json")
        inputs.append(proof_path)
        metrics = json.loads((directory / (name + ".json")).read_text())
        proof = json_util.loads(proof_path.read_text())
        require(
            isinstance(proof.get("profiles"), list) and proof["profiles"],
            "Missing raw profile proof",
        )
        mapping = {(str(p["guild_id"]), p["player_tag"]): p for p in proof["profiles"]}
        require(len(mapping) == len(proof["profiles"]), "Duplicate profile proof")
        return metrics, proof, mapping

    before, prior, p = load(before_name)
    after, current, q = load(after_name)
    require(
        utc(prior["started"])
        <= utc(prior["ended"])
        <= utc(current["started"])
        <= utc(current["ended"]),
        "Mongo captures overlap or are reversed",
    )
    report = compare_mongo_snapshots(
        before, after, p, q, started=prior["started"], ended=current["ended"]
    )
    report.update(collection="strike_profiles", allowed_fields=sorted(PRESENCE_FIELDS))
    write_report(
        directory / (after_name + "-automatic-comparison.json"), report, inputs
    )
    return report


def compare_sqlite_files(before_path, after_path, report_path):
    before_path, after_path = independent_paths(before_path, after_path)
    report = compare_sqlite_snapshots(
        json.loads(before_path.read_text()), json.loads(after_path.read_text())
    )
    report["allowed_columns"] = {
        table: column for table, (_, column) in CAPTURE_FIELDS.items()
    }
    write_report(report_path, report, [before_path, after_path])
    return report

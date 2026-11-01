"""Fail-closed release comparison for proven roster-sync departure transitions.

The coordinator supplies snapshots and raw profiles from the same observations.
No database write or broad exclusion of departure flags is allowed here.
"""

import re
import json
from pathlib import Path
from bson import json_util

from copy import deepcopy
from datetime import datetime, timezone


def _utc(value):
    if not isinstance(value, datetime):
        raise ValueError("A typed profile timestamp is required")
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def compare_protected(
    before, after, profiles_before, profiles_after, *, started, ended
):
    """Return departure evidence or raise for any unproven protected change.

    Profile maps use (str(guild_id), player_tag) keys. Raw BSON-decoded profiles
    must be captured alongside each metrics snapshot, not reconstructed later.
    """
    required = {
        "active",
        "streaks",
        "replacement",
        "member_profiles_count",
        "member_profiles_digest",
        "warrior_settings_digest",
    }
    for snapshot in (before, after):
        if (
            not isinstance(snapshot, dict)
            or not required <= set(snapshot)
            or not isinstance(snapshot["active"], list)
            or not isinstance(snapshot["streaks"], list)
            or not snapshot["streaks"]
            or not isinstance(snapshot["replacement"], dict)
            or type(snapshot["member_profiles_count"]) is not int
            or snapshot["member_profiles_count"] <= 0
            or any(
                not isinstance(snapshot[key], str)
                or not re.fullmatch(r"[a-f0-9]{64}", snapshot[key])
                for key in ("member_profiles_digest", "warrior_settings_digest")
            )
        ):
            raise ValueError("Protected snapshot is empty or incomplete.")
    left, right = deepcopy(before), deepcopy(after)
    a, b = left.pop("replacement"), right.pop("replacement")
    if left != right or set(a) != set(b):
        raise ValueError("Protected state changed outside replacement departure")
    evidence = []
    for guild in a:
        old = {row[0]: list(row) for row in a[guild]}
        new = {row[0]: list(row) for row in b[guild]}
        if (
            len(old) != len(a[guild])
            or len(new) != len(b[guild])
            or set(old) != set(new)
        ):
            raise ValueError("Replacement membership changed")
        for player in old:
            prior, current = old[player], new[player]
            if prior == current:
                continue
            if (
                len(prior) != 5
                or len(current) != 5
                or prior[:4] != current[:4]
                or prior[4] is not False
                or current[4] is not True
            ):
                raise ValueError("Protected replacement data changed")
            key = (str(guild), player)
            p, q = profiles_before.get(key), profiles_after.get(key)
            if not p or not q or not p.get("current_clan_tag"):
                raise ValueError("Missing contemporaneous departure proof")
            observed = q.get("roster_observed_at")
            if not _utc(started) <= _utc(observed) <= _utc(ended):
                raise ValueError("Departure outside activation window")
            if _utc(
                p.get("roster_observed_at") or p.get("roster_seen_at") or observed
            ) > _utc(observed):
                raise ValueError("Stale roster observation")
            expected = deepcopy(p)
            clan = expected.pop("current_clan_tag")
            departed = p.get("departed_clan_tag")
            preserve = departed and departed in (
                p.get("replacement_clan_tag"),
                p.get("filler_clan_tag"),
            )
            expected.update(
                departed_clan_tag=departed if preserve else clan,
                roster_observed_at=observed,
                departed_last_seen_at=(
                    p.get("departed_last_seen_at")
                    if preserve
                    else p.get("roster_seen_at")
                )
                or observed,
            )
            if expected != q:
                raise ValueError("Raw profile differs from exact roster-sync departure")
            evidence.append(
                {
                    "guild_id": str(guild),
                    "player_tag": player,
                    "observed_at": _utc(observed).isoformat(),
                    "transition": "proven_roster_sync_departure",
                }
            )
    return evidence


def compare_capture_files(directory, before_name, after_name):
    directory = Path(directory)

    def load(name):
        metrics = json.loads((directory / (name + ".json")).read_text())
        proof = json_util.loads((directory / (name + "-profiles.json")).read_text())
        profiles = proof["profiles"]
        if not isinstance(profiles, list) or not profiles:
            raise ValueError("Missing contemporaneous profile evidence")
        mapping = {(str(row["guild_id"]), row["player_tag"]): row for row in profiles}
        expected = {(str(row[0]), row[1]) for row in metrics["streaks"]}
        if len(mapping) != len(profiles) or set(mapping) != expected:
            raise ValueError("Profile evidence does not match protected snapshot")
        return metrics, proof, mapping

    before, prior, profiles_before = load(before_name)
    after, current, profiles_after = load(after_name)
    evidence = compare_protected(
        before,
        after,
        profiles_before,
        profiles_after,
        started=prior["started"],
        ended=current["ended"],
    )
    report = directory / (after_name + "-comparison.json")
    report.write_text(
        json.dumps(
            {
                "compared_to": before_name,
                "departure_count": len(evidence),
                "observed_at": [row["observed_at"] for row in evidence],
            },
            indent=2,
        )
    )
    report.chmod(0o600)
    return evidence

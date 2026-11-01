"""Fail-closed release comparison for proven roster-sync departure transitions.

The coordinator supplies snapshots and raw profiles from the same observations.
No database write or broad exclusion of departure flags is allowed here.
"""

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

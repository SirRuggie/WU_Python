"""Read-only strike/activity signals; no transport or persistent writes."""

from datetime import datetime, timedelta, timezone

from utils.strike_store import stamp
from utils.player_activity_raids import latest_raid_end


def skipped_weekends(weekends, now):
    expected = latest_raid_end(now)
    by_end = {stamp(row["weekend_id"]): row for row in weekends}
    count = 0
    while expected in by_end and by_end[expected].get("attacked") is False:
        count += 1
        expected -= timedelta(days=7)
    return count


def activity_signals(
    activity, records, *, active_strikes=0, priority=None, now=None, tracking_fresh=None
):
    now = stamp(now or datetime.now(timezone.utc))
    activity = activity or {}
    if tracking_fresh is None:
        updated = activity.get("updated_at")
        tracking_fresh = bool(
            updated
            and now - timedelta(hours=36)
            <= stamp(updated)
            <= now + timedelta(minutes=5)
        )
    seen = activity.get("last_seen_at")
    quiet = (
        max(0, int((now - stamp(seen)).total_seconds() // 86400))
        if seen and tracking_fresh
        else None
    )
    regular = {}
    for row in activity.get("recent_wars", []):
        if row.get("unusable"):
            regular[row["war_key"]] = row
            continue
        used, available = row.get("attacks_used"), row.get("attacks_available")
        if (
            row.get("war_key")
            and row.get("occurred_at")
            and type(used) is int
            and type(available) is int
            and available == 2
            and 0 <= used <= available
        ):
            regular[row["war_key"]] = {**row, "missed_attacks": available - used}
    for row in records:
        if row.get("source") == "war" and (
            row.get("revoked_at")
            or row.get("kind") in ("mismatch", "exempt", "no_attack")
            or row.get("exemption")
        ):
            regular.pop(row.get("war_key"), None)
            continue
        # Imported ledgers omit completed members. Only full-lineup backfill or
        # monitored captures can establish the ordered sequence for this player.
        if (
            row.get("source") != "war"
            or row.get("capture_source") != "clash_api"
            or row.get("import_id")
            or row.get("war_type") == "cwl"
        ):
            continue
        if row.get("war_key"):
            regular[row["war_key"]] = row
    eligible = [
        row
        for row in regular.values()
        if row.get("kind") not in ("mismatch", "exempt", "no_attack", "cwl")
        and not row.get("exemption")
        and not row.get("neutral")
        and (
            row.get("unusable")
            or (
                type(row.get("missed_attacks")) is int
                and 0 <= row["missed_attacks"] <= 2
            )
        )
    ]
    wars = sorted(eligible, key=lambda row: stamp(row["occurred_at"]), reverse=True)[
        :14
    ]
    consecutive = 0
    for row in wars:
        if row.get("unusable") or row["missed_attacks"] != 2:
            break
        consecutive += 1
    missed = sum(row.get("missed_attacks", 0) for row in wars)
    usable_wars = [row for row in wars if not row.get("unusable")]
    attacking_wars = [row for row in usable_wars if row["missed_attacks"] < 2]
    # This is a war-end proxy, not an invented exact attack timestamp.
    last_attacked_war_end = max(
        (stamp(row["occurred_at"]) for row in attacking_wars), default=None
    )
    raid_end = latest_raid_end(now)
    raid_by_end = {
        stamp(row["weekend_id"]): row for row in activity.get("raid_weekends", [])
    }
    known_raids = [
        raid_by_end[end]
        for end in (raid_end, raid_end - timedelta(days=7))
        if end in raid_by_end and type(raid_by_end[end].get("attacked")) is bool
    ]
    raid_skips = skipped_weekends(activity.get("raid_weekends", []), now)
    latest_missed = bool(wars and wars[0].get("missed_attacks", 0) > 0)
    risk = (
        active_strikes >= 3
        or consecutive >= 3
        or (quiet is not None and quiet >= 14)
        or priority == "replace_first"
    )
    watch = (
        active_strikes in (1, 2)
        or (quiet is not None and 7 <= quiet < 14)
        or latest_missed
        or raid_skips > 0
        or priority == "high"
    )
    return {
        "status": "risk" if risk else "watch" if watch else "active",
        "last_seen_at": seen,
        "last_seen_source": activity.get("last_seen_source"),
        "tracking_started_at": activity.get("tracking_started_at"),
        "quiet_days": quiet,
        "activity_tracking_behind": not tracking_fresh,
        "missed_attacks": missed,
        "observed_attacks": sum(not row.get("unusable") for row in wars) * 2,
        "observed_wars": len(usable_wars),
        "attacked_wars": len(attacking_wars),
        "last_attacked_war_end": last_attacked_war_end,
        "observed_raid_weekends": len(known_raids),
        "attacked_raid_weekends": sum(row["attacked"] is True for row in known_raids),
        "no_attack_wars": consecutive,
        "war_chain_unavailable": bool(wars and wars[0].get("unusable")),
        "skipped_raid_weekends": raid_skips,
    }

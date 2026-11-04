"""Frozen955 read baseline for159 equality only; never imported by product code."""
from datetime import datetime, timedelta, timezone
from utils.strike_store import tag


async def activity_context_reference(self, guild_id, activity_tags):
    """Bounded family snapshot for the read-only activity overview."""
    from utils.player_activity_polling import active_clan
    clans = [row for row in await self.mongo.clans.find({}).to_list(length=None)
             if active_clan(row) and row.get('tag')]
    family = [row['tag'] for row in clans]
    players = [tag(value) for value in activity_tags]
    now = datetime.now(timezone.utc)
    profiles = await self.mongo.strike_profiles.find({
        'guild_id': int(guild_id), '$or': [{'current_clan_tag': {'$in': family}},
                                          {'player_tag': {'$in': players}},
                                          {'departed_clan_tag': {'$in': family},
                                           'departed_last_seen_at': {'$gte': now-timedelta(days=90)}}]}).to_list(length=None)
    players = list(set(players) | {row['player_tag'] for row in profiles})
    now = datetime.now(timezone.utc)
    records = await self.mongo.strike_records.find({
        'guild_id': int(guild_id), 'player_tag': {'$in': players},
        '$or': [{'occurred_at': {'$gte': now-timedelta(days=90)}},
                {'kind': 'strike', 'expires_at': {'$gt': now}}]},
        {'player_tag': 1, 'war_key': 1, 'kind': 1, 'source': 1, 'war_type': 1,
         'occurred_at': 1, 'missed_attacks': 1, 'expires_at': 1, 'revoked_at': 1,
         'capture_source': 1, 'import_id': 1, 'exemption': 1}).to_list(length=None)
    return {'profiles': profiles, 'records': records, 'clans': clans,
            'replacements': await self.replacement(guild_id, limit=None),
            'strike_limit': (await self.settings(guild_id))['strike_limit']}


async def overview_reference(self):
    """Read only page signals, never the large per-unit diff baseline."""
    fields = {
        key: 1
        for key in (
            "tag",
            "name",
            "current_clan_tag",
            "left_at",
            "last_seen_at",
            "last_seen_source",
            "tracking_started_at",
            "raid_weekends",
            "recent_wars",
            "updated_at",
            "baseline.townHallLevel",
        )
    }
    return await self.collection.find(
        {"kind": {"$ne": "history_clan"}}, fields
    ).to_list(length=None)


# Exact955 row assembler, renamed only, for ordinary no-Mongo equivalence.
from collections import defaultdict
from utils.strike_store import status_of, stamp

def family_activity_rows_reference(activity, profiles, records, clans, *, replacements=None, strike_limit=3, now=None):
    now = now or datetime.now(timezone.utc)
    updated = [stamp(row['updated_at']) for row in activity if row.get('updated_at')]
    tracking_fresh = bool(updated and now-timedelta(hours=36) <= max(updated) <= now+timedelta(minutes=5))
    clan_names = {row['tag']: row.get('name') or row['tag'] for row in clans}
    activities = {row['tag']: row for row in activity
                  if not row.get('left_at') or stamp(row['left_at']) >= now-timedelta(days=90)}
    by_profile = {row['player_tag']: row for row in profiles}
    by_record = defaultdict(list)
    for row in records:
        by_record[row['player_tag']].append(row)
    eligible = {row['player_tag']: row for row in replacements or []}
    result = []
    for player in sorted(set(activities) | set(by_profile)):
        item = activities.get(player, {})
        profile = by_profile.get(player, {})
        clan = item.get('current_clan_tag', profile.get('current_clan_tag'))
        left = bool(item.get('left_at') or (clan not in clan_names and profile.get('departed_clan_tag')))
        if left:
            clan = None
        if clan not in clan_names and not left:
            continue
        active = sum(row.get('kind')=='strike' and status_of(row, now)=='active' for row in by_record[player])
        marked = bool(profile.get('replacement_listed') and profile.get('replacement_clan_tag')==clan)
        filler = bool(profile.get('filler') and profile.get('filler_clan_tag')==clan)
        priority = profile.get('replacement_priority') if marked else 'replace_first' if filler else None
        replacement = eligible.get(player)
        if replacements is not None:
            marked = bool(replacement and replacement.get('replacement_listed'))
            filler = bool(replacement and replacement.get('filler'))
            priority = replacement.get('replacement_priority') if marked or filler else None
        signals = activity_signals(item, by_record[player], active_strikes=active, priority=priority, now=now, tracking_fresh=tracking_fresh and not left)
        if left:
            signals['quiet_days'] = None
            signals['activity_tracking_behind'] = False
        result.append({'player_tag': player, 'player_name': item.get('name') or profile.get('player_name') or player,
                       'current_clan_tag': clan, 'current_clan_name': clan_names.get(clan),
                       'last_clan_tag': profile.get('departed_clan_tag'),
                       'last_clan_name': clan_names.get(profile.get('departed_clan_tag')), 'left_clan': left,
                       'departed_at': item.get('left_at') or profile.get('departed_last_seen_at'),
                       'town_hall': profile.get('town_hall') or item.get('baseline', {}).get('townHallLevel'),
                       'weight': profile.get('weight'), 'active_strikes': active,
                       'over_limit': active >= strike_limit,
                       'new_this_week': any(row.get('kind')=='strike' and status_of(row,now)=='active'
                                            and now-timedelta(days=7) <= stamp(row['occurred_at']) <= now
                                            for row in by_record[player]),
                       'total_strikes': sum(row.get('kind') == 'strike' for row in by_record[player]),
                       'discord_id': str(profile['member_id']) if profile.get('member_id') else None,
                       'discord_name': profile.get('discord_name'), 'priority': priority,
                       'replacement_note': profile.get('replacement_note') or '',
                       'marked_for_replacement': (marked or filler or active>=3) if replacements is None else bool(replacement and (marked or filler or active>=3)),
                       'replacement_eligible_low': bool(replacement and active in (1, 2)),
                       'revision': profile.get('revision', 0), **signals})
    return result


# Frozen955 signal implementation. No import of the live signal function.
from utils.player_activity_raids import latest_raid_end


def skipped_weekends_reference(weekends, now):
    expected = latest_raid_end(now)
    by_end = {stamp(row["weekend_id"]): row for row in weekends}
    count = 0
    while expected in by_end and by_end[expected].get("attacked") is False:
        count += 1
        expected -= timedelta(days=7)
    return count


def activity_signals_reference(
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

# Bind only to frozen implementations inside this test reference module.
skipped_weekends = skipped_weekends_reference
activity_signals = activity_signals_reference

"""Read-only strike/activity signals; no transport or persistent writes."""
from datetime import datetime, timedelta, timezone

from utils.strike_store import stamp
from utils.player_activity_raids import latest_raid_end


def skipped_weekends(weekends, now):
    expected = latest_raid_end(now)
    by_end = {stamp(row['weekend_id']): row for row in weekends}
    count = 0
    while expected in by_end and by_end[expected].get('attacked') is False:
        count += 1
        expected -= timedelta(days=7)
    return count


def activity_signals(activity, records, *, active_strikes=0, priority=None, now=None, tracking_fresh=None):
    now = stamp(now or datetime.now(timezone.utc))
    activity = activity or {}
    if tracking_fresh is None:
        updated = activity.get('updated_at')
        tracking_fresh = bool(updated and now-timedelta(hours=36) <= stamp(updated) <= now+timedelta(minutes=5))
    seen = activity.get('last_seen_at')
    quiet = max(0, int((now-stamp(seen)).total_seconds()//86400)) if seen and tracking_fresh else None
    regular = {}
    for row in activity.get('recent_wars', []):
        used, available = row.get('attacks_used'), row.get('attacks_available')
        if (row.get('war_key') and row.get('occurred_at') and type(used) is int
                and type(available) is int and available == 2 and 0 <= used <= available):
            regular[row['war_key']] = {**row, 'missed_attacks': available-used}
    for row in records:
        if row.get('source') == 'war' and (row.get('kind') in ('mismatch', 'exempt', 'no_attack') or row.get('exemption')):
            regular.pop(row.get('war_key'), None)
            continue
        # Imported ledgers omit completed members. Only full-lineup backfill or
        # monitored captures can establish the ordered sequence for this player.
        if (row.get('source') != 'war' or row.get('capture_source') != 'clash_api'
                or row.get('import_id') or row.get('war_type') == 'cwl'):
            continue
        if row.get('war_key'):
            regular[row['war_key']] = row
    eligible = [row for row in regular.values()
                if row.get('kind') not in ('mismatch', 'exempt', 'no_attack', 'cwl')
                and not row.get('exemption') and type(row.get('missed_attacks')) is int
                and 0 <= row['missed_attacks'] <= 2]
    wars = sorted(eligible, key=lambda row: stamp(row['occurred_at']), reverse=True)[:14]
    consecutive = 0
    for row in wars:
        if row['missed_attacks'] != 2:
            break
        consecutive += 1
    missed = sum(row['missed_attacks'] for row in wars)
    raid_skips = skipped_weekends(activity.get('raid_weekends', []), now)
    latest_missed = bool(wars and wars[0]['missed_attacks'] > 0)
    risk = active_strikes >= 3 or consecutive >= 3 or (quiet is not None and quiet >= 14) or priority == 'replace_first'
    watch = (active_strikes in (1,2) or (quiet is not None and 7 <= quiet < 14)
             or latest_missed or raid_skips > 0 or priority == 'high')
    return {'status': 'risk' if risk else 'watch' if watch else 'active',
            'last_seen_at': seen, 'last_seen_source': activity.get('last_seen_source'),
            'tracking_started_at': activity.get('tracking_started_at'), 'quiet_days': quiet,
            'activity_tracking_behind': not tracking_fresh,
            'missed_attacks': missed, 'observed_attacks': len(wars)*2,
            'observed_wars': len(wars), 'no_attack_wars': consecutive,
            'skipped_raid_weekends': raid_skips}

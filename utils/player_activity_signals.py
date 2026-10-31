"""Read-only strike/activity signals; no transport or persistent writes."""
from datetime import datetime, timedelta, timezone

from utils.strike_store import stamp


def latest_raid_end(now):
    now = stamp(now)
    end = (now-timedelta(days=now.weekday())).replace(hour=7, minute=0, second=0, microsecond=0)
    return end if end <= now else end-timedelta(days=7)


def skipped_weekends(weekends, now):
    expected = latest_raid_end(now)
    by_end = {stamp(row['weekend_id']): row for row in weekends}
    count = 0
    while expected in by_end and by_end[expected].get('attacked') is False:
        count += 1
        expected -= timedelta(days=7)
    return count


def activity_signals(activity, records, *, active_strikes=0, priority=None, now=None):
    now = stamp(now or datetime.now(timezone.utc))
    activity = activity or {}
    seen = activity.get('last_seen_at')
    quiet = max(0, int((now-stamp(seen)).total_seconds()//86400)) if seen else None
    regular = {}
    for row in records:
        if row.get('source') != 'war' or row.get('kind') == 'cwl' or row.get('war_type') == 'cwl':
            continue
        if row.get('war_key'):
            regular[row['war_key']] = row
    wars = sorted(regular.values(), key=lambda row: stamp(row['occurred_at']), reverse=True)[:14]
    valid = [row for row in wars if type(row.get('missed_attacks')) is int and 0 <= row['missed_attacks'] <= 2]
    consecutive = 0
    for row in wars:
        if row.get('missed_attacks') != 2:
            break
        consecutive += 1
    missed = sum(row['missed_attacks'] for row in valid)
    raid_skips = skipped_weekends(activity.get('raid_weekends', []), now)
    latest_missed = bool(wars and type(wars[0].get('missed_attacks')) is int and wars[0]['missed_attacks'] > 0)
    risk = active_strikes >= 3 or consecutive >= 3 or (quiet is not None and quiet >= 14) or priority == 'replace_first'
    watch = (active_strikes in (1,2) or (quiet is not None and 7 <= quiet < 14)
             or latest_missed or raid_skips > 0 or priority == 'high')
    return {'status': 'risk' if risk else 'watch' if watch else 'active',
            'last_seen_at': seen, 'last_seen_source': activity.get('last_seen_source'),
            'tracking_started_at': activity.get('tracking_started_at'), 'quiet_days': quiet,
            'missed_attacks': missed, 'observed_attacks': len(valid)*2,
            'observed_wars': len(wars), 'no_attack_wars': consecutive,
            'skipped_raid_weekends': raid_skips}

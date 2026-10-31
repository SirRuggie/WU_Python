"""Merge official raid evidence once per ended weekend, retrying partial reads."""
from datetime import datetime, timedelta, timezone

from utils.strike_store import stamp


def timestamp(value):
    value = value if isinstance(value, datetime) else getattr(value, 'time', value)
    return stamp(value)


def latest_raid_end(now):
    now = timestamp(now)
    end = (now-timedelta(days=now.weekday())).replace(hour=7,minute=0,second=0,microsecond=0)
    return end if end <= now else end-timedelta(days=7)


async def capture_raids(store, client, clan_tags, *, now=None):
    now = timestamp(now or datetime.now(timezone.utc))
    latest_end = latest_raid_end(now)
    expected = [(latest_end-timedelta(days=7*index)).isoformat() for index in range(8)]
    rows = await store.all_players()
    pending = [row for row in rows if not set(expected).issubset(row.get('raid_checked_weekends', []))]
    if not pending:
        return {'weekends': 0, 'writes': 0, 'complete': True}
    weekends = {latest_end.isoformat(): {'end': latest_end, 'attacks': {}}}
    clan_tags = sorted(set(clan_tags))
    complete = bool(clan_tags)
    for clan in clan_tags:
        try:
            entries = await client.get_raid_log(clan, limit=9)
            if hasattr(entries, '__aiter__'):
                entries = [entry async for entry in entries]
            for entry in entries:
                end = timestamp(entry.end_time)
                key = end.isoformat()
                if end > now or key not in expected:
                    continue
                weekend = weekends.setdefault(key, {'end': end, 'attacks': {}})
                for member in entry.members:
                    attacks = member.attack_count
                    if type(attacks) is not int or attacks < 0:
                        raise ValueError('Invalid raid attack count')
                    player_clan = (member.tag, clan)
                    weekend['attacks'][player_clan] = max(attacks, weekend['attacks'].get(player_clan, 0))
        except Exception:
            complete = False
    writes = 0
    for row in pending:
        observations = {}
        checked = set(row.get('raid_checked_weekends', []))
        for key, weekend in weekends.items():
            if key in checked:
                continue
            attacks = sum(count for (player, clan), count in weekend['attacks'].items() if player == row['_id'])
            previous = row.get('previous_roster_at')
            latest = row.get('last_roster_at')
            since = row.get('family_since')
            observed = bool(complete and not row.get('left_at') and previous and latest and since
                            and timestamp(since) <= weekend['end']
                            and timestamp(previous) <= weekend['end'] <= timestamp(latest)
                            and timestamp(latest)-timestamp(previous) <= timedelta(minutes=90))
            observations[key] = (attacks, observed)
        writes += bool(await store.merge_raid_observations(row['_id'], observations, expected if complete else []))
    return {'weekends': len(weekends), 'writes': writes, 'complete': complete}

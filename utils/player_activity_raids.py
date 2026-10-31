"""Merge official raid evidence across the family; never infer historical skips."""
from datetime import datetime, timedelta, timezone

from utils.strike_store import stamp


def timestamp(value):
    value = value if isinstance(value, datetime) else getattr(value, 'time', value)
    return stamp(value)


async def capture_raids(store, client, clan_tags, *, now=None):
    now = now or datetime.now(timezone.utc)
    weekends = {}
    complete = True
    for clan in sorted(set(clan_tags)):
        try:
            entries = await client.get_raid_log(clan, limit=8)
            # coc exposes an async iterator; fixtures may supply ordinary lists.
            if hasattr(entries, '__aiter__'):
                entries = [entry async for entry in entries]
            for entry in entries:
                end = timestamp(entry.end_time)
                if end > now:
                    continue
                key = end.isoformat()
                weekend = weekends.setdefault(key, {'end': end, 'attacks': {}})
                for member in entry.members:
                    attacks = int(member.attack_count)
                    if attacks < 0:
                        raise ValueError('Invalid raid attack count')
                    player_clan = (member.tag, clan)
                    weekend['attacks'][player_clan] = max(
                        attacks, weekend['attacks'].get(player_clan, 0))
        except Exception:
            complete = False
    rows = await store.all_players()
    writes = 0
    for key, weekend in weekends.items():
        for row in rows:
            attacks = sum(count for (player, clan), count in weekend['attacks'].items()
                          if player == row['_id'])
            previous = row.get('previous_roster_at')
            latest = row.get('last_roster_at')
            since = row.get('family_since')
            observed = bool(complete and not row.get('left_at') and previous and latest and since
                            and timestamp(since) <= weekend['end']
                            and timestamp(previous) <= weekend['end'] <= timestamp(latest)
                            and timestamp(latest) - timestamp(previous) <= timedelta(minutes=90))
            writes += bool(await store.record_weekend(row['_id'], key, attacks,
                                                       observed_member=observed))
    return {'weekends': len(weekends), 'writes': writes, 'complete': complete}

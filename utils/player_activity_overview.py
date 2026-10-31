"""Assemble one compact family response from owner-provided snapshots."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from utils.player_activity_signals import activity_signals
from utils.strike_store import status_of, stamp


def family_activity_rows(activity, profiles, records, clans, *, replacements=None, strike_limit=3, now=None):
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

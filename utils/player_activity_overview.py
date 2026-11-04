"""Assemble one compact family response from owner-provided snapshots."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from utils.player_activity_signals import activity_signals
from utils.strike_store import status_of, stamp


def family_activity_rows(activity, profiles, records, clans, *, replacements=None, strike_limit=3, now=None, record_totals=None, include_unknown_clans=False):
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
        if clan not in clan_names and not left and not include_unknown_clans:
            continue
        totals = record_totals.get(player, {}) if record_totals is not None else None
        active = totals.get('active_strikes', 0) if totals is not None else sum(row.get('kind')=='strike' and status_of(row, now)=='active' for row in by_record[player])
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
                       'new_this_week': totals.get('new_this_week', False) if totals is not None else any(row.get('kind')=='strike' and status_of(row,now)=='active'
                                            and now-timedelta(days=7) <= stamp(row['occurred_at']) <= now
                                            for row in by_record[player]),
                       'total_strikes': totals.get('total_strikes', 0) if totals is not None else sum(row.get('kind') == 'strike' for row in by_record[player]),
                       'discord_id': str(profile['member_id']) if profile.get('member_id') else None,
                       'discord_name': profile.get('discord_name'), 'priority': priority,
                       'replacement_note': profile.get('replacement_note') or '',
                       'marked_for_replacement': (marked or filler or active>=3) if replacements is None else bool(replacement and (marked or filler or active>=3)),
                       'replacement_eligible_low': bool(replacement and active in (1, 2)),
                       'revision': profile.get('revision', 0), **signals})
    return result


def activity_view_context(core, activity, records, *, now=None):
    """Apply old filled eligibility; fresh headers select a safe cold subset."""
    now = now or datetime.now(timezone.utc)
    profiles = core['profiles']
    family = {row['tag'] for row in core['clans']}
    missing_optional = activity is None or records is None
    def known_family(row):
        return row.get('current_clan_tag') in family or (
            row.get('departed_clan_tag') in family
            and isinstance(row.get('departed_last_seen_at'), datetime)
            and stamp(row['departed_last_seen_at']) >= now-timedelta(days=90))
    if missing_optional:
        headers = {row['tag']: row for row in core.get('activity_headers', [])
                   if not row.get('left_at') or stamp(row['left_at']) >= now-timedelta(days=90)}
        def cold_visible(profile):
            header = headers.get(profile.get('player_tag'), {})
            clan = header.get('current_clan_tag', profile.get('current_clan_tag'))
            left = bool(header.get('left_at') or (clan not in family and profile.get('departed_clan_tag')))
            return clan in family or left
        profiles = [row for row in profiles if (core['clan_warning'] or known_family(row))
                    and (core['clan_warning'] or cold_visible(row))]
    if not core['clan_warning'] and not missing_optional:
        players = {row['tag'] for row in activity}
        profiles = [row for row in profiles if row.get('current_clan_tag') in family
            or row.get('player_tag') in players or (row.get('departed_clan_tag') in family
                and isinstance(row.get('departed_last_seen_at'), datetime)
                and stamp(row['departed_last_seen_at']) >= now-timedelta(days=90))]
    if any(not row.get('player_tag') for row in profiles):
        raise ValueError('Invalid strike profile identity')
    selected = {row['player_tag'] for row in profiles} | {row['tag'] for row in activity or []}
    if any(core['record_totals'].get(player, {}).get('invalid') for player in selected):
        raise ValueError('Invalid strike dates in activity ledger')
    return {'profiles': profiles, 'records': records or [],
            'clans': core['clans'], 'record_totals': core['record_totals'],
            'replacements': core['replacements'], 'strike_limit': core['strike_limit'],
            'include_unknown_clans': core['clan_warning']}

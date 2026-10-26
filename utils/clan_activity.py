"""Full-clan projections of game objects; never derive totals from linked players."""
from datetime import datetime, timezone
from math import isfinite


def epoch(value):
    value = value if isinstance(value, datetime) else getattr(value, 'time', None)
    if not isinstance(value, datetime):
        return None
    return int(value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp())


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0 else None


def war_summary(kind, war, clan_tag, *, now=None, accounts=None):
    if kind != 'war' or war is None:
        return {'state': kind if kind in ('none', 'private', 'error') else 'error'}
    state = getattr(war, 'state', None)
    state = str(getattr(state, 'value', state))
    if state == 'notInWar':
        return {'state': 'none'}
    if state not in ('preparation', 'inWar', 'warEnded'):
        return {'state': 'error'}
    ours, opponent = getattr(war, 'clan', None), getattr(war, 'opponent', None)
    if getattr(opponent, 'tag', None) == clan_tag:
        ours, opponent = opponent, ours
    if getattr(ours, 'tag', None) != clan_tag or opponent is None:
        return {'state': 'error'}
    starts, ends = epoch(getattr(war, 'start_time', None)), epoch(getattr(war, 'end_time', None))
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    stale = state != 'warEnded' and ends is not None and ends <= now
    def side(value):
        return {'tag': value.tag, 'name': value.name, 'stars': number(getattr(value, 'stars', None)),
                'destruction': number(getattr(value, 'destruction', None)),
                'attacks': number(getattr(value, 'attacks_used', None)),
                'badge_url': getattr(getattr(value, 'badge', None), 'medium', None)}
    size = number(getattr(war, 'team_size', None))
    per_member = number(getattr(war, 'attacks_per_member', None))
    personal = []
    if accounts is not None:
        members = {str(member.tag).upper(): member for member in (getattr(ours, 'members', None) or [])}
        for account in accounts:
            member = members.get(account.tag.upper())
            if member is None:
                continue
            attacks = getattr(member, 'attacks', None)
            used = len(attacks) if attacks is not None else None
            personal.append({'tag': account.tag, 'name': account.name,
                             'attacks_left': max(0, per_member - used) if per_member is not None and used is not None else None,
                             'attacks_total': per_member})
    return {'my_accounts': personal, 'state': 'awaitingResult' if stale else state, 'clan': side(ours), 'opponent': side(opponent),
            'team_size': size, 'attacks_total': size * per_member if size is not None and per_member is not None else None,
            'starts_at': starts, 'ends_at': ends}


def raid_summary(kind, raid):
    if kind != 'raid' or raid is None:
        return {'state': kind if kind in ('none', 'not_started', 'error') else 'error'}
    return {'state': 'active', 'starts_at': epoch(getattr(raid, 'start_time', None)),
            'ends_at': epoch(getattr(raid, 'end_time', None)),
            'attacks': number(getattr(raid, 'attack_count', None)),
            'districts': number(getattr(raid, 'destroyed_district_count', None)),
            'loot': number(getattr(raid, 'total_loot', None))}

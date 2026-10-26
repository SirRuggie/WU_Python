"""Full-clan projections of game objects; never derive totals from linked players."""
from datetime import datetime, timezone
from math import isfinite
from hashlib import sha256


def epoch(value):
    value = value if isinstance(value, datetime) else getattr(value, 'time', None)
    if not isinstance(value, datetime):
        return None
    return int(value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp())


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0 else None


def war_identity(war, clan_tag):
    """Stable identity for a displayed war, independent of side orientation."""
    sides = (getattr(war, 'clan', None), getattr(war, 'opponent', None))
    tags = [getattr(side, 'tag', None) for side in sides]
    if clan_tag not in tags or any(not tag for tag in tags):
        return None
    explicit = str(getattr(war, 'war_tag', '') or getattr(war, 'tag', '') or '')
    starts = epoch(getattr(war, 'start_time', None))
    ends = epoch(getattr(war, 'end_time', None))
    if not explicit and starts is None and ends is None:
        return None
    parts = (explicit, *sorted(tags), str(starts), str(ends))
    return sha256('|'.join(parts).encode()).hexdigest()[:24]


def _integer(value, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def _percent(value):
    parsed = number(value)
    return parsed if parsed is not None and parsed <= 100 else None


def war_detail(kind, war, clan_tag, *, linked_tags=(), league=False):
    """Project only public current-war roster and attacks from one checked war."""
    summary = war_summary(kind, war, clan_tag)
    if summary['state'] in ('none', 'private', 'error'):
        return summary
    ours, theirs = getattr(war, 'clan', None), getattr(war, 'opponent', None)
    if getattr(theirs, 'tag', None) == clan_tag:
        ours, theirs = theirs, ours
    linked = None if linked_tags is None else {str(tag).upper() for tag in linked_tags}
    per_member = number(getattr(war, 'attacks_per_member', None))
    if league and per_member is None:
        per_member = 1
    size = number(getattr(war, 'team_size', None))
    raw_members = {'clan': list(getattr(ours, 'members', None) or []),
                   'opponent': list(getattr(theirs, 'members', None) or [])}
    members_by_side = {side: members[:100] for side, members in raw_members.items()}
    def roster(side_name, members):
        result = []
        for member in members:
            tag = getattr(member, 'tag', None)
            if not isinstance(tag, str) or not tag:
                continue
            attacks = getattr(member, 'attacks', None)
            used = len(attacks) if attacks is not None else None
            if used is not None and used > 4:
                used = None
            result.append({'tag': tag, 'name': getattr(member, 'name', None) or tag,
                           'map_position': _integer(getattr(member, 'map_position', None), 1),
                           'town_hall': _integer(getattr(member, 'town_hall', None), 1),
                           'attacks_used': used,
                           'attacks_total': per_member,
                           'linked': None if linked is None else side_name == 'clan' and tag.upper() in linked})
        return sorted(result, key=lambda row: (row['map_position'] is None, row['map_position'] or 0, row['tag']))
    lineups = {side: roster(side, members) for side, members in members_by_side.items()}
    names = {row['tag'].upper(): row['name'] for rows in lineups.values() for row in rows}
    lineup_complete = size is not None and all(
        len(raw_members[side]) <= 100 and len(rows) == size
        and len({row['tag'].upper() for row in rows}) == size
        for side, rows in lineups.items())
    attacks_complete = lineup_complete
    attacks = []
    seen_orders = set()
    for side_name, members in members_by_side.items():
        for member in members:
            member_tag = getattr(member, 'tag', None)
            member_attacks = getattr(member, 'attacks', None)
            if member_attacks is None or len(member_attacks) > 4:
                attacks_complete = False
            for attack in (member_attacks or [])[:4]:
                attacker = getattr(attack, 'attacker_tag', member_tag)
                if attacker != member_tag:
                    attacks_complete = False
                defender = getattr(attack, 'defender_tag', None)
                if not isinstance(attacker, str):
                    attacks_complete = False
                    continue
                if not isinstance(defender, str):
                    defender = None
                    attacks_complete = False
                stars = _integer(getattr(attack, 'stars', None), 0, 3)
                destruction = _percent(getattr(attack, 'destruction', None))
                order = _integer(getattr(attack, 'order', None), 1)
                duration = _integer(getattr(attack, 'duration', None), 0)
                if stars is None or destruction is None or order is None or duration is None:
                    attacks_complete = False
                if order is not None:
                    if order in seen_orders:
                        attacks_complete = False
                    seen_orders.add(order)
                attacks.append({'side': side_name, 'attacker_tag': attacker,
                                'attacker_name': names.get(attacker.upper(), attacker),
                                'defender_tag': defender,
                                'defender_name': names.get(defender.upper(), defender) if defender else None,
                                'stars': stars,
                                'destruction': destruction,
                                'order': order,
                                'duration': duration,
                                'linked': None if linked is None else (side_name == 'clan'
                                          and attacker == member_tag and attacker.upper() in linked)})
    attacks.sort(key=lambda row: (row['order'] is None, row['order'] or 0,
                                  row['attacker_tag'], row['defender_tag'] or ''))
    return {**summary, 'war_id': war_identity(war, clan_tag),
            'attacks_per_member': per_member,
            'attacks_total': size * per_member if size is not None and per_member is not None else None,
            'lineup': lineups, 'lineup_complete': lineup_complete,
            'attacks': attacks, 'attacks_complete': attacks_complete}


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
            'war_id': war_identity(war, clan_tag), 'team_size': size, 'attacks_total': size * per_member if size is not None and per_member is not None else None,
            'starts_at': starts, 'ends_at': ends}


def raid_summary(kind, raid):
    if kind != 'raid' or raid is None:
        return {'state': kind if kind in ('none', 'not_started', 'error') else 'error'}
    return {'state': 'active', 'starts_at': epoch(getattr(raid, 'start_time', None)),
            'ends_at': epoch(getattr(raid, 'end_time', None)),
            'attacks': number(getattr(raid, 'attack_count', None)),
            'districts': number(getattr(raid, 'destroyed_district_count', None)),
            'loot': number(getattr(raid, 'total_loot', None))}

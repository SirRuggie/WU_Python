"""Normalize current-war and league-war objects from the official Clash API.

No historical provider is consulted here. An observation is never eligible for
automatic strikes until an official ``warEnded`` response passes completeness
checks and a prior active observation has been saved durably.
"""
from __future__ import annotations

from datetime import datetime

from utils.strike_store import tag, utc
from utils.strike_war_type import classify_war_type


def _time(value):
    value = getattr(value, 'time', value)
    if isinstance(value, datetime):
        return utc(value)
    return None


def _members(side, attack_limit):
    members = []
    for member in getattr(side, 'members', ()) or ():
        attacks = getattr(member, 'attacks', None)
        if not isinstance(attacks, (list, tuple)) or len(attacks) > attack_limit:
            raise ValueError('War attack list is incomplete.')
        members.append({'tag': tag(member.tag), 'name': getattr(member, 'name', None),
                        'town_hall': getattr(member, 'town_hall', None),
                        'map_position': getattr(member, 'map_position', None),
                        'attacks': len(attacks),
                        'attack_details': [{
                            'attacker_tag': tag(attack.attacker_tag),
                            'defender_tag': tag(attack.defender_tag),
                            'order': attack.order, 'stars': attack.stars,
                            'destruction': attack.destruction,
                            'duration': attack.duration,
                        } for attack in attacks]})
    if len({member['tag'] for member in members}) != len(members):
        raise ValueError('War roster has duplicate accounts.')
    return members


def normalize(war, clan_tag: str) -> dict | None:
    """Return a bounded, public-field snapshot, or None for explicit no-war."""
    observed_state = getattr(war, 'state', None)
    state = str(getattr(observed_state, 'value', observed_state) or '')
    if state == 'notInWar':
        return None
    if state not in ('preparation', 'inWar', 'warEnded'):
        raise ValueError('War state is unavailable.')
    sides = (getattr(war, 'clan', None), getattr(war, 'opponent', None))
    clan = next((side for side in sides if side is not None and
                 tag(getattr(side, 'tag', None)) == tag(clan_tag)), None)
    opponent = next((side for side in sides if side is not None and side is not clan), None)
    if clan is None or opponent is None:
        raise ValueError('War sides are incomplete.')
    attack_limit = getattr(war, 'attacks_per_member', None)
    end = _time(getattr(war, 'end_time', None))
    start = _time(getattr(war, 'start_time', None))
    preparation = _time(getattr(war, 'preparation_start_time', None))
    war_type = classify_war_type(start, preparation, war_tag=getattr(war, 'war_tag', None))
    team_size = getattr(war, 'team_size', None)
    if (not start or not end or start >= end or not isinstance(attack_limit, int)
            or isinstance(attack_limit, bool) or attack_limit not in (1, 2)):
        raise ValueError('War timing or attack limit is incomplete.')
    members = _members(clan, attack_limit)
    opponents = _members(opponent, attack_limit)
    def attack_total_matches(side, roster):
        total = getattr(side, 'attacks_used', None)
        return total is None or (isinstance(total, int) and not isinstance(total, bool)
                                 and total == sum(member['attacks'] for member in roster))
    complete = (isinstance(team_size, int) and not isinstance(team_size, bool)
                and 1 <= team_size <= 50 and len(members) == team_size
                and len(opponents) == team_size and war_type != 'unknown'
                and attack_total_matches(clan, members)
                and attack_total_matches(opponent, opponents))
    return {'clan_tag': tag(clan_tag), 'clan_name': getattr(clan, 'name', None),
            'opponent_tag': tag(opponent.tag), 'opponent_name': getattr(opponent, 'name', None),
            'start_time': start, 'preparation_start_time': preparation,
            'end_time': end, 'type': war_type,
            'state': state, 'attacks_per_member': attack_limit,
            'war_tag': tag(war.war_tag) if getattr(war, 'war_tag', None) else None,
            'complete': complete, 'team_size': team_size,
            'members': members, 'opponent_members': opponents}

"""Deterministic dashboard projections over the shared replacement candidates.

Priority marks and strike counts remain owned by StrikeService. These helpers
only select and order a read result; they never change the ledger or profiles.
"""
from __future__ import annotations

PRIORITY = {'replace_first': 0, 'high': 1, 'normal': 2}


def priority_key(row: dict) -> tuple:
    weight = row.get('weight')
    return (PRIORITY.get(row.get('replacement_priority'), 2),
            -row['active_strikes'], weight is None, weight or 0, row['player_tag'])


def replacement_page(rows: list[dict], *, include_low=False, clan=None,
                     town_hall=None, search='', sort='priority', offset=0, limit=25) -> dict:
    if sort not in ('priority', 'strikes', 'weight'):
        raise ValueError('Choose priority, most strikes, or weight.')
    if type(include_low) is not bool:
        raise ValueError('Choose whether to include one or two strikes.')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Choose a valid page.')
    if town_hall is not None and (type(town_hall) is not int or not 1 <= town_hall < 100):
        raise ValueError('Choose a valid Town Hall level.')
    search = str(search).strip().casefold()
    if len(search) > 80:
        raise ValueError('Use a shorter search.')
    eligible = [row for row in rows if
                (row.get('is_manual') or row['active_strikes'] >= (1 if include_low else 3))
                and (town_hall is None or row.get('town_hall') == town_hall)]
    top = sorted(eligible, key=priority_key)[:10]
    visible = [row for row in eligible if
               (not clan or row.get('last_seen_clan_tag') == clan)
               and (not search or search in ' '.join(str(row.get(key) or '') for key in
                    ('player_tag', 'player_name', 'member_id')).casefold())]
    def order(row):
        if sort == 'strikes':
            return (-row['active_strikes'], *priority_key(row))
        if sort == 'weight':
            return (row.get('weight') is None, row.get('weight') or 0, *priority_key(row))
        return priority_key(row)
    visible.sort(key=order)
    groups = {}
    for row in visible:
        tag = row['last_seen_clan_tag']
        group = groups.setdefault(tag, {'clan_tag': tag, 'listed': 0, 'at_three': 0,
                                       'chopping_block': 0, 'first': priority_key(row)})
        group['listed'] += 1
        group['at_three'] += row['active_strikes'] >= 3
        group['chopping_block'] += row.get('replacement_priority') == 'replace_first'
        group['first'] = min(group['first'], priority_key(row))
    summaries = sorted(groups.values(), key=lambda group: (group['first'], group['clan_tag']))
    return {'items': visible[offset:offset + limit], 'total': len(visible), 'top': top,
            'groups': [{k: v for k, v in group.items() if k != 'first'} for group in summaries]}


def best_slots(rows: list[dict], weight: int) -> list[dict]:
    """Closest eligible FWA weights; the caller supplies FWA-only candidates."""
    if type(weight) is not int or not 0 < weight <= 500000:
        raise ValueError('Enter a positive recruit weight.')
    known = [row for row in rows if type(row.get('weight')) is int and row['weight'] > 0]
    return sorted(known, key=lambda row: (abs(row['weight'] - weight), *priority_key(row)))[:3]

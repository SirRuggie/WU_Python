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


MAX_SLOT_WEIGHTS = 5
SLOTS_PER_WEIGHT = 3


def member_slot_tags(links) -> tuple[set[str] | None, set[str], bool]:
    """Linked tags for a read-only member slot search: (tags, disputed, partial).

    Every linked tag counts, verified or not. A tag also linked to another
    Discord user is kept and reported in disputed. partial means a provider's forward
    lookup failed (a reverse owner-check failure alone leaves nothing out).
    tags is None only when both providers failed and nothing came back.
    """
    disputed = set(links.conflicts)
    tags = set(links.sources) | disputed
    if not tags and {'ClashKing', 'ClashPerk'} <= set(links.forward_unavailable):
        return None, set(), False
    return tags, disputed, bool(links.forward_unavailable)


def slot_pool(rows: list[dict], *, fwa_tags, clan_tags=None, member_tags=None) -> list[dict]:
    """Candidate slots: FWA clans only; marked or 3+ strikes, or every linked account of one member.

    member_tags is the member's linked player tags: None means no member filter,
    an empty set means a member with no linked accounts (no slots).
    """
    fwa = set(fwa_tags)
    clans = set(clan_tags) if clan_tags else None
    member = set(member_tags) if member_tags is not None else None
    pool = []
    for row in rows:
        if row.get('last_seen_clan_tag') not in fwa:
            continue
        if clans is not None and row['last_seen_clan_tag'] not in clans:
            continue
        if member is not None:
            if row.get('player_tag') not in member:
                continue
        elif not (row.get('is_manual') or row['active_strikes'] >= 3):
            continue
        pool.append(row)
    return pool


def find_slots(rows: list[dict], weights: list[int], *, fwa_tags, clan_tags=None,
               member_tags=None) -> list[dict]:
    """Best three slots per weight, in input order; unknown weights are never matched."""
    if not weights or len(weights) > MAX_SLOT_WEIGHTS:
        raise ValueError(f'Enter 1 to {MAX_SLOT_WEIGHTS} weights.')
    for weight in weights:
        if type(weight) is not int or not 0 < weight <= 500000:
            raise ValueError('Enter a positive recruit weight.')
    known = [row for row in slot_pool(rows, fwa_tags=fwa_tags, clan_tags=clan_tags, member_tags=member_tags)
             if type(row.get('weight')) is int and row['weight'] > 0]
    groups = []
    for weight in weights:
        ranked = sorted(known, key=lambda row: (abs(row['weight'] - weight), *priority_key(row)))
        groups.append({'weight': weight, 'slots': [
            {**row, 'weight_difference': abs(row['weight'] - weight)}
            for row in ranked[:SLOTS_PER_WEIGHT]]})
    return groups

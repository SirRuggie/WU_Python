"""Pure read-plan helpers for StrikeService's activity ledger snapshot."""
from datetime import timedelta


def truthy(field):
    # Match Python truthiness of supported stored scalar values, including old
    # explicit null/empty values. Never turn an unavailable read into a count.
    return {'$not': [{'$in': [{'$ifNull': ['$' + field, None]}, [None, False, 0, '', [], {}]]}]}


def record_query(guild_id, players, now):
    query = {'guild_id': int(guild_id), '$or': [{'occurred_at': {'$gte': now-timedelta(days=90)}},
                    {'kind': 'strike', 'expires_at': {'$gt': now}}]}
    if players is not None:
        query['player_tag'] = {'$in': list(players)}
    return query


def count_pipeline(query, now):
    strike = {'$eq': ['$kind', 'strike']}
    not_removed = {'$not': [truthy('revoked_at')]}
    live = {'$and': [strike, not_removed, {'$gt': ['$expires_at', now]}]}
    invalid = {'$and': [strike, not_removed, {'$or': [
        {'$ne': [{'$type': '$expires_at'}, 'date']},
        {'$and': [live, {'$ne': [{'$type': '$occurred_at'}, 'date']}]},
    ]}]}
    return [{'$match': query}, {'$group': {
        '_id': '$player_tag', 'replacement_active': {'$sum': {'$cond': [{'$and': [strike, {'$eq': [{'$type': '$revoked_at'}, 'missing']}, {'$gt': ['$expires_at', now]}]}, 1, 0]}}, 'active_strikes': {'$sum': {'$cond': [live, 1, 0]}},
        'total_strikes': {'$sum': {'$cond': [strike, 1, 0]}},
        'new_this_week': {'$max': {'$cond': [{'$and': [live,
            {'$gte': ['$occurred_at', now-timedelta(days=7)]}, {'$lte': ['$occurred_at', now]}]}, 1, 0]}},
        'invalid': {'$sum': {'$cond': [invalid, 1, 0]}},
    }}]


def observation_query(query):
    # Imported strikes still contribute to count_pipeline. Imported neutral
    # dispositions must remain available to remove matching backfilled wars.
    return {'$and': [query, {'source': 'war'}, {'$or': [
        {'kind': {'$in': ['mismatch', 'exempt', 'no_attack']}},
        {'$expr': truthy('revoked_at')}, {'$expr': truthy('exemption')},
        {'capture_source': 'clash_api', 'war_type': {'$ne': 'cwl'},
         '$expr': {'$not': [truthy('import_id')]}},
    ]}]}


def decode_counts(rows, *, validate=True):
    if validate and any(row['invalid'] for row in rows):
        raise ValueError('Invalid strike dates in activity ledger')
    return {row['_id']: {'replacement_active': row['replacement_active'], 'active_strikes': row['active_strikes'],
                        'total_strikes': row['total_strikes'],
                        'new_this_week': bool(row['new_this_week']),
                        **({'invalid': row['invalid']} if not validate else {})} for row in rows}

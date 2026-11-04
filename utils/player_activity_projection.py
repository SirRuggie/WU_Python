"""Read-only page projection. Mongo retains missing/null/zero exactly."""

WAR_FIELDS = ('war_key', 'occurred_at', 'unusable', 'attacks_used',
              'attacks_available', 'neutral', 'kind', 'exemption', 'missed_attacks')

def overview_fields():
    fields = {name: 1 for name in ('tag', 'name', 'current_clan_tag', 'left_at',
        'last_seen_at', 'last_seen_source', 'tracking_started_at', 'updated_at',
        'baseline.townHallLevel')}
    fields.update({'recent_wars.' + name: 1 for name in WAR_FIELDS})
    fields.update({'raid_weekends.' + name: 1 for name in ('weekend_id', 'attacked')})
    return fields


def short_keys(value, names):
    # Filtering actual stored key/value pairs retains absent vs null vs zero.
    return {'$arrayToObject': {'$map': {
        'input': {'$filter': {'input': {'$objectToArray': value}, 'as': 'field',
                              'cond': {'$in': ['$$field.k', list(names)]}}},
        'as': 'field', 'in': {'k': {'$toString': {'$indexOfArray': [list(names), '$$field.k']}}, 'v': '$$field.v'}
    }}}


def _map_present(field, expression):
    return {'$cond': [{'$eq': [{'$type': '$' + field}, 'missing']}, '$$REMOVE',
                      {'$map': {'input': '$' + field, 'as': 'entry', 'in': expression}}]}


def dictionary_pipeline():
    """Deduplicate repeated war/weekend keys after native projection was too slow.

    This only changes the transient read representation, not domain rules. Every
    present signal field is reconstructed, including explicit null and zero.
    """
    raids = ('weekend_id', 'attacked')
    stages = [
        {'$match': {'kind': {'$ne': 'history_clan'}}},
        {'$project': overview_fields()},
        {'$set': {'recent_wars': _map_present('recent_wars', short_keys('$$entry', WAR_FIELDS)),
                  'raid_weekends': _map_present('raid_weekends', short_keys('$$entry', raids))}},
        {'$facet': {'players': [{'$match': {}}],
                    'war_keys': [{'$unwind': '$recent_wars'}, {'$group': {'_id': {'$getField': {'field': '0', 'input': '$recent_wars'}}}}],
                    'raid_keys': [{'$unwind': '$raid_weekends'}, {'$group': {'_id': {'$getField': {'field': '0', 'input': '$raid_weekends'}}}}]}},
        {'$set': {name: {'$map': {'input': '$' + name, 'as': 'key', 'in': '$$key._id'}} for name in ('war_keys', 'raid_keys')}},
    ]
    replacements = {}
    for field, table in (('recent_wars', 'war_keys'), ('raid_weekends', 'raid_keys')):
        replacements[field] = {'$cond': [{'$eq': [{'$type': '$$player.' + field}, 'missing']}, '$$REMOVE', {'$map': {
            'input': '$$player.' + field, 'as': 'entry', 'in': {'$cond': [
                {'$eq': [{'$type': '$$entry.0'}, 'missing']}, '$$entry',
                {'$mergeObjects': ['$$entry', {'0': {'$indexOfArray': ['$' + table, '$$entry.0']}}]}
            ]}
        }}]}
    stages.append({'$set': {'players': {'$map': {'input': '$players', 'as': 'player',
        'in': {'$mergeObjects': ['$$player', replacements]}}}}})
    return stages


def decode_dictionary(snapshot):
    result = []
    for source in snapshot['players']:
        player = dict(source)
        for field, names, table in (('recent_wars', WAR_FIELDS, snapshot['war_keys']),
                                     ('raid_weekends', ('weekend_id', 'attacked'), snapshot['raid_keys'])):
            if field not in player or player[field] is None:
                continue
            decoded = []
            for entry in player[field]:
                if not isinstance(entry, dict) or not set(entry).issubset({str(i) for i in range(len(names))}):
                    raise ValueError('Invalid transient activity observation')
                item = {}
                for key, value in entry.items():
                    if key == '0':
                        if type(value) is not int or not 0 <= value < len(table):
                            raise ValueError('Invalid transient activity key reference')
                        value = table[value]
                    item[names[int(key)]] = value
                decoded.append(item)
            player[field] = decoded
        result.append(player)
    return result

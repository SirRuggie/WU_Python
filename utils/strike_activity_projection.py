"""Lossless transient representation for fresh optional ledger observations."""

from utils.player_activity_projection import short_keys

FIELDS = ('player_tag', 'war_key', 'kind', 'source', 'capture_source', 'war_type',
          'occurred_at', 'missed_attacks', 'revoked_at', 'import_id', 'exemption')
DICTIONARIES = ((0, 'players'), (1, 'wars'), (2, 'kinds'), (3, 'sources'),
                (4, 'captures'), (9, 'imports'), (10, 'exemptions'))


def observation_pipeline(query):
    fields = {name: 1 for name in FIELDS}
    fields['_id'] = 0
    stages = [{'$match': query}, {'$project': fields},
              {'$project': {'value': short_keys('$$ROOT', FIELDS)}}]
    stages.append({'$facet': {'records': [{'$match': {}}], **{
        table: [{'$group': {'_id': '$value.' + str(index)}}]
        for index, table in DICTIONARIES}}})
    stages.append({'$set': {table: {'$map': {'input': '$' + table, 'as': 'item',
                            'in': '$$item._id'}} for _, table in DICTIONARIES}})
    substitutions = {str(index): {'$cond': [
        {'$eq': [{'$type': '$$record.value.' + str(index)}, 'missing']}, '$$REMOVE',
        {'$indexOfArray': ['$' + table, '$$record.value.' + str(index)]}]}
        for index, table in DICTIONARIES}
    stages.append({'$set': {'records': {'$map': {'input': '$records', 'as': 'record',
        'in': {'$mergeObjects': ['$$record.value', substitutions]}}}}})
    return stages


def decode_observations(snapshot):
    result = []
    dictionaries = {str(index): snapshot.get(table, []) for index, table in DICTIONARIES}
    for source in snapshot['records']:
        if not isinstance(source, dict) or not set(source).issubset({str(i) for i in range(len(FIELDS))}):
            raise ValueError('Invalid transient strike observation')
        row = {}
        for key, value in source.items():
            if key in dictionaries:
                table = dictionaries[key]
                if type(value) is not int or not 0 <= value < len(table):
                    raise ValueError('Invalid transient strike key reference')
                value = table[value]
            row[FIELDS[int(key)]] = value
        result.append(row)
    return result

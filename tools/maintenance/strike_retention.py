"""Backup, isolated restore verification, then opt-in strike TTL migration.

No TTL is installed unless the local dumps round-trip through a fresh throwaway
Mongo database. A failure leaves backups and installs no TTL. Never restore into
production. Run with the deployment's environment and explicit --apply.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from bson import json_util
from pymongo import MongoClient

from utils.mongo_routes import load_routes
from utils.strike_retention import validate_record_retention, snapshot_purge_after

COLLECTIONS = ('strike_records', 'strike_war_snapshots', 'strike_profiles')


def digest(rows):
    encoded = sorted(json_util.dumps(row, json_options=json_util.CANONICAL_JSON_OPTIONS)
                     for row in rows)
    return hashlib.sha256('\n'.join(encoded).encode()).hexdigest()


def migrate(client, routes, destination, *, apply=False):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    restore_name = 'wu_retention_restore_' + uuid4().hex
    restore = client[restore_name]
    manifest = {'collections': {}, 'restored': False, 'ttl_applied': False}
    try:
        for name in COLLECTIONS:
            route = routes[name]
            collection = client[route.database][route.collection]
            rows = list(collection.find({}))
            data = '\n'.join(json_util.dumps(row) for row in rows)
            path = destination / (name + '.jsonl')
            path.write_text(data)
            recovered = [json_util.loads(line) for line in path.read_text().splitlines()]
            if recovered:
                restore[name].insert_many(recovered)
            restored = list(restore[name].find({}))
            assert len(restored) == len(rows) and digest(restored) == digest(rows), name
            manifest['collections'][name] = {'count': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                             'content_sha256': digest(rows),
                                             'before': client[route.database].command('collStats', route.collection)}
        # A pending streak receipt must complete before any history is eligible
        # for deletion. Existing streak_count/watermark fields remain untouched.
        profiles = routes['strike_profiles']
        if client[profiles.database][profiles.collection].find_one({'streak_pending': {'$exists': True}}):
            raise RuntimeError('Pending streak receipts must finish before retention migration')
        manifest['restored'] = True
        if apply:
            for name, calculate in (('strike_records', validate_record_retention),
                                    ('strike_war_snapshots', snapshot_purge_after)):
                route = routes[name]
                collection = client[route.database][route.collection]
                for row in collection.find({}):
                    collection.update_one({'_id': row['_id']}, {'$set': {'purge_after': calculate(row)}})
            # No index is created before every dump and restore has succeeded.
            for name in ('strike_records', 'strike_war_snapshots'):
                route = routes[name]
                client[route.database][route.collection].create_index('purge_after', expireAfterSeconds=0,
                                                                      name='retention_purge_after')
            activity = routes['player_activity']
            client[activity.database][activity.collection].create_index('left_at', expireAfterSeconds=90*86400,
                                                                       name='activity_departure_retention')
            manifest['ttl_applied'] = True
        for name in COLLECTIONS:
            route = routes[name]
            manifest['collections'][name]['after'] = client[route.database].command('collStats', route.collection)
        return manifest
    finally:
        (destination / 'manifest.json').write_text(json_util.dumps(manifest, indent=2))
        client.drop_database(restore_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with MongoClient(os.environ['MONGODB_URI']) as client:
        result = migrate(client, load_routes(), args.output, apply=args.apply)
    print(json.dumps({'restore_verified': result['restored'], 'ttl_applied': result['ttl_applied']}))


if __name__ == '__main__':
    main()

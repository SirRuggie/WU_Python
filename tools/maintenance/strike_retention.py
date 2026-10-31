"""Private backup and separate-local-server restore gate for opt-in retention.

A dry run only reads the source. Restore always targets an explicitly supplied
local mongod that must differ from the source server. No Python assert is a gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

from bson import json_util
from pymongo import MongoClient

from utils.mongo_routes import load_routes
from utils.strike_retention import validate_record_retention, snapshot_purge_after
from utils.strike_retention_policy import SNAPSHOT_DAYS, DEPARTED_ACTIVITY_DAYS
from utils.strike_store import stamp

COLLECTIONS = ('strike_records', 'strike_war_snapshots', 'strike_profiles')


def digest(rows):
    encoded = sorted(json_util.dumps(row, json_options=json_util.CANONICAL_JSON_OPTIONS) for row in rows)
    return hashlib.sha256('\n'.join(encoded).encode()).hexdigest()


def validate_restore_uri(uri):
    parsed = urlsplit(uri)
    if (parsed.scheme != 'mongodb' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.port in (None, 27017) or parsed.username or parsed.password):
        raise ValueError('Restore requires an explicit isolated local mongod on a non-default port')
    return uri


def verify_separate_server(source, restore):
    if source is restore:
        raise ValueError('Restore server must differ from source')
    source_hello = source.admin.command('hello')
    restore_hello = restore.admin.command('hello')
    source_nodes, restore_nodes = set(source.nodes), set(restore.nodes)
    if not restore_nodes or any(host not in ('127.0.0.1', 'localhost', '::1') for host, port in restore_nodes):
        raise ValueError('Restore server must be local')
    if source_nodes & restore_nodes:
        raise ValueError('Restore server matches a source endpoint')
    source_id = source_hello.get('topologyVersion', {}).get('processId')
    restore_id = restore_hello.get('topologyVersion', {}).get('processId')
    if source_id is not None and source_id == restore_id:
        raise ValueError('Restore server is the source process')


def migrate(client, routes, destination, *, restore_client, apply=False, allow_empty=False):
    verify_separate_server(client, restore_client)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    restore_name = 'wu_retention_restore_' + uuid4().hex
    restore = restore_client[restore_name]
    manifest = {'collections': {}, 'restored': False, 'ttl_applied': False,
                'indexes': {name: 'not_applied' for name in (*COLLECTIONS[:2], 'player_activity')}}
    try:
        snapshots = {}
        for name in COLLECTIONS:
            route = routes[name]
            collection = client[route.database][route.collection]
            rows = list(collection.find({}))
            snapshots[name] = rows
            if not rows and not allow_empty:
                raise RuntimeError('Empty source collection requires explicit --allow-empty: ' + name)
            path = destination / (name + '.jsonl')
            path.write_text('\n'.join(json_util.dumps(row) for row in rows))
            recovered = [json_util.loads(line) for line in path.read_text().splitlines()]
            if recovered:
                restore[name].insert_many(recovered)
            restored = list(restore[name].find({}))
            if len(restored) != len(rows) or digest(restored) != digest(rows):
                raise RuntimeError('Restore verification failed: ' + name)
            manifest['collections'][name] = {'count': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                             'content_sha256': digest(rows),
                                             'before': client[route.database].command('collStats', route.collection)}
        if any('streak_pending' in row for row in snapshots['strike_profiles']):
            raise RuntimeError('Pending streak receipts must finish before retention migration')
        now = datetime.now(timezone.utc)
        manifest['unresolved_snapshots_over_30_days'] = sum(
            snapshot_purge_after(row) is None and stamp(row['end_time']) < now-timedelta(days=SNAPSHOT_DAYS)
            for row in snapshots['strike_war_snapshots'])
        # Validate every planned date before the first source mutation.
        plans = {'strike_records': [(row, validate_record_retention(row)) for row in snapshots['strike_records']],
                 'strike_war_snapshots': [(row, snapshot_purge_after(row)) for row in snapshots['strike_war_snapshots']]}
        manifest['restored'] = True
        if apply:
            for name, plan in plans.items():
                route = routes[name]
                collection = client[route.database][route.collection]
                for row, purge in plan:
                    update = {'$set': {'purge_after': purge}} if purge is not None else {'$unset': {'purge_after': ''}}
                    collection.update_one({'_id': row['_id']}, update)
            for name in ('strike_records', 'strike_war_snapshots', 'player_activity'):
                route = routes[name]
                manifest['indexes'][name] = 'attempting'
                try:
                    if name == 'player_activity':
                        client[route.database][route.collection].create_index('left_at', expireAfterSeconds=DEPARTED_ACTIVITY_DAYS*86400,
                                                                            name='activity_departure_retention')
                    else:
                        client[route.database][route.collection].create_index('purge_after', expireAfterSeconds=0,
                                                                            name='retention_purge_after')
                except Exception:
                    manifest['indexes'][name] = 'failed'
                    raise
                manifest['indexes'][name] = 'applied'
            manifest['ttl_applied'] = True
        for name in COLLECTIONS:
            route = routes[name]
            manifest['collections'][name]['after'] = client[route.database].command('collStats', route.collection)
        return manifest
    finally:
        try:
            (destination / 'manifest.json').write_text(json_util.dumps(manifest, indent=2))
        finally:
            restore_client.drop_database(restore_name)


def restore_backup(directory, restore_client):
    """Restore verified dumps to a fresh local recovery database, never in place."""
    if not restore_client.nodes:
        restore_client.admin.command('hello')
    if any(host not in ('127.0.0.1', 'localhost', '::1') or port == 27017
           for host, port in restore_client.nodes) or not restore_client.nodes:
        raise ValueError('Recovery target must be an isolated local mongod')
    directory = Path(directory)
    manifest = json_util.loads((directory/'manifest.json').read_text())
    recovered = {}
    for name in COLLECTIONS:
        path = directory/(name+'.jsonl')
        evidence = manifest['collections'][name]
        rows = [json_util.loads(line) for line in path.read_text().splitlines()]
        if (hashlib.sha256(path.read_bytes()).hexdigest() != evidence['sha256']
                or len(rows) != evidence['count'] or digest(rows) != evidence['content_sha256']):
            raise RuntimeError('Backup verification failed: '+name)
        recovered[name] = rows
    name = 'wu_retention_recovery_'+uuid4().hex
    try:
        for collection, rows in recovered.items():
            if rows:
                restore_client[name][collection].insert_many(rows)
            if digest(list(restore_client[name][collection].find({}))) != digest(rows):
                raise RuntimeError('Recovery verification failed: '+collection)
    except BaseException:
        restore_client.drop_database(name)
        raise
    return name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    parser.add_argument('--restore-backup')
    parser.add_argument('--restore-uri', required=True, type=validate_restore_uri)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--allow-empty', action='store_true')
    args = parser.parse_args(argv)
    if args.restore_backup:
        if args.apply or args.output or args.allow_empty:
            parser.error('--restore-backup cannot be combined with migration options')
        with MongoClient(args.restore_uri) as restore:
            print(json.dumps({'recovery_database': restore_backup(args.restore_backup, restore)}))
        return
    if not args.output:
        parser.error('--output is required for migration')
    with MongoClient(os.environ['MONGODB_URI']) as client, MongoClient(args.restore_uri) as restore:
        result = migrate(client, load_routes(), args.output, restore_client=restore,
                         apply=args.apply, allow_empty=args.allow_empty)
    print(json.dumps({'restore_verified': result['restored'], 'ttl_applied': result['ttl_applied'],
                      'indexes': result['indexes'],
                      'unresolved_over_30_days': result['unresolved_snapshots_over_30_days']}))


if __name__ == '__main__':
    main()

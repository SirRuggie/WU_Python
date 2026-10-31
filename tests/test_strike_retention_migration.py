from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json

import pytest

from tests.test_player_activity import NOW
from tools.maintenance.strike_retention import migrate, COLLECTIONS


class Collection:
    def __init__(self):
        self.rows = []
        self.indexes = []
    def find(self, query):
        return deepcopy(self.rows)
    def find_one(self, query):
        return next((row for row in self.rows if 'streak_pending' in row), None)
    def insert_many(self, rows):
        self.rows.extend(deepcopy(rows))
    def update_one(self, query, update):
        row=next(row for row in self.rows if row['_id']==query['_id'])
        row.update(update.get('$set',{}))
        for key in update.get('$unset',{}): row.pop(key,None)
    def create_index(self, field, **options):
        self.indexes.append((field, options))


class Database:
    def __init__(self):
        self.collections = {}
    def __getitem__(self, name):
        return self.collections.setdefault(name, Collection())
    def command(self, command, name):
        rows = self[name].rows
        return {'count': len(rows), 'size': len(repr(rows)), 'storageSize': len(repr(rows))}


class Client:
    def __init__(self, restore=False):
        self.databases = {}
        self.nodes = {('127.0.0.1',27155)} if restore else {('source.fixture',27017)}
        self.admin = SimpleNamespace(command=lambda *args: {'topologyVersion': {'processId': 'restore' if restore else 'source'}})
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def __getitem__(self, name):
        return self.databases.setdefault(name, Database())
    def drop_database(self, name):
        assert name.startswith('wu_retention_restore_')
        del self.databases[name]


def test_backup_restore_gate_precedes_ttl_and_preserves_profiles(tmp_path):
    client = Client()
    routes = {name: SimpleNamespace(database='fixture', collection=name)
              for name in (*COLLECTIONS, 'player_activity')}
    client['fixture']['strike_records'].rows = [{'_id': 'strike', 'occurred_at': NOW}]
    client['fixture']['strike_war_snapshots'].rows = [{'_id': 'war', 'end_time': NOW, 'status': 'finalized'}]
    profiles = [{'_id': 'profile', 'streak_count': 5, 'replacement_note': 'Keep'}]
    client['fixture']['strike_profiles'].rows = deepcopy(profiles)
    result = migrate(client, routes, tmp_path/'backup', restore_client=Client(restore=True), apply=True)
    assert result['restored'] and result['ttl_applied']
    assert client['fixture']['strike_profiles'].rows == profiles
    assert client['fixture']['strike_profiles'].indexes == []
    assert client['fixture']['strike_records'].indexes[0][1]['expireAfterSeconds']==0
    assert set(client.databases)=={'fixture'}
    client['fixture']['strike_profiles'].rows[0]['streak_pending'] = {'count': 6}
    with pytest.raises(RuntimeError, match='Pending streak'):
        migrate(client, routes, tmp_path/'pending', restore_client=Client(restore=True), apply=True)
    failed = json.loads((tmp_path/'pending/manifest.json').read_text())
    assert not failed['ttl_applied']


def test_restore_corruption_installs_no_ttl(tmp_path, monkeypatch):
    client = Client()
    routes = {name: SimpleNamespace(database='fixture', collection=name)
              for name in (*COLLECTIONS, 'player_activity')}
    client['fixture']['strike_records'].rows = [{'_id': 'strike', 'occurred_at': NOW}]
    monkeypatch.setattr(Collection, 'insert_many', lambda self, rows: None)
    with pytest.raises(RuntimeError, match="Restore verification"):
        migrate(client, routes, tmp_path/'corrupt', restore_client=Client(restore=True), apply=True)
    assert all(not collection.indexes for collection in client['fixture'].collections.values())


def populated():
    client = Client()
    routes = {name: SimpleNamespace(database='fixture', collection=name)
              for name in (*COLLECTIONS, 'player_activity')}
    for name, row in [('strike_records', {'occurred_at': NOW}),
                      ('strike_war_snapshots', {'end_time': datetime.now(timezone.utc)-timedelta(days=40), 'status': 'observing', 'purge_after': NOW}),
                      ('strike_profiles', {'streak_count': 5})]:
        client['fixture'][name].rows = [{'_id': name, **row}]
    return client, routes


def test_dry_run_never_mutates_source_and_reports_unresolved(tmp_path):
    client, routes = populated()
    before = deepcopy({key: value.rows for key, value in client['fixture'].collections.items()})
    result = migrate(client, routes, tmp_path/'dry', restore_client=Client(restore=True))
    assert result['restored'] and not result['ttl_applied']
    assert result['unresolved_snapshots_over_30_days'] == 1
    assert {key: value.rows for key, value in client['fixture'].collections.items()} == before
    assert all(not value.indexes for value in client['fixture'].collections.values())
    applied = migrate(client, routes, tmp_path/'apply', restore_client=Client(restore=True), apply=True)
    assert applied['ttl_applied']
    assert 'purge_after' not in client['fixture']['strike_war_snapshots'].rows[0]


def test_separate_server_and_empty_source_gates(tmp_path):
    client, routes = populated()
    with pytest.raises(ValueError, match='differ'):
        migrate(client, routes, tmp_path/'same', restore_client=client)
    alias = Client(restore=True)
    alias.nodes = client.nodes
    with pytest.raises(ValueError):
        migrate(client, routes, tmp_path/'alias', restore_client=alias)
    empty = Client()
    with pytest.raises(RuntimeError, match='Empty source'):
        migrate(empty, routes, tmp_path/'empty', restore_client=Client(restore=True), apply=True)
    assert not any(value.indexes for value in empty['fixture'].collections.values())
    assert migrate(empty, routes, tmp_path/'expected-empty', restore_client=Client(restore=True), allow_empty=True)['restored']


def test_partial_index_failure_is_reported_per_index(tmp_path, monkeypatch):
    client, routes = populated()
    original = Collection.create_index
    def fail_departure(self, field, **options):
        if field == 'left_at':
            raise RuntimeError('departure index unavailable')
        original(self, field, **options)
    monkeypatch.setattr(Collection, 'create_index', fail_departure)
    with pytest.raises(RuntimeError, match='departure index'):
        migrate(client, routes, tmp_path/'partial', restore_client=Client(restore=True), apply=True)
    result = json.loads((tmp_path/'partial/manifest.json').read_text())
    assert result['indexes'] == {'strike_records': 'applied', 'strike_war_snapshots': 'applied', 'player_activity': 'failed'}
    assert not result['ttl_applied']


@pytest.mark.parametrize('apply', [False, True])
def test_cli_passes_apply_flag_explicitly(tmp_path, monkeypatch, apply):
    from tools.maintenance import strike_retention as tool
    calls = []
    monkeypatch.setenv('MONGODB_URI', 'mongodb://source.fixture')
    monkeypatch.setattr(tool, 'MongoClient', lambda uri: Client(restore='27155' in uri))
    monkeypatch.setattr(tool, 'load_routes', lambda: {})
    def migration(*args, **kwargs):
        calls.append(kwargs)
        return {'restored': True, 'ttl_applied': kwargs['apply'], 'indexes': {}, 'unresolved_snapshots_over_30_days': 0}
    monkeypatch.setattr(tool, 'migrate', migration)
    tool.main(['--output', str(tmp_path/'cli'), '--restore-uri', 'mongodb://127.0.0.1:27155'] + (['--apply'] if apply else []))
    assert calls[0]['apply'] is apply


def test_restore_gate_survives_optimized_python(tmp_path):
    import subprocess
    import sys
    script = '''
from pathlib import Path
from tests.test_strike_retention_migration import populated, Client, Collection
from tools.maintenance.strike_retention import migrate
client, routes = populated()
Collection.insert_many = lambda self, rows: None
try:
    migrate(client, routes, Path(__import__('sys').argv[1]), restore_client=Client(restore=True), apply=True)
except RuntimeError:
    raise SystemExit(0)
raise SystemExit(9)
'''
    result = subprocess.run([sys.executable, '-O', '-c', script, str(tmp_path/'optimized')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_recovery_command_verifies_backup_before_any_insert(tmp_path):
    from tools.maintenance.strike_retention import restore_backup
    client, routes = populated()
    restore = Client(restore=True)
    migrate(client, routes, tmp_path/'backup', restore_client=restore)
    name = restore_backup(tmp_path/'backup', restore)
    assert len(restore[name]['strike_records'].rows) == 1
    path = tmp_path/'backup/strike_records.jsonl'
    path.write_text(path.read_text()+'\n{}')
    before = set(restore.databases)
    with pytest.raises(RuntimeError, match='Backup verification'):
        restore_backup(tmp_path/'backup', restore)
    assert set(restore.databases) == before

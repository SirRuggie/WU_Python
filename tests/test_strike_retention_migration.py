from copy import deepcopy
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
        next(row for row in self.rows if row['_id']==query['_id']).update(update['$set'])
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
    def __init__(self):
        self.databases = {}
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
    client['fixture']['strike_war_snapshots'].rows = [{'_id': 'war', 'end_time': NOW}]
    profiles = [{'_id': 'profile', 'streak_count': 5, 'replacement_note': 'Keep'}]
    client['fixture']['strike_profiles'].rows = deepcopy(profiles)
    result = migrate(client, routes, tmp_path/'backup', apply=True)
    assert result['restored'] and result['ttl_applied']
    assert client['fixture']['strike_profiles'].rows == profiles
    assert client['fixture']['strike_profiles'].indexes == []
    assert client['fixture']['strike_records'].indexes[0][1]['expireAfterSeconds']==0
    assert set(client.databases)=={'fixture'}
    client['fixture']['strike_profiles'].rows[0]['streak_pending'] = {'count': 6}
    with pytest.raises(RuntimeError, match='Pending streak'):
        migrate(client, routes, tmp_path/'pending', apply=True)
    failed = json.loads((tmp_path/'pending/manifest.json').read_text())
    assert not failed['ttl_applied']


def test_restore_corruption_installs_no_ttl(tmp_path, monkeypatch):
    client = Client()
    routes = {name: SimpleNamespace(database='fixture', collection=name)
              for name in (*COLLECTIONS, 'player_activity')}
    client['fixture']['strike_records'].rows = [{'_id': 'strike', 'occurred_at': NOW}]
    monkeypatch.setattr(Collection, 'insert_many', lambda self, rows: None)
    with pytest.raises(AssertionError):
        migrate(client, routes, tmp_path/'corrupt', apply=True)
    assert all(not collection.indexes for collection in client['fixture'].collections.values())

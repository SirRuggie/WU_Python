from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import sqlite3

import pytest
from pymongo.errors import DuplicateKeyError

from cwl_web.store import Store
from utils.clan_weight_trial_store import ClanWeightTrialStore
from utils.cwl_dashboard_state import (
    MongoDashboardState, DashboardDurabilityError, encode, decode, utcnow, database_lock,
)


class Collection:
    def __init__(self):
        self.doc = None
        self.fail = None

    def matches(self, query):
        if self.doc is None:
            return False
        for key, value in query.items():
            if key == '$or':
                if not any(self.matches(item) for item in value):
                    return False
            elif isinstance(value, dict) and '$lte' in value:
                if self.doc[key] > value['$lte']:
                    return False
            elif self.doc.get(key) != value:
                return False
        return True

    def insert_one(self, document):
        if self.doc:
            raise DuplicateKeyError('existing')
        self.doc = deepcopy(document)

    def update_one(self, query, update):
        if self.fail == 'before':
            raise RuntimeError('offline')
        matches = self.matches(query)
        if matches:
            self.doc.update(deepcopy(update.get('$set', {})))
            for key, value in update.get('$inc', {}).items():
                self.doc[key] += value
        if self.fail == 'after':
            raise RuntimeError('lost acknowledgement')
        return SimpleNamespace(matched_count=int(matches))

    def find_one_and_update(self, query, update, **kwargs):
        result = self.update_one(query, update)
        return deepcopy(self.doc) if result.matched_count else None


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / 'original.sqlite'
    store = Store(path)
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES(1,'November 2026')")
        db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(1,'#ABC','123','lazy',0,'Name',17)")
        db.execute("INSERT INTO roster_entries(season_id,tag,manual_weight) VALUES(1,'#ABC',149000)")
    collection = Collection()
    owner = MongoDashboardState(collection)
    owner.seed(path)
    owner.restore(path)
    store = Store(path, durability=owner)
    return path, store, owner, collection


def test_successful_save_recovers_on_empty_replacement_server(setup, tmp_path):
    path, store, owner, collection = setup
    with store.tx() as db:
        db.execute('UPDATE roster_entries SET manual_weight=150000')
    trial = ClanWeightTrialStore(path, transaction_factory=store.tx)
    trial.save({'tag': '#CLAN', 'name': 'FWA clan', 'members': [
        {'tag': '#ABC', 'name': 'Name', 'town_hall': 17}]},
        [{'tag': '#ABC', 'revision': 0, 'weight': 149000, 'storages': 5}], '123', 'Discord name')
    trial.remember_lineup('#CLAN', {'order': {'#ABC': 1}, 'state': 'warEnded', 'end_time': '20261021T070000.000Z'})
    owner.close()
    replacement = tmp_path / 'new-server' / 'recovered.sqlite'
    recovered = MongoDashboardState(collection)
    recovered.restore(replacement)
    new = Store(replacement, durability=recovered)
    assert new.one('SELECT manual_weight FROM roster_entries')['manual_weight'] == 150000
    assert new.one('SELECT count(*) n FROM signups')['n'] == 1
    assert new.one('SELECT weight FROM clan_weight_trial')['weight'] == 149000
    assert ClanWeightTrialStore(replacement).saved_lineup('#CLAN')['order'] == {'#ABC': 1}
    assert new.one('SELECT actor_name FROM clan_weight_trial_history')['actor_name'] == 'Discord name'


@pytest.mark.parametrize('failure,expected', [('before', 149000), ('after', 151000)])
def test_unknown_mongo_result_fences_writes_and_restores_truth(setup, tmp_path, failure, expected):
    path, store, owner, collection = setup
    collection.fail = failure
    with pytest.raises(DashboardDurabilityError):
        with store.tx() as db:
            db.execute('UPDATE roster_entries SET manual_weight=151000')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT manual_weight FROM roster_entries').fetchone()[0] == 149000
    with pytest.raises(DashboardDurabilityError):
        with store.tx():
            pass
    collection.fail = None
    owner.close()
    replacement = MongoDashboardState(collection)
    recovered = tmp_path / 'recovered.sqlite'
    replacement.restore(recovered)
    assert Store(recovered).one('SELECT manual_weight FROM roster_entries')['manual_weight'] == expected


def test_crash_after_mongo_before_sqlite_commit_recovers_change(setup, tmp_path):
    path, store, owner, collection = setup
    with sqlite3.connect(path) as db:
        db.execute('UPDATE roster_entries SET manual_weight=152000')
        owner.publish(db)
        db.rollback()  # Crash loses the local transaction, but not the Mongo head.
    collection.doc['lease_until'] = utcnow() - timedelta(seconds=1)
    replacement = MongoDashboardState(collection)
    recovered = tmp_path / 'crash-recovered.sqlite'
    replacement.restore(recovered)
    assert Store(recovered).one('SELECT manual_weight FROM roster_entries')['manual_weight'] == 152000
    with pytest.raises(DashboardDurabilityError):
        with store.tx() as db:
            db.execute('UPDATE roster_entries SET manual_weight=153000')


def test_second_server_cannot_claim_active_writer(setup):
    _, _, _, collection = setup
    with pytest.raises(DashboardDurabilityError):
        MongoDashboardState(collection).acquire()


def test_rollback_does_not_publish(setup):
    _, store, owner, collection = setup
    revision = owner.revision
    with pytest.raises(ValueError):
        with store.tx() as db:
            db.execute('UPDATE roster_entries SET manual_weight=160000')
            raise ValueError('invalid request')
    assert collection.doc['revision'] == revision


def test_read_only_transaction_does_not_write_checkpoint(setup):
    _, store, owner, collection = setup
    revision = owner.revision
    with store.tx() as db:
        db.execute('SELECT * FROM signups').fetchall()
    assert collection.doc['revision'] == revision


def test_corrupt_checkpoint_does_not_replace_local_database(setup):
    path, store, owner, collection = setup
    owner.close()
    collection.doc['sha256'] = 'corrupted'
    with pytest.raises(DashboardDurabilityError):
        MongoDashboardState(collection).restore(path)
    assert Store(path).one('SELECT count(*) n FROM signups')['n'] == 1


def test_missing_mongo_never_initializes_empty_replacement(tmp_path):
    path = tmp_path / 'absent.sqlite'
    with pytest.raises(DashboardDurabilityError):
        MongoDashboardState(Collection()).restore(path)
    assert not path.exists()


def test_seed_does_not_overwrite_existing_state(setup):
    path, _, owner, _ = setup
    with pytest.raises(DuplicateKeyError):
        owner.seed(path)


def test_local_process_lock_blocks_recovery_race(tmp_path):
    path = tmp_path / 'database.sqlite'
    with database_lock(path):
        with pytest.raises(DashboardDurabilityError):
            with database_lock(path):
                pass


def test_empty_or_invalid_database_cannot_seed(tmp_path):
    owner = MongoDashboardState(Collection())
    with pytest.raises(DashboardDurabilityError):
        owner.seed(tmp_path / 'missing.sqlite')
    bad = tmp_path / 'bad.sqlite'
    with sqlite3.connect(bad) as db:
        db.execute('CREATE TABLE wrong(x)')
    with pytest.raises(DashboardDurabilityError):
        owner.seed(bad)


def test_corrupt_local_file_is_replaced_from_verified_mongo(setup):
    path, _, owner, collection = setup
    owner.close()
    path.write_bytes(b'corrupt local database')
    replacement = MongoDashboardState(collection)
    replacement.restore(path)
    assert Store(path).one('SELECT count(*) n FROM signups')['n'] == 1
    assert path.with_name(path.name + '.before-mongo').read_bytes() == b'corrupt local database'


def test_real_mongo_recovery_when_local_binary_is_available(setup, tmp_path, monkeypatch):
    """Opt-in standalone authenticated Mongo; no production URI or test credentials."""
    import os
    import secrets
    import socket
    import subprocess
    import time
    from pymongo import MongoClient
    from urllib.parse import quote

    binary = os.environ.get('CWL_RECOVERY_MONGOD')
    if not binary:
        pytest.skip('Set CWL_RECOVERY_MONGOD to run an isolated real Mongo recovery drill')
    monkeypatch.delenv('MONGODB_ROUTES', raising=False)
    source, _, _, _ = setup
    data = tmp_path / 'mongodata'
    data.mkdir()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    uri = f'mongodb://127.0.0.1:{port}/?directConnection=true'
    with (tmp_path / 'mongod.log').open('w') as log:
        proc = subprocess.Popen([binary, '--dbpath', str(data), '--bind_ip', '127.0.0.1',
            '--port', str(port), '--auth', '--nounixsocket', '--wiredTigerCacheSizeGB', '0.25'], stdout=log, stderr=log)
        first = second = None
        try:
            with MongoClient(uri, serverSelectionTimeoutMS=500) as bootstrap:
                for _ in range(40):
                    try:
                        bootstrap.admin.command('ping')
                        break
                    except Exception:
                        assert proc.poll() is None
                        time.sleep(0.1)
                password = secrets.token_urlsafe(24)
                bootstrap.admin.command('createUser', 'recovery', pwd=password, roles=[{'role': 'root', 'db': 'admin'}])
            authenticated = f'mongodb://recovery:{quote(password, safe="")}@127.0.0.1:{port}/?authSource=admin&directConnection=true'
            first = MongoDashboardState.open(authenticated)
            first.seed(source)
            first.restore(source)
            store = Store(source, durability=first)
            with store.tx() as db:
                db.execute('UPDATE roster_entries SET manual_weight=179000')
            first.close()
            first = None
            second = MongoDashboardState.open(authenticated)
            replacement = tmp_path / 'replacement-server.sqlite'
            second.restore(replacement)
            assert Store(replacement).one('SELECT manual_weight FROM roster_entries')['manual_weight'] == 179000
            assert second.collection.write_concern.document == {'w': 'majority', 'j': True, 'wtimeout': 5000}
        finally:
            for client in (first, second):
                if client:
                    client.close()
            proc.terminate()
            proc.wait(timeout=20)


def test_local_commit_failure_fences_process_but_mongo_has_saved_change(setup, monkeypatch):
    _, store, owner, collection = setup
    original = sqlite3.connect

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError('simulated disk failure')

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', lambda *args, **kwargs: original(*args, factory=FailedCommit, **kwargs))
        with pytest.raises(sqlite3.OperationalError):
            with store.tx() as db:
                db.execute('UPDATE roster_entries SET manual_weight=155000')
    assert owner.poisoned
    recovered = decode(collection.doc)
    try:
        assert recovered.execute('SELECT manual_weight FROM roster_entries').fetchone()[0] == 155000
    finally:
        recovered.close()


def test_heartbeat_failure_fences_further_writes(setup):
    _, store, owner, collection = setup
    collection.fail = 'before'
    with pytest.raises(DashboardDurabilityError):
        owner.heartbeat()
    with pytest.raises(DashboardDurabilityError):
        with store.tx():
            pass

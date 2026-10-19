import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from cwl_web.store import Store
from cwl_web.player_weights import record, sync


class PlayerWeights(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name)/'test.sqlite'))

    def tearDown(self):
        self.temp.cleanup()

    def signup(self, season):
        with self.store.tx() as db:
            db.execute('INSERT INTO seasons(id,label) VALUES (?,?)',(season,str(season)))
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,'#P2Y','123','lazy',0,'Player',16)",(season,))

    async def test_carry_forward_clear_and_history_survive_restart(self):
        with self.store.tx() as db:
            record(db,'#P2Y',150000,1,'staff')
            record(db,'#P2Y',155000,1,'staff')
        self.store = Store(self.store.path)
        self.signup(2)
        self.assertEqual(self.store.one('SELECT manual_weight FROM roster_entries')['manual_weight'],155000)
        self.assertEqual(self.store.one('SELECT initial_weight FROM player_weights')['initial_weight'],150000)
        with self.store.tx() as db:
            record(db,'#P2Y',None,2,'staff')
        self.signup(3)
        self.assertIsNone(self.store.one('SELECT * FROM roster_entries WHERE season_id=3'))
        self.assertEqual(self.store.one('SELECT manual_weight FROM roster_entries WHERE season_id=2')['manual_weight'],155000)
        self.assertEqual(len(self.store.rows('SELECT * FROM player_weight_events')),3)

    async def test_failed_mongo_sync_retains_queue_and_retry_is_idempotent(self):
        with self.store.tx() as db:
            record(db,'#P2Y',150000,1,'staff')
        collection=SimpleNamespace(update_one=AsyncMock(side_effect=RuntimeError('offline')))
        db=SimpleNamespace(fwa_data=SimpleNamespace(database=SimpleNamespace(get_collection=lambda *a,**kw:collection)))
        app={'store':self.store,'server_management_mongo':db}
        with self.assertRaises(RuntimeError):
            await sync(app)
        self.assertEqual(self.store.one('SELECT synced FROM player_weight_events')['synced'],0)
        collection.update_one=AsyncMock()
        collection.find=lambda *a:SimpleNamespace(to_list=AsyncMock(return_value=[]))
        await sync(app)
        await sync(app)
        self.assertEqual(collection.update_one.await_count,1)
        self.assertEqual(self.store.one('SELECT synced FROM player_weight_events')['synced'],1)

    async def test_recovery_imports_mongo_history_and_initial_value(self):
        records=[{'event_id':'first','tag':'#P2Y','weight':140000,'season_id':1,'actor_id':'staff','recorded_at':'2026-01-01T00:00:00+00:00'},
                 {'event_id':'second','tag':'#P2Y','weight':150000,'season_id':2,'actor_id':'staff','recorded_at':'2026-02-01T00:00:00+00:00'}]
        collection=SimpleNamespace(update_one=AsyncMock(),find=lambda *a:SimpleNamespace(to_list=AsyncMock(return_value=records)))
        shared=SimpleNamespace(fwa_data=SimpleNamespace(database=SimpleNamespace(get_collection=lambda *a,**kw:collection)))
        await sync({'store':self.store,'server_management_mongo':shared})
        self.signup(3)
        self.assertEqual(self.store.one('SELECT manual_weight FROM roster_entries')['manual_weight'],150000)
        self.assertEqual(self.store.one('SELECT initial_weight FROM player_weights')['initial_weight'],140000)
        self.assertEqual(len(self.store.rows('SELECT * FROM player_weight_events WHERE synced=1')),2)

    async def test_legacy_migration_preserves_edits_and_is_repeatable(self):
        import json
        with self.store.tx() as db:
            db.execute('DELETE FROM player_weight_migrations')
            for before,after in [(None,140000),(140000,150000),(150000,None)]:
                db.execute("INSERT INTO roster_audit(season_id,tag,actor_id,action,before_json,after_json) VALUES (1,'#P2Y','staff','manual_roster_edit',?,?)",(json.dumps({'manual_weight':before}),json.dumps({'manual_weight':after})))
        self.store=Store(self.store.path)
        self.store=Store(self.store.path)
        row=self.store.one('SELECT * FROM player_weights')
        self.assertIsNone(row['weight'])
        self.assertEqual(row['initial_weight'],140000)
        self.assertEqual(len(self.store.rows('SELECT * FROM player_weight_events')),3)

    async def test_failed_roster_transaction_cannot_queue_a_weight(self):
        with self.assertRaises(RuntimeError):
            with self.store.tx() as db:
                record(db,'#P2Y',150000,1,'staff')
                raise RuntimeError('rollback')
        self.assertEqual(self.store.rows('SELECT * FROM player_weight_events'),[])
        self.assertEqual(self.store.rows('SELECT * FROM player_weights'),[])

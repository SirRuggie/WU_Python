import asyncio
from types import SimpleNamespace
import pytest
from pymongo.errors import OperationFailure
from utils.player_activity_polling import poll_hour


def test_poll_spreads_hour_and_failure_does_not_write():
    async def run():
        writes = []
        delays = []
        tick = [0.0]
        async def sleep(delay):
            delays.append(delay)
            tick[0] += delay
        async def fetch(tag):
            if tag == '#B':
                raise TimeoutError()
            return {'tag': tag, 'attackWins': 1}
        async def record(player, clan):
            writes.append((player, clan))
        result = await poll_hour(SimpleNamespace(record=record),
                                 {'#A': '#CLAN', '#B': '#CLAN'}, fetch,
                                 sleep=sleep, clock=lambda: tick[0])
        assert delays == [0, 1800]
        assert result == {'success': 1, 'failure': 1}
        assert len(writes) == 1
    asyncio.run(run())


def test_identity_mismatch_and_cancellation_do_not_write():
    async def run():
        writes = []
        async def record(*args):
            writes.append(args)
        async def wrong(tag):
            return {'tag': '#OTHER'}
        async def no_sleep(delay):
            pass
        store = SimpleNamespace(record=record)
        result = await poll_hour(store, {'#A': '#CLAN'}, wrong, sleep=no_sleep)
        assert result['failure'] == 1
        assert writes == []
        async def cancel(tag):
            raise asyncio.CancelledError()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await poll_hour(store, {'#A': '#CLAN'}, cancel, sleep=no_sleep)
        assert writes == []
    asyncio.run(run())


def test_worker_cancels_its_background_seed_on_shutdown(monkeypatch):
    from utils import player_activity_polling as polling
    async def scenario():
        seed_started = asyncio.Event()
        seed_stopped = asyncio.Event()
        class Store:
            def __init__(self, mongo):
                pass
            async def ensure_indexes(self):
                pass
            async def reconcile_membership(self, members):
                pass
        async def family(*args):
            return polling.RosterSweep({'#A': '#CLAN'}, ['#CLAN'], True)
        async def raids(*args):
            return {}
        async def hour(*args, **kwargs):
            return {'success': 1, 'failure': 0}
        async def seed(store):
            seed_started.set()
            try:
                await asyncio.Future()
            finally:
                seed_stopped.set()
        monkeypatch.setattr(polling, 'PlayerActivityStore', Store)
        monkeypatch.setattr(polling, 'family_members', family)
        monkeypatch.setattr(polling, 'capture_raids', raids)
        monkeypatch.setattr(polling, 'poll_hour', hour)
        monkeypatch.setattr(polling, 'seed_from_clashking', seed)
        task = asyncio.create_task(polling.run(None, SimpleNamespace(get_player=None)))
        await seed_started.wait()
        task.cancel()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await task
        assert seed_stopped.is_set()
    asyncio.run(scenario())


@pytest.mark.parametrize('failed_index,error', [
    ('activity_family_clan', TimeoutError('fixture index timeout')),
    ('activity_departed_player_180d', OperationFailure('fixture index conflict', code=85)),
])
def test_index_failure_preserves_same_sweep_retries_next_hour_and_logs_index(
    monkeypatch, caplog, failed_index, error,
):
    from utils import player_activity_polling as polling, player_activity_history as history
    from tests.test_player_activity_retention_239n import IndexCollection
    from tests.test_player_activity_store import PLAYER, CLAN
    from tests.test_player_activity import NOW
    from utils.player_activity_store import PlayerActivityStore

    async def scenario():
        events = []
        real_sleep = asyncio.sleep

        class FailingCollection(IndexCollection):
            failed = False

            async def create_index(self, field, **options):
                await super().create_index(field, **options)
                events.append(('index', options['name']))
                if not self.failed and options['name'] == failed_index:
                    self.failed = True
                    raise error

        collection = FailingCollection()
        mongo = SimpleNamespace(player_activity=collection)
        await PlayerActivityStore(mongo).record({'tag': PLAYER, 'attackWins': 1}, CLAN, now=NOW)
        collection.rows[PLAYER].update(left_at=NOW, current_clan_tag=None)
        reconcile = PlayerActivityStore.reconcile_membership

        async def observed_reconcile(store, members):
            events.append(('reconcile',))
            return await reconcile(store, members)

        async def family(*args):
            events.append(('family',))
            return polling.RosterSweep({PLAYER: CLAN}, [CLAN], True)

        async def hour(store, members, *args, **kwargs):
            # The real membership write already ran, even on the failed-index hour.
            row = await store.get(PLAYER)
            assert row['left_at'] is None and row['current_clan_tag'] == CLAN
            events.append(('poll',))
            await store.record({'tag': PLAYER, 'attackWins': 2}, CLAN)
            await real_sleep(0)
            return {'success': 1, 'failure': 0}

        async def raids(*args):
            events.append(('raids',))

        async def backfill(*args):
            return None

        async def seed(*args):
            return {'pending': 0, 'retryable': 0}

        async def next_hour(delay):
            events.append(('hour_end',))
            if events.count(('hour_end',)) == 3:
                raise asyncio.CancelledError()
            await real_sleep(0)

        monkeypatch.setattr(polling, 'family_members', family)
        monkeypatch.setattr(PlayerActivityStore, 'reconcile_membership', observed_reconcile)
        monkeypatch.setattr(polling, 'capture_raids', raids)
        monkeypatch.setattr(polling, 'poll_hour', hour)
        monkeypatch.setattr(polling, 'seed_from_clashking', seed)
        monkeypatch.setattr(history, 'backfill_recent_wars', backfill)
        monkeypatch.setattr(polling.asyncio, 'sleep', next_hour)
        with pytest.raises(asyncio.CancelledError):
            await polling.run(mongo, SimpleNamespace(get_player=None))
        all_indexes = ['activity_family_clan', 'activity_departed_player_180d']
        failed_attempt = all_indexes[:all_indexes.index(failed_index) + 1]
        assert [options['name'] for _, options in collection.index_calls] == failed_attempt + all_indexes
        for stage in ('family', 'reconcile', 'poll', 'raids', 'hour_end'):
            assert events.count((stage,)) == 3
        first_sweep = [('index', name) for name in failed_attempt] + [
            ('family',), ('reconcile',), ('poll',), ('raids',), ('hour_end',),
        ]
        assert events[:len(first_sweep)] == first_sweep
        failures = [record for record in caplog.records if 'index unavailable' in record.message]
        assert len(failures) == 1
        assert failed_index in failures[0].message
        assert failures[0].exc_info[0] is type(error)
        assert str(error) in caplog.text
        assert 'family sweep unavailable' not in caplog.text
    asyncio.run(scenario())


def test_index_cancellation_propagates_before_sweep(monkeypatch, caplog):
    import pytest
    from utils import player_activity_polling as polling
    from tests.test_player_activity_retention_239n import IndexCollection

    async def scenario():
        class CancelledCollection(IndexCollection):
            async def create_index(self, *args, **kwargs):
                raise asyncio.CancelledError()

        async def family(*args):
            pytest.fail('Cancelled index bootstrap must not start a sweep')

        monkeypatch.setattr(polling, 'family_members', family)
        mongo = SimpleNamespace(player_activity=CancelledCollection())
        with pytest.raises(asyncio.CancelledError):
            await polling.run(mongo, SimpleNamespace(get_player=None))
        assert 'index unavailable' not in caplog.text
    asyncio.run(scenario())


def test_official_calls_share_a_one_per_second_budget():
    from utils.player_activity_polling import PacedOfficialClient
    async def scenario():
        tick = [0.0]
        calls = []
        async def sleep(delay):
            tick[0] += delay
        async def read(value, **kwargs):
            calls.append(tick[0])
            return value
        client = PacedOfficialClient(SimpleNamespace(get_clan=read, get_player=read, get_raid_log=read),
                                     sleep=sleep, clock=lambda: tick[0])
        await client.get_clan('#CLAN')
        await client.get_raid_log('#CLAN', limit=8)
        await client.get_player('#A')
        assert calls==[0,1,2]
    asyncio.run(scenario())


def test_family_read_isolates_failed_archived_removed_and_empty_answers(caplog):
    from utils.player_activity_polling import family_members, CompleteActivityClan
    import pytest
    async def scenario():
        from tests.test_strike_streaks import Cursor
        good,bad,empty,archived,removed='#PYY','#PQQ','#PRR','#PJJ','#PUU'
        rows=[{'tag':good},{'tag':bad},{'tag':empty},{'tag':archived,'archived':True},{'tag':removed,'removed_at':1}]
        mongo=SimpleNamespace(clans=SimpleNamespace(find=lambda *args:Cursor(rows)))
        called=[]
        async def clan(value):
            called.append(value)
            if value==bad: raise TimeoutError()
            return SimpleNamespace(tag=value,member_count=0 if value==empty else 1,
                                   members=[] if value==empty else [SimpleNamespace(tag='#PC9YGL0JL')])
        sweep=await family_members(mongo,SimpleNamespace(get_clan=clan))
        assert sweep.members=={'#PC9YGL0JL':good}
        assert sweep.clan_tags==[good,bad,empty] and not sweep.complete
        assert called==[good,bad,empty] and bad in caplog.text
        with pytest.raises(ValueError,match='member list'):
            CompleteActivityClan(data={'tag':good,'members':0},client=None)
        rows.clear()
        sweep=await family_members(mongo,SimpleNamespace(get_clan=clan))
        assert not sweep.complete and sweep.members=={}
    asyncio.run(scenario())


def test_incomplete_roster_never_marks_left_but_polls_healthy_and_reads_all_clans(monkeypatch):
    from utils import player_activity_polling as polling
    import pytest
    async def scenario():
        seen=[]
        class Store:
            def __init__(self,mongo): pass
            async def ensure_indexes(self): pass
            async def reconcile_membership(self,members): seen.append('left-write')
        async def family(*args): return polling.RosterSweep({'#PYY':'#PQQ'},['#PQQ','#PRR'],False)
        async def hour(store,members,*args,**kwargs):
            assert members=={'#PYY':'#PQQ'};seen.append('poll');return {'success':1,'failure':0}
        async def raids(store,client,tags):
            assert tags==['#PQQ','#PRR'];seen.append('raids');raise asyncio.CancelledError()
        monkeypatch.setattr(polling,'PlayerActivityStore',Store)
        monkeypatch.setattr(polling,'family_members',family)
        monkeypatch.setattr(polling,'poll_hour',hour)
        monkeypatch.setattr(polling,'capture_raids',raids)
        with pytest.raises(asyncio.CancelledError): await polling.run(None,SimpleNamespace(get_player=None))
        assert seen==['poll','raids']
    asyncio.run(scenario())


def test_failed_clan_members_are_polled_from_last_known_storage_owner():
    from utils.player_activity_polling import family_members
    from tests.test_player_activity_store import ActivityCollection, PLAYER, CLAN
    from utils.player_activity_store import PlayerActivityStore
    from types import SimpleNamespace as NS
    async def run():
        collection=ActivityCollection()
        store=PlayerActivityStore(NS(player_activity=collection))
        await store.record({'tag':PLAYER,'attackWins':1},CLAN)
        class Cursor:
            async def to_list(self,length=None):return [{'tag':CLAN}]
        mongo=NS(clans=NS(find=lambda *args:Cursor()),player_activity=collection)
        async def broken(*args,**kwargs):raise TimeoutError()
        sweep=await family_members(mongo,NS(get_clan=broken))
        assert sweep.members=={PLAYER:CLAN} and not sweep.complete
        seen=[]
        async def player(value):seen.append(value);return {'tag':value,'attackWins':2}
        await poll_hour(store,sweep.members,player,sleep=lambda _:__import__('asyncio').sleep(0),duration=0)
        assert seen==[PLAYER] and (await store.get(PLAYER))['last_seen_source']=='clash_api'
    asyncio.run(run())


def test_missing_and_empty_roster_responses_never_authorize_departures():
    from utils.player_activity_polling import family_members
    from types import SimpleNamespace as NS
    from tests.test_player_activity_store import ActivityCollection, CLAN, PLAYER
    async def run():
        class Cursor:
            async def to_list(self,length=None):return [{'tag':CLAN}]
        mongo=NS(clans=NS(find=lambda *args:Cursor()),player_activity=ActivityCollection())
        for count,players in ((1,[]),(2,[NS(tag=PLAYER)]),(0,[])):
            async def clan(*args,**kwargs):return NS(tag=CLAN,member_count=count,members=players)
            sweep=await family_members(mongo,NS(get_clan=clan))
            assert not sweep.complete and not sweep.members
    asyncio.run(run())


def test_history_starts_before_the_hourly_player_poll_and_is_cancelled(monkeypatch):
    from types import SimpleNamespace
    from utils import player_activity_polling as polling, player_activity_history as history
    async def scenario():
        started=asyncio.Event();cancelled=asyncio.Event()
        class Store:
            def __init__(self,mongo):pass
            async def ensure_indexes(self):pass
        async def family(*args):return polling.RosterSweep({},[],False)
        async def backfill(*args):
            started.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        async def poll(*args,**kwargs):
            await asyncio.sleep(0)
            assert started.is_set()
            raise asyncio.CancelledError
        monkeypatch.setattr(polling,'PlayerActivityStore',Store)
        monkeypatch.setattr(polling,'family_members',family)
        monkeypatch.setattr(polling,'poll_hour',poll)
        monkeypatch.setattr(history,'backfill_recent_wars',backfill)
        with __import__('pytest').raises(asyncio.CancelledError):
            await polling.run(None,SimpleNamespace(get_player=None))
        assert cancelled.is_set()
    asyncio.run(scenario())

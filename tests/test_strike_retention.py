import asyncio
from datetime import timedelta
from copy import deepcopy

from tests.test_strike_streaks import setup, PLAYER, GUILD, NOW
from utils.strike_retention import record_purge_after, snapshot_purge_after
from utils.strike_store import status_of


def test_purge_dates_and_persistent_streak_active_count_invariance():
    async def run():
        mongo, service = setup()
        profile = {'_id': f'{GUILD}:{PLAYER}', 'guild_id': GUILD, 'player_tag': PLAYER,
                   'streak_count': 4, 'streak_last_war_key': 'persisted',
                   'replacement_listed': True, 'replacement_priority': 'high',
                   'replacement_note': 'Keep this note', 'replacement_clan_tag': '#2UVGQU9',
                   'current_clan_tag': '#2UVGQU9', 'roster_seen_at': NOW}
        mongo.strike_profiles.rows[profile['_id']] = deepcopy(profile)
        for key, age in [('old', 100), ('expired', 70), ('active', 1)]:
            occurred = NOW - timedelta(days=age)
            row = {'_id': key, 'guild_id': GUILD, 'player_tag': PLAYER, 'kind': 'strike',
                   'occurred_at': occurred, 'expires_at': occurred + timedelta(days=60)}
            row['purge_after'] = record_purge_after(row)
            mongo.strike_records.rows[key] = row
        def active():
            return sum(status_of(row, NOW)=='active' for row in mongo.strike_records.rows.values())
        before = (await service.streak(GUILD, PLAYER), active(), deepcopy(profile),
                  {key:row['expires_at'] for key,row in mongo.strike_records.rows.items() if status_of(row,NOW)=='active'},
                  await service.replacement(GUILD))
        for key, row in list(mongo.strike_records.rows.items()):
            if row['purge_after'] <= NOW:
                del mongo.strike_records.rows[key]
        after = (await service.streak(GUILD, PLAYER), active(), mongo.strike_profiles.rows[profile['_id']],
                 {key:row['expires_at'] for key,row in mongo.strike_records.rows.items() if status_of(row,NOW)=='active'},
                 await service.replacement(GUILD))
        assert before == after
        assert set(mongo.strike_records.rows) == {'expired', 'active'}
        assert snapshot_purge_after({'end_time': NOW, 'status': 'finalized'}) == NOW + timedelta(days=30)
        assert record_purge_after({'occurred_at': NOW}) == NOW + timedelta(days=90)
    asyncio.run(run())


def test_legacy_extended_active_expiry_blocks_retention():
    import pytest
    from utils.strike_retention import validate_record_retention
    with pytest.raises(ValueError, match='expiry exceeds retention'):
        validate_record_retention({'kind': 'strike', 'occurred_at': NOW,
                                   'expires_at': NOW+timedelta(days=120)})


def test_manual_regular_cwl_and_snapshot_writers_use_policy_dates():
    from tests.test_strike_streaks import war, CLAN, Collection
    from utils.strike_tracking import StrikeTracking
    from types import SimpleNamespace
    async def run():
        mongo, service=setup()
        manual=await service.add_manual(GUILD,PLAYER,'Fixture reason',123)
        assert manual['purge_after']==manual['occurred_at']+timedelta(days=90)
        regular=war(1,attacks=0)
        await service.process_war(GUILD,regular)
        rows=list(mongo.strike_records.rows.values())
        assert next(row for row in rows if row['source']=='war')['purge_after']==regular['end_time']+timedelta(days=90)
        cwl={**war(2,attacks=0),'type':'cwl','attacks_per_member':1,'war_tag':'#PYY'}
        await service.process_cwl_war(GUILD,cwl)
        assert next(row for row in mongo.strike_records.rows.values() if row['source']=='cwl')['purge_after']==cwl['end_time']+timedelta(days=90)
        tracking=StrikeTracking(SimpleNamespace(strike_war_snapshots=Collection()))
        pending=await tracking.observe(GUILD,regular)
        assert 'purge_after' not in pending
        await tracking.finalized(GUILD,regular)
        assert (await tracking.snapshot(GUILD,regular))['purge_after']==regular['end_time']+timedelta(days=30)
        await tracking.observe(GUILD,cwl)
        await tracking.incomplete(GUILD,cwl,'Incomplete fixture')
        assert (await tracking.snapshot(GUILD,cwl))['purge_after'] >= cwl['end_time']+timedelta(days=60)
    asyncio.run(run())


def test_both_ingest_guards_reject_outside_retention():
    import pytest
    from tests.test_strike_streaks import war
    async def run():
        mongo, service=setup()
        old={**war(1),'end_time':NOW-timedelta(days=100)}
        with pytest.raises(ValueError,match='retention'):
            await service.process_war(GUILD,old)
        old.update(type='cwl',attacks_per_member=1,war_tag='#PYY',members=[{'tag':PLAYER,'attacks':0}])
        with pytest.raises(ValueError,match='retention'):
            await service.process_cwl_war(GUILD,old)
        assert not mongo.strike_records.rows
    asyncio.run(run())


def test_old_unresolved_final_is_quarantined_and_next_war_still_processes():
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from extensions.commands.strikes import _finish_official_war
    from tests.test_strike_streaks import war
    async def run():
        tracking=SimpleNamespace(snapshot=AsyncMock(return_value={'seen_active':True}),
            observe=AsyncMock(return_value={'seen_active':True,'status':'observing'}),
            quarantine_old=AsyncMock(),finalized=AsyncMock())
        ledger=SimpleNamespace(process_war=AsyncMock(return_value={'deferred_count':0}))
        old={**war(1),'end_time':NOW-timedelta(days=100)}
        assert await _finish_official_war(tracking,ledger,GUILD,old)==(0,0,0,1)
        tracking.quarantine_old.assert_awaited_once()
        ledger.process_war.assert_not_awaited()
        assert await _finish_official_war(tracking,ledger,GUILD,war(2))==(1,0,0,0)
        ledger.process_war.assert_awaited_once()
    asyncio.run(run())


def test_review_hold_overrides_every_terminal_purge_policy():
    from utils.strike_retention import snapshot_purge_after
    for status in ('incomplete','finalized','abandoned','resolved'):
        assert snapshot_purge_after({'end_time':NOW,'resolved_at':NOW,'status':status,'manual_review_required':True}) is None

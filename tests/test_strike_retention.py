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
                   'replacement_note': 'Keep this note'}
        mongo.strike_profiles.rows[profile['_id']] = deepcopy(profile)
        for key, age in [('old', 100), ('expired', 70), ('active', 1)]:
            occurred = NOW - timedelta(days=age)
            row = {'_id': key, 'guild_id': GUILD, 'player_tag': PLAYER, 'kind': 'strike',
                   'occurred_at': occurred, 'expires_at': occurred + timedelta(days=60)}
            row['purge_after'] = record_purge_after(row)
            mongo.strike_records.rows[key] = row
        def active():
            return sum(status_of(row, NOW)=='active' for row in mongo.strike_records.rows.values())
        before = (await service.streak(GUILD, PLAYER), active(), deepcopy(profile))
        for key, row in list(mongo.strike_records.rows.items()):
            if row['purge_after'] <= NOW:
                del mongo.strike_records.rows[key]
        after = (await service.streak(GUILD, PLAYER), active(), mongo.strike_profiles.rows[profile['_id']])
        assert before == after
        assert set(mongo.strike_records.rows) == {'expired', 'active'}
        assert snapshot_purge_after({'end_time': NOW}) == NOW + timedelta(days=30)
        assert record_purge_after({'occurred_at': NOW}) == NOW + timedelta(days=90)
    asyncio.run(run())

"""Mismatch receipt integration preserves streak and history semantics."""
import asyncio
from copy import deepcopy
from cwl_web.strikes import entry
from utils.strike_store import status_of
from tests.test_strike_streaks import capture, GUILD
from tests.test_fwa_war_plan_receipts import fixture, record


def test_mismatch_record_is_streak_neutral_and_exposes_reason():
    async def run():
        db, service, store = fixture()
        await capture(db, service, 0)
        before = deepcopy(db.strike_profiles.rows)
        war = await capture(db, service, 1, attacks=0, apply=False)
        await record(store, war)
        rows = await service._war_rows(GUILD, war)
        result = await service.process_war(GUILD, war, official_capture=True)
        assert result['strikes'] == 0 and result['applied'] == 1
        assert db.strike_profiles.rows == before
        saved = db.strike_records.rows[rows[0]['_id']]
        assert not saved.get('streak_eligible')
        assert status_of(saved) == 'mismatch'
        adapted = entry(saved, {})
        assert adapted['kind'] == 'mismatch'
        assert adapted['war_plan_reason'] == 'Confirmed war plan used'
        assert (await capture(db, service, 2))['deferred_count'] == 0
    asyncio.run(run())

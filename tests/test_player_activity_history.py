"""Historical activity is an isolated player-document write, never a strike import."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.test_strike_streaks import setup, war, NOW, PLAYER, CLAN, Collection
from tests.test_player_activity_store import ActivityCollection
from utils.player_activity_store import PlayerActivityStore
from utils.player_activity_history import backfill_recent_wars, recent_wars


def test_full_history_backfill_is_bounded_and_cannot_change_strikes_or_streaks():
    async def run():
        db, _ = setup()
        db.player_activity = ActivityCollection()
        db.fwa_war_plans = Collection()
        db.clans.rows['clan']['type'] = 'War'
        await db.strike_records.insert_one({'_id':'protected','kind':'strike'})
        await db.strike_profiles.insert_one({'_id':'protected','player_tag':PLAYER,'streak_count':4,'replacement_listed':True})
        protected = deepcopy((db.strike_records.rows,db.strike_profiles.rows))
        store=PlayerActivityStore(db)
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        before=await store.get(PLAYER)
        fetch=AsyncMock(return_value={'wars':[war(n,n%3) for n in range(20)]})
        result=await backfill_recent_wars(db,fetch=fetch,now=NOW)
        row=await store.get(PLAYER)
        assert result['players']==1 and len(row['recent_wars'])==14
        assert row['recent_wars'][0]['war_key']!=row['recent_wars'][-1]['war_key']
        assert row['updated_at']==before['updated_at'] and row.get('last_seen_at')==before.get('last_seen_at')
        assert (db.strike_records.rows,db.strike_profiles.rows)==protected
        await backfill_recent_wars(db,fetch=fetch,now=NOW)
        fetch.assert_awaited_once_with(CLAN,days=60)
        assert len(db.player_activity.rows)==1
    asyncio.run(run())


def test_partial_history_and_neutral_plan_never_invent_misses_or_receipt():
    async def run():
        db,_=setup();db.player_activity=ActivityCollection();db.fwa_war_plans=Collection()
        store=PlayerActivityStore(db)
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        fetch=AsyncMock(side_effect=RuntimeError('fixture outage'))
        await backfill_recent_wars(db,fetch=fetch,now=NOW)
        row=await store.get(PLAYER)
        assert not row['recent_wars'] and row.get('recent_wars_version') is None
        fetch.side_effect=None;fetch.return_value={'wars':[war(1,0)]}
        with patch('utils.player_activity_history.WarPlanStore.outcome',AsyncMock(return_value=('mismatch','fixture'))):
            await backfill_recent_wars(db,fetch=fetch,now=NOW)
        assert not (await store.get(PLAYER))['recent_wars']
    asyncio.run(run())


def test_recent_wars_merge_deduplicates_and_partial_lineup_is_not_accepted():
    sample={'war_key':'same','occurred_at':NOW,'attacks_used':0,'attacks_available':2}
    assert recent_wars([sample],[{**sample,'attacks_used':2}])[0]['attacks_used']==2
    import pytest
    with pytest.raises(ValueError):recent_wars([],[{**sample,'attacks_used':None}])


def test_history_storage_cas_retries_preserve_concurrent_official_fields():
    async def run():
        class Racing(ActivityCollection):
            race=True
            async def update_one(self,q,u,upsert=False):
                if self.race and 'recent_wars' in u.get('$set',{}):
                    self.race=False;self.rows[PLAYER]['revision']+=1;self.rows[PLAYER]['last_seen_source']='clash_api'
                    return SimpleNamespace(matched_count=0)
                return await super().update_one(q,u,upsert)
        collection=Racing();store=PlayerActivityStore(SimpleNamespace(player_activity=collection))
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        await store.save_recent_wars(PLAYER,[{'war_key':'w','occurred_at':NOW,'attacks_used':2,'attacks_available':2}],complete=True,version=1,now=NOW)
        row=await store.get(PLAYER)
        assert row['last_seen_source']=='clash_api' and len(row['recent_wars'])==1
    asyncio.run(run())

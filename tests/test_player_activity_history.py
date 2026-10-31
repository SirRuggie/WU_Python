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
        db.clans.rows["clan"]["type"] = "War"
        await db.strike_records.insert_one({"_id": "protected", "kind": "strike"})
        await db.strike_profiles.insert_one(
            {
                "_id": "protected",
                "player_tag": PLAYER,
                "streak_count": 4,
                "replacement_listed": True,
            }
        )
        protected = deepcopy((db.strike_records.rows, db.strike_profiles.rows))
        store = PlayerActivityStore(db)
        await store.record({"tag": PLAYER, "attackWins": 1}, CLAN, now=NOW)
        before = await store.get(PLAYER)
        fetch = AsyncMock(return_value={"wars": [war(n, n % 3) for n in range(20)]})
        result = await backfill_recent_wars(
            db, fetch=fetch, now=NOW + timedelta(hours=5)
        )
        row = await store.get(PLAYER)
        assert result["players"] == 1 and len(row["recent_wars"]) == 14
        assert row["recent_wars"][0]["war_key"] != row["recent_wars"][-1]["war_key"]
        assert row["updated_at"] == before["updated_at"] and row.get(
            "last_seen_at"
        ) == before.get("last_seen_at")
        assert (db.strike_records.rows, db.strike_profiles.rows) == protected
        await backfill_recent_wars(db, fetch=fetch, now=NOW + timedelta(hours=5))
        fetch.assert_awaited_once_with(CLAN, days=60)
        assert len(await store.all_players()) == 1
        assert len(await store.history_clans()) == 1

    asyncio.run(run())


def test_partial_history_and_neutral_plan_never_invent_misses_or_receipt():
    async def run():
        db, _ = setup()
        db.player_activity = ActivityCollection()
        db.fwa_war_plans = Collection()
        store = PlayerActivityStore(db)
        await store.record({"tag": PLAYER, "attackWins": 1}, CLAN, now=NOW)
        fetch = AsyncMock(side_effect=RuntimeError("fixture outage"))
        await backfill_recent_wars(db, fetch=fetch, now=NOW)
        row = await store.get(PLAYER)
        assert row["recent_wars"][0]["unusable"]
        assert "recent_wars_complete" not in row
        fetch.side_effect = None
        fetch.return_value = {"wars": [war(1, 0)]}
        with patch(
            "utils.player_activity_history.WarPlanStore.outcome",
            AsyncMock(return_value=("mismatch", "fixture")),
        ):
            await backfill_recent_wars(db, fetch=fetch, now=NOW + timedelta(minutes=6))
        assert all(item["neutral"] for item in (await store.get(PLAYER))["recent_wars"])

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
        await store.save_recent_wars(PLAYER,[{'war_key':'w','occurred_at':NOW,'attacks_used':2,'attacks_available':2}],version=1,now=NOW)
        row=await store.get(PLAYER)
        assert row['last_seen_source']=='clash_api' and len(row['recent_wars'])==1
    asyncio.run(run())


def test_total_history_budget_cancels_upstream_without_completion_receipt(monkeypatch):
    from utils import player_activity_history as history
    import pytest
    async def run():
        db,_=setup();db.player_activity=ActivityCollection();db.fwa_war_plans=Collection()
        db.clans.rows['clan']['type']='War'
        store=PlayerActivityStore(db)
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        async def fetch(*args,**kwargs):await asyncio.Event().wait()
        monkeypatch.setattr(history,'HISTORY_TIMEOUT_SECONDS',.01)
        with pytest.raises(TimeoutError):await history.backfill_recent_wars(db,fetch=fetch,now=NOW)
        row=await store.get(PLAYER)
        assert row.get('recent_wars_version') is None and not row.get('recent_wars')
        assert not db.strike_records.rows and not db.strike_profiles.rows
    asyncio.run(run())


def test_one_clan_failure_does_not_exhaust_players_or_refetch_healthy_clans():
    from utils.player_activity_signals import activity_signals

    async def run():
        db, _ = setup()
        db.player_activity = ActivityCollection()
        db.fwa_war_plans = Collection()
        db.clans.rows["clan"]["type"] = "War"
        other = "#PYY"
        await db.clans.insert_one({"_id": "other", "tag": other, "type": "War"})
        store = PlayerActivityStore(db)
        await store.record({"tag": PLAYER, "attackWins": 1}, CLAN, now=NOW)
        await store.record({'tag':'#PQL','attackWins':1}, other, now=NOW)
        calls = []
        recovered = False

        async def fetch(clan, days):
            calls.append(clan)
            if clan == other and not recovered:
                raise RuntimeError("one clan outage")
            days_list = (1, 3, 5) if clan == CLAN else (2, 4)
            return {
                "wars": [
                    {
                        **war(n, 0 if clan == CLAN else 2),
                        "clan_tag": clan,
                        "end_time": NOW - timedelta(days=n),
                    }
                    for n in days_list
                ]
            }

        for hour in (0, 1, 2):
            await backfill_recent_wars(db, fetch=fetch, now=NOW + timedelta(hours=hour))
        row = await store.get(PLAYER)
        assert "recent_wars_complete" not in row and "recent_wars_attempts" not in row
        signals = activity_signals(row, [], now=NOW + timedelta(hours=2))
        assert (
            signals["missed_attacks"] == 6
            and signals["no_attack_wars"] == 3
        )
        affected = await store.get('#PQL')
        assert activity_signals(affected, [], now=NOW)['no_attack_wars'] == 0
        assert any(w.get('unusable') for w in affected['recent_wars'])
        assert not any(w.get('unusable') for w in row['recent_wars'])
        assert calls.count(CLAN) == 1 and calls.count(other) == 3
        report = await store.history_report()
        assert report == [other]
        recovered = True
        await backfill_recent_wars(db, fetch=fetch, now=NOW + timedelta(hours=9))
        row = await store.get(PLAYER)
        assert (
            calls.count(CLAN) == 1
            and calls.count(other) == 4
        )
        assert (
            activity_signals(row, [], now=NOW + timedelta(hours=9))["no_attack_wars"]
            == 1
        )
        # New account uses the complete cached lineups; only its own clan may
        # need refreshing when its tracking start is newer than that cache.
        await store.record({"tag": "#PQQ", "attackWins": 1}, CLAN, now=NOW)
        await backfill_recent_wars(db, fetch=fetch, now=NOW + timedelta(hours=9))
        assert calls.count(CLAN) == 1 and calls.count(other) == 4
        await store.record({"tag": "#PQR", "attackWins": 1}, CLAN,
                           now=NOW + timedelta(hours=10))
        await backfill_recent_wars(db, fetch=fetch, now=NOW + timedelta(hours=10))
        assert calls.count(CLAN) == 2 and calls.count(other) == 4

    asyncio.run(run())


def test_restart_does_not_charge_clan_failure_and_can_resume(monkeypatch):
    from utils import player_activity_history as history
    import pytest

    async def run():
        db, _ = setup()
        db.player_activity = ActivityCollection()
        db.fwa_war_plans = Collection()
        db.clans.rows["clan"]["type"] = "War"
        store = PlayerActivityStore(db)
        await store.record({"tag": PLAYER, "attackWins": 1}, CLAN, now=NOW)

        async def cancel(*args, **kwargs):
            raise asyncio.CancelledError

        for _ in range(3):
            with pytest.raises(asyncio.CancelledError):
                await backfill_recent_wars(db, fetch=cancel, now=NOW)
        assert not await store.history_clans()
        await backfill_recent_wars(
            db, fetch=AsyncMock(return_value={"wars": [war(1, 2)]}), now=NOW
        )
        assert not (await store.get(PLAYER))["recent_wars"][0].get("unusable")

    asyncio.run(run())


def test_exempt_observation_cannot_return_after_ledger_purge():
    from utils.constants import WARRIORS_UNITED_GUILD_ID
    from utils.strike_store import war_key
    from utils.player_activity_signals import activity_signals

    async def run():
        db, _ = setup()
        db.player_activity = ActivityCollection()
        db.fwa_war_plans = Collection()
        db.clans.rows["clan"]["type"] = "War"
        store = PlayerActivityStore(db)
        await store.record({"tag": PLAYER, "attackWins": 1}, CLAN, now=NOW)
        sample = war(1, 0)
        await db.strike_records.insert_one(
            {
                "_id": "exempt",
                "guild_id": WARRIORS_UNITED_GUILD_ID,
                "player_tag": PLAYER,
                "source": "war",
                "kind": "exempt",
                "war_key": war_key(sample),
            }
        )
        fetch = AsyncMock(return_value={"wars": [sample]})
        await backfill_recent_wars(db, fetch=fetch, now=NOW)
        assert (await store.get(PLAYER))["recent_wars"][0]["neutral"]
        db.strike_records.rows.clear()
        await backfill_recent_wars(db, fetch=fetch, now=NOW + timedelta(days=1))
        row = await store.get(PLAYER)
        assert row["recent_wars"][0]["neutral"]
        assert (
            activity_signals(row, [], now=NOW + timedelta(days=1))["missed_attacks"]
            == 0
        )

    asyncio.run(run())


def test_daily_refresh_heals_gap_and_local_unusable_war_stops_chain():
    from utils.player_activity_signals import activity_signals
    async def run():
        db,_=setup();db.player_activity=ActivityCollection();db.fwa_war_plans=Collection()
        db.clans.rows['clan']['type']='War'
        store=PlayerActivityStore(db)
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        known = [{**war(n,0), "end_time": NOW-timedelta(days=n)} for n in (1,3,5)]
        fetch=AsyncMock(return_value={'wars':known,
             'skipped':[{'end_time':(NOW-timedelta(days=2)).isoformat(),'reason':'malformed lineup'}]})
        await backfill_recent_wars(db,fetch=fetch,now=NOW)
        result=activity_signals(await store.get(PLAYER),[],now=NOW)
        assert result['no_attack_wars']==1 and result['missed_attacks']==6
        fetch.return_value={'wars':known+[{**war(2,2), 'end_time': NOW-timedelta(days=2)}]}
        await backfill_recent_wars(db,fetch=fetch,now=NOW+timedelta(days=1))
        assert fetch.await_count==2
        row=await store.get(PLAYER)
        assert not any(w.get('unusable') for w in row['recent_wars'])
        assert activity_signals(row,[],now=NOW+timedelta(days=1))['no_attack_wars']==1
        revision=row['revision']
        await backfill_recent_wars(db,fetch=fetch,now=NOW+timedelta(days=1,hours=1))
        assert fetch.await_count==2 and (await store.get(PLAYER))['revision']==revision
    asyncio.run(run())


def test_fwa_no_plan_counts_and_non_regular_wars_are_ignored():
    from utils.player_activity_signals import activity_signals
    async def run():
        for outcome, expected in ((None,2),('win',2),('mismatch',0)):
            db,_=setup();db.player_activity=ActivityCollection();db.fwa_war_plans=Collection()
            store=PlayerActivityStore(db)
            await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
            fetch=AsyncMock(return_value={'wars':[war(1,0),{**war(2,0),'type':'friendly'},
                     {**war(3,0),'type':'cwl'}], 'skipped':[
                     {'reason':'not a regular war','ignored':True,'end_time':NOW.isoformat()}]})
            with patch('utils.player_activity_history.WarPlanStore.outcome',AsyncMock(return_value=(outcome,None))):
                await backfill_recent_wars(db,fetch=fetch,now=NOW)
            row=await store.get(PLAYER)
            assert len(row['recent_wars'])==1 and not await store.history_report()
            assert activity_signals(row,[],now=NOW)['missed_attacks']==expected
    asyncio.run(run())


def test_successful_clan_cache_refreshes_next_day_after_tracker_gap():
    from utils.player_activity_signals import activity_signals
    async def run():
        db,_=setup();db.player_activity=ActivityCollection();db.fwa_war_plans=Collection()
        db.clans.rows['clan']['type']='War'
        store=PlayerActivityStore(db)
        await store.record({'tag':PLAYER,'attackWins':1},CLAN,now=NOW)
        old={**war(1,0),'end_time':NOW-timedelta(days=1)}
        fetch=AsyncMock(return_value={'wars':[old]})
        await backfill_recent_wars(db,fetch=fetch,now=NOW)
        fetch.return_value={'wars':[old,{**war(2,2),'end_time':NOW+timedelta(hours=1)}]}
        await backfill_recent_wars(db,fetch=fetch,now=NOW+timedelta(hours=2))
        assert fetch.await_count==1
        await backfill_recent_wars(db,fetch=fetch,now=NOW+timedelta(days=1))
        assert fetch.await_count==2
        signals=activity_signals(await store.get(PLAYER),[],now=NOW+timedelta(days=1))
        assert signals['observed_wars']==2 and signals['no_attack_wars']==0
    asyncio.run(run())

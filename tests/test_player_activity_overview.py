import pytest
import gzip
import json
from datetime import timedelta
from tests.test_player_activity_signals import NOW
from utils.player_activity_overview import family_activity_rows
from cwl_web.strikes import public


@pytest.fixture(autouse=True)
def no_external_link_reads(monkeypatch):
    from unittest.mock import AsyncMock
    from utils import recruit_links

    monkeypatch.setattr(
        recruit_links,
        "resolve_players",
        AsyncMock(return_value=recruit_links.PlayerOwners()),
    )
    monkeypatch.setattr(
        "utils.player_activity_store.PlayerActivityStore.history_report",
        AsyncMock(
            return_value=[]
        ),
    )


def test_family_with_zero_strikes_and_departed_accounts_is_visible():
    activity=[{'tag':'#PYY','name':'Healthy','current_clan_tag':'#CLAN','last_seen_at':NOW},
              {'tag':'#PQQ','name':'Left','current_clan_tag':None,'left_at':NOW}]
    profiles=[{'player_tag':'#PQQ','current_clan_tag':'#CLAN','departed_clan_tag':'#CLAN'}]
    rows=family_activity_rows(activity,profiles,[],[{'tag':'#CLAN','name':'Family'}],now=NOW)
    assert len(rows)==2
    left=next(row for row in rows if row['player_tag']=='#PQQ')
    assert left['left_clan'] and left['current_clan_tag'] is None
    assert next(row for row in rows if row['player_tag']=='#PYY')['active_strikes']==0


def test_counts_marks_and_payload_budget_for_1000_rows():
    activity=[{'tag':f'#P{n:04}','name':f'Fixture player {n}','current_clan_tag':'#CLAN',
               'last_seen_at':NOW-timedelta(days=n%20)} for n in range(1000)]
    profiles=[{'player_tag':row['tag'],'current_clan_tag':'#CLAN','town_hall':16,'weight':149000}
              for row in activity]
    records=[{'player_tag':activity[0]['tag'],'source':'manual','kind':'strike',
              'occurred_at':NOW,'expires_at':NOW+timedelta(days=60)} for _ in range(3)]
    rows=family_activity_rows(activity,profiles,records,[{'tag':'#CLAN','name':'Family'}],now=NOW)
    assert rows[0]['marked_for_replacement'] and rows[0]['status']=='risk'
    payload=json.dumps(public({'accounts':rows})).encode()
    assert len(gzip.compress(payload))<300000


def test_activity_read_keeps_the_existing_authorization_gate():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch
    import pytest
    from aiohttp import web
    from cwl_web import strikes
    async def run():
        deny=AsyncMock(side_effect=web.HTTPForbidden())
        handler=AsyncMock()
        with patch.object(strikes.shared,'require_manage',deny), patch.object(strikes,'activity_accounts',handler):
            with pytest.raises(web.HTTPForbidden):
                await strikes.accounts(SimpleNamespace(method='GET',query={'activity':'true'}))
            handler.assert_not_called()
            assert deny.call_args.args[1]=='strikes_read'
    asyncio.run(run())


def test_route_uses_public_weight_owner_and_preserves_rows_on_upstream_failure():
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch
    from cwl_web import strikes
    from cwl_web.providers import ProviderUnavailable
    from utils import clan_weights
    async def run():
        @asynccontextmanager
        async def mongo(request):
            yield SimpleNamespace(player_activity=SimpleNamespace())
        ledger = SimpleNamespace(activity_context=AsyncMock(return_value={
            'profiles': [], 'records': [], 'clans':[{'tag':'#CLAN','name':'Family'}]}))
        request = SimpleNamespace(app={'store':object(),'providers':object()})
        activity=[{'tag':'#PYY','name':'Healthy','current_clan_tag':'#CLAN','last_seen_at':NOW}]
        weights = AsyncMock(return_value={'#PYY':{'weight':149000}})
        saved_blank = [False]
        def overlay(store, payload):
            return {'accounts': [{**row, 'war_weight': None} for row in payload['accounts']]} if saved_blank[0] else payload
        with patch.object(strikes.shared,'mongo',mongo), patch.object(strikes,'service',AsyncMock(return_value=ledger)), \
             patch('utils.player_activity_store.PlayerActivityStore.overview',AsyncMock(return_value=activity)), \
             patch.object(clan_weights,'source_weights',weights), \
             patch.object(clan_weights,'overlay_accounts',overlay):
            result=json.loads((await strikes.activity_accounts(request)).body)
            assert result['accounts'][0]['weight']==149000
            assert not result['weight_warning']
            assert weights.call_args.args[2]==['#PYY']
            ledger.activity_context.return_value['profiles']=[{'player_tag':'#PYY','current_clan_tag':'#CLAN','weight':149000}]
            saved_blank[0]=True
            weights.side_effect=ProviderUnavailable('fixture outage')
            result=json.loads((await strikes.activity_accounts(request)).body)
            assert len(result['accounts'])==1 and result['weight_warning']
            assert result['accounts'][0]['weight'] is None
            weights.side_effect=None
            weights.return_value=[]
            result=json.loads((await strikes.activity_accounts(request)).body)
            assert result['weight_warning'] and result['accounts'][0]['weight'] is None
    asyncio.run(run())


def test_replacement_filter_uses_owner_eligibility_and_departure_grace():
    activity=[{'tag':'#PYY','current_clan_tag':None,'left_at':NOW}]
    profile={'player_tag':'#PYY','departed_clan_tag':'#CLAN','replacement_listed':True,
             'replacement_clan_tag':'#CLAN','replacement_priority':'high'}
    clans=[{'tag':'#CLAN','name':'Family'}]
    expired=family_activity_rows(activity,[profile],[],clans,replacements=[],now=NOW)[0]
    assert not expired['marked_for_replacement'] and expired['priority'] is None
    eligible={**profile,'replacement_listed':True,'active_strikes':0}
    grace=family_activity_rows(activity,[profile],[],clans,replacements=[eligible],now=NOW)[0]
    assert grace['marked_for_replacement'] and grace['priority']=='high'
    assert grace['left_clan'] and grace['departed_at']==NOW


def test_context_keeps_all_family_members_without_writes_and_reuses_eligibility():
    import asyncio
    from tests.test_strike_streaks import setup, PLAYER, CLAN, GUILD
    from unittest.mock import AsyncMock
    async def run():
        db, ledger=setup()
        db.clans.rows.clear()
        await db.clans.insert_one({'_id':'family','tag':CLAN,'name':'Family'})
        await db.clans.insert_one({'_id':'archived','tag':'#PYY','name':'Archived','archived':True})
        await db.strike_profiles.insert_one({'_id':'profile','player_tag':PLAYER,'guild_id':GUILD,'current_clan_tag':CLAN})
        ledger.replacement=AsyncMock(return_value=[{'player_tag':PLAYER}])
        context=await ledger.activity_context(GUILD,[PLAYER])
        assert [row['tag'] for row in context['clans']]==[CLAN]
        assert len(context['profiles'])==1 and context['replacements']==[{'player_tag':PLAYER}]
        ledger.replacement.assert_awaited_once_with(GUILD,limit=None)
        assert len(db.strike_profiles.rows)==1 and not db.strike_records.rows
    asyncio.run(run())


def test_activity_overview_projects_out_the_large_unit_baseline():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock, AsyncMock
    from utils.player_activity_store import PlayerActivityStore

    collection = SimpleNamespace(
        find=Mock(return_value=SimpleNamespace(to_list=AsyncMock(return_value=[])))
    )
    asyncio.run(
        PlayerActivityStore(SimpleNamespace(player_activity=collection)).overview()
    )
    query, fields = collection.find.call_args.args
    assert (
        query == {"kind": {"$ne": "history_clan"}}
        and fields["baseline.townHallLevel"] == 1
    )
    assert "baseline" not in fields and "active_days" not in fields
    assert fields["raid_weekends"] == 1 and fields["last_seen_at"] == 1


def test_activity_outage_preserves_strike_rows_and_directory_names_without_profile_name():
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch
    from pymongo.errors import PyMongoError
    from cwl_web import strikes, manage_roles
    from utils import clan_weights
    async def run():
        @asynccontextmanager
        async def mongo(request):
            yield SimpleNamespace(player_activity=SimpleNamespace())
        profile={'player_tag':'#PYY','current_clan_tag':'#CLAN'}
        from utils import recruit_links
        recruit_links.resolve_players.return_value=recruit_links.PlayerOwners(owners={'#PYY':'123456789012345678'})
        ledger=SimpleNamespace(activity_context=AsyncMock(return_value={'profiles':[profile], 'records':[],
            'clans':[{'tag':'#CLAN','name':'Family'}]}))
        request=SimpleNamespace(app={'store':object(),'providers':object()})
        directory=AsyncMock(return_value=[{'nick':'Real display name','user':{'id':'123456789012345678','username':'fixture'}}])
        with patch.object(strikes.shared,'mongo',mongo), patch.object(strikes,'service',AsyncMock(return_value=ledger)), \
             patch('utils.player_activity_store.PlayerActivityStore.overview',AsyncMock(side_effect=PyMongoError('isolated outage'))), \
             patch.object(manage_roles,'searchable_members',directory), \
             patch.object(clan_weights,'source_weights',AsyncMock(return_value={})), \
             patch.object(clan_weights,'overlay_accounts',lambda store,payload:payload):
            result=json.loads((await strikes.activity_accounts(request)).body)
            assert len(result['accounts'])==1 and result['activity_warning'].startswith('Activity unavailable')
            row=result['accounts'][0]
            assert row['activity_unavailable'] and row['quiet_days'] is None and not row['observed_attacks']
            assert row['discord_name'] is None and not result['identity_warning'] and result['identity_updating']
            await request.app['activity_identity_cache']['task']
            result=json.loads((await strikes.activity_accounts(request)).body)
            assert result['accounts'][0]['discord_name']=='Real display name' and not result['identity_warning']
            directory.assert_awaited_once()
    asyncio.run(run())


def test_action_filters_use_configured_limit_and_only_new_active_strikes():
    activity=[{'tag':'#PYY','current_clan_tag':'#CLAN','updated_at':NOW}]
    def record(days,expires,revoked=False):
        row={'player_tag':'#PYY','kind':'strike','source':'manual','occurred_at':NOW-timedelta(days=days),'expires_at':NOW+timedelta(days=expires)}
        if revoked:row['revoked_at']=NOW
        return row
    records=[record(8,30),record(9,30),record(1,-1),record(1,30,True)]
    row=family_activity_rows(activity,[],records,[{'tag':'#CLAN'}],strike_limit=2,now=NOW)[0]
    assert row['over_limit'] and not row['new_this_week'] and row['active_strikes']==2
    row=family_activity_rows(activity,[],records+[record(1,30)],[{'tag':'#CLAN'}],strike_limit=5,now=NOW)[0]
    assert not row['over_limit'] and row['new_this_week']


def test_production_profile_without_member_id_gets_cached_bulk_link_identity(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cwl_web.strike_activity_identity import account_identities
    from cwl_web import manage_roles
    from utils import recruit_links
    async def run():
        request=SimpleNamespace(app={})
        recruit_links.resolve_players.return_value=recruit_links.PlayerOwners(owners={'#PYY':'123456789012345678'})
        monkeypatch.setattr(manage_roles, 'searchable_members', AsyncMock(return_value=[
            {'nick':'Display','user':{'id':'123456789012345678'}}]))
        first, empty=await account_identities(request,['#PYY'])
        assert first == {} and not empty
        await request.app['activity_identity_cache']['task']
        cached, empty=await account_identities(request,['#PYY'])
        assert cached['#PYY']=={'discord_id':'123456789012345678','discord_name':'Display'} and not empty
        recruit_links.resolve_players.assert_awaited_once_with(['#PYY'])
    asyncio.run(run())


def test_page_freshness_and_left_members_never_invent_quiet_risk():
    for left in (False, True):
        activity = [
            {
                "tag": "#PYY",
                "current_clan_tag": "#CLAN" if not left else None,
                "left_at": NOW if left else None,
                "last_seen_at": NOW - timedelta(days=40),
                "updated_at": NOW if left else NOW - timedelta(hours=37),
            }
        ]
        profiles = (
            [{"player_tag": "#PYY", "departed_clan_tag": "#CLAN"}] if left else []
        )
        row = family_activity_rows(activity, profiles, [], [{"tag": "#CLAN"}], now=NOW)[
            0
        ]
        assert row["quiet_days"] is None and row["status"] == "active"
        assert row["left_clan"] is left


def test_page_does_not_wait_for_names_and_failure_refresh_is_cached(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from contextlib import asynccontextmanager
    from cwl_web import strikes
    from utils import clan_weights, recruit_links
    async def run():
        blocked=asyncio.Event()
        async def slow(*args):
            await blocked.wait()
            raise RuntimeError('name provider offline')
        recruit_links.resolve_players.side_effect=slow
        request=SimpleNamespace(app={'store':object(),'providers':object()})
        ledger=SimpleNamespace(activity_context=AsyncMock(return_value={
            'profiles':[{'player_tag':'#PYY','current_clan_tag':'#CLAN'}],
            'records':[], 'clans':[{'tag':'#CLAN'}]}))
        @asynccontextmanager
        async def mongo(request):yield SimpleNamespace(player_activity=object())
        monkeypatch.setattr(strikes.shared,'mongo',mongo)
        monkeypatch.setattr(strikes,'service',AsyncMock(return_value=ledger))
        monkeypatch.setattr('utils.player_activity_store.PlayerActivityStore.overview',AsyncMock(return_value=[]))
        monkeypatch.setattr(clan_weights,'source_weights',AsyncMock(return_value={}))
        monkeypatch.setattr(clan_weights,'overlay_accounts',lambda store,payload:payload)
        for _ in range(3):
            response=await asyncio.wait_for(strikes.activity_accounts(request),.1)
            body=json.loads(response.body)
            assert not body['identity_warning']
            assert body['identity_updating'] is True
        await asyncio.sleep(0)
        assert recruit_links.resolve_players.await_count==1, repr(request.app)
        blocked.set()
        await request.app['activity_identity_cache']['task']
        for _ in range(3):
            response=await asyncio.wait_for(strikes.activity_accounts(request),.1)
            assert json.loads(response.body)['identity_updating'] is False
        assert recruit_links.resolve_players.await_count==1
    asyncio.run(run())


def test_route_clan_failure_names_clan_without_changing_healthy_chain(monkeypatch):
    import asyncio
    from datetime import datetime, timezone
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cwl_web import strikes
    from utils import clan_weights
    async def run():
        now = datetime.now(timezone.utc)
        sample={'tag':'#PYY','current_clan_tag':'#PQQ','updated_at':now,
                'recent_wars':[{'war_key':str(n),'occurred_at':now-timedelta(days=n),
                    'attacks_used':0,'attacks_available':2} for n in range(3)]}
        ledger=SimpleNamespace(activity_context=AsyncMock(return_value={
            'profiles':[], 'records':[], 'clans':[{'tag':'#PQQ','name':'Healthy clan'},
                                                {'tag':'#PQL','name':'Unavailable clan'}]}))
        @asynccontextmanager
        async def mongo(request):yield SimpleNamespace(player_activity=object())
        monkeypatch.setattr(strikes.shared,'mongo',mongo)
        monkeypatch.setattr(strikes,'service',AsyncMock(return_value=ledger))
        monkeypatch.setattr('utils.player_activity_store.PlayerActivityStore.overview',AsyncMock(return_value=[sample]))
        monkeypatch.setattr('utils.player_activity_store.PlayerActivityStore.history_report',AsyncMock(return_value=['#PQL']))
        monkeypatch.setattr('cwl_web.strike_activity_identity.account_identities',AsyncMock(return_value=({},True)))
        monkeypatch.setattr(clan_weights,'source_weights',AsyncMock(return_value={}))
        monkeypatch.setattr(clan_weights,'overlay_accounts',lambda store,payload:payload)
        response=await strikes.activity_accounts(SimpleNamespace(app={'store':object(),'providers':object()}))
        result=json.loads(response.body)
        assert result['history_warning']=='Some war reads unavailable for clans: Unavailable clan'
        assert result['accounts'][0]['no_attack_wars']==3
        assert result['accounts'][0]['observed_wars']==3
    asyncio.run(run())


def test_identity_failure_cooldown_can_recover_and_pending_is_not_failure(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cwl_web import strike_activity_identity as identity, manage_roles
    from utils import recruit_links
    async def run():
        clock = [0]
        monkeypatch.setattr(identity.time, "monotonic", lambda: clock[0])
        request = SimpleNamespace(app={})
        recruit_links.resolve_players.side_effect = [TimeoutError(), recruit_links.PlayerOwners(owners={"#PYY": "123456789012345678"})]
        monkeypatch.setattr(manage_roles, "searchable_members", AsyncMock(return_value=[{"nick":"Recovered", "user":{"id":"123456789012345678"}}]))
        assert (await identity.account_identities(request,["#PYY"])) == ({},False)
        await request.app["activity_identity_cache"]["task"]
        assert (await identity.account_identities(request,["#PYY"])) == ({},True)
        assert recruit_links.resolve_players.await_count == 1
        clock[0] = 121
        await identity.account_identities(request,["#PYY"])
        await request.app["activity_identity_cache"]["task"]
        rows, warning = await identity.account_identities(request,["#PYY"])
        assert rows["#PYY"]["discord_name"] == "Recovered" and not warning
    asyncio.run(run())


def test_background_identity_lookup_can_complete_after_the_old_eight_second_limit(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cwl_web import strike_activity_identity as identity, manage_roles
    from utils import recruit_links
    async def run():
        async def slow(tags):
            await asyncio.sleep(8.05)
            return recruit_links.PlayerOwners(owners={"#PYY":"123456789012345678"})
        recruit_links.resolve_players.side_effect = slow
        monkeypatch.setattr(manage_roles, "searchable_members", AsyncMock(return_value=[{"nick":"Cold success", "user":{"id":"123456789012345678"}}]))
        request = SimpleNamespace(app={})
        assert await identity.account_identities(request,["#PYY"]) == ({},False)
        await request.app["activity_identity_cache"]["task"]
        rows, warning = await identity.account_identities(request,["#PYY"])
        assert rows["#PYY"]["discord_name"] == "Cold success" and not warning
    asyncio.run(run())

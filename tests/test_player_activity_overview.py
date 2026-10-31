import gzip
import json
from datetime import timedelta
from tests.test_player_activity_signals import NOW
from utils.player_activity_overview import family_activity_rows
from cwl_web.strikes import public


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
        with patch.object(strikes.shared,'mongo',mongo), patch.object(strikes,'service',AsyncMock(return_value=ledger)), \
             patch('utils.player_activity_store.PlayerActivityStore.all_players',AsyncMock(return_value=activity)), \
             patch.object(clan_weights,'source_weights',weights), \
             patch.object(clan_weights,'overlay_accounts',lambda store,payload: payload):
            result=json.loads((await strikes.activity_accounts(request)).body)
            assert result['accounts'][0]['weight']==149000
            assert not result['weight_warning']
            assert weights.call_args.args[2]==['#PYY']
            weights.side_effect=ProviderUnavailable('fixture outage')
            result=json.loads((await strikes.activity_accounts(request)).body)
            assert len(result['accounts'])==1 and result['weight_warning']
    asyncio.run(run())

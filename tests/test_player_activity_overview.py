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

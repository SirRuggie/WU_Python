import asyncio
import json
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from utils.war_reminder_health import health
from utils.war_reminder_store import WarReminderStore
from utils import war_reminder_store as storage
from cwl_web import war_reminders as api
from cwl_web.manage_clans import public

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
CONFIG = dict(enabled=True, channel_id='123456789012345678', updated_at=NOW-timedelta(minutes=10))
STATE = dict(checked_at=NOW, detail='Tracking battle day', error=None)

@pytest.mark.parametrize('config,state,delivery,category,label', [
    (None,None,None,'not_configured','Not configured'),
    ({**CONFIG,'enabled':False},STATE,{'status':'uncertain'},'off','Off'),
    ({**CONFIG,'channel_id':''},STATE,None,'attention','Channel needed'),
    (CONFIG,STATE,{'status':'uncertain'},'attention','Check delivery'),
    (CONFIG,STATE,{'status':'sending'},'attention','Check delivery'),
    (CONFIG,STATE,{'status':'failed'},'attention','Check delivery'),
    (CONFIG,STATE,{'status':'sent'},'tracking','Monitoring'),
    (CONFIG,{**STATE,'checked_at':NOW-timedelta(minutes=4)},None,'attention','Check overdue'),
    (CONFIG,{**STATE,'checked_at':NOW+timedelta(minutes=2)},None,'attention','Check overdue'),
    (CONFIG,{**STATE,'error':'Network'},None,'attention','Check failed'),
    (CONFIG,None,None,'attention','No recent check'),
    ({**CONFIG,'updated_at':NOW},None,None,'pending','Awaiting check'),
    ({**CONFIG,'updated_at':NOW}, {**STATE,'checked_at':NOW-timedelta(seconds=5),'error':'OldError'},None,'pending','Awaiting check'),
    (CONFIG,{**STATE,'checked_at':NOW.replace(tzinfo=None)},None,'tracking','Monitoring'),
])
def test_health_never_confuses_enabled_with_verified(config,state,delivery,category,label):
    assert health(config,state,delivery,NOW)[:2] == (category,label)


def cursor(rows):
    value = NS(to_list=AsyncMock(return_value=rows))
    value.sort = Mock(return_value=value)
    return value


def test_batched_overview_preserves_revision_excludes_tests_and_removed_clans(monkeypatch):
    clan = {'_id':'mongo-id', 'tag':'#P0LY','name':'Warriors'}
    clans=NS(find=Mock(return_value=cursor([clan])))
    configs=NS(find=Mock(return_value=cursor([{'_id':'#P0LY',**CONFIG}])))
    states=NS(find=Mock(return_value=cursor([{'_id':'#P0LY',**STATE}])))
    deliveries=NS(aggregate=AsyncMock(return_value=cursor([{'_id':'#P0LY','latest':{'status':'sent','at':NOW}}])))
    collections={'war_reminder_settings':configs,'war_reminder_status':states,'war_reminder_deliveries':deliveries}
    monkeypatch.setattr(storage,'collection',lambda db,name='war_reminder_settings':collections[name])
    store=WarReminderStore(NS(clans=clans))
    result=asyncio.run(store.family_overview())
    assert public(result[0][0])['revision']==public(clan)['revision']
    assert len(result)==1 and result[0][3]['status']=='sent'
    configs.find.assert_called_once_with({'_id':{'$in':['#P0LY']}})
    pipeline=deliveries.aggregate.await_args.args[0]
    assert pipeline[0]=={'$match':{'clan_tag':{'$in':['#P0LY']},'test':False}}
    assert pipeline[1]=={'$sort':{'clan_tag':1,'at':-1}}
    assert deliveries.aggregate.await_args.kwargs['maxTimeMS']==10000


def test_overview_endpoint_auth_before_database_access(monkeypatch):
    monkeypatch.setattr(api,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    db=Mock()
    monkeypatch.setattr(api,'mongo',db)
    with pytest.raises(web.HTTPForbidden):asyncio.run(api.overview(NS()))
    db.assert_not_called()


def test_overview_response_is_read_only_and_contains_public_fields(monkeypatch):
    actor=AsyncMock()
    monkeypatch.setattr(api,'require_manage',actor)
    @asynccontextmanager
    async def mongo(request):yield object()
    monkeypatch.setattr(api,'mongo',mongo)
    rows=[({'_id':'private-id','tag':'#P0LY','name':'Warriors'},None,None,None)]
    monkeypatch.setattr(api,'WarReminderStore',lambda db:NS(family_overview=AsyncMock(return_value=rows)))
    request=NS()
    response=asyncio.run(api.overview(request))
    body=json.loads(response.text)
    assert body['clans'][0]['health']['category']=='not_configured'
    assert '_id' not in body['clans'][0]['clan']
    assert body['generated_at'].endswith('+00:00')
    actor.assert_awaited_once_with(request,'clans')

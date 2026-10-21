import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from cwl_web import war_reminders as api
from utils import war_reminders as r


@pytest.fixture
def setup(monkeypatch):
    coll = NS(insert_one=AsyncMock(), update_one=AsyncMock())
    db = NS(clans=NS(find_one=AsyncMock(return_value={'tag':'#P0LY','name':'Warriors'})))
    @asynccontextmanager
    async def mongo(request): yield db
    monkeypatch.setattr(api,'mongo',mongo)
    monkeypatch.setattr(r,'collection',lambda *args:coll)
    monkeypatch.setattr(api,'require_manage',AsyncMock(return_value={'user_id':'123456789012345678'}))
    discord = AsyncMock(side_effect=[{'guild_id':str(r.GUILD_ID),'type':0},{'id':'456'}])
    monkeypatch.setattr(api,'discord',discord)
    req = NS(match_info={'tag':'#P0LY'},json=AsyncMock(return_value={'settings':{**r.settings(),'channel_id':'123456789012345679'},'event':'60','request_id':str(uuid4()),'mention_me':True}))
    return req,coll,discord


def test_test_send_mentions_only_actor_and_returns_receipt(setup):
    req,coll,discord=setup
    response=asyncio.run(api.test_send(req))
    assert json.loads(response.text)['url'].endswith('/456')
    payload=discord.await_args.kwargs['json']
    assert payload['allowed_mentions']['users']==['123456789012345678']
    assert coll.insert_one.await_args.args[0]['test'] is True
    assert coll.update_one.await_args.args[1]['$set']['status']=='sent'


def test_foreign_channel_rejected_before_send(setup):
    req,coll,discord=setup;discord.side_effect=None;discord.return_value={'guild_id':'other','type':0}
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.test_send(req))
    assert discord.await_count==1 and not coll.insert_one.called


def test_test_send_claim_prevents_duplicate(setup):
    req,coll,discord=setup;coll.insert_one.side_effect=DuplicateKeyError('duplicate')
    with pytest.raises(web.HTTPConflict):asyncio.run(api.test_send(req))
    assert discord.await_count==1


def test_delivery_failure_is_uncertain(setup):
    req,coll,discord=setup;discord.side_effect=[{'guild_id':str(r.GUILD_ID),'type':0},web.HTTPServiceUnavailable()]
    with pytest.raises(web.HTTPServiceUnavailable):asyncio.run(api.test_send(req))
    assert coll.update_one.await_args.args[1]['$set']['status']=='uncertain'


def test_access_denied_before_request_read(setup,monkeypatch):
    req,_,discord=setup;monkeypatch.setattr(api,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):asyncio.run(api.test_send(req))
    req.json.assert_not_awaited();discord.assert_not_awaited()


def test_save_rejects_stale_revision(setup):
    req,coll,discord=setup
    coll.find_one=AsyncMock(return_value={'_id':'#P0LY','version':2})
    req.json.return_value['revision']='stale'
    with pytest.raises(web.HTTPConflict):asyncio.run(api.save(req))
    coll.update_one.assert_not_awaited()


def test_save_compare_and_swap_rejects_concurrent_edit(setup):
    req,coll,discord=setup
    before={'_id':'#P0LY','version':2}
    coll.find_one=AsyncMock(return_value=before)
    coll.update_one.return_value=NS(matched_count=0,upserted_id=None)
    req.json.return_value['revision']=api.revision(before)
    with pytest.raises(web.HTTPConflict):asyncio.run(api.save(req))
    assert coll.update_one.await_args.args[0]=={'_id':'#P0LY','version':2}


def test_save_persists_normalized_times_and_actor(setup,monkeypatch):
    req,coll,discord=setup
    coll.find_one=AsyncMock(return_value=None)
    coll.update_one.return_value=NS(matched_count=0,upserted_id='#P0LY')
    req.json.return_value.update(revision=api.revision(None))
    req.json.return_value['settings']['minutes']=[75,75,30]
    monkeypatch.setattr(api,'read',AsyncMock(return_value=web.json_response({'ok':True})))
    asyncio.run(api.save(req))
    changes=coll.update_one.await_args.args[1]['$set']
    assert changes['minutes']==[75,30] and changes['updated_by']=='123456789012345678'

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
from utils import war_reminder_store as storage


@pytest.fixture
def setup(monkeypatch):
    coll = NS(insert_one=AsyncMock(), update_one=AsyncMock())
    db = NS(clans=NS(find_one=AsyncMock(return_value={'tag':'#P0LY','name':'Warriors'})))
    @asynccontextmanager
    async def mongo(request): yield db
    monkeypatch.setattr(api,'mongo',mongo)
    monkeypatch.setattr(storage,'collection',lambda *args:coll)
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


def test_linked_samples_use_actor_accounts_cache_and_simulated_counts():
    providers=NS(linked_tags=AsyncMock(return_value={'#B':True,'#A':True}),clan_roster=AsyncMock(return_value={'members':[{'tag':'#A','name':'Real One','town_hall':18},{'tag':'#B','name':'Real Two','town_hall':17},{'tag':'#OTHER','name':'Someone Else','town_hall':16}]}))
    req=NS(app={'providers':providers})
    actor={'user_id':'505227988229554179'}
    async def run():
        args=(req,{'tag':'#P0LY','name':'Warriors'},r.settings(),'60',{'use_my_accounts':True,'mention_me':True},actor)
        first=await api.test_messages(*args)
        await api.test_messages(*args)
        return first
    first=asyncio.run(run())
    providers.linked_tags.assert_awaited_once_with(actor['user_id'])
    providers.clan_roster.assert_awaited_once_with('#P0LY')
    assert 'Someone Else' not in str(first)
    assert first[0]['allowed_mentions']['users']==[actor['user_id']]
    assert '<@505227988229554179>' in first[0]['content']
    assert 'Simulated attacks' in first[0]['content']
    assert 'Real One' in first[0]['content'] and 'Real Two' in first[0]['content']
    assert 'Shield Bearer' not in str(first)


def test_no_linked_accounts_does_not_silently_use_fake_players():
    req=NS(app={'providers':NS(linked_tags=AsyncMock(return_value={}))})
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(api.test_messages(req,{'tag':'#P0LY','name':'Warriors'},r.settings(),'60',{'use_my_accounts':True},{'user_id':'505227988229554179'}))


@pytest.mark.parametrize('body', [None, [], 'bad', 42])
def test_malformed_body_is_a_client_error(body):
    with pytest.raises(web.HTTPBadRequest): api.candidate(body)


@pytest.mark.parametrize('event', ['9'*5000, '１２', '-1', '0', '1441', '1.5', None, True])
def test_invalid_preview_times_are_client_errors(event):
    with pytest.raises(web.HTTPBadRequest): api.event_key({'event':event})


def test_form_cannot_supply_a_different_mention_recipient(setup):
    req,coll,discord=setup
    req.json.return_value.update(user_id='999999999999999999',tester='999999999999999999')
    asyncio.run(api.test_send(req))
    assert discord.await_args.kwargs['json']['allowed_mentions']['users']==['123456789012345678']


def test_multipart_test_sends_all_parts_and_keeps_partial_receipts(setup,monkeypatch):
    req,coll,discord=setup
    monkeypatch.setattr(api,'test_messages',AsyncMock(return_value=[
        {'content':'first','allowed_mentions':{'users':['123456789012345678']}},
        {'content':'second','allowed_mentions':{'users':[]}},
    ]))
    discord.side_effect=[{'guild_id':str(r.GUILD_ID),'type':0},{'id':'first'},{'id':'second'}]
    result=json.loads(asyncio.run(api.test_send(req)).text)
    assert len(result['urls'])==2 and discord.await_count==3
    assert coll.update_one.await_args.args[1]['$set']['status']=='sent'


def test_partial_delivery_failure_records_sent_part_without_automatic_retry(setup,monkeypatch):
    req,coll,discord=setup
    monkeypatch.setattr(api,'test_messages',AsyncMock(return_value=[{'content':'first'},{'content':'second'}]))
    discord.side_effect=[{'guild_id':str(r.GUILD_ID),'type':0},{'id':'first'},web.HTTPServiceUnavailable()]
    with pytest.raises(web.HTTPServiceUnavailable):asyncio.run(api.test_send(req))
    receipt=coll.update_one.await_args.args[1]['$set']
    assert receipt['status']=='uncertain' and len(receipt['urls'])==1


def test_sample_cache_is_scoped_to_user_and_clan():
    from cwl_web.war_reminder_samples import SampleAccounts
    cache=SampleAccounts()
    providers=NS(linked_tags=AsyncMock(side_effect=[{'#A':True},{'#B':True},{'#C':True}]),
                 clan_roster=AsyncMock(return_value={'members':[{'tag':tag,'name':tag,'town_hall':18} for tag in ['#A','#B','#C']]}))
    async def run():
        assert (await cache.get(providers,'1','#CLAN1'))[0]['tag']=='#A'
        assert (await cache.get(providers,'2','#CLAN1'))[0]['tag']=='#B'
        assert (await cache.get(providers,'1','#CLAN2'))[0]['tag']=='#C'
        assert (await cache.get(providers,'1','#CLAN1'))[0]['tag']=='#A'
    asyncio.run(run())
    assert providers.linked_tags.await_count==3

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from cwl_web import command_test as api
from utils.text_commands import GUILD_ID

@pytest.fixture
def setup(monkeypatch):
    audit=NS(insert_one=AsyncMock(),update_one=AsyncMock(),find_one=AsyncMock(return_value={'url':'https://discord.com/test'}))
    db=NS(bot_config=NS(database=NS(get_collection=lambda *a,**kw:audit)))
    @asynccontextmanager
    async def mongo(request):yield db
    discord=AsyncMock(side_effect=[{'guild_id':str(GUILD_ID),'type':0},{'id':'456'}])
    monkeypatch.setattr(api,'mongo',mongo);monkeypatch.setattr(api,'discord',discord)
    monkeypatch.setattr(api,'require_manage',AsyncMock(return_value={'user_id':'123'}))
    monkeypatch.setattr(api,'load_files',AsyncMock(return_value={}))
    body={'channel_id':'123456789012345678','request_id':'a'*24,'values':{'command':'!test','text':'@everyone test','allow_pings':True}}
    request=NS(json=AsyncMock(return_value=body))
    return request,body,discord,audit

def test_send_inert_and_audited(setup):
    request,body,discord,audit=setup
    response=asyncio.run(api.send(request))
    data=discord.await_args.kwargs['json']
    assert data['allowed_mentions']=={'parse':[]}
    assert data['enforce_nonce'] is True
    assert '456' in response.text
    assert audit.insert_one.await_count==1 and audit.update_one.await_count==1

def test_foreign_channel_rejected(setup):
    request,body,discord,audit=setup
    discord.side_effect=[{'guild_id':'other','type':0}]
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.send(request))
    assert audit.insert_one.await_count==0 and discord.await_count==1

def test_duplicate_does_not_resend(setup):
    request,body,discord,audit=setup
    audit.insert_one.side_effect=DuplicateKeyError('duplicate')
    assert 'discord.com/test' in asyncio.run(api.send(request)).text
    assert discord.await_count==1

def test_disabled_nested_actions():
    value=[{'type':17,'components':[{'type':1,'components':[{'type':2,'custom_id':'ct:test'},{'type':2,'url':'https://example.com'}]}]}]
    api.disable_actions(value)
    assert value[0]['components'][0]['components'][0]['disabled']
    assert 'disabled' not in value[0]['components'][0]['components'][1]

def test_permission_before_body(setup,monkeypatch):
    request,*_=setup
    monkeypatch.setattr(api,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):asyncio.run(api.send(request))
    request.json.assert_not_awaited()

def test_attachment_uses_multipart(setup,monkeypatch):
    import hikari
    request,body,discord,audit=setup
    monkeypatch.setattr(api,'payload',lambda *args:{'components':[],'attachments':[hikari.Bytes(b'hello','test.txt')]})
    asyncio.run(api.send(request))
    assert 'data' in discord.await_args.kwargs

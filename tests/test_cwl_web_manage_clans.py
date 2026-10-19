import asyncio,copy
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from cwl_web import manage_clans as api

class Rows:
    def __init__(self,row):self.row=row;self.changes=[]
    async def find_one(self,q):return copy.deepcopy(self.row)
    async def update_one(self,q,change,**kwargs):
        self.changes.append((q,change))
        if self.row is None:return NS(matched_count=0)
        if any((k in self.row if v=={'$exists':False} else self.row.get(k)!=v) for k,v in q.items()):return NS(matched_count=0)
        self.row.update(change['$set']);return NS(matched_count=1)
    async def delete_one(self,q):self.row=None;return NS(deleted_count=1)

@pytest.fixture
def setup(monkeypatch):
    rows=Rows({'_id':'clan1','tag':'#P0LYQ','name':'Warriors','type':'FWA','emoji':'','role_id':123456789012345678})
    history=NS(insert_one=AsyncMock())
    db=NS(clans=rows,bot_config=NS(database=NS(get_collection=lambda *a,**kw:history)))
    @asynccontextmanager
    async def mongo(request):yield db
    monkeypatch.setattr(api,'mongo',mongo);monkeypatch.setattr(api,'require_manage',AsyncMock(return_value={'user_id':'owner','roles':[]}))
    req=NS(match_info={'tag':'#P0LYQ'},json=AsyncMock(return_value={'revision':api.revision(rows.row),'values':{'type':'Tactical'}}))
    return req,rows,history

def test_dashboard_update_shared_record_preserves_other_fields(setup):
    req,rows,history=setup
    asyncio.run(api.save(req))
    assert rows.row['type']=='Tactical' and rows.row['role_id']==123456789012345678
    assert history.insert_one.await_count==1
    assert api.public(rows.row)['type']=='Tactical'

def test_native_edit_rejects_stale_web_save(setup):
    req,rows,history=setup;rows.row['type']='CWL'
    with pytest.raises(web.HTTPConflict):asyncio.run(api.save(req))
    assert rows.row['type']=='CWL' and not rows.changes

def test_unknown_fields_rejected(setup):
    req,rows,_=setup;req.json.return_value['values']={'_id':'other'}
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.save(req))
    assert not rows.changes

def test_remove_requires_tag_and_retains_snapshot(setup):
    req,rows,history=setup
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.remove(req))
    req.json.return_value['confirm_tag']='#P0LYQ'
    asyncio.run(api.remove(req))
    assert rows.row is None
    assert history.insert_one.await_args.args[0]['clan']['tag']=='#P0LYQ'

def test_foreign_channel_rejected(setup,monkeypatch):
    req,rows,_=setup;req.json.return_value['values']={'chat_channel_id':'123456789012345679'}
    monkeypatch.setattr(api,'discord',AsyncMock(return_value={'guild_id':'other','type':0}))
    with pytest.raises(web.HTTPBadRequest):asyncio.run(api.save(req))
    assert not rows.changes

def test_denied_before_database(setup,monkeypatch):
    req,rows,_=setup;monkeypatch.setattr(api,'require_manage',AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden):asyncio.run(api.save(req))
    req.json.assert_not_awaited()

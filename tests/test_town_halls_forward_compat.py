"""1184 schema compatibility retained under the245 admin storage contract."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bson import BSON
import pytest
from utils import town_halls as store
from test_town_halls import registry


def schema2():
    doc=registry();doc.update(schema_version=2,nonbase_revision=5)
    doc['levels']['19']['bases']={'war_image':'https://example.org/war.png','active_image':'https://example.org/active.png','merged':{'link':'https://link.clashofclans.com/en?action=OpenLayout&id=fixture','instructions':'Saved instructions ✓','upgrade_notes':'Keep this note'},'non_merged':{'link':'','instructions':'Hidden variant','upgrade_notes':''}}
    return doc


def test_schema2_registry_loads_without_changing_base_bytes(monkeypatch):
    doc=schema2();before=BSON.encode(doc['levels']['19']['bases'])
    collection=SimpleNamespace(find_one=AsyncMock(return_value=doc))
    monkeypatch.setattr(store,'_collection',lambda _:collection)
    loaded=asyncio.run(store.load(object(),123))
    assert loaded==doc and loaded is not doc
    assert BSON.encode(loaded['levels']['19']['bases'])==before


def test_admin_save_preserves_bases_and_stamps_nonbase_revision(monkeypatch):
    original=schema2();before=BSON.encode(original['levels']['19']['bases'])
    changed=store.set_emoji(original,19,'')
    committed=deepcopy(changed);committed.update(revision=8,nonbase_revision=8)
    collection=SimpleNamespace(find_one_and_update=AsyncMock(return_value=committed))
    monkeypatch.setattr(store,'_collection',lambda _:collection)
    saved=asyncio.run(store.save(object(),123,changed,456,7))
    assert saved['revision']==saved['nonbase_revision']==8
    assert BSON.encode(saved['levels']['19']['bases'])==before
    assert original['nonbase_revision']==5
    args=collection.find_one_and_update.await_args
    assert args.args[0]=={'_id':'123','revision':7} and args.kwargs['upsert'] is False
    assert args.args[1]['$set']['nonbase_revision']==8
    assert not any('.bases' in path for path in args.args[1]['$set'])


def test_unknown_keys_still_fail_in_schema2():
    for path in [('surprise',),('levels','19','surprise'),('levels','19','bases','surprise'),('levels','19','bases','merged','surprise')]:
        doc=schema2();target=doc
        for key in path[:-1]:target=target[key]
        target[path[-1]]='not permitted'
        with pytest.raises(ValueError):store.validate(doc)

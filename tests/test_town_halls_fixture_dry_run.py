"""26/65/125-account SQLite samples alongside fixture-only Mongo dry runs."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from cwl_web.store import Store
from test_town_halls_migration import FakeCollection, legacy
from test_town_halls_bases import AtomicCollection, registry, LINK
from tools import migrate_town_halls as migration
from utils import town_halls

@pytest.mark.parametrize('accounts',[26,65,125])
@pytest.mark.parametrize('bases', [False, True])
def test_migration_dry_run_preserves_fixture_counts(accounts,bases,tmp_path,monkeypatch):
    store=Store(str(tmp_path/'fixture.sqlite'))
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label,signup_open) VALUES(1,'Isolated fixture',1)")
        db.execute("INSERT INTO clans(tag,name) VALUES('#P2Y','Fixture clan')")
        for i in range(accounts):
            tag=f'#FIX{i:04}'
            db.execute("INSERT INTO signups(season_id,tag,user_id,player_name,town_hall,pool,prefer_crystal_1_or_lower) VALUES(1,?,?,?,?,?,0)",(tag,str(1000+i),f'Fixture {i}',19,'main' if i<accounts//2 else 'lazy'))
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES(1,?,?,?)",(tag,'#P2Y' if i%3 else None,int(i%5==0)))
    def counts():
        with store.read() as db:
            return {pool:dict(zip(('signups','assigned','locked'),db.execute("SELECT COUNT(*),SUM(r.assigned_clan_tag IS NOT NULL),SUM(r.kept) FROM signups s JOIN roster_entries r USING(season_id,tag) WHERE s.pool=?",(pool,)).fetchone())) for pool in ('main','lazy')}
    old,new=FakeCollection([legacy()]),FakeCollection([])
    base_source = {'_id': 'fwa_config', 'fwa_base_links': {'th19': LINK},
        'base_information': {'th19': 'Fixture instructions'},
        'war_base_images': {'th19': 'https://images.example/merged.png',
                            'th19_new': 'https://images.example/nonmerged.png'}}
    base_collection = AtomicCollection(registry())
    base_before = deepcopy(base_collection.row)
    before=counts();legacy_before=deepcopy(old.rows)
    monkeypatch.setattr(migration,'collection_from',lambda _parent,alias: old if alias=='war_weight_settings' else pytest.fail('Unexpected collection'))
    monkeypatch.setattr(town_halls,'_collection',lambda _mongo:base_collection if bases else new)
    source_collection = SimpleNamespace(find_one=AsyncMock(return_value=base_source))
    report=asyncio.run(migration.migrate(SimpleNamespace(fwa_data=source_collection if bases else object()),123,bases=bases))
    after=counts()
    assert before==after and old.rows==legacy_before and new.rows==[]
    assert report['counts_before']==report['counts_after']
    if bases:
        assert base_collection.row == base_before and base_collection.calls == []
        assert report['counts_before']['town_halls_documents'] == 1
        assert report['proposed_registry_counts']['merged_links'] == 1
        assert len(report['image_differences']) == 1
        assert not report['applied']
    else:
        assert report['counts_before']=={'war_weight_settings':1,'town_halls':0}
        assert not report['inserted']
    assert report['status']=='dry run' and report['legacy_unchanged']
    receipt={'accounts':accounts,'bases':bases,'sqlite_before':before,'sqlite_after':after,'migration_before':report['counts_before'],'migration_after':report['counts_after'],'legacy_bson_before':report['legacy_document_sha256_before'],'legacy_bson_after':report['legacy_document_sha256_after']}
    (tmp_path/'migration-dry-run.json').write_text(json.dumps(receipt,indent=2))
    print('FIXTURE_DRY_RUN '+json.dumps(receipt,sort_keys=True))

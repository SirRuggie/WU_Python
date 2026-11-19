"""26/65/125-account SQLite samples alongside fixture-only Mongo dry runs."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from cwl_web.store import Store
from test_town_halls_migration import FakeCollection, legacy
from tools import migrate_town_halls as migration
from utils import town_halls

@pytest.mark.parametrize('accounts',[26,65,125])
def test_migration_dry_run_preserves_fixture_counts(accounts,tmp_path,monkeypatch):
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
    before=counts();legacy_before=deepcopy(old.rows)
    monkeypatch.setattr(migration,'collection_from',lambda _parent,alias: old if alias=='war_weight_settings' else pytest.fail('Unexpected collection'))
    monkeypatch.setattr(town_halls,'_collection',lambda _mongo:new)
    report=asyncio.run(migration.migrate(SimpleNamespace(fwa_data=object()),123))
    after=counts()
    assert before==after and old.rows==legacy_before and new.rows==[]
    assert report['counts_before']==report['counts_after']=={'war_weight_settings':1,'town_halls':0}
    assert report['status']=='dry run' and report['legacy_unchanged'] and not report['inserted']
    receipt={'accounts':accounts,'sqlite_before':before,'sqlite_after':after,'migration_before':report['counts_before'],'migration_after':report['counts_after'],'legacy_bson_before':report['legacy_document_sha256_before'],'legacy_bson_after':report['legacy_document_sha256_after']}
    (tmp_path/'migration-dry-run.json').write_text(json.dumps(receipt,indent=2))
    print('FIXTURE_DRY_RUN '+json.dumps(receipt,sort_keys=True))

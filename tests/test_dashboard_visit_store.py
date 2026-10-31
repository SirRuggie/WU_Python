from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone, timedelta
import sqlite3
import pytest
from cwl_web.store import Store
from utils.dashboard_visit_store import VisitStore


def test_daily_visit_migration_is_additive_idempotent_and_metadata_minimal(tmp_path):
    path=tmp_path/'old.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE unrelated(value TEXT)')
        db.execute("INSERT INTO unrelated VALUES('preserve')")
    store=Store(str(path)); Store(str(path))
    assert store.one('SELECT value FROM unrelated')['value']=='preserve'
    columns=store.rows('PRAGMA table_info(visit_days)')
    assert {row['name'] for row in columns}=={'user_id','day','first_seen_at','is_staff'}
    assert [row['name'] for row in columns if row['pk']]==['user_id','day']


def test_daily_visit_is_idempotent_under_concurrent_page_loads(tmp_path):
    store=Store(str(tmp_path/'visits.sqlite')); visits=VisitStore(store)
    now=datetime(2026,11,1,1,30,tzinfo=timezone(timedelta(hours=-4)))
    def write(_):return visits.record('123',day=date(2026,11,1),at=now,is_staff=False)
    with ThreadPoolExecutor(max_workers=4) as pool:assert sum(pool.map(write,range(12)))==1
    assert not visits.record('123',day=date(2026,11,1),at=now+timedelta(hours=2),is_staff=True)
    row=store.one('SELECT * FROM visit_days')
    assert row['first_seen_at']=='2026-11-01T05:30:00+00:00'
    assert row['is_staff']==0
    assert visits.record('123',day=date(2026,11,2),at=now+timedelta(days=1),is_staff=True)
    assert len(store.rows('SELECT * FROM visit_days'))==2


def test_invalid_visit_data_never_writes(tmp_path):
    store=Store(str(tmp_path/'visits.sqlite')); visits=VisitStore(store)
    with pytest.raises(ValueError):visits.record('123',day=date.today(),at=datetime.now(),is_staff=False)
    with pytest.raises(ValueError):visits.record('bad',day=date.today(),at=datetime.now(timezone.utc),is_staff=False)
    with pytest.raises(ValueError):visits.record('123',day=date.today(),at=datetime.now(timezone.utc),is_staff='false')
    assert not store.rows('SELECT * FROM visit_days')

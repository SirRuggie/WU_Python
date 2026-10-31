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
    assert not store.rows("SELECT name FROM sqlite_master WHERE name='visit_days'")
    visits=VisitStore(tmp_path/'old.sqlite.visits.sqlite3')
    columns=visits.rows('PRAGMA table_info(visit_days)')
    assert {row['name'] for row in columns}=={'user_id','day','first_seen_at','is_staff'}
    assert [row['name'] for row in columns if row['pk']]==['user_id','day']


def test_daily_visit_is_idempotent_under_concurrent_page_loads(tmp_path):
    store=VisitStore(tmp_path/'visits.sqlite'); visits=store
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
    store=VisitStore(tmp_path/'visits.sqlite'); visits=store
    with pytest.raises(ValueError):visits.record('123',day=date.today(),at=datetime.now(),is_staff=False)
    with pytest.raises(ValueError):visits.record('bad',day=date.today(),at=datetime.now(timezone.utc),is_staff=False)
    with pytest.raises(ValueError):visits.record('123',day=date.today(),at=datetime.now(timezone.utc),is_staff='false')
    assert not store.rows('SELECT * FROM visit_days')


def test_local_day_dst_and_retention(tmp_path):
    store = VisitStore(tmp_path/'visits.sqlite'); visits = store
    visits.record_session('123', at=datetime(2026,11,1,5,30,tzinfo=timezone.utc), is_staff=False)
    assert not visits.record_session('123', at=datetime(2026,11,1,6,30,tzinfo=timezone.utc), is_staff=True)
    assert store.one('SELECT day FROM visit_days')['day'] == '2026-11-01'
    for age in (89,90):
        day=date(2026,11,1)-timedelta(days=age)
        visits.record(str(age),day=day,at=datetime(2026,8,1,tzinfo=timezone.utc),is_staff=False)
    VisitStore(store.path).prune(date(2026,11,1))
    assert {row['user_id'] for row in store.rows('SELECT user_id FROM visit_days')} == {'123','89'}


def test_aggregate_unique_windows_staff_transition_and_zero_days(tmp_path):
    store=VisitStore(tmp_path/'visits.sqlite'); visits=store; today=date(2026,11,1)
    for user,age,staff in [('123',0,False),('123',1,True),('456',6,False),('789',7,True),('999',30,False)]:
        visits.record(user,day=today-timedelta(days=age),at=datetime(2026,11,1,tzinfo=timezone.utc),is_staff=staff)
    result=visits.aggregates(today)
    assert result['windows']=={'1':{'total':1,'staff':0,'members':1},'7':{'total':2,'staff':1,'members':1},'30':{'total':3,'staff':2,'members':1}}
    assert len(result['series'])==30
    assert result['series'][0]['total']==0
    assert result['series'][-1]=={'day':'2026-11-01','total':1,'staff':0,'members':1}
    assert 'user_id' not in str(result)


def test_visit_file_permissions_wal_and_connection_timeout(tmp_path):
    import stat
    path = tmp_path / 'visits.sqlite'
    store = VisitStore(path)
    for _ in range(2):
        with store.tx() as db:
            assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            assert db.execute('PRAGMA busy_timeout').fetchone()[0] == 200
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        path.chmod(0o644)
    with VisitStore(path).tx() as db:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'

from datetime import datetime, timedelta, timezone
import pytest
from utils.gold_loot import connect
from utils import goldrush

START = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    db = connect(tmp_path / 'loot.db')
    goldrush.event_tables(db)
    with db:
        db.execute('INSERT INTO session VALUES (?, ?, ?)', ('#CLAN', 'WU', START.isoformat()))
        for tag in ('#ONE', '#TWO', '#THREE'):
            db.execute('INSERT INTO players VALUES (?, ?, 0, 0, ?, ?)', (tag, tag, START.isoformat(), START.isoformat()))
    yield db
    db.close()


def event(db, mode='single', late=True):
    return goldrush.create_event(db, guild_id=123, account_mode=mode, allow_late_join=late, at=START)


def loot(db, tag, when, amount):
    with db:
        db.execute('INSERT INTO loot_events VALUES (?, ?, ?, ?)', (tag, when.isoformat(), 'farming', amount))


def test_only_entrants_count_with_exact_event_boundaries_and_late_backfill(db):
    e=event(db)
    goldrush.start_event(db,e['id'],at=START)
    loot(db,'#ONE',START-timedelta(seconds=1),900)
    loot(db,'#ONE',START,100)
    loot(db,'#ONE',START+timedelta(hours=24),900)
    loot(db,'#TWO',START,999999)
    goldrush.join_event(db,e['id'],1,['#ONE'],at=START+timedelta(hours=2))
    rows=goldrush.standings(db,e['id'])
    assert len(rows)==1 and rows[0]['gold']==100


def test_duplicate_join_account_lock_and_conflicting_owner(db):
    e=event(db)
    assert goldrush.join_event(db,e['id'],1,['#ONE'],at=START)
    assert not goldrush.join_event(db,e['id'],1,['#ONE'],at=START)
    with pytest.raises(ValueError,match='locked'):
        goldrush.join_event(db,e['id'],1,['#TWO'],at=START)
    with pytest.raises(ValueError,match='already entered'):
        goldrush.join_event(db,e['id'],2,['#ONE'],at=START)


def test_end_and_signup_close_rules(db):
    e=event(db,late=False)
    goldrush.start_event(db,e['id'],at=START)
    with pytest.raises(ValueError,match='Signup closed'):
        goldrush.join_event(db,e['id'],1,['#ONE'],at=START)
    with pytest.raises(ValueError,match='has not ended'):
        goldrush.finalize_event(db,e['id'],at=START)


def test_combined_scoring_tie_uses_battle_time_and_final_snapshot(db):
    e=event(db,mode='combined')
    goldrush.join_event(db,e['id'],1,['#ONE','#TWO'],at=START)
    goldrush.join_event(db,e['id'],2,['#THREE'],at=START)
    goldrush.start_event(db,e['id'],at=START)
    loot(db,'#ONE',START,50)
    loot(db,'#TWO',START+timedelta(minutes=2),50)
    loot(db,'#THREE',START+timedelta(minutes=1),100)
    assert [r['user_id'] for r in goldrush.standings(db,e['id'])]==['2','1']
    goldrush.finalize_event(db,e['id'],at=START+timedelta(days=1))
    loot(db,'#ONE',START+timedelta(minutes=3),999)
    assert goldrush.standings(db,e['id'])[0]['gold']==100


def test_future_schedule_requires_bound_confirmation_and_preserves_entries_and_history(db):
    e=event(db)
    goldrush.start_event(db,e['id'],at=START)
    goldrush.join_event(db,e['id'],1,['#ONE'],at=START)
    loot(db,'#ONE',START,100)
    proposal=goldrush.propose_schedule(db,e['id'],7,START+timedelta(days=2),24,at=START)
    assert goldrush.standings(db,e['id'])[0]['gold']==100
    with pytest.raises(ValueError,match='administrator'):
        goldrush.confirm_schedule(db,proposal['id'],8,123,at=START)
    goldrush.confirm_schedule(db,proposal['id'],7,123,at=START)
    assert goldrush.standings(db,e['id'])[0]['gold']==0
    assert db.execute('SELECT count(*) FROM goldrush_entries').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM loot_events').fetchone()[0]==1
    with pytest.raises(ValueError,match='expired or was already used'):
        goldrush.confirm_schedule(db,proposal['id'],7,123,at=START)


def test_confirmation_expires_and_rejects_stale_event_settings(db):
    e=event(db)
    goldrush.start_event(db,e['id'],at=START)
    first=goldrush.propose_schedule(db,e['id'],7,START+timedelta(days=1),24,at=START)
    second=goldrush.propose_schedule(db,e['id'],7,START+timedelta(days=2),24,at=START)
    goldrush.confirm_schedule(db,first['id'],7,123,at=START)
    with pytest.raises(ValueError,match='event changed'):
        goldrush.confirm_schedule(db,second['id'],7,123,at=START)
    third=goldrush.propose_schedule(db,e['id'],7,START+timedelta(days=3),24,at=START)
    with pytest.raises(ValueError,match='expired'):
        goldrush.confirm_schedule(db,third['id'],7,123,at=START+timedelta(minutes=11))


def test_reopen_preserves_event_signups_and_scores(db):
    e=event(db)
    goldrush.start_event(db,e['id'],at=START)
    goldrush.join_event(db,e['id'],1,['#ONE'],at=START)
    loot(db,'#ONE',START,500)
    path=db.execute('PRAGMA database_list').fetchone()[2]
    other=connect(__import__('pathlib').Path(path))
    goldrush.event_tables(other)
    assert goldrush.current_event(other,123)['id']==e['id']
    assert goldrush.standings(other,e['id'])[0]['gold']==500
    other.close()


def test_per_account_conversion_preserves_signup_loot_and_reopen(db):
    e=event(db,mode='combined')
    goldrush.start_event(db,e['id'],at=START)
    loot(db,'#ONE',START,10_000_000)
    loot(db,'#TWO',START,8_000_000)
    loot(db,'#THREE',START,99_000_000)
    goldrush.join_event(db,e['id'],1,['#ONE','#TWO'],at=START+timedelta(hours=1))
    assert goldrush.standings(db,e['id'])[0]['gold']==18_000_000
    goldrush.use_per_account_scoring(db,123)
    path=__import__('pathlib').Path(db.execute('PRAGMA database_list').fetchone()[2])
    other=goldrush.open_store(path)
    try:
        rows=goldrush.standings(other,e['id'])
        assert [(r['user_id'],r['accounts'][0]['tag'],r['gold']) for r in rows]==[
            ('1','#ONE',10_000_000),('1','#TWO',8_000_000)]
        assert other.execute('SELECT count(*) FROM loot_events').fetchone()[0]==3
        assert other.execute('SELECT count(*) FROM goldrush_entries').fetchone()[0]==2
        assert goldrush.get_event(other,e['id'])['starts_at']==START.isoformat()
        goldrush.use_per_account_scoring(other,123)
        assert goldrush.standings(other,e['id'])==rows
    finally:
        other.close()


def test_conversion_does_not_change_final_results(db):
    e=event(db,mode='combined')
    goldrush.start_event(db,e['id'],at=START)
    goldrush.join_event(db,e['id'],1,['#ONE','#TWO'],at=START)
    loot(db,'#ONE',START,10)
    loot(db,'#TWO',START,8)
    goldrush.finalize_event(db,e['id'],at=START+timedelta(days=1))
    goldrush.use_per_account_scoring(db,123)
    assert goldrush.get_event(db,e['id'])['account_mode']=='combined'
    assert goldrush.standings(db,e['id'])[0]['gold']==18


def test_initial_event_ranks_accounts_separately(db):
    assert goldrush.ensure_current(db,123)['account_mode']=='per_account'


def test_per_account_rejoin_adds_missing_accounts_without_removing_existing(db):
    e=event(db,mode='per_account')
    goldrush.join_event(db,e['id'],1,['#ONE'],at=START)
    assert goldrush.join_event(db,e['id'],1,['#TWO'],at=START)
    assert not goldrush.join_event(db,e['id'],1,['#ONE','#TWO'],at=START)
    assert [r[0] for r in db.execute('SELECT player_tag FROM goldrush_entries ORDER BY player_tag')]==['#ONE','#TWO']



def test_snapshot_only_displays_positive_gold_and_keeps_zero_accounts_entered(db):
    e=event(db,mode='per_account')
    goldrush.start_event(db,e['id'],at=START)
    goldrush.join_event(db,e['id'],1,['#ONE','#TWO'],at=START)
    assert goldrush.snapshot(db,e['id'])['rows']==[]
    loot(db,'#ONE',START,100)
    data=goldrush.snapshot(db,e['id'])
    assert [r['accounts'][0]['tag'] for r in data['rows']]==['#ONE']
    assert data['accounts']==2 and data['entrants']==1
    loot(db,'#TWO',START,200)
    assert [r['gold'] for r in goldrush.snapshot(db,e['id'])['rows']]==[200,100]

from datetime import datetime, timedelta, timezone
import pytest
from utils.player_activity_signals import activity_signals, latest_raid_end

NOW = datetime(2026,11,3,12,tzinfo=timezone.utc)


@pytest.mark.parametrize('days,status', [(2,'active'),(3,'active'),(6,'active'),(7,'watch'),(13,'watch'),(14,'risk')])
def test_quiet_boundaries(days,status):
    row=activity_signals({'last_seen_at':NOW-timedelta(days=days),'updated_at':NOW}, [], now=NOW)
    assert row['status']==status and row['quiet_days']==days


def test_unknown_is_not_quiet_and_seed_provenance_is_retained():
    row=activity_signals({'tracking_started_at':NOW}, [], now=NOW)
    assert row['quiet_days'] is None and row['last_seen_at'] is None
    row=activity_signals({'last_seen_at':NOW-timedelta(days=20),'last_seen_source':'clashking_seed'},[],now=NOW)
    assert row['last_seen_source']=='clashking_seed'


@pytest.mark.parametrize('count,status', [(2,'watch'),(3,'risk')])
def test_last_regular_wars_exclude_cwl(count,status):
    wars=[{'war_key':str(n),'occurred_at':NOW-timedelta(days=n),'source':'war','capture_source':'clash_api','kind':'strike','missed_attacks':2}
          for n in range(count)]
    wars.append({'war_key':'cwl','occurred_at':NOW+timedelta(seconds=1),'source':'cwl','kind':'cwl','missed_attacks':1})
    row=activity_signals(None,wars,now=NOW)
    assert row['no_attack_wars']==count and row['observed_wars']==count
    assert row['observed_attacks']==count*2 and row['status']==status


def test_raid_skips_require_consecutive_latest_weekends():
    end=latest_raid_end(NOW)
    rows=[{'weekend_id':end.isoformat(),'attacked':False},
          {'weekend_id':(end-timedelta(days=14)).isoformat(),'attacked':False}]
    assert activity_signals({'raid_weekends':rows},[],now=NOW)['skipped_raid_weekends']==1
    rows[0]['attacked']=True
    assert activity_signals({'raid_weekends':rows},[],now=NOW)['skipped_raid_weekends']==0
    assert activity_signals({'raid_weekends':rows[1:]},[],now=NOW)['skipped_raid_weekends']==0


def test_imported_misses_do_not_invent_a_consecutive_history():
    rows=[{'war_key':str(n),'occurred_at':NOW-timedelta(days=n),'source':'war',
           'capture_source':'clashking_import','import_id':'fixture','kind':'strike','missed_attacks':2} for n in range(3)]
    signals=activity_signals({},rows,now=NOW)
    assert signals['no_attack_wars']==0 and signals['observed_wars']==0
    recent=[{'war_key':str(n),'occurred_at':NOW-timedelta(days=n),'attacks_used':0 if n%2==0 else 2,'attacks_available':2} for n in range(5)]
    signals=activity_signals({'recent_wars':recent},rows,now=NOW)
    assert signals['no_attack_wars']==1 and signals['missed_attacks']==6 and signals['observed_attacks']==10


@pytest.mark.parametrize('kind',['mismatch','exempt','no_attack'])
def test_non_penalty_wars_neither_count_nor_break_chain(kind):
    rows=[{'war_key':str(n),'occurred_at':NOW-timedelta(days=n),'source':'war','capture_source':'clash_api',
           'kind':kind if n==1 else 'strike','missed_attacks':2} for n in range(4)]
    signals=activity_signals({},rows,now=NOW)
    assert signals['observed_wars']==3 and signals['no_attack_wars']==3


@pytest.mark.parametrize('size',[13,15])
def test_observed_war_window_is_capped_at_fourteen(size):
    recent=[{'war_key':str(n),'occurred_at':NOW-timedelta(days=n),'attacks_used':1,'attacks_available':2} for n in range(size)]
    signals=activity_signals({'recent_wars':recent},[],now=NOW)
    assert signals['observed_wars']==min(size,14)
    assert signals['no_attack_wars']==0 and signals['missed_attacks']==min(size,14)


def test_stale_tracker_suppresses_quiet_and_quiet_badge():
    signals=activity_signals({'last_seen_at':NOW-timedelta(days=15),'updated_at':NOW-timedelta(hours=37)},[],now=NOW)
    assert signals['activity_tracking_behind'] and signals['quiet_days'] is None and signals['status']=='active'


@pytest.mark.parametrize('priority,status',[('high','watch'),('replace_first','risk')])
def test_priority_badges(priority,status):
    assert activity_signals({},[],priority=priority,now=NOW)['status']==status


def test_partial_attack_breaks_no_attack_chain_and_raid_skip_is_watch():
    recent=[{'war_key':str(n),'occurred_at':NOW-timedelta(days=n),'attacks_used':used,'attacks_available':2}
            for n,used in enumerate((0,1,0))]
    row=activity_signals({'recent_wars':recent},[],now=NOW)
    assert row['no_attack_wars']==1 and row['status']=='watch' and row['missed_attacks']==5
    row=activity_signals({'raid_weekends':[{'weekend_id':latest_raid_end(NOW).isoformat(),'attacked':False}]},[],now=NOW)
    assert row['status']=='watch'


def test_revoked_wars_are_neutral_and_incomplete_history_cannot_chain():
    rows = [
        {
            "war_key": str(n),
            "occurred_at": NOW - timedelta(days=n),
            "source": "war",
            "capture_source": "clash_api",
            "kind": "strike",
            "missed_attacks": 2,
            **({"revoked_at": NOW} if n == 1 else {}),
        }
        for n in range(4)
    ]
    result = activity_signals({}, rows, now=NOW)
    assert result["observed_wars"] == 3 and result["no_attack_wars"] == 3
    result = activity_signals({"recent_wars": [{"war_key": "unread", "occurred_at": NOW + timedelta(seconds=1), "unusable": True}]}, rows, now=NOW)
    assert (
        result["no_attack_wars"] == 0
        and result["status"] != "risk"
    )


def test_compact_summary_counts_only_known_wars_and_recent_known_raids():
    end=latest_raid_end(NOW)
    recent=[{'war_key':'miss','occurred_at':NOW-timedelta(days=1),'attacks_used':0,'attacks_available':2},
            {'war_key':'hit','occurred_at':NOW-timedelta(days=3),'attacks_used':1,'attacks_available':2},
            {'war_key':'barrier','occurred_at':NOW-timedelta(days=4),'unusable':True}]
    raids=[{'weekend_id':end.isoformat(),'attacked':False},
           {'weekend_id':(end-timedelta(days=7)).isoformat(),'attacked':None},
           {'weekend_id':(end-timedelta(days=14)).isoformat(),'attacked':True}]
    result=activity_signals({'recent_wars':recent,'raid_weekends':raids},[],now=NOW)
    assert result['observed_wars']==2 and result['attacked_wars']==1
    assert result['last_attacked_war_end']==NOW-timedelta(days=3)
    assert result['observed_raid_weekends']==1 and result['attacked_raid_weekends']==0
    empty=activity_signals({},[],now=NOW)
    assert empty['observed_wars']==0 and empty['attacked_wars']==0
    assert empty['last_attacked_war_end'] is None
    assert empty['observed_raid_weekends']==0 and empty['attacked_raid_weekends']==0

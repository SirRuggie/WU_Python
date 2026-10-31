from datetime import datetime, timedelta, timezone
import pytest
from utils.player_activity_signals import activity_signals, latest_raid_end

NOW = datetime(2026,11,3,12,tzinfo=timezone.utc)


@pytest.mark.parametrize('days,status', [(2,'active'),(3,'active'),(6,'active'),(7,'watch'),(13,'watch'),(14,'risk')])
def test_quiet_boundaries(days,status):
    row=activity_signals({'last_seen_at':NOW-timedelta(days=days)}, [], now=NOW)
    assert row['status']==status and row['quiet_days']==days


def test_unknown_is_not_quiet_and_seed_provenance_is_retained():
    row=activity_signals({'tracking_started_at':NOW}, [], now=NOW)
    assert row['quiet_days'] is None and row['last_seen_at'] is None
    row=activity_signals({'last_seen_at':NOW-timedelta(days=20),'last_seen_source':'clashking_seed'},[],now=NOW)
    assert row['last_seen_source']=='clashking_seed'


@pytest.mark.parametrize('count,status', [(2,'watch'),(3,'risk')])
def test_last_regular_wars_exclude_cwl(count,status):
    wars=[{'war_key':str(n),'occurred_at':NOW-timedelta(days=n),'source':'war','kind':'strike','missed_attacks':2}
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

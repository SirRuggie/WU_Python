from datetime import datetime, timedelta, timezone
import pytest
from utils.return_schedule import validate_window, before_start, window_end
from utils.return_reminder_status import return_status

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)

def test_timezone_and_window_validation():
    start,end = validate_window('2026-11-06T08:00:00-05:00','2026-11-07T08:00:00-05:00',now=NOW)
    assert start.hour == 13
    assert end-start == timedelta(days=1)
    for first,last in [('2026-11-06T08:00','2026-11-07T08:00Z'),('bad','bad'),('2026-11-06T00:00Z','2026-11-14T00:00Z'),('2026-11-06T00:00Z','2026-11-05T00:00Z')]:
        with pytest.raises(ValueError):validate_window(first,last,now=NOW)

def test_existing_window_and_seasonal_cutoff_cannot_be_extended():
    current={'expires_at':NOW+timedelta(days=4),'reminders':{'started_at':NOW-timedelta(days=5)}}
    with pytest.raises(ValueError,match='original seven-day'):validate_window(NOW.isoformat(),(NOW+timedelta(days=3)).isoformat(),current,now=NOW)
    current['reminders']={}
    with pytest.raises(ValueError,match='seasonal cutoff'):validate_window(NOW.isoformat(),(NOW+timedelta(days=5)).isoformat(),current,now=NOW)

def test_future_start_and_custom_stop_are_visible_and_enforced():
    settings={'enabled':True,'started_at':NOW+timedelta(days=1),'schedule_start_at':NOW+timedelta(days=1),'schedule_end_at':NOW+timedelta(days=2)}
    assert before_start(settings,NOW)
    assert not before_start(settings,NOW+timedelta(days=1))
    assert window_end(settings)==NOW+timedelta(days=2)
    row={'players':[],'expires_at':NOW+timedelta(days=10),'reminders':settings}
    assert return_status(row,'FWA',now=NOW)['label']=='Scheduled to start'
    assert return_status(row,'FWA',now=NOW+timedelta(days=2))['state']=='expired'
    assert return_status(row,'MAIN',now=NOW)['state']=='manual'

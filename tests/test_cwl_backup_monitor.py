import importlib.util
from pathlib import Path
from datetime import datetime, timezone
import pytest

spec = importlib.util.spec_from_file_location('monitor', Path(__file__).parents[1] / 'tools/backup/monitor.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def healthy():
    now = 1800000000
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    records = {kind: {'local_success': stamp, 'remote_success': stamp} for kind in m.JOBS}
    units = {}
    for unit, _ in m.JOBS.values():
        units[unit + '.timer'] = {'ActiveState': 'active', 'UnitFileState': 'enabled'}
        units[unit + '.service'] = {'LoadState': 'loaded', 'Result': 'success'}
    return now, records, units


def test_stale_remote_detected_even_when_local_succeeds():
    now, records, units = healthy()
    records['cwl']['remote_success'] = datetime.fromtimestamp(now - 1201, timezone.utc).isoformat()
    assert m.issues(now, records, units, True) == ['cwl: remote backup/check is missing or overdue.']


def test_failed_job_and_disabled_timer_detected_with_fresh_timestamps():
    now, records, units = healthy()
    units['cwl-backup.service']['Result'] = 'exit-code'
    units['cwl-backup.timer']['UnitFileState'] = 'disabled'
    result = m.issues(now, records, units, True)
    assert len(result) == 2
    assert any('failed' in item for item in result)
    assert any('disabled' in item for item in result)


def test_healthy_silent_incident_deduplicated_recovery_once():
    sent = []
    state = m.deliver([], {}, 100, sent.append)
    assert not sent
    state = m.deliver(['broken'], state, 200, sent.append)
    assert len(sent) == 1
    assert m.deliver(['broken'], state, 300, sent.append) == state
    assert len(sent) == 1
    state = m.deliver([], state, 400, sent.append)
    assert 'recovered' in sent[-1]
    m.deliver([], state, 500, sent.append)
    assert len(sent) == 2


def test_delivery_failure_does_not_acknowledge_incident():
    previous = {}
    def fail(_):
        raise RuntimeError('delivery failed')
    with pytest.raises(RuntimeError):
        m.deliver(['broken'], previous, 100, fail)
    assert previous == {}


def test_reminder_and_invalid_timestamp():
    now, records, units = healthy()
    records['mongo']['local_success'] = 'garbage'
    assert any('mongo: local' in item for item in m.issues(now, records, units, True))
    sent = []
    m.deliver(['broken'], {'issues': ['broken'], 'notified_at': 1}, 22000, sent.append)
    assert len(sent) == 1


def test_external_heartbeat_healthy_and_failure_use_no_payload():
    calls = []
    class Response:
        status_code = 200
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    url = 'https://hc-ping.com/12345678-1234-1234-1234-123456789abc'
    assert m.ping_external(url, True, get)
    assert m.ping_external(url, False, get)
    assert calls[0][0] == url
    assert calls[1][0] == url + '/fail'
    assert calls[0][1] == {'timeout': (5, 10), 'allow_redirects': False}


def test_external_url_missing_and_unsafe_rejected():
    def never(*args, **kwargs):
        raise AssertionError('No request expected')
    assert m.ping_external('', True, never) is False
    for url in ('http://hc-ping.com/test', 'https://example.com/test',
                'https://hc-ping.com/not-a-uuid', 'https://hc-ping.com/uuid?secret=yes'):
        with pytest.raises(RuntimeError):
            m.ping_external(url, True, never)


def test_external_failure_does_not_leak_ping_secret():
    url = 'https://hc-ping.com/12345678-1234-1234-1234-123456789abc'
    def fail(*args, **kwargs):
        raise m.requests.RequestException('private url: ' + url)
    with pytest.raises(RuntimeError) as error:
        m.ping_external(url, True, fail)
    assert url not in str(error.value)
    assert error.value.__suppress_context__


def test_external_http_failure_is_not_success():
    class Response:
        status_code = 403
    with pytest.raises(RuntimeError, match='403'):
        m.ping_external('https://hc-ping.com/12345678-1234-1234-1234-123456789abc', True,
                        lambda *args, **kwargs: Response())


def test_retry_start_is_not_recovery():
    issue='mongo: latest backup/check job failed.'
    previous={'issues':[issue],'notified_at':100}
    units={'cwl-mongo-backup.service':{'ActiveState':'activating','Result':'success'}}
    sent=[]
    pending=m.retain_running_incidents([],previous,units)
    assert pending==[issue]
    assert m.deliver(pending,previous,200,sent.append)==previous
    assert not sent
    units['cwl-mongo-backup.service']['ActiveState']='inactive'
    current=m.retain_running_incidents([],previous,units)
    m.deliver(current,previous,300,sent.append)
    assert len(sent)==1 and 'recovered' in sent[0]


def test_hourly_mongo_backup_does_not_false_alarm_between_scheduled_runs():
    now, records, units = healthy()
    stamp = datetime.fromtimestamp(now - 75 * 60, timezone.utc).isoformat()
    records['mongo'] = {'local_success': stamp, 'remote_success': stamp}
    assert m.issues(now, records, units, True) == []


def test_hourly_mongo_backup_overdue_after_ninety_minute_grace():
    now, records, units = healthy()
    records['mongo']['remote_success'] = datetime.fromtimestamp(now - 90 * 60 - 1, timezone.utc).isoformat()
    assert m.issues(now, records, units, True) == ['mongo: remote backup/check is missing or overdue.']

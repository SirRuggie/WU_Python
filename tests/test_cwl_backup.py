"""Recovery safety checks against actual SQLite files, without live services."""
import importlib.util
from pathlib import Path
import sqlite3
import pytest

spec = importlib.util.spec_from_file_location('cwl_backup', Path(__file__).parents[1] / 'tools/backup/cwl_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_missing_source_never_created(tmp_path):
    source, target = tmp_path / 'absent.sqlite', tmp_path / 'backup.sqlite'
    with pytest.raises(RuntimeError, match='missing or empty'):
        backup.snapshot(source, target)
    assert not source.exists()
    assert not target.exists()


def test_consistent_backup_includes_committed_wal_and_preserves_source(tmp_path):
    source, target = tmp_path / 'live.sqlite', tmp_path / 'backup.sqlite'
    with sqlite3.connect(source) as live:
        live.executescript('PRAGMA journal_mode=WAL; CREATE TABLE seasons(id INTEGER PRIMARY KEY);'
                          'CREATE TABLE signups(id INTEGER PRIMARY KEY, season INTEGER REFERENCES seasons(id));'
                          'INSERT INTO seasons VALUES(1); INSERT INTO signups VALUES(1,1);')
        counts = backup.snapshot(source, target)
        assert counts['signups'] == 1
        live.execute('INSERT INTO signups VALUES(2,1)')
        live.commit()
        assert backup.sqlite_check(target)['signups'] == 1
        assert backup.sqlite_check(source)['signups'] == 2


def test_invalid_snapshot_does_not_replace_good_backup(tmp_path):
    source, target = tmp_path / 'bad.sqlite', tmp_path / 'backup.sqlite'
    target.write_bytes(b'existing verified backup')
    with sqlite3.connect(source) as db:
        db.executescript('CREATE TABLE seasons(id INTEGER PRIMARY KEY);'
                        'CREATE TABLE signups(id INTEGER PRIMARY KEY, season INTEGER REFERENCES seasons(id));'
                        'INSERT INTO signups VALUES(1,999);')
    with pytest.raises(RuntimeError, match='foreign-key'):
        backup.snapshot(source, target)
    assert target.read_bytes() == b'existing verified backup'
    assert not target.with_suffix('.pending').exists()


def test_failed_tool_log_survives_success_and_stays_private(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(backup, 'STATE', tmp_path)
    def fail(args, **kwargs):
        kwargs['stderr'].write('private diagnostic')
        return subprocess.CompletedProcess(args, 1, stdout='private stdout')
    monkeypatch.setattr(backup.subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='private diagnostics') as error:
        backup.command(['mongodump'], capture=True)
    assert 'private diagnostic' not in str(error.value).replace('private diagnostics', '')
    files = list((tmp_path/'tool-failures').glob('*.log'))
    assert len(files) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert 'private stdout' in files[0].read_text()
    monkeypatch.setattr(backup.subprocess, 'run', lambda args, **kwargs: subprocess.CompletedProcess(args,0,stdout='ok'))
    assert backup.command(['restic'], capture=True) == 'ok'
    assert list((tmp_path/'tool-failures').glob('*.log')) == files


def test_timeout_retains_private_diagnostics(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(backup, 'STATE', tmp_path)
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args,1800)
    monkeypatch.setattr(backup.subprocess, 'run', timeout)
    with pytest.raises(RuntimeError, match='private diagnostics'):
        backup.command(['mongodump'])
    assert 'TimeoutExpired' in next((tmp_path/'tool-failures').glob('*.log')).read_text()


@pytest.mark.parametrize('failures',[1,3])
def test_dump_retries_without_partial_database(tmp_path,monkeypatch,failures):
    output=tmp_path/'dump';calls=[]
    def command(args):
        calls.append(args)
        assert not (output/'settings'/'partial').exists()
        if len(calls)<=failures:
            (output/'settings').mkdir(parents=True,exist_ok=True)
            (output/'settings'/'partial').write_text('partial')
            raise RuntimeError('network failed')
    monkeypatch.setattr(backup,'command',command)
    monkeypatch.setattr(backup.time,'sleep',lambda _:None)
    if failures==3:
        with pytest.raises(RuntimeError):backup.dump_database(tmp_path/'config','settings',output)
    else:backup.dump_database(tmp_path/'config','settings',output)
    assert len(calls)==min(failures+1,3)


@pytest.fixture
def artwork(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    images = SimpleNamespace(capture=lambda *args: 1, verify=lambda *args: 1)
    monkeypatch.setitem(sys.modules, 'command_images', images)
    monkeypatch.setattr(backup, 'STATE', tmp_path)
    sleeps = []
    monkeypatch.setattr(backup.time, 'sleep', sleeps.append)
    return images, sleeps


def s3_error(code='InternalError', status=500):
    from botocore.exceptions import ClientError
    return ClientError({'Error': {'Code': code, 'Message': 'secret-fixture-credential'},
                        'ResponseMetadata': {'HTTPStatusCode': status},
                        'private': 'secret-fixture-credential'}, 'GetObject')


def test_artwork_transient_then_success(tmp_path, monkeypatch, artwork, capsys):
    images, sleeps = artwork
    calls = []
    def capture(*args):
        calls.append(args)
        if len(calls) == 1:
            raise s3_error()
        return 7
    monkeypatch.setattr(images, 'capture', capture)
    result = backup.protect_artwork(tmp_path)
    assert len(calls) == 2 and sleeps == [10]
    assert datetime_from(result['artwork_success']).utcoffset().total_seconds() == 0
    assert result['artwork_failing_since'] is None and result['artwork_error'] is None
    assert 'Dashboard artwork protected: 7 images' in capsys.readouterr().out


def datetime_from(value):
    from datetime import datetime
    return datetime.fromisoformat(value)


def test_artwork_exhaustion_keeps_first_streak_and_safe_warning(tmp_path, monkeypatch, artwork, capsys):
    images, sleeps = artwork
    calls = []
    def capture(*args):
        calls.append(args)
        raise s3_error()
    monkeypatch.setattr(images, 'capture', capture)
    monkeypatch.setattr(images, 'verify', lambda stage: 79)
    first = backup.protect_artwork(tmp_path)
    backup.status('cwl', **first)
    second = backup.protect_artwork(tmp_path)
    assert len(calls) == 6 and sleeps == [10, 30, 10, 30]
    assert first == second
    assert first['artwork_error'] == 'ClientError:InternalError'
    lines = capsys.readouterr().out.splitlines()
    assert lines == ['Dashboard artwork skipped after 3 tries (ClientError:InternalError); previous copy kept: 79 images'] * 2
    assert 'secret-fixture-credential' not in '\n'.join(lines)


@pytest.mark.parametrize('error', [s3_error('AccessDenied', 403), RuntimeError('Dashboard artwork exceeds backup size limit')])
def test_artwork_nontransient_skips_without_retry(tmp_path, monkeypatch, artwork, error):
    images, sleeps = artwork
    calls = []
    def capture(*args):
        calls.append(args)
        raise error
    monkeypatch.setattr(images, 'capture', capture)
    assert backup.protect_artwork(tmp_path)['artwork_error'].startswith(type(error).__name__)
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize('error', [OSError('disk full'), KeyError('R2_FIXTURE'), TypeError('fixture bug')])
def test_artwork_nonboto_errors_raise_without_skip(tmp_path, monkeypatch, artwork, capsys, error):
    images, sleeps = artwork
    def capture(*args):
        raise error
    monkeypatch.setattr(images, 'capture', capture)
    monkeypatch.setattr(images, 'verify', lambda *args: pytest.fail('must not verify as skip'))
    with pytest.raises(type(error)):
        backup.protect_artwork(tmp_path)
    assert sleeps == [] and capsys.readouterr().out == ''


@pytest.mark.parametrize('error', [s3_error('PreconditionFailed', 412), RuntimeError('Dashboard artwork changed during backup')])
def test_artwork_precondition_and_changed_retry(tmp_path, monkeypatch, artwork, error):
    images, sleeps = artwork
    calls = []
    def capture(*args):
        calls.append(args)
        if len(calls) == 1:
            raise error
        return 1
    monkeypatch.setattr(images, 'capture', capture)
    assert backup.protect_artwork(tmp_path)['artwork_error'] is None
    assert len(calls) == 2 and sleeps == [10]


@pytest.mark.parametrize('name,kwargs', [
    ('EndpointConnectionError', {'endpoint_url': 'https://fixture.invalid'}),
    ('ConnectTimeoutError', {'endpoint_url': 'https://fixture.invalid'}),
    ('ReadTimeoutError', {'endpoint_url': 'https://fixture.invalid'}),
    ('ConnectionClosedError', {'endpoint_url': 'https://fixture.invalid'}),
    ('ResponseStreamingError', {'error': 'fixture'}),
    ('IncompleteReadError', {'actual_bytes': 1, 'expected_bytes': 3}),
])
def test_artwork_botocore_transient_base_classes(tmp_path, monkeypatch, artwork, name, kwargs):
    import botocore.exceptions
    images, sleeps = artwork
    calls = []
    def capture(*args):
        calls.append(args)
        if len(calls) == 1:
            raise getattr(botocore.exceptions, name)(**kwargs)
        return 1
    monkeypatch.setattr(images, 'capture', capture)
    assert backup.protect_artwork(tmp_path)['artwork_error'] is None
    assert len(calls) == 2 and sleeps == [10]


def test_skip_verifies_before_warning_and_raises_corruption(tmp_path, monkeypatch, artwork, capsys):
    images, sleeps = artwork
    def capture(*args):
        raise s3_error('AccessDenied', 403)
    def verify(*args):
        raise RuntimeError('Restored dashboard artwork checksum mismatch')
    monkeypatch.setattr(images, 'capture', capture)
    monkeypatch.setattr(images, 'verify', verify)
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        backup.protect_artwork(tmp_path)
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('skipped', [False, True])
def test_cwl_backup_persists_artwork_status_only_after_restic(tmp_path, monkeypatch, artwork, skipped):
    images, sleeps = artwork
    root = tmp_path / 'repo'
    home = tmp_path / 'home'
    config = tmp_path / 'config'
    (root / '.local').mkdir(parents=True)
    (home / '.config/systemd/user').mkdir(parents=True)
    config.mkdir()
    (config / 'r2-enabled').touch()
    source = root / 'fixture.sqlite'
    with sqlite3.connect(source) as db:
        db.executescript('CREATE TABLE seasons(id INTEGER); CREATE TABLE signups(id INTEGER); INSERT INTO seasons VALUES(1);')
    env_file = root / '.local/cwl-web.env'
    env_file.write_text('CWL_WEB_DB_PATH=' + str(source) + '\n')
    monkeypatch.setattr(backup, 'ROOT', root)
    monkeypatch.setattr(backup, 'HOME', home)
    monkeypatch.setattr(backup, 'CONFIG', config)
    monkeypatch.setattr(backup.os.path, 'ismount', lambda _: True)
    if skipped:
        def fail(*args):
            raise s3_error('AccessDenied', 403)
        monkeypatch.setattr(images, 'capture', fail)
    calls = []
    def restic(*args, **kwargs):
        assert not (tmp_path / 'cwl-status.json').exists()
        calls.append(('restic', args))
    def command(*args, **kwargs):
        assert (tmp_path / 'cwl-status.json').exists()
        calls.append(('remote', args))
    monkeypatch.setattr(backup, 'restic', restic)
    monkeypatch.setattr(backup, 'restic_env', lambda remote: {})
    monkeypatch.setattr(backup, 'command', command)
    backup.backup('cwl')
    import json
    status = json.loads((tmp_path / 'cwl-status.json').read_text())
    assert status['local_success'] and status['remote_success']
    assert bool(status['artwork_error']) is skipped
    assert bool(status['artwork_failing_since']) is skipped
    assert ('artwork_success' in status) is not skipped
    assert calls[0][0] == 'restic' and calls[1][0] == 'remote'
    assert calls[0][1][:5] == ('backup', '--tag', 'cwl', '--host', 'wu-cwl')
    stage = tmp_path / 'cwl'
    assert (stage / 'cwl-web.env').read_bytes() == env_file.read_bytes()
    assert backup.sqlite_check(stage / 'cwl.sqlite') == backup.sqlite_check(source)
    assert (stage / 'manifest.json').is_file()


@pytest.mark.parametrize('name,kwargs', [
    ('ResponseStreamingError', {'error': 'fixture'}),
    ('IncompleteReadError', {'actual_bytes': 1, 'expected_bytes': 3}),
])
def test_body_read_failure_retries_real_capture_and_kept_copy_verifies(tmp_path, monkeypatch, name, kwargs):
    import io
    import sys
    import botocore.exceptions
    from types import SimpleNamespace as NS
    spec = importlib.util.spec_from_file_location('fixture_images', Path(__file__).parents[1] / 'tools/backup/command_images.py')
    images = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(images)
    calls = []
    closed = []
    class BrokenBody:
        def read(self, size):
            raise getattr(botocore.exceptions, name)(**kwargs)
        def close(self):
            closed.append(True)
    def get(**kwargs):
        calls.append(kwargs)
        return {'Body': BrokenBody() if len(calls) == 1 else io.BytesIO(b'new')}
    client = NS(get_paginator=lambda _: NS(paginate=lambda **kw: [{'Contents': [
        {'Key': 'clans/image.png', 'ETag': 'v2', 'Size': 3}]}]), get_object=get)
    capture = images.capture
    images.capture = lambda root, stage: capture(root, stage, client, 'fixture')
    monkeypatch.setitem(sys.modules, 'command_images', images)
    monkeypatch.setattr(backup, 'STATE', tmp_path)
    sleeps = []
    monkeypatch.setattr(backup.time, 'sleep', sleeps.append)
    result = backup.protect_artwork(tmp_path)
    assert result['artwork_error'] is None
    assert len(calls) == 2 and sleeps == [10] and closed == [True]
    assert images.verify(tmp_path) == 1


def test_skipped_real_capture_preserves_and_verifies_previous_copy(tmp_path, monkeypatch, capsys):
    import io
    import sys
    from types import SimpleNamespace as NS
    spec = importlib.util.spec_from_file_location('fixture_images', Path(__file__).parents[1] / 'tools/backup/command_images.py')
    images = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(images)
    client = NS(get_paginator=lambda _: NS(paginate=lambda **kw: [{'Contents': [
        {'Key': 'clans/image.png', 'ETag': 'v1', 'Size': 3}]}]),
        get_object=lambda **kw: {'Body': io.BytesIO(b'old')})
    assert images.capture(tmp_path, tmp_path, client, 'fixture') == 1
    before = {path.name: path.read_bytes() for path in (tmp_path / 'command-images').iterdir()}
    def pages(**kwargs):
        raise s3_error('AccessDenied', 403)
    client.get_paginator = lambda _: NS(paginate=pages)
    capture = images.capture
    images.capture = lambda root, stage: capture(root, stage, client, 'fixture')
    monkeypatch.setitem(sys.modules, 'command_images', images)
    monkeypatch.setattr(backup, 'STATE', tmp_path)
    monkeypatch.setattr(backup.time, 'sleep', lambda _: pytest.fail('no nontransient retry'))
    assert backup.protect_artwork(tmp_path)['artwork_error'] == 'ClientError:AccessDenied'
    assert images.verify(tmp_path) == 1
    assert {path.name: path.read_bytes() for path in (tmp_path / 'command-images').iterdir()} == before
    assert 'previous copy kept: 1 images' in capsys.readouterr().out


def test_restic_failure_does_not_persist_new_artwork_status(tmp_path, monkeypatch, artwork):
    images, sleeps = artwork
    root = tmp_path / 'repo'
    home = tmp_path / 'home'
    (root / '.local').mkdir(parents=True)
    (home / '.config/systemd/user').mkdir(parents=True)
    env_file = root / '.local/cwl-web.env'
    env_file.write_text('CWL_WEB_DB_PATH=' + str(root / 'fixture.sqlite') + '\n')
    monkeypatch.setattr(backup, 'ROOT', root)
    monkeypatch.setattr(backup, 'HOME', home)
    monkeypatch.setattr(backup, 'CONFIG', tmp_path / 'config')
    monkeypatch.setattr(backup.os.path, 'ismount', lambda _: True)
    def snapshot(source, target):
        target.write_bytes(b'fixture snapshot')
        return {'seasons': 1, 'signups': 0}
    monkeypatch.setattr(backup, 'snapshot', snapshot)
    def restic(*args, **kwargs):
        raise RuntimeError('fixture Restic failure')
    monkeypatch.setattr(backup, 'restic', restic)
    with pytest.raises(RuntimeError, match='Restic failure'):
        backup.backup('cwl')
    assert not (tmp_path / 'cwl-status.json').exists()



def test_manifest_disk_failure_cannot_be_skipped_as_provider_failure(tmp_path, monkeypatch, capsys):
    import sys
    import traceback
    from types import SimpleNamespace as NS
    spec = importlib.util.spec_from_file_location('fixture_images', Path(__file__).parents[1] / 'tools/backup/command_images.py')
    images = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(images)
    first_error = s3_error('AccessDenied', 403)
    def pages(**kwargs):
        raise first_error
    client = NS(get_paginator=lambda _: NS(paginate=pages))
    capture = images.capture
    images.capture = lambda root, stage: capture(root, stage, client, 'fixture')
    original_write = Path.write_text
    def write(path, *args, **kwargs):
        if path.name == 'manifest.pending':
            raise OSError('fixture disk full')
        return original_write(path, *args, **kwargs)
    root = tmp_path / 'repo'
    (root / '.local').mkdir(parents=True)
    env_file = root / '.local/cwl-web.env'
    env_file.write_text('CWL_WEB_DB_PATH=' + str(root / 'fixture.sqlite') + '\n')
    def snapshot(source, target):
        target.write_bytes(b'fixture snapshot')
        return {'seasons': 1, 'signups': 0}
    monkeypatch.setattr(backup, 'ROOT', root)
    monkeypatch.setattr(backup, 'snapshot', snapshot)
    monkeypatch.setattr(backup.os.path, 'ismount', lambda _: True)
    monkeypatch.setattr(Path, 'write_text', write)
    monkeypatch.setitem(sys.modules, 'command_images', images)
    monkeypatch.setattr(backup, 'STATE', tmp_path)
    monkeypatch.setattr(backup.time, 'sleep', lambda _: pytest.fail('local failure must not retry'))
    monkeypatch.setattr(backup, 'restic', lambda *args, **kwargs: pytest.fail('local failure must stop before Restic'))
    with pytest.raises(RuntimeError, match='manifest persistence failed') as raised:
        backup.backup('cwl')
    assert raised.value.capture_error is first_error
    assert isinstance(first_error.__cause__, OSError)
    assert first_error.response['Error']['Message'] == 'secret-fixture-credential'
    rendered = ''.join(traceback.format_exception(raised.value))
    assert 'secret-fixture-credential' not in rendered
    assert 'fixture disk full' not in rendered
    assert raised.value.__suppress_context__
    assert capsys.readouterr().out == ''
    assert not (tmp_path / 'cwl-status.json').exists()


@pytest.mark.parametrize('code', [
    'https://example.invalid/key-secret-token',
    'InternalError\nsecret-fixture-credential',
    {'secret': 'fixture-credential'},
])
def test_unknown_provider_code_cannot_leak_into_warning_or_status(tmp_path, monkeypatch, artwork, capsys, code):
    images, sleeps = artwork
    def capture(*args):
        raise s3_error(code, 403)
    monkeypatch.setattr(images, 'capture', capture)
    result = backup.protect_artwork(tmp_path)
    backup.status('cwl', **result)
    assert result['artwork_error'] == 'ClientError:UnknownCode'
    assert capsys.readouterr().out == (
        'Dashboard artwork skipped after 1 tries (ClientError:UnknownCode); previous copy kept: 1 images\n')
    assert 'secret' not in (tmp_path / 'cwl-status.json').read_text()

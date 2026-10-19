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

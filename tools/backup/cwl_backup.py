"""SQLite online snapshots + official MongoDB tools + encrypted Restic repositories.

No production restore operation is provided. Run with the project's Python.
Secrets are read from private files and never placed in subprocess arguments.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
STATE = HOME / '.local/state/wu-backup'
CONFIG = HOME / '.config/wu-backup'
REPO = HOME / '.local/share/wu-backup/restic'
RESTIC = HOME / '.local/bin/restic'
MONGO_TOOLS = HOME / '.local/opt/wu-backup-tools'


def sqlite_check(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('SQLite integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('SQLite foreign-key check failed')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if 'seasons' not in tables or 'signups' not in tables:
            raise RuntimeError('Expected CWL tables missing')
        return {t: db.execute('SELECT COUNT(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}


def snapshot(source, target):
    """Read-only source URI prevents missing files becoming empty databases."""
    if not source.is_file() or source.stat().st_size == 0:
        raise RuntimeError('Live SQLite database missing or empty; refusing backup')
    temporary = target.with_suffix('.pending')
    try:
        with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(temporary) as dst:
                src.backup(dst, pages=256, sleep=0.05)
        counts = sqlite_check(temporary)
        os.replace(temporary, target)
        return counts
    finally:
        temporary.unlink(missing_ok=True)


def command(args, env=None, capture=False):
    # Each command owns its output; failed output survives later successful jobs.
    # Raw diagnostics can contain credentials, so never print them to the journal.
    logs = STATE / 'tool-failures'
    logs.mkdir(mode=0o700, exist_ok=True)
    os.chmod(logs, 0o700)
    tool = Path(args[0]).name
    fd, path = tempfile.mkstemp(prefix=tool + '-', suffix='.log', dir=logs)
    log = Path(path)
    failed = False
    try:
        with os.fdopen(fd, 'w') as out:
            try:
                result = subprocess.run([str(a) for a in args], env=env,
                                        stdout=subprocess.PIPE if capture else out,
                                        stderr=out, text=True, timeout=1800)
            except (subprocess.TimeoutExpired, OSError) as exc:
                failed = True
                out.write('\nCommand ended: ' + type(exc).__name__ + '\n')
                raise RuntimeError(f'{tool} failed; private diagnostics: {log.name}') from None
            if result.returncode:
                failed = True
                if capture and result.stdout:
                    out.write(result.stdout)
        if failed:
            raise RuntimeError(f'{tool} failed (exit {result.returncode}); private diagnostics: {log.name}')
        return result.stdout if capture else None
    finally:
        if not failed:
            log.unlink(missing_ok=True)
        # Bound private diagnostic retention to the latest 100 failures.
        old = sorted(logs.glob('*.log'), key=lambda item: item.stat().st_mtime, reverse=True)
        for item in old[100:]:
            item.unlink(missing_ok=True)


def dump_database(credentials, name, output):
    """Retry a failed logical dump in fresh staging; never publish a partial dump."""
    for attempt in range(3):
        try:
            command([MONGO_TOOLS / 'mongodump', '--config', credentials, '--db', name,
                     '--gzip', '--out', output])
            return
        except RuntimeError:
            if attempt == 2:
                raise
            shutil.rmtree(output / name, ignore_errors=True)
            print('Mongo dump retry after temporary failure', flush=True)
            time.sleep((2, 5)[attempt])


def restic_env(remote=False):
    env = os.environ.copy()
    # Do not inherit a shell's unrelated Restic repository or credentials.
    for name in list(env):
        if name.startswith(('RESTIC_', 'AWS_')):
            env.pop(name)
    env.update(RESTIC_REPOSITORY=str(REPO), RESTIC_PASSWORD_FILE=str(CONFIG / 'password'))
    if remote:
        values = dotenv_values(ROOT / '.local/cwl-backup-r2.env')
        main = dotenv_values(ROOT / '.env')
        for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'):
            if not values.get(key):
                raise RuntimeError('Private R2 backup credentials are not configured')
            env[key] = values[key]
        env['AWS_DEFAULT_REGION'] = 'auto'
        env['RESTIC_REPOSITORY'] = f"s3:https://{main['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com/wu-private-backups/restic"
    return env


def restic(*args, remote=False, capture=False):
    return command([RESTIC, *args], env=restic_env(remote), capture=capture)


def status(kind, **fields):
    path = STATE / (kind + '-status.json')
    old = json.loads(path.read_text()) if path.exists() else {}
    old.update(fields)
    tmp = path.with_suffix('.pending')
    tmp.write_text(json.dumps(old, indent=2) + '\n')
    os.replace(tmp, path)


def backup(kind):
    if not os.path.ismount('/nvme0n1-disk'):
        raise RuntimeError('Production volume is not mounted')
    stage = STATE / kind
    stage.mkdir(mode=0o700, exist_ok=True)
    if kind == 'cwl':
        web_env = ROOT / '.local/cwl-web.env'
        source = Path(dotenv_values(web_env)['CWL_WEB_DB_PATH'])
        counts = snapshot(source, stage / 'cwl.sqlite')
        from command_images import capture
        print(f'Dashboard artwork protected: {capture(ROOT,stage)} images',flush=True)
        manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'counts': counts,
                    'sha256': hashlib.sha256((stage / 'cwl.sqlite').read_bytes()).hexdigest()}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        shutil.copy2(web_env, stage / 'cwl-web.env')
        # Preserve the VAPID identity so restored phone subscriptions still work.
        push_key = dotenv_values(web_env).get('CWL_PUSH_VAPID_PRIVATE_KEY')
        if push_key:
            shutil.copy2(Path(push_key), stage / 'push-vapid-private.pem')
        else:
            (stage / 'push-vapid-private.pem').unlink(missing_ok=True)
        for name in ('cwl-backup-alerts.env', 'cwl-backup-r2.env'):
            source_config = ROOT / '.local' / name
            if source_config.exists():
                shutil.copy2(source_config, stage / name)
            else:
                (stage / name).unlink(missing_ok=True)
        shutil.copytree(HOME / '.config/systemd/user', stage / 'systemd-user', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('*.wants'))
        paths = [stage, ROOT, CONFIG]
    else:
        from pymongo import MongoClient
        uri = dotenv_values(ROOT / '.env')['MONGODB_URI']
        with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
            names = sorted(n for n in client.list_database_names() if n not in {'admin', 'local', 'config'})
        if not {'settings', 'database'}.issubset(names):
            raise RuntimeError('Expected production Mongo databases missing')
        # Fresh directory avoids retaining dropped collections in later dumps.
        with tempfile.TemporaryDirectory(dir=STATE, prefix='mongo-') as temporary:
            tmp = Path(temporary)
            credentials = tmp / 'config.yml'
            credentials.write_text(json.dumps({'uri': uri}))
            for name in names:
                dump_database(credentials, name, tmp / 'dump')
            if (stage / 'dump').exists():
                shutil.rmtree(stage / 'dump')
            shutil.move(str(tmp / 'dump'), stage / 'dump')
        (stage / 'manifest.json').write_text(json.dumps({'databases': names,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'consistency': 'Logical collection backups; not a cross-database point-in-time snapshot.'}, indent=2))
        paths = [stage]
    excludes = ['.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', str(ROOT / '.local'), str(ROOT / '.local-backups'), '*.log']
    arguments = ['backup', '--tag', kind, '--host', 'wu-cwl', *map(str, paths)]
    for pattern in excludes:
        arguments += ['--exclude', pattern]
    restic(*arguments)
    status(kind, local_success=datetime.now(timezone.utc).isoformat())
    if (CONFIG / 'r2-enabled').exists():
        # Copy the already committed snapshot: local/off-site copies are identical.
        remote_env = restic_env(True)
        remote_env['RESTIC_FROM_REPOSITORY'] = str(REPO)
        remote_env['RESTIC_FROM_PASSWORD_FILE'] = str(CONFIG / 'password')
        # Catch up retained snapshots after outages; Restic skips existing copies.
        command([RESTIC, 'copy', '--tag', kind, '--host', 'wu-cwl'], env=remote_env)
        status(kind, remote_success=datetime.now(timezone.utc).isoformat())
    else:
        print('Off-site backup pending private R2 credentials', flush=True)
    print(kind + ' encrypted backup complete', flush=True)


def verify(remote=False):
    restic('check', '--read-data', remote=remote)
    snapshots = json.loads(restic('snapshots', '--tag', 'cwl', '--latest', '1', '--json', remote=remote, capture=True))
    if not snapshots:
        raise RuntimeError('No CWL snapshot available for recovery check')
    with tempfile.TemporaryDirectory(dir=STATE, prefix='restore-test-') as tmp:
        stage = STATE / 'cwl'
        restic('restore', snapshots[0]['id'] + ':' + str(stage), '--target', tmp, remote=remote)
        recovered = Path(tmp)
        manifest = json.loads((recovered / 'manifest.json').read_text())
        database = recovered / 'cwl.sqlite'
        if hashlib.sha256(database.read_bytes()).hexdigest() != manifest['sha256']:
            raise RuntimeError('Restored database checksum mismatch')
        from command_images import verify as verify_images
        print(f'Restored dashboard artwork verified: {verify_images(recovered)} images',flush=True)
        if sqlite_check(database) != manifest['counts']:
            raise RuntimeError('Restored table counts mismatch')
    mongo_snapshots = json.loads(restic('snapshots', '--tag', 'mongo', '--latest', '1', '--json', remote=remote, capture=True))
    if not mongo_snapshots:
        raise RuntimeError('No Mongo snapshot available for recovery check')
    with tempfile.TemporaryDirectory(dir=STATE, prefix='mongo-restore-test-') as tmp:
        from verify_mongo import verify_dump
        stage = STATE / 'mongo'
        restic('restore', mongo_snapshots[0]['id'] + ':' + str(stage), '--target', tmp, remote=remote)
        recovered = Path(tmp)
        result = verify_dump(recovered / 'dump', Path(tmp) / 'scratch', MONGO_TOOLS, command)
        print(f"Mongo restore verified: {result['collections']} collections, {result['documents']} documents", flush=True)
    status('verification', **{('remote_success' if remote else 'local_success'): datetime.now(timezone.utc).isoformat()})
    print('Full repository check and isolated SQLite/Mongo restores verified', flush=True)


def maintain():
    # Never prune before establishing a verified recovery point.
    verify()
    for remote in [False, True] if (CONFIG / 'r2-enabled').exists() else [False]:
        if remote:
            verify(True)
        for kind in ('cwl', 'mongo'):
            restic('forget', '--tag', kind, '--group-by', 'host,tags', '--keep-within', '2d',
                   '--keep-hourly', '48', '--keep-daily', '30', '--keep-weekly', '12',
                   '--keep-monthly', '12', '--prune', remote=remote)
        restic('check', remote=remote)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['cwl', 'mongo', 'verify', 'maintain', 'init-r2'])
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action in ('cwl', 'mongo'):
            backup(args.action)
        elif args.action == 'verify':
            verify()
        elif args.action == 'maintain':
            maintain()
        else:
            restic('init', '--copy-chunker-params', '--from-repo', str(REPO),
                   '--from-password-file', str(CONFIG / 'password'), remote=True)
            (CONFIG / 'r2-enabled').write_text('wu-private-backups\n')


if __name__ == '__main__':
    main()

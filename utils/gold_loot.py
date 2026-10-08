"""Persistent battle-loot leaderboard for Warriors United’s starting roster."""
import argparse
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CLAN = '#2YRVY8YCP'
DEFAULT_DB = ROOT / '.local/gold-loot.sqlite3'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA synchronous=FULL")
    db.executescript('''
        CREATE TABLE IF NOT EXISTS loot_events (
            tag TEXT NOT NULL, battle_time TEXT NOT NULL, mode TEXT NOT NULL,
            gold INTEGER NOT NULL CHECK (gold >= 0),
            PRIMARY KEY (tag, battle_time, mode)
        );
        CREATE TABLE IF NOT EXISTS session (clan TEXT PRIMARY KEY, name TEXT, started TEXT);
        CREATE TABLE IF NOT EXISTS players (
            tag TEXT PRIMARY KEY, name TEXT NOT NULL, baseline INTEGER NOT NULL,
            latest INTEGER NOT NULL, baseline_at TEXT NOT NULL, updated TEXT NOT NULL
        );
    ''')
    return db


def backup_database(db):
    """Keep the original baseline and an atomic latest snapshot outside checkout."""
    source = Path(db.execute('PRAGMA database_list').fetchone()[2])
    directory = (Path.home() / '.local/state/wu-bot/gold-loot-backups'
                 if source.resolve() == DEFAULT_DB.resolve()
                 else source.parent / (source.name + '.backups'))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Never back up an empty session or replace the first recovery baseline.
    if not db.execute('SELECT 1 FROM session').fetchone():
        return
    fd, temporary = tempfile.mkstemp(prefix='.snapshot-', dir=directory)
    os.close(fd)
    try:
        with sqlite3.connect(temporary) as destination:
            db.backup(destination)
            if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('Gold-loot backup integrity check failed')
        with open(temporary, 'rb') as snapshot:
            os.fsync(snapshot.fileno())
        # Atomic no-overwrite creation, even if two processes refresh together.
        try:
            os.link(temporary, directory / 'baseline.sqlite3')
        except FileExistsError:
            pass
        os.replace(temporary, directory / 'latest.sqlite3')
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def gold(player):
    for achievement in player.get('achievements', []):
        if achievement.get('name') == 'Gold Grab':
            value = achievement.get('value')
            if type(value) is int and value >= 0:
                return value
    raise ValueError('Gold Grab counter is missing or invalid')


def save_sample(db, player, timestamp):
    value = gold(player)
    row = db.execute('SELECT latest FROM players WHERE tag=?', (player['tag'],)).fetchone()
    if row is None:
        raise ValueError('Player is outside the starting roster')
    if value < row['latest']:
        raise ValueError('Gold Grab decreased; keeping the previous sample')
    db.execute('UPDATE players SET name=?, latest=?, updated=? WHERE tag=?',
               (player['name'], value, timestamp, player['tag']))


RANKING_SQL = """SELECT p.*, COALESCE(e.looted, 0) AS looted FROM players p
    LEFT JOIN (SELECT tag, SUM(gold) AS looted FROM loot_events GROUP BY tag) e
    ON e.tag=p.tag ORDER BY looted DESC, p.tag ASC LIMIT 10"""


def save_battles(db, tag, items, timestamp):
    """Validate a full response before storing; retries never double count loot."""
    row = db.execute('SELECT baseline_at FROM players WHERE tag=?', (tag,)).fetchone()
    if row is None or not isinstance(items, list):
        raise ValueError('Invalid battle history response')
    began = datetime.fromisoformat(row['baseline_at'])
    records = []
    for item in items:
        mode = item.get('battleMode')
        if mode not in ('farming', 'ranked', 'legend'):
            raise ValueError('Unknown battle mode')
        moment = datetime.fromisoformat(item['battleTime'].replace('Z', '+00:00'))
        amount = item.get('lootedResources', {}).get('gold')
        if type(amount) is not int or amount < 0:
            raise ValueError('Invalid battle gold amount')
        if moment >= began:
            records.append((tag, moment.astimezone(timezone.utc).isoformat(), mode, amount))
    db.executemany("""INSERT INTO loot_events VALUES (?, ?, ?, ?)
        ON CONFLICT(tag, battle_time, mode) DO UPDATE SET gold=excluded.gold""", records)
    db.execute('UPDATE players SET updated=? WHERE tag=?', (timestamp, tag))


async def collect_battles(db, *, display=True):
    """ClashKing returns observed farming, ranked and legend attacks, not defenses."""
    rows = db.execute('SELECT tag,baseline_at FROM players').fetchall()
    if not db.execute('SELECT 1 FROM session').fetchone():
        raise ValueError('No baseline yet. Run start first.')
    semaphore = asyncio.Semaphore(5)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:
        async def sample(row):
            async with semaphore:
                url = 'https://api.clashk.ing/v2/player/' + row['tag'].replace('#', '%23') + '/battlelog/history'
                async with http.get(url, params={'time[after]': row['baseline_at']}) as response:
                    if response.status != 200:
                        raise ValueError(f'Battle history HTTP {response.status}')
                    data = await response.json()
                    return data['items'], now()
        results = await asyncio.gather(*(sample(row) for row in rows), return_exceptions=True)
    failures = 0
    with db:
        db.execute('BEGIN IMMEDIATE')
        for row, result in zip(rows, results):
            try:
                if isinstance(result, Exception):
                    raise ValueError('Battle history unavailable') from result
                save_battles(db, row['tag'], *result)
            except (ValueError, KeyError, TypeError):
                failures += 1
    backup_database(db)
    if display:
        leaderboard(db)
        if failures:
            print(f'WARNING: {failures} players could not refresh; saved battle totals retained.')
    return failures


def leaderboard(db):
    session = db.execute('SELECT * FROM session').fetchone()
    if session is None:
        raise ValueError('No baseline yet. Run start first.')
    rows = db.execute(RANKING_SQL).fetchall()
    print(f"\n{session['name']} — TOP 10 GOLD LOOTERS", flush=True)
    print(f"Starting roster | Baseline capture began {session['started']}")
    print('Recorded farming, ranked and legend gold • ClashKing. Timestamps are UTC.')
    print(f"{'Rank':<5} {'Player':<24} {'Tag':<14} {'Gold looted':>15}  Last sample")
    for index, row in enumerate(rows, 1):
        name = ''.join(c for c in row['name'] if c.isprintable())[:24]
        print(f"{index:<5} {name:<24} {row['tag']:<14} {row['looted']:>15,}  {row['updated']}")
    stats = db.execute('SELECT count(*), min(updated), max(updated) FROM players').fetchone()
    print(f'Tracking {stats[0]} players. Sample range: {stats[1]} to {stats[2]}', flush=True)


async def collect(db, command, *, display=True):
    if command != 'start':
        return await collect_battles(db, display=display)
    load_dotenv(ROOT / '.env')
    token = os.getenv('COC_API_TOKEN', '').strip()
    if not token:
        raise ValueError('COC_API_TOKEN is not configured')
    semaphore = asyncio.Semaphore(5)
    async with aiohttp.ClientSession(
        headers={'Authorization': f'Bearer {token}'},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as http:
        async def get(kind, tag):
            async with semaphore:
                url = f"https://api.clashofclans.com/v1/{kind}/{tag.replace('#', '%23')}"
                async with http.get(url) as response:
                    if response.status != 200:
                        raise ValueError(f'{tag}: official API HTTP {response.status}')
                    return await response.json()

        starting = command == 'start'
        if starting:
            if db.execute('SELECT 1 FROM session').fetchone():
                raise ValueError('Baseline already exists; use refresh or watch. Use --db for a separate test.')
            began = now()
            clan = await get('clans', CLAN)
            tags = [member['tag'] for member in clan['memberList']]
            if not tags:
                raise ValueError('Clan roster is empty; no baseline created')
        else:
            if not db.execute('SELECT 1 FROM session').fetchone():
                raise ValueError('No baseline yet. Run start first.')
            tags = [row[0] for row in db.execute('SELECT tag FROM players')]

        async def sample(tag):
            player = await get('players', tag)
            gold(player)
            return player, now()

        results = await asyncio.gather(*(sample(tag) for tag in tags), return_exceptions=True)
        failures = 0
        if starting and any(isinstance(result, Exception) for result in results):
            for tag, result in zip(tags, results):
                if isinstance(result, Exception):
                    print(f'{tag}: {type(result).__name__}: {result}', file=sys.stderr)
            raise ValueError('Could not fetch every starting player; no baseline saved. Retry start.')
        with db:
            # Serialize writers before reading previous counters.
            db.execute("BEGIN IMMEDIATE")
            if starting:
                db.execute('INSERT INTO session VALUES (?, ?, ?)', (CLAN, clan['name'], began))
            for tag, result in zip(tags, results):
                if isinstance(result, Exception):
                    print(f'Skipped {tag}: {type(result).__name__}; previous sample retained', file=sys.stderr)
                    failures += 1
                    continue
                player, timestamp = result
                if starting:
                    value = gold(player)
                    db.execute('INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)',
                               (tag, player['name'], value, value, timestamp, timestamp))
                else:
                    try:
                        save_sample(db, player, timestamp)
                    except ValueError as error:
                        print(f'Skipped {tag}: {error}', file=sys.stderr)
                        failures += 1
        backup_database(db)
        if display:
            leaderboard(db)
        if failures and display:
            print(f'WARNING: {failures} players could not be refreshed; totals may be stale.', flush=True)
        return failures


def refresh_board(path=DEFAULT_DB):
    """Run in a worker thread: SQLite waits and HTTP do not block Discord."""
    if not path.is_file():
        raise ValueError('The gold-loot test has not been started on this bot host.')
    db = connect(path)
    try:
        if not db.execute('SELECT 1 FROM session').fetchone():
            raise ValueError('The gold-loot test has no saved baseline.')
        warning = None
        try:
            failures = asyncio.run(collect(db, 'refresh', display=False))
            if failures:
                warning = f'{failures} players could not refresh. Their last saved totals are shown.'
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            warning = 'Refresh unavailable. Showing the last saved totals.'
        session = dict(db.execute('SELECT * FROM session').fetchone())
        rows = [dict(row) for row in db.execute(
            RANKING_SQL
        )]
        stats = db.execute('SELECT count(*), min(updated), max(updated) FROM players').fetchone()
        return dict(session=session, rows=rows, count=stats[0], oldest=stats[1],
                    newest=stats[2], warning=warning)
    finally:
        db.close()


async def run(args):
    db = connect(args.db)
    try:
        if args.command == 'show':
            leaderboard(db)
            return 0
        if args.command != 'watch':
            return 1 if await collect(db, args.command) else 0
        if not db.execute('SELECT 1 FROM session').fetchone():
            raise ValueError('No baseline yet. Run start first.')
        while True:
            try:
                await collect(db, 'refresh')
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                print(f'Refresh failed ({type(error).__name__}); saved baseline retained.', flush=True)
            await asyncio.sleep(args.interval)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'show', 'refresh', 'watch'))
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--interval', type=int, default=300, help='Watch refresh seconds (minimum 60)')
    args = parser.parse_args()
    if args.interval < 60:
        parser.error('--interval must be at least 60 seconds')
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0
    except (ValueError, sqlite3.Error, aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

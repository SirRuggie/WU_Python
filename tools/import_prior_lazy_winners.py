"""One-time Lazy history import. Dry run is read-only; apply is atomic.

Use --fixture-players with a JSON tag/name map for isolated fixture work. Without
it, only the existing official Clash provider is used. Apply requires exclusive
ownership of the dashboard DB and its existing Mongo durable checkpoint lease;
stop the dashboard through the separately authorized maintenance procedure first.
Production dry runs and imports require the owner's explicit authorization.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cwl_web.providers import LiveProviders, ProviderUnavailable, TAG_RE
from cwl_web.participation_sync import bind_history_month, history_season_for_cycle
from cwl_web.store import Store
from utils.cwl_bonus_raffle_store import RaffleStore
from utils.cwl_dashboard_state import MongoDashboardState, database_lock


def read_rows(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != ['cycle', 'player_tag', 'pasted_name', 'clan_name', 'clan_tag']:
            raise ValueError('Expected cycle, player_tag, pasted_name, clan_name, clan_tag TSV columns')
        rows, seen, names = [], set(), {}
        for number, raw in enumerate(reader, 2):
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(f'Incomplete TSV row {number}')
            row = {key: value.strip() for key, value in raw.items()}
            row['player_tag'] = row['player_tag'].upper()
            row['clan_tag'] = row['clan_tag'].upper()
            if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', row['cycle']):
                raise ValueError(f'Invalid month on row {number}')
            if any(not TAG_RE.fullmatch(row[key]) for key in ('player_tag', 'clan_tag')):
                raise ValueError(f'Invalid Clash tag on row {number}')
            key = (row['cycle'], row['player_tag'])
            if key in seen:
                raise ValueError(f'Duplicate month and tag on row {number}')
            if not row['clan_name'] or (row['clan_tag'] in names and names[row['clan_tag']] != row['clan_name']):
                raise ValueError(f'Missing or inconsistent clan name on row {number}')
            names[row['clan_tag']] = row['clan_name']
            seen.add(key)
            rows.append(row)
    if not rows:
        raise ValueError('No winners in TSV')
    return rows


def _existing_seasons(db, rows):
    return {cycle: history_season_for_cycle(db, cycle) for cycle in sorted({row['cycle'] for row in rows})}


def _display(value):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(value))


def pool_conflict_message(conflicts):
    return '\n'.join(
        f"Pool conflict: {row['cycle']} · {_display(row['clan_name'])} ({row['clan_tag']}) · "
        f"existing pool: {_display(row['existing_pool']) if row['existing_pool'] is not None else 'unset'}. "
        "Set the existing rule to Lazy and rerun; nothing imported."
        for row in conflicts)


async def check_rows(db, rows, provider):
    """No writes and no private provider methods; failures other than 404 fence apply."""
    if db.in_transaction:
        raise ValueError('Player checks must run outside a database transaction')
    checked = []
    identities = {}
    for row in rows:
        value = row['player_tag']
        if value not in identities:
            try:
                identity = await provider.player(value)
            except KeyError:
                identity = None  # Fixture provider's not-found contract.
            except ProviderUnavailable as exc:
                if getattr(exc, 'status_code', None) != 404:
                    raise
                identity = None
            if identity is not None and (identity.get('tag') != value or
                    not isinstance(identity.get('name'), str) or not identity['name'].strip()):
                raise ValueError(f'Player lookup did not match {value}')
            identities[value] = identity
        identity = identities[value]
        imported = db.execute('SELECT 1 FROM bonus_imported_winners WHERE cycle=? AND player_tag=?',
                              (row['cycle'], value)).fetchone()
        clan_new = not db.execute('SELECT 1 FROM clans WHERE tag=?', (row['clan_tag'],)).fetchone()
        status = 'tag not found' if identity is None else 'already imported' if imported else 'new'
        checked.append({**row, 'player_name': identity['name'] if identity else '',
                        'missing': identity is None, 'status': status + (' / clan new' if clan_new else '')})
    conflicts = RaffleStore(db, None).import_pool_conflicts(checked, _existing_seasons(db, checked))
    by_clan = {(row['cycle'], row['clan_tag']): row for row in conflicts}
    for row in checked:
        row['pool_conflict'] = by_clan.get((row['cycle'], row['clan_tag']))
    return checked


def apply_checked(store, checked, actor, skip_missing=False):
    missing = [row for row in checked if row['missing']]
    if missing and not skip_missing:
        raise ValueError('Tag not found; nothing imported. Use --skip-missing to list and skip these rows')
    with store.tx() as db:
        # Recheck inside the transaction. Repeated imports must not reconstruct
        # hosting clans/rules removed or edited by staff since the first import.
        pending = [row for row in checked if not db.execute(
            'SELECT 1 FROM bonus_imported_winners WHERE cycle=? AND player_tag=?',
            (row['cycle'], row['player_tag'])).fetchone()]
        owner = RaffleStore(db, None)
        existing = _existing_seasons(db, pending)
        conflicts = owner.import_pool_conflicts(pending, existing)
        if conflicts:
            raise ValueError(pool_conflict_message(conflicts))
        rows = [row for row in pending if not row['missing']]
        seasons = owner.ensure_import_seasons(rows, existing)
        for cycle, sid in seasons.items():
            bind_history_month(db, sid, cycle, actor)
        added = owner.import_winners(rows, seasons, actor)
    return {'added': added, 'skipped': [(row['cycle'], row['player_tag']) for row in missing]}


def print_table(checked, output):
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(['month', 'clan', 'tag', 'pasted name', 'API name', 'status'])
    for row in checked:
        # Prevent external names adding terminal rows/control characters.
        writer.writerow([_display(row[key]) for key in
                         ('cycle', 'clan_name', 'player_tag', 'pasted_name', 'player_name', 'status')])
    conflicts = {(row['pool_conflict']['cycle'], row['pool_conflict']['clan_tag']): row['pool_conflict']
                 for row in checked if row.get('pool_conflict')}
    if conflicts:
        output.write(pool_conflict_message([conflicts[key] for key in sorted(conflicts)]) + '\n')


class FixturePlayers:
    def __init__(self, path):
        self.names = json.loads(Path(path).read_text(encoding='utf-8'))

    async def player(self, tag):
        return {'tag': tag, 'name': self.names[tag]}


async def run(args):
    rows = read_rows(args.tsv)
    provider = FixturePlayers(args.fixture_players) if args.fixture_players else LiveProviders()
    try:
        # Never initialize/migrate a database for a dry run.
        with sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None) as db:
            db.row_factory = sqlite3.Row
            checked = await check_rows(db, rows, provider)
        print_table(checked, sys.stdout)
        if not args.apply:
            print('Dry run: no writes.')
            return
        conflicts = {(row['pool_conflict']['cycle'], row['pool_conflict']['clan_tag']): row['pool_conflict']
                     for row in checked if row.get('pool_conflict')}
        if conflicts:
            raise ValueError(pool_conflict_message([conflicts[key] for key in sorted(conflicts)]))
        if any(row['missing'] for row in checked) and not args.skip_missing:
            raise ValueError('Tag not found; nothing imported. Use --skip-missing to skip')
        if not args.actor.strip():
            raise ValueError('--actor is required for --apply')
        durability = None
        with database_lock(args.database):
            try:
                if not args.fixture_players:
                    durability = MongoDashboardState.open(os.getenv('MONGODB_URI', ''))
                    durability.restore(args.database)
                store = Store(args.database, durability=durability)
                result = apply_checked(store, checked, args.actor, args.skip_missing)
                print(f"Imported: {result['added']}")
                for cycle, tag in result['skipped']:
                    print(f'Skipped: {cycle} {tag}')
            finally:
                if durability:
                    durability.close()
    finally:
        if isinstance(provider, LiveProviders):
            await provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tsv')
    parser.add_argument('--database', required=True, help='Explicit existing dashboard SQLite path')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--skip-missing', action='store_true')
    parser.add_argument('--actor', default='')
    parser.add_argument('--fixture-players', help='Isolated fixture JSON tag/name map; never production')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, ProviderUnavailable, sqlite3.Error) as exc:
        parser.exit(2, f'Import stopped: {exc}\n')


if __name__ == '__main__':
    main()

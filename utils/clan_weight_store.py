"""Official clan weights keyed by player tag; migrated in place from the former trial ledger."""
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = '''
CREATE TABLE IF NOT EXISTS clan_weight_war_lineups (
 clan_tag TEXT PRIMARY KEY, end_time TEXT NOT NULL, captured_at TEXT NOT NULL, lineup_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clan_player_weights (
 tag TEXT PRIMARY KEY, weight INTEGER, revision INTEGER NOT NULL,
 player_name TEXT NOT NULL, town_hall INTEGER, last_clan_tag TEXT NOT NULL,
 last_clan_name TEXT NOT NULL, updated_at TEXT NOT NULL, actor_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clan_player_weight_history (
 id INTEGER PRIMARY KEY, tag TEXT NOT NULL, weight INTEGER, revision INTEGER NOT NULL,
 clan_tag TEXT NOT NULL, actor_id TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(tag,revision)
);
'''


class WeightConflict(ValueError):
    pass


def validate_weight(weight, storages=None):
    """Shared write validation; reads never normalize historical saved values."""
    if storages is not None and (type(storages) is not int or not 1 <= storages <= 5):
        raise ValueError('Storages must be a whole number from 1 to 5.')
    if weight is not None:
        if type(weight) is not int or not 1000 <= weight <= 999999 or weight % 1000:
            raise ValueError('Full weight must be a whole multiple of 1,000. Correct Loot or Full; leave blank for Not Available.')
        if storages is not None and weight % storages:
            raise ValueError('Full weight must be divisible by the storage count. Correct Loot or Storages.')


def effective_weights(db, tags):
    """Resolve retained legacy and linked rows by aware saved time.

    Equal instants favor the linked ledger, including an intentional blank.
    The revision always belongs to that ledger, regardless of the winning value.
    """
    tags = tuple(tags)
    if not tags:
        return {}
    placeholders = ','.join('?' for _ in tags)
    result = {row['tag']: dict(row) for row in db.execute(
        'SELECT * FROM clan_player_weights WHERE tag IN (' + placeholders + ')', tags)}
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='player_weights'").fetchone():
        return result

    def instant(value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('Saved weight timestamp has no timezone; reconcile before editing.')
        return parsed.astimezone(timezone.utc)

    for raw in db.execute('SELECT * FROM player_weights WHERE tag IN (' + placeholders + ')', tags):
        legacy = dict(raw)
        current = result.get(legacy['tag'])
        legacy_time = instant(legacy['updated_at'])
        if current is not None and legacy_time <= instant(current['updated_at']):
            continue
        result[legacy['tag']] = {
            **(current or {'tag': legacy['tag'], 'revision': 0, 'player_name': legacy['tag'],
                          'town_hall': None, 'last_clan_tag': '', 'last_clan_name': '', 'actor_id': ''}),
            'weight': legacy['weight'], 'updated_at': legacy['updated_at'],
            'storages': None, 'source': 'Roster',
        }
    return result


class ClanWeightStore:
    def __init__(self, path, transaction_factory=None):
        self.path = path
        self.transaction_factory = transaction_factory
        with self.connect() as db:
            initialize(db)

    @contextmanager
    def connect(self):
        if self.transaction_factory is not None:
            with self.transaction_factory() as db:
                yield db
            return
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self):
        with self.connect() as db:
            rows = db.execute('SELECT tag FROM clan_player_weights ORDER BY last_clan_name,player_name,tag').fetchall()
            resolved = effective_weights(db, [row['tag'] for row in rows])
            return [resolved[row['tag']] for row in rows]

    def for_members(self, tags):
        if not tags:
            return {}
        with self.connect() as db:
            return effective_weights(db, tags)

    def last_saved(self, clan_tag):
        with self.connect() as db:
            row = db.execute(
                'SELECT updated_at,actor_id,actor_name FROM clan_player_weight_history WHERE clan_tag=? ORDER BY id DESC LIMIT 1',
                (clan_tag,),
            ).fetchone()
            return dict(row) if row else None

    def search(self, query, *, limit=25, offset=0):
        # instr treats %, _ and backslash literally; only saved rows are searched.
        with self.connect() as db:
            db.create_function('weight_casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
            args = (query.casefold(), query.upper())
            predicate = 'instr(weight_casefold(player_name), ?) > 0 OR instr(upper(tag), ?) > 0'
            total = db.execute('SELECT COUNT(*) FROM clan_player_weights WHERE ' + predicate, args).fetchone()[0]
            rows = db.execute('SELECT * FROM clan_player_weights WHERE ' + predicate +
                              ' ORDER BY player_name COLLATE NOCASE,tag LIMIT ? OFFSET ?',
                              (*args, limit, offset)).fetchall()
            resolved = effective_weights(db, [row['tag'] for row in rows])
            return {'players': [resolved[row['tag']] for row in rows], 'total': total}

    @staticmethod
    def _invalidate(db, changed_tags):
        if changed_tags and db.execute("SELECT 1 FROM sqlite_master WHERE name='roster_meta'").fetchone():
            placeholders = ','.join('?' for _ in changed_tags)
            db.execute("INSERT INTO roster_meta(season_id,revision) SELECT DISTINCT s.season_id,1 "
                       "FROM signups s JOIN seasons se ON se.id=s.season_id "
                       "WHERE se.status='draft' AND s.tag IN (" + placeholders + ") "
                       "ON CONFLICT(season_id) DO UPDATE SET revision=revision+1", tuple(changed_tags))

    @staticmethod
    def _write(db, change, current, member, clan, actor, actor_name, now, source="Clan weights"):
        revision = current['revision'] if current else 0
        storages = change.get('storages', current['storages'] if current else None)
        effective = effective_weights(db, [change['tag']]).get(change['tag'])
        same = current and effective['weight'] == change['weight'] and effective['storages'] == storages
        if not same:
            validate_weight(change['weight'], storages)
        if revision != change['revision'] and not same:
            raise WeightConflict('Changed by someone else · Reload')
        if same:
            return False  # Includes unchanged legacy values and lost-response retries.
        db.execute('INSERT OR REPLACE INTO clan_player_weights('
                   'tag,weight,revision,player_name,town_hall,last_clan_tag,last_clan_name,updated_at,actor_id,storages) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (change['tag'], change['weight'], revision + 1, member['name'], member['town_hall'],
                    clan['tag'], clan['name'], now, actor, storages))
        db.execute('INSERT INTO clan_player_weight_history('
                   'tag,weight,revision,clan_tag,actor_id,updated_at,storages,actor_name,source) VALUES (?,?,?,?,?,?,?,?,?)',
                   (change['tag'], change['weight'], revision + 1, clan['tag'], actor, now, storages, actor_name, source))
        return True

    def save(self, roster, changes, actor, actor_name=None):
        members = {row['tag']: row for row in roster['members']}
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            changed_tags = []
            for change in changes:
                if change['tag'] not in members:
                    raise WeightConflict('A selected member has left this clan. Refresh members before saving.')
                current = db.execute('SELECT * FROM clan_player_weights WHERE tag=?', (change['tag'],)).fetchone()
                if self._write(db, change, current, members[change['tag']], roster, actor, actor_name, now):
                    changed_tags.append(change['tag'])
            self._invalidate(db, changed_tags)
        return self.for_members(members)

    def save_existing(self, player_tag, change, actor, actor_name=None):
        """Explicit saved-player edit: existence, CAS, audit and invalidation are atomic.

        Preserve the saved clan/name provenance rather than claiming that an
        unavailable or departed player's location was verified by this edit.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM clan_player_weights WHERE tag=?', (player_tag,)).fetchone()
            if current is None:
                raise WeightConflict('This player has no saved clan weight. Open their current FWA clan to add one.')
            changed = self._write(db, {**change, 'tag': player_tag}, current,
                                  {'name': current['player_name'], 'town_hall': current['town_hall']},
                                  {'tag': current['last_clan_tag'], 'name': current['last_clan_name']},
                                  actor, actor_name, now)
            self._invalidate(db, [player_tag] if changed else [])
            return dict(db.execute('SELECT * FROM clan_player_weights WHERE tag=?', (player_tag,)).fetchone())

    @classmethod
    def save_roster(cls, db, season_id, player_tag, change, actor, actor_name=None):
        """Write through the caller's roster transaction, never a nested connection.

        Signup existence is a creation boundary. Placement undo remains separate;
        the invalidation makes any earlier placement undo stale as before.
        """
        member = db.execute('SELECT * FROM signups WHERE season_id=? AND tag=?',
                            (season_id, player_tag)).fetchone()
        if member is None:
            raise ValueError('Signed-up account not found')
        current = db.execute('SELECT * FROM clan_player_weights WHERE tag=?', (player_tag,)).fetchone()
        changed = cls._write(
            db, {**change, 'tag': player_tag}, current,
            {'name': member['player_name'], 'town_hall': member['town_hall']},
            {'tag': current['last_clan_tag'] if current else '',
             'name': current['last_clan_name'] if current else ''},
            actor, actor_name, datetime.now(timezone.utc).isoformat(), source='Roster')
        cls._invalidate(db, [player_tag] if changed else [])
        return changed

    def remember_lineup(self, clan_tag, lineup):
        order = lineup.get('order')
        if (lineup.get('state') not in ('preparation', 'inWar', 'warEnded')
                or not isinstance(order, dict) or not 1 <= len(order) <= 50
                or any(not isinstance(tag, str) or not tag.startswith('#') or type(position) is not int for tag, position in order.items())
                or set(order.values()) != set(range(1, len(order) + 1))):
            raise ValueError('Incomplete war lineup')
        end_time = lineup.get('end_time')
        if not end_time:
            return  # Old fixtures/providers without a war identity cannot replace history.
        ended = datetime.strptime(end_time, '%Y%m%dT%H%M%S.000Z').replace(tzinfo=timezone.utc)
        stamp = ended.isoformat()
        payload = json.dumps(lineup, sort_keys=True)
        with self.connect() as db:
            previous = db.execute('SELECT * FROM clan_weight_war_lineups WHERE clan_tag=?', (clan_tag,)).fetchone()
            if previous and (previous['end_time'] > stamp or previous['lineup_json'] == payload):
                return
            if previous and previous['end_time'] == stamp:
                states = {'preparation': 0, 'inWar': 1, 'warEnded': 2}
                if states[json.loads(previous['lineup_json'])['state']] > states[lineup['state']]:
                    return
            db.execute('INSERT INTO clan_weight_war_lineups VALUES(?,?,?,?) ON CONFLICT(clan_tag) DO UPDATE SET end_time=excluded.end_time,captured_at=excluded.captured_at,lineup_json=excluded.lineup_json',
                       (clan_tag, stamp, datetime.now(timezone.utc).isoformat(), payload))

    def saved_lineup(self, clan_tag):
        with self.connect() as db:
            row = db.execute('SELECT * FROM clan_weight_war_lineups WHERE clan_tag=?', (clan_tag,)).fetchone()
            return {**json.loads(row['lineup_json']), 'cached': True, 'captured_at': row['captured_at']} if row else None


def initialize(db):
    # Rename the existing ledger in place: no duplicate source or lost history.
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    migrated = False
    for old, new in (("clan_weight_trial", "clan_player_weights"),
                     ("clan_weight_trial_history", "clan_player_weight_history")):
        if old in tables:
            if new in tables:
                raise RuntimeError("Both legacy and official clan-weight tables exist; reconcile before startup")
            db.execute(f'ALTER TABLE {old} RENAME TO {new}')
            migrated = True
    db.executescript(SCHEMA)
    if migrated and 'roster_meta' in tables:
        db.execute("INSERT INTO roster_meta(season_id,revision) SELECT id,1 FROM seasons WHERE status='draft' "
                   "ON CONFLICT(season_id) DO UPDATE SET revision=revision+1")
    for table in ('clan_player_weights', 'clan_player_weight_history'):
        columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
        if 'storages' not in columns:
            db.execute(f'ALTER TABLE {table} ADD COLUMN storages INTEGER')
    columns = {row['name'] for row in db.execute('PRAGMA table_info(clan_player_weight_history)')}
    if 'actor_name' not in columns:
        db.execute('ALTER TABLE clan_player_weight_history ADD COLUMN actor_name TEXT')
    if 'source' not in columns:
        db.execute("ALTER TABLE clan_player_weight_history ADD COLUMN source TEXT NOT NULL DEFAULT 'Clan weights'")
    db.execute('CREATE INDEX IF NOT EXISTS clan_player_weight_history_clan_id ON clan_player_weight_history(clan_tag,id DESC)')

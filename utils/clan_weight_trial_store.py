"""Official clan weights keyed by player tag; legacy table names preserve data."""
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = '''
CREATE TABLE IF NOT EXISTS clan_weight_war_lineups (
 clan_tag TEXT PRIMARY KEY, end_time TEXT NOT NULL, captured_at TEXT NOT NULL, lineup_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clan_weight_trial (
 tag TEXT PRIMARY KEY, weight INTEGER, revision INTEGER NOT NULL,
 player_name TEXT NOT NULL, town_hall INTEGER, last_clan_tag TEXT NOT NULL,
 last_clan_name TEXT NOT NULL, updated_at TEXT NOT NULL, actor_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clan_weight_trial_history (
 id INTEGER PRIMARY KEY, tag TEXT NOT NULL, weight INTEGER, revision INTEGER NOT NULL,
 clan_tag TEXT NOT NULL, actor_id TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(tag,revision)
);
'''


class WeightConflict(ValueError):
    pass


class ClanWeightTrialStore:
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
            return [dict(row) for row in db.execute('SELECT * FROM clan_weight_trial ORDER BY last_clan_name,player_name,tag')]

    def for_members(self, tags):
        if not tags:
            return {}
        with self.connect() as db:
            return {row['tag']: dict(row) for row in db.execute(
                'SELECT * FROM clan_weight_trial WHERE tag IN (' + ','.join('?' for _ in tags) + ')', tuple(tags))}

    def last_saved(self, clan_tag):
        with self.connect() as db:
            row = db.execute(
                'SELECT updated_at,actor_id,actor_name FROM clan_weight_trial_history WHERE clan_tag=? ORDER BY id DESC LIMIT 1',
                (clan_tag,),
            ).fetchone()
            return dict(row) if row else None

    def save(self, roster, changes, actor, actor_name=None):
        members = {row['tag']: row for row in roster['members']}
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            changed_tags = []
            for change in changes:
                current = db.execute('SELECT * FROM clan_weight_trial WHERE tag=?', (change['tag'],)).fetchone()
                revision = current['revision'] if current else 0
                storages = change.get('storages', (current['storages'] if current else None))
                same = current and current['weight'] == change['weight'] and current['storages'] == storages
                if revision != change['revision'] and not same:
                    raise WeightConflict('A weight changed since you loaded this clan. Refresh members before saving again.')
                if same:
                    continue  # Safe replay after a lost response; no duplicate audit event.
                changed_tags.append(change['tag'])
                member = members[change['tag']]
                db.execute('INSERT OR REPLACE INTO clan_weight_trial(tag,weight,revision,player_name,town_hall,last_clan_tag,last_clan_name,updated_at,actor_id,storages) VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (change['tag'],change['weight'],revision+1,member['name'],member['town_hall'],roster['tag'],roster['name'],now,actor,storages))
                db.execute('INSERT INTO clan_weight_trial_history(tag,weight,revision,clan_tag,actor_id,updated_at,storages,actor_name) VALUES (?,?,?,?,?,?,?,?)',
                           (change['tag'],change['weight'],revision+1,roster['tag'],actor,now,storages,actor_name))
            if changed_tags and db.execute("SELECT 1 FROM sqlite_master WHERE name='roster_meta'").fetchone():
                placeholders = ','.join('?' for _ in changed_tags)
                db.execute("INSERT INTO roster_meta(season_id,revision) SELECT DISTINCT s.season_id,1 FROM signups s JOIN seasons se ON se.id=s.season_id WHERE se.status='draft' AND s.tag IN (" + placeholders + ") ON CONFLICT(season_id) DO UPDATE SET revision=revision+1", tuple(changed_tags))
        return self.for_members(members)

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
    db.executescript(SCHEMA)
    for table in ('clan_weight_trial', 'clan_weight_trial_history'):
        columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
        if 'storages' not in columns:
            db.execute(f'ALTER TABLE {table} ADD COLUMN storages INTEGER')
    columns = {row['name'] for row in db.execute('PRAGMA table_info(clan_weight_trial_history)')}
    if 'actor_name' not in columns:
        db.execute('ALTER TABLE clan_weight_trial_history ADD COLUMN actor_name TEXT')
    db.execute('CREATE INDEX IF NOT EXISTS weight_trial_history_clan_id ON clan_weight_trial_history(clan_tag,id DESC)')

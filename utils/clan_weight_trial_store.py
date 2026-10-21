"""Isolated trial weights keyed by player tag; no effect on production weights."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = '''
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
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
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

    def save(self, roster, changes, actor):
        members = {row['tag']: row for row in roster['members']}
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for change in changes:
                current = db.execute('SELECT * FROM clan_weight_trial WHERE tag=?', (change['tag'],)).fetchone()
                revision = current['revision'] if current else 0
                if revision != change['revision'] and (not current or current['weight'] != change['weight']):
                    raise WeightConflict('A weight changed since you loaded this clan. Refresh members before saving again.')
                if current and current['weight'] == change['weight']:
                    continue  # Safe replay after a lost response; no duplicate audit event.
                member = members[change['tag']]
                db.execute('INSERT OR REPLACE INTO clan_weight_trial VALUES (?,?,?,?,?,?,?,?,?)',
                           (change['tag'],change['weight'],revision+1,member['name'],member['town_hall'],roster['tag'],roster['name'],now,actor))
                db.execute('INSERT INTO clan_weight_trial_history(tag,weight,revision,clan_tag,actor_id,updated_at) VALUES (?,?,?,?,?,?)',
                           (change['tag'],change['weight'],revision+1,roster['tag'],actor,now))
        return self.for_members(members)

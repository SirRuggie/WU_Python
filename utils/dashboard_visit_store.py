"""Storage owner for daily authenticated visits; no device or request metadata."""
from datetime import date, datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS visit_days (
 user_id TEXT NOT NULL,
 day TEXT NOT NULL,
 first_seen_at TEXT NOT NULL,
 is_staff INTEGER NOT NULL CHECK(is_staff IN (0,1)),
 PRIMARY KEY(user_id,day)
);
CREATE INDEX IF NOT EXISTS visit_days_day ON visit_days(day);
"""


class VisitStore:
    def __init__(self, store):
        self.store = store

    def record(self, user_id, *, day, at, is_staff):
        """The caller supplies policy's local day and current staff classification."""
        if not isinstance(user_id, str) or not user_id.isdecimal() or not 1 <= len(user_id) <= 22:
            raise ValueError('A valid authenticated user is required.')
        if type(day) is not date or not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('A calendar day and timezone-aware timestamp are required.')
        if type(is_staff) is not bool:
            raise ValueError('Staff classification must be a boolean.')
        with self.store.tx() as db:
            cursor = db.execute(
                'INSERT OR IGNORE INTO visit_days(user_id,day,first_seen_at,is_staff) VALUES(?,?,?,?)',
                (user_id, day.isoformat(), at.astimezone(timezone.utc).isoformat(), int(is_staff)),
            )
        return cursor.rowcount == 1

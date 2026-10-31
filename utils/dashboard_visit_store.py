"""Storage owner for daily authenticated visits; no device or request metadata."""
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE = ZoneInfo("America/New_York")

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
        self._pruned_day = None

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

    def record_session(self, user_id, *, at, is_staff):
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('A timezone-aware timestamp is required.')
        day = at.astimezone(LOCAL_TIMEZONE).date()
        self.prune(day)
        return self.record(user_id, day=day, at=at, is_staff=is_staff)

    def prune(self, today):
        """Keep today and the preceding 89 local days; run once per process/day."""
        if type(today) is not date:
            raise ValueError('A calendar day is required.')
        if self._pruned_day == today:
            return
        with self.store.tx() as db:
            db.execute('DELETE FROM visit_days WHERE day < ?',
                       ((today - timedelta(days=89)).isoformat(),))
        self._pruned_day = today

    def aggregates(self, today):
        """Return counts only; a person seen as staff in a window counts as staff."""
        if type(today) is not date:
            raise ValueError('A calendar day is required.')
        with self.store.tx() as db:
            def window(days):
                rows = db.execute(
                    'SELECT MAX(is_staff) AS staff FROM visit_days WHERE day BETWEEN ? AND ? GROUP BY user_id',
                    ((today - timedelta(days=days-1)).isoformat(), today.isoformat()),
                ).fetchall()
                staff = sum(row['staff'] for row in rows)
                return {'total': len(rows), 'staff': staff, 'members': len(rows)-staff}
            counts = {str(days): window(days) for days in (1, 7, 30)}
            rows = db.execute(
                'SELECT day, COUNT(*) AS total, SUM(is_staff) AS staff FROM visit_days '
                'WHERE day BETWEEN ? AND ? GROUP BY day',
                ((today-timedelta(days=29)).isoformat(), today.isoformat()),
            ).fetchall()
        by_day = {row['day']: row for row in rows}
        series = []
        for offset in range(29, -1, -1):
            day = (today-timedelta(days=offset)).isoformat()
            row = by_day.get(day)
            total, staff = (row['total'], row['staff']) if row else (0, 0)
            series.append({'day': day, 'total': total, 'staff': staff, 'members': total-staff})
        return {'timezone': 'America/New_York', 'today': today.isoformat(), 'windows': counts, 'series': series}

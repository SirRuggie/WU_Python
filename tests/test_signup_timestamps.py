import sqlite3
from cwl_web.store import signup_timestamps


def test_registration_dates_ignore_edits_and_use_latest_resignup():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE roster_audit (id INTEGER PRIMARY KEY,season_id INTEGER,tag TEXT,action TEXT,before_json TEXT,created_at TEXT)')
    events = [
        (1, '#A', 'member_signup', None, '2026-10-01 12:00:00'),
        (1, '#A', 'member_signup', '{}', '2026-10-02 12:00:00'),
        (1, '#A', 'member_withdrawal', '{}', '2026-10-03 12:00:00'),
        (1, '#A', 'member_signup', None, '2026-10-04 12:00:00'),
        (1, '#A', 'member_pool_change', '{}', '2026-10-05 12:00:00'),
        (1, '#B', 'staff_signup', 'null', '2026-10-02 13:00:00'),
        (2, '#A', 'member_signup', None, '2026-11-01 12:00:00'),
    ]
    db.executemany('INSERT INTO roster_audit(season_id,tag,action,before_json,created_at) VALUES (?,?,?,?,?)', events)
    assert signup_timestamps(db, 1) == {'#A': '2026-10-04T12:00:00Z', '#B': '2026-10-02T13:00:00Z'}
    assert signup_timestamps(db, 3) == {}

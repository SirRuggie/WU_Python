"""Persistent staff roster marks keyed by player tag, separate from Strikes.

SQLite transactions supplied by the dashboard own the commit boundary. Marks and
all affected season revisions change together; per-tag revisions protect undo
across seasons. No existing player or strike records are migrated or inferred.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS roster_player_marks (
 tag TEXT PRIMARY KEY, roster_filler INTEGER NOT NULL DEFAULT 0 CHECK(roster_filler IN (0,1)),
 revision INTEGER NOT NULL DEFAULT 0, updated_by TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS roster_player_mark_audit (
 id INTEGER PRIMARY KEY, tag TEXT NOT NULL, actor_id TEXT NOT NULL,
 before_value INTEGER NOT NULL, after_value INTEGER NOT NULL,
 revision INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class MarkConflict(ValueError):
    pass


def marks(db):
    return {
        row["tag"]: dict(row) for row in db.execute("SELECT * FROM roster_player_marks")
    }


def mark(db, player_tag):
    row = db.execute(
        "SELECT * FROM roster_player_marks WHERE tag=?", (player_tag,)
    ).fetchone()
    return dict(row) if row else dict(tag=player_tag, roster_filler=False, revision=0)


def save(db, player_tag, value, revision, actor):
    if (
        type(value) is not bool
        or type(revision) is not int
        or not 0 <= revision < 2**63
    ):
        raise ValueError("Expected filler boolean and mark revision")
    before = mark(db, player_tag)
    if before["revision"] != revision:
        raise MarkConflict("Filler mark changed. Refresh and try again.")
    if bool(before["roster_filler"]) == value:
        return before, before
    db.execute(
        "INSERT INTO roster_player_marks(tag,roster_filler,revision,updated_by,updated_at) "
        "VALUES (?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(tag) DO UPDATE SET "
        "roster_filler=excluded.roster_filler,revision=excluded.revision,"
        "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (player_tag, int(value), revision + 1, str(actor)),
    )
    db.execute(
        "INSERT INTO roster_player_mark_audit(tag,actor_id,before_value,after_value,revision) "
        "VALUES (?,?,?,?,?)",
        (
            player_tag,
            str(actor),
            int(before["roster_filler"]),
            int(value),
            revision + 1,
        ),
    )
    # A mark is global. Invalidate stale plans, confirmations and undo in every season.
    db.execute(
        "INSERT OR IGNORE INTO roster_meta(season_id,revision) SELECT id,0 FROM seasons"
    )
    db.execute("UPDATE roster_meta SET revision=revision+1")
    return before, mark(db, player_tag)


def overlay(db, accounts):
    saved = marks(db)
    for account in accounts:
        value = saved.get(account["tag"], {})
        account["roster_filler"] = bool(value.get("roster_filler"))
        account["roster_filler_revision"] = value.get("revision", 0)
    return accounts


def incoming_regular(db, tags):
    saved = marks(db)
    return [tag for tag in tags if not saved.get(tag, {}).get("roster_filler")]


def assigned_counts(db, season_id, clan_tag):
    row = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(m.roster_filler),0) AS fillers "
        "FROM roster_entries e LEFT JOIN roster_player_marks m ON m.tag=e.tag "
        "WHERE e.season_id=? AND e.assigned_clan_tag=?",
        (season_id, clan_tag),
    ).fetchone()
    return row["total"], row["fillers"]

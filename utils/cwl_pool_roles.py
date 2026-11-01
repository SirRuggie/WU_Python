"""Single SQLite owner for CWL pool-role settings, outbox, leases and receipts.

Signup triggers share the existing transaction. Discord is never called here.
The dashboard remains the sole SQLite writer; the bot uses its loopback bridge.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

from utils.lazy_cwl_store import expires_at_for

GUILD_ID = 644963518025826315
POOLS = ("main", "lazy")
LEASE_SECONDS = 200
ID = re.compile(r"[1-9][0-9]{14,21}\Z")
SCHEMA = """
CREATE TABLE IF NOT EXISTS cwl_pool_role_settings (
 pool TEXT PRIMARY KEY CHECK(pool IN ('main','lazy')), role_id TEXT,
 revision INTEGER NOT NULL DEFAULT 0, next_expiry TEXT, updated_by TEXT
);
INSERT OR IGNORE INTO cwl_pool_role_settings(pool) VALUES ('main'),('lazy');
CREATE TABLE IF NOT EXISTS cwl_pool_role_jobs (
 id TEXT PRIMARY KEY, job_key TEXT NOT NULL UNIQUE, pool TEXT NOT NULL,
 role_id TEXT NOT NULL, setting_revision INTEGER NOT NULL,
 kind TEXT NOT NULL, intent TEXT NOT NULL DEFAULT 'add', season_id INTEGER, cycle_cutoff REAL NOT NULL DEFAULT 0, user_id TEXT, cursor TEXT NOT NULL DEFAULT '0',
 generation INTEGER NOT NULL DEFAULT 1, requested_at REAL NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until REAL, message TEXT,
 created_at REAL NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS cwl_pool_roles_ready
 ON cwl_pool_role_jobs(state,next_at,created_at);
CREATE INDEX IF NOT EXISTS cwl_pool_roles_pool ON cwl_pool_role_jobs(pool,setting_revision,kind,state);
CREATE TABLE IF NOT EXISTS cwl_pool_role_clock (
 id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL, last_prune REAL NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO cwl_pool_role_clock(id,next_at) VALUES (1,0);
CREATE TABLE IF NOT EXISTS cwl_pool_role_audit (
 id INTEGER PRIMARY KEY, pool TEXT NOT NULL, role_id TEXT, user_id TEXT,
 actor_id TEXT, action TEXT NOT NULL, details_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Conflict(ValueError):
    pass


def active_season(db):
    row = db.execute(
        "SELECT x.id FROM member_season m JOIN seasons x ON x.id=m.season_id WHERE m.id=1 AND x.status='draft'"
    ).fetchone()
    return row[0] if row else None


def members(db, pool, season_id=None):
    season_id = active_season(db) if season_id is None else season_id
    return [
        row[0]
        for row in db.execute(
            "SELECT DISTINCT user_id FROM signups WHERE season_id=? AND pool=? ORDER BY user_id",
            (season_id, pool),
        )
        if ID.fullmatch(row[0])
    ]


def member_basis(db, pool):
    return hashlib.sha256(
        json.dumps([active_season(db), members(db, pool)]).encode()
    ).hexdigest()


def initialize(db):
    db.executescript(SCHEMA)
    if "requested_at" not in {
        r[1] for r in db.execute("PRAGMA table_info(cwl_pool_role_jobs)")
    }:
        db.execute(
            "ALTER TABLE cwl_pool_role_jobs ADD COLUMN requested_at REAL NOT NULL DEFAULT 0"
        )
        db.execute("UPDATE cwl_pool_role_jobs SET requested_at=created_at")

    if "last_prune" not in {
        r[1] for r in db.execute("PRAGMA table_info(cwl_pool_role_clock)")
    }:
        db.execute(
            "ALTER TABLE cwl_pool_role_clock ADD COLUMN last_prune REAL NOT NULL DEFAULT 0"
        )

    columns = {r[1] for r in db.execute("PRAGMA table_info(cwl_pool_role_jobs)")}
    for name, declaration in (
        ("intent", "TEXT NOT NULL DEFAULT 'add'"),
        ("season_id", "INTEGER"),
        ("cycle_cutoff", "REAL NOT NULL DEFAULT 0"),
    ):
        if name not in columns:
            db.execute(
                f"ALTER TABLE cwl_pool_role_jobs ADD COLUMN {name} {declaration}"
            )
    clock_columns = {r[1] for r in db.execute("PRAGMA table_info(cwl_pool_role_clock)")}
    for name, declaration in (
        ("progress_version", "INTEGER NOT NULL DEFAULT 0"),
        ("last_backup_version", "INTEGER NOT NULL DEFAULT 0"),
        ("last_backup_attempt", "REAL NOT NULL DEFAULT 0"),
    ):
        if name not in clock_columns:
            db.execute(
                f"ALTER TABLE cwl_pool_role_clock ADD COLUMN {name} {declaration}"
            )
    # Only the member-facing draft season participates. A job retains its own
    # season scope; unarchived historical drafts never contribute to its count.
    stamp = "((julianday('now')-2440587.5)*86400.0)"

    def enqueue(uid, pool, season, intent):
        supersede = (
            f"""UPDATE cwl_pool_role_jobs SET state='superseded',lease_token=NULL
          WHERE kind='remove' AND user_id={uid} AND state IN ('pending','leased')
          AND role_id IN (SELECT role_id FROM cwl_pool_role_settings WHERE pool={pool})
          AND {season}=(SELECT season_id FROM member_season WHERE id=1);"""
            if intent == "add"
            else ""
        )
        return supersede + f"""
        INSERT INTO cwl_pool_role_jobs
          (id,job_key,pool,role_id,setting_revision,kind,intent,season_id,user_id,requested_at)
        SELECT lower(hex(randomblob(16))),
          'sync:'||r.pool||':'||{season}||':'||{uid}||':'||r.revision,
          r.pool,r.role_id,r.revision,'sync','{intent}',{season},{uid},{stamp}
        FROM cwl_pool_role_settings r WHERE r.pool={pool}
          AND r.role_id IS NOT NULL AND {uid}<>''
          AND {season}=(SELECT season_id FROM member_season WHERE id=1)
          AND EXISTS(SELECT 1 FROM seasons WHERE id={season} AND status='draft')
          AND {uid} NOT GLOB '*[^0-9]*' AND length({uid}) BETWEEN 15 AND 22
          AND substr({uid},1,1)<>'0'
        ON CONFLICT(job_key) DO UPDATE SET generation=generation+1,
          intent=excluded.intent,season_id=excluded.season_id,
          state='pending',attempts=0,next_at=0,lease_token=NULL,lease_until=NULL,requested_at={stamp};
        """

    for event, name, body in (
        (
            "INSERT",
            "insert",
            enqueue("NEW.user_id", "NEW.pool", "NEW.season_id", "add"),
        ),
        (
            "DELETE",
            "delete",
            enqueue("OLD.user_id", "OLD.pool", "OLD.season_id", "cancel"),
        ),
        (
            "UPDATE",
            "update",
            enqueue("OLD.user_id", "OLD.pool", "OLD.season_id", "cancel")
            + enqueue("NEW.user_id", "NEW.pool", "NEW.season_id", "add"),
        ),
    ):
        for suffix in ("", "_v2"):
            db.execute(f"DROP TRIGGER IF EXISTS cwl_pool_role_{name}{suffix}")
        condition = (
            "WHEN OLD.user_id<>NEW.user_id OR OLD.pool<>NEW.pool OR OLD.season_id<>NEW.season_id"
            if event == "UPDATE"
            else ""
        )
        db.executescript(
            f"CREATE TRIGGER IF NOT EXISTS cwl_pool_role_{name}_v3 AFTER {event} ON signups {condition} BEGIN {body} END;"
        )


def audit(db, pool, action, details, *, role_id=None, user_id=None, actor_id=None):
    db.execute(
        "INSERT INTO cwl_pool_role_audit(pool,role_id,user_id,actor_id,action,details_json) "
        "VALUES (?,?,?,?,?,?)",
        (pool, role_id, user_id, actor_id, action, json.dumps(details)),
    )


def snapshot(db):
    result = []
    for row in db.execute("SELECT * FROM cwl_pool_role_settings ORDER BY pool"):
        setting = dict(row)
        scan = db.execute(
            "SELECT * FROM cwl_pool_role_jobs WHERE pool=? AND setting_revision=? "
            "AND kind='scan' AND state<>'superseded' ORDER BY created_at DESC,id DESC LIMIT 1",
            (row["pool"], row["revision"]),
        ).fetchone()
        base = "pool=? AND setting_revision=? AND state<>'superseded'"
        args = [row["pool"], row["revision"]]
        condition = base + " AND kind='sync'"
        stage = "signup"
        scanning = bool(scan and scan["state"] in ("pending", "leased"))
        if scan:
            prefix = f"expiry:{row['pool']}:{row['revision']}:"
            cutoff = datetime.fromisoformat(scan["job_key"][len(prefix) :]).timestamp()
            removal = base + " AND kind='remove' AND job_key LIKE ?"
            removal_args = [*args, scan["job_key"] + ":%"]
            waiting = db.execute(
                "SELECT 1 FROM cwl_pool_role_jobs WHERE "
                + removal
                + " AND state IN ('pending','leased') LIMIT 1",
                removal_args,
            ).fetchone()
            newer = db.execute(
                "SELECT 1 FROM cwl_pool_role_jobs WHERE "
                + base
                + " AND kind='sync' AND requested_at>=? LIMIT 1",
                [*args, cutoff],
            ).fetchone()
            if scanning or waiting or not newer:
                condition, args, stage = removal, removal_args, "expiry"
            else:
                condition += " AND requested_at>=?"
                args.append(cutoff)
        counts = {
            r[0]: r[1]
            for r in db.execute(
                "SELECT state,COUNT(*) FROM cwl_pool_role_jobs WHERE "
                + condition
                + " GROUP BY state",
                args,
            )
        }
        failure = db.execute(
            "SELECT message FROM cwl_pool_role_jobs WHERE "
            + condition
            + " AND message<>'' AND state IN ('failed','pending','leased') "
            "ORDER BY requested_at DESC,created_at DESC LIMIT 1",
            args,
        ).fetchone()
        if scan and scan["state"] in ("failed", "pending") and scan["message"]:
            failure = [scan["message"]]
        setting.update(
            member_count=len(members(db, row["pool"])),
            member_basis=member_basis(db, row["pool"]),
            progress=counts,
            scanning=scanning,
            stage=stage,
            failure=failure[0] if failure else None,
        )
        result.append(setting)
    return {"pools": result, "season_id": active_season(db)}


def _insert(db, key, setting, kind, uid=None):
    db.execute(
        "INSERT OR IGNORE INTO cwl_pool_role_jobs"
        "(id,job_key,pool,role_id,setting_revision,kind,user_id,requested_at,intent,season_id,cycle_cutoff) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            uuid4().hex,
            key,
            setting["pool"],
            setting["role_id"],
            setting.get("revision", setting.get("setting_revision")),
            kind,
            uid,
            time.time(),
            setting.get("intent", "add"),
            setting.get("season_id"),
            setting.get("cycle_cutoff", 0),
        ),
    )


def save(db, pool, role_id, revision, basis, actor, *, now=None):
    if pool not in POOLS or (role_id is not None and not ID.fullmatch(role_id)):
        raise ValueError("Choose a valid pool and role.")
    if type(revision) is not int:
        raise ValueError("Invalid settings revision.")
    old = db.execute(
        "SELECT * FROM cwl_pool_role_settings WHERE pool=?", (pool,)
    ).fetchone()
    if old["revision"] != revision or member_basis(db, pool) != basis:
        raise Conflict("Signups or settings changed. Review the count again.")
    if role_id == old["role_id"]:
        return snapshot(db)  # A same-role Save never discards cleanup/cancel work.
    now = now or datetime.now(timezone.utc)
    next_expiry = (
        expires_at_for(now, section="MAIN" if pool == "main" else "FWA").isoformat()
        if role_id
        else None
    )
    if role_id is not None and role_id == old["role_id"] and old["next_expiry"]:
        next_expiry = old["next_expiry"]
    db.execute(
        "UPDATE cwl_pool_role_settings SET role_id=?,revision=revision+1,next_expiry=?,"
        "updated_by=? WHERE pool=?",
        (role_id, next_expiry, actor, pool),
    )
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state='superseded',lease_token=NULL "
        "WHERE pool=? AND state IN ('pending','leased')",
        (pool,),
    )
    setting = dict(old) | {
        "role_id": role_id,
        "revision": revision + 1,
        "season_id": active_season(db),
    }
    if role_id:
        for uid in members(db, pool):
            _insert(
                db,
                f"sync:{pool}:{active_season(db)}:{uid}:{revision+1}",
                setting,
                "sync",
                uid,
            )
    audit(
        db,
        pool,
        "setting_saved",
        {"before": old["role_id"], "after": role_id},
        role_id=role_id,
        actor_id=actor,
    )
    return snapshot(db)


def _due(db, now):
    for row in db.execute(
        "SELECT * FROM cwl_pool_role_settings WHERE role_id IS NOT NULL"
    ).fetchall():
        due = datetime.fromisoformat(row["next_expiry"])
        if due > now:
            continue
        # Catch up once at the latest due cycle, using the saved-list calculation.
        following = expires_at_for(
            due, section="MAIN" if row["pool"] == "main" else "FWA"
        )
        while following <= now:
            due, following = following, expires_at_for(
                following, section="MAIN" if row["pool"] == "main" else "FWA"
            )
        db.execute(
            "UPDATE cwl_pool_role_jobs SET state='superseded',lease_token=NULL "
            "WHERE pool=? AND setting_revision=? AND kind='sync' "
            "AND state IN ('pending','leased') AND requested_at<?",
            (row["pool"], row["revision"], due.timestamp()),
        )
        setting = dict(row) | {"cycle_cutoff": due.timestamp()}
        _insert(
            db,
            f"expiry:{row['pool']}:{row['revision']}:{due.isoformat()}",
            setting,
            "scan",
        )
        db.execute(
            "UPDATE cwl_pool_role_settings SET next_expiry=? WHERE pool=?",
            (following.isoformat(), row["pool"]),
        )


def _valid(db, job):
    if job["season_id"] is not None and job["season_id"] != active_season(db):
        return False
    return db.execute(
        "SELECT 1 FROM cwl_pool_role_settings WHERE pool=? AND role_id=? "
        "AND revision=?",
        (job["pool"], job["role_id"], job["setting_revision"]),
    ).fetchone()


def desired(db, job):
    if job["kind"] == "remove":
        return False
    # If the operator chooses the same physical role for both pools, retain it
    # while this member is signed up in either configured pool.
    return any(
        job["user_id"] in members(db, row[0], job["season_id"])
        for row in db.execute(
            "SELECT pool FROM cwl_pool_role_settings WHERE role_id=?", (job["role_id"],)
        )
    )


def skip_change(db, job):
    if job["kind"] == "sync" and job["intent"] == "cancel":
        return desired(db, job)  # Retain an existing role, never add on cancel.
    if job["kind"] == "remove":
        return bool(
            db.execute(
                "SELECT 1 FROM cwl_pool_role_jobs j JOIN cwl_pool_role_settings r ON r.pool=j.pool AND r.role_id=j.role_id AND r.revision=j.setting_revision WHERE j.kind='sync' AND j.intent='add' AND j.user_id=? AND j.role_id=? AND j.season_id=? AND j.requested_at>=? LIMIT 1",
                (
                    job["user_id"],
                    job["role_id"],
                    active_season(db),
                    job["cycle_cutoff"],
                ),
            ).fetchone()
        )
    return False


def claim(db, *, now=None):
    now = now or datetime.now(timezone.utc)
    _due(db, now)
    stamp = now.timestamp()
    last = db.execute(
        "SELECT last_prune FROM cwl_pool_role_clock WHERE id=1"
    ).fetchone()[0]
    if (
        stamp - last > 86400
        and db.execute(
            "SELECT 1 FROM cwl_pool_role_settings WHERE role_id IS NOT NULL"
        ).fetchone()
    ):
        db.execute(
            "DELETE FROM cwl_pool_role_jobs WHERE state IN ('done','failed','superseded') AND created_at<?",
            (stamp - 90 * 86400,),
        )
        db.execute(
            "DELETE FROM cwl_pool_role_audit WHERE action<>'setting_saved' AND unixepoch(created_at)<?",
            (stamp - 90 * 86400,),
        )
        db.execute("UPDATE cwl_pool_role_clock SET last_prune=? WHERE id=1", (stamp,))
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state='pending',lease_token=NULL,message=COALESCE(message,'Role work was not confirmed. Checking current roles.') WHERE state='leased' "
        "AND lease_until<=?",
        (stamp,),
    )
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state='superseded' WHERE state='pending' AND NOT EXISTS "
        "(SELECT 1 FROM cwl_pool_role_settings r WHERE r.pool=cwl_pool_role_jobs.pool "
        "AND r.role_id=cwl_pool_role_jobs.role_id AND r.revision=cwl_pool_role_jobs.setting_revision)"
    )
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state='superseded',lease_token=NULL WHERE season_id IS NOT NULL AND (season_id<>? OR ? IS NULL) AND state IN ('pending','leased')",
        (active_season(db), active_season(db)),
    )
    row = db.execute(
        "SELECT * FROM cwl_pool_role_jobs WHERE state='pending' AND next_at<=? "
        "ORDER BY CASE kind WHEN 'scan' THEN 0 WHEN 'remove' THEN 1 ELSE 2 END,created_at,id LIMIT 1",
        (stamp,),
    ).fetchone()
    if row is None:
        return None
    job = dict(row)
    clock = db.execute("SELECT next_at FROM cwl_pool_role_clock WHERE id=1").fetchone()[
        0
    ]
    if stamp < clock:
        return None
    db.execute("UPDATE cwl_pool_role_clock SET next_at=? WHERE id=1", (stamp + 3,))
    token = uuid4().hex
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state='leased',lease_token=?,lease_until=?,"
        "attempts=attempts+1 WHERE id=?",
        (token, stamp + LEASE_SECONDS, job["id"]),
    )
    return job | {
        "lease_token": token,
        "lease_until": stamp + LEASE_SECONDS,
        "desired": desired(db, job) if job["kind"] != "scan" else None,
        "skip": skip_change(db, job),
    }


def owned(db, job_id, token, generation):
    row = db.execute(
        "SELECT * FROM cwl_pool_role_jobs WHERE id=? AND state='leased' "
        "AND lease_token=? AND generation=?",
        (job_id, token, generation),
    ).fetchone()
    return (
        dict(row)
        if row
        and row["lease_until"]
        and row["lease_until"] > time.time()
        and _valid(db, row)
        else None
    )


def validate(db, job_id, token, generation):
    job = owned(db, job_id, token, generation)
    return {
        "valid": bool(job),
        "desired": desired(db, job) if job and job["kind"] != "scan" else None,
        "skip": skip_change(db, job) if job else False,
    }


def finish(
    db,
    job_id,
    token,
    generation,
    *,
    message="",
    failed=False,
    retry=False,
    page=None,
    cursor=None,
):
    job = owned(db, job_id, token, generation)
    if job is None:
        return {"accepted": False}
    if page is not None:
        if (
            job["kind"] != "scan"
            or not isinstance(page, list)
            or len(page) > 1000
            or any(not isinstance(uid, str) or not ID.fullmatch(uid) for uid in page)
            or not isinstance(cursor, str)
            or not re.fullmatch(r"0|[1-9][0-9]{0,21}", cursor)
        ):
            raise ValueError("Invalid expiry page.")
        if int(cursor) < int(job["cursor"]) or (
            page and int(cursor) <= int(job["cursor"])
        ):
            raise ValueError("Expiry cursor did not advance.")
        for uid in set(page):
            _insert(db, f"{job['job_key']}:{uid}", job, "remove", uid)
        if int(cursor) > int(job["cursor"]):
            db.execute(
                "UPDATE cwl_pool_role_jobs SET cursor=?,state='pending',lease_token=NULL "
                "WHERE id=?",
                (cursor, job_id),
            )
            return {"accepted": True}
    if retry:
        db.execute(
            "UPDATE cwl_pool_role_jobs SET state='pending',message=?,next_at=?,lease_token=NULL WHERE id=?",
            (
                message[:250],
                time.time() + min(3600, 30 * max(1, job["attempts"])),
                job_id,
            ),
        )
        if job["attempts"] == 1 or job.get("message") != message[:250]:
            audit(
                db,
                job["pool"],
                "role_retry",
                {"job_id": job_id, "message": message[:250]},
                role_id=job["role_id"],
                user_id=job["user_id"],
                actor_id="bot",
            )
        return {"accepted": True}
    status = "failed" if failed else "done"
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state=?,message=?,lease_token=NULL WHERE id=?",
        (status, message[:250], job_id),
    )
    audit(
        db,
        job["pool"],
        "role_" + status,
        {"job_id": job_id, "kind": job["kind"], "message": message[:250]},
        role_id=job["role_id"],
        user_id=job["user_id"],
        actor_id="bot",
    )
    return {"accepted": True}


# Role progress is locally committed with SQLite FULL synchronous durability.
# Its separate recovery snapshot never changes the dashboard head/revision.
PROGRESS_TABLES = (
    "cwl_pool_role_settings",
    "cwl_pool_role_jobs",
    "cwl_pool_role_clock",
    "cwl_pool_role_audit",
)


def progress_image(db):
    tables = {}
    for table in PROGRESS_TABLES:
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
        if not columns:
            return None
        tables[table] = {
            "columns": columns,
            "rows": [list(row) for row in db.execute(f"SELECT * FROM {table}")],
        }
    clock = dict(
        zip(
            tables[PROGRESS_TABLES[2]]["columns"], tables[PROGRESS_TABLES[2]]["rows"][0]
        )
    )
    raw = json.dumps({"format": 1, "tables": tables}, separators=(",", ":")).encode()
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Role progress recovery image is too large.")
    import zlib

    payload = zlib.compress(raw)
    if len(payload) > 12 * 1024 * 1024:
        raise ValueError("Role progress recovery image exceeds its backup limit.")
    return {
        "format": 1,
        "payload": payload,
        "raw_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "version": clock["progress_version"],
    }


def decode_progress(image):
    import zlib

    if not image or image.get("format") != 1:
        raise ValueError("Role progress recovery format is unavailable.")
    unpacker = zlib.decompressobj()
    raw = unpacker.decompress(image["payload"], 32 * 1024 * 1024 + 1)
    if (
        len(raw) > 32 * 1024 * 1024
        or not unpacker.eof
        or unpacker.unused_data
        or len(raw) != image["raw_bytes"]
        or hashlib.sha256(raw).hexdigest() != image["sha256"]
    ):
        raise ValueError("Role progress recovery checksum failed.")
    value = json.loads(raw)
    if value.get("format") != 1 or set(value.get("tables", {})) != set(PROGRESS_TABLES):
        raise ValueError("Role progress recovery tables are invalid.")
    return value["tables"]


def recover_progress(db, image):
    """Merge only matching intents; the Mongo head owns signups and settings."""
    tables = decode_progress(image)
    decoded = {}
    for table in PROGRESS_TABLES:
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
        data = tables[table]
        if data.get("columns") != columns or not isinstance(data.get("rows"), list):
            raise ValueError("Role progress recovery schema does not match.")
        if any(
            not isinstance(row, list) or len(row) != len(columns)
            for row in data["rows"]
        ):
            raise ValueError("Role progress recovery row is invalid.")
        decoded[table] = [dict(zip(columns, row)) for row in data["rows"]]
    clocks = decoded[PROGRESS_TABLES[2]]
    if (
        len(clocks) != 1
        or clocks[0]["id"] != 1
        or clocks[0]["progress_version"] != image["version"]
    ):
        raise ValueError("Role progress recovery version is invalid.")
    current_clock = db.execute(
        "SELECT * FROM cwl_pool_role_clock WHERE id=1"
    ).fetchone()
    if image["version"] < current_clock["progress_version"]:
        return {"restored": 0, "older": True}
    settings = {row["pool"]: row for row in decoded[PROGRESS_TABLES[0]]}
    current = {
        row["pool"]: dict(row)
        for row in db.execute("SELECT * FROM cwl_pool_role_settings")
    }
    compatible = {
        pool
        for pool, row in settings.items()
        if pool in current
        and row["role_id"] is not None
        and (row["role_id"], row["revision"])
        == (current[pool]["role_id"], current[pool]["revision"])
    }
    restored = 0
    for job in decoded[PROGRESS_TABLES[1]]:
        if job["pool"] not in compatible or not _valid(db, job):
            continue
        if job["state"] not in ("pending", "leased", "done", "failed", "superseded"):
            raise ValueError("Invalid recovered role state.")
        existing = db.execute(
            "SELECT * FROM cwl_pool_role_jobs WHERE id=?", (job["id"],)
        ).fetchone()
        if existing:
            if (
                existing["generation"] != job["generation"]
                or existing["job_key"] != job["job_key"]
                or existing["intent"] != job["intent"]
            ):
                continue
            if existing["state"] in ("done", "failed", "superseded") and job[
                "state"
            ] in ("pending", "leased"):
                continue
            fields = (
                "state",
                "attempts",
                "next_at",
                "lease_token",
                "lease_until",
                "message",
                "cursor",
                "cycle_cutoff",
            )
            db.execute(
                "UPDATE cwl_pool_role_jobs SET "
                + ",".join(field + "=?" for field in fields)
                + " WHERE id=?",
                tuple(job[field] for field in fields) + (job["id"],),
            )
        elif (
            job["kind"] in ("scan", "remove")
            and job["job_key"].startswith(
                f"expiry:{job['pool']}:{job['setting_revision']}:"
            )
            and job["cycle_cutoff"] > 0
        ):
            columns = tables[PROGRESS_TABLES[1]]["columns"]
            db.execute(
                "INSERT INTO cwl_pool_role_jobs ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(job[column] for column in columns),
            )
        else:
            continue  # Never restore a signup intent missing from the authoritative head.
        restored += 1
    for pool in compatible:
        old, new = current[pool]["next_expiry"], settings[pool]["next_expiry"]
        if new and (
            not old or datetime.fromisoformat(new) > datetime.fromisoformat(old)
        ):
            db.execute(
                "UPDATE cwl_pool_role_settings SET next_expiry=? WHERE pool=?",
                (new, pool),
            )
    for row in decoded[PROGRESS_TABLES[3]]:
        if not row["action"].startswith("role_") or row["pool"] not in compatible:
            continue
        try:
            job_id = json.loads(row["details_json"])["job_id"]
        except (ValueError, KeyError, TypeError):
            continue
        if not db.execute(
            "SELECT 1 FROM cwl_pool_role_jobs WHERE id=? AND pool=? AND role_id=?",
            (job_id, row["pool"], row["role_id"]),
        ).fetchone():
            continue
        columns = tables[PROGRESS_TABLES[3]]["columns"]
        db.execute(
            "INSERT OR IGNORE INTO cwl_pool_role_audit ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")",
            tuple(row[column] for column in columns),
        )
    db.execute(
        "UPDATE cwl_pool_role_clock SET progress_version=MAX(progress_version,?),next_at=MAX(next_at,?),last_prune=MAX(last_prune,?),last_backup_attempt=MAX(last_backup_attempt,?),last_backup_version=MAX(last_backup_version,?) WHERE id=1",
        tuple(
            clocks[0][field]
            for field in (
                "progress_version",
                "next_at",
                "last_prune",
                "last_backup_attempt",
                "last_backup_version",
            )
        ),
    )
    return {"restored": restored, "older": False}


def local_progress(path):
    """Read only the actual local copy preserved by this startup's restore."""
    import sqlite3
    from pathlib import Path

    source = Path(path)
    if not source.is_file():
        return None
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("Local role progress integrity check failed.")
        return progress_image(db)

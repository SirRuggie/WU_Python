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
 kind TEXT NOT NULL, user_id TEXT, cursor TEXT NOT NULL DEFAULT '0',
 generation INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until REAL, message TEXT,
 created_at REAL NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS cwl_pool_roles_ready
 ON cwl_pool_role_jobs(state,next_at,created_at);
CREATE TABLE IF NOT EXISTS cwl_pool_role_clock (
 id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL
);
INSERT OR IGNORE INTO cwl_pool_role_clock VALUES (1,0);
CREATE TABLE IF NOT EXISTS cwl_pool_role_audit (
 id INTEGER PRIMARY KEY, pool TEXT NOT NULL, role_id TEXT, user_id TEXT,
 actor_id TEXT, action TEXT NOT NULL, details_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Conflict(ValueError):
    pass


def members(db, pool):
    return [
        r[0]
        for r in db.execute(
            "SELECT DISTINCT s.user_id FROM signups s JOIN seasons x ON x.id=s.season_id "
            "WHERE x.status='draft' AND s.pool=? AND s.user_id<>'' "
            "AND s.user_id NOT GLOB '*[^0-9]*' ORDER BY s.user_id",
            (pool,),
        )
        if ID.fullmatch(r[0])
    ]


def member_basis(db, pool):
    return hashlib.sha256(json.dumps(members(db, pool)).encode()).hexdigest()


def initialize(db):
    db.executescript(SCHEMA)

    # Every signup source, including staff changes, uses this same atomic outbox.
    # Blank settings bypass it entirely. No network failure can fail a signup.
    def enqueue(uid, pool):
        return f"""
        INSERT INTO cwl_pool_role_jobs
          (id,job_key,pool,role_id,setting_revision,kind,user_id)
        SELECT lower(hex(randomblob(16))),
          'sync:'||r.pool||':'||{uid}||':'||r.revision,
          r.pool,r.role_id,r.revision,'sync',{uid}
        FROM cwl_pool_role_settings r WHERE r.pool={pool}
          AND r.role_id IS NOT NULL AND {uid}<>''
          AND {uid} NOT GLOB '*[^0-9]*' AND length({uid}) BETWEEN 15 AND 22
          AND substr({uid},1,1)<>'0'
        ON CONFLICT(job_key) DO UPDATE SET generation=generation+1,
          state='pending',attempts=0,next_at=0,lease_token=NULL,lease_until=NULL;
        """

    for event, name, body in (
        ("INSERT", "insert", enqueue("NEW.user_id", "NEW.pool")),
        ("DELETE", "delete", enqueue("OLD.user_id", "OLD.pool")),
        (
            "UPDATE",
            "update",
            enqueue("OLD.user_id", "OLD.pool") + enqueue("NEW.user_id", "NEW.pool"),
        ),
    ):
        db.executescript(
            f"CREATE TRIGGER IF NOT EXISTS cwl_pool_role_{name} "
            f"AFTER {event} ON signups BEGIN {body} END;"
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
        counts = {
            r[0]: r[1]
            for r in db.execute(
                "SELECT state,COUNT(*) FROM cwl_pool_role_jobs WHERE pool=? "
                "AND setting_revision=? GROUP BY state",
                (row["pool"], row["revision"]),
            )
        }
        failure = db.execute(
            "SELECT message FROM cwl_pool_role_jobs WHERE pool=? AND "
            "setting_revision=? AND message<>'' AND state IN ('failed','pending') ORDER BY created_at DESC LIMIT 1",
            (row["pool"], row["revision"]),
        ).fetchone()
        setting.update(
            member_count=len(members(db, row["pool"])),
            member_basis=member_basis(db, row["pool"]),
            progress=counts,
            failure=failure[0] if failure else None,
        )
        result.append(setting)
    return {"pools": result}


def _insert(db, key, setting, kind, uid=None):
    db.execute(
        "INSERT OR IGNORE INTO cwl_pool_role_jobs"
        "(id,job_key,pool,role_id,setting_revision,kind,user_id) VALUES (?,?,?,?,?,?,?)",
        (
            uuid4().hex,
            key,
            setting["pool"],
            setting["role_id"],
            setting.get("revision", setting.get("setting_revision")),
            kind,
            uid,
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
    now = now or datetime.now(timezone.utc)
    next_expiry = (
        expires_at_for(now, section="MAIN" if pool == "main" else "FWA").isoformat()
        if role_id
        else None
    )
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
    setting = dict(old) | {"role_id": role_id, "revision": revision + 1}
    if role_id:
        for uid in members(db, pool):
            _insert(db, f"sync:{pool}:{uid}:{revision+1}", setting, "sync", uid)
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
        setting = dict(row)
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
        job["user_id"] in members(db, row[0])
        for row in db.execute(
            "SELECT pool FROM cwl_pool_role_settings WHERE role_id=?", (job["role_id"],)
        )
    )


def claim(db, *, now=None):
    now = now or datetime.now(timezone.utc)
    _due(db, now)
    stamp = now.timestamp()
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state='pending',lease_token=NULL WHERE state='leased' "
        "AND lease_until<=?",
        (stamp,),
    )
    db.execute(
        "UPDATE cwl_pool_role_jobs SET state='superseded' WHERE state='pending' AND NOT EXISTS "
        "(SELECT 1 FROM cwl_pool_role_settings r WHERE r.pool=cwl_pool_role_jobs.pool "
        "AND r.role_id=cwl_pool_role_jobs.role_id AND r.revision=cwl_pool_role_jobs.setting_revision)"
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
    }


def owned(db, job_id, token, generation):
    row = db.execute(
        "SELECT * FROM cwl_pool_role_jobs WHERE id=? AND state='leased' "
        "AND lease_token=? AND generation=?",
        (job_id, token, generation),
    ).fetchone()
    return dict(row) if row and _valid(db, row) else None


def validate(db, job_id, token, generation):
    job = owned(db, job_id, token, generation)
    return {
        "valid": bool(job),
        "desired": desired(db, job) if job and job["kind"] != "scan" else None,
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

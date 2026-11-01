"""Relational dashboard working copy with optional Mongo commit protection."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


from .push import SCHEMA as PUSH_SCHEMA
from utils.cwl_roster_image_store import SCHEMA as ROSTER_IMAGE_SCHEMA
from utils.owner_prank_store import SCHEMA as OWNER_PRANK_SCHEMA

SCHEMA = PUSH_SCHEMA + ROSTER_IMAGE_SCHEMA + OWNER_PRANK_SCHEMA + """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS roster_test_messages (
 id TEXT PRIMARY KEY, season_id INTEGER NOT NULL, pool TEXT NOT NULL,
 channel_id TEXT NOT NULL, actor_id TEXT NOT NULL, url TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS seasons (
 id INTEGER PRIMARY KEY, label TEXT NOT NULL UNIQUE, signup_open INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','archived'))
);
CREATE TABLE IF NOT EXISTS member_season (
 id INTEGER PRIMARY KEY CHECK(id=1), season_id INTEGER REFERENCES seasons(id),
 revision INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO member_season(id,season_id)
 SELECT 1, (SELECT id FROM seasons WHERE status='draft' ORDER BY id DESC LIMIT 1);
CREATE TABLE IF NOT EXISTS manage_campaign_bindings (
 season_id INTEGER PRIMARY KEY REFERENCES seasons(id), cycle TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS clans (
 tag TEXT PRIMARY KEY, name TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lineup (
 season_id INTEGER NOT NULL REFERENCES seasons(id), tag TEXT NOT NULL REFERENCES clans(tag),
 PRIMARY KEY(season_id,tag)
);
CREATE TABLE IF NOT EXISTS grants (
 user_id TEXT PRIMARY KEY, granted_by TEXT NOT NULL, granted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, username TEXT NOT NULL,
 guild_owner INTEGER NOT NULL, csrf TEXT NOT NULL, expires_at INTEGER NOT NULL,
 display_name TEXT, avatar_url TEXT
);
CREATE TABLE IF NOT EXISTS oauth_states (
state_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS signups (
 season_id INTEGER NOT NULL REFERENCES seasons(id), tag TEXT NOT NULL,
 user_id TEXT NOT NULL, pool TEXT NOT NULL CHECK(pool IN ('main','lazy')),
 prefer_crystal_1_or_lower INTEGER NOT NULL,
 player_name TEXT NOT NULL, town_hall INTEGER NOT NULL,
 signup_clan_tag TEXT, signup_clan_name TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(season_id,tag)
);
CREATE INDEX IF NOT EXISTS signups_owner ON signups(season_id,user_id,pool);
CREATE TABLE IF NOT EXISTS lineup_rules (
 season_id INTEGER NOT NULL, tag TEXT NOT NULL,
 pool TEXT CHECK(pool IN ('main','lazy')), capacity INTEGER CHECK(capacity IN (15,30)),
 min_weight INTEGER, max_weight INTEGER,
 -- unused since 2026-10-27; safe to drop later
 lower_league INTEGER CHECK(lower_league IN (0,1)),
 PRIMARY KEY(season_id,tag),
 FOREIGN KEY(season_id,tag) REFERENCES lineup(season_id,tag) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS roster_entries (
 season_id INTEGER NOT NULL, tag TEXT NOT NULL,
 source_weight INTEGER, source_status TEXT NOT NULL DEFAULT 'missing'
   CHECK(source_status IN ('missing','current','unavailable')),
 source_name TEXT, source_checked_at TEXT, source_modified_at TEXT,
 manual_weight INTEGER, assigned_clan_tag TEXT, kept INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(season_id,tag),
 FOREIGN KEY(season_id,tag) REFERENCES signups(season_id,tag) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS roster_meta (
 season_id INTEGER PRIMARY KEY REFERENCES seasons(id), revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS roster_audit (
 id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL, tag TEXT,
 actor_id TEXT NOT NULL, action TEXT NOT NULL,
 before_json TEXT, after_json TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS roster_audit_season ON roster_audit(season_id,id);
CREATE TABLE IF NOT EXISTS signup_activity_reviews (
 audit_id INTEGER PRIMARY KEY REFERENCES roster_audit(id),
 reviewed_by TEXT NOT NULL, reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS roster_undo (
 id INTEGER PRIMARY KEY,
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 actor_id TEXT NOT NULL,
 label TEXT NOT NULL,
 revision INTEGER NOT NULL,
 changes_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 consumed_at TEXT,
 UNIQUE(season_id,revision)
);
CREATE INDEX IF NOT EXISTS roster_undo_actor ON roster_undo(season_id,actor_id,revision DESC);
CREATE TABLE IF NOT EXISTS roster_publications (
 id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
 version INTEGER NOT NULL, revision INTEGER NOT NULL,
 published_by TEXT NOT NULL, published_at TEXT NOT NULL,
 joining_instructions TEXT NOT NULL,
 assigned_count INTEGER NOT NULL, unassigned_count INTEGER NOT NULL,
 clans_json TEXT NOT NULL,
 UNIQUE(season_id,version)
);
CREATE INDEX IF NOT EXISTS publications_latest ON roster_publications(season_id,version DESC);
CREATE TABLE IF NOT EXISTS publication_accounts (
 publication_id INTEGER NOT NULL REFERENCES roster_publications(id),
 tag TEXT NOT NULL, user_id TEXT NOT NULL,
 player_name TEXT NOT NULL, town_hall INTEGER NOT NULL,
 pool TEXT NOT NULL, prefer_crystal_1_or_lower INTEGER NOT NULL,
 signup_clan_tag TEXT, signup_clan_name TEXT,
 assigned_clan_tag TEXT, assigned_clan_name TEXT,
 source_weight INTEGER, source_status TEXT, source_name TEXT,
 source_checked_at TEXT, source_modified_at TEXT,
 manual_weight INTEGER, effective_weight INTEGER, kept INTEGER NOT NULL,
 PRIMARY KEY(publication_id,tag)
);
CREATE INDEX IF NOT EXISTS publication_accounts_owner ON publication_accounts(publication_id,user_id);
CREATE TABLE IF NOT EXISTS announcement_channels (
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 pool TEXT NOT NULL CHECK(pool IN ('main','lazy')),
 channel_id TEXT NOT NULL, channel_name TEXT NOT NULL,
 configured_by TEXT NOT NULL, configured_at TEXT NOT NULL,
 PRIMARY KEY(season_id,pool)
);
CREATE TABLE IF NOT EXISTS announcement_deliveries (
 id INTEGER PRIMARY KEY,
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 publication_version INTEGER NOT NULL,
 pool TEXT NOT NULL CHECK(pool IN ('main','lazy')),
 channel_id TEXT NOT NULL,
 nonce TEXT NOT NULL,
 content TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('sending','sent','uncertain','failed')),
 requested_by TEXT NOT NULL, requested_at TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 1,
 message_id TEXT, sent_at TEXT, failure TEXT,
 UNIQUE(season_id,publication_version,pool,channel_id)
);
CREATE INDEX IF NOT EXISTS announcement_deliveries_status ON announcement_deliveries(season_id,pool,publication_version);
CREATE TABLE IF NOT EXISTS participation_records (
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 tag TEXT NOT NULL,
 recorded_publication_version INTEGER NOT NULL,
 user_id TEXT NOT NULL,
 player_name TEXT NOT NULL,
 town_hall INTEGER NOT NULL,
 pool TEXT NOT NULL CHECK(pool IN ('main','lazy')),
 assigned_clan_tag TEXT, assigned_clan_name TEXT,
 attacks INTEGER CHECK(attacks IS NULL OR attacks BETWEEN 0 AND 7),
 stars INTEGER CHECK(stars IS NULL OR stars BETWEEN 0 AND 21),
 notes TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1,
 updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(season_id,tag),
 CHECK(stars IS NULL OR attacks IS NULL OR stars <= attacks * 3)
);
CREATE TABLE IF NOT EXISTS participation_audit (
 id INTEGER PRIMARY KEY,
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 tag TEXT NOT NULL,
 actor_id TEXT NOT NULL,
 revision INTEGER NOT NULL,
 before_json TEXT, after_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS participation_audit_season ON participation_audit(season_id,tag,id);
CREATE TABLE IF NOT EXISTS participation_sync_settings (
 season_id INTEGER PRIMARY KEY REFERENCES seasons(id),
 cycle TEXT NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 status TEXT NOT NULL DEFAULT 'never',
 warning TEXT,
 last_checked_at TEXT, last_success_at TEXT,
 updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS participation_group_observations (
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 cycle TEXT NOT NULL,
 clan_tag TEXT NOT NULL,
 season TEXT NOT NULL,
 state TEXT NOT NULL,
 war_tags_json TEXT NOT NULL,
 members_json TEXT,
 observed_at TEXT NOT NULL,
 PRIMARY KEY(season_id,cycle,clan_tag)
);
CREATE TABLE IF NOT EXISTS participation_war_observations (
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 cycle TEXT NOT NULL,
 war_tag TEXT NOT NULL,
 clan_tag TEXT NOT NULL,
 state TEXT NOT NULL,
 ended INTEGER NOT NULL CHECK(ended IN (0,1)),
 attacks_json TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 PRIMARY KEY(season_id,cycle,war_tag,clan_tag)
);
CREATE TABLE IF NOT EXISTS participation_war_fetches (
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 cycle TEXT NOT NULL,
 war_tag TEXT NOT NULL,
 ended INTEGER NOT NULL CHECK(ended IN (0,1)),
 scanned_clans_json TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 PRIMARY KEY(season_id,cycle,war_tag)
);
CREATE TABLE IF NOT EXISTS bonus_reviews (
 season_id INTEGER PRIMARY KEY REFERENCES seasons(id),
 revision INTEGER NOT NULL DEFAULT 0,
 min_attacks INTEGER CHECK(min_attacks IS NULL OR min_attacks BETWEEN 0 AND 7),
 min_stars INTEGER CHECK(min_stars IS NULL OR min_stars BETWEEN 0 AND 21),
 cooldown_months INTEGER CHECK(cooldown_months IS NULL OR cooldown_months BETWEEN 0 AND 24),
 updated_by TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS bonus_clan_slots (
 season_id INTEGER NOT NULL REFERENCES seasons(id), clan_tag TEXT NOT NULL,
 slots INTEGER CHECK(slots IS NULL OR slots BETWEEN 0 AND 50),
 PRIMARY KEY(season_id,clan_tag)
);
CREATE TABLE IF NOT EXISTS bonus_draft_selections (
 season_id INTEGER NOT NULL REFERENCES seasons(id), tag TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(season_id,tag)
);
CREATE TABLE IF NOT EXISTS bonus_batches (
 id INTEGER PRIMARY KEY,
 season_id INTEGER NOT NULL REFERENCES seasons(id), cycle TEXT NOT NULL,
 base_revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
 snapshot_json TEXT NOT NULL,
 confirmed_by TEXT NOT NULL, confirmed_at TEXT NOT NULL,
 UNIQUE(season_id,base_revision,fingerprint)
);
CREATE TABLE IF NOT EXISTS bonus_confirmations (
 id INTEGER PRIMARY KEY,
 batch_id INTEGER NOT NULL REFERENCES bonus_batches(id),
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 cycle TEXT NOT NULL, publication_version INTEGER NOT NULL,
 tag TEXT NOT NULL, player_name TEXT NOT NULL,
 pool TEXT NOT NULL, clan_tag TEXT NOT NULL, clan_name TEXT,
 attacks INTEGER, stars INTEGER, reason TEXT NOT NULL,
 warnings_json TEXT NOT NULL,
 confirmed_by TEXT NOT NULL, confirmed_at TEXT NOT NULL,
 voided_by TEXT, voided_at TEXT, void_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS bonus_active_cycle_tag
 ON bonus_confirmations(cycle,tag) WHERE voided_at IS NULL;
CREATE INDEX IF NOT EXISTS bonus_history_season ON bonus_confirmations(season_id,id);
CREATE INDEX IF NOT EXISTS bonus_history_tag ON bonus_confirmations(tag,cycle,id);
CREATE TABLE IF NOT EXISTS bonus_audit (
 id INTEGER PRIMARY KEY,
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 actor_id TEXT NOT NULL, action TEXT NOT NULL,
 before_json TEXT, after_json TEXT,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bonus_audit_season ON bonus_audit(season_id,id);
CREATE TABLE IF NOT EXISTS participation_source_results (
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 cycle TEXT NOT NULL,
 tag TEXT NOT NULL,
 attacks INTEGER CHECK(attacks IS NULL OR attacks BETWEEN 0 AND 7),
 stars INTEGER CHECK(stars IS NULL OR stars BETWEEN 0 AND 21),
 status TEXT NOT NULL,
 complete INTEGER NOT NULL CHECK(complete IN (0,1)),
 checked_at TEXT, warning TEXT,
 PRIMARY KEY(season_id,cycle,tag),
 CHECK(stars IS NULL OR attacks IS NULL OR stars <= attacks * 3)
);
"""


def signup_timestamps(db, season_id):
    """Current registration dates from durable creation events, never edit times."""
    rows = db.execute(
        "SELECT a.tag,a.created_at FROM roster_audit a JOIN ("
        "SELECT tag,MAX(id) AS id FROM roster_audit WHERE season_id=? "
        "AND action IN ('member_signup','staff_signup') "
        "AND (before_json IS NULL OR before_json='null') GROUP BY tag"
        ") latest ON a.id=latest.id",
        (season_id,),
    ).fetchall()
    return {row["tag"]: row["created_at"].replace(" ", "T") + "Z" for row in rows}


class Store:
    def __init__(self, path: str, durability=None):
        self.durability = None
        self.role_dirty = False
        self.role_backup_error = None
        self.role_next_backup = 0
        self.role_recovery_error = None
        import time

        self.role_started_at = time.time()
        self.role_last_contact = None
        self.path = str(Path(path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as db:
            db.executescript(SCHEMA)
            from utils.roster_player_marks import SCHEMA as MARK_SCHEMA

            db.executescript(MARK_SCHEMA)
            from utils.cwl_roster_image_store import migrate as migrate_image_status

            migrate_image_status(db)
            if "signup_clan_type" not in {
                row[1] for row in db.execute("PRAGMA table_info(signups)")
            }:
                db.execute("ALTER TABLE signups ADD COLUMN signup_clan_type TEXT")
            if "withdrawn_at" not in {
                row[1] for row in db.execute("PRAGMA table_info(roster_publications)")
            }:
                db.execute(
                    "ALTER TABLE roster_publications ADD COLUMN withdrawn_at TEXT"
                )
            from .player_weights import SCHEMA as WEIGHT_SCHEMA, migrate

            db.executescript(WEIGHT_SCHEMA)
            if "permissions" not in {
                row["name"] for row in db.execute("PRAGMA table_info(grants)")
            }:
                db.execute(
                    "ALTER TABLE grants ADD COLUMN permissions TEXT NOT NULL DEFAULT '[\"cwl\"]'"
                )
            clan_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(clans)")
            }
            if "pool" not in clan_columns:
                db.execute(
                    "ALTER TABLE clans ADD COLUMN pool TEXT CHECK(pool IN ('main','lazy'))"
                )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(roster_entries)")
            }
            if "source_modified_at" not in columns:
                db.execute(
                    "ALTER TABLE roster_entries ADD COLUMN source_modified_at TEXT"
                )
            columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
            if "display_name" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN display_name TEXT")
            if "avatar_url" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN avatar_url TEXT")
            if "is_bot" not in columns:
                db.execute(
                    "ALTER TABLE sessions ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0"
                )
            source_columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(participation_source_results)")
            }
            if "roster_token" not in source_columns:
                db.execute(
                    "ALTER TABLE participation_source_results ADD COLUMN roster_token TEXT"
                )
            columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(participation_records)")
            }
            if "attacks_override" not in columns:
                db.execute(
                    "ALTER TABLE participation_records ADD COLUMN attacks_override INTEGER NOT NULL DEFAULT 0"
                )
                db.execute(
                    "UPDATE participation_records SET attacks_override=1 WHERE attacks IS NOT NULL"
                )
            if "stars_override" not in columns:
                db.execute(
                    "ALTER TABLE participation_records ADD COLUMN stars_override INTEGER NOT NULL DEFAULT 0"
                )
                db.execute(
                    "UPDATE participation_records SET stars_override=1 WHERE stars IS NOT NULL"
                )
            columns = {
                row["name"]
                for row in db.execute(
                    "PRAGMA table_info(participation_group_observations)"
                )
            }
            if "members_json" not in columns:
                db.execute(
                    "ALTER TABLE participation_group_observations ADD COLUMN members_json TEXT"
                )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(bonus_batches)")
            }
            if "snapshot_json" not in columns:
                db.execute(
                    "ALTER TABLE bonus_batches ADD COLUMN snapshot_json TEXT NOT NULL DEFAULT '{}' "
                )

            from utils.cwl_bonus_raffle_store import SCHEMA as RAFFLE_SCHEMA

            db.executescript(RAFFLE_SCHEMA)
            from utils.cwl_bonus_allowance import SCHEMA as ALLOWANCE_SCHEMA

            db.executescript(ALLOWANCE_SCHEMA)
            migrate(db)
            from utils.clan_weight_store import initialize as initialize_clan_weights

            initialize_clan_weights(db)
            from utils.cwl_pool_roles import initialize as initialize_pool_roles

            initialize_pool_roles(db)
        self.durability = durability
        self._recover_role_progress()

    @contextmanager
    def tx(self):
        if self.durability:
            self.durability.check()
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            before = db.total_changes
            yield db
            if self.durability and db.total_changes != before:
                self.durability.publish(db)
            try:
                db.commit()
            except Exception:
                if self.durability:
                    self.durability.poisoned = True
                raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def role_tx(self, *, track=True):
        """Locally durable role-only progress, independent of dashboard publishing.

        Signup intents/settings still use tx(). This path must never mutate them.
        """
        if self.durability:
            self.durability.check()
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            allowed_tables = {
                "cwl_pool_role_jobs",
                "cwl_pool_role_clock",
                "cwl_pool_role_audit",
            }

            def role_authorizer(action, table, column, database, source):
                if action in (
                    sqlite3.SQLITE_INSERT,
                    sqlite3.SQLITE_UPDATE,
                    sqlite3.SQLITE_DELETE,
                ):
                    return (
                        sqlite3.SQLITE_OK
                        if table in allowed_tables
                        or (
                            table == "cwl_pool_role_settings"
                            and action == sqlite3.SQLITE_UPDATE
                            and column == "next_expiry"
                        )
                        else sqlite3.SQLITE_DENY
                    )
                return sqlite3.SQLITE_OK

            db.set_authorizer(role_authorizer)
            before = db.total_changes
            yield db
            if track and db.total_changes != before:
                db.execute(
                    "UPDATE cwl_pool_role_clock SET progress_version=progress_version+1 WHERE id=1"
                )
                self.role_dirty = True
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _recover_role_progress(self):
        if self.durability is None:
            return
        from utils import cwl_pool_roles as roles
        import logging

        try:
            with self.role_tx(track=False) as db:
                configured = db.execute(
                    "SELECT 1 FROM cwl_pool_role_settings WHERE role_id IS NOT NULL"
                ).fetchone()
                if not configured:
                    if hasattr(self.durability, "mark_local_recovery_complete"):
                        self.durability.mark_local_recovery_complete()
                    return
                previous = getattr(self.durability, "previous_local_path", None)
                paths = getattr(self.durability, "previous_local_paths", None) or (
                    [previous] if previous else []
                )
                images = [roles.local_progress(path) for path in paths]
                image = max(
                    (value for value in images if value is not None),
                    key=lambda value: value.get("version", -1),
                    default=None,
                )
                local = image is not None
                if hasattr(self.durability, "load_role_progress"):
                    try:
                        remote = self.durability.load_role_progress()
                        if remote is not None and (
                            image is None
                            or remote.get("version", -1) > image.get("version", -1)
                        ):
                            image, local = remote, False
                    except Exception:
                        if image is None:
                            raise
                if image is not None:
                    recovery = roles.recover_progress(db, image)
                    if recovery.get("older") or recovery.get("uncovered"):
                        local = False
                unfinished = db.execute(
                    "SELECT 1 FROM cwl_pool_role_jobs WHERE state IN ('pending','leased') LIMIT 1"
                ).fetchone()
                if (not local and unfinished) or getattr(
                    self.durability, "local_recovery_interrupted", False
                ):
                    roles.pause_recovery(db)
                if roles.recovery_paused(db):
                    self.role_recovery_error = "Role work is paused after recovery. Check roles, turn both settings off, then save them again. Signups are unchanged."
                clock = db.execute(
                    "SELECT progress_version,last_backup_version FROM cwl_pool_role_clock WHERE id=1"
                ).fetchone()
                self.role_dirty = clock[0] > clock[1]
            if hasattr(self.durability, "mark_local_recovery_complete"):
                self.durability.mark_local_recovery_complete()
        except Exception:
            with self.role_tx(track=False) as db:
                roles.pause_recovery(db)
                clock = db.execute(
                    "SELECT progress_version,last_backup_version FROM cwl_pool_role_clock WHERE id=1"
                ).fetchone()
                self.role_dirty = clock[0] > clock[1]
            self.role_recovery_error = "Role progress could not be recovered. Check roles, turn both settings off, then save them again. Signups are unchanged."
            logging.getLogger(__name__).warning(
                "Role progress recovery unavailable; role work paused"
            )

    def flush_role_progress(self, *, now=None):
        """Called off the event loop. At most one independent backup per minute."""
        import time
        import logging
        from utils import cwl_pool_roles as roles

        if self.durability is None or not self.role_dirty:
            return {"attempted": False}
        at = time.time() if now is None else now
        with self.role_tx(track=False) as db:
            clock = db.execute(
                "SELECT * FROM cwl_pool_role_clock WHERE id=1"
            ).fetchone()
            if not db.execute(
                "SELECT 1 FROM cwl_pool_role_settings WHERE role_id IS NOT NULL"
            ).fetchone():
                self.role_dirty = False
                return {"attempted": False}
            if clock["progress_version"] <= clock["last_backup_version"]:
                self.role_dirty = False
                return {"attempted": False}
            if at - clock["last_backup_attempt"] < 60:
                return {"attempted": False}
            db.execute(
                "UPDATE cwl_pool_role_clock SET last_backup_attempt=? WHERE id=1", (at,)
            )
            image = roles.progress_image(db)
        try:
            if self.durability.save_role_progress(image) is not True:
                raise RuntimeError("Role backup compare-and-swap was not accepted")
        except Exception:
            # This writes a separate recovery document, never the dashboard head.
            # A lost acknowledgement is safe to replace after the minute cooldown.
            self.role_backup_error = (
                "Role progress backup is unavailable. Signups are unchanged."
            )
            logging.getLogger(__name__).warning(
                "Role progress backup unavailable; dashboard durability remains independent"
            )
            return {"attempted": True, "published": False, "version": image["version"]}
        with self.role_tx(track=False) as db:
            db.execute(
                "UPDATE cwl_pool_role_clock SET last_backup_version=MAX(last_backup_version,?) WHERE id=1",
                (image["version"],),
            )
            current = db.execute(
                "SELECT progress_version FROM cwl_pool_role_clock WHERE id=1"
            ).fetchone()[0]
            self.role_dirty = current > image["version"]
        self.role_backup_error = None
        return {
            "attempted": True,
            "published": True,
            "version": image["version"],
            "bytes": len(image["payload"]),
        }

    def rows(self, sql, args=()):
        if self.durability:
            self.durability.check()
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def signup_activity(self, season_id):
        """One durable audit event per change; reviewed events remain in audit history."""
        with self.tx() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT a.* FROM roster_audit a LEFT JOIN signup_activity_reviews r ON r.audit_id=a.id "
                    "WHERE a.season_id=? AND a.action IN ('member_withdrawal','member_pool_change') "
                    "AND NULLIF(TRIM(json_extract(a.before_json, '$.assigned_clan_tag')), '') IS NOT NULL "
                    "AND r.audit_id IS NULL ORDER BY a.id DESC LIMIT 100",
                    (season_id,),
                )
            ]

    def review_signup_activity(self, season_id, audit_id, actor):
        with self.tx() as db:
            row = db.execute(
                "SELECT id FROM roster_audit WHERE season_id=? AND id=? AND action IN ('member_withdrawal','member_pool_change')",
                (season_id, audit_id),
            ).fetchone()
            if row is None:
                return False
            db.execute(
                "INSERT OR IGNORE INTO signup_activity_reviews(audit_id,reviewed_by) VALUES (?,?)",
                (audit_id, actor),
            )
            return True

    def member_season(self):
        return self.one("SELECT season_id,revision FROM member_season WHERE id=1")

    def set_member_season(self, season_id, revision, actor):
        with self.tx() as db:
            current = dict(
                db.execute(
                    "SELECT season_id,revision FROM member_season WHERE id=1"
                ).fetchone()
            )
            if current["revision"] != revision:
                raise RuntimeError("The member season changed. Refresh and try again.")
            if season_id is not None:
                season = db.execute(
                    "SELECT status FROM seasons WHERE id=?", (season_id,)
                ).fetchone()
                if not season or season["status"] != "draft":
                    raise ValueError("Choose a non-archived season.")
            db.execute(
                "UPDATE member_season SET season_id=?,revision=revision+1 WHERE id=1",
                (season_id,),
            )
            import json

            db.execute(
                "INSERT INTO roster_audit(season_id,actor_id,action,before_json,after_json) VALUES (?,?,?,?,?)",
                (
                    season_id or current["season_id"] or 0,
                    actor,
                    "member_season_change",
                    json.dumps(current),
                    json.dumps({"season_id": season_id}),
                ),
            )
            return dict(
                db.execute(
                    "SELECT season_id,revision FROM member_season WHERE id=1"
                ).fetchone()
            )

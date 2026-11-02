"""Official clan weights keyed by player tag; migrated in place from the former trial ledger."""

import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS clan_weight_war_lineups (
 clan_tag TEXT PRIMARY KEY, end_time TEXT NOT NULL, captured_at TEXT NOT NULL, lineup_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clan_weight_war_lineup_previous (
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
"""


class WeightConflict(ValueError):
    pass


def validate_weight(weight, storages=None):
    """Shared write validation; reads never normalize historical saved values."""
    if storages is not None and (type(storages) is not int or not 1 <= storages <= 5):
        raise ValueError("Storages must be a whole number from 1 to 5.")
    if weight is not None:
        if type(weight) is not int or not 1000 <= weight <= 999999 or weight % 1000:
            raise ValueError(
                "Full weight must be a whole multiple of 1,000. Correct Loot or Full; leave blank for Not Available."
            )
        if storages is not None and weight % storages:
            raise ValueError(
                "Full weight must be divisible by the storage count. Correct Loot or Storages."
            )


def effective_weights(db, tags):
    """Resolve retained legacy and linked rows by aware saved time.

    Equal instants favor the linked ledger, including an intentional blank.
    The revision always belongs to that ledger, regardless of the winning value.
    """
    tags = tuple(tags)
    if not tags:
        return {}
    placeholders = ",".join("?" for _ in tags)
    result = {
        row["tag"]: dict(row)
        for row in db.execute(
            "SELECT * FROM clan_player_weights WHERE tag IN (" + placeholders + ")",
            tags,
        )
    }
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='player_weights'"
    ).fetchone():
        return result

    def instant(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(
                "Saved weight timestamp has no timezone; reconcile before editing."
            )
        return parsed.astimezone(timezone.utc)

    for raw in db.execute(
        "SELECT * FROM player_weights WHERE tag IN (" + placeholders + ")", tags
    ):
        legacy = dict(raw)
        current = result.get(legacy["tag"])
        legacy_time = instant(legacy["updated_at"])
        if current is not None and legacy_time <= instant(current["updated_at"]):
            continue
        result[legacy["tag"]] = {
            **(
                current
                or {
                    "tag": legacy["tag"],
                    "revision": 0,
                    "player_name": legacy["tag"],
                    "town_hall": None,
                    "last_clan_tag": "",
                    "last_clan_name": "",
                    "actor_id": "",
                }
            ),
            "weight": legacy["weight"],
            "updated_at": legacy["updated_at"],
            "storages": None,
            "source": "Roster",
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
            rows = db.execute(
                "SELECT tag FROM clan_player_weights ORDER BY last_clan_name,player_name,tag"
            ).fetchall()
            resolved = effective_weights(db, [row["tag"] for row in rows])
            return [resolved[row["tag"]] for row in rows]

    def for_members(self, tags):
        if not tags:
            return {}
        with self.connect() as db:
            return effective_weights(db, tags)

    def last_saved(self, clan_tag):
        with self.connect() as db:
            row = db.execute(
                "SELECT updated_at,actor_id,actor_name FROM clan_player_weight_history WHERE clan_tag=? ORDER BY id DESC LIMIT 1",
                (clan_tag,),
            ).fetchone()
            return dict(row) if row else None

    def search(self, query, *, limit=25, offset=0):
        # instr treats %, _ and backslash literally; only saved rows are searched.
        with self.connect() as db:
            db.create_function(
                "weight_casefold",
                1,
                lambda value: str(value or "").casefold(),
                deterministic=True,
            )
            args = (query.casefold(), query.upper())
            predicate = (
                "instr(weight_casefold(player_name), ?) > 0 OR instr(upper(tag), ?) > 0"
            )
            total = db.execute(
                "SELECT COUNT(*) FROM clan_player_weights WHERE " + predicate, args
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM clan_player_weights WHERE "
                + predicate
                + " ORDER BY player_name COLLATE NOCASE,tag LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
            resolved = effective_weights(db, [row["tag"] for row in rows])
            return {"players": [resolved[row["tag"]] for row in rows], "total": total}

    @staticmethod
    def _invalidate(db, changed_tags):
        if (
            changed_tags
            and db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='roster_meta'"
            ).fetchone()
        ):
            placeholders = ",".join("?" for _ in changed_tags)
            db.execute(
                "INSERT INTO roster_meta(season_id,revision) SELECT DISTINCT s.season_id,1 "
                "FROM signups s JOIN seasons se ON se.id=s.season_id "
                "WHERE se.status='draft' AND s.tag IN (" + placeholders + ") "
                "ON CONFLICT(season_id) DO UPDATE SET revision=revision+1",
                tuple(changed_tags),
            )

    @staticmethod
    def _write(
        db, change, current, member, clan, actor, actor_name, now, source="Clan weights"
    ):
        revision = current["revision"] if current else 0
        storages = change.get("storages", current["storages"] if current else None)
        effective = effective_weights(db, [change["tag"]]).get(change["tag"])
        same = (
            current
            and effective["weight"] == change["weight"]
            and effective["storages"] == storages
        )
        if not same:
            validate_weight(change["weight"], storages)
        if revision != change["revision"] and not same:
            raise WeightConflict("Changed by someone else · Reload")
        if same:
            return False  # Includes unchanged legacy values and lost-response retries.
        db.execute(
            "INSERT OR REPLACE INTO clan_player_weights("
            "tag,weight,revision,player_name,town_hall,last_clan_tag,last_clan_name,updated_at,actor_id,storages) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                change["tag"],
                change["weight"],
                revision + 1,
                member["name"],
                member["town_hall"],
                clan["tag"],
                clan["name"],
                now,
                actor,
                storages,
            ),
        )
        db.execute(
            "INSERT INTO clan_player_weight_history("
            "tag,weight,revision,clan_tag,actor_id,updated_at,storages,actor_name,source) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                change["tag"],
                change["weight"],
                revision + 1,
                clan["tag"],
                actor,
                now,
                storages,
                actor_name,
                source,
            ),
        )
        return True

    def save(self, roster, changes, actor, actor_name=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            # The server's fresh roster plus this transaction's two saved lineups
            # are the creation boundary. Never trust the client's displayed rows.
            members = self.members_with_lineups(roster, db=db)
            members = {row["tag"]: row for row in members}
            changed_tags = []
            for change in changes:
                if change["tag"] not in members:
                    raise WeightConflict(
                        "This player is not a current member or in either saved war lineup. Refresh members before saving."
                    )
                current = db.execute(
                    "SELECT * FROM clan_player_weights WHERE tag=?", (change["tag"],)
                ).fetchone()
                if self._write(
                    db,
                    change,
                    current,
                    members[change["tag"]],
                    roster,
                    actor,
                    actor_name,
                    now,
                ):
                    changed_tags.append(change["tag"])
            self._invalidate(db, changed_tags)
        return self.for_members(members)

    def has_saved_player(self, player_tag):
        with self.connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM clan_player_weights WHERE tag=?", (player_tag,)
                ).fetchone()
                is not None
            )

    def save_existing(
        self, player_tag, change, actor, actor_name=None, *, lineup_clans=None
    ):
        """Explicit saved-player edit: existence, CAS, audit and invalidation are atomic.

        Preserve the saved clan/name provenance rather than claiming that an
        unavailable or departed player's location was verified by this edit.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT * FROM clan_player_weights WHERE tag=?", (player_tag,)
            ).fetchone()
            if current is None:
                options = []
                for clan_tag, clan in (lineup_clans or {}).items():
                    for lineup in self._lineups(db, clan_tag):
                        if player_tag in lineup["order"]:
                            options.append(
                                (lineup.get("end_time") or "", clan_tag, clan, lineup)
                            )
                if not options:
                    raise WeightConflict(
                        "This player has no saved clan weight. Open their current FWA clan to add one."
                    )
                _, _, clan, lineup = max(options, key=lambda item: item[:2])
                member = {
                    "name": (lineup.get("names") or {}).get(player_tag) or player_tag,
                    "town_hall": (lineup.get("town_halls") or {}).get(player_tag),
                }
            else:
                member = {
                    "name": current["player_name"],
                    "town_hall": current["town_hall"],
                }
                clan = {
                    "tag": current["last_clan_tag"],
                    "name": current["last_clan_name"],
                }
            changed = self._write(
                db,
                {**change, "tag": player_tag},
                current,
                member,
                clan,
                actor,
                actor_name,
                now,
            )
            self._invalidate(db, [player_tag] if changed else [])
            return dict(
                db.execute(
                    "SELECT * FROM clan_player_weights WHERE tag=?", (player_tag,)
                ).fetchone()
            )

    @classmethod
    def save_roster(cls, db, season_id, player_tag, change, actor, actor_name=None):
        """Write through the caller's roster transaction, never a nested connection.

        Signup existence is a creation boundary. Placement undo remains separate;
        the invalidation makes any earlier placement undo stale as before.
        """
        member = db.execute(
            "SELECT * FROM signups WHERE season_id=? AND tag=?", (season_id, player_tag)
        ).fetchone()
        if member is None:
            raise ValueError("Signed-up account not found")
        current = db.execute(
            "SELECT * FROM clan_player_weights WHERE tag=?", (player_tag,)
        ).fetchone()
        changed = cls._write(
            db,
            {**change, "tag": player_tag},
            current,
            {"name": member["player_name"], "town_hall": member["town_hall"]},
            {
                "tag": current["last_clan_tag"] if current else "",
                "name": current["last_clan_name"] if current else "",
            },
            actor,
            actor_name,
            datetime.now(timezone.utc).isoformat(),
            source="Roster",
        )
        cls._invalidate(db, [player_tag] if changed else [])
        return changed

    @staticmethod
    def _lineups(db, clan_tag):
        result = []
        for table in ("clan_weight_war_lineups", "clan_weight_war_lineup_previous"):
            row = db.execute(
                f"SELECT * FROM {table} WHERE clan_tag=?", (clan_tag,)
            ).fetchone()
            if row is not None:
                result.append(
                    {
                        **json.loads(row["lineup_json"]),
                        "cached": True,
                        "captured_at": row["captured_at"],
                    }
                )
        return result

    def saved_lineups(self, clan_tag):
        """The most recent usable lineup and its predecessor, newest first."""
        with self.connect() as db:
            return self._lineups(db, clan_tag)

    def saved_lineup(self, clan_tag):
        rows = self.saved_lineups(clan_tag)
        return rows[0] if rows else None

    def members_with_lineups(self, roster, *, db=None, latest_only=False):
        """Current members plus saved lineup people, without inventing metadata.

        Writes call this under their own immediate transaction, so a third war
        evicting the older lineup invalidates a stale editor's creation rights.
        """
        if db is None:
            with self.connect() as connection:
                return self.members_with_lineups(
                    roster, db=connection, latest_only=latest_only
                )
        rows = {
            member["tag"]: {**member, "current_member": True}
            for member in roster["members"]
        }
        lineups = self._lineups(db, roster["tag"])
        for lineup in lineups[:1] if latest_only else lineups:
            for tag, position in lineup["order"].items():
                if tag not in rows:
                    rows[tag] = {
                        "tag": tag,
                        "name": (lineup.get("names") or {}).get(tag) or tag,
                        "town_hall": (lineup.get("town_halls") or {}).get(tag),
                        "war_position": position,
                        "current_member": False,
                    }
        return list(rows.values())

    def lineup_assignments(self, tags, clan_tags):
        """Resolve a player's newest saved-war clan within verified family clans."""
        wanted = set(tags)
        candidates = []
        with self.connect() as db:
            for clan_tag in clan_tags:
                for lineup in self._lineups(db, clan_tag):
                    for player in wanted.intersection(lineup["order"]):
                        candidates.append(
                            (lineup.get("end_time") or "", clan_tag, player)
                        )
        result = {}
        for _, clan_tag, player in sorted(candidates, reverse=True):
            result.setdefault(player, clan_tag)
        return result

    def remember_lineup(self, clan_tag, lineup):
        if not isinstance(lineup, dict):
            raise ValueError("Incomplete war lineup")
        order = lineup.get("order")
        if (
            lineup.get("state") not in ("preparation", "inWar", "warEnded")
            or not isinstance(order, dict)
            or not 1 <= len(order) <= 50
            or any(
                not isinstance(tag, str)
                or not tag.startswith("#")
                or type(position) is not int
                for tag, position in order.items()
            )
            or set(order.values()) != set(range(1, len(order) + 1))
        ):
            raise ValueError("Incomplete war lineup")
        for field in ("names", "town_halls"):
            values = lineup.get(field)
            if values is None:
                values = {}
            if not isinstance(values, dict) or not set(values) <= set(order):
                raise ValueError("Invalid saved war member details")
            if field == "names" and any(
                not isinstance(value, str) for value in values.values()
            ):
                raise ValueError("Invalid saved war member name")
            if field == "town_halls" and any(
                type(value) is not int or not 0 < value < 100
                for value in values.values()
            ):
                raise ValueError("Invalid saved war member Town Hall")
        end_time = lineup.get("end_time")
        if not end_time:
            return  # An unidentified response cannot replace a saved war.
        ended = datetime.strptime(end_time, "%Y%m%dT%H%M%S.000Z").replace(
            tzinfo=timezone.utc
        )
        stamp = ended.isoformat()
        payload = json.dumps(lineup, sort_keys=True)
        captured = datetime.now(timezone.utc).isoformat()
        states = {"preparation": 0, "inWar": 1, "warEnded": 2}
        with self.connect() as db:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM clan_weight_war_lineups WHERE clan_tag=?", (clan_tag,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO clan_weight_war_lineups(clan_tag,end_time,captured_at,lineup_json) VALUES(?,?,?,?)",
                    (clan_tag, stamp, captured, payload),
                )
                return
            slots = [(row["end_time"], row["captured_at"], row["lineup_json"])]
            prior = db.execute(
                "SELECT * FROM clan_weight_war_lineup_previous WHERE clan_tag=?",
                (clan_tag,),
            ).fetchone()
            if prior is not None:
                slots.append(
                    (prior["end_time"], prior["captured_at"], prior["lineup_json"])
                )
            existing = next((item for item in slots if item[0] == stamp), None)
            if existing:
                previous_payload = json.loads(existing[2])
                if states[previous_payload["state"]] > states[lineup["state"]]:
                    return
                # A later response may omit optional details. Keep known details
                # for people still in this war, without inventing missing ones.
                merged = dict(lineup)
                for field in ("names", "town_halls"):
                    details = {
                        **(previous_payload.get(field) or {}),
                        **(lineup.get(field) or {}),
                    }
                    merged[field] = {
                        tag: value for tag, value in details.items() if tag in order
                    }
                payload = json.dumps(merged, sort_keys=True)
                if existing[2] == payload:
                    return
                slots = [item for item in slots if item[0] != stamp]
            slots.append((stamp, captured, payload))
            slots.sort(key=lambda item: item[0], reverse=True)
            slots = slots[:2]
            latest = slots[0]
            previous = slots[1] if len(slots) > 1 else (None, None, None)
            old_previous = (
                (prior["end_time"], prior["captured_at"], prior["lineup_json"])
                if prior
                else (None, None, None)
            )
            if (
                latest == (row["end_time"], row["captured_at"], row["lineup_json"])
                and previous == old_previous
            ):
                return
            db.execute(
                "UPDATE clan_weight_war_lineups SET end_time=?,captured_at=?,lineup_json=? WHERE clan_tag=?",
                (*latest, clan_tag),
            )
            if previous[0] is not None:
                db.execute(
                    "INSERT INTO clan_weight_war_lineup_previous(clan_tag,end_time,captured_at,lineup_json) VALUES(?,?,?,?) ON CONFLICT(clan_tag) DO UPDATE SET end_time=excluded.end_time,captured_at=excluded.captured_at,lineup_json=excluded.lineup_json",
                    (clan_tag, *previous),
                )


def initialize(db):
    # Rename the existing ledger in place: no duplicate source or lost history.
    tables = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    migrated = False
    for old, new in (
        ("clan_weight_trial", "clan_player_weights"),
        ("clan_weight_trial_history", "clan_player_weight_history"),
    ):
        if old in tables:
            if new in tables:
                raise RuntimeError(
                    "Both legacy and official clan-weight tables exist; reconcile before startup"
                )
            db.execute(f"ALTER TABLE {old} RENAME TO {new}")
            migrated = True
    db.executescript(SCHEMA)
    if migrated and "roster_meta" in tables:
        db.execute(
            "INSERT INTO roster_meta(season_id,revision) SELECT id,1 FROM seasons WHERE status='draft' "
            "ON CONFLICT(season_id) DO UPDATE SET revision=revision+1"
        )
    for table in ("clan_player_weights", "clan_player_weight_history"):
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if "storages" not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN storages INTEGER")
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(clan_player_weight_history)")
    }
    if "actor_name" not in columns:
        db.execute("ALTER TABLE clan_player_weight_history ADD COLUMN actor_name TEXT")
    if "source" not in columns:
        db.execute(
            "ALTER TABLE clan_player_weight_history ADD COLUMN source TEXT NOT NULL DEFAULT 'Clan weights'"
        )
    db.execute(
        "CREATE INDEX IF NOT EXISTS clan_player_weight_history_clan_id ON clan_player_weight_history(clan_tag,id DESC)"
    )
    # SCHEMA adds the bounded predecessor table without rewriting the existing
    # four-column latest-lineup row. Old code can still read/write that row on
    # rollback; the predecessor is retained but ignored until this code returns.

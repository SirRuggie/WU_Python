"""Majority-acknowledged Mongo recovery checkpoints for the dashboard database.

SQLite remains the relational working copy. A changed transaction is published
in Mongo *before* its local commit/success response. Only one leased writer may
publish. Ambiguous writes fence this process until recovery from Mongo on restart.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile
import uuid
import zlib

from pymongo import MongoClient, ReturnDocument, ReadPreference
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from utils.mongo_routes import collection_for

MAX_RAW = 64 * 1024 * 1024
MAX_COMPRESSED = 12 * 1024 * 1024
LEASE_SECONDS = 90


class DashboardDurabilityError(RuntimeError):
    """Do not report success or retry external delivery after this error."""


def utcnow():
    return datetime.now(timezone.utc)


def encode(db):
    raw = "\n".join(db.iterdump()).encode("utf-8")
    if len(raw) > MAX_RAW:
        raise DashboardDurabilityError(
            "Dashboard recovery image exceeds its safe size limit."
        )
    payload = zlib.compress(raw)
    if len(payload) > MAX_COMPRESSED:
        raise DashboardDurabilityError(
            "Dashboard recovery image exceeds its Mongo document limit."
        )
    return {
        "format": 1,
        "payload": payload,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "tables": table_counts(db),
    }


def table_counts(db):
    names = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {
        name: db.execute(
            'SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"'
        ).fetchone()[0]
        for name in names
    }


def decode(document):
    if document.get("format") != 1:
        raise DashboardDurabilityError("Unsupported dashboard recovery format.")
    unpacker = zlib.decompressobj()
    raw = unpacker.decompress(document["payload"], MAX_RAW + 1)
    if (
        len(raw) > MAX_RAW
        or not unpacker.eof
        or unpacker.unused_data
        or len(raw) != document["raw_bytes"]
        or hashlib.sha256(raw).hexdigest() != document["sha256"]
    ):
        raise DashboardDurabilityError(
            "Dashboard recovery checksum or size check failed."
        )
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(raw.decode("utf-8"))
        if (
            db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or db.execute("PRAGMA foreign_key_check").fetchall()
            or table_counts(db) != document["tables"]
            or not {"seasons", "signups", "roster_entries"}.issubset(document["tables"])
        ):
            raise DashboardDurabilityError("Dashboard recovery integrity check failed.")
        return db
    except Exception:
        db.close()
        raise


@contextmanager
def database_lock(path):
    """Prevent a recovery/seed operation racing the local web process."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(target) + ".recovery.lock", "a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DashboardDurabilityError(
                "The dashboard database is already in use."
            ) from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class MongoDashboardState:
    def __init__(self, collection, key="warriors-united-dashboard"):
        self.collection = collection
        self.key = key
        self.owner = uuid.uuid4().hex
        self.revision = None
        self.poisoned = False
        self.acquired = False
        self.previous_local_path = None
        self.previous_local_paths = []
        self.local_recovery_interrupted = False

    @classmethod
    def open(cls, uri, *, routes=None):
        if not uri:
            raise DashboardDurabilityError(
                "MONGODB_URI is required for dashboard recovery."
            )
        client = MongoClient(
            uri, serverSelectionTimeoutMS=5000, timeoutMS=10000, tz_aware=True,
            appName="wu-dashboard-durability", maxPoolSize=10
        )
        collection = collection_for(
            client, "cwl_dashboard_state", routes=routes
        ).with_options(
            write_concern=WriteConcern(w="majority", j=True, wtimeout=5000),
            read_concern=ReadConcern("majority"),
            read_preference=ReadPreference.PRIMARY,
        )
        result = cls(collection)
        result.client = client
        return result

    def seed(self, path):
        """Explicit one-time migration. Never upsert/overwrite an existing head."""
        source = Path(path).resolve()
        if not source.is_file() or not source.stat().st_size:
            raise DashboardDurabilityError(
                "Cannot initialize Mongo from a missing/empty database."
            )
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("BEGIN")
            document = encode(db)
        check = decode(document)
        check.close()
        self.collection.insert_one(
            {
                "_id": self.key,
                **document,
                "revision": 1,
                "owner": None,
                "lease_until": utcnow(),
                "saved_at": utcnow(),
            }
        )
        return document["tables"]

    def acquire(self):
        now = utcnow()
        document = self.collection.find_one_and_update(
            {"_id": self.key, "$or": [{"owner": None}, {"lease_until": {"$lte": now}}]},
            {
                "$set": {
                    "owner": self.owner,
                    "lease_until": now + timedelta(seconds=LEASE_SECONDS),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise DashboardDurabilityError(
                "Mongo recovery state is missing or another dashboard owns the writer lease. Never start an empty replacement; initialize once or wait for the previous lease to expire."
            )
        self.revision = document["revision"]
        self.acquired = True
        return document

    def restore(self, path):
        document = self.acquire()
        recovered = decode(document)
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            # Do not overwrite unconsumed progress if a prior startup crashed
            # between replacing the working database and merging role receipts.
            self.previous_local_path = None
            self.previous_local_paths = []
            backup = target.with_name(target.name + ".before-mongo")
            receipt = backup.with_name(backup.name + ".consumed")
            consumed = (
                backup.exists()
                and receipt.exists()
                and receipt.read_text()
                == hashlib.sha256(backup.read_bytes()).hexdigest()
            )
            self.local_recovery_interrupted = backup.exists() and not consumed
            if backup.exists() and not consumed:
                self.previous_local_paths.append(backup)
                self.previous_local_paths.extend(
                    sorted(backup.parent.glob(backup.name + ".pending-*"))
                )
            if target.exists() and target.stat().st_size:
                destination = (
                    backup.with_name(backup.name + ".pending-" + uuid.uuid4().hex)
                    if self.local_recovery_interrupted
                    else backup
                )
                try:
                    with sqlite3.connect(target) as old, sqlite3.connect(
                        destination
                    ) as saved:
                        old.backup(saved)
                except sqlite3.DatabaseError:
                    shutil.copy2(target, destination)
                with destination.open("rb") as saved:
                    os.fsync(saved.fileno())
                os.chmod(destination, 0o600)
                self.previous_local_paths.append(destination)
                if destination == backup:
                    receipt.unlink(missing_ok=True)
            if self.previous_local_paths:
                self.previous_local_path = self.previous_local_paths[0]
            fd, name = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
            os.close(fd)
            temporary = Path(name)
            with sqlite3.connect(temporary) as db:
                recovered.backup(db)
            with temporary.open("rb") as saved:
                os.fsync(saved.fileno())
            # No local process may be running during restore (database_lock).
            # Old journals must never replay into the recovered database.
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(target) + suffix).unlink(missing_ok=True)
            os.replace(temporary, target)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            recovered.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return document["tables"]

    def mark_local_recovery_complete(self):
        """Called only after SQLite FULL-commit of recovered role progress."""
        if self.previous_local_path is None:
            return
        backup = self.previous_local_path
        receipt = backup.with_name(backup.name + ".consumed")
        fd, name = tempfile.mkstemp(prefix=receipt.name + ".", dir=receipt.parent)
        try:
            with os.fdopen(fd, "w") as saved:
                saved.write(hashlib.sha256(backup.read_bytes()).hexdigest())
                saved.flush()
                os.fsync(saved.fileno())
            os.chmod(name, 0o600)
            os.replace(name, receipt)
            # Include consumed copies left if a prior boot died after receipt
            # rename but before cleanup; retain the base investigation proof.
            for pending in backup.parent.glob(backup.name + ".pending-*"):
                suffix = pending.name.removeprefix(backup.name + ".pending-")
                if len(suffix) == 32 and all(char in "0123456789abcdef" for char in suffix):
                    pending.unlink(missing_ok=True)
            directory = os.open(receipt.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)

    def save_role_progress(self, image):
        """Independent coalesced role recovery copy; never fences the main head."""
        self.check()
        revision = self.revision
        document = {
            **image,
            "dashboard_revision": revision,
            "saved_at": utcnow(),
            "writer": self.owner,
        }
        key = self.key + ":pool-roles-progress"
        # Read the copy before the head: a writer fenced during handover cannot
        # subsequently adopt the new owner's copy as its compare-and-swap basis.
        prior = self.collection.find_one(
            {"_id": key},
            {"dashboard_revision": 1, "version": 1, "writer": 1, "saved_at": 1},
        )
        head = self.collection.find_one(
            {"_id": self.key}, {"owner": 1, "revision": 1, "lease_until": 1}
        )
        if (
            not head
            or head.get("owner") != self.owner
            or head.get("revision") != revision
            or self.revision != revision
            or not isinstance(head.get("lease_until"), datetime)
            or head["lease_until"] <= utcnow()
        ):
            raise DashboardDurabilityError("Role backup writer lease was lost.")
        if (
            prior
            and prior.get("dashboard_revision") == revision
            and prior.get("version", -1) > image["version"]
        ):
            return False
        # A stale, higher copy revision can be replaced only by the actual head
        # owner, and only if its exact metadata still matches what was observed.
        selector = {"_id": key}
        if prior:
            for field in ("dashboard_revision", "version", "writer", "saved_at"):
                selector[field] = prior[field] if field in prior else {"$exists": False}
        else:
            selector["dashboard_revision"] = {"$exists": False}
        result = self.collection.update_one(
            selector, {"$set": document}, upsert=prior is None
        )
        return bool(result.matched_count or result.upserted_id)

    def load_role_progress(self):
        return self.collection.find_one({"_id": self.key + ":pool-roles-progress"})

    def check(self):
        if self.poisoned:
            raise DashboardDurabilityError(
                "Durable storage needs recovery. Restart the dashboard before making more changes."
            )

    def heartbeat(self):
        self.check()
        try:
            result = self.collection.update_one(
                {"_id": self.key, "owner": self.owner, "revision": self.revision},
                {"$set": {"lease_until": utcnow() + timedelta(seconds=LEASE_SECONDS)}},
            )
            if result.matched_count != 1:
                raise DashboardDurabilityError("Dashboard writer lease was lost.")
        except Exception:
            self.poisoned = True
            raise DashboardDurabilityError(
                "Mongo storage could not confirm the dashboard writer lease."
            ) from None

    def publish(self, db):
        self.check()
        document = encode(db)
        try:
            result = self.collection.update_one(
                {"_id": self.key, "owner": self.owner, "revision": self.revision},
                {
                    "$set": {
                        **document,
                        "saved_at": utcnow(),
                        "lease_until": utcnow() + timedelta(seconds=LEASE_SECONDS),
                    },
                    "$inc": {"revision": 1},
                },
            )
            if result.matched_count != 1:
                raise DashboardDurabilityError(
                    "Dashboard writer lease or revision was lost."
                )
            self.revision += 1
        except Exception:
            # Mongo may have accepted the write. Never retry using the stale
            # local copy, and never let a notification silently retry either.
            self.poisoned = True
            raise DashboardDurabilityError(
                "Mongo could not confirm this save. Changes may have reached recovery storage. Restart and check the saved result before retrying."
            ) from None

    def close(self):
        try:
            if self.acquired:
                self.collection.update_one(
                    {"_id": self.key, "owner": self.owner},
                    {"$set": {"owner": None, "lease_until": utcnow()}},
                )
        except Exception:
            logging.getLogger(__name__).warning(
                "Could not release dashboard lease; it will expire automatically."
            )
        finally:
            if hasattr(self, "client"):
                self.client.close()

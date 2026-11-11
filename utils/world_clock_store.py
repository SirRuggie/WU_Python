"""Mongo persistence for World clocks, shared by the bot task and the web API.

This module is the only storage owner for the feature. Collections follow
bot_config's database, like war reminders:

- world_clock_settings: one document, _id "settings" (category, time format,
  update interval, version).
- world_clocks: one document per clock. `version` changes on every staff edit
  so two editors never overwrite each other. The task writes only the result
  fields (last_name, status, …) and never changes `version`.
- world_clock_requests: one receipt per "Create channel" press. Receipts are
  kept so a double tap or a retry never creates a second channel.
- world_clock_runs: a short history of task runs for the page.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

from utils import world_clocks as rules

SETTINGS_ID = "settings"
RUN_HISTORY_DAYS = 7
RESULT_FIELDS = ("last_name", "last_renamed_at", "status", "status_detail", "checked_at")


class Conflict(Exception):
    """Another editor saved this item after the caller read it."""


class ChannelInUse(Exception):
    """Another clock already renames this channel."""


def collection(db, name):
    return db.bot_config.database.get_collection(
        name, write_concern=WriteConcern(w="majority", wtimeout=10000)
    )


def default_settings() -> dict:
    return {"category_id": None, "time_format": "12h",
            "interval_minutes": rules.DEFAULT_INTERVAL, "version": 0}


def clean_settings(row: dict | None) -> dict:
    values = default_settings()
    if row:
        values.update({key: row[key] for key in values if key in row})
    if values["time_format"] not in rules.TIME_FORMATS:
        values["time_format"] = "12h"
    # type() check: 6.0 == 6 would pass "in" and later break datetime.replace().
    if type(values["interval_minutes"]) is not int or values["interval_minutes"] not in rules.INTERVALS:
        values["interval_minutes"] = rules.DEFAULT_INTERVAL
    return values


class WorldClockStore:
    def __init__(self, db):
        self.db = db
        self.settings_rows = collection(db, "world_clock_settings")
        self.clocks = collection(db, "world_clocks")
        self.requests = collection(db, "world_clock_requests")
        self.runs = collection(db, "world_clock_runs")

    async def ensure_indexes(self):
        await self.clocks.create_index(
            "channel_id", unique=True, name="one_clock_per_channel",
            partialFilterExpression={"channel_id": {"$type": "string"}},
        )
        await self.runs.create_index([("at", -1)], name="recent_runs")

    # Settings ---------------------------------------------------------------

    async def get_settings(self) -> dict:
        return clean_settings(await self.settings_rows.find_one({"_id": SETTINGS_ID}))

    async def save_settings(self, version: int, values: dict, actor: str) -> dict:
        now = datetime.now(timezone.utc)
        query = {"_id": SETTINGS_ID, "version": version} if version else {"_id": SETTINGS_ID, "version": {"$in": [0, None]}}
        update = {"$set": {**values, "updated_by": actor, "updated_at": now}, "$inc": {"version": 1}}
        try:
            row = await self.settings_rows.find_one_and_update(
                query, update, upsert=not version, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError as exc:
            raise Conflict from exc
        if row is None:
            raise Conflict
        return clean_settings(row)

    # Clocks -----------------------------------------------------------------

    async def list_clocks(self) -> list[dict]:
        return await self.clocks.find({}).to_list(length=rules.MAX_CLOCKS * 2)

    async def enabled_clocks(self) -> list[dict]:
        return await self.clocks.find({"enabled": True}).to_list(length=rules.MAX_CLOCKS * 2)

    async def count(self) -> int:
        return await self.clocks.count_documents({})

    async def get_clock(self, clock_id: str) -> dict | None:
        return await self.clocks.find_one({"_id": clock_id})

    async def add_clock(self, values: dict, actor: str) -> dict:
        now = datetime.now(timezone.utc)
        row = {"_id": uuid4().hex, **values, "enabled": True, "version": 1,
               "created_by": actor, "created_at": now, "updated_by": actor, "updated_at": now,
               "status": "waiting", "status_detail": "Waiting for the first update."}
        # The unique channel index must exist before the first dashboard write,
        # not only after the task starts. create_index is a no-op when it exists.
        await self.ensure_indexes()
        try:
            await self.clocks.insert_one(row)
        except DuplicateKeyError as exc:
            raise ChannelInUse from exc
        return row

    async def update_clock(self, clock_id: str, version: int, values: dict, actor: str) -> dict:
        now = datetime.now(timezone.utc)
        changes = {**values, "updated_by": actor, "updated_at": now}
        if "channel_id" in values or "zone" in values or "code" in values or "flag" in values:
            changes.update(status="waiting", status_detail="Shows in Discord at the next update.")
        if "channel_id" in values:
            await self.ensure_indexes()
        try:
            row = await self.clocks.find_one_and_update(
                {"_id": clock_id, "version": version},
                {"$set": changes, "$inc": {"version": 1}},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise ChannelInUse from exc
        if row is None:
            raise Conflict
        return row

    async def remove_clock(self, clock_id: str, version: int) -> None:
        result = await self.clocks.delete_one({"_id": clock_id, "version": version})
        if result.deleted_count != 1:
            raise Conflict

    async def record_result(self, clock_id: str, version: int, **values) -> bool:
        """Task result for one clock. Ignored when staff changed the clock meanwhile."""
        unknown = set(values) - set(RESULT_FIELDS)
        if unknown:
            raise ValueError(f"Unknown result fields: {sorted(unknown)}")
        result = await self.clocks.update_one({"_id": clock_id, "version": version}, {"$set": values})
        return result.matched_count == 1

    # Create-channel receipts ------------------------------------------------

    async def claim_request(self, request_id: str, actor: str, payload: dict) -> dict | None:
        """Insert a receipt. Returns the earlier receipt when this id was used before."""
        try:
            await self.requests.insert_one({
                "_id": request_id, "actor": actor, "payload": payload,
                "category_id": payload.get("category_id"),
                "status": "creating", "created_at": datetime.now(timezone.utc)})
        except DuplicateKeyError:
            return await self.requests.find_one({"_id": request_id}) or {"status": "creating"}
        return None

    async def get_request(self, request_id: str) -> dict | None:
        return await self.requests.find_one({"_id": request_id})

    async def open_request(self, category_id: str, since: datetime, exclude: str) -> dict | None:
        """A recent create in this category that may have made a channel Discord did not confirm."""
        return await self.requests.find_one({
            "category_id": category_id, "status": {"$in": ["creating", "uncertain"]},
            "created_at": {"$gte": since}, "_id": {"$ne": exclude}})

    async def retry_failed(self, request_id: str, actor: str, payload: dict) -> bool:
        """Reuse a receipt that Discord refused. Atomic: only one press wins."""
        result = await self.requests.update_one(
            {"_id": request_id, "actor": actor, "status": "failed"},
            {"$set": {"status": "creating", "payload": payload, "category_id": payload.get("category_id"),
                      "created_at": datetime.now(timezone.utc)}})
        return result.matched_count == 1

    async def finish_request(self, request_id: str, **values) -> None:
        await self.requests.update_one({"_id": request_id}, {"$set": {**values, "finished_at": datetime.now(timezone.utc)}})

    # Run history ------------------------------------------------------------

    async def add_run(self, entry: dict) -> None:
        await self.runs.insert_one(entry)
        await self.runs.delete_many({"at": {"$lt": entry["at"] - timedelta(days=RUN_HISTORY_DAYS)}})

    async def recent_runs(self, limit: int = 10) -> list[dict]:
        return await self.runs.find({}, {"_id": 0}).sort("at", -1).limit(limit).to_list(length=limit)

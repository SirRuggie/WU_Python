"""In-memory stand-ins for the World clocks store tests. No network, no Mongo."""
from __future__ import annotations

import copy
from types import SimpleNamespace as NS

from pymongo.errors import DuplicateKeyError


def _matches(row, query):
    for key, wanted in query.items():
        value = row.get(key)
        if isinstance(wanted, dict):
            for op, arg in wanted.items():
                if op == "$in" and value not in arg:
                    return False
                if op == "$lt" and not (value is not None and value < arg):
                    return False
                if op == "$gte" and not (value is not None and value >= arg):
                    return False
                if op == "$ne" and value == arg:
                    return False
                if op == "$type" and arg == "string" and not isinstance(value, str):
                    return False
        elif value != wanted:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction=1):
        self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, length=None):
        return [copy.deepcopy(row) for row in self.rows[:length]]


class MemoryCollection:
    def __init__(self, unique=()):
        self.rows: list[dict] = []
        self.unique = unique  # Field names with a unique index (strings only).
        self.fail_next = None

    def _check_unique(self, row, ignore=None):
        for other in self.rows:
            if other is ignore:
                continue
            if other["_id"] == row["_id"]:
                raise DuplicateKeyError("_id")
            for field in self.unique:
                if isinstance(row.get(field), str) and other.get(field) == row.get(field):
                    raise DuplicateKeyError(field)

    def _raise(self):
        if self.fail_next:
            error, self.fail_next = self.fail_next, None
            raise error

    async def create_index(self, *args, **kwargs):
        return "ok"

    async def find_one(self, query):
        self._raise()
        for row in self.rows:
            if _matches(row, query):
                return copy.deepcopy(row)
        return None

    def find(self, query=None, projection=None):
        rows = [row for row in self.rows if _matches(row, query or {})]
        if projection and projection.get("_id") == 0:
            rows = [{k: v for k, v in row.items() if k != "_id"} for row in rows]
        return Cursor(list(rows))

    async def count_documents(self, query):
        return sum(1 for row in self.rows if _matches(row, query))

    async def insert_one(self, row):
        self._raise()
        row = copy.deepcopy(row)
        row.setdefault("_id", f"auto-{len(self.rows)}-{id(row)}")
        self._check_unique(row)
        self.rows.append(row)
        return NS(inserted_id=row["_id"])

    def _apply(self, row, update):
        updated = copy.deepcopy(row)
        updated.update(copy.deepcopy(update.get("$set", {})))
        for key, amount in update.get("$inc", {}).items():
            updated[key] = (updated.get(key) or 0) + amount
        return updated

    async def find_one_and_update(self, query, update, upsert=False, return_document=None):
        self._raise()
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                updated = self._apply(row, update)
                self._check_unique(updated, ignore=row)
                self.rows[index] = updated
                return copy.deepcopy(updated)
        if upsert:
            seed = {k: v for k, v in query.items() if not isinstance(v, dict)}
            row = self._apply(seed, update)
            self._check_unique(row)
            self.rows.append(row)
            return copy.deepcopy(row)
        return None

    async def update_one(self, query, update, upsert=False):
        self._raise()
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = self._apply(row, update)
                return NS(matched_count=1, upserted_id=None)
        return NS(matched_count=0, upserted_id=None)

    async def delete_one(self, query):
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                del self.rows[index]
                return NS(deleted_count=1)
        return NS(deleted_count=0)

    async def delete_many(self, query):
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return NS(deleted_count=before - len(self.rows))


def memory_db():
    collections = {
        "world_clock_settings": MemoryCollection(),
        "world_clocks": MemoryCollection(unique=("channel_id",)),
        "world_clock_requests": MemoryCollection(),
        "world_clock_runs": MemoryCollection(),
    }
    database = NS(get_collection=lambda name, **kwargs: collections[name])
    return NS(bot_config=NS(database=database), collections=collections)

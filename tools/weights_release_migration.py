"""Read-only, fail-closed comparison for the accepted two-war SQLite migration.

This is release tooling, not a schema writer. Call ``capture`` in each database,
then ``compare`` after the candidate's public Store/owner startup rehearsal.
``capture_protected(db, existing_reader)`` adds the raw predecessor rows to an
existing release capture in the same read transaction. No broad empty-table or
staff-edit exception is provided.
"""

from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import base64
import hashlib
import json
import sqlite3

TABLE = "clan_weight_war_lineup_previous"
ACCEPTED_DDL = """CREATE TABLE IF NOT EXISTS clan_weight_war_lineup_previous (
 clan_tag TEXT PRIMARY KEY, end_time TEXT NOT NULL, captured_at TEXT NOT NULL, lineup_json TEXT NOT NULL
);"""
_REQUIRED = {
    "seasons",
    "signups",
    "roster_entries",
    "clan_weight_war_lineups",
    "clan_player_weights",
    "clan_player_weight_history",
}


class MigrationGuardError(ValueError):
    """The release must stop rather than normalize an unproven change."""


def _require(condition, reason):
    if not condition:
        raise MigrationGuardError(reason)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _query(db, sql):
    cursor = db.cursor()
    cursor.row_factory = None
    cursor.execute(sql)
    return cursor


@contextmanager
def _read_transaction(db):
    own = not db.in_transaction
    if own:
        db.execute("BEGIN")
    try:
        yield
    finally:
        if own:
            db.rollback()


def _schema(db):
    return [
        list(row)
        for row in _query(
            db,
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name,tbl_name",
        )
    ]


@lru_cache(maxsize=1)
def _target_objects():
    # SQLite supplies the exact accepted CREATE text and implicit PK index.
    with sqlite3.connect(":memory:") as expected:
        expected.executescript(ACCEPTED_DDL)
        return tuple(tuple(row) for row in _schema(expected))


def _check_target(schema, *, required):
    objects = [tuple(row) for row in schema if row[1] == TABLE or row[2] == TABLE]
    _require(not required or objects, "Accepted predecessor table is missing")
    if objects:
        _require(
            tuple(objects) == _target_objects(),
            "Predecessor schema differs from accepted DDL",
        )


def _cell(value):
    # SQLite values must retain their type: Python considers 1 and 1.0 equal.
    if value is None:
        return ["null", None]
    if type(value) is int:
        return ["integer", str(value)]
    if type(value) is float:
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    if isinstance(value, bytes):
        return ["blob", base64.b64encode(value).decode("ascii")]
    raise MigrationGuardError("Unsupported SQLite value adapter")


def _json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def capture(db):
    """Capture all declared row values/counts and all schema objects, read-only.

    An existing caller transaction is preserved. Otherwise a consistent read
    transaction is opened and rolled back. Physical row order/implicit rowids
    are not a data contract; duplicate declared rows remain in the multiset.
    """
    with _read_transaction(db):
        _require(
            list(_query(db, "PRAGMA integrity_check")) == [("ok",)],
            "SQLite integrity check failed",
        )
        schema = _schema(db)
        tables = {}
        for kind, name, _, _ in schema:
            if kind != "table":
                continue
            cursor = _query(db, "SELECT * FROM " + _quote(name))
            rows = sorted(
                ([_cell(value) for value in row] for row in cursor), key=_json
            )
            tables[name] = {
                "columns": [item[0] for item in cursor.description],
                "rows": rows,
                "count": len(rows),
            }
        _require(
            _REQUIRED <= tables.keys(),
            "SQLite capture lacks required application tables",
        )
        _check_target(schema, required=False)
        payload = {"format": 1, "schema": schema, "tables": tables}
        return {**payload, "sha256": _digest(payload)}


def _validate(snapshot):
    _require(
        isinstance(snapshot, dict)
        and set(snapshot) == {"format", "schema", "tables", "sha256"},
        "Malformed SQLite capture",
    )
    _require(
        snapshot["format"] == 1
        and isinstance(snapshot["schema"], list)
        and isinstance(snapshot["tables"], dict),
        "Malformed SQLite capture",
    )
    payload = {key: value for key, value in snapshot.items() if key != "sha256"}
    _require(_digest(payload) == snapshot["sha256"], "SQLite capture checksum differs")
    schema, tables = snapshot["schema"], snapshot["tables"]
    _require(
        all(isinstance(row, list) and len(row) == 4 for row in schema),
        "Malformed schema capture",
    )
    names = [row[1] for row in schema if row[0] == "table"]
    _require(
        len(names) == len(set(names))
        and set(names) == set(tables)
        and _REQUIRED <= set(names),
        "Incomplete SQLite capture",
    )
    for table in tables.values():
        _require(
            isinstance(table, dict) and set(table) == {"columns", "rows", "count"},
            "Malformed table capture",
        )
        _require(
            isinstance(table["columns"], list)
            and isinstance(table["rows"], list)
            and type(table["count"]) is int
            and table["count"] == len(table["rows"]),
            "Malformed table counts",
        )
        _require(
            all(
                isinstance(row, list) and len(row) == len(table["columns"])
                for row in table["rows"]
            ),
            "Malformed row capture",
        )
    _check_target(schema, required=False)


def compare(before, after):
    """Permit only the exact empty first creation; every existing object stays strict."""
    _require(before is not after, "Independent SQLite captures required")
    _validate(before)
    _validate(after)
    old, new = before["tables"], after["tables"]
    _check_target(after["schema"], required=True)
    added = set(new) - set(old)
    allowed_added = {TABLE} if TABLE not in old else set()
    _require(added == allowed_added, "Unexpected SQLite table addition")
    _require(set(old) <= set(new), "Existing SQLite table removed")
    if added:
        _require(new[TABLE]["count"] == 0, "New predecessor table must be empty")
    # New objects must belong to the one already-validated exact table. Views,
    # triggers/indexes on old tables, and neighbouring columns are never ignored.
    old_objects_after = [row for row in after["schema"] if row[2] not in added]
    _require(old_objects_after == before["schema"], "Existing SQLite schema changed")
    for name in old:
        _require(new[name] == old[name], "Existing SQLite rows/counts changed: " + name)
    return {
        "format": 1,
        "before_sha256": before["sha256"],
        "after_sha256": after["sha256"],
        "added_tables": sorted(added),
        "created_empty_predecessor": bool(added),
        "previous_rows": new[TABLE]["count"],
        "previous_rows_sha256": _digest(new[TABLE]),
        "existing_tables_verified": len(old),
        "existing_schema_rows_counts_exact": True,
    }


def previous_rows(db):
    """Raw predecessor rows for a release's protected capture; absent means []."""
    with _read_transaction(db):
        schema = _schema(db)
        _check_target(schema, required=False)
        if not any(row[0] == "table" and row[1] == TABLE for row in schema):
            return []
        cursor = _query(db, "SELECT * FROM " + _quote(TABLE))
        columns = [item[0] for item in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor]
        return sorted(
            rows,
            key=lambda row: _json({key: _cell(value) for key, value in row.items()}),
        )


def capture_protected(db, existing_reader):
    """Atomically extend an existing protected reader without altering its data."""
    with _read_transaction(db):
        protected = deepcopy(existing_reader(db))
        _require(
            isinstance(protected, dict) and protected,
            "Existing protected capture is empty",
        )
        actual = previous_rows(db)
        if TABLE in protected:
            normalize = lambda rows: sorted(
                (
                    _json({key: _cell(value) for key, value in row.items()})
                    for row in rows
                )
            )
            _require(
                isinstance(protected[TABLE], list)
                and normalize(protected[TABLE]) == normalize(actual),
                "Protected predecessor rows disagree with SQLite",
            )
        return {**protected, TABLE: actual}

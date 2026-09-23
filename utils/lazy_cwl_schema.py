"""Versioned MongoDB contract and safe deployment migration for LazyCWL.

DDL belongs to deployment tooling, not individual dashboard requests. The
validator complements conditional writes: an array multikey unique index
cannot prevent repeated player tags within the same roster document.
"""
from __future__ import annotations

from copy import deepcopy

SCHEMA_VERSION = 1
INTEGER = {"bsonType": ["int", "long"], "minimum": 0}
TAG = {"bsonType": "string", "pattern": "^#[A-Z0-9]+$"}
NULLABLE_DATE = {"bsonType": ["date", "null"]}

JSON_SCHEMA = {
    "bsonType": "object",
    "required": ["schema_version", "clan_tag", "clan_name", "status", "saved_at", "saved_by", "expires_at", "purge_at", "players", "reminders"],
    "properties": {
        "schema_version": {"bsonType": "int", "enum": [SCHEMA_VERSION]},
        "clan_tag": TAG,
        "clan_name": {"bsonType": "string", "minLength": 1},
        "status": {"enum": ["active", "finished", "expired"]},
        "saved_at": {"bsonType": "date"},
        "saved_by": INTEGER,
        "expires_at": {"bsonType": "date"},
        "purge_at": {"bsonType": "date"},
        "finished_at": {"bsonType": "date"},
        "legacy_snapshot_id": {"bsonType": "string", "minLength": 1},
        "players": {
            "bsonType": "array",
            "items": {
                "bsonType": "object",
                "required": ["tag", "name", "town_hall", "discord_id", "added_manually", "added_at"],
                "properties": {
                    "tag": TAG,
                    "name": {"bsonType": "string"},
                    "town_hall": INTEGER,
                    "discord_id": {"bsonType": ["int", "long", "null"], "minimum": 1},
                    "added_manually": {"bsonType": "bool"},
                    "added_at": {"bsonType": "date"},
                },
            },
        },
        "reminders": {
            "bsonType": "object",
            "required": ["enabled", "every_minutes", "started_at", "last_sent_at", "sent_count"],
            "properties": {
                "enabled": {"bsonType": "bool"},
                # Legacy schedules may have intervals beyond current UI options.
                "every_minutes": {"bsonType": ["int", "long", "null"], "minimum": 1},
                "started_at": NULLABLE_DATE,
                "last_sent_at": NULLABLE_DATE,
                "sent_count": INTEGER,
            },
        },
    },
}

VALIDATOR = {
    "$and": [
        {"$jsonSchema": JSON_SCHEMA},
        {"$expr": {"$and": [
            {"$cond": [
                {"$isArray": "$players"},
                {"$eq": [{"$size": "$players"}, {"$size": {"$setUnion": ["$players.tag", []]}}]},
                False,
            ]},
            {"$gt": ["$expires_at", "$saved_at"]},
            {"$gte": ["$purge_at", "$expires_at"]},
            {"$or": [
                {"$eq": ["$reminders.enabled", False]},
                {"$and": [
                    {"$eq": ["$status", "active"]},
                    {"$gt": ["$reminders.every_minutes", 0]},
                    {"$eq": [{"$type": "$reminders.started_at"}, "date"]},
                ]},
            ]},
        ]}},
    ],
}


async def audit_collection(collection) -> dict:
    """Read-only preflight. Test the additive backfill without writing it."""
    pipeline = [
        {"$set": {"schema_version": {"$cond": [
            {"$eq": [{"$type": "$schema_version"}, "missing"]},
            SCHEMA_VERSION, "$schema_version",
        ]}}},
        {"$match": {"$nor": [VALIDATOR]}},
        {"$count": "count"},
    ]
    invalid = await (await collection.aggregate(pipeline)).to_list(length=None)
    options = await collection.options()
    return {
        "write_concern": collection.write_concern.document,
        "documents": await collection.count_documents({}),
        "unversioned_documents": await collection.count_documents({"schema_version": {"$exists": False}}),
        "invalid_after_version_backfill": invalid[0]["count"] if invalid else 0,
        "validator_matches": options.get("validator") == VALIDATOR,
        "validation_level": options.get("validationLevel"),
        "validation_action": options.get("validationAction"),
    }


async def apply_schema(collection) -> dict:
    """Backfill a version and enforce strict validation, without deleting data.

    Unknown validators/versions are refused rather than silently downgraded.
    Run while the bot is stopped so old writers cannot race this migration.
    """
    options = await collection.options()
    if options.get("validator") and options["validator"] != VALIDATOR:
        raise RuntimeError("An unrecognized LazyCWL validator is installed; review it before changing schema.")
    report = await audit_collection(collection)
    if report["invalid_after_version_backfill"]:
        raise RuntimeError("Existing LazyCWL documents do not match the proposed schema; nothing was changed.")
    await collection.update_many(
        {"schema_version": {"$exists": False}},
        {"$set": {"schema_version": SCHEMA_VERSION}},
    )
    # Check actual persisted data, including explicit null/unknown versions.
    if await collection.count_documents({"$nor": [VALIDATOR]}):
        raise RuntimeError("LazyCWL data changed during migration; strict validation was not installed.")
    await collection.database.command({
        "collMod": collection.name,
        "validator": deepcopy(VALIDATOR),
        "validationLevel": "strict",
        "validationAction": "error",
    })
    return await audit_collection(collection)

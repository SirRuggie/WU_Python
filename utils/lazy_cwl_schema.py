"""Versioned MongoDB contract and safe deployment migration for LazyCWL.

DDL belongs to deployment tooling, not individual dashboard requests. The
validator complements conditional writes: an array multikey unique index
cannot prevent repeated player tags within the same roster document.
"""
from __future__ import annotations

from copy import deepcopy

SCHEMA_VERSION = 2
INTEGER = {"bsonType": ["int", "long"], "minimum": 0}
TAG = {"bsonType": "string", "pattern": "^#[A-Z0-9]+$"}
NULLABLE_DATE = {"bsonType": ["date", "null"]}

JSON_SCHEMA = {
    "bsonType": "object",
    "required": ["schema_version", "section", "cwl_season", "clan_tag", "clan_name", "status", "saved_at", "saved_by", "expires_at", "purge_at", "players", "reminders"],
    "properties": {
        "schema_version": {"bsonType": "int", "enum": [SCHEMA_VERSION]},
        "section": {"enum": ["FWA", "MAIN"]},
        # The season is deliberately stored rather than inferred at read time:
        # a roster captured near month boundaries must remain attributable to
        # the CWL season it was created for.
        "cwl_season": {"bsonType": "string", "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$"},
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
            {"$or": [
                {"$eq": ["$section", "FWA"]},
                {"$eq": ["$reminders.enabled", False]},
            ]},
        ]}},
    ],
}

# The validator shipped with schema v1.  Keep this exact compatibility shape
# only for the deployment bridge below; it is never installed as the final
# contract.  A strict v1 collection rejects setting schema_version=2, so the
# bridge temporarily accepts either complete version while rows are upgraded.
LEGACY_JSON_SCHEMA = deepcopy(JSON_SCHEMA)
LEGACY_JSON_SCHEMA["required"] = [
    field for field in LEGACY_JSON_SCHEMA["required"] if field not in {"section", "cwl_season"}
]
LEGACY_JSON_SCHEMA["properties"].pop("section")
LEGACY_JSON_SCHEMA["properties"].pop("cwl_season")
LEGACY_JSON_SCHEMA["properties"]["schema_version"] = {"bsonType": "int", "enum": [1]}
LEGACY_VALIDATOR = deepcopy(VALIDATOR)
LEGACY_VALIDATOR["$and"][0]["$jsonSchema"] = LEGACY_JSON_SCHEMA
# v2 additionally prevents enabled reminders on MAIN.  It did not exist in
# the deployed v1 validator, which must accept enabled FWA legacy rows during
# the compatibility window.
LEGACY_VALIDATOR["$and"][1]["$expr"]["$and"].pop()
COMPATIBILITY_VALIDATOR = {"$or": [LEGACY_VALIDATOR, VALIDATOR]}


async def audit_collection(collection) -> dict:
    """Read-only preflight. Test the additive backfill without writing it."""
    pipeline = [
        {"$set": {
            "schema_version": {"$cond": [
                {"$or": [
                    {"$eq": [{"$type": "$schema_version"}, "missing"]},
                    {"$eq": ["$schema_version", 1]},
                ]}, SCHEMA_VERSION, "$schema_version",
            ]},
            "section": {"$ifNull": ["$section", "FWA"]},
            "cwl_season": {"$ifNull": ["$cwl_season", {"$dateToString": {
                "format": "%Y-%m", "timezone": "UTC", "date": {"$cond": [
                    {"$gte": [{"$dayOfMonth": {"date": "$saved_at", "timezone": "UTC"}}, 16]},
                    {"$dateAdd": {"startDate": "$saved_at", "unit": "month", "amount": 1}}, "$saved_at",
                ]},
            }}]},
        }},
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
    if (options.get("validator") and options["validator"] != VALIDATOR
            and options["validator"] != LEGACY_VALIDATOR
            and options["validator"] != COMPATIBILITY_VALIDATOR):
        raise RuntimeError("An unrecognized LazyCWL validator is installed; review it before changing schema.")
    report = await audit_collection(collection)
    if report["invalid_after_version_backfill"]:
        raise RuntimeError("Existing LazyCWL documents do not match the proposed schema; nothing was changed.")
    # This additive pipeline upgrades both unversioned rows and v1 rows that
    # already passed the old strict validator.  It is safe to repeat after an
    # interrupted deployment and preserves an explicitly assigned section or
    # season.
    if options.get("validator") == LEGACY_VALIDATOR:
        await collection.database.command({
            "collMod": collection.name, "validator": deepcopy(COMPATIBILITY_VALIDATOR),
            "validationLevel": "strict", "validationAction": "error",
        })
    await collection.update_many({"$or": [
        {"schema_version": {"$exists": False}}, {"schema_version": 1},
    ]}, [{"$set": {
        "schema_version": SCHEMA_VERSION,
        "section": {"$ifNull": ["$section", "FWA"]},
        "cwl_season": {"$ifNull": ["$cwl_season", {"$dateToString": {
            "format": "%Y-%m", "timezone": "UTC", "date": {"$cond": [
                {"$gte": [{"$dayOfMonth": {"date": "$saved_at", "timezone": "UTC"}}, 16]},
                {"$dateAdd": {"startDate": "$saved_at", "unit": "month", "amount": 1}}, "$saved_at",
            ]},
        }}]},
    }}])
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

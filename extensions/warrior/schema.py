"""Warrior-owned persistence, versioning and narrowly scoped initial migration.

Natural keys are preserved. Active progress and completed history have no TTL:
expiring these could silently lose delivery or role-cleanup obligations. Audit
arrays are bounded at their write site; ephemeral controls use component_state.
"""

import logging
from copy import deepcopy
from datetime import datetime, timezone

SCHEMA_VERSION = 1
log = logging.getLogger(__name__)


def normalize(document):
    """Own only Warrior documents; canonicalize BSON dates and identity fields."""

    def dates(value):
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )
        if isinstance(value, dict):
            return {k: dates(v) for k, v in value.items()}
        if isinstance(value, list):
            return [dates(v) for v in value]
        return value

    result = dates(deepcopy(document))
    if result.get("schema_version", 1) != SCHEMA_VERSION:
        raise ValueError("Unsupported Warrior schema version")
    result["schema_version"] = SCHEMA_VERSION
    for field in ("guild_id", "user_id", "actor_id", "ticket_channel", "updated_by"):
        if field in result:
            result[field] = int(result[field])
    return result


async def migrate_early_records(mongo):
    """Move only the initial Warrior release's records, never legacy onboarding.

    Copy, verify, then conditionally remove the exact source document. An ambiguous
    or conflicting target aborts without deleting the source. Restart is safe after
    any await. The worker must finish migration before processing new deliveries.
    """
    routes = [
        (
            mongo.ticket_setup,
            mongo.warrior_settings,
            {"_id": {"$regex": "^warrior_settings:[0-9]+$"}},
        ),
        (
            mongo.recruit_onboarding,
            mongo.warrior_walkthroughs,
            {
                "kind": "warrior_walkthrough",
                "_id": {"$regex": "^warrior:[0-9]+:[0-9]+$"},
            },
        ),
        (
            mongo.recruit_onboarding,
            mongo.warrior_history,
            {
                "kind": "warrior_walkthrough_history",
                "_id": {"$regex": "^warrior:[0-9]+:[0-9]+:"},
            },
        ),
        (
            mongo.recruit_onboarding,
            mongo.warrior_audit,
            {"_id": {"$regex": "^warrior_audit:[0-9]+:[0-9]+$"}},
        ),
    ]
    for source, target, query in routes:
        async for original in source.find(query):
            document = normalize(original)
            parts = str(document["_id"]).split(":")
            document.setdefault("guild_id", int(parts[1]))
            if len(parts) > 2:
                document.setdefault("user_id", int(parts[2]))
            await target.update_one(
                {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
            )
            copied = await target.find_one({"_id": document["_id"]})
            if copied is None or normalize(copied) != document:
                raise RuntimeError("Warrior migration conflict; source preserved")
            result = await source.delete_one(original)
            if result.deleted_count != 1:
                raise RuntimeError(
                    "Warrior source changed during migration; source preserved"
                )
            log.info("Migrated Warrior record collection=%s", target.name)

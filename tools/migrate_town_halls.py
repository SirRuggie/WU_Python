"""Copy legacy Town Hall weights into the registry; dry-run unless --apply.

Production invocation belongs to the reviewed release: show the dry-run report
first, then run --apply only after Ruggie's explicit migration authorization.
The old war_weight_settings document is never modified or deleted.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from bson import BSON

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import town_halls
from utils.mongo_routes import collection_from


# Migration-only seeds. Runtime code must use the saved registry instead.
SEED_EMOJIS = {
    1: "",
    2: "<:TH_2:1395728426849275997>",
    3: "<:TH_3:1395728517299306537>",
    4: "<:TH_4:1395728565575618623>",
    5: "<:TH_5:1395728620185718796>",
    6: "<:TH_6:1395728668583792716>",
    7: "<:TH_7:1395728738334806152>",
    8: "<:TH_8:1395728783591608360>",
    9: "<:TH_9:1395728820471857266>",
    10: "<:TH_10:1395728880991735899>",
    11: "<:TH_11:1395728917339570186>",
    12: "<:TH_12:1395728951854501959>",
    13: "<:TH_13:1395728985857458261>",
    14: "<:TH_14:1395729011404963843>",
    15: "<:TH_15:1395729045962096651>",
    16: "<:TH_16:1395729067990319164>",
    17: "<:TH_17:1395729126014324837>",
    18: "<:TH_18:1447966636496650310>",
    19: "<:TH_19A:1571025137896005783>",
}
_MARKUP = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>")
_NAME = re.compile(r"[A-Za-z0-9_]{2,32}")


def build_registry(legacy, guild_id):
    """Build and validate the proposed copy without writing or guessing names."""
    if not isinstance(legacy, dict) or legacy.get("_id") != str(guild_id):
        raise ValueError("The server's legacy weight settings are missing.")
    ranges = legacy.get("ranges")
    if not isinstance(ranges, dict) or not ranges:
        raise ValueError("Legacy weight ranges are missing.")
    if any(not isinstance(key, str) or re.fullmatch(r"[1-9][0-9]?", key) is None for key in ranges):
        raise ValueError("Legacy weight settings contain an invalid Town Hall level.")
    highest = max(19, *(int(key) for key in ranges))
    result = {
        "_id": str(guild_id), "schema_version": 1, "revision": 0,
        "lowest_fwa_town_hall": 12, "levels": {},
    }
    named = []
    for level in range(1, highest + 1):
        item = {"emoji": SEED_EMOJIS.get(level, "")}
        old = ranges.get(str(level))
        if old is not None:
            if not isinstance(old, dict) or "min" not in old or "max" not in old:
                raise ValueError("A legacy weight range is malformed.")
            item["weight"] = {"min": old["min"], "max": old["max"]}
            override = old.get("emoji", "")
            if not isinstance(override, str):
                raise ValueError("A legacy emoji override is malformed.")
            if _MARKUP.fullmatch(override):
                item["emoji"] = override
            elif override:
                if _NAME.fullmatch(override) is None:
                    raise ValueError("A legacy emoji override is malformed.")
                named.append({"level": level, "name": override, "seed_used": item["emoji"]})
        result["levels"][str(level)] = item
    town_halls.validate(result)
    return result, named


def _digest(doc):
    # BSON retains integer widths/types, binary values and datetimes. Ordinary
    # Python equality would miss a numeric value changing from int to float.
    encoded = b"missing" if doc is None else BSON.encode(doc)
    return hashlib.sha256(encoded).hexdigest()


async def migrate(mongo, guild_id, *, apply=False):
    """Perform a fixture-testable dry run or one insert; no automatic retries."""
    legacy_collection = collection_from(mongo.fwa_data, "war_weight_settings")
    before = {
        "war_weight_settings": await legacy_collection.count_documents({}),
        "town_halls": await town_halls.migration_count(mongo),
    }
    existing = await town_halls.load(mongo, guild_id)
    legacy = await legacy_collection.find_one({"_id": str(guild_id)})
    legacy_before = deepcopy(legacy)
    if existing is not None:
        proposed, named = existing, []
        status = "already migrated"
        inserted = False
    else:
        proposed, named = build_registry(legacy, guild_id)
        inserted = await town_halls.create_for_migration(mongo, guild_id, proposed) if apply else False
        status = "migrated" if inserted else "already migrated" if apply else "dry run"
        if apply:
            actual = await town_halls.load(mongo, guild_id)
            if actual is None:
                raise ValueError("The registry insert could not be verified; no retry was attempted.")
            if inserted and _digest(actual) != _digest(proposed):
                raise ValueError("Town Halls changed after the insert; no overwrite or retry was attempted.")
            proposed = actual
    after = {
        "war_weight_settings": await legacy_collection.count_documents({}),
        "town_halls": await town_halls.migration_count(mongo),
    }
    legacy_after = await legacy_collection.find_one({"_id": str(guild_id)})
    if _digest(legacy_after) != _digest(legacy_before) or before["war_weight_settings"] != after["war_weight_settings"]:
        raise ValueError("Legacy weight settings changed during the migration; no legacy write or restoration was attempted.")
    return {
        "status": status, "apply": apply, "inserted": inserted, "guild_id": str(guild_id),
        "lowest_fwa_town_hall": proposed["lowest_fwa_town_hall"],
        "levels": [
            {"level": level, "emoji": proposed["levels"][str(level)].get("emoji", ""),
             "weight": deepcopy(proposed["levels"][str(level)].get("weight"))}
            for level in town_halls.levels(proposed)
        ],
        "name_only_overrides": named, "counts_before": before, "counts_after": after,
        "legacy_document_sha256_before": _digest(legacy_before),
        "legacy_document_sha256_after": _digest(legacy_after),
        "legacy_unchanged": True,
    }


async def _run(uri, guild_id, *, apply=False):
    # Client creation and dotenv loading stay in the CLI, never module import.
    from utils.mongo import MongoClient
    mongo = MongoClient(uri, connect=False)
    try:
        return await migrate(mongo, guild_id, apply=apply)
    finally:
        await mongo.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="report the copy without writing (default)")
    modes.add_argument("--apply", action="store_true", help="insert only after explicit release/migration authorization")
    parser.add_argument("--guild-id", required=True, type=int)
    parser.add_argument("--report", type=Path, help="new JSON report under this checkout's .local directory")
    args = parser.parse_args(argv)
    if args.guild_id < 1:
        parser.error("--guild-id must be positive")
    from dotenv import load_dotenv
    load_dotenv()
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        print("MONGODB_URI is not set")
        return 2
    local = ROOT / ".local"
    report_path = args.report or local / ("town-halls-migration-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    report_path = report_path.absolute()
    if not report_path.resolve().is_relative_to(local.resolve()) or report_path.exists():
        parser.error("--report must be a new file under this checkout's .local directory")
    report = asyncio.run(_run(uri, args.guild_id, apply=args.apply))
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    report_path.chmod(0o600)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

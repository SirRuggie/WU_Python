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


LEGACY_ROLE_DEFAULTS = {'10': '1003796340578471977',
 '11': '1003796173993287690',
 '12': '1003796143630712943',
 '13': '1003796042317316166',
 '14': '1003796205630914630',
 '15': '1029879502484025474',
 '16': '1186343231303200848',
 '17': '1315835882435121152',
 '18': '1439244282392215552',
 '19': '1567934399234711765',
 '2': '1148951648484474951',
 '3': '1006458298842746890',
 '4': '1006458193418924062',
 '5': '1006458029597798420',
 '6': '1006457868037410887',
 '7': '1006456898616311808',
 '8': '1003796008121143436',
 '9': '1003795980052873276'}


BASE_MAPS = ("fwa_base_links", "base_information", "base_upgrade_notes", "war_base_images", "active_base_images")


def build_bases_registry(current, legacy):
    """Copy shared images and variant text without touching either input."""
    town_halls.validate(current)
    if not isinstance(legacy, dict) or legacy.get("_id") != "fwa_config":
        raise ValueError("Legacy FWA base configuration is missing.")
    result = deepcopy(current)
    result["schema_version"] = 2
    result["nonbase_revision"] = current.get("nonbase_revision", current["revision"])
    copied, differences, hidden = [], [], set()
    maps = {}
    for name in BASE_MAPS:
        values = legacy.get(name, {})
        if not isinstance(values, dict):
            raise ValueError(f"Legacy {name} must be a map.")
        maps[name] = values
        for key, value in values.items():
            if value == "":
                continue
            if not isinstance(value, str):
                raise ValueError(f"Legacy {name} contains a non-text base value.")
            level, variant = town_halls.parse_variant_value(key)
            if str(level) not in result["levels"]:
                result["levels"][str(level)] = {"emoji": ""}
            if level < current["lowest_fwa_town_hall"]:
                hidden.add(level)
            bases = result["levels"][str(level)].setdefault("bases", {})
            if name in ("war_base_images", "active_base_images"):
                # Select shared image below, after comparing both old variants.
                continue
            field = {"fwa_base_links": "link", "base_information": "instructions", "base_upgrade_notes": "upgrade_notes"}[name]
            bases.setdefault(variant, {})[field] = value
            copied.append({"source_map": name, "key": key, "destination": f"levels.{level}.bases.{variant}.{field}"})
    for level, item in result["levels"].items():
        for name, slot in (("war_base_images", "war_image"), ("active_base_images", "active_image")):
            merged = maps[name].get(f"th{level}", "")
            non_merged = maps[name].get(f"th{level}_new", "")
            if merged and non_merged and merged != non_merged:
                differences.append({"level": int(level), "slot": slot, "merged_url": merged, "non_merged_url": non_merged, "selected": "Merged"})
            chosen = merged or non_merged
            if chosen:
                item.setdefault("bases", {})[slot] = chosen
                key = f"th{level}" + ("_new" if not merged else "")
                copied.append({"source_map": name, "key": key, "destination": f"levels.{level}.bases.{slot}"})
    town_halls.validate(result)
    return result, copied, differences, sorted(hidden)


def base_counts(doc):
    entries = (doc or {}).get("levels", {})
    return {
        "levels_with_bases": sum("bases" in item for item in entries.values()),
        "merged_links": sum(bool(item.get("bases", {}).get("merged", {}).get("link")) for item in entries.values()),
        "non_merged_links": sum(bool(item.get("bases", {}).get("non_merged", {}).get("link")) for item in entries.values()),
        "war_images": sum(bool(item.get("bases", {}).get("war_image")) for item in entries.values()),
        "active_images": sum(bool(item.get("bases", {}).get("active_image")) for item in entries.values()),
    }


async def migrate_bases(mongo, guild_id, *, apply=False):
    """One bases-only migration, with exact legacy readback and no retries."""
    current = await town_halls.load(mongo, guild_id)
    if current is None:
        raise town_halls.TownHallsMissing(town_halls.MISSING_MESSAGE)
    legacy = await mongo.fwa_data.find_one({"_id": "fwa_config"})
    legacy_before = deepcopy(legacy)
    before = {"town_halls_documents": await town_halls.migration_count(mongo),
              "registry": base_counts(current),
              "legacy_maps": {name: len((legacy or {}).get(name, {})) for name in BASE_MAPS}}
    if any("bases" in item for item in current["levels"].values()):
        proposed, copied, differences, hidden = current, [], [], []
        status, applied = "already migrated", False
    else:
        proposed, copied, differences, hidden = build_bases_registry(current, legacy)
        applied = await town_halls.apply_bases_migration(mongo, guild_id, current, proposed) if apply and copied else False
        status = "migrated" if applied else "no base data" if not copied else "dry run" if not apply else "already migrated"
        if apply and copied and not applied:
            actual = await town_halls.load(mongo, guild_id)
            if actual is None or not any("bases" in item for item in actual["levels"].values()):
                raise ValueError("Town Halls changed during the bases migration; no retry attempted.")
    actual = await town_halls.load(mongo, guild_id)
    if actual is None:
        raise ValueError("The registry readback is missing; no retry attempted.")
    if applied:
        expected = {key: value.get("bases") for key, value in proposed["levels"].items()}
        observed = {key: value.get("bases") for key, value in actual["levels"].items()}
        if _digest({"bases": expected}) != _digest({"bases": observed}):
            raise ValueError("The migrated base fields changed after apply; no retry attempted.")
    legacy_after = await mongo.fwa_data.find_one({"_id": "fwa_config"})
    if _digest(legacy_before) != _digest(legacy_after):
        raise ValueError("Legacy FWA configuration changed; no legacy write or restoration attempted.")
    after = {"town_halls_documents": await town_halls.migration_count(mongo),
             "registry": base_counts(actual),
             "legacy_maps": {name: len((legacy_after or {}).get(name, {})) for name in BASE_MAPS}}
    if before["town_halls_documents"] != after["town_halls_documents"] or before["legacy_maps"] != after["legacy_maps"]:
        raise ValueError("Migration source counts changed; no retry attempted.")
    return {"mode": "bases", "status": status, "apply": apply, "applied": applied,
            "guild_id": str(guild_id), "copied_keys": copied, "image_differences": differences,
            "copied_below_lowest_fwa": hidden, "counts_before": before, "counts_after": after,
            "proposed_registry_counts": base_counts(proposed),
            "legacy_document_sha256_before": _digest(legacy_before),
            "legacy_document_sha256_after": _digest(legacy_after), "legacy_unchanged": True}


async def migrate_roles(mongo, guild_id, *, safe_role_ids, apply=False):
    """Insert/update only the separate roles document; never migrate registry bytes."""
    async with town_halls.role_configuration_guard(guild_id):
        current = await town_halls.load(mongo, guild_id)
        if current is None:
            raise town_halls.TownHallsMissing(town_halls.MISSING_MESSAGE)
        old = await mongo.warrior_settings.find_one({'_id': f'warrior_settings:{guild_id}'})
        before_registry, before_legacy = _digest(current), _digest(old)
        overrides = (old or {}).get('townhalls', {})
        if not isinstance(overrides, dict):
            raise ValueError('Legacy Warrior Town Hall roles are malformed.')
        target = dict(LEGACY_ROLE_DEFAULTS)
        for level, identifier in overrides.items():
            if not isinstance(level, str) or not re.fullmatch(r'[1-9][0-9]?', level):
                raise ValueError('Legacy Warrior Town Hall level is malformed.')
            if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
                raise ValueError('Legacy Warrior Town Hall role is malformed.')
            target[level] = str(identifier)
        town_halls.validate_roles(target, current)
        stored = await town_halls.load_roles(mongo, guild_id)
        if any(level in stored['roles'] and stored['roles'][level] != identifier for level, identifier in target.items()):
            raise ValueError('A Town Hall role conflicts with its saved value. No roles were written.')
        proposed = dict(stored['roles']) | target
        town_halls.validate_roles(proposed)
        from utils import server_roles
        conflicts = town_halls.cross_role_conflicts(proposed, (await server_roles.load(mongo, guild_id))['roles'])
        if conflicts:
            if apply:
                raise town_halls.TownHallRoleOverlap(conflicts)
            return {'mode': 'roles', 'status': 'conflict', 'applied': False, 'guild_id': str(guild_id),
                    'roles_before': stored['roles'], 'roles_proposed': proposed, 'conflicts': conflicts,
                    'registry_unchanged': True, 'warrior_settings_unchanged': True}
        if any(identifier not in safe_role_ids for identifier in target.values()):
            raise ValueError('A Town Hall role is missing or unsafe. No roles were written.')
        changes = {level: identifier for level, identifier in target.items() if stored['roles'].get(level) != identifier}
        applied = bool(apply and changes)
        if applied:
            saved = await town_halls.save_roles(mongo, guild_id, changes, 0, stored['revision'])
            actual = await town_halls.load_roles(mongo, guild_id)
            if actual['roles'] != proposed or actual['revision'] != saved['revision']:
                raise ValueError('Roles readback changed. No retry or restoration attempted.')
        if before_registry != _digest(await town_halls.load(mongo, guild_id)) or before_legacy != _digest(await mongo.warrior_settings.find_one({'_id': f'warrior_settings:{guild_id}'})):
            raise ValueError('Registry or legacy settings changed. No restoration attempted.')
        return {'mode': 'roles', 'status': 'migrated' if applied else 'dry run' if changes else 'already migrated',
                'applied': applied, 'guild_id': str(guild_id), 'roles_before': stored['roles'], 'roles_proposed': proposed,
                'registry_sha256_before': before_registry, 'registry_sha256_after': before_registry,
                'warrior_settings_sha256_before': before_legacy, 'warrior_settings_sha256_after': before_legacy,
                'registry_unchanged': True, 'warrior_settings_unchanged': True}


async def safe_discord_roles(mongo, guild_id):
    """Explicit CLI-only Discord read; tests inject fixture IDs instead."""
    import hikari
    from types import SimpleNamespace
    from utils.role_permissions import role_is_self_selectable
    from utils.dashboard_access import dashboard_role_grants
    token = os.getenv('DISCORD_TOKEN', '')
    if not token:
        raise ValueError('DISCORD_TOKEN is not set; cannot verify role safety.')
    async with hikari.RESTApp() as app:
        async with app.acquire(token, token_type=hikari.TokenType.BOT) as rest:
            me = await rest.fetch_my_user()
            guild, roles, member = await asyncio.gather(rest.fetch_guild(guild_id), rest.fetch_roles(guild_id), rest.fetch_member(guild_id, me.id))
    by_id = {int(role.id): role for role in roles}
    adapted = SimpleNamespace(id=guild.id, owner_id=guild.owner_id, get_role=lambda identifier: by_id.get(int(identifier)), get_member=lambda identifier: member if int(identifier) == int(me.id) else None)
    bot = SimpleNamespace(get_me=lambda: me)
    protected = await dashboard_role_grants(mongo)
    return {str(role.id) for role in roles if str(role.id) not in protected and role_is_self_selectable(adapted, bot, role)}


async def migrate(mongo, guild_id, *, apply=False, bases=False):
    """Perform a fixture-testable dry run or one insert; no automatic retries."""
    if bases:
        return await migrate_bases(mongo, guild_id, apply=apply)
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


async def _run(uri, guild_id, *, apply=False, bases=False, roles=False):
    # Client creation and dotenv loading stay in the CLI, never module import.
    from utils.mongo import MongoClient
    mongo = MongoClient(uri, connect=False)
    try:
        if roles:
            return await migrate_roles(mongo, guild_id, safe_role_ids=await safe_discord_roles(mongo, guild_id), apply=apply)
        return await migrate(mongo, guild_id, apply=apply, bases=bases)
    finally:
        await mongo.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="report the copy without writing (default)")
    modes.add_argument("--apply", action="store_true", help="insert only after explicit release/migration authorization")
    content_modes = parser.add_mutually_exclusive_group()
    content_modes.add_argument("--roles", action="store_true", help="copy legacy roles into their separate document")
    content_modes.add_argument("--bases", action="store_true", help="copy legacy bases into the existing registry (schema2)")
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
    report = asyncio.run(_run(uri, args.guild_id, apply=args.apply, bases=args.bases, roles=args.roles))
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    report_path.chmod(0o600)
    print(encoded, end="")
    return 1 if report.get("conflicts") else 0


if __name__ == "__main__":
    raise SystemExit(main())

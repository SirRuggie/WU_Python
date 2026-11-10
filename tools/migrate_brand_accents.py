"""Move saved message accent colors from the old bot colors to the WU brand colors.

Batch 1 of the brand color change (PR #277) moved the colors in code. Messages
that staff edited and saved keep the color that was current when they saved,
so this script updates those saved values in `bot_config`:

    recruit_question_template:<guild>:<variant>   field "accent"
    fwa_war_template:<guild>:<variant>            field "accent"
    cwl campaign defaults, cycles and drafts      any "accent_color" under
                                                  "campaign" or "recurring_campaign"

Every saved accent moves to the message's default brand color, including
colors staff picked by hand (see `new_color`). A value that already matches is
reported as KEEP. Revision history entries are never changed.

Each write matches the document's current revision (templates) or the exact
old value at that path (CWL campaigns), so an edit saved while the script runs
is never overwritten; the script reports it as skipped. Template writes add 1
to `revision`, so an editor that was open before the run reports a conflict
instead of saving the old color back.

    .venv/bin/python tools/migrate_brand_accents.py                 # dry run
    .venv/bin/python tools/migrate_brand_accents.py --apply --backup PATH

`--apply` needs `--backup`: every document is written to that JSON file before
any change. Exit status: 0 done, 1 some writes skipped, 2 setup error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WU_GOLD = 0xF2B62A
WU_GREEN = 0x43E58C
WU_RED = 0xE00010

TEMPLATE_PREFIXES = ("recruit_question_template:", "fwa_war_template:")
CAMPAIGN_PREFIXES = ("cwl:defaults:", "cwl:cycle:", "cwl:draft:")
CAMPAIGN_FIELDS = ("campaign", "recurring_campaign")


WAR_DEFAULTS = {"win": WU_GREEN, "lose": WU_RED, "mismatch": WU_GOLD, "blacklisted": 0x000000}


def new_color(value: int, *, war_variant: str | None = None) -> int:
    """Return the brand color this saved message should use.

    Ruggie approved (2026-11-10) moving every saved accent, including colors
    staff picked by hand, to the message's default: FWA war results keep their
    meaning (win green, lose red, mismatch gold, blacklisted black); every
    other saved message is WU_GOLD.
    """
    if war_variant is not None:
        return WAR_DEFAULTS.get(war_variant, WU_GOLD)
    return WU_GOLD


def _walk(node, path: str):
    """Yield (dotted path, value) for every accent_color under node."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}"
            if key == "accent_color" and isinstance(value, int) and not isinstance(value, bool):
                yield child, value
            else:
                yield from _walk(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}.{index}")


def plan(document: dict) -> tuple[list[tuple[str, int, int]], list[tuple[str, int]]]:
    """Return (changes, kept) for one bot_config document.

    changes: (path, old, new) for each exact old color.
    kept: (path, value) for each saved accent that already has its brand color.
    """
    doc_id = str(document.get("_id", ""))
    found: list[tuple[str, int, str | None]] = []
    if doc_id.startswith(TEMPLATE_PREFIXES):
        accent = document.get("accent")
        if isinstance(accent, int) and not isinstance(accent, bool):
            variant = doc_id.rsplit(":", 1)[-1] if doc_id.startswith("fwa_war_template:") else None
            found.append(("accent", accent, variant))
    elif doc_id.startswith(CAMPAIGN_PREFIXES):
        for field in CAMPAIGN_FIELDS:
            for path, value in _walk(document.get(field), field):
                found.append((path, value, None))
    changes, kept = [], []
    for path, value, variant in found:
        target = new_color(value, war_variant=variant)
        if target == value:
            kept.append((path, value))
        else:
            changes.append((path, value, target))
    return changes, kept


async def apply_changes(collection, document: dict, changes: list[tuple[str, int, int]]) -> bool:
    """Write one document's changes. Return False when the document changed first."""
    query = {"_id": document["_id"]}
    query.update({path: old for path, old, _new in changes})
    update = {"$set": {path: new for path, _old, new in changes}}
    if str(document["_id"]).startswith(TEMPLATE_PREFIXES):
        query["revision"] = document.get("revision", 0)
        update["$inc"] = {"revision": 1}
    result = await collection.update_one(query, update)
    return getattr(result, "modified_count", 0) == 1


async def run(collection, *, apply: bool, backup: Path | None, out=print) -> int:
    prefixes = "|".join(re.escape(prefix) for prefix in TEMPLATE_PREFIXES + CAMPAIGN_PREFIXES)
    query = {"_id": {"$regex": f"^({prefixes})"}}
    documents = await collection.find(query).to_list(length=None)
    planned = []
    for document in documents:
        changes, kept = plan(document)
        for path, old, new in changes:
            out(f"CHANGE {document['_id']} {path}: #{old:06X} -> #{new:06X}")
        for path, value in kept:
            out(f"KEEP   {document['_id']} {path}: #{value:06X}")
        if changes:
            planned.append((document, changes))
    total = sum(len(changes) for _doc, changes in planned)
    out(f"{len(documents)} saved message document(s) checked; {total} color(s) in {len(planned)} document(s) to change")
    if not apply:
        out("DRY RUN: nothing written")
        return 0
    if backup is None:
        out("--apply needs --backup PATH")
        return 2
    backup.write_text(json.dumps(documents, default=str, indent=2), encoding="utf-8")
    out(f"Backup of {len(documents)} document(s) written to {backup}")
    skipped = 0
    for document, changes in planned:
        if await apply_changes(collection, document, changes):
            out(f"UPDATED {document['_id']}")
        else:
            skipped += 1
            out(f"SKIPPED {document['_id']}: it changed after the read; run again to recheck")
    out(f"{len(planned) - skipped} document(s) updated, {skipped} skipped")
    return 1 if skipped else 0


async def _main(uri: str, *, apply: bool, backup: Path | None) -> int:
    from utils.mongo import MongoClient

    mongo = MongoClient(uri)
    try:
        return await run(mongo.bot_config, apply=apply, backup=backup)
    finally:
        await mongo.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--backup", type=Path, help="JSON file for the pre-change documents; required with --apply")
    args = parser.parse_args(argv)
    if args.apply and args.backup is None:
        print("--apply needs --backup PATH")
        return 2
    if args.backup is not None and args.backup.exists():
        print(f"{args.backup} already exists; choose a new backup path")
        return 2

    from dotenv import load_dotenv

    load_dotenv()
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        print("MONGODB_URI is not set")
        return 2
    return asyncio.run(_main(uri, apply=args.apply, backup=args.backup))


if __name__ == "__main__":
    sys.exit(main())

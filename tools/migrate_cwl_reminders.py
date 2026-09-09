"""One-shot migration for CWL reminder data out of the stray `database` DB.

Before this fix, `extensions/tasks/cwl_reminder.py` read `mongo_client.database`,
which pymongo's `__getattr__` resolves to a second, undeclared database
literally named "database" (never the "settings" database the rest of the
bot uses). Two collections accumulated there:

    database.cwl_reminder            -- one singleton "schedule" document
    database.cwl_pending_reminders   -- one row per outstanding reminder job

`utils/mongo.py` now declares both collections against the correct
`settings` database (`mongo.cwl_reminder`, `mongo.cwl_pending_reminders`),
and the bot code has been repointed there. Any data written before that fix
is stuck in the stray database and needs a one-time copy.

This script copies every document from each stray collection into its
declared counterpart, upserting by `_id`, so re-running it is a no-op once
the copy is complete (existing declared-side documents are left in place;
running it again just re-applies the same values). It never deletes
anything from the stray database -- clean that up by hand once the counts
look right.

Run it anywhere with the repo's `.env` (MONGODB_URI):

    venv/bin/python tools/migrate_cwl_reminders.py --dry-run   # counts only
    venv/bin/python tools/migrate_cwl_reminders.py              # does the copy

Exit status is 2 when MONGODB_URI is not set.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

from utils.mongo import MongoClient  # noqa: E402

# (stray collection name, declared collection attribute name)
COLLECTIONS = (
    ("cwl_reminder", "cwl_reminder"),
    ("cwl_pending_reminders", "cwl_pending_reminders"),
)


async def migrate_collection(mongo, stray_name: str, declared_name: str, *, dry_run: bool) -> tuple[int, int]:
    """Upsert every document from `database.<stray_name>` into `mongo.<declared_name>`.

    Returns (found, copied). `copied` stays 0 on a dry run.
    """
    stray = mongo.database.get_collection(stray_name)
    declared = getattr(mongo, declared_name)

    documents = await stray.find().to_list(length=None)
    if dry_run:
        return len(documents), 0

    copied = 0
    for document in documents:
        doc_id = document["_id"]
        fields = {k: v for k, v in document.items() if k != "_id"}
        await declared.update_one(
            {"_id": doc_id},
            {"$set": fields},
            upsert=True,
        )
        copied += 1

    return len(documents), copied


async def _run(uri: str, *, dry_run: bool) -> list[tuple[str, int, int]]:
    """Open the Mongo client, migrate every collection, and always close it --
    all on the same event loop, since AsyncMongoClient is bound to the loop
    it was created on."""
    mongo = MongoClient(uri)
    try:
        results = []
        for stray_name, declared_name in COLLECTIONS:
            found, copied = await migrate_collection(mongo, stray_name, declared_name, dry_run=dry_run)
            results.append((stray_name, found, copied))
        return results
    finally:
        await mongo.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print the counts; touch nothing")
    args = parser.parse_args(argv)

    load_dotenv()
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        print("MONGODB_URI is not set")
        return 2

    if args.dry_run:
        print("DRY RUN: nothing will be written\n")

    results = asyncio.run(_run(uri, dry_run=args.dry_run))

    for stray_name, found, copied in results:
        if args.dry_run:
            print(f"database.{stray_name}: {found} document(s) found")
        else:
            print(f"database.{stray_name}: {found} document(s) found, {copied} upserted")

    return 0


if __name__ == "__main__":
    sys.exit(main())

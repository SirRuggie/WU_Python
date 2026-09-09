"""List clan_data rows that share a tag. Read-only.

`clans` (`settings.clan_data`) had no unique index on `tag`, so a repeat
`/clan add` for the same clan created a second document with a fresh
ObjectId `_id` instead of updating the existing one; reads then picked one
of the duplicates at random. A unique index on `tag` now prevents new
duplicates, but if any already exist in this database the index creation
at startup fails with DuplicateKeyError (logged at ERROR) until they are
resolved by hand.

Run it on the host, with the venv interpreter, while the bot is up - it
only reads:

    venv/bin/python tools/find_duplicate_clans.py

For every tag with more than one document it prints the tag and the _id,
name and updated_at of each duplicate, oldest first, so you can decide
which row to keep before deleting the others.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient


def _show(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value


def main() -> int:
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    if not uri:
        print("MONGODB_URI is not set; run from the bot directory.")
        return 2
    database = MongoClient(uri).get_database("settings")

    by_tag = defaultdict(list)
    for doc in database.clan_data.find({}, {"tag": 1, "name": 1, "updated_at": 1}):
        tag = doc.get("tag")
        if tag:
            by_tag[tag].append(doc)

    duplicates = {tag: docs for tag, docs in by_tag.items() if len(docs) > 1}

    if not duplicates:
        print("no duplicate clan tags found")
        return 0

    print(f"{len(duplicates)} tag(s) with duplicates:\n")
    for tag, docs in sorted(duplicates.items()):
        print(f"tag {tag} - {len(docs)} documents")
        for doc in docs:
            print(
                f"  _id={doc['_id']!s} name={doc.get('name')!r} "
                f"updated_at={json.dumps(_show(doc.get('updated_at')), default=str)}"
            )
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One-shot importer for a ChocolateClash blacklist export in markdown.

The export (see docs/fwa-sites-access.md for how it is produced) is a
markdown file with a `Retrieved: <date>` line, a `Source: <url>` line, and a
"## Clan list" table whose rows look like:

    | _HÜÑTÈRS™_ | `#29PU8JYP0` | FWA Blacklisted | [View](https://...) |

Run it anywhere with the repo's `.env` (MONGODB_URI):

    venv/bin/python tools/import_fwa_blacklist.py <file> --dry-run   # lists the work
    venv/bin/python tools/import_fwa_blacklist.py <file>              # does it
    venv/bin/python tools/import_fwa_blacklist.py <file> --only-fwa   # FWA Blacklisted rows only

Each row upserts through `utils.fwa_blacklist.add_blacklisted` (so an
existing entry's `added_at`/`added_by_id`/`added_by_name`/`source` are never
overwritten — this importer always writes `added_by_id=0`,
`added_by_name="import"`, `source="import"`, which only take effect on first
insert), then `$set`s `classification` (the site's category for this row),
`imported_from` (the export's Source url) and `retrieved_at` (the export's
Retrieved date) on the same document. Re-running the same file is therefore
idempotent: existing rows are refreshed, not duplicated.

Exit status is 2 when MONGODB_URI is not set or the file cannot be read.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

from utils.fwa_blacklist import add_blacklisted  # noqa: E402
from utils.fwa_points_parser import sanitize_tag  # noqa: E402
from utils.mongo import MongoClient  # noqa: E402

CLAN_LIST_HEADING = "## Clan list"
ROW_RE = re.compile(r"^\| (.*?) \| `#([0-9A-Z]+)` \| (.*?) \| \[View\]")
RETRIEVED_RE = re.compile(r"^Retrieved:\s*(.+?)\s*$", re.MULTILINE)
SOURCE_RE = re.compile(r"^Source:\s*(.+?)\s*$", re.MULTILINE)

ONLY_FWA_CLASSIFICATION = "FWA Blacklisted"


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)
    unparsed: int = 0
    retrieved: str | None = None
    source: str | None = None


def parse_markdown(text: str) -> ParseResult:
    """Parse a blacklisted-clans.md export.

    Only lines in the "## Clan list" table (after its header and separator
    rows) are considered table rows; a row that does not match ROW_RE is
    counted in `unparsed` rather than raising. Lines outside that section
    (the "Category counts" table, prose, etc.) are ignored entirely.
    """
    retrieved_m = RETRIEVED_RE.search(text)
    source_m = SOURCE_RE.search(text)
    result = ParseResult(
        retrieved=retrieved_m.group(1) if retrieved_m else None,
        source=source_m.group(1) if source_m else None,
    )

    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == CLAN_LIST_HEADING)
    except StopIteration:
        return result

    header_rows_skipped = 0
    for line in lines[start + 1:]:
        if not line.startswith("|"):
            continue
        if header_rows_skipped < 2:
            # The table header ("| Clan name | Clan tag | ... |") and its
            # "| --- | --- | ... |" separator, never data.
            header_rows_skipped += 1
            continue
        m = ROW_RE.match(line)
        if not m:
            result.unparsed += 1
            continue
        name, tag, classification = m.group(1), m.group(2), m.group(3)
        result.rows.append({"name": name, "tag": tag, "classification": classification})

    return result


async def import_rows(
    mongo,
    rows: list[dict],
    *,
    dry_run: bool,
    source_url: str | None,
    retrieved_at: str | None,
) -> tuple[int, int, Counter]:
    """Upsert every row. Returns (inserted, updated, per_classification_counts).

    Always issues the one `$in` query up front to know which tags already
    exist -- in a dry run that query is the only thing that touches Mongo.
    """
    tags = [sanitize_tag(row["tag"]) for row in rows]
    existing_docs = await mongo.fwa_blacklist.find(
        {"_id": {"$in": tags}}, {"_id": 1}
    ).to_list(length=None)
    existing = {doc["_id"] for doc in existing_docs}

    inserted = 0
    updated = 0
    per_classification: Counter = Counter()
    for row in rows:
        sanitized = sanitize_tag(row["tag"])
        per_classification[row["classification"]] += 1
        if sanitized in existing:
            updated += 1
        else:
            inserted += 1

        if dry_run:
            continue

        result_tag = await add_blacklisted(
            mongo, row["tag"], row["name"],
            added_by_id=0, added_by_name="import", source="import",
        )
        if result_tag is None:
            continue
        await mongo.fwa_blacklist.update_one(
            {"_id": result_tag},
            {"$set": {
                "classification": row["classification"],
                "imported_from": source_url,
                "retrieved_at": retrieved_at,
            }},
        )

    return inserted, updated, per_classification


async def _run(uri: str, rows: list[dict], *, dry_run: bool,
                source_url: str | None, retrieved_at: str | None):
    """Open the Mongo client, do the import, and always close it -- all on
    the same event loop, since AsyncMongoClient is bound to the loop it was
    created on."""
    mongo = MongoClient(uri)
    try:
        return await import_rows(
            mongo, rows, dry_run=dry_run, source_url=source_url, retrieved_at=retrieved_at,
        )
    finally:
        await mongo.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("file", help="path to a blacklisted-clans.md export")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the summary; touch nothing")
    parser.add_argument("--only-fwa", action="store_true",
                        help="import only rows classified 'FWA Blacklisted'")
    args = parser.parse_args(argv)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        print(f"cannot read {args.file}: {exc}")
        return 2

    parsed = parse_markdown(text)
    rows = parsed.rows
    if args.only_fwa:
        rows = [row for row in rows if row["classification"] == ONLY_FWA_CLASSIFICATION]

    load_dotenv()
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        print("MONGODB_URI is not set")
        return 2

    if args.dry_run:
        print("DRY RUN: nothing will be written\n")

    inserted, updated, per_classification = asyncio.run(
        _run(
            uri, rows,
            dry_run=args.dry_run,
            source_url=parsed.source,
            retrieved_at=parsed.retrieved,
        )
    )

    print(f"rows parsed: {len(rows)}")
    print(f"inserted (new): {inserted}")
    print(f"updated (already existed): {updated}")
    print("by classification:")
    for classification, count in sorted(per_classification.items()):
        print(f"  {classification}: {count}")
    print(f"unparsed rows: {parsed.unparsed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

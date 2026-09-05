"""Copy every Cloudinary-hosted image referenced in Mongo to Cloudflare R2.

One-off migration for the move described in docs/media-hosting.md. Run it on
the box (anywhere with the repo's .env, Mongo access and the internet):

    venv/bin/python tools/migrate_media_to_r2.py --dry-run   # lists the work
    venv/bin/python tools/migrate_media_to_r2.py             # does it

What it touches:

  * `clan_data.logo` and `clan_data.banner`, one row per clan
  * `fwa_data` document `fwa_config`, maps `war_base_images` and
    `active_base_images`, one entry per Town Hall level

For every value hosted on res.cloudinary.com it downloads the ORIGINAL (the
raw URL Mongo holds, never a transformation) and uploads it to R2 under the
agreed bucket layout -- `clans/<Name>/logo` or `banner`, `fwa/bases/<th>/war`
or `active` -- then `$set`s the new public URL. Values not on Cloudinary are
skipped, so re-running only touches rows still to move, and a failure on one
row never blocks the rest. Cloudinary itself is not modified: it stays a
read-only fallback until you delete the account.

Exit status is 1 when any row failed, so a cron or a shell `&&` notices.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from utils.image_fetch import download_image_blocking  # noqa: E402
from utils.media_store import (  # noqa: E402
    CLAN_BANNER,
    CLAN_LOGO,
    FWA_ACTIVE_BASE_NAME,
    FWA_WAR_BASE_NAME,
    MediaStore,
    MediaStoreError,
    clan_folder,
    fwa_base_folder,
)

CLOUDINARY_HOST = "res.cloudinary.com"

# The bucket layout itself lives in utils/media_store.py (clan_folder,
# fwa_base_folder and these name constants), so migrated and new uploads
# sit side by side in the bucket. The clan folder is computed per-clan in
# migrate_clans; the FWA folder is computed per-TH in migrate_fwa.
CLAN_FIELDS = (
    # field, name
    ("logo", CLAN_LOGO),
    ("banner", CLAN_BANNER),
)
FWA_MAPS = (
    # map, name
    ("war_base_images", FWA_WAR_BASE_NAME),
    ("active_base_images", FWA_ACTIVE_BASE_NAME),
)


def is_cloudinary(value: object) -> bool:
    """True only when `value` is a URL whose host is Cloudinary's."""
    if not isinstance(value, str):
        return False
    try:
        return urlparse(value).hostname == CLOUDINARY_HOST
    except ValueError:  # malformed bracket host, e.g. "https://[x/y.png"
        return False


class Tally:
    def __init__(self) -> None:
        self.migrated = 0
        self.skipped = 0
        self.failed = 0


def copy_to_r2(store: MediaStore, url: str, folder: str, name: str,
               *, dry_run: bool, tally: Tally, label: str) -> str | None:
    """Download `url`, upload it, return the new URL (None when dry or failed)."""
    print(f"  {label}: {url}")
    print(f"    -> {folder}/{name}.<hash>.<ext>")
    if dry_run:
        return None
    try:
        data = download_image_blocking(url)
        new_url = store.upload_bytes_blocking(data, folder=folder, name=name)
    except (MediaStoreError, ValueError, OSError) as exc:
        tally.failed += 1
        print(f"    FAILED: {exc}")
        return None
    tally.migrated += 1
    print(f"    OK: {new_url}")
    return new_url


def migrate_clans(db, store: MediaStore, *, dry_run: bool, tally: Tally) -> None:
    # Case-insensitive and dots escaped, so this agrees with is_cloudinary,
    # which already accepts an upper-case host.
    host = re.escape(CLOUDINARY_HOST)
    query = {"$or": [{"logo": {"$regex": host, "$options": "i"}},
                     {"banner": {"$regex": host, "$options": "i"}}]}
    projection = {"tag": 1, "name": 1, "logo": 1, "banner": 1}
    for doc in db.clan_data.find(query, projection):
        folder = clan_folder(str(doc.get("name") or doc.get("tag") or "clan"))
        print(f"clan {doc.get('name')} ({doc.get('tag')})")
        for field, name in CLAN_FIELDS:
            url = doc.get(field)
            if not is_cloudinary(url):
                tally.skipped += 1
                continue
            new_url = copy_to_r2(store, url, folder, name,
                                 dry_run=dry_run, tally=tally, label=field)
            if new_url:
                db.clan_data.update_one({"_id": doc["_id"]}, {"$set": {field: new_url}})


def migrate_fwa(db, store: MediaStore, *, dry_run: bool, tally: Tally) -> None:
    doc = db.fwa_data.find_one({"_id": "fwa_config"})
    if not doc:
        print("fwa_config: no document, nothing to do")
        return
    for map_name, name in FWA_MAPS:
        entries = doc.get(map_name) or {}
        print(f"fwa_config.{map_name}: {len(entries)} entries")
        for th_level, url in entries.items():
            if not is_cloudinary(url):
                tally.skipped += 1
                continue
            folder = fwa_base_folder(th_level)
            new_url = copy_to_r2(store, url, folder, name,
                                 dry_run=dry_run, tally=tally, label=th_level)
            if new_url:
                db.fwa_data.update_one(
                    {"_id": "fwa_config"},
                    {"$set": {f"{map_name}.{th_level}": new_url}},
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would move; touch nothing")
    parser.add_argument("--only", choices=("clans", "fwa"),
                        help="migrate just one collection")
    args = parser.parse_args(argv)

    load_dotenv()
    store = MediaStore.from_env()
    if not store.configured:
        print("R2 is not configured: set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
              "R2_SECRET_ACCESS_KEY, R2_BUCKET and R2_PUBLIC_BASE_URL in .env")
        return 2
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        print("MONGODB_URI is not set")
        return 2

    db = MongoClient(uri)["settings"]   # the database utils/mongo.py uses
    tally = Tally()
    if args.dry_run:
        print("DRY RUN: nothing will be uploaded or written\n")
    if args.only in (None, "clans"):
        migrate_clans(db, store, dry_run=args.dry_run, tally=tally)
    if args.only in (None, "fwa"):
        migrate_fwa(db, store, dry_run=args.dry_run, tally=tally)

    print(f"\nmigrated={tally.migrated} skipped={tally.skipped} failed={tally.failed}")
    return 1 if tally.failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Upload the repo's static art (assets/) to the Cloudflare R2 bucket.

One-off tool for step 2 of docs/handoff-r2-migration.md. The `assets/`
tree mirrors the bucket layout: a file under `assets/branding/logo/WU_Logo.png`
uploads to the key `branding/logo/WU_Logo.png`. Run it on a box with the
repo's `.env`:

    venv/bin/python tools/upload_static_media.py --dry-run   # lists the work
    venv/bin/python tools/upload_static_media.py             # does it

Unlike the content-addressed uploads the slash commands write, these keys are
PLAIN names, so re-running only uploads a file whose local sha256 differs
from the object's stored `sha256` metadata -- everything else is reported as
unchanged and left alone.

Exit status is 1 when any file failed, so a cron or a shell `&&` notices.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

from utils.media_store import (  # noqa: E402
    REQUIRED_ENV,
    MediaStore,
    MediaStoreError,
    check_static_bytes,
)

ASSETS_DIR = "assets"

# Relative to the assets directory. assets/cards and the assets/*_Footer.png
# files are deliberately not here: they are not part of this move.
STATIC_ROOTS = ("branding", "fwa/static", "recruit", "tickets")

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


class Tally:
    def __init__(self) -> None:
        self.uploaded = 0
        self.unchanged = 0
        self.skipped = 0
        self.failed = 0


def iter_static_files(
    repo_root: pathlib.Path, tally: Tally | None = None
) -> list[tuple[pathlib.Path, str]]:
    """`(path, key)` for every static image under STATIC_ROOTS, sorted by key.

    A missing root prints an error and, when the caller passed a `tally`, is
    counted as a failure there -- it never raises, so one bad root does not
    stop the rest from being listed.
    """
    assets_dir = repo_root / ASSETS_DIR
    pairs: list[tuple[pathlib.Path, str]] = []
    for root in STATIC_ROOTS:
        root_dir = assets_dir / root
        if not root_dir.is_dir():
            print(f"missing root: {root_dir}")
            if tally is not None:
                tally.failed += 1
            continue
        for path in sorted(root_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(assets_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                print(f"skipped (not an image): {rel.as_posix()}")
                if tally is not None:
                    tally.skipped += 1
                continue
            pairs.append((path, rel.as_posix()))
    pairs.sort(key=lambda pair: pair[1])
    return pairs


def sync_file(store: MediaStore, path: pathlib.Path, key: str, *,
              dry_run: bool, tally: Tally) -> str:
    """Upload one file if it changed. Never raises: failures are tallied."""
    try:
        data = path.read_bytes()
        local = hashlib.sha256(data).hexdigest()
        remote = store.object_sha256(key) if store.configured else None
        if remote == local:
            tally.unchanged += 1
            print(f"unchanged: {key}")
            return "unchanged"
        if dry_run:
            check_static_bytes(data, key)
            tally.uploaded += 1
            print(f"would upload: {key}")
            return "would upload"
        url = store.upload_static_blocking(data, key=key)
        tally.uploaded += 1
        print(f"{key} -> {url}")
        return "uploaded"
    except (MediaStoreError, OSError) as exc:
        tally.failed += 1
        print(f"FAILED: {key}: {exc}")
        return "failed"


def default_store() -> MediaStore:
    """The store `main` uses. A separate function so tests can monkeypatch
    it directly instead of setting real R2_* environment variables."""
    return MediaStore.from_env()


def repo_root() -> pathlib.Path:
    """The repo root (parent of this `tools/` directory). A separate
    function so tests can point it at a fake tree instead of this one."""
    return pathlib.Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would upload; touch nothing")
    args = parser.parse_args(argv)

    root = repo_root()
    load_dotenv(root / ".env")
    store = default_store()

    if not store.configured:
        if not args.dry_run:
            print("R2 is not configured: set " + ", ".join(REQUIRED_ENV) +
                  " in .env")
            return 2
        print("R2 is not configured: cannot compare against the bucket, "
              "so every file below is listed as an upload.")

    tally = Tally()
    if args.dry_run:
        print("DRY RUN: nothing will be uploaded\n")
    for path, key in iter_static_files(root, tally):
        sync_file(store, path, key, dry_run=args.dry_run, tally=tally)

    verb = "would upload" if args.dry_run else "uploaded"
    print(f"\n{verb}={tally.uploaded} unchanged={tally.unchanged} "
          f"skipped={tally.skipped} failed={tally.failed}")
    return 1 if tally.failed else 0


if __name__ == "__main__":
    sys.exit(main())

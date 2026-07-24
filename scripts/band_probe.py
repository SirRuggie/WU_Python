#!/usr/bin/env python3
"""One-off diagnostic: dump raw BAND API post JSON.

Purpose: determine whether the BAND Open API includes calendar/schedule
attachment data (the FWA sync time) in /v2/band/posts responses, or strips
attachments and returns only the post text. Run it on the box that hosts
the bot (needs network access to openapi.band.us):

    python3 scripts/band_probe.py

Stdlib only — no venv needed. Reads BAND_ACCESS_TOKEN from the environment
if set, otherwise falls back to the value in extensions/tasks/band_monitor.py.
"""

import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MONITOR_SRC = REPO_ROOT / "extensions" / "tasks" / "band_monitor.py"

POSTS_URL = "https://openapi.band.us/v2/band/posts"
BANDS_URL = "https://openapi.band.us/v2.1/bands"

# The phrase the monitor matches war sync posts on (band_monitor.py)
SYNC_PHRASE = "PLEASE stop searching when the window closes after 1.5 hours"

MAX_POSTS = 5


def from_monitor_source(name: str) -> str | None:
    match = re.search(rf'{name} = "([^"]+)"', MONITOR_SRC.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def get_json(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=30) as resp:
        return json.load(resp)


def main() -> int:
    token = os.getenv("BAND_ACCESS_TOKEN") or from_monitor_source("BAND_ACCESS_TOKEN")
    band_name = os.getenv("TARGET_BAND_NAME") or from_monitor_source("TARGET_BAND_NAME")
    if not token or not band_name:
        print("ERROR: could not determine BAND_ACCESS_TOKEN / TARGET_BAND_NAME")
        return 1

    bands_resp = get_json(BANDS_URL, {"access_token": token})
    if bands_resp.get("result_code") != 1:
        print(f"ERROR resolving bands: {bands_resp.get('result_code')} {bands_resp.get('result_msg')}")
        return 1

    result_data = bands_resp.get("result_data", {})
    bands = result_data.get("bands", result_data.get("items", []))
    band_key = next((b["band_key"] for b in bands if b.get("name") == band_name), None)
    if not band_key:
        print(f"ERROR: no band named {band_name!r}. Available: {[b.get('name') for b in bands]}")
        return 1

    posts_resp = get_json(POSTS_URL, {"access_token": token, "band_key": band_key, "locale": "en_US"})
    if posts_resp.get("result_code") != 1:
        print(f"ERROR fetching posts: {posts_resp.get('result_code')} {posts_resp.get('result_msg')}")
        return 1

    posts = posts_resp.get("result_data", {}).get("items", [])
    print(f"Fetched {len(posts)} posts; showing up to {MAX_POSTS}.\n")

    for i, post in enumerate(posts[:MAX_POSTS]):
        is_sync = SYNC_PHRASE in post.get("content", "")
        marker = "  <<< WAR SYNC POST" if is_sync else ""
        print(f"===== post {i} | keys: {sorted(post.keys())}{marker} =====")
        print(json.dumps(post, indent=2, ensure_ascii=False))
        print()

    print("Look for a 'schedule'/'schedules'/'attachment' key on the war sync post.")
    print("If none of the posts above is the sync post, raise MAX_POSTS and rerun.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

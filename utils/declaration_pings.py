"""Pure declaration review and Components V2 payloads; no transport or storage."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import quote

TITLE = "## ⚔️ CWL declaration: join your clan"
TAG = re.compile(r"#[0289PYLQGRJCUV]{3,15}\Z")
USER = re.compile(r"[1-9][0-9]{14,21}\Z")


def display_text(value, limit=80):
    value = str(value or "").encode("utf-8", "replace").decode("utf-8")
    value = " ".join(value.split())[:limit]
    value = value.replace("@", "＠").replace("<", "‹").replace(">", "›")
    return re.sub(r"([\\`*_~|\[\]()])", r"\\\1", value)


def missing_groups(accounts, pool):
    if (
        pool not in ("main", "lazy")
        or not isinstance(accounts, list)
        or len(accounts) > 10000
    ):
        raise ValueError("Choose a valid pool and complete bounded arrival snapshot")
    groups, seen = {}, {}
    for row in accounts:
        if not isinstance(row, dict):
            raise ValueError("Incomplete arrival account")
        if (row.get("hosting_pool") or row.get("pool")) != pool:
            continue
        clan, player = row.get("assigned_clan_tag"), row.get("tag")
        if not clan or row.get("arrival_status") != "missing":
            continue  # Unassigned, arrived and unavailable are never proof of absence.
        if (
            not isinstance(clan, str)
            or not TAG.fullmatch(clan)
            or not isinstance(player, str)
            or not TAG.fullmatch(player)
        ):
            raise ValueError("Invalid assigned clan or player tag")
        if player in seen:
            if seen[player] != clan:
                raise ValueError("An account has conflicting assignments")
            continue
        seen[player] = clan
        group = groups.setdefault(
            clan,
            {
                "tag": clan,
                "name": str(row.get("assigned_clan_name") or clan)[:100],
                "accounts": [],
                "users": [],
                "unlinked": [],
            },
        )
        owner = str(row.get("user_id") or "")
        account = {
            "tag": player,
            "name": str(row.get("player_name") or player)[:100],
            "user_id": owner if USER.fullmatch(owner) else None,
        }
        group["accounts"].append(account)
        if account["user_id"]:
            if owner not in group["users"]:
                group["users"].append(owner)
        else:
            group["unlinked"].append(account)
    for group in groups.values():
        group["accounts"].sort(key=lambda r: r["tag"])
        group["users"].sort()
        group["unlinked"].sort(key=lambda r: r["tag"])
    return sorted(groups.values(), key=lambda r: (r["name"].casefold(), r["tag"]))


def review_fingerprint(groups, *, version, channel_id, revision):
    value = {
        "groups": groups,
        "version": version,
        "channel_id": channel_id,
        "revision": revision,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def text_units(text):
    return len(text.encode("utf-16-le")) // 2


def messages(groups, *, test=False):
    """Split on whole mention/name tokens, repeat clan headings when necessary.

    Each payload has at most100 allowed users,4000 text units and38 total nested
    components. A full clan can exceed a message; its mention tokens never split.
    """
    total = sum(len(g["accounts"]) for g in groups)
    footer = f"Total missing: {total}"
    chunks, lines, recipients, clans = [], [], set(), {}

    def flush():
        if not lines:
            return
        text = "\n".join([TITLE, *lines, footer])
        children = [{"type": 10, "content": text}]
        buttons = [
            {
                "type": 2,
                "style": 5,
                "label": ("Open " + str(g["name"]))[:80],
                "url": "https://link.clashofclans.com/en?action=OpenClanProfile&tag="
                + quote(tag, safe=""),
            }
            for tag, g in list(clans.items())[:30]
        ]
        for start in range(0, len(buttons), 5):
            children.append({"type": 1, "components": buttons[start : start + 5]})
        chunks.append(
            {
                "flags": 32768,
                "allowed_mentions": {
                    "parse": [],
                    "users": [] if test else sorted(recipients),
                    "roles": [],
                },
                "components": [
                    {"type": 17, "accent_color": 0xD4A017, "components": children}
                ],
            }
        )
        lines.clear()
        recipients.clear()
        clans.clear()

    for group in groups:
        tokens = [(f"<@{uid}>", uid) for uid in group["users"]]
        tokens += [
            (f"{display_text(r['name'])} (`{r['tag']}`)", None)
            for r in group["unlinked"]
        ]
        header = display_text(group["name"]) + "  ·  "
        current = header
        for token, uid in tokens:
            candidate = current + (" " if current != header else "") + token
            full = "\n".join([TITLE, *lines, candidate, footer])
            if text_units(full) > 4000 or (
                uid is not None and uid not in recipients and len(recipients) >= 100
            ):
                if current != header:
                    lines.append(current)
                flush()
                current = header + token
            else:
                current = candidate
            if uid:
                recipients.add(uid)
            clans[group["tag"]] = group
        if current != header:
            lines.append(current)
    flush()
    return chunks

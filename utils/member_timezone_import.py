"""Nickname classification and rerunnable import; never performs Discord writes."""

import asyncio
import json
import re
import unicodedata
from pathlib import Path

from utils.member_profiles import ProfileConflict
from utils.member_profile_leases import ProfileBusy

_DATA = json.loads(Path(__file__).with_name("member_timezone_data.json").read_text())


def parsed_zone(nickname):
    if not isinstance(nickname, str) or "|" not in nickname:
        return None
    raw = unicodedata.normalize("NFKC", nickname.rsplit("|", 1)[1])
    clean = "".join(
        c
        for c in raw
        if not any(lo <= ord(c) <= hi for lo, hi in _DATA["ignoredRanges"])
    )
    clean = " ".join(clean.split())
    label = clean.upper()
    if not label:
        return None
    offset = None
    if label not in _DATA["caseSensitive"] or clean == label:
        offset = _DATA["offsets"].get(label)
    if offset is None:
        numeric = re.fullmatch(
            r"(?:UTC|GMT)\s*([+-])\s*([0-9]{1,2})(?::([0-5][0-9]))?", label
        )
        if numeric:
            hours, minutes = int(numeric[2]), int(numeric[3] or 0)
            if hours < 14 or hours == 14 and minutes == 0:
                offset = (-1 if numeric[1] == "-" else 1) * (hours * 60 + minutes)
    return {"label": label, "offsetMinutes": offset}


_STANDARD_DAYLIGHT = {
    "EDT": -300,
    "CDT": -360,
    "MDT": -420,
    "PDT": -480,
    "BST": 0,
    "CEST": 60,
    "EEST": 120,
    "AEDT": 600,
    "NZDT": 720,
}


def profile_zone(nickname):
    """Profile labels use standard time; Compare retains its literal offset parser."""
    parsed = parsed_zone(nickname)
    if parsed and parsed["label"] in _STANDARD_DAYLIGHT:
        return dict(parsed, offsetMinutes=_STANDARD_DAYLIGHT[parsed["label"]])
    return parsed


def nickname_name(nickname, fallback=""):
    value = (nickname or fallback or "").strip()
    parsed = parsed_zone(value)
    if parsed and parsed["offsetMinutes"] is not None:
        return {"name": value.rsplit("|", 1)[0].strip(), "needs_review": False}
    return {"name": value, "needs_review": True}


def canonical_zone(offset):
    if type(offset) is not int or abs(offset) > 840:
        raise ValueError("Invalid time zone offset.")
    hours, minutes = divmod(abs(offset), 60)
    label = (
        "GMT"
        if offset == 0
        else f"GMT{'-' if offset < 0 else '+'}{hours}"
        + (f":{minutes:02d}" if minutes else "")
    )
    return {"zone_id": label.lower(), "gmt_label": label, "utc_offset_minutes": offset}


def nickname_country(nickname):
    """Only a single distinct regional-indicator pair establishes country."""
    pairs = set(re.findall("[\U0001f1e6-\U0001f1ff]{2}", nickname or ""))
    if len(pairs) != 1:
        return None
    return "".join(chr(ord(c) - 127397) for c in pairs.pop())


async def import_nicknames(store, members, *, actor_id, progress=None):
    # Reject incomplete/oversize directory results before any write.
    if not isinstance(members, list) or len(members) > 10000:
        raise ValueError("A complete bounded member directory is required.")
    ids = [str(row["discord_id"]) for row in members]
    from utils.member_profiles import member_id

    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate member in directory.")
    for key in ids:
        member_id(key)
    counts = progress if progress is not None else {}
    counts.update(
        known=0, unknown=0, none=0, imported=0, preserved=0, conflicts=0, bots=0
    )
    existing = await store.for_members(ids, include_departed=True)
    candidates = []
    for row in members:
        if row.get("bot"):
            counts["bots"] += 1
            continue
        parsed = profile_zone(row.get("nickname"))
        state = (
            "none"
            if parsed is None
            else "unknown" if parsed["offsetMinutes"] is None else "known"
        )
        counts[state] += 1
        if state != "known":
            continue
        current = existing.get(row["discord_id"])
        if current and current.get("source") in ("warrior", "staff", "nickname_import"):
            counts["preserved"] += 1
            continue
        candidates.append((row, parsed, current))

    pending = iter(candidates)

    async def worker():
        for row, parsed, current in pending:
            fields = dict(
                canonical_zone(parsed["offsetMinutes"]),
                country=nickname_country(row.get("nickname")),
            )
            try:
                saved = await store.write(
                    row["discord_id"],
                    fields,
                    expected_revision=int((current or {}).get("revision", 0)),
                    updated_by=actor_id,
                    source="nickname_import",
                )
                counts[
                    (
                        "imported"
                        if saved.get("source") == "nickname_import"
                        else "preserved"
                    )
                ] += 1
            except (ProfileConflict, ProfileBusy):
                counts["conflicts"] += 1

    # TaskGroup cancels and drains all siblings before returning a partial failure.
    # Every write still owns its per-member lease and rechecks revision/source.
    async with asyncio.TaskGroup() as group:
        for _ in range(min(8, len(candidates))):
            group.create_task(worker())
    return counts

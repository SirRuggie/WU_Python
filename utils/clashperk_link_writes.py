"""ClashPerk link writes; reads stay in utils.clashperk_links.

One call makes at most one ``POST /links``. The helper checks the current
owner first and never overwrites a link to another Discord user. A write that
may have reached ClashPerk is never retried; the result says so instead.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re

import aiohttp

from utils import clashperk_links
from utils.clash_links import _normalize_tag

TIMEOUT = aiohttp.ClientTimeout(total=15)
_TAG = re.compile(r"#[0289PYLQGRJCUV]{3,12}")
_lock = asyncio.Lock()
_log = logging.getLogger(__name__)

LINKED = "linked"
ALREADY_LINKED = "already_linked"
OTHER_OWNER = "other_owner"
INVALID = "invalid"
REJECTED = "rejected"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class LinkResult:
    status: str
    tag: str
    message: str
    verified: bool | None = None
    wrote: bool = False  # True when a POST was sent and may have changed ClashPerk.


def normalize_player_tag(value: str) -> str | None:
    tag = _normalize_tag(value)
    return tag if _TAG.fullmatch(tag) else None


async def _current_owner(tag: str) -> tuple[bool, dict | None]:
    """Return (known, record). known=False means the read failed or was unclear."""
    records = await clashperk_links.lookup(player_tags=[tag])
    if records is None:
        return False, None
    matching = [row for row in records if _normalize_tag(row.get("tag")) == tag]
    if len(matching) > 1:
        return False, None
    return True, (matching[0] if matching else None)


async def _post(session: aiohttp.ClientSession, tag: str, user_id: int) -> tuple[str, str | None]:
    """Return (outcome, error_code). outcome: ok, rejected, unavailable, unknown."""
    body = {"playerTag": tag, "userId": str(int(user_id)), "apiToken": None}
    token = await clashperk_links.get_access_token(session)
    if not token:
        return "unavailable", None
    for attempt in range(2):
        try:
            async with session.post(
                clashperk_links.BASE_URL + "/links", json=body,
                headers={"Authorization": "Bearer " + token}, allow_redirects=False,
            ) as response:
                if response.status in (200, 201):
                    return "ok", None
                # 401 is refused before any write; one fresh token is safe.
                if response.status == 401 and attempt == 0:
                    token = await clashperk_links.get_access_token(session, rejected=token)
                    if not token:
                        return "unavailable", None
                    continue
                code = None
                try:
                    payload = await response.json(content_type=None)
                    if isinstance(payload, dict) and isinstance(payload.get("code"), str):
                        code = payload["code"][:40]
                except (aiohttp.ContentTypeError, ValueError):
                    pass
                if response.status >= 500:
                    return "unknown", code
                return "rejected", code or str(response.status)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # The request may have reached ClashPerk. Never retry a write.
            return "unknown", None
    return "unavailable", None


_REJECTED_TEXT = {
    "FORBIDDEN": "ClashPerk refused this link for our access.",
    "UNAUTHORIZED": "ClashPerk refused our access key.",
    "INVALID_PASSKEY": "ClashPerk refused our access key.",
    "NOT_FOUND": "ClashPerk did not find this player tag.",
    "BAD_REQUEST": "ClashPerk rejected the player tag or user.",
}


async def create_link(user_id: int, player_tag: str) -> LinkResult:
    """Link ``player_tag`` to Discord ``user_id`` in ClashPerk as unverified."""
    tag = normalize_player_tag(player_tag)
    if tag is None:
        return LinkResult(INVALID, str(player_tag or "")[:20], "Enter a valid player tag.")
    async with _lock:
        known, record = await _current_owner(tag)
        if not known:
            return LinkResult(UNAVAILABLE, tag, "ClashPerk links could not be read. Nothing was changed.")
        if record is not None:
            if str(record.get("userId")) == str(int(user_id)):
                return LinkResult(ALREADY_LINKED, tag, "This account is already linked to this user in ClashPerk.",
                                  verified=record.get("verified") is True)
            return LinkResult(OTHER_OWNER, tag,
                              "This account is linked to a different Discord user in ClashPerk. Nothing was changed.",
                              verified=record.get("verified") is True)
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                outcome, code = await _post(session, tag, user_id)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            outcome, code = "unknown", None
        _log.info("ClashPerk link write tag=%s user=%s outcome=%s code=%s", tag, user_id, outcome, code)
        if outcome == "unavailable":
            return LinkResult(UNAVAILABLE, tag, "ClashPerk access is unavailable. Nothing was changed.")
        if outcome == "rejected":
            text = _REJECTED_TEXT.get(code or "", "ClashPerk rejected this link.")
            return LinkResult(REJECTED, tag, f"{text} Nothing was changed.")
        # Read back the link so the reply shows ClashPerk's real state.
        known, record = await _current_owner(tag)
        if known and record is not None and str(record.get("userId")) == str(int(user_id)):
            return LinkResult(LINKED, tag, "Linked in ClashPerk.", verified=record.get("verified") is True,
                              wrote=True)
        if outcome == "ok":
            return LinkResult(UNKNOWN, tag, "ClashPerk accepted the link, but the read-back did not confirm it. "
                                            "Check again before you retry.", wrote=True)
        return LinkResult(UNKNOWN, tag, "The ClashPerk result is unknown. The link may exist. "
                                        "Check again before you retry.", wrote=True)

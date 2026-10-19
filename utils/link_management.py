"""ClashKing link mutations; separate from the developer shared-lookup API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
import re
import time
from urllib.parse import quote

import aiohttp

from utils.clash_links import _normalize_tag

BASE_URL = "https://api.clashk.ing/v2/links"
TOKEN_ENV = "CLASHKING_BOT_TOKEN"
TIMEOUT = aiohttp.ClientTimeout(total=15)
# Leave time to reconcile the last operation and deliver Discord's response.
BATCH_SECONDS = 9 * 60
_mutation_lock = asyncio.Lock()


class LinkError(Exception):
    """A safe, user-facing error; never includes credentials or raw responses."""


@dataclass(frozen=True)
class Link:
    tag: str
    verified: bool = False
    hidden: bool = False


@dataclass
class Result:
    selected: list[str]
    completed: list[str] = field(default_factory=list)
    problem: str | None = None


def player_tag(value: str) -> str:
    tag = _normalize_tag(value)
    if not re.fullmatch(r"#[0289PYLQGRJCUV]+", tag):
        raise LinkError("Enter a valid player tag, or `all` for every linked account.")
    return tag


class LinkClient:
    def __init__(self, session: aiohttp.ClientSession, token: str):
        self.session = session
        self.token = token

    async def request(self, method: str, user_id: int, tag: str | None = None) -> dict:
        path = f"{BASE_URL}/{int(user_id)}"
        if method == "DELETE":
            path += "/" + quote(player_tag(tag or ""), safe="")
        kwargs = {"headers": {"Authorization": f"Bearer {self.token}"}}
        if method == "POST":
            kwargs["json"] = {"player_tag": player_tag(tag or "")}
        try:
            async with self.session.request(method, path, **kwargs) as response:
                if response.status in (401, 403):
                    raise LinkError(
                        "ClashKing denied account-management access. Configure a ClashKing-issued "
                        f"bot credential in {TOKEN_ENV}; the shared-lookup developer token is separate."
                    )
                if response.status == 409:
                    raise LinkError(
                        "ClashKing rejected a link conflict (another owner or the final verified "
                        "account while other links remain)."
                    )
                if response.status == 429:
                    raise LinkError("ClashKing rate-limited this operation. Try again later.")
                if response.status != 200:
                    raise LinkError(f"ClashKing returned HTTP {response.status}.")
                payload = await response.json()
                if not isinstance(payload, dict):
                    raise LinkError("ClashKing returned an invalid response.")
                return payload
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise LinkError("ClashKing's response could not be confirmed.") from exc

    async def links(self, user_id: int) -> list[Link]:
        payload = await self.request("GET", user_id)
        items = payload.get("items")
        if not isinstance(items, list):
            raise LinkError("ClashKing returned an invalid account list.")
        links = {}
        for item in items:
            if (not isinstance(item, dict) or str(item.get("user_id")) != str(user_id)
                    or not isinstance(item.get("is_verified"), bool)
                    or not isinstance(item.get("hidden"), bool)):
                raise LinkError("ClashKing returned an invalid account list.")
            tag = player_tag(item.get("player_tag", ""))
            links[tag] = Link(tag, item["is_verified"], item["hidden"])
        # Remove unverified accounts first to preserve the API's final-verified rule.
        return sorted(links.values(), key=lambda link: (link.verified, link.tag))

    async def unlink(self, source: int, tag: str) -> None:
        try:
            await self.request("DELETE", source, tag)
        except LinkError as original:
            # A timeout/5xx may follow a committed DELETE. Never blindly retry it.
            try:
                remaining = await self.links(source)
            except LinkError:
                raise LinkError(f"{original} The unlink outcome is unknown; inspect the links before retrying.") from original
            if any(link.tag == tag for link in remaining):
                raise original

    async def transfer(self, source: int, destination: int, tag: str) -> None:
        await self.unlink(source, tag)
        try:
            await self.request("POST", destination, tag)
            return
        except LinkError as original:
            # POST may have committed despite a lost response. Establish ownership
            # before attempting compensation, which must never steal a link back.
            try:
                target_links = await self.links(destination)
                source_links = await self.links(source)
            except LinkError:
                raise LinkError(
                    f"{original} Transfer outcome for {tag} is unknown; inspect both users before retrying."
                ) from original
            if any(link.tag == tag for link in target_links):
                return
            if any(link.tag == tag for link in source_links):
                raise LinkError(f"Transfer failed for {tag}; it is linked to the original user.") from original
            try:
                await self.request("POST", source, tag)
            except LinkError:
                try:
                    restored = any(link.tag == tag for link in await self.links(source))
                except LinkError:
                    restored = False
                if not restored:
                    raise LinkError(
                        f"Transfer failed for {tag}; restoration could not be confirmed. "
                        "It may be unlinked or owned elsewhere. Check it manually."
                    ) from original
            raise LinkError(
                f"Transfer failed for {tag}; the link was restored to the original user as unverified. "
                "Previous verification and private link settings were not restored."
            ) from original


async def run_batch(client: LinkClient, source: int, selection: str,
                    destination: int | None = None) -> Result:
    if destination == source:
        raise LinkError("Select a different destination user.")
    tag = None if selection.strip().lower() == "all" else player_tag(selection)
    # Full authenticated list includes hidden links; the shared lookup omits them.
    links = await client.links(source)
    selected = [link for link in links if tag is None or link.tag == tag]
    if not selected:
        raise LinkError("No matching accounts are linked to the selected user.")
    if destination is not None:
        await client.links(destination)  # Permission check before the first deletion.
    result = Result([link.tag for link in selected])
    deadline = time.monotonic() + BATCH_SECONDS
    for link in selected:
        if time.monotonic() >= deadline:
            result.problem = "Stopped at the time limit. Run the command again for remaining accounts."
            break
        try:
            # Verify the selected source still owns this tag before each mutation.
            current = await client.links(source)
            if not any(item.tag == link.tag for item in current):
                raise LinkError(f"{link.tag} is no longer linked to the selected source user.")
            if destination is None:
                await client.unlink(source, link.tag)
            else:
                await client.transfer(source, destination, link.tag)
            result.completed.append(link.tag)
        except LinkError as exc:
            result.problem = f"Stopped at {link.tag}: {exc}"
            break
    return result


async def manage_links(source: int, selection: str, destination: int | None = None) -> Result:
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        raise LinkError(
            f"Account-management access is not configured ({TOKEN_ENV}). "
            "Ask ClashKing for bot access; the existing shared-lookup token cannot manage accounts."
        )
    if _mutation_lock.locked():
        raise LinkError("Another link operation is running. Try again when it finishes.")
    async with _mutation_lock:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            return await run_batch(LinkClient(session, token), source, selection, destination)

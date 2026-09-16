"""Preview/backfill status emojis on completed imported ticket thread pairs."""
from __future__ import annotations

import argparse, asyncio, os, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import quote

import aiohttp
from dotenv import load_dotenv
from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.commands import ticket_runtime  # noqa: E402
from extensions.commands.tickets import thread_service  # noqa: E402

RUN_COLLECTION = "ticket_thread_rename_runs"
LEASE_ID = "ticket_thread_status_emoji:active"
LEASE_DURATION = timedelta(minutes=10)
CAPABILITY_MAX_AGE = timedelta(seconds=180)
SERIAL_EDIT_DELAY_SECONDS = 1.0


def utcnow():
    return datetime.now(timezone.utc)


def desired_names(ticket: Mapping[str, Any], *, ghosted: bool = False):
    return thread_service.thread_names(
        str(ticket.get("ticket_type") or ""), int(ticket.get("ticket_number") or 0),
        str(ticket.get("username") or "candidate"),
        status=str(ticket.get("status") or "closed"),
        ghosted=ghosted,
    )


async def desired_names_current(db, ticket: Mapping[str, Any]):
    """Keep an active identity-wide ghost report ahead of status backfill."""
    from extensions.commands.tickets import flag_store
    ids = flag_store._discord_ids(ticket.get("user_id"))
    tags = flag_store.schema.player_tags([
        *(ticket.get("player_tags") or ticket.get("playerTags") or ()),
        ticket.get("player_tag") or ticket.get("tag"),
    ])
    clauses = flag_store._identity_query(ids, tags)
    ghosted = bool(clauses and await db.ticket_flags.find_one({
        "kind": flag_store.FLAG_GHOSTED, "active": True, "$or": clauses,
    }))
    return desired_names(ticket, ghosted=ghosted)


def is_completed_import(ticket: Mapping[str, Any], completed_ids: set[str]):
    return (str(ticket.get("_id")) in completed_ids
            and ticket.get("runtime") == ticket_runtime.THREAD_RUNTIME
            and ticket.get("venue") == "thread"
            and str(ticket.get("status")) in {"approved", "denied", "closed"}
            and bool(ticket.get("source")))


def deployed_capability_ready(config: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    heartbeat = config.get("thread_name_capability_heartbeat_at")
    if isinstance(heartbeat, datetime) and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    current = now or utcnow()
    return (
        int(config.get("thread_name_capability_version") or 0)
        >= thread_service.THREAD_NAME_CAPABILITY_VERSION
        and isinstance(config.get("thread_name_capability_booted_at"), datetime)
        and bool(config.get("thread_name_capability_boot_id"))
        and isinstance(heartbeat, datetime)
        and timedelta(0) <= current - heartbeat <= CAPABILITY_MAX_AGE
    )


async def _discord_json(session, method, path, token, *, reason=None, **kwargs):
    headers = {"Authorization": f"Bot {token}"}
    if reason:
        headers["X-Audit-Log-Reason"] = quote(str(reason), safe=" ")
    async with session.request(method, f"https://discord.com/api/v10{path}",
                               headers=headers, **kwargs) as response:
        if response.status == 429:
            body = await response.json()
            await asyncio.sleep(float(body.get("retry_after") or 1))
            return await _discord_json(session, method, path, token,
                                       reason=reason, **kwargs)
        if response.status >= 400:
            raise RuntimeError(f"Discord {method} {path} returned {response.status}")
        return await response.json() if response.content_type == "application/json" else None


async def rename_one(session, token: str, thread_id: int, target: str,
                     checkpoint: Mapping[str, Any] | None,
                     save: Callable[[Mapping[str, Any]], Awaitable[None]]):
    """Phase-checkpoint one edit, preserving pre-edit archive/lock flags."""
    channel = await _discord_json(session, "GET", f"/channels/{thread_id}", token)
    state = dict(checkpoint or {})
    if state.get("state") == "complete" and state.get("target") == target:
        return "already_correct"
    if (state.get("target") != target
            and state.get("state") in {"planned", "unarchived", "renamed"}
            and "original_archived" in state and "original_locked" in state):
        # Finish the old plan's safety obligation before replacing a stale
        # target after an overturn. Otherwise an interrupted old unarchive
        # would become the new plan's observed baseline and stay active.
        restore = {"archived": bool(state["original_archived"]),
                   "locked": bool(state["original_locked"])}
        meta = channel.get("thread_metadata") or {}
        if bool(meta.get("archived")) != restore["archived"] or bool(meta.get("locked")) != restore["locked"]:
            await _discord_json(session, "PATCH", f"/channels/{thread_id}", token,
                                json=restore,
                                reason="Restore ticket thread state after status change")
        channel = await _discord_json(session, "GET", f"/channels/{thread_id}", token)
    if state.get("target") != target or state.get("state") not in {
        "planned", "unarchived", "renamed",
    }:
        meta = channel.get("thread_metadata") or {}
        state = {"state": "planned", "target": target, "thread_id": thread_id,
                 "original_name": str(channel.get("name") or ""),
                 "original_archived": bool(meta.get("archived")),
                 "original_locked": bool(meta.get("locked")), "updated_at": utcnow()}
        await save(state)
    if state["state"] == "planned":
        if bool((channel.get("thread_metadata") or {}).get("archived")):
            await _discord_json(session, "PATCH", f"/channels/{thread_id}", token,
                                json={"archived": False},
                                reason="Ticket status emoji backfill")
        state = {**state, "state": "unarchived", "updated_at": utcnow()}
        await save(state)
    if state["state"] == "unarchived":
        channel = await _discord_json(session, "GET", f"/channels/{thread_id}", token)
        if str(channel.get("name") or "") != target:
            await _discord_json(session, "PATCH", f"/channels/{thread_id}", token,
                                json={"name": target},
                                reason="Ticket status emoji backfill")
        state = {**state, "state": "renamed", "updated_at": utcnow()}
        await save(state)
    if state["state"] == "renamed":
        channel = await _discord_json(session, "GET", f"/channels/{thread_id}", token)
        meta = channel.get("thread_metadata") or {}
        restore = {"archived": bool(state["original_archived"]),
                   "locked": bool(state["original_locked"])}
        if bool(meta.get("archived")) != restore["archived"] or bool(meta.get("locked")) != restore["locked"]:
            await _discord_json(session, "PATCH", f"/channels/{thread_id}", token,
                                json=restore,
                                reason="Restore ticket thread state after emoji backfill")
        await save({**state, "state": "complete", "updated_at": utcnow()})
    return "renamed"


async def _acquire_lease(runs, owner, run_id):
    now = utcnow()
    try:
        row = await runs.find_one_and_update(
            {"_id": LEASE_ID, "$or": [{"lease_until": {"$lte": now}},
                                        {"lease_until": {"$exists": False}},
                                        {"lease_owner": owner}]},
            {"$set": {"lease_owner": owner, "lease_until": now + LEASE_DURATION,
                      "run_id": run_id, "updated_at": now}}, upsert=True,
            return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        return False
    return bool(row and row.get("lease_owner") == owner)


async def _renew_lease(runs, owner):
    result = await runs.update_one(
        {"_id": LEASE_ID, "lease_owner": owner},
        {"$set": {"lease_until": utcnow() + LEASE_DURATION, "updated_at": utcnow()}})
    if not getattr(result, "matched_count", 0):
        raise RuntimeError("maintenance ownership lease was lost")


async def run(args):
    load_dotenv(ROOT / ".env")
    uri, token = os.getenv("MONGODB_URI", ""), os.getenv("DISCORD_TOKEN", "")
    if not uri or not token:
        print("MONGODB_URI and DISCORD_TOKEN must be set", file=sys.stderr); return 2
    mongo = AsyncMongoClient(uri); db = mongo["settings"]
    runs, owner, leased = db[RUN_COLLECTION], uuid.uuid4().hex, False
    try:
        if args.apply:
            config = await db.ticket_setup.find_one({"_id": "config"}) or {}
            if not deployed_capability_ready(config):
                print("Refusing --apply: running bot has not published the required thread-name capability", file=sys.stderr)
                return 2
        completed = {str(row["ticket_id"]) async for row in db.ticket_migrations.find(
            {"kind": "legacy_thread_migration", "state": "complete", "ticket_id": {"$exists": True}},
            {"ticket_id": 1})}
        tickets = [row async for row in db.tickets.find(
            {"runtime": ticket_runtime.THREAD_RUNTIME, "venue": "thread"})
            if is_completed_import(row, completed)]
        async with aiohttp.ClientSession() as session:
            if not args.apply:
                for ticket in tickets:
                    loc, names = ticket.get("location") or {}, await desired_names_current(db, ticket)
                    for role, tid, target in (("public", int(loc.get("id") or 0), names[0]),
                                              ("staff", int(loc.get("staff_space_id") or 0), names[1])):
                        current = "<missing id>" if not tid else str((await _discord_json(
                            session, "GET", f"/channels/{tid}", token)).get("name") or "")
                        print(f"PREVIEW ticket={ticket['_id']} {role}={tid} {current!r} -> {target!r}")
                print(f"Preview: {len(tickets)} completed imported ticket pair(s); no changes made.")
                return 0
            leased = await _acquire_lease(runs, owner, args.run_id)
            if not leased:
                print("Another rename run owns the maintenance lease", file=sys.stderr); return 2
            await runs.update_one({"_id": args.run_id},
                {"$setOnInsert": {"created_at": utcnow(), "kind": "ticket_thread_status_emoji"},
                 "$set": {"updated_at": utcnow(),
                          "capability_version": thread_service.THREAD_NAME_CAPABILITY_VERSION}},
                upsert=True)
            renamed = skipped = failed = 0
            for original in tickets:
                ticket = await db.tickets.find_one({"_id": original["_id"]})
                if not ticket or not is_completed_import(ticket, completed): skipped += 1; continue
                effects = ticket.get("resolution_effects") or {}; until = effects.get("lease_until")
                if effects.get("lease_owner") and isinstance(until, datetime) and until > utcnow():
                    skipped += 1; continue
                loc = ticket.get("location") or {}
                for role, tid in (("public", int(loc.get("id") or 0)),
                                  ("staff", int(loc.get("staff_space_id") or 0))):
                    if not tid: skipped += 1; continue
                    live_config = await db.ticket_setup.find_one({"_id": "config"}) or {}
                    if not deployed_capability_ready(live_config):
                        raise RuntimeError("running bot thread-name capability heartbeat is stale")
                    # A decision/overturn may land between the two halves.
                    # Re-read immediately before each Discord workflow and
                    # derive this half's target from the newest durable status.
                    latest = await db.tickets.find_one({"_id": original["_id"]})
                    if not latest or not is_completed_import(latest, completed):
                        skipped += 1; continue
                    current_effects = latest.get("resolution_effects") or {}
                    current_until = current_effects.get("lease_until")
                    if (current_effects.get("lease_owner")
                            and isinstance(current_until, datetime)
                            and current_until > utcnow()):
                        skipped += 1; continue
                    pair_names = await desired_names_current(db, latest)
                    target = pair_names[0] if role == "public" else pair_names[1]
                    await _renew_lease(runs, owner)
                    path = f"threads.{ticket['_id']}.{role}"
                    row = await runs.find_one({"_id": args.run_id}) or {}
                    cp = ((row.get("threads") or {}).get(str(ticket["_id"])) or {}).get(role)
                    async def save(value, p=path):
                        await runs.update_one({"_id": args.run_id},
                            {"$set": {p: dict(value), "updated_at": utcnow()}})
                    try: result = await rename_one(session, token, tid, target, cp, save)
                    except Exception as exc:
                        failed += 1
                        # rename_one checkpoints every phase before its Discord
                        # mutation. Do not replace that recovery state here: a
                        # crash after unarchive must retain the original flags.
                        await runs.update_one(
                            {"_id": args.run_id},
                            {"$set": {f"errors.{ticket['_id']}.{role}": {
                                "error": f"{type(exc).__name__}: {exc}",
                                "updated_at": utcnow(),
                            }}},
                        )
                    else:
                        renamed += result == "renamed"; skipped += result == "already_correct"
                    await asyncio.sleep(SERIAL_EDIT_DELAY_SECONDS)
            print(f"Run {args.run_id}: renamed={renamed} skipped={skipped} failed={failed}")
            return 1 if failed else 0
    finally:
        if leased:
            await runs.update_one({"_id": LEASE_ID, "lease_owner": owner},
                {"$unset": {"lease_owner": "", "lease_until": ""}, "$set": {"updated_at": utcnow()}})
        await mongo.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.apply and not args.run_id: parser.error("--apply requires --run-id")
    return asyncio.run(run(args))


if __name__ == "__main__": raise SystemExit(main())

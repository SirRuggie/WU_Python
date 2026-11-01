"""Explicit declaration delivery jobs. Never resume or retry a Discord POST."""

import asyncio
import hashlib
import logging
from uuid import uuid4

from extensions.cwl_declaration_transport import DeclarationPingTransport, PingRejected
from utils.declaration_ping_store import DeclarationPingStore
from . import declaration_destinations
from .server_management import GUILD_ID, mongo

log = logging.getLogger(__name__)


async def lifecycle(app):
    app["declaration_runtime"] = uuid4().hex
    app["declaration_tasks"] = set()
    app["declaration_running_tokens"] = set()
    app["declaration_test_jobs"] = {}
    yield
    tasks = list(app["declaration_tasks"])
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def public_receipt(row):
    if not row:
        return None
    keys = (
        "token",
        "actor_id",
        "actor_name",
        "season_id",
        "channel",
        "created_at",
        "state",
        "test",
        "pool",
        "count",
        "unlinked",
        "chunks",
        "next",
        "attempting",
        "posted",
        "error",
        "finished_at",
    )
    return {key: row.get(key) for key in keys}


def launch(request, active, plan, *, test=False):
    running = request.app["declaration_running_tokens"]
    running.add(active["token"])
    task = asyncio.create_task(deliver(request, active, plan, test=test))
    tasks = request.app["declaration_tasks"]
    tasks.add(task)

    def completed(done):
        tasks.discard(done)
        running.discard(active["token"])
        if not done.cancelled() and done.exception():
            log.error(
                "Declaration worker stopped before its final receipt token=%s",
                active["token"],
                exc_info=done.exception(),
            )

    task.add_done_callback(completed)


def visible_active(request, row):
    result = public_receipt(row)
    if row and row["token"] not in request.app["declaration_running_tokens"]:
        result.update(
            state="uncertain",
            error="The worker stopped before its final receipt. Inspect the channel; no retry was attempted.",
        )
    return result


async def deliver(request, active, plan, *, test=False):
    token, pool = active["token"], active["pool"]
    state, error = "uncertain", None
    transport = request.app.get("declaration_transport") or DeclarationPingTransport()
    async with mongo(request) as client:
        storage = DeclarationPingStore(client, GUILD_ID)
        try:
            for index, payload in enumerate(plan):
                if not await declaration_destinations.authorized(
                    request, active["actor_id"]
                ):
                    raise PermissionError("Send permission was removed")
                await declaration_destinations.destination(
                    request, active["channel"]["id"]
                )
                # Finish the immutable reviewed list; unrelated or concurrent lineup
                # edits cannot abandon a half-delivered notification. Permissions
                # and destination ownership are still checked before every POST.
                if test:
                    active["attempting"] = index
                else:
                    await storage.begin_chunk(pool, token, index)
                nonce = hashlib.sha256(f"{token}:{index}".encode()).hexdigest()[:24]
                try:
                    message = await transport.send(
                        active["channel"]["id"], payload, nonce, test=test
                    )
                except PingRejected:
                    # A definite refusal may safely clear the in-flight marker.
                    if test:
                        active["attempting"] = None
                    else:
                        await storage.rejected(pool, token, index)
                    raise
                if test:
                    active["posted"].append({"chunk": index, "message_id": message})
                    active.update(next=index + 1, attempting=None)
                else:
                    await storage.posted(pool, token, index, message)
                if index + 1 < len(plan):
                    await asyncio.sleep(1.1)
            state = "done"
        except asyncio.CancelledError:
            state, error = (
                "uncertain",
                "The process stopped. Inspect the channel; no retry was attempted.",
            )
        except Exception as exc:
            # Store failures after acceptance leave the durable attempting marker.
            state = "uncertain"
            error = str(getattr(exc, "text", None) or exc)[:500]
            try:
                current = active if test else await storage.receipt(pool, token)
            except Exception:
                log.exception("Declaration receipt readback failed token=%s", token)
            else:
                state = (
                    "uncertain"
                    if not current or current.get("attempting") is not None
                    else "partial" if current.get("posted") else "failed"
                )
            log.warning(
                "Declaration ping stopped pool=%s token=%s state=%s", pool, token, state
            )
        finally:
            if test:
                active.update(state=state, error=error)
                await storage.release_test(pool, token)
            else:
                await storage.finish(pool, token, state, error)

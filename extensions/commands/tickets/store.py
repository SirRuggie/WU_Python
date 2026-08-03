"""The single seam between ticket documents and the collection that holds them.

Ticket documents were originally written into `button_store` - the same
collection the component dispatcher uses for ephemeral component kwargs. Durable
business records interleaved with throwaway UI state, unindexed, by accident
rather than by design. See docs/ticket-data-model.md.

Phase 1 moves them into a dedicated `tickets` collection. Every ticket-document
read and write in the bot goes through this module, so the transition has exactly
one home.

READS follow the `ticket_store` flag on ticket_setup/_id="config", defaulting to
`button_store`. WRITES always go to BOTH collections for the duration of the
transition, so flipping the flag either way strands nothing.

Making the read switch a config value rather than a deploy is deliberate: it
means the backfill and the code repoint cannot land in the wrong order. The code
can ship first and change nothing, and the moment of risk becomes a single Mongo
write that reverses in a second.

DO NOT ADD A TTL INDEX TO `tickets`. Ticket history is permanent and referred
back to. The pruning problem that motivated part of this move belongs to the
ephemeral collection, not this one - see docs/ticket-data-model.md.
"""

import dataclasses
import logging
from collections import Counter
from datetime import datetime, timezone

from pymongo import ReturnDocument

from utils.mongo import MongoClient

_log = logging.getLogger(__name__)

# Ticket documents carry this discriminator. It is redundant inside `tickets`,
# where every document is a ticket, but keeping it means a document copied in
# either direction is still valid, and the queries do not have to fork.
TICKET_FILTER = {"type": "ticket"}

STORE_BUTTON = "button_store"
STORE_TICKETS = "tickets"
DEFAULT_STORE = STORE_BUTTON


def as_int(value) -> int:
    """Channel/user ids have been stored as both int and str across schema versions.

    Canonical home; manage.py imports this as its `_as_int`.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def active_store(mongo: MongoClient) -> str:
    """Which collection reads currently come from.

    Read fresh every call rather than cached at startup. The `ticket_config`
    global in __init__.py is the cautionary tale: it is loaded once on
    StartedEvent and read by nothing, while every real consumer re-queries. A
    cached flag here would mean a flip needed a restart, which defeats the point
    of it being a flag.
    """
    config = await mongo.ticket_setup.find_one({"_id": "config"}, {"ticket_store": 1})
    return (config or {}).get("ticket_store", DEFAULT_STORE)


async def _reader(mongo: MongoClient):
    return mongo.tickets if await active_store(mongo) == STORE_TICKETS else mongo.button_store


async def _both(mongo: MongoClient):
    """(primary, secondary) with primary being whatever reads come from.

    Ordering matters on partial failure: if the second write raises, the
    collection actually being READ from is already correct, so the symptom is
    divergence visible in /ticket diagnostics rather than a ticket that appears
    not to exist.
    """
    if await active_store(mongo) == STORE_TICKETS:
        return mongo.tickets, mongo.button_store
    return mongo.button_store, mongo.tickets


# --- reads -------------------------------------------------------------------

async def find_one(mongo: MongoClient, filt: dict):
    return await (await _reader(mongo)).find_one(filt)


async def find(mongo: MongoClient, filt: dict) -> list[dict]:
    """All matching ticket documents. Callers all wanted a list anyway."""
    return await (await _reader(mongo)).find(filt).to_list(length=None)


# --- writes (always both) ----------------------------------------------------

async def insert_one(mongo: MongoClient, doc: dict) -> None:
    primary, secondary = await _both(mongo)
    # dict() per call: insert_one mutates its argument to attach _id when absent.
    # Ticket documents always carry an explicit _id, but sharing one dict between
    # two drivers is the kind of thing that only breaks once.
    await primary.insert_one(dict(doc))
    await secondary.insert_one(dict(doc))


async def update_one(mongo: MongoClient, filt: dict, update: dict):
    """Returns the PRIMARY result, so matched_count still means what callers think.

    close.py checks matched_count to catch silent no-op status writes
    (_status_write_warning). That check has to be against the collection being
    read from, or it reports on the wrong side of the transition.
    """
    primary, secondary = await _both(mongo)
    result = await primary.update_one(filt, update)
    await secondary.update_one(filt, update)
    return result


async def update_many(mongo: MongoClient, filt: dict, update: dict):
    primary, secondary = await _both(mongo)
    result = await primary.update_many(filt, update)
    await secondary.update_many(filt, update)
    return result


# --- conditional writes ------------------------------------------------------
#
# Everything below exists because an unconditional $set loses updates. Two
# recruiters resolving one ticket in the same second both used to succeed, both
# ran their side effects, and the last write silently won. The pattern here is
# the one already proven in manage.py's cleanup filter: re-assert the status you
# believe you are transitioning FROM, inside the filter, so Mongo arbitrates
# rather than the network.
#
# The rule that makes it worth anything: SIDE EFFECTS RUN ONLY ON "won".

WON = "won"
LOST = "lost"
MISSING = "missing"


@dataclasses.dataclass(frozen=True, slots=True)
class Transition:
    """Result of a conditional ticket write.

    outcome == WON     -> this caller caused the change. `doc` is the post-image.
                          Side effects are permitted, and only here.
    outcome == LOST    -> the precondition did not hold. `doc` is the CURRENT
                          document, so the caller can say who got there first and
                          when. Nothing was written.
    outcome == MISSING -> no such ticket. `doc` is None. Nothing was written.
    """

    outcome: str
    doc: dict | None

    @property
    def won(self) -> bool:
        return self.outcome == WON


async def _mirror(mongo: MongoClient, doc: dict) -> None:
    """Copy a post-image onto the secondary collection, unconditionally.

    Deliberately NOT conditional. The secondary is a copy kept so the
    `ticket_store` flag stays reversible; it is not a second opinion. Re-applying
    the precondition here would let a drifted secondary silently refuse and the
    divergence would compound. Mirroring the post-image instead means a
    conditional write HEALS drift rather than perpetuating it.

    Safe because nothing else writes ticket documents to the secondary - every
    path goes through this module - so there is no concurrent writer to clobber.
    """
    _, secondary = await _both(mongo)
    try:
        await secondary.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    except Exception:
        # The primary has already committed and the primary is what reads come
        # from, so the outcome stands. Divergence shows up in /ticket diagnostics.
        _log.exception("ticket mirror failed for %s - collections have diverged", doc.get("_id"))


async def _conditional(
        mongo: MongoClient,
        filt: dict,
        update: dict,
        ticket_id,
) -> Transition:
    """find_one_and_update against the primary, then mirror on success."""
    primary, _ = await _both(mongo)
    doc = await primary.find_one_and_update(
        filt, update, return_document=ReturnDocument.AFTER
    )
    if doc is not None:
        await _mirror(mongo, doc)
        return Transition(WON, doc)

    # Nothing matched. Distinguish "someone beat me to it" from "no such ticket",
    # because they need completely different things said to the user.
    current = await primary.find_one({"_id": ticket_id})
    return Transition(LOST, current) if current is not None else Transition(MISSING, None)


async def transition(
        mongo: MongoClient,
        ticket_id,
        *,
        to_status: str,
        actor_id: int,
        actor_name: str,
        expect: str | None = "open",
        extra: dict | None = None,
        overrides: dict | None = None,
) -> Transition:
    """Move a ticket to `to_status`, only if it is currently `expect`.

    expect=None performs the write unconditionally. That is the override path -
    a recruiter deliberately overturning a resolution someone else already made,
    which is normal in recruiting (a mistaken deny, an appeal, a leader's call)
    and should not require hand-editing Mongo.

    `overrides` is the prior resolution the actor was SHOWN before confirming.
    It is recorded verbatim in the audit entry. Note the small TOCTOU: a third
    write landing between the actor reading the warning and confirming it would
    not be reflected. That is accepted deliberately - the audit records what the
    human was told and acted on, which is the more useful record of a decision.
    """
    now = datetime.now(timezone.utc)

    audit = {
        "at": now,
        "actor": actor_id,
        "actor_name": actor_name,
        "to": to_status,
        "from": expect if expect is not None else (overrides or {}).get("status"),
        "override": overrides is not None,
    }
    if overrides:
        audit["overrode"] = {
            "status": overrides.get("status"),
            "by": overrides.get("by"),
            "by_name": overrides.get("by_name"),
            "at": overrides.get("at"),
        }

    filt = {"_id": ticket_id}
    if expect is not None:
        filt["status"] = expect

    return await _conditional(
        mongo,
        filt,
        {"$set": {"status": to_status, **(extra or {})}, "$push": {"audit": audit}},
        ticket_id,
    )


async def claim(mongo: MongoClient, ticket_id, actor_id: int, actor_name: str) -> Transition:
    """Advisory claim. Discord cannot enforce ownership inside a thread, so this
    records and signals intent - it does not prevent anyone acting.

    `{"claimed_by": None}` matches documents where the field is null OR absent,
    which is every ticket written before this existed. No backfill needed.
    """
    now = datetime.now(timezone.utc)
    return await _conditional(
        mongo,
        {"_id": ticket_id, "status": "open", "claimed_by": None},
        {
            "$set": {"claimed_by": actor_id, "claimed_by_name": actor_name, "claimed_at": now},
            "$push": {"audit": {
                "at": now, "actor": actor_id, "actor_name": actor_name, "to": "claimed",
            }},
        },
        ticket_id,
    )


async def release(
        mongo: MongoClient,
        ticket_id,
        actor_id: int,
        actor_name: str,
        *,
        force: bool = False,
) -> Transition:
    """Give up a claim. `force` lets an admin release someone else's."""
    now = datetime.now(timezone.utc)
    filt = {"_id": ticket_id, "claimed_by": {"$ne": None}}
    if not force:
        filt["claimed_by"] = actor_id

    return await _conditional(
        mongo,
        filt,
        {
            "$set": {"claimed_by": None, "claimed_by_name": None, "claimed_at": None},
            "$push": {"audit": {
                "at": now, "actor": actor_id, "actor_name": actor_name,
                "to": "released", "forced": force,
            }},
        },
        ticket_id,
    )


# --- reconciliation helpers --------------------------------------------------

async def status_counts(collection) -> dict[str, int]:
    """{status: count} for ticket documents in one collection.

    Takes a collection rather than the client because both /ticket diagnostics
    and the backfill need to compare the two sides directly.
    """
    docs = await collection.find(TICKET_FILTER, {"status": 1}).to_list(length=None)
    return dict(Counter(d.get("status") or "(missing)" for d in docs))

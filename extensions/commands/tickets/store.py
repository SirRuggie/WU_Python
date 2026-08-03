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

from collections import Counter

from utils.mongo import MongoClient

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


# --- reconciliation helpers --------------------------------------------------

async def status_counts(collection) -> dict[str, int]:
    """{status: count} for ticket documents in one collection.

    Takes a collection rather than the client because both /ticket diagnostics
    and the backfill need to compare the two sides directly.
    """
    docs = await collection.find(TICKET_FILTER, {"status": 1}).to_list(length=None)
    return dict(Counter(d.get("status") or "(missing)" for d in docs))

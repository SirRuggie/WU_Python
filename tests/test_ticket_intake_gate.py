"""A stuck committed ticket must never permanently gate new-ticket intake.

``thread_service.recover_pending_thread_ticket_creations`` used to count a
committed ticket's own unresolved problem -- delivery still pending, its
Discord thread returning 404/403, or its shared slot already released for a
terminal decision -- as a FAILED recovery item, forever, because nothing
ever retired the row. ``extensions.commands.tickets.__init__.recover_ticket_workflows``
raises whenever any recovery batch reports a failure, which keeps
``_thread_intake_ready`` false and refuses every ``ticket_v2_create`` click.
These tests pin the fixed behaviour: such rows are reported as ``degraded``
(logged, annotated, and marked complete so they drop out of the next pass)
and never counted toward ``failed``.
"""

import asyncio
from types import SimpleNamespace

import hikari

from extensions.commands import ticket_runtime
from extensions.commands.tickets import store, thread_service


async def _no_op(*_args, **_kwargs):
    return None


def _state(*, guild_id=10, user_id=30, ticket_type="main"):
    creation_id = f"thread:{user_id}:{ticket_type}"
    return {
        "_id": creation_id,
        "kind": "thread_ticket_creation",
        "state": "delivery_retry",
        "guild_id": guild_id,
        "user_id": user_id,
        "ticket_type": ticket_type,
        "username": "Applicant",
        "display_name": "Applicant",
        "candidate_parent_id": 20,
        "staff_parent_id": 21,
        "recruiter_role_id": 40,
        "open_slot_id": f"ticket-open:{user_id}:{ticket_type}",
        "creation_workflow_id": creation_id,
        "ticket_id": "ticket_101",
        "candidate_thread_id": 101,
        "staff_thread_id": 102,
    }


def _open_slot(state, *, ticket_id="ticket_101"):
    return {
        "_id": state["open_slot_id"],
        "state": ticket_runtime.SLOT_OPEN,
        "route": ticket_runtime.ROUTE_THREAD,
        "guild_id": state["guild_id"],
        "workflow_id": state["creation_workflow_id"],
        "ticket_id": ticket_id,
    }


def _ticket(*, status="open"):
    return {
        "_id": "ticket_101",
        "ticket_number": 5,
        "guild_id": 10,
        "user_id": 30,
        "username": "Applicant",
        "display_name": "Applicant",
        "ticket_type": "main",
        "location": {
            "id": 101,
            "staff_space_id": 102,
            "public_parent_id": 20,
            "staff_parent_id": 21,
        },
        "recruiter_role_id": 40,
        "status": status,
    }


class Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, _amount):
        return self

    async def to_list(self, *, length):
        return list(self._docs[:length])


class CreationStates:
    """A minimal ``ticket_creation_state`` fake that actually honours the
    ``state != complete`` filter, so a retired row is provably not reselected.
    """

    def __init__(self, docs):
        self.docs = {doc["_id"]: dict(doc) for doc in docs}

    def find(self, query):
        matches = [
            dict(doc)
            for doc in self.docs.values()
            if doc.get("kind") == query.get("kind") and doc.get("state") != "complete"
        ]
        return Cursor(matches)

    async def update_one(self, query, update, **_kwargs):
        doc_id = query["_id"]
        doc = self.docs.setdefault(doc_id, {"_id": doc_id})
        doc.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        return SimpleNamespace(matched_count=1)


class OpenSlots:
    def __init__(self, slot=None):
        self.slot = dict(slot) if slot else None

    async def find_one(self, query):
        if self.slot and self.slot.get("_id") == query.get("_id"):
            return dict(self.slot)
        return None


class Tickets:
    def __init__(self):
        self.updates = []

    async def update_one(self, query, update, **_kwargs):
        self.updates.append((query, update))
        return SimpleNamespace(matched_count=1)


def _mongo(*, states, slot=None):
    return SimpleNamespace(
        ticket_creation_state=CreationStates(states),
        ticket_open_slots=OpenSlots(slot),
        tickets=Tickets(),
    )


def test_committed_ticket_with_pending_delivery_is_degraded_not_failed(monkeypatch):
    """(a) A committed ticket whose opening delivery is still pending must be
    reported as degraded, not failed, so intake stays ready."""
    state = _state()
    mongo = _mongo(states=[state], slot=_open_slot(state))
    ticket = _ticket(status="open")

    async def committed(*_args, **_kwargs):
        return dict(ticket)

    async def reconcile(_bot, _mongo, received_ticket, *, coc_client=None):
        return thread_service.CreatedThreadTicket(
            received_ticket, resumed=True, delivery_pending=True
        )

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", _no_op)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", committed)
    monkeypatch.setattr(thread_service, "_reconcile_existing_ticket", reconcile)

    result = asyncio.run(thread_service.recover_pending_thread_ticket_creations(
        bot=object(), mongo=mongo
    ))

    assert result == {"processed": 1, "completed": 0, "degraded": 1, "failed": 0}
    row = mongo.ticket_creation_state.docs[state["_id"]]
    assert row["state"] == "complete"
    assert row["recovery_note"]
    assert "recovery_noted_at" in row
    # The ticket document is also annotated for staff visibility.
    assert mongo.tickets.updates
    annotated = mongo.tickets.updates[0][1]["$set"]
    assert annotated["creation_state.recovery_note"]


def test_candidate_thread_fetch_not_found_is_degraded_not_failed(monkeypatch):
    """(b) A 404 while reconciling the candidate/staff thread pair is the
    same per-ticket problem as (a) and must not count as failed."""
    state = _state()
    mongo = _mongo(states=[state], slot=_open_slot(state))
    ticket = _ticket(status="open")

    async def committed(*_args, **_kwargs):
        return dict(ticket)

    class Rest:
        async def fetch_channel(self, channel_id):
            if channel_id == ticket["location"]["id"]:
                raise hikari.NotFoundError(
                    url="https://discord.test", headers={}, raw_body="unknown channel"
                )
            return SimpleNamespace(id=channel_id, is_archived=False, is_locked=False)

    bot = SimpleNamespace(rest=Rest())

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", _no_op)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", committed)
    monkeypatch.setattr(thread_service, "notify_console_after_change", _no_op)

    result = asyncio.run(thread_service.recover_pending_thread_ticket_creations(
        bot=bot, mongo=mongo
    ))

    assert result == {"processed": 1, "completed": 0, "degraded": 1, "failed": 0}
    assert mongo.ticket_creation_state.docs[state["_id"]]["state"] == "complete"


def test_terminal_ticket_with_missing_slot_completes_without_failure(monkeypatch):
    """(c) Once a ticket is approved/denied its open slot is deleted; the
    recovery pass must retire the row as complete, not raise SlotConflict."""
    state = _state()
    # The open slot is already gone, so the recovery pass falls into the
    # "resume" branch instead of the "already-open, reconcile" branch.
    mongo = _mongo(states=[state], slot=None)
    ticket = _ticket(status="approved")

    async def committed(*_args, **_kwargs):
        return dict(ticket)

    async def resume(_mongo, **_kwargs):
        raise ticket_runtime.SlotConflict("open slot no longer exists")

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", _no_op)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", committed)
    monkeypatch.setattr(ticket_runtime, "resume_open_slot", resume)

    result = asyncio.run(thread_service.recover_pending_thread_ticket_creations(
        bot=object(), mongo=mongo
    ))

    assert result == {"processed": 1, "completed": 0, "degraded": 1, "failed": 0}
    row = mongo.ticket_creation_state.docs[state["_id"]]
    assert row["state"] == "complete"
    assert "terminal" in row["recovery_note"]


def test_missing_thread_config_binding_still_counts_as_failed(monkeypatch):
    """(d) A genuine runtime-level problem -- here, a row with no target
    guild binding -- must keep gating intake exactly as before."""
    state = _state(guild_id=0)
    mongo = _mongo(states=[state], slot=None)

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", _no_op)

    result = asyncio.run(thread_service.recover_pending_thread_ticket_creations(
        bot=object(), mongo=mongo
    ))

    assert result == {"processed": 1, "completed": 0, "degraded": 0, "failed": 1}


def test_degraded_row_is_not_reselected_on_the_next_pass(monkeypatch):
    """(e) Once a row is retired as degraded, the next recovery pass must not
    pick it up again -- this is what stops the infinite reselect."""
    state = _state()
    mongo = _mongo(states=[state], slot=_open_slot(state))
    ticket = _ticket(status="open")

    async def committed(*_args, **_kwargs):
        return dict(ticket)

    async def reconcile(_bot, _mongo, received_ticket, *, coc_client=None):
        return thread_service.CreatedThreadTicket(
            received_ticket, resumed=True, delivery_pending=True
        )

    monkeypatch.setattr(thread_service, "ensure_creation_indexes", _no_op)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", committed)
    monkeypatch.setattr(thread_service, "_reconcile_existing_ticket", reconcile)

    first = asyncio.run(thread_service.recover_pending_thread_ticket_creations(
        bot=object(), mongo=mongo
    ))
    assert first == {"processed": 1, "completed": 0, "degraded": 1, "failed": 0}

    second = asyncio.run(thread_service.recover_pending_thread_ticket_creations(
        bot=object(), mongo=mongo
    ))
    assert second == {"processed": 0, "completed": 0, "degraded": 0, "failed": 0}


def test_terminal_transition_retires_the_creation_state_row(monkeypatch):
    """store.transition marks a terminal ticket's creation-state row complete
    directly, so a fresh approval/denial never even reaches recovery."""
    calls = []

    async def mark_complete(_mongo, ticket):
        calls.append(ticket["_id"])

    monkeypatch.setattr(thread_service, "mark_creation_complete_for_terminal_ticket", mark_complete)
    monkeypatch.setattr(ticket_runtime, "mark_slot_release_pending", _no_op)
    monkeypatch.setattr(ticket_runtime, "release_open_slot", _no_op)

    async def conditional(_mongo, _filt, _update, ticket_id):
        return store.Transition(store.WON, {"_id": ticket_id, "status": "approved"})

    monkeypatch.setattr(store, "_conditional", conditional)

    class SourceTickets:
        async def find_one(self, _query):
            return {"_id": "ticket_101", "status": "open", "rev": 0}

    mongo = SimpleNamespace(tickets=SourceTickets())
    outcome = asyncio.run(store.transition(
        mongo,
        "ticket_101",
        to_status="approved",
        actor_id=1,
        actor_name="Recruiter",
    ))

    assert outcome.won
    assert calls == ["ticket_101"]

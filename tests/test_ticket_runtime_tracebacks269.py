"""Ticket runtime lease and busy-identity regressions; isolated fixtures only."""
import asyncio
import copy
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from extensions.commands.tickets import console, flag_store, thread_service
from test_ticket_console import _ContextRecoveryStates, _ContextRecoveryTickets, _ticket


@pytest.mark.parametrize("future", [False, True])
@pytest.mark.parametrize("naive", [False, True])
def test_resolution_lease_handles_naive_utc_and_preserves_active_owner(monkeypatch, future, naive):
    until = datetime.now(timezone.utc) + timedelta(hours=1 if future else -1)
    if naive:
        until = until.replace(tzinfo=None)
    ticket = {"_id": "fixture", "resolution_effects": {"lease_owner": "resolution-owner", "lease_until": until},
              "thread_name_reconcile": {"marker": "m", "complete": False}}
    before = copy.deepcopy(ticket)
    tickets = NS(find_one_and_update=AsyncMock(return_value=ticket), update_one=AsyncMock())
    owned = AsyncMock()
    monkeypatch.setattr(thread_service, "_reconcile_ticket_thread_names_owned", owned)
    asyncio.run(thread_service._reconcile_ticket_thread_names(NS(), NS(tickets=tickets), ticket, "m"))
    assert ticket == before
    if future:
        tickets.find_one_and_update.assert_not_awaited()
        tickets.update_one.assert_not_awaited()
        owned.assert_not_awaited()
    else:
        owned.assert_awaited_once()
        query = tickets.find_one_and_update.await_args.args[0]
        assert query["$and"][1]["$or"][1]["resolution_effects.lease_until"]["$lte"].tzinfo is timezone.utc
        assert "thread_name_reconcile.lease_until" in tickets.update_one.await_args.args[1]["$unset"]


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("leased", [False, True])
def test_identity_busy_keeps_pending_receipt_then_existing_recovery_delivers_once(monkeypatch, caplog, existing, leased):
    now = datetime(2026, 11, 21, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(console, "utcnow", lambda: now)
    ticket = _ticket(2, venue="thread")
    state_id = f"ticket_staff_context:{ticket['_id']}"
    old = {"_id": state_id, "kind": "ticket_staff_context", "ticket_id": ticket["_id"],
           "staff_space_id": ticket["location"]["staff_space_id"], "delivery_state": "delivered",
           "message_id": 800, "fingerprint": "old", "refresh_generation": 4,
           "created_at": now - timedelta(days=1), "updated_at": now - timedelta(hours=1)} if existing else None
    if leased:
        old = old or {"_id": state_id, "kind": "ticket_staff_context", "ticket_id": ticket["_id"],
                      "staff_space_id": ticket["location"]["staff_space_id"], "delivery_state": "pending",
                      "created_at": now, "updated_at": now}
        old.update(lease_owner="another-owner", lease_until=now + timedelta(minutes=1))
    states = _ContextRecoveryStates([old] if old else [])
    mongo = NS(ticket_automation_state=states, tickets=_ContextRecoveryTickets([ticket]))
    rest = NS(create_message=AsyncMock(return_value=NS(id=900)), edit_message=AsyncMock())
    bot = NS(rest=rest, get_me=lambda: NS(id=7, username="Fixture bot"))
    flag = AsyncMock(side_effect=flag_store.IdentityLockBusy("fixture contention"))
    monkeypatch.setattr(flag_store, "ensure_prior_denial_flag", flag)
    monkeypatch.setattr(console, "build_staff_identity_context", AsyncMock(return_value=console._notice("Applicant context", "Matched history")))
    monkeypatch.setattr(console, "build_staff_chocolate_checklist", lambda _: None)
    monkeypatch.setattr(console, "_find_staff_context_message", AsyncMock(return_value=None))
    with caplog.at_level(logging.INFO, logger=console.__name__):
        result = asyncio.run(console.deliver_staff_identity_context(bot, mongo, ticket, open_only_refresh=True))
    assert result is None
    pending = states.documents[state_id]
    assert pending["delivery_state"] == "pending" and pending["open_only_refresh"] is True
    assert pending.get("message_id") == (800 if existing else None)
    if leased:
        assert (pending["lease_owner"], pending["lease_until"]) == (old["lease_owner"], old["lease_until"])
    assert len([r for r in caplog.records if r.levelno == logging.INFO]) == 1
    assert all(r.exc_info is None for r in caplog.records)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
    rest.create_message.assert_not_awaited()
    rest.edit_message.assert_not_awaited()
    if leased:
        result = asyncio.run(console.recover_pending_staff_identity_contexts(bot=bot, mongo=mongo))
        assert result == {"processed": 0, "completed": 0, "failed": 0}
        assert states.documents[state_id]["lease_owner"] == "another-owner"
        states.documents[state_id]["lease_until"] = now - timedelta(seconds=1)
    flag.side_effect = None
    flag.return_value = (None, False)
    recovered = asyncio.run(console.recover_pending_staff_identity_contexts(bot=bot, mongo=mongo))
    assert recovered == {"processed": 1, "completed": 1, "failed": 0}
    final = states.documents[state_id]
    assert final["delivery_state"] == "delivered"
    assert final["message_id"] == (800 if existing else 900)
    assert rest.create_message.await_count == (0 if existing else 1)
    assert rest.edit_message.await_count == (1 if existing else 0)
    again = asyncio.run(console.recover_pending_staff_identity_contexts(bot=bot, mongo=mongo))
    assert again == {"processed": 0, "completed": 0, "failed": 0}
    assert rest.create_message.await_count == (0 if existing else 1)
    assert rest.edit_message.await_count == (1 if existing else 0)

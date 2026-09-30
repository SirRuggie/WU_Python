import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from extensions.commands.tickets import (
    lifecycle,
    resolve,
    store,
    console,
    thread_service,
)
from extensions.commands import ticket_runtime
from tests.test_ticket_storage_foundation import _mongo, _ticket as base_ticket


def _ticket(status="open"):
    doc = base_ticket()
    doc["status"] = status
    return doc


def test_close_records_no_denial_fields_and_preserves_flags(monkeypatch):
    async def run():
        doc = _ticket()
        mongo = _mongo(doc)
        mongo.ticket_flags.documents["ghost"] = {
            "_id": "ghost",
            "kind": "ghosted",
            "active": True,
        }
        monkeypatch.setattr(
            lifecycle.perms, "is_recruiter", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(ticket_runtime, "mark_slot_release_pending", AsyncMock())
        monkeypatch.setattr(ticket_runtime, "release_open_slot", AsyncMock())
        monkeypatch.setattr(
            thread_service, "mark_creation_complete_for_terminal_ticket", AsyncMock()
        )
        scheduled = []
        monkeypatch.setattr(
            resolve,
            "_schedule_resolution_effects",
            lambda *args: scheduled.append(args),
        )
        result = await lifecycle.change(
            NS(),
            mongo,
            ticket_id=doc["_id"],
            member=NS(id=9, guild_id=10),
            actor_name="Recruiter",
            kind="close",
            reason="Recruit withdrew",
        )
        assert result.won
        saved = result.doc
        assert (
            saved["status"] == "closed"
            and saved["closure_reason"] == "Recruit withdrew"
        )
        assert saved["closed_by"] == 9 and "denied_at" not in saved
        assert saved["resolution_effects"]["kind"] == "close"
        assert mongo.ticket_flags.documents["ghost"]["active"]
        assert len(scheduled) == 1
        ticket_runtime.release_open_slot.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "authorized,status", [(False, "open"), (True, "approved"), (True, "denied")]
)
def test_close_rejects_unauthorized_and_decided_tickets(
    monkeypatch, authorized, status
):
    async def run():
        doc = _ticket(status=status)
        monkeypatch.setattr(
            lifecycle.perms, "is_recruiter", AsyncMock(return_value=authorized)
        )
        result = await lifecycle.change(
            NS(),
            _mongo(doc),
            ticket_id=doc["_id"],
            member=NS(id=9, guild_id=10),
            actor_name="Recruiter",
            kind="close",
            reason="Recruit withdrew",
        )
        assert not result.won

    asyncio.run(run())


def test_stale_activity_prevents_inactivity_close(monkeypatch):
    async def run():
        doc = _ticket()
        doc.update(activity_revision=4, inactivity={"prompt": {"token": "new"}})
        monkeypatch.setattr(
            lifecycle.perms, "is_recruiter", AsyncMock(return_value=True)
        )
        result = await lifecycle.change(
            NS(),
            _mongo(doc),
            ticket_id=doc["_id"],
            member=NS(id=9, guild_id=10),
            actor_name="Recruiter",
            kind="close",
            reason="No response",
            expected_activity_revision=3,
            expected_inactivity_token="old",
        )
        assert not result.won

    asyncio.run(run())


def test_reopen_reserves_slot_resets_timer_and_never_releases_it(monkeypatch):
    async def run():
        doc = _ticket(status="closed")
        doc["inactivity"] = {"prompt": {"token": "old"}}
        mongo = _mongo(doc)
        monkeypatch.setattr(
            lifecycle.perms, "is_recruiter", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            ticket_runtime, "get_rollout", AsyncMock(return_value=NS(revision=2))
        )
        monkeypatch.setattr(
            ticket_runtime,
            "claim_open_slot",
            AsyncMock(
                return_value=ticket_runtime.SlotClaim(True, "owner", {"_id": "slot"})
            ),
        )
        release = AsyncMock()
        monkeypatch.setattr(ticket_runtime, "release_open_slot", release)
        monkeypatch.setattr(resolve, "_schedule_resolution_effects", lambda *args: None)
        result = await lifecycle.change(
            NS(),
            mongo,
            ticket_id=doc["_id"],
            member=NS(id=9, guild_id=10),
            actor_name="Recruiter",
            kind="reopen",
            reason="Recruit returned",
        )
        assert result.won and result.doc["status"] == "open"
        assert (
            result.doc["inactivity"]["reset_at"]
            and "prompt" not in result.doc["inactivity"]
        )
        assert result.doc["reopen_slot"] == {"id": "slot", "owner": "owner"}
        assert result.doc["creation_workflow_id"].startswith("reopen:")
        release.assert_not_awaited()

    asyncio.run(run())


def test_reopen_blocks_another_open_ticket(monkeypatch):
    async def run():
        doc = _ticket(status="closed")
        monkeypatch.setattr(
            lifecycle.perms, "is_recruiter", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            ticket_runtime, "get_rollout", AsyncMock(return_value=NS(revision=2))
        )
        monkeypatch.setattr(
            ticket_runtime,
            "claim_open_slot",
            AsyncMock(
                return_value=ticket_runtime.SlotClaim(False, None, {"_id": "slot"})
            ),
        )
        result = await lifecycle.change(
            NS(),
            _mongo(doc),
            ticket_id=doc["_id"],
            member=NS(id=9, guild_id=10),
            actor_name="Recruiter",
            kind="reopen",
            reason="Recruit returned",
        )
        assert result.outcome == store.BLOCKED

    asyncio.run(run())


def test_close_archives_both_threads_and_reopen_restores_them(monkeypatch):
    async def run():
        doc = _ticket()
        bot = NS(
            rest=NS(
                fetch_channel=AsyncMock(
                    return_value=NS(is_archived=False, is_locked=False)
                ),
                edit_channel=AsyncMock(),
            )
        )
        await lifecycle.finish_effects(bot, NS(), doc, "close")
        assert [c.args[0] for c in bot.rest.edit_channel.await_args_list] == [101, 102]
        assert all(
            c.kwargs["archived"] and c.kwargs["locked"]
            for c in bot.rest.edit_channel.await_args_list
        )
        doc["reopen_slot"] = {"id": "slot", "owner": "owner"}
        mongo = NS(
            ticket_open_slots=NS(find_one=AsyncMock(return_value={"state": "reserved"}))
        )
        bind = AsyncMock()
        monkeypatch.setattr(ticket_runtime, "bind_open_slot", bind)
        bot.rest.fetch_channel.return_value = NS(is_archived=True, is_locked=True)
        bot.rest.edit_channel.reset_mock()
        await lifecycle.finish_effects(bot, mongo, doc, "reopen")
        bind.assert_awaited_once()
        assert all(
            not c.kwargs["archived"] and not c.kwargs["locked"]
            for c in bot.rest.edit_channel.await_args_list
        )

    asyncio.run(run())


def test_closed_details_offer_reopen_and_open_details_offer_close():
    for status, wanted in [
        ("open", "Close without a decision"),
        ("closed", "Reopen ticket"),
    ]:
        view = repr(
            console.build_ticket_detail(
                _ticket(status=status), action_id="test", flags=[], history=[]
            )
        )
        assert wanted in view
    assert thread_service.thread_names("main", 1, "recruit", status="closed")[
        0
    ].startswith("📁")
    assert thread_service.thread_names(
        "main", 1, "recruit", status="closed", ghosted=True
    )[1].startswith("👻")


def test_archive_failure_keeps_durable_effects_pending_for_restart(monkeypatch):
    async def run():
        doc = _ticket(status="closed")
        doc["resolution_effects"] = {
            "kind": "close",
            "marker": "close:1",
            "complete": False,
            **{
                s: {"state": "delivered"}
                for s in (
                    "notification",
                    "staff_notification",
                    "staff_context",
                    "thread_names_candidate",
                    "thread_names_staff",
                )
            },
            "hub": {"state": "requested"},
        }
        monkeypatch.setattr(store, "find_one", AsyncMock(return_value=doc))
        finish = AsyncMock(side_effect=[RuntimeError("Discord unavailable"), None])
        monkeypatch.setattr(lifecycle, "finish_effects", finish)
        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(resolve, "_finalize_effects", finalize)
        first = await resolve._process_resolution_effects_owned(NS(), NS(), doc)
        assert first.outcome == store.EFFECT_FAILED
        finalize.assert_not_awaited()
        assert (await resolve._process_resolution_effects_owned(NS(), NS(), doc)).won
        finalize.assert_awaited_once()

    asyncio.run(run())


def test_restart_sweep_includes_closed_and_reopened_obligations(monkeypatch):
    async def run():
        find = AsyncMock(return_value=[])
        monkeypatch.setattr(store, "find", find)
        await resolve.reconcile_pending_resolution_effects(NS(), NS())
        query = find.call_args.args[1]
        assert {"closed", "open"} <= set(query["status"]["$in"])
        assert query["resolution_effects.marker"] == {"$exists": True}

    asyncio.run(run())


def test_reopen_preserves_pending_ghosted_flag_recovery(monkeypatch):
    async def run():
        doc = _ticket(status="closed")
        doc["inactivity"] = {"prompt": {"state": "yes", "token": "pending"}}
        monkeypatch.setattr(
            lifecycle.perms, "is_recruiter", AsyncMock(return_value=True)
        )
        result = await lifecycle.change(
            NS(),
            _mongo(doc),
            ticket_id=doc["_id"],
            member=NS(id=9, guild_id=10),
            actor_name="Recruiter",
            kind="reopen",
            reason="Recruit returned",
        )
        assert result.outcome == store.BLOCKED

    asyncio.run(run())

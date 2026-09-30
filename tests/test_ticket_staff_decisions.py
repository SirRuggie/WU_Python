import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from extensions.commands.tickets import resolve, store


def ticket():
    return {
        "_id": "ticket_1",
        "venue": "thread",
        "user_id": 22,
        "ticket_number": 1,
        "ticket_type": "fwa",
        "location": {"id": 44, "staff_space_id": 55},
        "handled_by": 33,
        "handled_at": datetime(2026, 9, 29, tzinfo=timezone.utc),
        "denial_reason": "Recruit stopped responding",
        "status": "denied",
        "resolution_effects": {"marker": "decision1", "kind": resolve.KIND_DENY_CUSTOM},
    }


@pytest.mark.parametrize(
    "kind",
    [
        resolve.KIND_APPROVE,
        resolve.KIND_DENY_CUSTOM,
        resolve.KIND_DENY_MAIN,
        resolve.KIND_DENY_FWA,
    ],
)
def test_staff_decision_copy_includes_actor_date_and_correct_reason(kind):
    view = repr(resolve._staff_decision_components(ticket(), kind))
    assert "<@22>" in view and "<@33>" in view and ":F>" in view
    if kind == resolve.KIND_APPROVE:
        assert "Approved" in view and "Recruit stopped responding" not in view
    elif kind == resolve.KIND_DENY_CUSTOM:
        assert "Recruit stopped responding" in view
    else:
        assert resolve._DENIAL_BODY[kind].split("\n")[0] in view


def test_staff_retry_finds_same_decision_and_overturn_posts_new_record(monkeypatch):
    async def run():
        messages = []
        rest = NS(
            create_message=AsyncMock(),
            fetch_channel=AsyncMock(return_value=NS(is_archived=True, is_locked=True)),
            edit_channel=AsyncMock(return_value=NS(is_locked=True)),
        )
        bot = NS(rest=rest, get_me=lambda: NS(id=99))

        async def history(*args):
            return messages

        async def create(**kwargs):
            assert kwargs["channel"] == 55
            assert kwargs["user_mentions"] is False
            assert kwargs["role_mentions"] is False
            assert kwargs["mentions_everyone"] is False
            message = NS(
                id=100 + len(messages), nonce=kwargs["nonce"], author=NS(id=99)
            )
            messages.append(message)
            return message

        rest.create_message.side_effect = create
        monkeypatch.setattr(resolve, "_all_messages", history)
        original = await resolve._deliver_staff_decision(
            bot, ticket(), resolve.KIND_DENY_CUSTOM, "decision1"
        )
        assert (
            await resolve._deliver_staff_decision(
                bot, ticket(), resolve.KIND_DENY_CUSTOM, "decision1"
            )
        ).id == original.id
        updated = ticket()
        updated["resolution_effects"]["overturn"] = True
        await resolve._deliver_staff_decision(
            bot, updated, resolve.KIND_APPROVE, "decision2"
        )
        assert len(messages) == 2 and rest.create_message.await_count == 2
        assert "earlier staff record is retained" in repr(
            resolve._staff_decision_components(updated, resolve.KIND_APPROVE)
        )
        assert rest.edit_channel.await_args_list[0].kwargs["archived"] is False

    asyncio.run(run())


def test_failed_staff_send_retries_without_repeating_applicant_notification(
    monkeypatch,
):
    async def run():
        doc = ticket()
        effects = doc["resolution_effects"]
        for step in (
            "notification",
            "staff_context",
            "thread_names_candidate",
            "thread_names_staff",
        ):
            effects[step] = {"state": "delivered"}
        effects["hub"] = {"state": "requested"}
        effects["staff_notification"] = {"state": "pending"}
        effects["complete"] = False

        async def checkpoint(mongo, ticket_id, marker, *, step, state, **kwargs):
            effects[step] = {"state": state, "message_id": kwargs.get("message_id")}
            return True

        monkeypatch.setattr(resolve, "_checkpoint_effect", checkpoint)
        monkeypatch.setattr(
            resolve.store, "find_one", AsyncMock(side_effect=lambda *a, **k: doc)
        )
        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(resolve, "_finalize_effects", finalize)
        send = AsyncMock(side_effect=[RuntimeError("Discord unavailable"), NS(id=999)])
        monkeypatch.setattr(resolve, "_deliver_staff_decision", send)
        applicant = AsyncMock()
        monkeypatch.setattr(resolve, "run_side_effects", applicant)
        first = await resolve._process_resolution_effects_owned(NS(), NS(), doc)
        assert first.outcome == store.EFFECT_FAILED
        finalize.assert_not_awaited()
        second = await resolve._process_resolution_effects_owned(NS(), NS(), doc)
        assert second.outcome == store.WON
        assert effects["staff_notification"] == {
            "state": "delivered",
            "message_id": 999,
        }
        await resolve._process_resolution_effects_owned(NS(), NS(), doc)
        assert send.await_count == 2
        applicant.assert_not_awaited()

    asyncio.run(run())

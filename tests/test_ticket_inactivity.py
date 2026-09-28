from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio
import functools

def run_async(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run

from extensions.commands.tickets import inactivity, store


def ticket(**kwargs):
    return {"_id": "ticket_123", **store.RUNTIME_FILTER, "status": "open", "guild_id": 1,
            "created_at": datetime.now(timezone.utc) - timedelta(days=8), "rev": 2,
            "user_id": 42, "location": {"id": 123, "staff_space_id": 456}, **kwargs}


class History:
    def __init__(self, messages): self.messages = messages
    def limit(self, limit): return History(self.messages[:limit])
    def __aiter__(self):
        async def items():
            for message in self.messages: yield message
        return items()


def message(bot=False, at=None):
    return SimpleNamespace(author=SimpleNamespace(is_bot=bot), webhook_id=None,
                           timestamp=at or datetime.now(timezone.utc))


@run_async
async def test_any_human_activity_invalidates_prompt_without_decision_rev():
    mongo = SimpleNamespace(tickets=SimpleNamespace(update_one=AsyncMock()))
    await inactivity.record_human_activity(mongo, ticket(), message())
    query, update = mongo.tickets.update_one.call_args.args
    assert query["status"] == "open"
    assert update["$unset"] == {"inactivity.prompt": ""}
    assert update["$inc"] == {"activity_revision": 1}
    assert "rev" not in update["$inc"]


@run_async
async def test_resolved_and_test_tickets_do_not_reset():
    mongo = SimpleNamespace(tickets=SimpleNamespace(update_one=AsyncMock()))
    await inactivity.record_human_activity(mongo, ticket(status="approved"), message())
    await inactivity.record_human_activity(mongo, ticket(venue="channel"), message())
    mongo.tickets.update_one.assert_not_awaited()


@run_async
async def test_baseline_ignores_bot_messages_and_uses_latest_human():
    at = datetime.now(timezone.utc) - timedelta(days=9)
    bot = SimpleNamespace(rest=SimpleNamespace(fetch_messages=lambda _: History([message(True), message(at=at)])))
    mongo = SimpleNamespace(tickets=SimpleNamespace(update_one=AsyncMock(), find_one=AsyncMock(return_value=ticket())))
    await inactivity.verify_baseline(bot, mongo, ticket())
    query, update = mongo.tickets.update_one.call_args.args
    assert update["$max"]["inactivity.last_human_at"] == at
    assert update["$inc"]["activity_revision"] == 1


@run_async
async def test_unproven_bounded_baseline_never_prompts():
    bot = SimpleNamespace(rest=SimpleNamespace(fetch_messages=lambda _: History([message(True)] * 500)))
    mongo = SimpleNamespace(tickets=SimpleNamespace(find_one_and_update=AsyncMock()))
    assert await inactivity.verify_baseline(bot, mongo, ticket()) is None
    mongo.tickets.find_one_and_update.assert_not_awaited()


def test_prompt_card_has_exact_copy_and_requested_emojis():
    card = inactivity.card(ticket(), "abc", 987)[0]
    assert card.accent_color == inactivity.GOLDENROD_ACCENT
    assert inactivity.PROMPT in card.components[0].content
    buttons = card.components[1].components
    assert [button.label for button in buttons] == ["Yes - Deny", "No - Wait"]
    assert [int(button.emoji.id) for button in buttons] == [inactivity.YES_EMOJI, inactivity.NO_EMOJI]
    assert buttons[0].custom_id == "ticket_inactivity:ticket_123:abc:yes"


@run_async
async def test_recent_activity_or_no_reset_prevents_prompt():
    mongo = SimpleNamespace(tickets=SimpleNamespace(find_one_and_update=AsyncMock()))
    t = ticket(inactivity={"last_human_at": datetime.now(timezone.utc) - timedelta(days=9), "reset_at": datetime.now(timezone.utc)})
    await inactivity.publish_prompt(None, mongo, t, {"main_thread_recruiter_role": 77})
    mongo.tickets.find_one_and_update.assert_not_awaited()


def click_fixture():
    t = ticket(inactivity={"prompt": {"token": "abc", "state": "ready", "message_id": 999, "activity_revision": 3}})
    t["activity_revision"] = 3
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={})),
        tickets=SimpleNamespace(find_one=AsyncMock(return_value=t),
        find_one_and_update=AsyncMock(return_value=t), update_one=AsyncMock(return_value=SimpleNamespace(modified_count=1))))
    ctx = SimpleNamespace(defer=AsyncMock(), member=SimpleNamespace(id=7), user=SimpleNamespace(id=7, username="Recruiter"),
        channel_id=456, guild_id=1, respond_with_modal=AsyncMock(), interaction=SimpleNamespace(message=SimpleNamespace(id=999), edit_initial_response=AsyncMock()))
    return t, mongo, ctx


def set_modal_reason(monkeypatch, reason="Recruit stopped responding"):
    from extensions.commands.tickets import console
    monkeypatch.setattr(console, "_modal_value", lambda ctx, field: reason if field == "reason" else "")


@run_async
async def test_yes_click_opens_reason_modal_without_deciding_or_database_work():
    _, mongo, ctx = click_fixture()
    await inactivity.handle_inactivity(ctx, "ticket_123:abc:yes", bot=object(), mongo=mongo)
    ctx.respond_with_modal.assert_awaited_once()
    args = ctx.respond_with_modal.call_args.kwargs
    assert args["custom_id"] == "ticket_inactivity_reason:ticket_123:abc:yes"
    assert not ctx.defer.await_count
    mongo.tickets.find_one.assert_not_awaited()
    mongo.tickets.find_one_and_update.assert_not_awaited()
    mongo.tickets.update_one.assert_not_awaited()


@run_async
async def test_yes_uses_normal_deny_exact_reason_and_activity_cas(monkeypatch):
    t, mongo, ctx = click_fixture()
    set_modal_reason(monkeypatch, "No response after three follow-ups")
    monkeypatch.setattr(inactivity.perms, "is_recruiter", AsyncMock(return_value=True))
    monkeypatch.setattr(inactivity, "verify_baseline", AsyncMock(return_value=t))
    monkeypatch.setattr(inactivity, "retire_prompt", AsyncMock())
    deny = AsyncMock(return_value=store.Transition(store.WON, t))
    finish = AsyncMock(return_value=True)
    monkeypatch.setattr(inactivity.resolve, "deny_ticket", deny)
    monkeypatch.setattr(inactivity, "finish_ghosted", finish)
    await inactivity.handle_inactivity_reason(ctx, "ticket_123:abc:yes", bot=object(), mongo=mongo)
    assert deny.await_count == 1
    assert deny.call_args.kwargs["reason"] == "No response after three follow-ups"
    assert deny.call_args.kwargs["kind"] == inactivity.resolve.KIND_DENY_CUSTOM
    assert deny.call_args.kwargs["expected_activity_revision"] == 3
    assert deny.call_args.kwargs["expected_inactivity_token"] == "abc"
    finish.assert_awaited_once()
    claim = mongo.tickets.find_one_and_update.call_args.args[1]["$set"]
    assert claim["inactivity.prompt.state"] == "yes"
    assert claim["inactivity.prompt.actor_id"] == 7
    assert claim["inactivity.prompt.reason"] == "No response after three follow-ups"


@run_async
async def test_invalid_submitted_reason_makes_no_database_decision(monkeypatch):
    t, mongo, ctx = click_fixture()
    set_modal_reason(monkeypatch, " ")
    monkeypatch.setattr(inactivity.perms, "is_recruiter", AsyncMock(return_value=True))
    await inactivity.handle_inactivity_reason(ctx, "ticket_123:abc:yes", bot=object(), mongo=mongo)
    assert "Enter a denial reason" in ctx.interaction.edit_initial_response.call_args.kwargs["content"]
    mongo.tickets.find_one.assert_not_awaited()
    mongo.tickets.find_one_and_update.assert_not_awaited()


@run_async
async def test_no_only_resets_timer_leaving_status_and_flags(monkeypatch):
    t, mongo, ctx = click_fixture()
    monkeypatch.setattr(inactivity.perms, "is_recruiter", AsyncMock(return_value=True))
    monkeypatch.setattr(inactivity, "verify_baseline", AsyncMock(return_value=t))
    monkeypatch.setattr(inactivity, "retire_prompt", AsyncMock())
    deny = AsyncMock()
    monkeypatch.setattr(inactivity.resolve, "deny_ticket", deny)
    await inactivity.handle_inactivity(ctx, "ticket_123:abc:no", bot=object(), mongo=mongo)
    update = mongo.tickets.update_one.call_args.args[1]
    assert set(update["$set"]) == {"inactivity.reset_at"}
    assert update["$unset"] == {"inactivity.prompt": ""}
    deny.assert_not_awaited()


@run_async
async def test_unauthorized_stale_duplicate_wrong_source_and_crossguild_refuse(monkeypatch):
    deny = AsyncMock()
    set_modal_reason(monkeypatch)
    monkeypatch.setattr(inactivity.resolve, "deny_ticket", deny)
    retire = AsyncMock()
    monkeypatch.setattr(inactivity, "retire_prompt", retire)
    allowed = AsyncMock(return_value=False)
    monkeypatch.setattr(inactivity.perms, "is_recruiter", allowed)
    t, mongo, ctx = click_fixture()
    await inactivity.handle_inactivity_reason(ctx, "ticket_123:abc:yes", bot=object(), mongo=mongo)
    mongo.tickets.find_one.assert_not_awaited()
    allowed.return_value = True
    for mutation in ("token", "state", "message", "channel", "guild", "claim", "status"):
        t, mongo, ctx = click_fixture()
        if mutation == "status": t["status"] = "denied"
        if mutation == "token": t["inactivity"]["prompt"]["token"] = "newer"
        if mutation == "state": t["inactivity"]["prompt"]["state"] = "yes"
        if mutation == "message": ctx.interaction.message.id = 111
        if mutation == "channel": ctx.channel_id = 111
        if mutation == "guild": ctx.guild_id = 111
        if mutation == "claim": mongo.tickets.find_one_and_update.return_value = None
        monkeypatch.setattr(inactivity, "verify_baseline", AsyncMock(return_value=t))
        await inactivity.handle_inactivity_reason(ctx, "ticket_123:abc:yes", bot=object(), mongo=mongo)
    deny.assert_not_awaited()


@run_async
async def test_offline_human_activity_invalidates_click(monkeypatch):
    t, mongo, ctx = click_fixture()
    set_modal_reason(monkeypatch)
    old = datetime.now(timezone.utc) - timedelta(days=8)
    t["inactivity"]["last_human_at"] = old
    refreshed = ticket(inactivity={"last_human_at": datetime.now(timezone.utc)})
    mongo.tickets.find_one.side_effect = [t, refreshed]
    bot = SimpleNamespace(rest=SimpleNamespace(fetch_messages=lambda _: History([message()])))
    monkeypatch.setattr(inactivity.perms, "is_recruiter", AsyncMock(return_value=True))
    monkeypatch.setattr(inactivity, "retire_prompt", AsyncMock())
    deny = AsyncMock()
    monkeypatch.setattr(inactivity.resolve, "deny_ticket", deny)
    await inactivity.handle_inactivity_reason(ctx, "ticket_123:abc:yes", bot=bot, mongo=mongo)
    deny.assert_not_awaited()
    update = mongo.tickets.update_one.call_args.args[1]
    assert update["$unset"] == {"inactivity.prompt": ""}
    assert update["$inc"] == {"activity_revision": 1}


@run_async
async def test_restart_send_recovers_exact_bot_token_without_duplicate_ping():
    t = ticket(ticket_type="main", inactivity={"last_human_at": datetime.now(timezone.utc) - timedelta(days=8),
        "prompt": {"token": "abc", "state": "sending", "lease_until": datetime.now(timezone.utc) - timedelta(minutes=1),
                   "started_at": datetime.now(timezone.utc) - timedelta(minutes=10)}})
    card = inactivity.card(t, "abc", 77)
    saved = SimpleNamespace(id=1001, author=SimpleNamespace(id=99), components=card, timestamp=datetime.now(timezone.utc))
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=SimpleNamespace(
        fetch_messages=lambda _: History([saved]), create_message=AsyncMock()))
    mongo = SimpleNamespace(tickets=SimpleNamespace(find_one_and_update=AsyncMock(return_value=t),
        find_one=AsyncMock(return_value=t), update_one=AsyncMock()))
    await inactivity.publish_prompt(bot, mongo, t, {"main_thread_recruiter_role": 77})
    bot.rest.create_message.assert_not_awaited()
    update = mongo.tickets.update_one.call_args.args[1]
    assert update["$set"]["inactivity.prompt.message_id"] == 1001
    assert update["$set"]["inactivity.prompt.state"] == "ready"


@run_async
async def test_won_denial_flag_recovery_survives_overturn_and_preserves_existing(monkeypatch):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def guard(*args, **kwargs): yield
    monkeypatch.setattr(inactivity.flag_store, "identity_guard", guard)
    flag = AsyncMock()
    monkeypatch.setattr(inactivity.flag_store, "_set_flag_unlocked", flag)
    from extensions.commands.tickets import thread_service, console
    monkeypatch.setattr(thread_service, "notify_console_after_change", AsyncMock())
    monkeypatch.setattr(console, "_refresh_after_flag_mutation", AsyncMock())
    monkeypatch.setattr(inactivity, "retire_prompt", AsyncMock())
    t = ticket(status="approved", inactivity={"prompt": {"state": "yes", "token": "abc", "actor_id": 999}},
        audit=[{"inactivity_token": "abc", "to": "denied", "actor": 7, "actor_name": "Original recruiter"}])
    flags = SimpleNamespace(find=lambda _: History([]))
    # Mongo cursors also expose to_list.
    class Cursor:
        def __init__(self, docs): self.docs = docs
        def limit(self, n): return self
        async def to_list(self, **kwargs): return self.docs
    flags.find = lambda _: Cursor([])
    mongo = SimpleNamespace(ticket_flags=flags, tickets=SimpleNamespace(update_one=AsyncMock()))
    await inactivity.finish_ghosted(object(), mongo, t)
    assert flag.call_args.kwargs["added_by"] == 7
    assert flag.call_args.kwargs["reason"] == "Recruit stopped responding"
    flag.reset_mock()
    t["audit"] = [{"inactivity_token": "abc", "to": "denied", "actor": 7, "actor_name": "Original recruiter", "reason": "Audit reason wins"}]
    t["inactivity"]["prompt"]["reason"] = "Saved prompt reason"
    await inactivity.finish_ghosted(object(), mongo, t)
    assert flag.call_args.kwargs["reason"] == "Audit reason wins"
    flag.reset_mock()
    t["audit"][0].pop("reason")
    await inactivity.finish_ghosted(object(), mongo, t)
    assert flag.call_args.kwargs["reason"] == "Saved prompt reason"
    flag.reset_mock()
    flags.find = lambda _: Cursor([{"kind": "ghosted", "reason": "Human-authored history"}])
    await inactivity.finish_ghosted(object(), mongo, t)
    flag.assert_not_awaited()
    t["audit"] = [{"to": "approved", "actor": 7}]
    mongo.tickets.update_one.reset_mock()
    await inactivity.finish_ghosted(object(), mongo, t)
    flag.assert_not_awaited()
    mongo.tickets.update_one.assert_not_awaited()


@run_async
async def test_won_denial_flag_failure_reports_pending_and_keeps_durable_yes(monkeypatch):
    t, mongo, ctx = click_fixture()
    set_modal_reason(monkeypatch)
    monkeypatch.setattr(inactivity.perms, "is_recruiter", AsyncMock(return_value=True))
    monkeypatch.setattr(inactivity, "verify_baseline", AsyncMock(return_value=t))
    monkeypatch.setattr(inactivity, "retire_prompt", AsyncMock())
    monkeypatch.setattr(inactivity.resolve, "deny_ticket", AsyncMock(return_value=store.Transition(store.WON, t)))
    monkeypatch.setattr(inactivity, "finish_ghosted", AsyncMock(side_effect=RuntimeError("Mongo unavailable")))
    await inactivity.handle_inactivity_reason(ctx, "ticket_123:abc:yes", bot=object(), mongo=mongo)
    wording = ctx.interaction.edit_initial_response.call_args.kwargs["content"]
    assert wording == "Ticket denied; Ghosted flag update is pending and will retry automatically."
    claim_update = mongo.tickets.find_one_and_update.call_args.args[1]
    assert claim_update["$set"]["inactivity.prompt.state"] == "yes"
    mongo.tickets.update_one.assert_not_awaited()


@run_async
async def test_first_prompt_mentions_only_recruiters_with_recoverable_nonce():
    t = ticket(ticket_type="main")
    collection = SimpleNamespace(
        find_one_and_update=AsyncMock(return_value=t),
        find_one=AsyncMock(return_value=t), update_one=AsyncMock(),
    )
    mongo = SimpleNamespace(tickets=collection)
    send = AsyncMock(return_value=SimpleNamespace(id=9876))
    bot = SimpleNamespace(rest=SimpleNamespace(create_message=send))
    await inactivity.publish_prompt(bot, mongo, t, {"main_thread_recruiter_role": 77})
    saved = collection.find_one_and_update.call_args.args[1]["$set"]["inactivity.prompt"]
    options = send.call_args.kwargs
    assert options["nonce"] == f"inact-{saved['token']}"
    assert len(options["nonce"]) <= 25
    assert options["role_mentions"] == [77]
    assert options["user_mentions"] is False
    assert options["mentions_everyone"] is False
    assert collection.update_one.call_args.args[1]["$set"]["inactivity.prompt.message_id"] == 9876


def test_five_minute_override_changes_prompt_text_and_default_stays_seven_days():
    assert inactivity.configured_period({}) == timedelta(days=7)
    period = inactivity.configured_period({"ticket_inactivity_minutes": 5})
    assert period == timedelta(minutes=5)
    text = inactivity.card(ticket(), "abc", 77, period)[0].components[0].content
    assert "last 5 minutes" in text
    assert "7 days" not in text


@run_async
async def test_five_minute_window_sends_when_seven_day_window_would_not():
    t = ticket(ticket_type="main", created_at=datetime.now(timezone.utc) - timedelta(minutes=6))
    collection = SimpleNamespace(find_one_and_update=AsyncMock(return_value=t),
        find_one=AsyncMock(return_value=t), update_one=AsyncMock())
    send = AsyncMock(return_value=SimpleNamespace(id=9876))
    bot = SimpleNamespace(rest=SimpleNamespace(create_message=send))
    mongo = SimpleNamespace(tickets=collection)
    await inactivity.publish_prompt(bot, mongo, t, {"main_thread_recruiter_role": 77})
    send.assert_not_awaited()
    await inactivity.publish_prompt(bot, mongo, t, {
        "main_thread_recruiter_role": 77, "ticket_inactivity_minutes": 5,
    })
    send.assert_awaited_once()


@run_async
async def test_restoring_seven_days_blocks_old_five_minute_yes(monkeypatch):
    t, mongo, ctx = click_fixture()
    set_modal_reason(monkeypatch)
    t["created_at"] = datetime.now(timezone.utc) - timedelta(minutes=6)
    monkeypatch.setattr(inactivity.perms, "is_recruiter", AsyncMock(return_value=True))
    monkeypatch.setattr(inactivity, "verify_baseline", AsyncMock(return_value=t))
    deny = AsyncMock()
    monkeypatch.setattr(inactivity.resolve, "deny_ticket", deny)
    await inactivity.handle_inactivity_reason(ctx, "ticket_123:abc:yes", bot=object(), mongo=mongo)
    deny.assert_not_awaited()
    assert "not due" in ctx.interaction.edit_initial_response.call_args.kwargs["content"]

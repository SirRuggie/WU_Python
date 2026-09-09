import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import uuid

import hikari
import pytest
from pymongo import AsyncMongoClient

from extensions.commands.tickets_legacy import resolution_delivery as delivery
from extensions.commands.tickets_legacy import store
from extensions.commands.tickets_legacy import close as legacy_close


_MISSING = object()


def _get(row, path):
    value = row
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _matches(row, query):
    for key, expected in query.items():
        if key == "$and":
            if not all(_matches(row, item) for item in expected):
                return False
            continue
        if key == "$or":
            if not any(_matches(row, item) for item in expected):
                return False
            continue
        actual = _get(row, key)
        if isinstance(expected, dict) and any(str(k).startswith("$") for k in expected):
            for operator, operand in expected.items():
                if operator == "$exists":
                    if (actual is not _MISSING) != bool(operand):
                        return False
                elif operator == "$in":
                    if actual is _MISSING or actual not in operand:
                        return False
                elif operator == "$lte":
                    if actual is _MISSING or not actual <= operand:
                        return False
                elif operator == "$gt":
                    if actual is _MISSING or not actual > operand:
                        return False
                else:
                    raise AssertionError(f"unsupported query operator: {operator}")
        elif actual is _MISSING or actual != expected:
            return False
    return True


def _set(row, path, value):
    target = row
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = deepcopy(value)


def _unset(row, path):
    target = row
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.get(part)
        if not isinstance(target, dict):
            return
    target.pop(parts[-1], None)


class _Result:
    def __init__(self, matched=0, modified=None):
        self.matched_count = matched
        self.modified_count = matched if modified is None else modified


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, fields):
        for field, direction in reversed(fields):
            self.rows.sort(key=lambda row: _get(row, field), reverse=direction < 0)
        return self

    def limit(self, value):
        self.rows = self.rows[:value]
        return self

    async def to_list(self, length=None):
        return deepcopy(self.rows if length is None else self.rows[:length])


class _Collection:
    def __init__(self, rows=(), events=None):
        self.rows = {row["_id"]: deepcopy(row) for row in rows}
        self.events = events

    def _apply(self, row, update):
        changed = False
        for path, value in update.get("$set", {}).items():
            changed |= _get(row, path) != value
            _set(row, path, value)
        for path in update.get("$unset", {}):
            changed |= _get(row, path) is not _MISSING
            _unset(row, path)
        for path, value in update.get("$push", {}).items():
            current = _get(row, path)
            if current is _MISSING:
                _set(row, path, [])
                current = _get(row, path)
            current.append(deepcopy(value))
            changed = True
        return changed

    async def find_one_and_update(self, query, update, **_kwargs):
        for row in self.rows.values():
            if _matches(row, query):
                self._apply(row, update)
                return deepcopy(row)
        return None

    async def find_one(self, query):
        for row in self.rows.values():
            if _matches(row, query):
                return deepcopy(row)
        return None

    async def update_one(self, query, update, **_kwargs):
        for row in self.rows.values():
            if _matches(row, query):
                changed = self._apply(row, update)
                if self.events is not None and "step_data.questionnaire.discord_skills_monitor_active" in update.get("$set", {}):
                    self.events.append("clear")
                return _Result(1, int(changed))
        return _Result()

    def find(self, query):
        return _Cursor([deepcopy(row) for row in self.rows.values() if _matches(row, query)])

    async def count_documents(self, query):
        return sum(_matches(row, query) for row in self.rows.values())


class _MessageIterator:
    def __init__(self, messages, error=None):
        self.messages = messages
        self.error = error

    async def collect(self, _factory):
        if self.error is not None:
            raise self.error
        return list(self.messages)


class _Rest:
    def __init__(self, *, events=None):
        self.events = events if events is not None else []
        self.messages = {}
        self.channel = SimpleNamespace(id=444, guild_id=111, name="🆕candidate")
        self.notice_calls = 0
        self.edit_calls = 0
        self.history_error = None
        self.accept_notice_then_raise = False
        self.accept_rename_then_raise = False
        self.next_message_id = 1_000

    def fetch_messages(self, channel_id):
        error, self.history_error = self.history_error, None
        return _MessageIterator(self.messages.get(int(channel_id), []), error)

    async def create_message(self, channel, content=None, components=None, **_kwargs):
        self.notice_calls += 1
        self.events.append("notice")
        message = SimpleNamespace(
            id=self.next_message_id,
            author=SimpleNamespace(id=999),
            content=content or "",
            components=tuple(components or ()),
        )
        self.next_message_id += 1
        self.messages.setdefault(int(channel), []).append(message)
        if self.accept_notice_then_raise:
            self.accept_notice_then_raise = False
            raise TimeoutError("response lost")
        return message

    async def fetch_channel(self, channel_id):
        assert int(channel_id) == self.channel.id
        return deepcopy(self.channel)

    async def edit_channel(self, channel_id, *, name, **_kwargs):
        assert int(channel_id) == self.channel.id
        self.edit_calls += 1
        self.events.append("rename")
        self.channel.name = name
        if self.accept_rename_then_raise:
            self.accept_rename_then_raise = False
            raise TimeoutError("response lost")
        return deepcopy(self.channel)


class _Bot:
    def __init__(self, rest):
        self.rest = rest

    def get_me(self):
        return SimpleNamespace(id=999)


def _plan(kind="approve"):
    if kind == "approve":
        return {
            "kind": "approve",
            "user_id": 7,
            "notice_content": "<@7> accepted",
            "rename_emoji": "✅",
            "actor_name": "Recruiter",
        }
    return {
        "kind": kind,
        "user_id": 7,
        "notice_text": "<@7> denied",
        "rename_emoji": "❌",
        "actor_name": "Recruiter",
        "accent_color": 0xCC0000,
        "denied_thumb": "https://example.test/denied.png",
        "footer_media": "assets/Red_Footer.png",
    }


def _ticket(*, status="approved", state="pending", kind="approve", effect_id="effect-a"):
    return {
        "_id": "ticket-1",
        "type": "ticket",
        "venue": "channel",
        "runtime": store.LEGACY_RUNTIME,
        "status": status,
        "guild_id": 111,
        "channel_id": 444,
        "thread_id": 445,
        "user_id": 7,
        "ticket_type": "main",
        "resolution_delivery": {
            "effect_id": effect_id,
            "decision_status": status,
            "state": state,
            "actor_name": "Recruiter",
            "plan": _plan(kind),
        },
    }


def _mongo(ticket, *, events=None, extras=()):
    return SimpleNamespace(
        button_store=_Collection([ticket, *extras]),
        ticket_automation_state=_Collection([{
            "_id": str(ticket["channel_id"]),
            "step_data": {
                "questionnaire": {"discord_skills_monitor_active": True},
            },
        }], events=events),
    )


def _expire_retry(mongo, ticket_id="ticket-1"):
    effect = mongo.button_store.rows[ticket_id]["resolution_delivery"]
    effect["retry_after"] = datetime.now(timezone.utc) - timedelta(seconds=1)


def test_transition_atomically_commits_status_and_resolution_marker():
    ticket = _ticket(status="open")
    ticket.pop("resolution_delivery")
    mongo = _mongo(ticket)

    result = asyncio.run(store.transition(
        mongo,
        "ticket-1",
        to_status="approved",
        actor_id=8,
        actor_name="Recruiter",
        resolution_effect=_plan("approve"),
    ))

    assert result.won
    durable = mongo.button_store.rows["ticket-1"]
    assert durable["status"] == "approved"
    assert durable["resolution_delivery"]["decision_status"] == "approved"
    assert durable["resolution_delivery"]["state"] == "pending"
    assert durable["resolution_delivery"]["plan"] == _plan("approve")


def test_missing_approval_authority_reports_no_change_and_runs_no_effects(
    monkeypatch,
):
    responses = []
    ticket = _ticket(status="open")
    ticket.pop("resolution_delivery")

    async def find_ticket(*_args, **_kwargs):
        return ticket

    async def missing_transition(*_args, **_kwargs):
        return store.Transition(store.MISSING, None)

    async def allowed(*_args, **_kwargs):
        return True

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("missing authority ran a Discord effect")

    async def respond(content, **_kwargs):
        responses.append(content)

    async def defer(**_kwargs):
        return None

    monkeypatch.setattr(legacy_close.store, "find_one", find_ticket)
    monkeypatch.setattr(legacy_close.store, "transition", missing_transition)
    monkeypatch.setattr(
        legacy_close.resolve,
        "deliver_committed_resolution",
        forbidden,
    )
    monkeypatch.setattr(legacy_close.resolve, "apply_approval", forbidden)
    mongo = SimpleNamespace(
        ticket_setup=SimpleNamespace(
            find_one=lambda *_args, **_kwargs: None,
        )
    )

    async def config(_query):
        return {}

    mongo.ticket_setup.find_one = config
    ctx = SimpleNamespace(
        guild_id=111,
        channel_id=444,
        member=SimpleNamespace(
            role_ids=(),
            permissions=hikari.Permissions.ADMINISTRATOR,
        ),
        user=SimpleNamespace(id=8, username="Recruiter"),
        defer=defer,
        respond=respond,
    )
    asyncio.run(legacy_close.Approve.invoke._func(
        SimpleNamespace(),
        ctx,
        mongo=mongo,
        bot=SimpleNamespace(),
    ))

    assert responses == [legacy_close.MISSING_TICKET_MESSAGE]


@pytest.mark.parametrize(
    "handler",
    [
        legacy_close.deny_fwa_default_handler,
        legacy_close.deny_main_default_handler,
        legacy_close.process_custom_denial_handler,
    ],
)
def test_missing_denial_authority_reports_no_change_and_runs_no_effects(
    monkeypatch,
    handler,
):
    edits = []
    responses = []
    deleted = []
    data = {
        "ticket_id": "ticket-1",
        "guild_id": 111,
        "channel_id": 444,
        "user_id": 7,
        "denier_id": 8,
        "denier_name": "Recruiter",
    }

    async def get_state(*_args, **_kwargs):
        return data

    async def allowed(*_args, **_kwargs):
        return True

    async def missing_transition(*_args, **_kwargs):
        return store.Transition(store.MISSING, None)

    async def delete_state(_mongo, action_id):
        deleted.append(action_id)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("missing authority ran a Discord effect")

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    async def respond(content, **kwargs):
        responses.append((content, kwargs))

    monkeypatch.setattr(legacy_close, "get_state", get_state)
    monkeypatch.setattr(legacy_close, "delete_state", delete_state)
    monkeypatch.setattr(legacy_close, "_allow_denial_action", allowed)
    monkeypatch.setattr(legacy_close.store, "transition", missing_transition)
    monkeypatch.setattr(
        legacy_close.resolve,
        "deliver_committed_resolution",
        forbidden,
    )
    monkeypatch.setattr(legacy_close.resolve, "apply_denial", forbidden)
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=8, username="Recruiter"),
        interaction=SimpleNamespace(
            components=[[SimpleNamespace(
                custom_id="denial_reason",
                value="Application requirements were not met.",
            )]],
            edit_initial_response=edit_initial_response,
        ),
        respond=respond,
    )
    asyncio.run(handler(
        ctx,
        "action-1",
        mongo=SimpleNamespace(),
        bot=SimpleNamespace(),
    ))

    assert deleted == ["action-1"]
    if handler is legacy_close.process_custom_denial_handler:
        assert responses == [(
            legacy_close.MISSING_TICKET_MESSAGE,
            {"ephemeral": True},
        )]
        assert edits == []
    else:
        assert responses == []
        assert edits == [{
            "content": legacy_close.MISSING_TICKET_MESSAGE,
            "components": [],
        }]


def test_pending_prior_effect_blocks_override_until_complete():
    ticket = _ticket()
    mongo = _mongo(ticket)

    blocked = asyncio.run(store.transition(
        mongo,
        "ticket-1",
        to_status="denied",
        actor_id=9,
        actor_name="Leader",
        expect=None,
        overrides={"status": "approved", "by": 8, "by_name": "Recruiter"},
        resolution_effect=_plan("deny_custom"),
    ))
    assert blocked.busy
    assert mongo.button_store.rows["ticket-1"]["status"] == "approved"

    mongo.button_store.rows["ticket-1"]["resolution_delivery"]["state"] = "complete"
    won = asyncio.run(store.transition(
        mongo,
        "ticket-1",
        to_status="denied",
        actor_id=9,
        actor_name="Leader",
        expect=None,
        overrides={"status": "approved", "by": 8, "by_name": "Recruiter"},
        resolution_effect=_plan("deny_custom"),
    ))
    assert won.won
    assert won.doc["resolution_delivery"]["effect_id"] != "effect-a"


@pytest.mark.parametrize(
    ("kind", "status", "expected"),
    [
        ("approve", "approved", ["clear", "rename", "notice"]),
        ("deny_custom", "denied", ["notice", "clear", "rename"]),
    ],
)
def test_resolution_steps_run_in_decision_specific_order(monkeypatch, kind, status, expected):
    events = []
    ticket = _ticket(status=status, kind=kind)
    mongo = _mongo(ticket, events=events)
    rest = _Rest(events=events)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(delivery.asyncio, "sleep", no_sleep)
    result = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))

    assert result["completed"] == 1
    assert events == expected
    assert mongo.button_store.rows["ticket-1"]["resolution_delivery"]["state"] == "complete"


def test_accepted_notice_response_loss_is_reconciled_without_resend():
    ticket = _ticket(status="denied", kind="deny_custom")
    mongo = _mongo(ticket)
    rest = _Rest()
    rest.accept_notice_then_raise = True

    first = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert first["failed"] == 1
    assert rest.notice_calls == 1

    _expire_retry(mongo)
    second = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert second["completed"] == 1
    assert rest.notice_calls == 1
    assert mongo.button_store.rows["ticket-1"]["resolution_delivery"]["notice_sent"] is True


def test_accepted_rename_response_loss_is_reconciled_without_second_rename(monkeypatch):
    ticket = _ticket()
    mongo = _mongo(ticket)
    rest = _Rest()
    rest.accept_rename_then_raise = True

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(delivery.asyncio, "sleep", no_sleep)
    first = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert first["failed"] == 1
    assert rest.edit_calls == 1
    assert rest.channel.name.startswith("✅")

    _expire_retry(mongo)
    second = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert second["completed"] == 1
    assert rest.edit_calls == 1
    assert rest.notice_calls == 1


def test_transient_history_failure_never_sends_before_exact_scan():
    ticket = _ticket(status="denied", kind="deny_custom")
    mongo = _mongo(ticket)
    rest = _Rest()
    rest.history_error = TimeoutError("history unavailable")

    first = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert first["failed"] == 1
    assert rest.notice_calls == 0

    _expire_retry(mongo)
    second = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert second["completed"] == 1
    assert rest.notice_calls == 1


def test_checkpoint_loss_then_lease_takeover_reconciles_notice(monkeypatch):
    ticket = _ticket(status="denied", kind="deny_custom")
    mongo = _mongo(ticket)
    rest = _Rest()
    real_mark = delivery.mark_step
    calls = 0

    async def lose_first_notice(mongo_arg, ticket_arg, owner, step):
        nonlocal calls
        if step == "notice_sent" and calls == 0:
            calls += 1
            raise delivery.ResolutionLeaseLost("checkpoint response lost")
        return await real_mark(mongo_arg, ticket_arg, owner, step)

    monkeypatch.setattr(delivery, "mark_step", lose_first_notice)
    first = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert first["failed"] == 1
    assert rest.notice_calls == 1
    _expire_retry(mongo)

    second = asyncio.run(delivery.recover_pending_deliveries(bot=_Bot(rest), mongo=mongo))
    assert second["completed"] == 1
    assert rest.notice_calls == 1


def test_stale_effect_and_stale_owner_cannot_checkpoint():
    ticket = _ticket(state="processing")
    ticket["resolution_delivery"].update({
        "lease_owner": "current",
        "lease_until": datetime.now(timezone.utc) + timedelta(minutes=1),
    })
    mongo = _mongo(ticket)

    with pytest.raises(delivery.ResolutionLeaseLost):
        asyncio.run(delivery.mark_step(mongo, ticket, "stale", "notice_sent"))

    stale_effect = deepcopy(ticket)
    stale_effect["resolution_delivery"]["effect_id"] = "old-effect"
    with pytest.raises(delivery.ResolutionLeaseLost):
        asyncio.run(delivery.mark_step(mongo, stale_effect, "current", "notice_sent"))
    assert "notice_sent" not in mongo.button_store.rows["ticket-1"]["resolution_delivery"]


def test_expired_processing_lease_is_taken_over_but_live_lease_is_not():
    now = datetime.now(timezone.utc)
    ticket = _ticket(state="processing")
    ticket["resolution_delivery"].update({
        "lease_owner": "old",
        "lease_until": now - timedelta(seconds=1),
    })
    mongo = _mongo(ticket)

    claimed = asyncio.run(delivery.claim_delivery(mongo, ticket, now=now))
    assert claimed is not None
    assert claimed["resolution_delivery"]["lease_owner"] != "old"
    assert asyncio.run(delivery.claim_delivery(mongo, claimed, now=now)) is None


def test_startup_scan_only_processes_rows_with_resolution_marker(monkeypatch):
    marked = _ticket()
    unmarked = {**_ticket(effect_id="unused"), "_id": "ticket-2"}
    unmarked.pop("resolution_delivery")
    mongo = _mongo(marked, extras=[unmarked])
    seen = []

    async def complete(_bot, mongo_arg, claimed):
        seen.append(claimed["_id"])
        effect = claimed["resolution_delivery"]
        return await delivery.finish_delivery(
            mongo_arg, claimed, effect["lease_owner"]
        )

    monkeypatch.setattr(delivery, "deliver_claimed", complete)
    result = asyncio.run(delivery.recover_pending_deliveries(bot=SimpleNamespace(), mongo=mongo))

    assert seen == ["ticket-1"]
    assert result["processed"] == 1


def test_recovery_fair_order_reaches_rows_beyond_persistent_failed_batch(
    monkeypatch,
):
    baseline = datetime(2026, 8, 23, tzinfo=timezone.utc)
    blockers = []
    for index in range(delivery.RECOVERY_LIMIT):
        blocker = {
            **_ticket(effect_id=f"failed-effect-{index}"),
            "_id": f"ticket-a-{index:02d}",
        }
        blocker["resolution_delivery"]["updated_at"] = baseline
        blockers.append(blocker)
    target = {
        **_ticket(effect_id="target-effect"),
        "_id": "ticket-z-target",
    }
    target["resolution_delivery"]["updated_at"] = baseline
    mongo = _mongo(blockers[0], extras=[*blockers[1:], target])
    seen = []

    async def fail_blockers(_bot, mongo_arg, claimed):
        seen.append(claimed["_id"])
        if claimed["_id"] == "ticket-z-target":
            effect = claimed["resolution_delivery"]
            return await delivery.finish_delivery(
                mongo_arg,
                claimed,
                effect["lease_owner"],
            )
        raise RuntimeError("persistent Discord failure")

    monkeypatch.setattr(delivery, "deliver_claimed", fail_blockers)
    first = asyncio.run(delivery.recover_pending_deliveries(
        bot=SimpleNamespace(),
        mongo=mongo,
    ))
    assert first["failed"] == delivery.RECOVERY_LIMIT
    assert "ticket-z-target" not in seen

    for blocker in blockers:
        mongo.button_store.rows[blocker["_id"]]["resolution_delivery"][
            "retry_after"
        ] = datetime.now(timezone.utc) - timedelta(seconds=1)

    second = asyncio.run(delivery.recover_pending_deliveries(
        bot=SimpleNamespace(),
        mongo=mongo,
    ))
    assert second["completed"] == 1
    assert seen[delivery.RECOVERY_LIMIT] == "ticket-z-target"


def test_status_mismatch_cancels_stale_effect_without_blocking_next_override():
    ticket = _ticket(status="approved", kind="deny_custom")
    ticket["resolution_delivery"]["decision_status"] = "denied"
    mongo = _mongo(ticket)

    async def scenario():
        recovery = await delivery.recover_pending_deliveries(
            bot=SimpleNamespace(),
            mongo=mongo,
        )
        assert recovery["completed"] == 0
        assert (
            mongo.button_store.rows["ticket-1"]
            ["resolution_delivery"]["state"]
            == "cancelled"
        )

        result = await store.transition(
            mongo,
            "ticket-1",
            to_status="denied",
            actor_id=9,
            actor_name="Leader",
            expect=None,
            overrides={"status": "approved", "by": 8, "by_name": "Recruiter"},
            resolution_effect=_plan("deny_custom"),
        )
        assert result.won
        assert result.doc["status"] == "denied"
        assert result.doc["resolution_delivery"]["state"] == "pending"

    asyncio.run(scenario())


def test_shutdown_cancels_and_clears_retry_tasks(monkeypatch):
    async def scenario():
        await delivery.start_retries()
        ticket = _ticket()

        async def never_finish(**_kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(delivery, "_retry_worker", never_finish)
        task = delivery.schedule_retry(bot=SimpleNamespace(), mongo=SimpleNamespace(), ticket=ticket)
        await asyncio.sleep(0)
        await delivery.stop_retries()
        assert task.cancelled()
        assert delivery._retry_tasks == {}

    asyncio.run(scenario())


def test_notice_history_requires_exact_bot_author_and_content():
    ticket = _ticket()
    plan = _plan("approve")
    rest = _Rest()
    rest.messages[444] = [
        SimpleNamespace(id=10, author=SimpleNamespace(id=7), content=plan["notice_content"], components=()),
        SimpleNamespace(id=11, author=SimpleNamespace(id=999), content=plan["notice_content"] + "!", components=()),
    ]
    assert not asyncio.run(delivery._notice_exists(_Bot(rest), ticket, plan))

    rest.messages[444].append(
        SimpleNamespace(id=12, author=SimpleNamespace(id=999), content=plan["notice_content"], components=())
    )
    assert asyncio.run(delivery._notice_exists(_Bot(rest), ticket, plan))


def test_denial_history_requires_exact_bot_component_signature():
    ticket = _ticket(status="denied", kind="deny_custom")
    plan = _plan("deny_custom")
    rest = _Rest()
    wrong = _plan("deny_custom")
    wrong["notice_text"] += " altered"
    rest.messages[444] = [
        SimpleNamespace(id=10, author=SimpleNamespace(id=7), content="", components=delivery.denial_components(plan)),
        SimpleNamespace(id=11, author=SimpleNamespace(id=999), content="", components=delivery.denial_components(wrong)),
    ]
    assert not asyncio.run(delivery._notice_exists(_Bot(rest), ticket, plan))

    rest.messages[444].append(SimpleNamespace(
        id=12, author=SimpleNamespace(id=999), content="", components=delivery.denial_components(plan)
    ))
    assert asyncio.run(delivery._notice_exists(_Bot(rest), ticket, plan))


def test_denial_history_matches_discord_cdn_response_for_local_footer_attachment():
    ticket = _ticket(status="denied", kind="deny_custom")
    expected_plan = _plan("deny_custom")
    response_plan = {
        **expected_plan,
        "footer_media": (
            "https://cdn.discordapp.com/attachments/123/456/Red_Footer.png"
            "?ex=abc&is=def&hm=ghi"
        ),
    }
    rest = _Rest()
    rest.messages[444] = [SimpleNamespace(
        id=10,
        author=SimpleNamespace(id=999),
        content="",
        components=delivery.denial_components(response_plan),
    )]

    assert asyncio.run(delivery._notice_exists(_Bot(rest), ticket, expected_plan))


@pytest.mark.parametrize(
    ("sequence", "statuses"),
    [
        (("approve", "deny_custom", "approve"), ("approved", "denied", "approved")),
        (("deny_custom", "approve", "deny_custom"), ("denied", "approved", "denied")),
    ],
)
def test_repeat_override_notice_ignores_identical_older_effect(
    monkeypatch,
    sequence,
    statuses,
):
    ticket = _ticket(status=statuses[0], kind=sequence[0])
    mongo = _mongo(ticket)
    rest = _Rest()

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(delivery.asyncio, "sleep", no_sleep)

    async def scenario():
        first = await delivery.recover_pending_deliveries(
            bot=_Bot(rest), mongo=mongo
        )
        assert first["completed"] == 1

        for index in (1, 2):
            prior = mongo.button_store.rows["ticket-1"]
            result = await store.transition(
                mongo,
                "ticket-1",
                to_status=statuses[index],
                actor_id=8 + index,
                actor_name="Recruiter",
                expect=None,
                overrides={"status": prior["status"], "by": 8, "by_name": "Recruiter"},
                resolution_effect=_plan(sequence[index]),
            )
            assert result.won
            driven = await delivery.recover_pending_deliveries(
                bot=_Bot(rest), mongo=mongo
            )
            assert driven["completed"] == 1

    asyncio.run(scenario())

    assert rest.notice_calls == 3
    messages = rest.messages[444]
    repeated_kind = sequence[0]
    if repeated_kind == "approve":
        repeated = [
            message for message in messages
            if message.content == _plan("approve")["notice_content"]
        ]
    else:
        signature = delivery._component_signature(
            delivery.denial_components(_plan("deny_custom"))
        )
        repeated = [
            message for message in messages
            if delivery._component_signature(message.components) == signature
        ]
    assert len(repeated) == 2
    assert repeated[1].id > repeated[0].id


def test_resolution_transition_and_claim_cas_against_real_mongo():
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
        database_name = f"wu_legacy_resolution_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        mongo = SimpleNamespace(button_store=database.button_store)
        ticket = _ticket(status="open")
        ticket.pop("resolution_delivery")
        try:
            await client.admin.command("ping")
            await database.button_store.insert_one(ticket)
            first, second = await asyncio.gather(
                store.transition(
                    mongo, "ticket-1", to_status="approved", actor_id=8,
                    actor_name="A", resolution_effect=_plan("approve"),
                ),
                store.transition(
                    mongo, "ticket-1", to_status="denied", actor_id=9,
                    actor_name="B", resolution_effect=_plan("deny_custom"),
                ),
            )
            assert sum(result.won for result in (first, second)) == 1
            durable = await database.button_store.find_one({"_id": "ticket-1"})
            assert durable["resolution_delivery"]["decision_status"] == durable["status"]

            now = datetime.now(timezone.utc)
            one, two = await asyncio.gather(
                delivery.claim_delivery(mongo, durable, now=now),
                delivery.claim_delivery(mongo, durable, now=now),
            )
            assert sum(result is not None for result in (one, two)) == 1
        finally:
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())

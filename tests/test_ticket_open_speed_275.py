"""Opening-order regressions use fictional tickets and in-memory transports."""

import asyncio
import logging
import re
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from extensions.commands import ticket_runtime
from extensions.commands.tickets import account_sync, console, store, thread_service
from tests.test_ticket_creation import _slot_claim
from tests.test_ticket_storage_foundation import Collection, _mongo, _ticket


@pytest.fixture
def opening(monkeypatch):
    events = []
    saved = {}
    state = {}
    delivered = set()

    async def nothing(*_args, **_kwargs):
        return None

    async def existing(*_args, **_kwargs):
        return deepcopy(saved) if saved else None

    async def claim(*_args, **kwargs):
        return "fixture-owner", {"ticket_number": 1, "ticket_type": kwargs["ticket_type"]}, False

    async def pair(**kwargs):
        events.append("pair")
        return SimpleNamespace(id=101), SimpleNamespace(id=102), kwargs["state"]

    async def insert(_mongo, ticket):
        events.append("row")
        saved.update(ticket)
        mongo.tickets.documents[ticket["_id"]] = deepcopy(ticket)
        return deepcopy(saved)

    async def checkpoint(_mongo, _ticket, *, state: str, error=None):
        if state == "complete":
            assert store.opening_delivery_proven(mongo.tickets.documents[_ticket["_id"]])
        opening_state.update({
            "_id": _ticket["creation_workflow_id"],
            "kind": "thread_ticket_creation", "ticket_id": _ticket["_id"],
            "guild_id": _ticket["guild_id"], "user_id": _ticket["user_id"],
            "ticket_type": _ticket["ticket_type"], "state": state,
            "delivery": {"state": "complete" if state == "complete" else "pending"},
        })

    async def delivery(_rest, ticket, **_kwargs):
        events.append("delivery")
        delivered.add(ticket["_id"])

    async def dm(*_args, **_kwargs):
        events.append("dm")

    async def refresh(*_args, **_kwargs):
        events.append("console")

    async def sync(_mongo, _client, _ticket_id, *, source):
        events.append("account_sync")
        current = mongo.tickets.documents.get(_ticket_id, saved)
        updated = {**current, "linked_accounts": {
            "version": 2, "state": "empty", "retry_required": False,
            "current": [], "current_tags": [], "revision": 1, "source": source,
        }}
        saved.update(updated)
        return account_sync.AccountSyncResult(updated, account_sync.snapshot_from_ticket(updated))

    async def failed(_mongo, _ticket_id, **_kwargs):
        saved["linked_accounts"] = {
            "version": 2, "state": "failed", "retry_required": True,
            "current": [], "current_tags": [], "revision": 1,
        }
        return account_sync.AccountSyncResult(deepcopy(saved), account_sync.snapshot_from_ticket(saved))

    opening_state = state
    mongo = SimpleNamespace(
        ticket_creation_state=SimpleNamespace(find_one=nothing),
        ticket_staff_templates=SimpleNamespace(find_one=nothing),
        tickets=Collection(),
    )
    monkeypatch.setattr(thread_service, "ensure_creation_indexes", nothing)
    monkeypatch.setattr(thread_service, "validate_thread_parents", nothing)
    monkeypatch.setattr(thread_service, "parents_from_config", lambda *_a, **_k: thread_service.ThreadParents(10, 20, 21, 40))
    monkeypatch.setattr(thread_service.store, "find_open_for_applicant", existing)
    monkeypatch.setattr(thread_service.store, "insert_one", insert)
    monkeypatch.setattr(thread_service, "_committed_ticket_for_creation_state", nothing)
    monkeypatch.setattr(thread_service, "_claim_creation", claim)
    monkeypatch.setattr(thread_service, "_ensure_live_thread_pair", pair)
    monkeypatch.setattr(thread_service, "_set_committed_creation_state", checkpoint)
    monkeypatch.setattr(thread_service, "_queue_staff_context_outbox", nothing)
    monkeypatch.setattr(thread_service, "_deliver_opening_messages", delivery)
    monkeypatch.setattr(thread_service, "reconcile_ticket_pair", nothing)
    monkeypatch.setattr(thread_service, "_send_ticket_creation_dm", dm)
    monkeypatch.setattr(thread_service, "notify_console_after_change", refresh)
    monkeypatch.setattr(ticket_runtime, "bind_open_slot", nothing)
    monkeypatch.setattr(ticket_runtime, "cancel_open_slot", nothing)
    monkeypatch.setattr(account_sync, "sync_ticket_accounts", sync)
    monkeypatch.setattr(account_sync, "record_ticket_account_failure", failed)
    from utils import gauntlet_tracking
    monkeypatch.setattr(gauntlet_tracking, "ticket_opened", nothing)
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=SimpleNamespace())

    async def create(kind="main"):
        return await thread_service.create_live_thread_ticket(
            bot=bot, mongo=mongo, guild_id=10, user_id=30,
            username="Fictional member", display_name=None, ticket_type=kind,
            account_clan="main" if kind == "account" else None,
            config={"ticket_target_guild_id": 10},
            open_slot_claim=_slot_claim(ticket_type=kind), coc_client=object(),
        )

    return SimpleNamespace(events=events, saved=saved, state=state, delivered=delivered,
                           create=create, bot=bot, mongo=mongo)


@pytest.mark.parametrize("kind", ["main", "fwa", "account"])
def test_opening_delivery_precedes_external_account_lookup(opening, kind):
    result = asyncio.run(opening.create(kind))
    assert not result.delivery_pending
    assert opening.events.index("delivery") < opening.events.index("account_sync")
    assert opening.events.index("dm") < opening.events.index("account_sync")
    assert opening.events.index("console") < opening.events.index("account_sync")


def test_contact_staff_skips_open_account_lookup(opening):
    asyncio.run(opening.create("staff"))
    assert "delivery" in opening.events
    assert "account_sync" not in opening.events


@pytest.mark.parametrize("failure", [account_sync.AccountSyncError("fixture failure"), TimeoutError("fixture timeout")])
def test_post_delivery_lookup_failure_remains_account_only_work(opening, monkeypatch, failure):
    async def fail(*_args, **_kwargs):
        opening.events.append("account_sync")
        raise failure

    monkeypatch.setattr(account_sync, "sync_ticket_accounts", fail)
    result = asyncio.run(opening.create())
    assert result.delivery_pending is False
    assert opening.state["state"] == "complete"
    assert opening.saved["linked_accounts"]["retry_required"] is True
    assert opening.events.count("delivery") == 1


def test_restart_after_delivery_recovers_lookup_without_resending(opening, monkeypatch):
    async def interrupted(*_args, **_kwargs):
        opening.events.append("account_sync")
        raise asyncio.CancelledError

    monkeypatch.setattr(account_sync, "sync_ticket_accounts", interrupted)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(opening.create())
    assert opening.state["state"] == "complete"
    assert opening.delivered == {"ticket_101"}
    # Startup's independent account-recovery path consumes a missing snapshot;
    # it must not enter creation delivery or create a second pair.
    ticket = deepcopy(opening.mongo.tickets.documents[opening.saved["_id"]])
    mongo = _mongo(ticket)
    mongo.ticket_creation_state = Collection([opening.state])

    async def completed(_mongo, _client, ticket_id, *, source):
        assert source == account_sync.SOURCE_RECOVERY
        durable = {**ticket, "linked_accounts": {"version": 2, "state": "empty", "retry_required": False}}
        return account_sync.AccountSyncResult(durable, account_sync.snapshot_from_ticket(durable))

    monkeypatch.setattr(account_sync, "sync_ticket_accounts", completed)
    counts = asyncio.run(account_sync.recover_pending_account_syncs(mongo, object()))
    assert counts["completed"] == 1
    assert opening.events.count("delivery") == 1
    assert opening.events.count("pair") == 1


def test_staff_without_snapshot_is_not_automatic_open_sync_work(monkeypatch):
    ticket = _ticket()
    ticket.update(ticket_type="staff", status="open")
    ticket.pop("linked_accounts", None)
    calls = []

    async def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("staff open sync must be skipped")

    monkeypatch.setattr(account_sync, "sync_ticket_accounts", forbidden)
    counts = asyncio.run(account_sync.recover_pending_account_syncs(_mongo(ticket), object()))
    assert calls == []
    assert counts["processed"] == 0


def test_staff_context_shows_loading_before_first_account_result(monkeypatch):
    async def empty(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", empty)
    monkeypatch.setattr(console.store, "history_for", empty)
    ticket = _ticket()
    ticket.pop("linked_accounts", None)
    components = asyncio.run(console.build_staff_identity_context(SimpleNamespace(), ticket))
    assert components is not None
    rendered = str([component.build() for component in components])
    assert "Loading accounts" in rendered
    assert "zero accounts" not in rendered


def test_open_timing_line_is_one_bounded_private_shape(opening, caplog):
    with caplog.at_level(logging.INFO, logger=thread_service.__name__):
        asyncio.run(opening.create())
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("ticket_open ")]
    assert len(lines) == 1
    assert re.fullmatch(r"ticket_open ticket=ticket_101 pair_ms=\d+ row_ms=\d+ delivery_ms=\d+ account_sync_ms=\d+ dm_ms=\d+ console_ms=\d+", lines[0])
    assert "Fictional" not in lines[0]
    assert "#" not in lines[0]


def test_fake_latency_removes_account_lookup_from_opening_delay(opening, monkeypatch, caplog):
    """Before uses the recorded base call order; after executes the new flow.

    No sleep or provider request is made. These synthetic numbers describe the
    ordering effect, never measured production or real Discord latency.
    """
    clock = [0.0]
    delivered_at = []
    delays = {"pair": .010, "row": .020, "delivery": .030,
              "account_sync": .250, "dm": .005, "console": .002}

    def wrap(name, original):
        async def measured(*args, **kwargs):
            clock[0] += delays[name]
            result = await original(*args, **kwargs)
            if name == "delivery":
                delivered_at.append(clock[0])
            return result
        return measured

    for name, module, attribute in [
        ("pair", thread_service, "_ensure_live_thread_pair"),
        ("row", thread_service.store, "insert_one"),
        ("delivery", thread_service, "_finish_committed_creation"),
        ("account_sync", account_sync, "sync_ticket_accounts"),
        ("dm", thread_service, "_send_ticket_creation_dm"),
        ("console", thread_service, "notify_console_after_change"),
    ]:
        monkeypatch.setattr(module, attribute, wrap(name, getattr(module, attribute)))
    monkeypatch.setattr(thread_service.time, "monotonic", lambda: clock[0])
    with caplog.at_level(logging.INFO, logger=thread_service.__name__):
        asyncio.run(opening.create())
    before_order = ["pair", "row", "account_sync", "delivery", "dm", "console"]
    before_delivery = sum(delays[name] for name in before_order[:4])
    assert round(delivered_at[0] * 1000) == 60
    assert round(before_delivery * 1000) == 310
    line = next(record.getMessage() for record in caplog.records if record.getMessage().startswith("ticket_open "))
    assert "pair_ms=10 row_ms=20 delivery_ms=30 account_sync_ms=250 dm_ms=5 console_ms=4" in line
    report = {
        "method": "Synthetic monotonic clock; fake latency in every stage; no network or sleeping",
        "before_basis": "Modeled from actual unchanged-main fail-first trace order saved in wu-275-fail-first-5bon4blm",
        "before_order": before_order, "after_order": opening.events,
        "before_opening_ms_modeled": 310, "after_opening_ms_observed_fixture": 60,
        "lookup_ms": 250, "timing_log": line,
        "live_latency_claim": False,
    }
    path = Path(".local/275-evidence/fixture-timing275.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")


def _modern_ticket(*, public=101, number=1):
    ticket = _ticket(public=public, staff=public + 1, number=number)
    ticket["creation_workflow_id"] = "thread:30:main"
    ticket["opening_delivery"] = store.pending_opening_delivery(ticket)
    return ticket


def test_recovery_waits_for_permanent_delivery_transition(monkeypatch):
    ticket = _modern_ticket()
    mongo = _mongo(ticket)
    calls = []

    async def completed(_mongo, _client, ticket_id, *, source):
        calls.append(ticket_id)
        durable = {**ticket, "linked_accounts": {"version": 2, "state": "empty", "retry_required": False}}
        return account_sync.AccountSyncResult(durable, account_sync.snapshot_from_ticket(durable))

    monkeypatch.setattr(account_sync, "sync_ticket_accounts", completed)
    before = asyncio.run(account_sync.recover_pending_account_syncs(mongo, object()))
    assert calls == [] and before["processed"] == 0
    assert asyncio.run(store.finish_opening_delivery(mongo, ticket))
    after = asyncio.run(account_sync.recover_pending_account_syncs(mongo, object()))
    assert calls == [ticket["_id"]] and after["completed"] == 1


@pytest.mark.parametrize("change", [
    {"ticket_id": "ticket_other_generation"}, {"guild_id": 999},
    {"user_id": 999}, {"ticket_type": "fwa"}, {"candidate_id": 999},
    {"staff_id": 999}, {"workflow_id": "unrelated"}, {"state": "unknown"},
])
def test_permanent_receipt_generation_and_authority_must_match(change):
    ticket = _modern_ticket()
    mongo = _mongo(ticket)
    assert asyncio.run(store.finish_opening_delivery(mongo, ticket))
    ticket["opening_delivery"].update(change)
    assert asyncio.run(thread_service.opening_delivery_complete(mongo, ticket)) is False


def test_new_pending_marker_cannot_borrow_a_later_creation_generation():
    ticket = _modern_ticket()
    mongo = _mongo(ticket)
    mongo.ticket_creation_state = Collection([{
        "_id": ticket["creation_workflow_id"], "ticket_id": "later_ticket",
        "state": "complete", "delivery": {"state": "complete"},
    }])
    assert asyncio.run(thread_service.opening_delivery_complete(mongo, ticket)) is False
    ticket["opening_delivery"] = "malformed"
    assert asyncio.run(thread_service.opening_delivery_complete(mongo, ticket)) is False


def test_permanent_proof_survives_creation_ttl_and_key_reuse():
    ticket = _modern_ticket()
    mongo = _mongo(ticket)
    assert asyncio.run(store.finish_opening_delivery(mongo, ticket))
    # Creation receipts have expired (or the user/type key belongs to a later
    # ticket). Account recovery uses the non-TTL canonical proof instead.
    mongo.ticket_creation_state = Collection()
    from datetime import datetime, timedelta, timezone
    ticket["opening_delivery"]["completed_at"] = datetime.now(timezone.utc) - timedelta(days=3)
    assert asyncio.run(thread_service.opening_delivery_complete(mongo, ticket))
    mongo.ticket_creation_state.documents["thread:30:main"] = {"ticket_id": "later"}
    assert asyncio.run(thread_service.opening_delivery_complete(mongo, ticket))


def test_pre275_owner_notification_is_not_retroactively_a_proof_requirement():
    ticket = _ticket()
    ticket["creation_workflow_id"] = "thread:30:main"
    ticket["opening_member_notification"] = {"state": "attempted"}
    assert "opening_delivery" not in ticket
    assert asyncio.run(thread_service.opening_delivery_complete(SimpleNamespace(), ticket))


@pytest.mark.parametrize("accepted", [False, True])
def test_proof_write_uncertainty_never_starts_creation_ttl(opening, monkeypatch, accepted):
    original = store.finish_opening_delivery

    async def unavailable(mongo, ticket):
        if accepted:
            await original(mongo, ticket)
        raise TimeoutError("synthetic uncertain proof acknowledgement")

    monkeypatch.setattr(store, "finish_opening_delivery", unavailable)
    first = asyncio.run(opening.create())
    assert first.delivery_pending is True
    assert opening.state["state"] != "complete"
    assert "account_sync" not in opening.events
    durable = opening.mongo.tickets.documents[first.ticket["_id"]]
    assert store.opening_delivery_proven(durable) is accepted
    monkeypatch.setattr(store, "finish_opening_delivery", original)
    # The existing message receipts, not this new proof, prevent resend after
    # uncertainty. This fixture's transport records unique accepted ticket ids.
    second = asyncio.run(opening.create())
    assert second.delivery_pending is False
    assert len(opening.delivered) == 1


def test_staff_explicit_failed_refresh_remains_recoverable(monkeypatch):
    ticket = _ticket()
    ticket.update(ticket_type="staff", linked_accounts={"version": 2, "state": "failed", "retry_required": True})
    calls = []

    async def completed(_mongo, _client, ticket_id, *, source):
        calls.append(ticket_id)
        durable = {**ticket, "linked_accounts": {"version": 2, "state": "empty", "retry_required": False}}
        return account_sync.AccountSyncResult(durable, account_sync.snapshot_from_ticket(durable))

    monkeypatch.setattr(account_sync, "sync_ticket_accounts", completed)
    counts = asyncio.run(account_sync.recover_pending_account_syncs(_mongo(ticket), object()))
    assert calls == [ticket["_id"]]
    assert counts["completed"] == 1


def test_open_sync_persists_context_refresh_before_return(monkeypatch):
    from extensions.commands.linked_accounts import AccountsData

    async def empty(*_args, **_kwargs):
        return AccountsData()

    monkeypatch.setattr(account_sync, "load_accounts", empty)
    ticket = _ticket()
    mongo = _mongo(ticket)
    result = asyncio.run(account_sync.sync_ticket_accounts(mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN))
    assert result.snapshot.successful
    assert mongo.tickets.documents[ticket["_id"]]["linked_accounts"]["context_refresh_required"] is True


@pytest.mark.parametrize('blocked', [25, 50])
def test_full_pending_pages_do_not_starve_later_lookup_or_context(monkeypatch, blocked):
    rows = [_modern_ticket(public=1000 + index * 2, number=index + 1) for index in range(blocked)]
    # Stable ids put the gated rows first in the missing-attempt bucket.
    for index, row in enumerate(rows):
        row['_id'] = f'ticket_a{index:03}'
        row['user_id'] = 30 + index
        row['creation_workflow_id'] = f'thread:{30 + index}:main'
        row['opening_delivery'] = store.pending_opening_delivery(row)
    eligible = _ticket(public=9000)
    eligible['_id'] = 'ticket_z_lookup'
    context = _ticket(public=9002)
    context['_id'] = 'ticket_z_context'
    context['linked_accounts'] = {
        'version': 2, 'state': 'empty', 'retry_required': False,
        'context_refresh_required': True, 'context_refresh_revision': 0,
    }
    mongo = _mongo(*rows, eligible, context)
    observed = []
    queued = []

    async def sync(_mongo, _client, ticket_id, *, source):
        observed.append(ticket_id)
        result = {**eligible, 'linked_accounts': {'version': 2, 'state': 'empty', 'retry_required': False}}
        mongo.tickets.documents[ticket_id] = result
        return account_sync.AccountSyncResult(result, account_sync.snapshot_from_ticket(result))

    async def queue(ticket):
        queued.append(ticket['_id'])
        return f"ticket_staff_context:{ticket['_id']}"

    monkeypatch.setattr(account_sync, 'sync_ticket_accounts', sync)
    for _ in range(blocked // 25 + 1):
        asyncio.run(account_sync.recover_pending_account_syncs(mongo, object(), after_sync=queue))
    assert observed == ['ticket_z_lookup']
    assert queued == ['ticket_z_context']
    assert all(mongo.tickets.documents[row['_id']] == row for row in rows)


def test_seek_cursor_handles_missing_dates_equal_dates_and_wrap_without_duplicates(monkeypatch):
    from datetime import datetime, timedelta, timezone
    date = datetime.now(timezone.utc) - timedelta(days=1)
    rows = [_ticket(public=100 + i * 2) for i in range(5)]
    for index, row in enumerate(rows):
        row['_id'] = f'ticket_{index}'
        if index >= 2:
            row['linked_accounts'] = {'last_attempt_at': date}
    mongo = _mongo(*rows)
    query = {**store.RUNTIME_FILTER, '$or': [
        {'linked_accounts.last_attempt_at': {'$exists': False}},
        {'linked_accounts.last_attempt_at': {'$lte': date}},
    ]}
    found = []
    for _ in range(3):
        scan, page = asyncio.run(account_sync._account_recovery_page(mongo, query, 2))
        ids = [row['_id'] for row in page]
        assert len(ids) == len(set(ids)) <= 2
        found.extend(ids)
        scan.reserved.difference_update(ids)
    assert set(found) == {row['_id'] for row in rows}
    assert found[:5] == [row['_id'] for row in rows]


def test_concurrent_page_reservations_are_disjoint_and_cancel_releases_lock(monkeypatch):
    mongo = _mongo(*[_ticket(public=100 + i * 2) for i in range(3)])

    async def exercise():
        first, second = await asyncio.gather(
            account_sync._account_recovery_page(mongo, store.RUNTIME_FILTER, 2),
            account_sync._account_recovery_page(mongo, store.RUNTIME_FILTER, 2),
        )
        left = {row['_id'] for row in first[1]}
        right = {row['_id'] for row in second[1]}
        assert not left & right and len(left | right) == 3
        first[0].reserved.clear()
        original = account_sync.store.find
        entered = asyncio.Event()

        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(account_sync.store, 'find', blocked)
        task = asyncio.create_task(account_sync._account_recovery_page(mongo, store.RUNTIME_FILTER, 2))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not first[0].lock.locked() and not first[0].reserved
        monkeypatch.setattr(account_sync.store, 'find', original)
        scan, page = await account_sync._account_recovery_page(mongo, store.RUNTIME_FILTER, 2)
        assert page
        scan.reserved.clear()

    asyncio.run(exercise())


def test_new_ticket_pending_proof_is_present_at_insert(opening, monkeypatch):
    original = store.insert_one
    observed = []

    async def insert(mongo, ticket):
        observed.append(deepcopy(ticket['opening_delivery']))
        assert ticket['opening_delivery'] == store.pending_opening_delivery(ticket)
        return await original(mongo, ticket)

    monkeypatch.setattr(store, 'insert_one', insert)
    result = asyncio.run(opening.create())
    assert observed[0]['state'] == 'pending'
    assert store.opening_delivery_proven(result.ticket)


def test_opening_proof_has_one_public_storage_owner():
    ticket = _modern_ticket()
    mongo = _mongo(ticket)
    with pytest.raises(store.GuardedFieldWriteError):
        asyncio.run(store.update_one(mongo, {'_id': ticket['_id']}, {'$unset': {'opening_delivery': ''}}))
    assert mongo.tickets.documents[ticket['_id']]['opening_delivery']['state'] == 'pending'


def test_null_attempt_stays_ineligible_while_missing_and_dates_progress():
    from datetime import datetime, timedelta, timezone
    due = datetime.now(timezone.utc) - timedelta(days=1)
    missing, null, dated = [_ticket(public=100 + i * 2) for i in range(3)]
    missing['_id'], null['_id'], dated['_id'] = 'ticket_a', 'ticket_b', 'ticket_c'
    null['linked_accounts'] = {'last_attempt_at': None}
    dated['linked_accounts'] = {'last_attempt_at': due}
    mongo = _mongo(missing, null, dated)
    all_rows = mongo.tickets.find(store.RUNTIME_FILTER).sort([
        ('linked_accounts.last_attempt_at', 1), ('_id', 1),
    ]).documents
    assert [row['_id'] for row in all_rows] == ['ticket_a', 'ticket_b', 'ticket_c']
    query = {**store.RUNTIME_FILTER, '$or': [
        {'linked_accounts.last_attempt_at': {'$exists': False}},
        {'linked_accounts.last_attempt_at': {'$lte': due}},
    ]}
    ids = []
    for _ in range(2):
        scan, page = asyncio.run(account_sync._account_recovery_page(mongo, query, 1))
        ids.extend(row['_id'] for row in page)
        scan.reserved.difference_update(row['_id'] for row in page)
    assert ids == ['ticket_a', 'ticket_c']
    assert 'ticket_b' not in ids
    # The synthetic comparator intentionally models type bracketing. This is
    # not a real-Mongo execution claim and does not broaden null eligibility.
    assert mongo.tickets.find({'linked_accounts.last_attempt_at': {'$gt': None}}).documents == []


def test_cursor_bypasses_auto_collection_attributes_and_releases_on_query_error(monkeypatch):
    class ClientTrap(SimpleNamespace):
        def __getattr__(self, name):
            raise AssertionError(f'auto collection attribute was probed: {name}')

    mongo = ClientTrap(**vars(_mongo(_ticket())))
    original = account_sync.store.find

    async def exercise():
        scan, page = await account_sync._account_recovery_page(mongo, store.RUNTIME_FILTER, 2)
        scan.reserved.clear()
        cursor = scan.cursor

        async def outage(*args, **kwargs):
            raise TimeoutError('synthetic query outage')

        monkeypatch.setattr(account_sync.store, 'find', outage)
        with pytest.raises(TimeoutError):
            await account_sync._account_recovery_page(mongo, store.RUNTIME_FILTER, 2)
        assert scan.cursor == cursor and not scan.lock.locked() and not scan.reserved
        monkeypatch.setattr(account_sync.store, 'find', original)

    asyncio.run(exercise())


def test_processing_cancellation_releases_reserved_page(monkeypatch):
    mongo = _mongo(_ticket())

    async def exercise():
        entered = asyncio.Event()

        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(account_sync, 'sync_ticket_accounts', blocked)
        task = asyncio.create_task(account_sync.recover_pending_account_syncs(mongo, object()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        scan = vars(mongo)['_wu_ticket_account_recovery_scan']
        assert not scan.reserved and not scan.lock.locked()

    asyncio.run(exercise())


def test_terminal_retirement_does_not_manufacture_opening_proof():
    ticket = _modern_ticket()
    ticket['status'] = 'denied'
    mongo = _mongo(ticket)
    mongo.ticket_creation_state = Collection()
    asyncio.run(thread_service.mark_creation_complete_for_terminal_ticket(mongo, ticket))
    assert mongo.tickets.documents[ticket['_id']]['opening_delivery']['state'] == 'pending'


@pytest.mark.parametrize("tz_aware", [False, True])
def test_bson_int64_pending_cas_and_completed_proof_survive_driver_roundtrip(tz_aware):
    """Real BSON encoding, synthetic collection: not a live Mongo CAS test."""
    from bson import BSON
    from bson.codec_options import CodecOptions
    from bson.int64 import Int64
    from datetime import datetime

    ticket = _modern_ticket(public=123456789012345678)
    ticket["guild_id"] = 223456789012345678
    ticket["location"]["guild_id"] = ticket["guild_id"]
    ticket["user_id"] = 323456789012345678
    ticket["opening_delivery"] = store.pending_opening_delivery(ticket)
    options = CodecOptions(tz_aware=tz_aware)
    decoded = BSON(BSON.encode(ticket)).decode(codec_options=options)
    for key in ["guild_id", "user_id", "candidate_id", "staff_id"]:
        assert isinstance(decoded["opening_delivery"][key], Int64)
        assert type(decoded["opening_delivery"][key]) is not int
    mongo = _mongo(decoded)
    assert asyncio.run(store.finish_opening_delivery(mongo, decoded))
    durable = BSON(BSON.encode(mongo.tickets.documents[ticket["_id"]])).decode(codec_options=options)
    completed_at = durable["opening_delivery"]["completed_at"]
    assert isinstance(completed_at, datetime)
    assert (completed_at.tzinfo is not None) is tz_aware
    assert store.opening_delivery_proven(durable)
    assert asyncio.run(thread_service.opening_delivery_complete(_mongo(durable), durable))
    # Completed idempotent retry must not write another proof after driver decode.
    async def forbidden_write(*_args, **_kwargs):
        raise AssertionError("completed proof must not be rewritten")
    mongo.tickets.update_one = forbidden_write
    assert asyncio.run(store.finish_opening_delivery(mongo, durable))


@pytest.mark.parametrize("key", ["guild_id", "user_id", "candidate_id", "staff_id"])
@pytest.mark.parametrize("bad", [True, False, "123456789012345678", 123456789012345678.0, None])
def test_numeric_opening_proof_binding_rejects_wrong_types(key, bad):
    ticket = _modern_ticket(public=123456789012345678)
    ticket["opening_delivery"][key] = bad
    mongo = _mongo(ticket)
    assert asyncio.run(store.finish_opening_delivery(mongo, ticket)) is False
    ticket["opening_delivery"].update(state="complete", completed_at=store.utcnow())
    assert store.opening_delivery_proven(ticket) is False


@pytest.mark.parametrize("key", ["ticket_id", "workflow_id", "ticket_type"])
@pytest.mark.parametrize("bad", [True, 1, None])
def test_text_opening_proof_binding_stays_strict(key, bad):
    ticket = _modern_ticket()
    ticket["opening_delivery"][key] = bad
    assert asyncio.run(store.finish_opening_delivery(_mongo(ticket), ticket)) is False
    ticket["opening_delivery"].update(state="complete", completed_at=store.utcnow())
    assert store.opening_delivery_proven(ticket) is False


@pytest.mark.parametrize("key", ["guild_id", "user_id", "candidate_id", "staff_id"])
@pytest.mark.parametrize("bad", [True, 1.0, "1"])
def test_numeric_opening_proof_rejects_equal_value_lookalikes(key, bad):
    # bool/float equal1 in Python; pending and complete proof reject both.
    ticket = _modern_ticket(public=1)
    ticket["guild_id"] = ticket["user_id"] = 1
    ticket["location"]["guild_id"] = ticket["location"]["staff_space_id"] = 1
    ticket["opening_delivery"] = store.pending_opening_delivery(ticket)
    ticket["opening_delivery"][key] = bad
    assert asyncio.run(store.finish_opening_delivery(_mongo(ticket), ticket)) is False
    ticket["opening_delivery"].update(state="complete", completed_at=store.utcnow())
    assert store.opening_delivery_proven(ticket) is False


@pytest.mark.parametrize("key", ["guild_id", "user_id", "candidate_id", "staff_id"])
def test_hikari_snowflake_receipt_values_are_valid_integer_bindings(key):
    from hikari import Snowflake

    ticket = _modern_ticket(public=123456789012345678)
    ticket["opening_delivery"][key] = Snowflake(ticket["opening_delivery"][key])
    assert asyncio.run(store.finish_opening_delivery(_mongo(ticket), ticket))
    ticket["opening_delivery"][key] = Snowflake(ticket["opening_delivery"][key])
    assert store.opening_delivery_proven(ticket)


@pytest.mark.parametrize("key", ["guild_id", "user_id", "candidate_id", "staff_id"])
def test_canonical_bool_snowflakes_cannot_be_normalized_into_delivery_proof(key):
    ticket = _modern_ticket(public=1)
    ticket["guild_id"] = ticket["user_id"] = 1
    ticket["location"]["staff_space_id"] = 1
    ticket["opening_delivery"] = store.pending_opening_delivery(ticket)
    if key in ["guild_id", "user_id"]:
        ticket[key] = True
    else:
        ticket["location"]["id" if key == "candidate_id" else "staff_space_id"] = True
    assert asyncio.run(store.finish_opening_delivery(_mongo(ticket), ticket)) is False
    ticket["opening_delivery"].update(state="complete", completed_at=store.utcnow())
    assert store.opening_delivery_proven(ticket) is False


@pytest.mark.parametrize("key", ["ticket_id", "workflow_id", "ticket_type"])
def test_opening_proof_text_subclasses_do_not_relax_exact_binding_type(key):
    class TextLookalike(str):
        pass

    ticket = _modern_ticket()
    ticket["opening_delivery"][key] = TextLookalike(ticket["opening_delivery"][key])
    assert asyncio.run(store.finish_opening_delivery(_mongo(ticket), ticket)) is False
    ticket["opening_delivery"].update(state="complete", completed_at=store.utcnow())
    assert store.opening_delivery_proven(ticket) is False


@pytest.mark.parametrize("key", ["guild_id", "user_id", "candidate_id", "staff_id"])
@pytest.mark.parametrize("bad", [1.9, 1.0, "1"])
def test_canonical_numeric_lookalikes_cannot_be_normalized_into_delivery_proof(key, bad):
    ticket = _modern_ticket(public=1)
    ticket["guild_id"] = ticket["user_id"] = 1
    ticket["location"]["staff_space_id"] = 1
    ticket["opening_delivery"] = store.pending_opening_delivery(ticket)
    if key in ["guild_id", "user_id"]:
        ticket[key] = bad
    else:
        ticket["location"]["id" if key == "candidate_id" else "staff_space_id"] = bad
    assert asyncio.run(store.finish_opening_delivery(_mongo(ticket), ticket)) is False
    ticket["opening_delivery"].update(state="complete", completed_at=store.utcnow())
    assert store.opening_delivery_proven(ticket) is False


@pytest.mark.parametrize("key", ["guild_id", "user_id", "candidate_id", "staff_id"])
def test_canonical_hikari_snowflakes_preserve_pending_and_completed_bindings(key):
    from hikari import Snowflake

    ticket = _modern_ticket(public=123456789012345678)
    if key in ["guild_id", "user_id"]:
        ticket[key] = Snowflake(ticket[key])
    else:
        location_key = "id" if key == "candidate_id" else "staff_space_id"
        ticket["location"][location_key] = Snowflake(ticket["location"][location_key])
    assert asyncio.run(store.finish_opening_delivery(_mongo(ticket), ticket))
    assert store.opening_delivery_proven(ticket)

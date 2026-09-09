"""Verified vs. mentioned player-tag identity split.

A ``#TAG``-shaped token an applicant types in their thread is unverified —
anyone can type any tag. These tests confirm it lands only on
``mentioned_tags`` (a search/display hint) and never on ``player_tags`` (the
verified identity flag matching, the blacklist gate, and account-identity
reconciliation rely on).
"""

import asyncio
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands.accounts import AccountsData
from extensions.commands.tickets import account_sync, console, flag_store, handlers, resolve, store
from tests.test_ticket_storage_foundation import Collection, NOW, _linked_account, _mongo, _ticket


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _nodes(view):
    return list(_walk([component.build() for component in view]))


def test_applicant_typed_tag_becomes_mentioned_not_verified(monkeypatch):
    """(a) A foreign tag typed in a message joins mentioned_tags, not player_tags."""
    ticket = _ticket()
    mongo = _mongo(ticket)

    async def no_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(handlers.thread_service, "notify_console_after_change", no_notify)

    event = SimpleNamespace(
        is_human=True,
        channel_id=ticket["location"]["id"],
        author_id=ticket["user_id"],
        message_id=9001,
        message=SimpleNamespace(
            content="I also played a while back on #FOREIGN9",
            attachments=(),
            timestamp=NOW,
        ),
    )

    asyncio.run(handlers.capture_candidate_thread_activity(
        event, bot=SimpleNamespace(), mongo=mongo,
    ))

    saved = mongo.tickets.documents[ticket["_id"]]
    assert saved["mentioned_tags"] == ["#FOREIGN9"]
    assert saved["player_tags"] == ["#ABC123"]


def test_candidate_activity_does_not_force_a_hub_redraw(monkeypatch):
    """A candidate's own message never moves the console's chart counts or
    the open-ticket set, so it must not force a full hub redraw the way a
    ticket create/decide/flag change does. See console._chart_signature."""
    ticket = _ticket()
    mongo = _mongo(ticket)
    calls = []

    async def notify(_bot, _mongo, _ticket_doc, *, reason, force=True):
        calls.append((reason, force))

    monkeypatch.setattr(handlers.thread_service, "notify_console_after_change", notify)

    event = SimpleNamespace(
        is_human=True,
        channel_id=ticket["location"]["id"],
        author_id=ticket["user_id"],
        message_id=9002,
        message=SimpleNamespace(
            content="Just checking in!",
            attachments=(),
            timestamp=NOW,
        ),
    )

    asyncio.run(handlers.capture_candidate_thread_activity(
        event, bot=SimpleNamespace(), mongo=mongo,
    ))

    assert calls == [("candidate activity", False)]


def test_blacklist_on_mentioned_tag_does_not_block_approval_or_console(monkeypatch):
    """(b) A blacklist flag keyed only to a mentioned tag blocks nothing."""
    ticket = _ticket()
    ticket["mentioned_tags"] = ["#FOREIGN9"]
    mongo = _mongo(ticket)
    mongo.ticket_flags = Collection([{
        "_id": "flag_foreign",
        "kind": flag_store.FLAG_BLACKLISTED,
        "active": True,
        "discord_ids": [],
        "player_tags": ["#FOREIGN9"],
        "rev": 0,
        "audit": [],
    }])

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#ABC123"),))

    async def deliver(*_args, **_kwargs):
        return None

    async def effects(_bot, _mongo, resolved):
        return store.Transition(store.WON, resolved)

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(console, "deliver_staff_identity_context", deliver)
    monkeypatch.setattr(resolve, "process_resolution_effects", effects)
    result = asyncio.run(resolve.approve_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99),
        actor_name="Recruiter",
        coc_client=object(),
    ))

    assert result.outcome == store.WON
    assert mongo.tickets.documents[ticket["_id"]]["status"] == "approved"

    # Sanity: the flag really is keyed to the mentioned tag, so it would have
    # matched had mentioned tags been used for identity.
    would_match = asyncio.run(flag_store.active_blacklist(
        mongo, user_id=ticket["user_id"], player_tags=ticket["mentioned_tags"],
    ))
    assert would_match is not None

    matching_flags = asyncio.run(flag_store.list_for_identity(
        mongo, discord_ids=ticket["user_id"], player_tags=ticket["player_tags"],
    ))
    assert matching_flags == []

    view = console.build_ticket_detail(
        ticket, action_id="z" * 32, flags=matching_flags, history=[],
    )
    buttons = [
        node for node in _nodes(view)
        if int(node.get("type", -1)) == int(hikari.ComponentType.BUTTON)
    ]
    approve = next(node for node in buttons if node.get("label") == "Approve")
    assert approve.get("disabled", False) is False


def test_reconcile_flag_identities_excludes_mentioned_tags(monkeypatch):
    """(c) Flag identity reconciliation never receives mentioned tags."""
    ticket = _ticket()
    ticket["mentioned_tags"] = ["#FOREIGN9"]
    mongo = _mongo(ticket)

    calls = []

    async def extend(_mongo, *, discord_ids, player_tags, source):
        calls.append(tuple(player_tags))
        return []

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#NEW123"),))

    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(flag_store, "extend_matching_flags", extend)

    asyncio.run(account_sync.sync_ticket_accounts(
        mongo, object(), ticket["_id"], source=account_sync.SOURCE_OPEN, now=NOW,
    ))

    assert calls
    for call_tags in calls:
        assert "#FOREIGN9" not in call_tags


def test_search_by_mentioned_tag_finds_the_ticket():
    """(d) Search matches a tag the applicant typed even though it is unverified."""
    ticket = _ticket()
    ticket["mentioned_tags"] = ["#FOREIGN9"]
    mongo = _mongo(ticket)

    results = asyncio.run(store.search(mongo, "#FOREIGN9"))

    assert [doc["_id"] for doc in results] == [ticket["_id"]]


def test_linked_account_tag_still_lands_in_player_tags_and_blocks_approval(monkeypatch):
    """(e) Linked-account sync tags remain verified identity and still block approval."""
    ticket = _ticket()
    mongo = _mongo(ticket)
    seen = []

    async def recruiter(*_args, **_kwargs):
        return True

    async def load(*_args, **_kwargs):
        return AccountsData(entries=(_linked_account("#NEW123"),))

    async def blacklist(_mongo, *, user_id, player_tags):
        seen.extend(player_tags)
        return {"_id": "flag_new"} if "#NEW123" in player_tags else None

    monkeypatch.setattr(resolve.perms, "is_recruiter", recruiter)
    monkeypatch.setattr(account_sync, "load_accounts", load)
    monkeypatch.setattr(resolve.flag_store, "active_blacklist", blacklist)
    result = asyncio.run(resolve.approve_ticket(
        object(),
        mongo,
        ticket_id=ticket["_id"],
        member=SimpleNamespace(id=99),
        actor_name="Recruiter",
        coc_client=object(),
    ))

    assert result.outcome == store.BLOCKED
    assert result.blocker == {"_id": "flag_new"}
    assert "#NEW123" in seen
    assert "#NEW123" in mongo.tickets.documents[ticket["_id"]]["player_tags"]

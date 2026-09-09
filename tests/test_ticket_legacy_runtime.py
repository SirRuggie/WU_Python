import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from extensions.commands import tickets_legacy
from extensions.commands.tickets_legacy import handlers
from extensions.components import registered_functions


LEGACY_ACTIONS = {
    "create_ticket",
    "deny_fwa_default",
    "deny_main_default",
    "deny_custom",
    "process_custom_denial",
    "ticket_override",
    "ticket_dashboard_action",
}


class _CreationCollection:
    def __init__(self, document):
        self.document = deepcopy(document)
        self.update_calls = []

    async def find_one(self, query):
        if self.document and query.get("_id") == self.document.get("_id"):
            return deepcopy(self.document)
        return None

    async def find_one_and_update(self, query, update, **_kwargs):
        self.update_calls.append((deepcopy(query), deepcopy(update)))
        if self.document is None:
            return None
        for key, expected in query.items():
            if self.document.get(key) != expected:
                return None
        self.document.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            self.document.pop(key, None)
        for key, amount in update.get("$inc", {}).items():
            self.document[key] = int(self.document.get(key, 0)) + int(amount)
        return deepcopy(self.document)


def _completed_legacy_creation(status="approved"):
    state = {
        "_id": "111:7:main",
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "state": "complete",
        "ticket_id": "ticket_444",
        "ticket_number": 10,
        "channel_id": 444,
        "thread_id": 445,
        "channel_name": "🆕main-10-candidate",
    }
    ticket = {
        "_id": "ticket_444",
        "guild_id": 111,
        "user_id": 7,
        "ticket_type": "main",
        "channel_id": 444,
        "status": status,
    }
    return state, ticket


@pytest.mark.parametrize("attempt_state", ["complete", "creating"])
def test_open_or_incomplete_legacy_attempt_still_blocks(monkeypatch, attempt_state):
    state, ticket = _completed_legacy_creation(status="open")
    state["state"] = attempt_state
    collection = _CreationCollection(state)

    async def no_index(_mongo):
        return None

    async def no_terminal(_mongo, _query):
        return None

    monkeypatch.setattr(handlers, "ensure_creation_index", no_index)
    monkeypatch.setattr(handlers.store, "find_one", no_terminal)
    won, blocked = asyncio.run(handlers.claim_ticket_creation(
        SimpleNamespace(ticket_creation_state=collection), 111, 7, "main",
    ))

    assert not won
    assert blocked["channel_id"] == 444
    assert collection.update_calls == []


def test_legacy_commands_and_persistent_actions_are_preserved():
    assert tickets_legacy.ticket.name == "ticket"
    assert {
        "setup", "config", "approve", "deny", "list", "dashboard",
        "reset-counter",
    } <= set(tickets_legacy.ticket.subcommands)
    assert LEGACY_ACTIONS <= set(registered_functions)
    for action_name in LEGACY_ACTIONS:
        assert "tickets_legacy" in registered_functions[action_name].declared_at


def test_main_explicitly_loads_both_ticket_runtimes_and_monitor():
    source = open("main.py", encoding="utf-8").read()
    assert '"extensions.commands.tickets_legacy"' in source
    assert '"extensions.commands.tickets"' in source
    assert '"extensions.events.channel.ticket_channel_monitor"' in source
    assert '"tickets_legacy"' in source

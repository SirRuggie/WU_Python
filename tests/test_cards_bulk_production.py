"""Production invariants for the exact-count bulk collection editor."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands import cards as cards_command
from utils import cards
from utils.todo_data import Account


_ABSENT = object()


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _nodes(components):
    return list(_walk([component.build() for component in components]))


def _text(components):
    return "\n".join(
        str(node["content"])
        for node in _nodes(components)
        if "content" in node
    )


def _custom_ids(components):
    return [
        str(node["custom_id"])
        for node in _nodes(components)
        if "custom_id" in node
    ]


def _field_value(document, path):
    current = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _ABSENT
        current = current[part]
    return current


def _matches_value(actual, expected):
    if not isinstance(expected, dict) or not any(
        str(key).startswith("$") for key in expected
    ):
        return actual is not _ABSENT and actual == expected
    for operator, operand in expected.items():
        if operator == "$exists":
            if (actual is not _ABSENT) != bool(operand):
                return False
        elif actual is _ABSENT:
            return False
        elif operator == "$lte" and not actual <= operand:
            return False
        elif operator == "$lt" and not actual < operand:
            return False
        elif operator == "$gte" and not actual >= operand:
            return False
        elif operator == "$gt" and not actual > operand:
            return False
        elif operator == "$in" and actual not in operand:
            return False
        elif operator not in {"$exists", "$lte", "$lt", "$gte", "$gt", "$in"}:
            raise AssertionError(f"unsupported fake query operator: {operator}")
    return True


def _matches(document, query):
    for field, expected in query.items():
        if field == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
        elif field == "$and":
            if not all(_matches(document, branch) for branch in expected):
                return False
        elif not _matches_value(_field_value(document, field), expected):
            return False
    return True


def _set_field(document, path, value):
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = deepcopy(value)


def _unset_field(document, path):
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.get(part)
        if not isinstance(target, dict):
            return
    target.pop(parts[-1], None)


def _apply_update(document, update):
    for path, value in update.get("$set", {}).items():
        _set_field(document, path, value)
    for path, value in update.get("$setOnInsert", {}).items():
        if _field_value(document, path) is _ABSENT:
            _set_field(document, path, value)
    for path, value in update.get("$inc", {}).items():
        current = _field_value(document, path)
        _set_field(document, path, (0 if current is _ABSENT else current) + value)
    for path in update.get("$unset", {}):
        _unset_field(document, path)
    for path in update.get("$unset", {}):
        target = document
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.get(part, {})
        target.pop(parts[-1], None)
    for path, operation in update.get("$addToSet", {}).items():
        values = operation.get("$each", ()) if isinstance(operation, dict) else (operation,)
        stored = _field_value(document, path)
        current = [] if stored is _ABSENT else list(stored)
        for value in values:
            if value not in current:
                current.append(value)
        _set_field(document, path, current)
    for path, condition in update.get("$pull", {}).items():
        current = _field_value(document, path)
        if not isinstance(current, list):
            continue
        rejected = set(condition.get("$in", ())) if isinstance(condition, dict) else {condition}
        _set_field(document, path, [value for value in current if value not in rejected])


class _Collection:
    def __init__(self, documents=()):
        self.documents = {
            document["_id"]: deepcopy(document) for document in documents
        }
        self.updates = []
        self.before_update = None

    async def find_one(self, query, projection=None):
        found = next(
            (document for document in self.documents.values() if _matches(document, query)),
            None,
        )
        if found is None:
            return None
        if projection and projection.get("_id") == 0:
            return {key: deepcopy(value) for key, value in found.items() if key != "_id"}
        return found

    async def insert_one(self, document):
        self.documents[document["_id"]] = deepcopy(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update, upsert=False):
        self.updates.append((deepcopy(query), deepcopy(update), upsert))
        if self.before_update is not None:
            callback, self.before_update = self.before_update, None
            callback(self, query, update)
        found = await self.find_one(query)
        if found is None and upsert:
            found = {"_id": query["_id"]}
            self.documents[found["_id"]] = found
        if found is None:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        _apply_update(found, update)
        return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

    async def delete_one(self, query):
        found = await self.find_one(query)
        if found is None:
            return SimpleNamespace(deleted_count=0)
        self.documents.pop(found["_id"], None)
        return SimpleNamespace(deleted_count=1)


def _account():
    return Account(
        tag="#ME",
        name="Member",
        clan_tag="#HOME",
        clan_name="Home Clan",
        town_hall=18,
    )


def _inventory(*, revision=7, complete=("elixir",)):
    values = {card.id: cards.OWNED for card in cards.CARDS}
    values["wizard"] = cards.DUPLICATE
    return {
        "_id": "#ME",
        "discord_id": 123,
        "guild_id": 1,
        "inventory_revision": revision,
        "cards": values,
        "complete_categories": list(complete),
        "reviewed_lists": [],
        # Wizard is an ordinary scanner 2+: trusted spare information whose
        # exact count is unknown. Minion is the separate hidden-badge case.
        "scan_duplicate_unverified_card_ids": ["minion"],
        "count_confirmed_card_ids": [],
        "confirmed_at": datetime.now(timezone.utc),
    }


def _mongo(document=None):
    inventory = document or _inventory()
    return SimpleNamespace(
        card_inventories=_Collection([inventory]),
        component_state=_Collection(),
        button_store=_Collection(),
    )


def _stored_inventory(mongo):
    return mongo.card_inventories.documents["#ME"]


def _reserve(document, *card_ids):
    document["card_trade_reservations"] = {
        card_id: {"owner": f"trade:{card_id}"} for card_id in card_ids
    }
    return document


def _bulk_state(
    *,
    selected=(),
    next_index=0,
    phase="select",
    nonce="nonce_a",
    revision=7,
    expires_at=None,
):
    editable = [card.id for card in cards.CATEGORY_CARDS["elixir"]]
    counts = {card_id: cards.OWNED for card_id in editable}
    counts["wizard"] = cards.DUPLICATE
    return {
        "type": "cards_bulk_edit",
        "user_id": 123,
        "guild_id": 1,
        "account_tag": "#ME",
        "account_name": "Member",
        "category_id": "elixir",
        "editable_ids": editable,
        "count_snapshot": counts,
        "unconfirmed_ids": ["wizard"],
        "selected_ids": list(selected),
        "next_index": next_index,
        "expected_revision": revision,
        "processed_count": next_index,
        "written_count": next_index,
        "phase": phase,
        "nonce": nonce,
        "expires_at": expires_at or datetime.now(timezone.utc) + timedelta(minutes=30),
        "component_state": True,
    }


def _state_id():
    return "cards_bulk_token|ME|elixir"


def _put_state(mongo, state, *, state_id=None):
    state_id = state_id or _state_id()
    mongo.component_state.documents[state_id] = {"_id": state_id, **deepcopy(state)}
    return state_id


def _state_kwargs(mongo, state_id=None):
    document = mongo.component_state.documents[state_id or _state_id()]
    return {key: deepcopy(value) for key, value in document.items() if key != "_id"}


def _scan_finish_case(
    unresolved,
    *,
    inventory_revision=7,
    state_revision=None,
    reserved=(),
):
    """Build one canonical cross-category scanner-finish session."""
    unresolved = list(unresolved)
    document = _inventory(revision=inventory_revision, complete=())
    trusted, ready, reviewed = cards_command._trust_projection(
        {"trusted_card_ids": []},
        add=[card.id for card in cards.CARDS if card.id not in unresolved],
    )
    document.update({
        "trusted_card_ids": trusted,
        "complete_categories": ready,
        "reviewed_lists": reviewed,
        "scan_duplicate_unverified_card_ids": [],
    })
    if reserved:
        _reserve(document, *reserved)
    mongo = _mongo(document)
    state = _bulk_state(
        selected=unresolved,
        phase="continue",
        revision=(
            inventory_revision if state_revision is None else state_revision
        ),
    )
    state.update({
        "scope": "scan_finish",
        "category_id": cards.CARD_BY_ID[unresolved[0]].category,
        "editable_ids": unresolved,
        "count_snapshot": {
            card_id: document["cards"].get(card_id, cards.OWNED)
            for card_id in unresolved
        },
        "unconfirmed_ids": [],
        "required_entry_ids": unresolved,
    })
    state_id = cards_command._bulk_state_id(
        "#ME", state["category_id"], scope="scan_finish"
    )
    _put_state(mongo, state, state_id=state_id)
    return mongo, state, state_id


def _fake_load_target(mongo):
    account = _account()

    async def load_target(*_args, **_kwargs):
        return account, mongo.card_inventories.documents["#ME"], None

    return load_target


class _OpenCtx:
    def __init__(self, *, values=(), user_id=123, guild_id=1):
        self.user = SimpleNamespace(id=user_id)
        self.guild_id = guild_id
        self.interaction = SimpleNamespace(values=list(values))
        self.opened = None
        self.responses = []

    async def respond_with_modal(self, **kwargs):
        self.opened = kwargs

    async def respond(self, **kwargs):
        self.responses.append(kwargs)


class _SubmitCtx:
    def __init__(self, fields, *, user_id=123, guild_id=1):
        self.user = SimpleNamespace(id=user_id)
        self.guild_id = guild_id
        self.sequence = []
        self.edited = None
        self.responses = []
        self.interaction = SimpleNamespace(
            components=[
                [SimpleNamespace(custom_id=custom_id, value=value)]
                for custom_id, value in fields.items()
            ],
            message=SimpleNamespace(id=42),
            create_initial_response=self._ack,
            edit_initial_response=self._edit,
        )

    async def _ack(self, response_type, **_kwargs):
        self.sequence.append(("ack", response_type))

    async def _edit(self, components=None, **_kwargs):
        self.sequence.append("edit")
        self.edited = components

    async def defer(self, *_args, **_kwargs):
        self.sequence.append("defer")

    async def respond(self, **kwargs):
        self.responses.append(kwargs)


def test_bulk_session_contract_is_two_hours():
    assert cards_command.CARD_BULK_SESSION_FOR == timedelta(hours=2)


def test_exact_batch_writes_only_explicit_fields_and_preserves_ready_and_two_plus():
    source = _inventory()
    untouched = source["cards"]["giant"]
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_exact_card_batch(
        mongo,
        _account(),
        source,
        ["barbarian", "archer", "wizard"],
        {"barbarian": 0, "archer": 4},
        expected_revision=7,
        discord_id=123,
        guild_id=1,
    ))

    assert updated["cards"]["barbarian"] == 0
    assert updated["cards"]["archer"] == 4
    assert updated["cards"]["wizard"] == cards.DUPLICATE
    assert updated["cards"]["giant"] == untouched
    assert updated["count_confirmed_card_ids"] == ["barbarian", "archer"]
    assert updated["scan_duplicate_unverified_card_ids"] == ["minion"]
    assert updated["inventory_revision"] == 8
    assert updated["complete_categories"] == ["elixir"]
    update = mongo.card_inventories.updates[-1][1]
    assert {
        path for path in update["$set"] if path.startswith("cards.")
    } == {"cards.barbarian", "cards.archer"}


def test_an_explicit_two_confirms_a_scanner_two_plus():
    source = _inventory()
    source["trusted_card_ids"] = [
        card.id for card in cards.CATEGORY_CARDS["elixir"]
    ]
    source["scan_duplicate_unverified_card_ids"] = ["minion"]
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

    assert "wizard" in cards_command._trusted_card_ids(source)
    assert cards_command._inventory_board_values(source)["wizard"] == (
        cards_command.SPARE_FLOOR
    )

    updated = asyncio.run(cards_command._write_exact_card_batch(
        mongo,
        _account(),
        source,
        ["wizard"],
        {"wizard": 2},
        expected_revision=7,
        discord_id=123,
        guild_id=1,
    ))

    assert updated["cards"]["wizard"] == 2
    assert "wizard" in updated["trusted_card_ids"]
    assert "wizard" in updated["count_confirmed_card_ids"]
    assert "wizard" not in updated["scan_duplicate_unverified_card_ids"]
    assert "elixir" in updated["complete_categories"]
    assert cards_command._inventory_board_values(updated)["wizard"] == 2
    assert updated["inventory_revision"] == 8


def test_an_all_blank_two_plus_batch_is_a_guarded_noop():
    source = _inventory()
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_exact_card_batch(
        mongo,
        _account(),
        source,
        ["wizard"],
        {},
        expected_revision=7,
        discord_id=123,
        guild_id=1,
    ))

    assert updated["inventory_revision"] == 7
    assert updated["count_confirmed_card_ids"] == []
    assert updated["scan_duplicate_unverified_card_ids"] == ["minion"]
    assert mongo.card_inventories.updates == []


def test_blank_is_rejected_for_an_exact_card_instead_of_silently_skipping_it():
    source = _inventory()
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

    with pytest.raises(cards_command.InventoryWriteConflict):
        asyncio.run(cards_command._write_exact_card_batch(
            mongo,
            _account(),
            source,
            ["barbarian"],
            {},
            expected_revision=7,
            discord_id=123,
            guild_id=1,
        ))

    assert _stored_inventory(mongo)["inventory_revision"] == 7
    assert mongo.card_inventories.updates == []


def test_exact_batch_rejects_revision_conflict_without_a_partial_write():
    source = _inventory(revision=8)
    before = deepcopy(source)
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

    with pytest.raises(cards_command.InventoryWriteConflict):
        asyncio.run(cards_command._write_exact_card_batch(
            mongo,
            _account(),
            source,
            ["barbarian", "archer"],
            {"barbarian": 0, "archer": 5},
            expected_revision=7,
            discord_id=123,
            guild_id=1,
        ))

    assert _stored_inventory(mongo) == before
    assert mongo.card_inventories.updates == []


def test_reservation_in_the_batch_blocks_every_field_but_an_unselected_one_does_not():
    blocked = _reserve(_inventory(), "archer")
    blocked_before = deepcopy(blocked)
    blocked_mongo = _mongo(blocked)
    cards_command._inventory_locks.clear()

    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_exact_card_batch(
            blocked_mongo,
            _account(),
            blocked,
            ["barbarian", "archer"],
            {"barbarian": 0, "archer": 5},
            expected_revision=7,
            discord_id=123,
            guild_id=1,
        ))
    assert _stored_inventory(blocked_mongo) == blocked_before

    allowed = _reserve(_inventory(), "giant")
    allowed_mongo = _mongo(allowed)
    cards_command._inventory_locks.clear()
    updated = asyncio.run(cards_command._write_exact_card_batch(
        allowed_mongo,
        _account(),
        allowed,
        ["barbarian", "archer"],
        {"barbarian": 0, "archer": 5},
        expected_revision=7,
        discord_id=123,
        guild_id=1,
    ))
    assert updated["cards"]["barbarian"] == 0
    assert updated["cards"]["giant"] == cards.OWNED


def test_reservation_acquired_between_reload_and_update_loses_the_atomic_race():
    source = _inventory()
    mongo = _mongo(source)
    before = deepcopy(_stored_inventory(mongo))

    def reserve_archer(collection, _query, _update):
        collection.documents["#ME"]["card_trade_reservations"] = {
            "archer": {"owner": "trade:late"},
        }

    mongo.card_inventories.before_update = reserve_archer
    cards_command._inventory_locks.clear()

    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_exact_card_batch(
            mongo,
            _account(),
            source,
            ["barbarian", "archer"],
            {"barbarian": 0, "archer": 5},
            expected_revision=7,
            discord_id=123,
            guild_id=1,
        ))

    stored = _stored_inventory(mongo)
    assert stored["cards"] == before["cards"]
    assert stored["inventory_revision"] == before["inventory_revision"]


def test_exact_batch_requires_one_canonical_category_batch_of_at_most_five():
    source = _inventory()
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

    bad_batches = [
        [],
        ["archer", "barbarian"],
        ["barbarian", "barbarian"],
        [card.id for card in cards.CATEGORY_CARDS["elixir"][:6]],
        ["barbarian", "minion"],
    ]
    for batch in bad_batches:
        with pytest.raises(ValueError):
            asyncio.run(cards_command._write_exact_card_batch(
                mongo,
                _account(),
                source,
                batch,
                {card_id: 1 for card_id in batch},
                expected_revision=7,
                discord_id=123,
                guild_id=1,
            ))
    assert mongo.card_inventories.updates == []


def test_exact_batches_project_trust_and_ready_only_after_the_final_card():
    category_ids = [card.id for card in cards.CATEGORY_CARDS["elixir"]]
    first, final = category_ids[:2]
    source = _inventory(complete=())
    source["trusted_card_ids"] = category_ids[2:]
    source["reviewed_lists"] = []
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

    after_first = asyncio.run(cards_command._write_exact_card_batch(
        mongo,
        _account(),
        source,
        [first],
        {first: 4},
        expected_revision=7,
        discord_id=123,
        guild_id=1,
    ))

    assert first in after_first["trusted_card_ids"]
    assert final not in after_first["trusted_card_ids"]
    assert "elixir" not in after_first["complete_categories"]
    assert "elixir:missing" not in after_first["reviewed_lists"]

    completed = asyncio.run(cards_command._write_exact_card_batch(
        mongo,
        _account(),
        after_first,
        [final],
        {final: 0},
        expected_revision=8,
        discord_id=123,
        guild_id=1,
    ))

    assert set(category_ids) <= set(completed["trusted_card_ids"])
    assert "elixir" in completed["complete_categories"]
    assert {"elixir:missing", "elixir:duplicates"} <= set(
        completed["reviewed_lists"]
    )
    assert completed["inventory_revision"] == 9


def test_cross_category_exact_batch_requires_an_explicit_canonical_scope():
    boundary = [
        cards.CATEGORY_CARDS["elixir"][-1].id,
        cards.CATEGORY_CARDS["dark_elixir"][0].id,
    ]
    source = _inventory(complete=())
    source["trusted_card_ids"] = [
        card.id for card in cards.CARDS if card.id not in boundary
    ]
    source["reviewed_lists"] = []
    blocked = _mongo(source)
    cards_command._inventory_locks.clear()

    with pytest.raises(ValueError):
        asyncio.run(cards_command._write_exact_card_batch(
            blocked,
            _account(),
            source,
            boundary,
            {boundary[0]: 2, boundary[1]: 3},
            expected_revision=7,
            discord_id=123,
            guild_id=1,
        ))
    assert blocked.card_inventories.updates == []

    allowed = _mongo(source)
    cards_command._inventory_locks.clear()
    updated = asyncio.run(cards_command._write_exact_card_batch(
        allowed,
        _account(),
        source,
        boundary,
        {boundary[0]: 2, boundary[1]: 3},
        expected_revision=7,
        discord_id=123,
        guild_id=1,
        allowed_ids=boundary,
    ))

    assert [updated["cards"][card_id] for card_id in boundary] == [2, 3]
    assert set(boundary) <= set(updated["trusted_card_ids"])
    assert {"elixir", "dark_elixir"} <= set(updated["complete_categories"])
    assert updated["inventory_revision"] == 8


def test_cross_category_scope_keeps_revision_and_reservation_guards():
    boundary = [
        cards.CATEGORY_CARDS["elixir"][-1].id,
        cards.CATEGORY_CARDS["dark_elixir"][0].id,
    ]
    base = _inventory(complete=())
    base["trusted_card_ids"] = [
        card.id for card in cards.CARDS if card.id not in boundary
    ]
    values = {boundary[0]: 3, boundary[1]: 4}

    reserved = _reserve(deepcopy(base), boundary[1])
    reserved_before = deepcopy(reserved)
    reserved_mongo = _mongo(reserved)
    cards_command._inventory_locks.clear()
    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_exact_card_batch(
            reserved_mongo,
            _account(),
            reserved,
            boundary,
            values,
            expected_revision=7,
            discord_id=123,
            guild_id=1,
            allowed_ids=boundary,
        ))
    assert _stored_inventory(reserved_mongo) == reserved_before

    stale = deepcopy(base)
    stale["inventory_revision"] = 8
    stale_before = deepcopy(stale)
    stale_mongo = _mongo(stale)
    cards_command._inventory_locks.clear()
    with pytest.raises(cards_command.InventoryWriteConflict):
        asyncio.run(cards_command._write_exact_card_batch(
            stale_mongo,
            _account(),
            stale,
            boundary,
            values,
            expected_revision=7,
            discord_id=123,
            guild_id=1,
            allowed_ids=boundary,
        ))
    assert _stored_inventory(stale_mongo) == stale_before


def test_category_bulk_controls_keep_reserved_cards_visible_but_not_selectable():
    account = _account()
    document = _reserve(_inventory(), "archer", "wizard")
    state_id = "cards_bulk_token|ME|elixir"
    view = cards_command._quantity_editor(
        account,
        document,
        "elixir",
        bulk_state_id=state_id,
    )
    nodes = _nodes(view)
    bulk = next(
        node for node in nodes
        if str(node.get("custom_id", "")).startswith("cards_bulk_select:")
    )
    option_ids = [str(option["value"]) for option in bulk["options"]]
    expected = [
        card.id for card in cards.CATEGORY_CARDS["elixir"]
        if card.id not in {"archer", "wizard"}
    ]

    assert option_ids == expected
    assert bulk["min_values"] == 1
    assert bulk["max_values"] == len(expected)
    rendered = _text(view)
    assert "Archer" in rendered and "Wizard" in rendered
    assert rendered.count("in a trade") >= 2
    assert "Member" in rendered and "#ME" in rendered
    assert f"cards_bulk_edit_all:{state_id}" in _custom_ids(view)

    # The existing one-card editor is a frozen fallback and retains every card.
    single = next(
        node for node in nodes
        if str(node.get("custom_id", "")).startswith("cards_qpick:")
    )
    assert [str(option["value"]) for option in single["options"]] == [
        card.id for card in cards.CATEGORY_CARDS["elixir"]
    ]
    assert "cards_qpick:#ME|elixir" in _custom_ids(view)


def test_category_bulk_component_budget_and_discord_limits_hold_in_the_worst_shape():
    account = _account()
    inventory = _reserve(_inventory(complete=()), "wizard")
    # A selected, scanner-unconfirmed, reserved card draws every existing
    # single-editor affordance plus its lock note alongside the bulk controls.
    view = cards_command._quantity_editor(
        account,
        inventory,
        "elixir",
        card_id="wizard",
        saved="Five cards updated.",
        bulk_state_id="cards_bulk_token|ME|elixir",
    )
    nodes = _nodes(view)
    component_count = len([node for node in nodes if "type" in node])
    custom_ids = [str(node["custom_id"]) for node in nodes if "custom_id" in node]

    assert component_count <= 34
    assert len(custom_ids) == len(set(custom_ids))
    assert all(len(custom_id) <= 100 for custom_id in custom_ids)
    bulk = next(
        node for node in nodes
        if str(node.get("custom_id", "")).startswith("cards_bulk_select:")
    )
    assert len(bulk["options"]) == 18
    assert len(bulk["options"]) <= 25
    assert bulk["max_values"] == 18


def test_all_reserved_category_omits_invalid_bulk_components_and_keeps_single_editor():
    inventory = _reserve(
        _inventory(),
        *(card.id for card in cards.CATEGORY_CARDS["elixir"]),
    )
    view = cards_command._quantity_editor(
        _account(),
        inventory,
        "elixir",
        bulk_state_id="cards_bulk_token|ME|elixir",
    )
    ids = _custom_ids(view)

    assert not any(custom_id.startswith("cards_bulk_select:") for custom_id in ids)
    assert not any(custom_id.startswith("cards_bulk_edit_all:") for custom_id in ids)
    assert "cards_qpick:#ME|elixir" in ids
    assert "none can be changed" in _text(view)


def test_category_view_creates_an_owner_bound_two_hour_session(monkeypatch):
    captured = {}

    async def insert_state(_mongo, document, *, ttl):
        captured["document"] = deepcopy(document)
        captured["ttl"] = ttl
        return SimpleNamespace(inserted_id=document["_id"])

    monkeypatch.setattr(cards_command, "insert_state", insert_state)
    document = _reserve(_inventory(), "archer")
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    view = asyncio.run(cards_command._quantity_editor_view(
        ctx,
        _account(),
        document,
        "elixir",
        mongo=SimpleNamespace(),
    ))

    state = captured["document"]
    expected_editable = [
        card.id for card in cards.CATEGORY_CARDS["elixir"]
        if card.id != "archer"
    ]
    assert captured["ttl"] == timedelta(hours=2)
    assert state["type"] == "cards_bulk_edit"
    assert state["user_id"] == 123 and state["guild_id"] == 1
    assert state["account_tag"] == "#ME" and state["category_id"] == "elixir"
    assert state["editable_ids"] == expected_editable
    assert list(state["count_snapshot"]) == expected_editable
    assert state["unconfirmed_ids"] == ["wizard"]
    assert state["expected_revision"] == 7
    assert state["phase"] == "select" and state["next_index"] == 0
    assert any(custom_id.startswith("cards_bulk_select:") for custom_id in _custom_ids(view))


def test_scan_finish_state_is_preselected_global_required_and_two_hours():
    remaining = [card.id for card in cards.CARDS[10:28]]
    source = _inventory(complete=())
    trusted, ready, reviewed = cards_command._trust_projection(
        {"trusted_card_ids": []},
        add=[card.id for card in cards.CARDS if card.id not in remaining],
    )
    source.update({
        "trusted_card_ids": trusted,
        "complete_categories": ready,
        "reviewed_lists": reviewed,
        "scan_duplicate_unverified_card_ids": [],
    })
    mongo = _mongo(source)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    state_id, state = asyncio.run(cards_command._create_bulk_state(
        ctx,
        _account(),
        source,
        mongo=mongo,
        category_id=cards.CARD_BY_ID[remaining[0]].category,
        scope="scan_finish",
        selected_ids=remaining,
    ))

    assert state_id is not None and state_id.startswith("cards_finish_")
    stored = mongo.component_state.documents[state_id]
    assert stored["scope"] == "scan_finish"
    assert stored["editable_ids"] == remaining
    assert stored["selected_ids"] == remaining
    assert stored["required_entry_ids"] == remaining
    assert stored["unconfirmed_ids"] == []
    assert stored["phase"] == "continue"
    assert stored["expected_revision"] == 7
    assert stored["expires_at"] > datetime.now(timezone.utc) + timedelta(
        hours=1, minutes=59
    )
    assert cards_command._bulk_state_well_formed(stored)


def test_scan_finish_modal_batches_are_global_blank_required_five_five_five_three():
    selected = [card.id for card in cards.CARDS[10:28]]
    state = _bulk_state(selected=selected, phase="continue")
    state.update({
        "scope": "scan_finish",
        "category_id": cards.CARD_BY_ID[selected[0]].category,
        "editable_ids": selected,
        "count_snapshot": {card_id: cards.OWNED for card_id in selected},
        "unconfirmed_ids": [],
        "required_entry_ids": selected,
    })
    state_id = cards_command._bulk_state_id(
        "#ME", state["category_id"], scope="scan_finish"
    )
    sizes = []
    seen_labels = []

    for start in range(0, len(selected), 5):
        state["next_index"] = start
        modal = cards_command._bulk_exact_modal(state_id, state)
        fields = [
            node for node in _nodes(modal["components"])
            if node.get("type") == int(hikari.ComponentType.TEXT_INPUT)
        ]
        sizes.append(len(fields))
        seen_labels.extend(str(field["label"]) for field in fields)
        assert "Finish collection" in modal["title"]
        assert all(field["required"] is True for field in fields)
        assert all("value" not in field for field in fields)

    assert sizes == [5, 5, 5, 3]
    assert len(seen_labels) == len(selected)


def test_scan_finish_handoff_is_scoped_and_has_no_ready_confirmation_step():
    selected = [card.id for card in cards.CARDS[10:28]]
    state = _bulk_state(selected=selected, phase="continue")
    state.update({
        "scope": "scan_finish",
        "category_id": cards.CARD_BY_ID[selected[0]].category,
        "editable_ids": selected,
        "count_snapshot": {card_id: cards.OWNED for card_id in selected},
        "unconfirmed_ids": [],
        "required_entry_ids": selected,
    })
    state_id = cards_command._bulk_state_id(
        "#ME", state["category_id"], scope="scan_finish"
    )

    view = cards_command._scan_finish_view(state_id, state, read_count=42)

    rendered = _text(view)
    assert "# Scan finished" in rendered
    assert "42 of 60 cards read." in rendered
    assert "18 still need a count." in rendered
    assert "Finish these cards to complete your collection." in rendered
    assert "Ready to trade" not in rendered
    assert _custom_ids(view) == [
        f"cards_bulk_continue:{state_id}",
        f"cards_bulk_finish:{state_id}",
    ]
    assert all(len(custom_id) <= 100 for custom_id in _custom_ids(view))
    assert [
        str(node["label"])
        for node in _nodes(view)
        if "label" in node and "custom_id" in node
    ] == ["Enter counts", "Finish later"]


def test_bulk_state_id_retains_only_the_expiry_recovery_target():
    state_id = cards_command._bulk_state_id("#ME", "elixir")

    assert state_id.startswith("cards_bulk_")
    assert len(state_id) < 100
    assert cards_command._bulk_state_target(state_id) == ("#ME", "elixir")
    assert cards_command._bulk_state_target("broken") == ("", None)


def test_category_session_storage_failure_falls_back_to_the_single_editor(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("state storage unavailable")

    monkeypatch.setattr(cards_command, "insert_state", unavailable)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(cards_command._quantity_editor_view(
        ctx,
        _account(),
        _inventory(),
        "elixir",
        mongo=SimpleNamespace(),
    ))
    ids = _custom_ids(view)

    assert not any(custom_id.startswith("cards_bulk_") for custom_id in ids)
    assert "cards_qpick:#ME|elixir" in ids


@pytest.mark.parametrize(
    ("total", "sizes"),
    [
        (1, [1]),
        (5, [5]),
        (6, [5, 1]),
        (10, [5, 5]),
        (19, [5, 5, 5, 4]),
    ],
)
def test_exact_modal_partition_is_one_to_five_fields(total, sizes):
    selected = [card.id for card in cards.CATEGORY_CARDS["elixir"][:total]]
    seen = []
    for start, expected_size in zip(range(0, total, 5), sizes):
        state = _bulk_state(selected=selected, next_index=start)
        modal = cards_command._bulk_exact_modal(_state_id(), state)
        fields = [
            node for node in _nodes(modal["components"])
            if node.get("type") == int(hikari.ComponentType.TEXT_INPUT)
        ]
        assert len(modal["components"]) == expected_size
        assert len(fields) == expected_size
        assert [str(field["custom_id"]) for field in fields] == [
            f"q_nonce_a_{offset}" for offset in range(expected_size)
        ]
        assert len(modal["title"]) <= 45
        assert len(modal["custom_id"]) <= 100
        seen.extend(selected[start:start + expected_size])
    assert seen == selected


def test_scanner_two_plus_modal_is_optional_blank_but_numeric_two_is_exact():
    state = _bulk_state(selected=["wizard"])
    modal = cards_command._bulk_exact_modal(_state_id(), state)
    field = next(
        node for node in _nodes(modal["components"])
        if node.get("type") == int(hikari.ComponentType.TEXT_INPUT)
    )
    assert field["required"] is False
    assert "2+" in field["placeholder"]
    assert "value" not in field

    blank, problem = cards_command._bulk_modal_values(
        _SubmitCtx({"q_nonce_a_0": ""}), state
    )
    assert blank == {} and problem is None
    explicit, problem = cards_command._bulk_modal_values(
        _SubmitCtx({"q_nonce_a_0": "2"}), state
    )
    assert explicit == {"wizard": 2} and problem is None


def test_hidden_badge_uncertainty_is_required_in_finish_not_optional_two_plus():
    hidden = "minion"
    source = _inventory(complete=())
    trusted, ready, reviewed = cards_command._trust_projection(
        {"trusted_card_ids": []},
        add=[card.id for card in cards.CARDS if card.id != hidden],
    )
    source.update({
        "trusted_card_ids": trusted,
        "complete_categories": ready,
        "reviewed_lists": reviewed,
        "scan_duplicate_unverified_card_ids": [hidden],
    })
    mongo = _mongo(source)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    state_id, state = asyncio.run(cards_command._create_bulk_state(
        ctx,
        _account(),
        source,
        mongo=mongo,
        category_id=cards.CARD_BY_ID[hidden].category,
        scope="scan_finish",
        selected_ids=cards_command._untrusted_card_ids(source),
    ))

    assert state["selected_ids"] == [hidden]
    assert state["required_entry_ids"] == [hidden]
    assert state["unconfirmed_ids"] == []
    modal = cards_command._bulk_exact_modal(state_id, state)
    field = next(
        node for node in _nodes(modal["components"])
        if node.get("type") == int(hikari.ComponentType.TEXT_INPUT)
    )
    assert field["required"] is True
    assert "value" not in field
    assert "leave blank" not in str(field.get("placeholder", ""))


def test_selection_normalizes_to_catalog_order_and_slides_expiry():
    selected = [card.id for card in cards.CATEGORY_CARDS["elixir"][:6]]
    state = _bulk_state()
    old_expiry = state["expires_at"]
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    ctx = _OpenCtx(values=reversed(selected))

    asyncio.run(cards_command.cards_bulk_select(
        ctx,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    stored = mongo.component_state.documents[state_id]
    assert stored["selected_ids"] == selected
    assert stored["expires_at"] > old_expiry + timedelta(hours=1)
    assert ctx.opened is not None and ctx.responses == []
    assert len(ctx.opened["components"]) == 5
    assert ctx.opened["custom_id"] == f"cards_bulk_submit:{state_id}"


def test_edit_all_bypasses_selection_and_targets_all_nineteen():
    state = _bulk_state()
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    ctx = _OpenCtx()

    asyncio.run(cards_command.cards_bulk_edit_all(
        ctx,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert mongo.component_state.documents[state_id]["selected_ids"] == [
        card.id for card in cards.CATEGORY_CARDS["elixir"]
    ]
    assert len(ctx.opened["components"]) == 5
    assert "1-5 of 19" in ctx.opened["title"]


def test_edit_all_counts_four_autosaved_batches_complete_a_new_category(monkeypatch):
    category_ids = [card.id for card in cards.CATEGORY_CARDS["elixir"]]
    source = _inventory(complete=())
    trusted, ready, reviewed = cards_command._trust_projection(
        {"trusted_card_ids": []},
        add=[card.id for card in cards.CARDS if card.id not in category_ids],
    )
    source.update({
        "trusted_card_ids": trusted,
        "complete_categories": ready,
        "reviewed_lists": reviewed,
        "scan_duplicate_unverified_card_ids": [],
    })
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()
    state = _bulk_state()
    state.update({"scope": "category", "required_entry_ids": []})
    state_id = _put_state(mongo, state)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    opened = _OpenCtx()

    asyncio.run(cards_command.cards_bulk_edit_all(
        opened,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert mongo.component_state.documents[state_id]["selected_ids"] == category_ids
    submitted_batches = 0
    final_view = None
    while state_id in mongo.component_state.documents:
        current = _state_kwargs(mongo, state_id)
        batch = current["selected_ids"][
            current["next_index"]:current["next_index"] + 5
        ]
        submit = _SubmitCtx({
            f"q_{current['nonce']}_{offset}": "1"
            for offset in range(len(batch))
        })
        asyncio.run(cards_command.cards_bulk_submit(
            submit,
            state_id,
            coc_client=SimpleNamespace(),
            mongo=mongo,
            **current,
        ))
        submitted_batches += 1
        final_view = submit.edited
        if state_id not in mongo.component_state.documents:
            break
        continued = _OpenCtx()
        progressed = _state_kwargs(mongo, state_id)
        asyncio.run(cards_command.cards_bulk_continue(
            continued,
            state_id,
            coc_client=SimpleNamespace(),
            mongo=mongo,
            **progressed,
        ))
        assert continued.opened is not None

    completed = _stored_inventory(mongo)
    assert submitted_batches == 4
    assert completed["inventory_revision"] == 11
    assert set(category_ids) <= set(completed["trusted_card_ids"])
    assert set(category_ids) <= set(completed["count_confirmed_card_ids"])
    assert "elixir" in completed["complete_categories"]
    assert {"elixir:missing", "elixir:duplicates"} <= set(
        completed["reviewed_lists"]
    )
    assert "Ready to trade." in _text(final_view)
    assert not any(
        custom_id.startswith("cards_ready:") for custom_id in _custom_ids(final_view)
    )


def test_sliding_cas_cannot_revive_an_expired_row():
    expired = _bulk_state(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    mongo = _mongo()
    state_id = _put_state(mongo, expired)

    result = asyncio.run(cards_command._bulk_state_update(
        mongo,
        state_id,
        expired,
        guard={"phase": "select", "nonce": "nonce_a"},
        values={"nonce": "nonce_b"},
    ))

    assert result.matched_count == 0
    # update_state's legacy fallback asks get_state whether this was a migrated
    # panel; get_state synchronously removes the expired exact row. Either way,
    # the session was not revived and no caller transition was applied.
    assert state_id not in mongo.component_state.documents


def test_first_batch_autosaves_then_finish_keeps_it_and_leaves_the_rest(monkeypatch):
    selected = [card.id for card in cards.CATEGORY_CARDS["elixir"][:6]]
    state = _bulk_state(selected=selected)
    old_expiry = state["expires_at"]
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    fields = {
        f"q_nonce_a_{offset}": str(value)
        for offset, value in enumerate((0, 2, 3, 4, 5))
    }
    submit = _SubmitCtx(fields)

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    inventory = _stored_inventory(mongo)
    assert [inventory["cards"][item_id] for item_id in selected[:5]] == [0, 2, 3, 4, 5]
    assert inventory["cards"][selected[5]] == cards.OWNED
    assert inventory["inventory_revision"] == 8
    progressed = mongo.component_state.documents[state_id]
    assert progressed["phase"] == "continue"
    assert progressed["next_index"] == 5
    assert progressed["processed_count"] == 5
    assert progressed["written_count"] == 5
    assert progressed["expected_revision"] == 8
    assert "writing_started_at" not in progressed
    assert progressed["expires_at"] > old_expiry + timedelta(hours=1)
    assert submit.sequence[0] == (
        "ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    assert "Submitted batches are already saved" in _text(submit.edited)
    assert "1 remaining" in _text(submit.edited)

    finish = _SubmitCtx({})
    asyncio.run(cards_command.cards_bulk_finish(
        finish,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **_state_kwargs(mongo, state_id),
    ))

    assert inventory["cards"][selected[5]] == cards.OWNED
    assert inventory["inventory_revision"] == 8
    assert state_id not in mongo.component_state.documents
    assert "5 exact counts were saved" in _text(finish.edited)
    assert "remaining cards were unchanged" in _text(finish.edited)


def test_scan_finish_cross_category_batches_autosave_then_final_card_readies_all(
    monkeypatch,
):
    selected = [
        *[card.id for card in cards.CATEGORY_CARDS["elixir"][-3:]],
        *[card.id for card in cards.CATEGORY_CARDS["dark_elixir"][:3]],
    ]
    source = _inventory(complete=())
    trusted, ready, reviewed = cards_command._trust_projection(
        {"trusted_card_ids": []},
        add=[card.id for card in cards.CARDS if card.id not in selected],
    )
    source.update({
        "trusted_card_ids": trusted,
        "complete_categories": ready,
        "reviewed_lists": reviewed,
        "scan_duplicate_unverified_card_ids": [],
    })
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()
    state = _bulk_state(selected=selected, phase="continue")
    state.update({
        "scope": "scan_finish",
        "category_id": "elixir",
        "editable_ids": selected,
        "count_snapshot": {
            card_id: source["cards"].get(card_id, cards.OWNED)
            for card_id in selected
        },
        "unconfirmed_ids": [],
        "required_entry_ids": selected,
    })
    state_id = cards_command._bulk_state_id(
        "#ME", "elixir", scope="scan_finish"
    )
    _put_state(mongo, state, state_id=state_id)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    first_values = (0, 2, 3, 4, 5)
    first_fields = {
        f"q_nonce_a_{offset}": str(value)
        for offset, value in enumerate(first_values)
    }

    asyncio.run(cards_command.cards_bulk_submit(
        _SubmitCtx(first_fields),
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    after_first = _stored_inventory(mongo)
    assert [after_first["cards"][card_id] for card_id in selected[:5]] == list(
        first_values
    )
    assert set(selected[:5]) <= set(after_first["trusted_card_ids"])
    assert selected[5] not in after_first["trusted_card_ids"]
    assert "elixir" in after_first["complete_categories"]
    assert "dark_elixir" not in after_first["complete_categories"]
    assert after_first["inventory_revision"] == 8
    progressed = _state_kwargs(mongo, state_id)
    assert progressed["next_index"] == 5
    assert progressed["phase"] == "continue"

    revision_after_first = after_first["inventory_revision"]
    replay = _SubmitCtx(first_fields)
    asyncio.run(cards_command.cards_bulk_submit(
        replay,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))
    assert _stored_inventory(mongo)["inventory_revision"] == revision_after_first
    assert _state_kwargs(mongo, state_id)["next_index"] == 5

    final_ctx = _SubmitCtx({f"q_{progressed['nonce']}_0": "6"})
    asyncio.run(cards_command.cards_bulk_submit(
        final_ctx,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **progressed,
    ))

    completed = _stored_inventory(mongo)
    assert completed["cards"][selected[5]] == 6
    assert set(selected) <= set(completed["trusted_card_ids"])
    assert set(category.id for category in cards.CATEGORIES) == set(
        completed["complete_categories"]
    )
    assert completed["inventory_revision"] == 9
    assert state_id not in mongo.component_state.documents
    assert "Ready to trade." in _text(final_ctx.edited)
    assert not any(
        custom_id.startswith("cards_ready:")
        for custom_id in _custom_ids(final_ctx.edited)
    )


def test_replayed_modal_nonce_cannot_apply_old_fields_to_the_next_batch(monkeypatch):
    selected = [card.id for card in cards.CATEGORY_CARDS["elixir"][:6]]
    state = _bulk_state(selected=selected)
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    old_fields = {
        f"q_nonce_a_{offset}": str(value)
        for offset, value in enumerate((0, 2, 3, 4, 5))
    }
    asyncio.run(cards_command.cards_bulk_submit(
        _SubmitCtx(old_fields),
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))
    revision_after_first = _stored_inventory(mongo)["inventory_revision"]
    fresh = _state_kwargs(mongo, state_id)
    assert fresh["nonce"] != "nonce_a" and fresh["next_index"] == 5

    replay = _SubmitCtx(old_fields)
    asyncio.run(cards_command.cards_bulk_submit(
        replay,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **fresh,
    ))

    assert _stored_inventory(mongo)["inventory_revision"] == revision_after_first
    assert _stored_inventory(mongo)["cards"][selected[5]] == cards.OWNED
    assert replay.edited is None
    assert replay.responses and replay.responses[0]["ephemeral"] is True
    assert "no longer current" in _text(replay.responses[0]["components"])
    assert mongo.component_state.documents[state_id]["next_index"] == 5


def test_expired_action_recovers_to_fresh_category_without_claiming_saved_work_was_lost(
    monkeypatch,
):
    document = _inventory()
    document["cards"]["barbarian"] = 6
    document["inventory_revision"] = 8
    mongo = _mongo(document)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    ctx = _SubmitCtx({})

    # No injected state is how the dispatcher calls a non-requires_state bulk
    # action after get_state has rejected or removed its expired row.
    asyncio.run(cards_command.cards_bulk_select(
        ctx,
        _state_id(),
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    rendered = _text(ctx.edited)
    assert ctx.sequence[0] == (
        "ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    assert "Counts from completed batches are shown" in rendered
    assert "Select any remaining cards again" in rendered
    barbarian_line = next(
        line for line in rendered.splitlines() if "Barbarian" in line
    )
    assert "`6`" in barbarian_line
    assert "lost" not in rendered.lower()
    assert any(
        state.get("type") == "cards_bulk_edit"
        for state in mongo.component_state.documents.values()
    )


def test_expired_scan_finish_rebuilds_only_remaining_untrusted_cards(monkeypatch):
    remaining = [
        cards.CATEGORY_CARDS["elixir"][-1].id,
        cards.CATEGORY_CARDS["dark_elixir"][0].id,
    ]
    document = _inventory(revision=9, complete=())
    trusted, ready, reviewed = cards_command._trust_projection(
        {"trusted_card_ids": []},
        add=[card.id for card in cards.CARDS if card.id not in remaining],
    )
    document.update({
        "trusted_card_ids": trusted,
        "complete_categories": ready,
        "reviewed_lists": reviewed,
    })
    document["cards"][remaining[0]] = 6
    mongo = _mongo(document)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    expired_id = cards_command._bulk_state_id(
        "#ME", cards.CARD_BY_ID[remaining[0]].category, scope="scan_finish"
    )
    ctx = _SubmitCtx({})

    asyncio.run(cards_command.cards_bulk_continue(
        ctx,
        expired_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    assert ctx.sequence[0] == (
        "ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    rendered = _text(ctx.edited)
    assert "Completed groups remain saved" in rendered
    assert "cards that still need a count" in rendered
    assert "lost" not in rendered.lower()
    replacement = next(
        state for state in mongo.component_state.documents.values()
        if state.get("scope") == "scan_finish"
    )
    assert replacement["selected_ids"] == remaining
    assert replacement["required_entry_ids"] == remaining
    assert replacement["expected_revision"] == 9


def test_scan_finish_reservation_conflict_rebuilds_cross_category_unresolved_queue(
    monkeypatch,
):
    unresolved = [card.id for card in cards.CARDS[17:25]]
    reserved_id = unresolved[1]
    assert len({cards.CARD_BY_ID[item_id].category for item_id in unresolved}) > 1
    mongo, state, state_id = _scan_finish_case(
        unresolved, reserved=[reserved_id]
    )
    before = deepcopy(_stored_inventory(mongo))
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    cards_command._inventory_locks.clear()
    submit = _SubmitCtx({
        f"q_nonce_a_{offset}": str(offset)
        for offset in range(5)
    })

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    inventory = _stored_inventory(mongo)
    assert inventory["cards"] == before["cards"]
    assert inventory["inventory_revision"] == 7
    assert inventory["trusted_card_ids"] == before["trusted_card_ids"]
    assert state_id not in mongo.component_state.documents
    replacements = [
        document for document in mongo.component_state.documents.values()
        if document.get("scope") == "scan_finish"
    ]
    assert len(replacements) == 1
    replacement = replacements[0]
    expected = [item_id for item_id in unresolved if item_id != reserved_id]
    assert replacement["selected_ids"] == expected
    assert replacement["required_entry_ids"] == expected
    assert replacement["expected_revision"] == 7
    assert reserved_id not in replacement["editable_ids"]
    assert len({cards.CARD_BY_ID[item_id].category for item_id in expected}) > 1
    rendered = _text(submit.edited)
    assert "entered a trade" in rendered
    assert "Earlier completed groups remain saved" in rendered
    assert "cards that still need a count" in rendered


def test_scan_finish_revision_conflict_rebuilds_cross_category_unresolved_queue(
    monkeypatch,
):
    unresolved = [card.id for card in cards.CARDS[17:25]]
    mongo, state, state_id = _scan_finish_case(
        unresolved,
        inventory_revision=8,
        state_revision=7,
    )
    before = deepcopy(_stored_inventory(mongo))
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    cards_command._inventory_locks.clear()
    submit = _SubmitCtx({
        f"q_nonce_a_{offset}": str(offset)
        for offset in range(5)
    })

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert _stored_inventory(mongo) == before
    assert state_id not in mongo.component_state.documents
    replacement = next(
        document for document in mongo.component_state.documents.values()
        if document.get("scope") == "scan_finish"
    )
    assert replacement["selected_ids"] == unresolved
    assert replacement["required_entry_ids"] == unresolved
    assert replacement["expected_revision"] == 8
    assert len({
        cards.CARD_BY_ID[item_id].category
        for item_id in replacement["selected_ids"]
    }) > 1
    rendered = _text(submit.edited)
    assert "The collection changed" in rendered
    assert "Earlier completed groups remain saved" in rendered
    assert "cards that still need a count" in rendered


def test_all_trusted_scan_finish_recovery_does_not_call_reserved_cards_unfinished(
    monkeypatch,
):
    reserved_id = cards.CATEGORY_CARDS["elixir"][-1].id
    document = _inventory(revision=9, complete=())
    trusted, ready, reviewed = cards_command._trust_projection(
        {"trusted_card_ids": []},
        add=[card.id for card in cards.CARDS],
    )
    document.update({
        "trusted_card_ids": trusted,
        "complete_categories": ready,
        "reviewed_lists": reviewed,
        "scan_duplicate_unverified_card_ids": [],
    })
    _reserve(document, reserved_id)
    assert cards_command._untrusted_card_ids(document) == []
    assert reserved_id in cards_command._card_reservations(document)
    mongo = _mongo(document)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    expired_id = cards_command._bulk_state_id(
        "#ME", "elixir", scope="scan_finish"
    )
    ctx = _SubmitCtx({})

    asyncio.run(cards_command.cards_bulk_continue(
        ctx,
        expired_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    rendered = _text(ctx.edited)
    assert "all remaining counts were saved" in rendered
    assert "Reserved cards can be finished" not in rendered
    assert "still need a count" not in rendered
    assert "Ready to trade." in rendered
    assert not any(
        state.get("scope") == "scan_finish"
        for state in mongo.component_state.documents.values()
    )


def test_wrong_owner_cannot_open_or_refresh_someone_elses_session():
    state = _bulk_state()
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    original = deepcopy(mongo.component_state.documents[state_id])
    ctx = _OpenCtx(values=["barbarian"], user_id=999)

    asyncio.run(cards_command.cards_bulk_select(
        ctx,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert ctx.opened is None
    assert ctx.responses and ctx.responses[0]["ephemeral"] is True
    assert "another player" in _text(ctx.responses[0]["components"])
    assert mongo.component_state.documents[state_id] == original


def test_wrong_owner_cannot_open_a_scan_finish_queue():
    selected = [cards.CATEGORY_CARDS["elixir"][0].id]
    state = _bulk_state(selected=selected, phase="continue")
    state.update({
        "scope": "scan_finish",
        "editable_ids": selected,
        "count_snapshot": {selected[0]: cards.OWNED},
        "unconfirmed_ids": [],
        "required_entry_ids": selected,
    })
    state_id = cards_command._bulk_state_id(
        "#ME", "elixir", scope="scan_finish"
    )
    mongo = _mongo()
    _put_state(mongo, state, state_id=state_id)
    original = deepcopy(mongo.component_state.documents[state_id])
    ctx = _OpenCtx(user_id=999)

    asyncio.run(cards_command.cards_bulk_continue(
        ctx,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert ctx.opened is None
    assert ctx.responses and ctx.responses[0]["ephemeral"] is True
    assert "another player" in _text(ctx.responses[0]["components"])
    assert mongo.component_state.documents[state_id] == original


def test_submitting_blank_for_only_two_plus_finishes_without_a_revision(monkeypatch):
    state = _bulk_state(selected=["wizard"])
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    submit = _SubmitCtx({"q_nonce_a_0": ""})

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    inventory = _stored_inventory(mongo)
    assert inventory["inventory_revision"] == 7
    assert inventory["cards"]["wizard"] == cards.DUPLICATE
    assert "wizard" not in inventory["count_confirmed_card_ids"]
    assert "wizard" not in inventory["scan_duplicate_unverified_card_ids"]
    assert "minion" in inventory["scan_duplicate_unverified_card_ids"]
    assert state_id not in mongo.component_state.documents
    rendered = _text(submit.edited)
    wizard_line = next(line for line in rendered.splitlines() if "Wizard" in line)
    assert "`2+`" in wizard_line
    assert "0 exact counts were saved" in rendered


def test_current_but_invalid_number_writes_nothing_and_slides_retry_session(monkeypatch):
    state = _bulk_state(selected=["barbarian"])
    old_expiry = state["expires_at"]
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    submit = _SubmitCtx({"q_nonce_a_0": "many"})

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert _stored_inventory(mongo)["inventory_revision"] == 7
    stored = mongo.component_state.documents[state_id]
    assert stored["phase"] == "continue" and stored["next_index"] == 0
    assert stored["nonce"] != "nonce_a"
    assert stored["expires_at"] > old_expiry + timedelta(hours=1)
    assert "whole number" in _text(submit.edited)
    assert "Nothing changed" in _text(submit.edited)


def test_linked_account_ownership_change_before_submit_closes_without_writing(
    monkeypatch,
):
    state = _bulk_state(selected=["barbarian"])
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    before = deepcopy(_stored_inventory(mongo))
    writer_calls = []

    async def ownership_changed(*_args, **_kwargs):
        return None, None, cards_command._notice(
            "Account no longer linked",
            "Link the account again before changing its collection.",
        )

    async def forbidden_writer(*args, **kwargs):
        writer_calls.append((args, kwargs))
        raise AssertionError("ownership failure must stop before the writer")

    monkeypatch.setattr(cards_command, "_load_target", ownership_changed)
    monkeypatch.setattr(cards_command, "_write_exact_card_batch", forbidden_writer)
    submit = _SubmitCtx({"q_nonce_a_0": "4"})

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert writer_calls == []
    assert _stored_inventory(mongo) == before
    assert state_id not in mongo.component_state.documents
    assert submit.sequence[0] == (
        "ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    rendered = _text(submit.edited)
    assert "Account no longer linked" in rendered
    assert "Earlier saved batches remain saved" in rendered
    assert "earlier completed batches remain in the collection" in rendered


def test_stranded_writing_state_recovers_to_inventory_truth(monkeypatch):
    selected = [card.id for card in cards.CATEGORY_CARDS["elixir"][:6]]
    state = _bulk_state(selected=selected, phase="writing")
    state["writing_started_at"] = (
        datetime.now(timezone.utc) - cards_command.CARD_BULK_WRITE_GRACE
        - timedelta(seconds=1)
    )
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    ctx = _SubmitCtx({})

    asyncio.run(cards_command.cards_bulk_continue(
        ctx,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert state_id not in mongo.component_state.documents
    assert ctx.sequence[0] == (
        "ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    rendered = _text(ctx.edited)
    assert "Bulk editing was interrupted" in rendered
    assert "Completed groups remain saved" in rendered
    assert "continue with cards that still need a count" in rendered


def test_active_writing_state_is_not_discarded_by_a_concurrent_click():
    selected = [card.id for card in cards.CATEGORY_CARDS["elixir"][:6]]
    state = _bulk_state(selected=selected, phase="writing")
    state["writing_started_at"] = datetime.now(timezone.utc)
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    ctx = _OpenCtx()

    asyncio.run(cards_command.cards_bulk_continue(
        ctx,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    assert state_id in mongo.component_state.documents
    assert ctx.opened is None
    assert ctx.responses and ctx.responses[0]["ephemeral"] is True
    assert "still saving" in _text(ctx.responses[0]["components"])


def test_saved_batch_returns_truthfully_if_session_advance_raises(monkeypatch):
    selected = [card.id for card in cards.CATEGORY_CARDS["elixir"][:6]]
    state = _bulk_state(selected=selected)
    mongo = _mongo()
    state_id = _put_state(mongo, state)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    real_update = cards_command._bulk_state_update
    calls = 0

    async def fail_after_writer(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("component state unavailable after inventory save")
        return await real_update(*args, **kwargs)

    monkeypatch.setattr(cards_command, "_bulk_state_update", fail_after_writer)
    submit = _SubmitCtx({
        f"q_nonce_a_{offset}": str(value)
        for offset, value in enumerate((0, 2, 3, 4, 5))
    })

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    inventory = _stored_inventory(mongo)
    assert inventory["inventory_revision"] == 8
    assert [inventory["cards"][item_id] for item_id in selected[:5]] == [
        0, 2, 3, 4, 5,
    ]
    assert inventory["cards"][selected[5]] == cards.OWNED
    assert state_id not in mongo.component_state.documents
    rendered = _text(submit.edited)
    assert "This submitted batch was saved" in rendered
    assert "select the remaining cards again" in rendered


def test_saved_scan_finish_group_rebuilds_remaining_queue_if_advance_raises(
    monkeypatch,
):
    unresolved = [card.id for card in cards.CARDS[17:23]]
    assert len({cards.CARD_BY_ID[item_id].category for item_id in unresolved}) > 1
    mongo, state, state_id = _scan_finish_case(unresolved)
    monkeypatch.setattr(cards_command, "_load_target", _fake_load_target(mongo))
    cards_command._inventory_locks.clear()
    real_update = cards_command._bulk_state_update
    calls = 0

    async def fail_after_writer(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("component state unavailable after inventory save")
        return await real_update(*args, **kwargs)

    monkeypatch.setattr(cards_command, "_bulk_state_update", fail_after_writer)
    values = (0, 2, 3, 4, 5)
    submit = _SubmitCtx({
        f"q_nonce_a_{offset}": str(value)
        for offset, value in enumerate(values)
    })

    asyncio.run(cards_command.cards_bulk_submit(
        submit,
        state_id,
        coc_client=SimpleNamespace(),
        mongo=mongo,
        **state,
    ))

    inventory = _stored_inventory(mongo)
    assert inventory["inventory_revision"] == 8
    assert [inventory["cards"][item_id] for item_id in unresolved[:5]] == list(
        values
    )
    assert set(unresolved[:5]) <= set(inventory["trusted_card_ids"])
    assert unresolved[5] not in inventory["trusted_card_ids"]
    assert state_id not in mongo.component_state.documents
    replacement = next(
        document for document in mongo.component_state.documents.values()
        if document.get("scope") == "scan_finish"
    )
    assert replacement["selected_ids"] == [unresolved[5]]
    assert replacement["required_entry_ids"] == [unresolved[5]]
    assert replacement["expected_revision"] == 8
    rendered = _text(submit.edited)
    assert "This submitted group was saved" in rendered
    assert "cards that still need a count" in rendered
    assert "lost" not in rendered.lower()

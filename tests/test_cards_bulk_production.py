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
        "scan_duplicate_unverified_card_ids": ["wizard", "minion"],
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
    assert updated["scan_duplicate_unverified_card_ids"] == ["wizard", "minion"]
    assert updated["inventory_revision"] == 8
    assert updated["complete_categories"] == ["elixir"]
    update = mongo.card_inventories.updates[-1][1]
    assert {
        path for path in update["$set"] if path.startswith("cards.")
    } == {"cards.barbarian", "cards.archer"}


def test_an_explicit_two_confirms_a_scanner_two_plus():
    source = _inventory()
    mongo = _mongo(source)
    cards_command._inventory_locks.clear()

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
    assert "wizard" in updated["count_confirmed_card_ids"]
    assert "wizard" not in updated["scan_duplicate_unverified_card_ids"]
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
    assert updated["scan_duplicate_unverified_card_ids"] == ["wizard", "minion"]
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
    assert "wizard" in inventory["scan_duplicate_unverified_card_ids"]
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
    assert "Counts from completed batches are" in rendered
    assert "Select any remaining cards again" in rendered


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

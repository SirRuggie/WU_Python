import asyncio
import math
import pathlib
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands import cards as cards_command
from utils import card_board, cards, troop_emoji
from utils.emoji import emojis
from utils.todo_data import Account


def _walk_payload(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_payload(child)


def _assert_discord_payload(view):
    payload = [component.build() for component in view]
    nodes = list(_walk_payload(payload))
    # Discord counts nested Components V2 objects, but select options are data,
    # not components and carry no `type` field.
    assert len([node for node in nodes if "type" in node]) <= 40
    text_nodes = [
        node for node in nodes
        if int(node.get("type", -1)) == int(hikari.ComponentType.TEXT_DISPLAY)
    ]
    assert sum(len(str(node.get("content") or "")) for node in text_nodes) <= 4_000
    custom_ids = [node["custom_id"] for node in nodes if "custom_id" in node]
    assert len(custom_ids) == len(set(custom_ids))
    for node in nodes:
        custom_id = node.get("custom_id")
        if custom_id is not None:
            assert len(custom_id) <= 100
            assert custom_id.count(":") == 1
        if "content" in node:
            assert len(str(node["content"])) <= 4_000
        if "placeholder" in node:
            assert len(str(node["placeholder"])) <= 150
        if "label" in node:
            assert len(str(node["label"])) <= 100
        options = node.get("options")
        if options is not None:
            assert 1 <= len(options) <= 25
            assert int(node.get("max_values", 1)) <= len(options)
            assert len({str(option["value"]) for option in options}) == len(options)
            for option in options:
                assert len(str(option["label"])) <= 100
                assert len(str(option["value"])) <= 100
                assert len(str(option.get("description", ""))) <= 100


def _complete_inventory(*, tag="#ME", clan_tag="#HOME", confirmed_at=None):
    values = {}
    for category in cards.CATEGORIES:
        values = cards.apply_category_selection(
            values, category.id, mode="baseline"
        )
    return {
        "_id": tag,
        "player_name": tag,
        "clan_tag": clan_tag,
        "clan_name": "Home Clan",
        "cards": values,
        "complete_categories": [category.id for category in cards.CATEGORIES],
        "confirmed_at": confirmed_at or datetime.now(timezone.utc),
    }


def test_catalog_has_60_unique_cards_in_the_live_category_counts():
    assert len(cards.CARDS) == 60
    assert len(cards.CARD_BY_ID) == 60
    assert len(cards.CARD_BY_NAME) == 60
    assert {
        category.id: len(cards.CATEGORY_CARDS[category.id])
        for category in cards.CATEGORIES
    } == {
        "elixir": 19,
        "dark_elixir": 13,
        "builder_base": 11,
        "super_troop": 17,
    }
    assert cards.CATEGORY_CARDS["elixir"][0].name == "Barbarian"
    assert cards.CATEGORY_CARDS["super_troop"][-1].name == "Super Bowler"


def test_category_entry_defaults_to_owned_and_only_changes_exceptions():
    values = cards.apply_category_selection(
        {},
        "elixir",
        {"root_rider", "meteor_golem"},
        mode="missing",
    )
    assert values["root_rider"] == cards.MISSING
    assert values["meteor_golem"] == cards.MISSING
    assert values["barbarian"] == cards.OWNED

    values = cards.apply_category_selection(
        values,
        "elixir",
        {"wizard", "root_rider"},
        mode="duplicates",
    )
    assert values["wizard"] == cards.DUPLICATE
    assert values["root_rider"] == cards.DUPLICATE
    assert values["meteor_golem"] == cards.MISSING

    values = cards.apply_category_selection(
        values,
        "elixir",
        {"meteor_golem"},
        mode="missing",
    )
    assert values["root_rider"] == cards.DUPLICATE
    assert values["wizard"] == cards.DUPLICATE
    assert values["meteor_golem"] == cards.MISSING

    baseline = cards.apply_category_selection(values, "elixir", mode="baseline")
    assert all(
        baseline[card.id] == cards.OWNED
        for card in cards.CATEGORY_CARDS["elixir"]
    )


def test_inventory_summary_does_not_claim_unconfigured_categories_are_owned():
    values = cards.apply_category_selection(
        {}, "builder_base", {"night_witch"}, mode="missing"
    )
    summary = cards.inventory_summary(values, ["builder_base"])
    assert summary.known == 11
    assert summary.collected == 10
    assert summary.missing == 1
    assert summary.duplicates == 0
    assert summary.complete_categories == 1


def test_matching_prefers_same_clan_reciprocal_and_rejects_stale_inventory():
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    requester = _complete_inventory(confirmed_at=now)
    requester["cards"]["root_rider"] = cards.MISSING
    requester["cards"]["wizard"] = cards.DUPLICATE
    requester["cards"]["super_barbarian"] = cards.DUPLICATE

    same_clan = _complete_inventory(tag="#SAME", confirmed_at=now - timedelta(hours=2))
    same_clan.update({"discord_id": 11, "player_name": "Same", "clan_tag": "#HOME"})
    same_clan["cards"]["root_rider"] = cards.DUPLICATE
    same_clan["cards"]["wizard"] = cards.MISSING

    other_clan = _complete_inventory(tag="#OTHER", clan_tag="#AWAY", confirmed_at=now)
    other_clan.update({"discord_id": 22, "player_name": "Other"})
    other_clan["cards"]["root_rider"] = cards.DUPLICATE
    # This is a need, but it is in the wrong category for Root Rider.
    other_clan["cards"]["super_barbarian"] = cards.MISSING

    stale = _complete_inventory(
        tag="#STALE",
        confirmed_at=now - cards.MATCHABLE_FOR - timedelta(seconds=1),
    )
    stale["cards"]["root_rider"] = cards.DUPLICATE

    found = cards.find_matches(
        requester, [other_clan, stale, same_clan], now=now
    )

    assert [match.holder_tag for match in found] == ["#SAME", "#OTHER"]
    assert found[0].offers == ("root_rider",)
    assert found[0].returns == ("wizard",)
    assert found[0].same_clan is True
    assert found[0].wanted_returns == ("wizard",)
    # The other holder already owns the wizard, which does NOT disqualify it:
    # the event lets any same-category duplicate be offered and they simply
    # end up with a spare. It is only a worse trade, not an illegal one.
    assert found[1].returns == ("wizard",)
    assert found[1].wanted_returns == ()


def test_specific_card_lookup_lists_fresh_duplicate_holders_only():
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    requester = _complete_inventory(confirmed_at=now)
    requester["cards"]["ice_hound"] = cards.MISSING
    requester["cards"]["super_wizard"] = cards.DUPLICATE

    holder = _complete_inventory(tag="#HOLDER", confirmed_at=now)
    holder["cards"]["ice_hound"] = cards.DUPLICATE
    holder["cards"]["super_wizard"] = cards.MISSING

    no_spare = _complete_inventory(tag="#SINGLE", confirmed_at=now)
    no_spare["cards"]["ice_hound"] = cards.OWNED

    found = cards.holders_for_card(
        requester, [no_spare, holder], "ice_hound", now=now
    )
    assert len(found) == 1
    assert found[0].holder_tag == "#HOLDER"
    assert found[0].returns == ("super_wizard",)


def test_stale_requester_cannot_search_even_when_holder_is_fresh():
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    requester = _complete_inventory(
        confirmed_at=now - cards.MATCHABLE_FOR - timedelta(seconds=1)
    )
    requester["cards"]["root_rider"] = cards.MISSING
    holder = _complete_inventory(tag="#HOLDER", confirmed_at=now)
    holder["cards"]["root_rider"] = cards.DUPLICATE

    assert cards.find_matches(requester, [holder], now=now) == []
    assert cards.holders_for_card(requester, [holder], "root_rider", now=now) == []


def test_reciprocal_trade_allows_cross_clan_fresh_four_leg_state():
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    requester = _complete_inventory(confirmed_at=now)
    holder = _complete_inventory(tag="#HOLDER", confirmed_at=now)
    requester["cards"].update({"root_rider": cards.MISSING, "wizard": cards.DUPLICATE})
    holder["cards"].update({"root_rider": cards.DUPLICATE, "wizard": cards.MISSING})

    assert cards.reciprocal_trade_error(
        requester, holder, "root_rider", "wizard", now=now
    ) is None
    assert "same category" in cards.reciprocal_trade_error(
        requester, holder, "root_rider", "super_wizard", now=now
    ).lower()
    holder["clan_tag"] = "#AWAY"
    assert cards.reciprocal_trade_error(
        requester, holder, "root_rider", "wizard", now=now
    ) is None


class _FakeTradeCollection:
    def __init__(self):
        self.docs = {}

    async def update_one(self, query, update, upsert=False):
        key = query["_id"]
        current = self.docs.get(key)
        if current is not None and not _matches_query(current, query):
            if upsert:
                raise DuplicateKeyError("active lease")
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        if current is None and not upsert:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        inserted = current is None
        document = current if current is not None else {"_id": key}
        _apply_update(document, update, inserted=inserted)
        self.docs[key] = document
        return SimpleNamespace(
            matched_count=0 if inserted else 1,
            modified_count=1,
            upserted_id=key if inserted else None,
        )

    async def update_many(self, query, update):
        matched = 0
        for document in self.docs.values():
            if _matches_query(document, query):
                matched += 1
                _apply_update(document, update)
        return SimpleNamespace(matched_count=matched, modified_count=matched)

    async def delete_many(self, query):
        doomed = [
            key for key, value in self.docs.items()
            if _matches_query(value, query)
        ]
        for key in doomed:
            self.docs.pop(key)
        return SimpleNamespace(deleted_count=len(doomed))

    async def delete_one(self, query):
        for key, value in list(self.docs.items()):
            if _matches_query(value, query):
                self.docs.pop(key)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def find_one(self, query):
        return next(
            (document for document in self.docs.values()
             if _matches_query(document, query)),
            None,
        )

    async def insert_one(self, document):
        key = document["_id"]
        if key in self.docs:
            raise DuplicateKeyError("duplicate trade")
        self.docs[key] = dict(document)
        return SimpleNamespace(inserted_id=key)

    def find(self, query):
        return _FakeCursor([
            document for document in self.docs.values()
            if _matches_query(document, query)
        ])


class _FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, field, direction):
        self.documents.sort(
            key=lambda document: _field_value(document, field),
            reverse=direction < 0,
        )
        return self

    async def to_list(self, length):
        return self.documents[:length] if length is not None else self.documents


_ABSENT = object()


def _field_value(document, path):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _ABSENT
        value = value[part]
    return value


def _matches_value(actual, expected):
    if not isinstance(expected, dict) or not any(
        str(operator).startswith("$") for operator in expected
    ):
        return actual is not _ABSENT and actual == expected
    for operator, operand in expected.items():
        if operator == "$exists":
            if (actual is not _ABSENT) != bool(operand):
                return False
        elif actual is _ABSENT:
            return False
        elif operator == "$gt" and not actual > operand:
            return False
        elif operator == "$gte" and not actual >= operand:
            return False
        elif operator == "$lt" and not actual < operand:
            return False
        elif operator == "$lte" and not actual <= operand:
            return False
        elif operator == "$in" and actual not in operand:
            return False
        elif operator == "$ne" and actual == operand:
            return False
        elif operator not in {
            "$exists", "$gt", "$gte", "$lt", "$lte", "$in", "$ne",
        }:
            raise AssertionError(f"unsupported fake query operator: {operator}")
    return True


def _matches_query(document, query):
    for field, expected in query.items():
        if field == "$or":
            if not any(_matches_query(document, branch) for branch in expected):
                return False
        elif field == "$and":
            if not all(_matches_query(document, branch) for branch in expected):
                return False
        elif not _matches_value(_field_value(document, field), expected):
            return False
    return True


def _set_field(document, path, value):
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def _unset_field(document, path):
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.get(part, {})
    target.pop(parts[-1], None)


def _apply_update(document, update, *, inserted=False):
    if inserted:
        for path, value in update.get("$setOnInsert", {}).items():
            _set_field(document, path, value)
    for path, value in update.get("$set", {}).items():
        _set_field(document, path, value)
    for path, value in update.get("$inc", {}).items():
        current = _field_value(document, path)
        _set_field(document, path, (0 if current is _ABSENT else current) + value)
    for path in update.get("$unset", {}):
        _unset_field(document, path)
    for path, condition in update.get("$pull", {}).items():
        current = _field_value(document, path)
        if not isinstance(current, list):
            continue
        if isinstance(condition, dict) and "$in" in condition:
            rejected = set(condition["$in"])
            remaining = [value for value in current if value not in rejected]
        else:
            remaining = [value for value in current if value != condition]
        _set_field(document, path, remaining)
    for path, operation in update.get("$addToSet", {}).items():
        values = (
            operation.get("$each", [])
            if isinstance(operation, dict)
            else [operation]
        )
        current = _field_value(document, path)
        target = [] if current is _ABSENT or not isinstance(current, list) else current
        for value in values:
            if value not in target:
                target.append(value)
        _set_field(document, path, target)


def _trade_document(*, trade_id="trade-a"):
    return {
        "_id": trade_id,
        "guild_id": 1,
        "requester_tag": "#ME",
        "holder_tag": "#HOLDER",
        "wanted_card_id": "root_rider",
        "given_card_id": "wizard",
    }


def _reserved_trade(*, trade_id="trade-a", token="token-a"):
    trade = _trade_document(trade_id=trade_id)
    trade["reservation_token"] = token
    return trade


def _reserve_inventory(
    document,
    trade,
    *,
    owner=None,
    until=None,
    legacy=False,
):
    owner = owner or cards_command._reservation_owner(trade)
    document["guild_id"] = trade["guild_id"]
    marker = owner if legacy else {"owner": owner}
    if until is not None and not legacy:
        marker = {"owner": owner, "until": until}
    document["card_trade_reservations"] = {
        trade["wanted_card_id"]: dict(marker) if isinstance(marker, dict) else marker,
        trade["given_card_id"]: dict(marker) if isinstance(marker, dict) else marker,
    }
    return document


def _lease_documents(trade, *, until=None):
    documents = {
        cards_command._trade_lease_id(kind, tag, card_id): {
            "_id": cards_command._trade_lease_id(kind, tag, card_id),
            "kind": "lease",
            "trade_id": trade["_id"],
            "owner_token": cards_command._reservation_owner(trade),
            "guild_id": trade["guild_id"],
            "lease_kind": kind,
            "player_tag": tag,
            "card_id": card_id,
        }
        for kind, tag, card_id in cards_command._trade_lease_specs(trade)
    }
    if until is not None:
        for document in documents.values():
            document["lease_expires_at"] = until
    return documents


def test_trade_reservation_uses_four_unified_card_leases_and_rolls_back_conflict():
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    collection = _FakeTradeCollection()
    mongo = SimpleNamespace(card_trades=collection)
    trade = _trade_document()
    trade["reservation_token"] = "token-a"
    conflict_id = cards_command._trade_lease_id("supply", "#HOLDER", "root_rider")
    collection.docs[conflict_id] = {
        "_id": conflict_id,
        "kind": "lease",
        "trade_id": "other-trade",
        "owner_token": "other-trade:other-token",
    }

    acquired = asyncio.run(cards_command._acquire_trade_leases(
        mongo, trade, now=now
    ))

    assert acquired is False
    assert len(cards_command._trade_lease_specs(trade)) == 4
    assert len({
        cards_command._trade_lease_id(kind, tag, card_id)
        for kind, tag, card_id in cards_command._trade_lease_specs(trade)
    }) == 4
    assert collection.docs == {
        conflict_id: collection.docs[conflict_id]
    }


def test_unified_lease_id_ignores_need_supply_role():
    assert cards_command._trade_lease_id("need", "#ME", "wizard") == (
        cards_command._trade_lease_id("supply", "#ME", "wizard")
    )
    assert cards_command._trade_lease_id("need", "#ME", "wizard") != (
        cards_command._trade_lease_id("need", "#OTHER", "wizard")
    )


def test_two_disjoint_accepted_swaps_can_coexist_on_one_account():
    now = datetime.now(timezone.utc)
    first = _reserved_trade(trade_id="trade-a", token="token-a")
    second = _reserved_trade(trade_id="trade-b", token="token-b")
    second.update({
        "holder_tag": "#HOLDER2",
        "wanted_card_id": "archer",
        "given_card_id": "giant",
    })
    inventories = _FakeInventoryCollection([
        dict(_complete_inventory(), guild_id=1),
        dict(_complete_inventory(tag="#HOLDER"), guild_id=1),
        dict(_complete_inventory(tag="#HOLDER2"), guild_id=1),
    ])
    trades = _FakeTradeCollection()
    mongo = SimpleNamespace(
        card_inventories=inventories,
        card_trades=trades,
    )

    for trade in (first, second):
        assert asyncio.run(cards_command._acquire_trade_leases(
            mongo, trade, now=now
        )) is True
        assert asyncio.run(cards_command._acquire_trade_inventory_fences(
            mongo, trade
        )) is True

    assert len(trades.docs) == 8
    shared = inventories.documents["#ME"]["card_trade_reservations"]
    assert {card_id: marker["owner"] for card_id, marker in shared.items()} == {
        "root_rider": "trade-a:token-a",
        "wizard": "trade-a:token-a",
        "archer": "trade-b:token-b",
        "giant": "trade-b:token-b",
    }
    assert all(isinstance(marker.get("until"), datetime) for marker in shared.values())

    asyncio.run(cards_command._release_trade_reservation(mongo, first))
    assert len(trades.docs) == 4
    shared = inventories.documents["#ME"]["card_trade_reservations"]
    assert set(shared) == {"archer", "giant"}
    assert {marker["owner"] for marker in shared.values()} == {"trade-b:token-b"}


@pytest.mark.parametrize(
    ("live_clans", "expected_status"),
    [
        (("#HOME", "#AWAY"), "move_needed"),
        (("#HOME", "#HOME"), "ready"),
    ],
)
def test_acceptance_promotes_temporary_resources_before_final_status(
    monkeypatch,
    live_clans,
    expected_status,
):
    now = datetime.now(timezone.utc)
    trade = _trade_document()
    trade.update({
        "kind": "trade",
        "status": "pending",
        "requester_discord_id": 111,
        "holder_discord_id": 222,
        "updated_at": now,
    })
    requester = dict(_complete_inventory(confirmed_at=now), guild_id=1)
    holder = dict(
        _complete_inventory(tag="#HOLDER", confirmed_at=now),
        guild_id=1,
    )
    requester["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holder["cards"].update({
        "root_rider": cards.DUPLICATE,
        "wizard": cards.MISSING,
    })

    class TrackingInventories(_FakeInventoryCollection):
        def __init__(self, documents):
            super().__init__(documents)
            self.marker_promotions = 0

        async def update_one(self, query, update, upsert=False):
            until_paths = [
                path
                for path in update.get("$unset", {})
                if path.startswith("card_trade_reservations.")
                and path.endswith(".until")
            ]
            if until_paths:
                document = self.documents[query["_id"]]
                for path in until_paths:
                    assert isinstance(_field_value(document, path), datetime)
                    self.marker_promotions += 1
            return await super().update_one(query, update, upsert=upsert)

    inventories = TrackingInventories([requester, holder])

    class TrackingTrades(_FakeTradeCollection):
        def __init__(self):
            super().__init__()
            self.lease_promotions = 0
            self.promoted_before_status = False

        async def update_many(self, query, update):
            if "lease_expires_at" in update.get("$unset", {}):
                expiring = [
                    document
                    for document in self.docs.values()
                    if document.get("kind") == "lease"
                    and isinstance(document.get("lease_expires_at"), datetime)
                ]
                self.lease_promotions = len(expiring)
            return await super().update_many(query, update)

        async def update_one(self, query, update, upsert=False):
            target_status = update.get("$set", {}).get("status")
            if target_status in {"move_needed", "ready"}:
                markers = [
                    marker
                    for document in inventories.documents.values()
                    for marker in document.get("card_trade_reservations", {}).values()
                ]
                leases = [
                    document
                    for document in self.docs.values()
                    if document.get("kind") == "lease"
                ]
                assert len(markers) == 4
                assert all(
                    isinstance(marker, dict) and "until" not in marker
                    for marker in markers
                )
                assert len(leases) == 4
                assert all("lease_expires_at" not in lease for lease in leases)
                assert inventories.marker_promotions == 4
                assert self.lease_promotions == 4
                self.promoted_before_status = True
            return await super().update_one(query, update, upsert=upsert)

    trades = TrackingTrades()
    trades.docs[trade["_id"]] = dict(trade)
    mongo = SimpleNamespace(
        card_inventories=inventories,
        card_trades=trades,
    )
    monkeypatch.setattr(cards_command.secrets, "token_hex", lambda _size: "accept-token")

    outcome, status = asyncio.run(cards_command._accept_trade_reservation(
        mongo,
        trade,
        user_id=222,
        live_clans=live_clans,
        now=now,
    ))

    assert (outcome, status) == ("accepted", expected_status)
    saved = trades.docs[trade["_id"]]
    assert saved["status"] == expected_status
    assert saved["reservation_token"] == "accept-token"
    assert "reservation_until" not in saved
    assert trades.promoted_before_status is True


def test_cross_clan_proposal_is_indefinite_and_holds_no_reservations():
    requester = _complete_inventory(clan_tag="#HOME")
    holder = _complete_inventory(tag="#HOLDER", clan_tag="#AWAY")
    requester.update({"guild_id": 1, "discord_id": 111, "player_name": "Shaun"})
    holder.update({"guild_id": 1, "discord_id": 222, "player_name": "Holder"})
    requester["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holder["cards"].update({
        "root_rider": cards.DUPLICATE,
        "wizard": cards.MISSING,
    })
    trades = _FakeTradeCollection()
    mongo = SimpleNamespace(card_trades=trades)

    trade, error = asyncio.run(cards_command._create_trade_request(
        mongo,
        requester=requester,
        holder=holder,
        wanted_card_id="root_rider",
        given_card_id="wizard",
        guild_id=1,
    ))

    assert error is None
    assert trade is not None and trade["status"] == "pending"
    assert trade["requester_clan_tag"] == "#HOME"
    assert trade["holder_clan_tag"] == "#AWAY"
    assert "expires_at" not in trade
    assert "reservation_token" not in trade
    saved_trades = [
        document for document in trades.docs.values()
        if document.get("kind") == "trade"
    ]
    proposal_slots = [
        document for document in trades.docs.values()
        if document.get("kind") == "proposal_slot"
    ]
    assert [document["_id"] for document in saved_trades] == [trade["_id"]]
    assert len(proposal_slots) == 2
    assert {slot["player_tag"] for slot in proposal_slots} == {"#ME", "#HOLDER"}
    assert all("lease_expires_at" not in slot for slot in proposal_slots)


def test_proposal_creation_caps_each_account_at_twenty_five_open_proposals():
    requester = _complete_inventory(clan_tag="#HOME")
    holder = _complete_inventory(tag="#HOLDER", clan_tag="#AWAY")
    requester.update({"guild_id": 1, "discord_id": 111})
    holder.update({"guild_id": 1, "discord_id": 222})
    requester["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holder["cards"].update({
        "root_rider": cards.DUPLICATE,
        "wizard": cards.MISSING,
    })
    trades = _FakeTradeCollection()
    for index in range(cards_command.MAX_OPEN_PROPOSALS_PER_ACCOUNT):
        trades.docs[f"open-{index}"] = {
            "_id": f"open-{index}",
            "kind": "trade",
            "guild_id": 1,
            "status": "pending",
            "requester_tag": "#ME",
            "holder_tag": f"#OTHER{index}",
            "wanted_card_id": "root_rider",
            "given_card_id": "wizard",
        }

    created, error = asyncio.run(cards_command._create_trade_request(
        SimpleNamespace(card_trades=trades),
        requester=requester,
        holder=holder,
        wanted_card_id="root_rider",
        given_card_id="wizard",
        guild_id=1,
    ))

    assert created is None
    assert error is not None and "25 open proposals" in error
    assert len(trades.docs) == cards_command.MAX_OPEN_PROPOSALS_PER_ACCOUNT


def test_atomic_proposal_slots_enforce_limit_and_roll_back_partial_acquire():
    now = datetime.now(timezone.utc)
    trades = _FakeTradeCollection()
    for index in range(cards_command.MAX_OPEN_PROPOSALS_PER_ACCOUNT):
        owner_id = f"holder-open-{index}"
        trades.docs[owner_id] = {
            "_id": owner_id,
            "kind": "trade",
            "guild_id": 1,
            "status": "pending",
        }
        slot_id = cards_command._proposal_slot_id(1, "#HOLDER", index)
        trades.docs[slot_id] = {
            "_id": slot_id,
            "kind": "proposal_slot",
            "trade_id": owner_id,
            "guild_id": 1,
            "player_tag": "#HOLDER",
        }
    trade = _trade_document(trade_id="new-proposal")
    trade.update({"kind": "trade", "status": "pending"})
    mongo = SimpleNamespace(card_trades=trades)

    acquired = asyncio.run(cards_command._acquire_proposal_slots(
        mongo, trade, now=now
    ))

    assert acquired is None
    assert not any(
        document.get("kind") == "proposal_slot"
        and document.get("trade_id") == trade["_id"]
        for document in trades.docs.values()
    )
    assert len([
        document for document in trades.docs.values()
        if document.get("kind") == "proposal_slot"
        and document.get("player_tag") == "#HOLDER"
    ]) == cards_command.MAX_OPEN_PROPOSALS_PER_ACCOUNT


def test_two_concurrent_proposals_cannot_take_the_same_last_slot():
    now = datetime.now(timezone.utc)

    class RacingSlots(_FakeTradeCollection):
        def __init__(self):
            super().__init__()
            self.arrivals = 0
            self.both_arrived = asyncio.Event()

        async def update_one(self, query, update, upsert=False):
            if (
                upsert
                and str(query.get("_id", "")).endswith("|24")
                and update.get("$set", {}).get("kind") == "proposal_slot"
            ):
                self.arrivals += 1
                if self.arrivals == 2:
                    self.both_arrived.set()
                else:
                    await self.both_arrived.wait()
            return await super().update_one(query, update, upsert=upsert)

    trades = RacingSlots()
    for index in range(cards_command.MAX_OPEN_PROPOSALS_PER_ACCOUNT - 1):
        owner_id = f"existing-{index}"
        trades.docs[owner_id] = {
            "_id": owner_id,
            "kind": "trade",
            "status": "pending",
        }
        slot_id = cards_command._proposal_slot_id(1, "#ME", index)
        trades.docs[slot_id] = {
            "_id": slot_id,
            "kind": "proposal_slot",
            "trade_id": owner_id,
            "guild_id": 1,
            "player_tag": "#ME",
        }
    mongo = SimpleNamespace(card_trades=trades)
    first = dict(_trade_document(trade_id="first"), kind="trade", status="pending")
    second = dict(_trade_document(trade_id="second"), kind="trade", status="pending")

    async def race():
        return await asyncio.gather(
            cards_command._acquire_account_proposal_slot(
                mongo, first, "#ME", now=now
            ),
            cards_command._acquire_account_proposal_slot(
                mongo, second, "#ME", now=now
            ),
        )

    results = asyncio.run(race())

    assert sum(result is not None for result in results) == 1
    last_slot = trades.docs[cards_command._proposal_slot_id(1, "#ME", 24)]
    assert last_slot["trade_id"] in {"first", "second"}


def test_reserving_owner_keeps_and_finalizes_its_proposal_slot():
    now = datetime.now(timezone.utc)
    trade = dict(
        _trade_document(trade_id="accepting"),
        kind="trade",
        status="reserving",
    )
    slot_id = cards_command._proposal_slot_id(1, "#ME", 0)
    slot = {
        "_id": slot_id,
        "kind": "proposal_slot",
        "trade_id": trade["_id"],
        "guild_id": 1,
        "player_tag": "#ME",
        "lease_expires_at": now + timedelta(minutes=5),
    }
    trades = _FakeTradeCollection()
    trades.docs.update({trade["_id"]: trade, slot_id: slot})

    reclaimable = asyncio.run(cards_command._proposal_slot_reclaimable(
        SimpleNamespace(card_trades=trades), slot, now=now
    ))

    assert reclaimable is False
    assert "lease_expires_at" not in trades.docs[slot_id]


def test_trade_dm_is_best_effort_and_contains_no_account_secrets():
    class Rest:
        def __init__(self):
            self.messages = []

        async def create_dm_channel(self, discord_id):
            assert discord_id == 222
            return "dm-channel"

        async def create_message(self, *, channel, components, flags=None):
            assert channel == "dm-channel"
            self.messages.append((_view_text(components), _view_media(components)))

    rest = Rest()
    bot = SimpleNamespace(rest=rest)
    trade = _trade_document()
    trade.update({
        "requester_name": "Shaun",
        "requester_discord_id": 111,
        "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_clan_tag": "#HOME",
        "requester_clan_name": "Morning Woods",
        "requester_town_hall": 17,
        "holder_clan_tag": "#AWAY",
        "holder_clan_name": "Edrag Rush",
        "holder_town_hall": 18,
        "compatible_card_ids": ["wizard", "dragon"],
    })

    assert asyncio.run(cards_command._notify_trade_holder(bot, trade)) is True
    assert len(rest.messages) == 1
    content, attachment = rest.messages[0]
    assert "Root Rider" in content
    assert "Wizard" in content
    assert "Dragon" in content
    # The labels carry the ask; the old lead sentence repeated the card.
    assert "**You give:**" in content
    assert "wants your" not in content
    # Every card they could take, as a list - not one named card plus an
    # aside about others, which read as a contradiction.
    assert "You receive one of:" in content
    assert "You receive:" not in content
    # Both clans are named, and both town halls shown, so a reader can see
    # who they are dealing with without opening the game.
    assert "Morning Woods" in content and "Edrag Rush" in content
    assert "TH_18" in content and "TH_17" in content
    assert "different clans" in content
    assert "token" not in content.casefold()
    assert "password" not in content.casefold()
    # Mounted in the container's gallery, which is the only way a V2
    # message shows an image at all.
    assert "card-trade-root_rider-wizard.png" in str(attachment)

    channel_copy = cards_command._trade_channel_content(trade)
    assert "Shaun needs your duplicate Root Rider" in channel_copy
    assert "Wizard, Dragon" in channel_copy
    # The channel post names both clans and calls neither side "you".
    assert "`#HOME`" in channel_copy and "`#AWAY`" in channel_copy
    assert "you are in" not in channel_copy

    class ClosedRest:
        async def create_dm_channel(self, _discord_id):
            raise RuntimeError("DMs closed")

    closed_bot = SimpleNamespace(rest=ClosedRest())
    assert asyncio.run(cards_command._notify_trade_holder(
        closed_bot, trade
    )) is False


def test_trade_visual_failure_still_delivers_accessible_text(monkeypatch):
    class Rest:
        def __init__(self):
            self.messages = []

        async def create_dm_channel(self, _discord_id):
            return "dm-channel"

        async def create_message(self, **kwargs):
            self.messages.append(kwargs)

    def broken_renderer(*_args, **_kwargs):
        raise RuntimeError("renderer unavailable")

    monkeypatch.setattr(cards_command, "render_trade_strip", broken_renderer)
    rest = Rest()
    trade = _trade_document()
    trade.update({
        "requester_name": "Shaun",
        "requester_discord_id": 111,
        "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_clan_tag": "#HOME",
        "holder_clan_tag": "#AWAY",
        "compatible_card_ids": ["wizard", "dragon"],
    })

    assert asyncio.run(cards_command._notify_trade_holder(
        SimpleNamespace(rest=rest), trade
    )) is True
    assert len(rest.messages) == 1
    sent = rest.messages[0]["components"]
    # No gallery at all when the render failed, but the words still arrive.
    assert _view_media(sent) is None
    assert "**You give:**" in _view_text(sent)
    assert "Root Rider" in _view_text(sent)


def test_follow_up_status_dm_names_only_the_readers_account():
    """A status DM names the reader's account, not both players' accounts.

    The pair of account lines was clutter: the reader only needs to know
    which of their own accounts the notice is about.
    """
    class Rest:
        def __init__(self):
            self.messages = []

        async def create_dm_channel(self, discord_id):
            assert discord_id == 222
            return "dm-channel"

        async def create_message(self, *, channel, components, flags=None):
            assert channel == "dm-channel"
            self.messages.append(_view_text(components))

    trade = _trade_document()
    trade.update({
        "requester_name": "Shaun",
        "requester_discord_id": 111,
        "holder_name": "Holder",
        "holder_discord_id": 222,
    })
    rest = Rest()

    sent = asyncio.run(cards_command._notify_trade_status(
        SimpleNamespace(rest=rest),
        trade,
        recipient_id=222,
        title="Card swap is ready",
        detail="Both accounts moved together.",
    ))

    assert sent is True
    assert len(rest.messages) == 1
    assert "`#HOLDER`" in rest.messages[0], "the reader's own account"
    assert "`#ME`" not in rest.messages[0], "the partner's tag is not listed"


def test_trade_channel_posts_in_configured_guild_and_mentions_holder_only(monkeypatch):
    class Rest:
        def __init__(self, guild_id):
            self.guild_id = guild_id
            self.messages = []

        async def fetch_channel(self, channel_id):
            assert channel_id == 999
            return SimpleNamespace(guild_id=self.guild_id)

        async def create_message(self, **kwargs):
            self.messages.append(kwargs)
            return SimpleNamespace(id=777)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    trade = _trade_document()
    trade.update({
        "kind": "trade",
        "status": "pending",
        "requester_name": "Shaun",
        "requester_discord_id": 111,
        "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_clan_tag": "#HOME",
        "holder_clan_tag": "#AWAY",
        "compatible_card_ids": ["wizard", "dragon"],
    })
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = dict(trade)
    mongo = SimpleNamespace(card_trades=trades)
    rest = Rest(guild_id=1)

    posted = asyncio.run(cards_command._post_trade_channel(
        SimpleNamespace(rest=rest), mongo, trade
    ))

    assert posted is True
    assert len(rest.messages) == 1
    sent = rest.messages[0]
    assert sent["channel"] == 999
    assert sent["user_mentions"] == [222]
    assert sent["mentions_everyone"] is False
    assert sent["role_mentions"] is False
    # The standing post is Components V2 now: the strip is mounted inside the
    # message's own gallery (a bare attachment would silently not render).
    assert sent["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2
    assert "attachment" not in sent
    media = _view_media(sent["components"])
    assert "card-trade-root_rider-wizard.png" in str(media)
    assert trades.docs[trade["_id"]]["channel_id"] == 999
    assert trades.docs[trade["_id"]]["channel_message_id"] == 777
    # The V2 marker is what routes later edits down the components branch,
    # and the filename is remembered so edits can re-reference the upload
    # even after the accepter changes given_card_id.
    assert trades.docs[trade["_id"]]["channel_post_v2"] is True
    assert trades.docs[trade["_id"]]["channel_post_image"] == (
        "card-trade-root_rider-wizard.png"
    )

    wrong_rest = Rest(guild_id=2)
    rejected = asyncio.run(cards_command._post_trade_channel(
        SimpleNamespace(rest=wrong_rest), mongo, dict(trade, _id="trade-wrong")
    ))
    assert rejected is False
    assert wrong_rest.messages == []


class _RecordingRest:
    """A rest client that records what the transport asked Discord to do."""

    def __init__(self, guild_id=1):
        self.guild_id = guild_id
        self.messages = []
        self.edits = []

    async def fetch_channel(self, channel_id):
        return SimpleNamespace(guild_id=self.guild_id)

    async def create_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(id=777)

    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(id=kwargs.get("message"))


def test_no_cards_channel_message_can_mention_everyone_or_a_role(monkeypatch):
    """The transport decides mentions, so no caller can get this wrong.

    Player names are the only user-controlled text in these posts. They are
    escaped on the way in, but the allowlist is what makes a miss harmless
    rather than an @everyone in a channel the whole family reads.
    """
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    rest = _RecordingRest()
    bot = SimpleNamespace(rest=rest)

    # Every shape a caller can post in: plain content, V2 components, a reply.
    asyncio.run(cards_command._channel_post(bot, content="@everyone hello"))
    asyncio.run(cards_command._channel_post(bot, components=[], ping=[222]))
    asyncio.run(cards_command._channel_post(bot, content="x", reply_to=5))

    assert len(rest.messages) == 3
    for sent in rest.messages:
        assert sent["mentions_everyone"] is False
        assert sent["role_mentions"] is False
        assert isinstance(sent["user_mentions"], list), (
            "never True and never undefined - an explicit list only"
        )

    asyncio.run(cards_command._channel_edit(
        bot, channel_id=999, message_id=777, content="updated"
    ))
    assert rest.edits[0]["mentions_everyone"] is False
    assert rest.edits[0]["role_mentions"] is False
    assert rest.edits[0]["user_mentions"] is False


def test_a_ping_list_is_bounded_deduplicated_and_survives_junk():
    """A ping list comes from a query, and a query can return surprises."""
    assert cards_command._mention_allowlist([]) == []
    assert cards_command._mention_allowlist(None) == []
    assert cards_command._mention_allowlist([5, 5, 6]) == [5, 6], "deduplicated"
    assert cards_command._mention_allowlist(["7", 8]) == [7, 8], "coerced"
    assert cards_command._mention_allowlist([None, "nope", 9]) == [9], (
        "an unusable id is skipped rather than raising mid-delivery"
    )
    crowd = list(range(100))
    capped = cards_command._mention_allowlist(crowd)
    assert len(capped) == cards_command.MAX_PING_PER_MESSAGE
    assert capped == crowd[:cards_command.MAX_PING_PER_MESSAGE], (
        "the first ids win, so the caller's ordering is its priority"
    )


def test_a_reply_never_pings_the_author_on_top_of_the_allowlist(monkeypatch):
    """Discord pings a reply's author by default. The policy picks who pings."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    rest = _RecordingRest()

    asyncio.run(cards_command._channel_post(
        SimpleNamespace(rest=rest), content="x", reply_to=42, ping=[222]
    ))

    assert rest.messages[0]["reply"] == 42
    assert rest.messages[0]["mentions_reply"] is False
    assert rest.messages[0]["user_mentions"] == [222]


def test_channel_delivery_failures_are_reported_not_raised(monkeypatch):
    """A trade is saved before it is announced, so delivery must not unwind it."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)

    class Broken:
        async def fetch_channel(self, channel_id):
            raise RuntimeError("discord is having a day")

        async def edit_message(self, **kwargs):
            raise RuntimeError("discord is having a day")

    bot = SimpleNamespace(rest=Broken())
    assert asyncio.run(cards_command._channel_post(bot, content="x")) is None
    assert asyncio.run(cards_command._channel_edit(
        bot, channel_id=999, message_id=777, content="x"
    )) is False


def test_an_unconfigured_channel_refuses_to_post_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", None)
    rest = _RecordingRest()

    posted = asyncio.run(cards_command._channel_post(
        SimpleNamespace(rest=rest), content="x"
    ))

    assert posted is None
    assert rest.messages == []


def test_the_sticky_notice_and_the_trade_board_share_one_channel():
    """The notice explaining how to trade cannot sit away from the trades.

    They were two settings - an env var and a hardcoded snowflake - and
    nothing stopped them disagreeing.
    """
    from extensions.tasks import cards_sticky
    from utils import cards_config

    assert cards_sticky.STICKY_CHANNEL_ID == cards_config.cards_channel_id()
    assert cards_command.CARDS_CHANNEL_ID == cards_config.cards_channel_id()


def test_an_unset_channel_variable_falls_back_instead_of_disabling_posting(monkeypatch):
    """An unset CARDS_CHANNEL_ID used to mean "no trade board" silently."""
    from utils import cards_config

    monkeypatch.delenv("CARDS_CHANNEL_ID", raising=False)
    assert cards_config.cards_channel_id() == cards_config.CARDS_CHANNEL_FALLBACK

    monkeypatch.setenv("CARDS_CHANNEL_ID", "12345")
    assert cards_config.cards_channel_id() == 12345

    monkeypatch.setenv("CARDS_CHANNEL_ID", "not-a-snowflake")
    assert cards_config.cards_channel_id() == cards_config.CARDS_CHANNEL_FALLBACK, (
        "a malformed id falls back rather than disabling the board"
    )

    # The guild id has no fallback: it is the authority boundary, so an unset
    # value must disable the feature rather than guess at a server.
    monkeypatch.delenv("CARDS_GUILD_ID", raising=False)
    assert cards_config.cards_guild_id() is None


def _standing_post_trade(**overrides):
    """A trade with everything the standing post renders."""
    trade = _trade_document()
    trade.update({
        "kind": "trade",
        "status": "pending",
        "requester_name": "Shaun",
        "requester_discord_id": 111,
        "holder_name": "Holder Person",
        "holder_discord_id": 222,
        "requester_clan_tag": "#HOME",
        "requester_clan_name": "Morning Woods",
        "requester_town_hall": 17,
        "holder_clan_tag": "#AWAY",
        "holder_clan_name": "Edrag Rush",
        "holder_town_hall": 18,
        "compatible_card_ids": ["wizard", "dragon"],
    })
    trade.update(overrides)
    return trade


def test_the_standing_post_carries_controls_only_while_pending():
    """The V2 standing post: three live controls while pending, none after.

    The accept button names the card the holder takes - the same words as
    the DM's accept. It wore the holder's name at first, but this family's
    names are decorated unicode and the first live label truncated one to
    "Accept · ŦH̶Ɇ"; the footer and the handler's participant check are what
    keep wrong tappers out.
    """
    trade = _standing_post_trade()
    view = cards_command._trade_post(
        trade, attachment_ref="attachment://card-trade-root_rider-wizard.png"
    )
    _assert_discord_payload(view)
    ids = [str(n["custom_id"]) for n in _view_nodes(view) if "custom_id" in n]
    assert ids == [
        "cards_pub_accept:trade-a",
        "cards_pub_decline:trade-a",
        "cards_pub_cancel:trade-a",
    ]
    for custom_id in ids:
        assert custom_id.count(":") == 1, "one colon per custom_id"
    labels = _view_labels(view)
    assert "Accept · take Wizard" in labels, (
        "the card on Accept, matching the DM's wording"
    )
    assert "Cancel · requester" in labels
    text = _view_text(view)
    assert "Only <@222> can accept" in text
    assert "**Shaun** needs your duplicate **Root Rider**" in text
    assert "Wizard, Dragon" in text
    # The channel post names both clans and calls neither side "you".
    assert "Morning Woods" in text and "Edrag Rush" in text
    assert "you are in" not in text
    media = _view_media(view)
    assert "attachment://card-trade-root_rider-wizard.png" in str(media)

    # An accepted-ish trade keeps the full body but loses every control:
    # from here it belongs to My trades, not to the channel.
    for status in ("reserving", "move_needed", "ready", "accepted",
                   "completing", "needs_review"):
        working = cards_command._trade_post(dict(trade, status=status))
        assert not [
            n for n in _view_nodes(working) if "custom_id" in n
        ], status

    # Terminal statuses collapse to the compact closed form: zero
    # interactive components, no image, but the audit line survives.
    for status in sorted(cards_command.TRADE_POST_TERMINAL_STATUSES):
        closed = cards_command._trade_post(
            dict(trade, status=status),
            attachment_ref="attachment://card-trade-root_rider-wizard.png",
        )
        _assert_discord_payload(closed)
        assert not [n for n in _view_nodes(closed) if "custom_id" in n], status
        assert _view_media(closed) is None, status
        closed_text = _view_text(closed)
        assert "Root Rider" in closed_text and "Wizard" in closed_text, (
            "the closed form still records what the trade was"
        )


def test_the_standing_post_stays_far_below_the_component_ceiling():
    """Discord rejects the WHOLE message past 40 components.

    Worst case: pending (controls present), an image mounted, long names,
    and a maximal spare list - headroom, not just "fits".
    """
    trade = _standing_post_trade(
        requester_name="R" * 90,
        holder_name="H" * 90,
        compatible_card_ids=[card.id for card in cards.CARDS[:30]],
    )
    view = cards_command._trade_post(
        trade, attachment_ref="attachment://card-trade-root_rider-wizard.png"
    )
    used = len([n for n in _view_nodes(view) if "type" in n])
    assert used <= 36, f"standing post is at {used}/40"
    _assert_discord_payload(view)


def test_only_listed_events_may_post_and_ping():
    """THE noise guard: exactly five events create a channel message.

    Widening delivery is a deliberate one-row change to TRADE_DELIVERY,
    never an accident at a call site - this test is what enforces that.
    """
    table = cards_command.TRADE_DELIVERY
    posting = {event for event, policy in table.items() if policy.posts}
    assert posting == {
        "proposal_created", "proposal_accepted", "open_request_posted",
        "open_request_claimed", "gem_ask_posted",
    }
    assert table["proposal_created"].pings == "holder"
    assert table["proposal_accepted"].pings == "requester"
    # The owner's decision: a want-ad pings NOBODY, edits nothing (it IS the
    # standing post) and never falls back to a DM - there is no recipient.
    assert table["open_request_posted"] == cards_command._EventPolicy(
        posts=True, pings=None, edits=False, dm="never"
    )
    # A claim delivers the CONVERTED kind:"trade" doc, so "requester" is the
    # want-ad's poster; the edit refreshes the reused want-ad message into
    # the trade's standing post. dm="always" for the live-verification
    # window, like the other two pinging events - the end state is
    # "fallback", one table entry away.
    assert table["open_request_claimed"] == cards_command._EventPolicy(
        posts=True, pings="requester", edits=True, dm="always"
    )
    # Nothing else may ping: a ping without a post cannot exist anyway
    # (edits are structurally silent), and the table says so.
    for event, policy in table.items():
        if not policy.posts:
            assert policy.pings is None, event
    # The silent set edits the standing post and sends nothing at all.
    for event in ("declined", "cancelled", "ready", "card_arrived",
                  "completed", "expired"):
        assert table[event] == cards_command._EventPolicy(
            posts=False, pings=None, edits=True, dm="never"
        ), event
    # The gem ask IS its standing post and pings the one holder asked; the
    # DM is strictly a fallback for a failed post - the old DM-only
    # fragility (and its delete-on-DM-failure branch) is gone.
    assert table["gem_ask_posted"] == cards_command._EventPolicy(
        posts=True, pings="holder", edits=False, dm="fallback"
    )
    # The answer never posts or pings - the ping budget is proposal +
    # acceptance ONLY (the owner's decision overrides the plan table's
    # sketch). It silently edits the ask's post and always DMs the asker.
    assert table["gem_ask_answered"] == cards_command._EventPolicy(
        posts=False, pings=None, edits=True, dm="always"
    )
    # Review stays private: no post, but both DMs still go.
    assert table["needs_review"].dm == "always"
    assert table["needs_review"].edits is True


class _DmRecorder:
    """Stands in for _send_trade_dm and records who got what."""

    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    async def __call__(self, _bot, discord_id, components, **_kwargs):
        self.sent.append((int(discord_id), components))
        return int(discord_id) not in self.fail_for


def _delivery_fixture(monkeypatch, *, fail_dm_for=()):
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    dms = _DmRecorder(fail_for=fail_dm_for)
    monkeypatch.setattr(cards_command, "_send_trade_dm", dms)
    rest = _RecordingRest()
    trades = _FakeTradeCollection()
    mongo = SimpleNamespace(card_trades=trades)
    return SimpleNamespace(rest=rest), mongo, rest, dms


def test_acceptance_posts_one_reply_pinging_exactly_the_requester(monkeypatch):
    bot, mongo, rest, dms = _delivery_fixture(monkeypatch)
    trade = _standing_post_trade(
        status="move_needed",
        channel_id=999,
        channel_message_id=555,
        channel_post_v2=True,
        channel_post_image="card-trade-root_rider-wizard.png",
    )
    mongo.card_trades.docs[trade["_id"]] = dict(trade)

    delivery = asyncio.run(cards_command._deliver(
        bot, mongo, trade, event="proposal_accepted"
    ))

    assert len(rest.messages) == 1, "exactly ONE new channel message"
    sent = rest.messages[0]
    assert sent["user_mentions"] == [111], "exactly the requester"
    assert sent["reply"] == 555, "threaded under the standing post"
    assert sent["mentions_reply"] is False
    note_text = _view_text(sent["components"])
    assert "<@111>" in note_text and "accepted" in note_text
    assert "My trades" in note_text
    # The standing post itself is refreshed in place, as V2.
    assert len(rest.edits) == 1
    assert "components" in rest.edits[0] and "content" not in rest.edits[0]
    # dm="always" during the live-verification window: the requester's DM
    # still goes on top of the ping.
    assert [recipient for recipient, _ in dms.sent] == [111]
    assert delivery.channel_message_id == 777
    assert delivery.pinged == (111,)
    assert delivery.dm_sent == (111,)


def test_silent_events_edit_the_post_and_send_nothing(monkeypatch):
    """decline / cancel / ready / card-arrived / completed / expired:
    zero new posts, zero pings, zero DMs - only the silent edit."""
    for event in ("declined", "cancelled", "ready", "card_arrived",
                  "completed", "expired"):
        bot, mongo, rest, dms = _delivery_fixture(monkeypatch)
        status = {
            "declined": "declined", "cancelled": "cancelled",
            "ready": "ready", "card_arrived": "ready",
            "completed": "completed", "expired": "expired",
        }[event]
        trade = _standing_post_trade(
            status=status,
            channel_id=999,
            channel_message_id=555,
            channel_post_v2=True,
        )

        delivery = asyncio.run(cards_command._deliver(
            bot, mongo, trade, event=event
        ))

        assert rest.messages == [], event
        assert dms.sent == [], event
        assert len(rest.edits) == 1, event
        assert delivery.pinged == (), event
        assert delivery.channel_message_id is None, event


def test_needs_review_still_dms_both_participants(monkeypatch):
    bot, mongo, rest, dms = _delivery_fixture(monkeypatch)
    trade = _standing_post_trade(
        status="needs_review",
        channel_id=999,
        channel_message_id=555,
        channel_post_v2=True,
    )

    delivery = asyncio.run(cards_command._deliver(
        bot, mongo, trade, event="needs_review",
        dm_components_by_recipient=cards_command._notify_review_participants(
            trade, "Recheck both categories."
        ),
    ))

    assert rest.messages == [], "review never posts publicly"
    assert sorted(recipient for recipient, _ in dms.sent) == [111, 222]
    for _recipient, components in dms.sent:
        assert "Card swap needs review" in _view_text(components)
    assert len(rest.edits) == 1
    assert delivery.dm_sent == (111, 222) or set(delivery.dm_sent) == {111, 222}


def test_a_legacy_post_keeps_the_plain_content_edit_path(monkeypatch):
    """A message created with content= can never become V2 by an edit, so
    trades without the creation-time marker keep today's path verbatim."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    rest = _RecordingRest()
    bot = SimpleNamespace(rest=rest)
    legacy = _standing_post_trade(
        status="declined", channel_id=999, channel_message_id=555,
    )
    assert "channel_post_v2" not in legacy

    assert asyncio.run(cards_command._update_trade_channel(bot, legacy)) is True
    assert rest.edits[0]["content"] == cards_command._trade_channel_content(
        legacy
    )
    assert "components" not in rest.edits[0]

    modern = dict(legacy, channel_post_v2=True)
    assert asyncio.run(cards_command._update_trade_channel(bot, modern)) is True
    assert "content" not in rest.edits[1]
    assert "components" in rest.edits[1]


def test_an_accepted_post_becomes_the_coordination_point():
    """After acceptance the post stops re-stating the proposal and tells the
    two players what to do next, in short numbered steps - the live feedback
    was that the family needs the next tap, not the history. Different clans
    adds the move step; the same clan does not."""
    trade = _standing_post_trade(
        status="ready", channel_post_v2=True, holder_clan_tag="#HOME",
    )
    text = _view_text(cards_command._trade_post(trade))
    # Mention plus account name: one Discord user can hold both sides with
    # two linked accounts, and mentions alone rendered as the same person
    # giving both cards.
    assert "<@111> — **Shaun** gives **Wizard**" in text
    assert "<@222> — **Holder Person** gives **Root Rider**" in text
    assert "Talk here" in text
    assert "I sent my card" in text
    assert "needs your duplicate" not in text, "the proposal detail is done"
    same_clan_steps = text.count("**1.**") + text.count("**2.**") + text.count("**3.**")

    moved = cards_command._trade_post(dict(
        trade, status="move_needed", holder_clan_tag="#AWAY",
    ))
    moved_text = _view_text(moved)
    assert "moves to the other clan" in moved_text
    assert "**4.**" in moved_text, "the move adds a step"
    assert "**4.**" not in text, "same clan has no move step"
    assert same_clan_steps == 3


def test_an_edited_post_never_references_the_original_upload():
    """Edits drop the strip - live-verified on 2026-08-16.

    The `attachment://<filename>` re-reference theory failed on the first
    real acceptance: the reply-note posted but the standing-post edit was
    refused, exactly the audit's predicted failure mode. `attachment://`
    only names a file uploaded in the same request, so an edit that carries
    no upload must carry no reference either - otherwise the WHOLE edit
    fails and the post freezes at "pending" with live buttons after the
    trade has moved on.
    """
    trade = _standing_post_trade(
        status="move_needed",
        channel_post_v2=True,
        channel_post_image="card-trade-root_rider-wizard.png",
        given_card_id="dragon",
    )
    for status in ("move_needed", "ready", "accepted", "completed"):
        assert cards_command._standing_post_image_ref(
            dict(trade, status=status)
        ) is None, status


def test_deliver_soon_returns_the_result_and_survives_a_slow_post(monkeypatch):
    """The interactive wrapper: a fast delivery reports, a slow one keeps
    running past the 3-second patience window instead of being cancelled."""
    finished = asyncio.Event()

    async def slow_deliver(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        finished.set()
        return cards_command._Delivery(channel_message_id=777, pinged=(222,))

    monkeypatch.setattr(cards_command, "_deliver", slow_deliver)

    async def fast_path():
        return await cards_command._deliver_soon(
            SimpleNamespace(), SimpleNamespace(), {"_id": "t"},
            event="proposal_created",
        )

    delivery = asyncio.run(fast_path())
    assert delivery is not None and delivery.channel_message_id == 777

    async def never_deliver(*_args, **_kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(cards_command, "_deliver", never_deliver)
    monkeypatch.setattr(cards_command.asyncio, "wait", _instant_timeout_wait)

    async def slow_path():
        cards_command._DELIVERY_TASKS.clear()
        result = await cards_command._deliver_soon(
            SimpleNamespace(), SimpleNamespace(), {"_id": "t"},
            event="proposal_created",
        )
        task = next(iter(cards_command._DELIVERY_TASKS))
        still_running = not task.done()
        task.cancel()
        return result, still_running

    result, still_running = asyncio.run(slow_path())
    assert result is None, "the handler answers without the delivery"
    assert still_running, "asyncio.wait does not cancel; the post still lands"


async def _instant_timeout_wait(tasks, timeout=None):
    """asyncio.wait with the clock removed: nothing is done yet."""
    del timeout
    return set(), set(tasks)


def test_the_delivery_note_reports_what_actually_happened():
    note = cards_command._delivery_note
    pinged = cards_command._Delivery(
        channel_message_id=1, pinged=(222,), dm_sent=(222,)
    )
    assert "pinged them in" in note(pinged, recipient_id=222)
    assert "They also got a DM." in note(pinged, recipient_id=222)
    dm_only = cards_command._Delivery(channel_message_id=None, dm_sent=(222,))
    assert note(dm_only, recipient_id=222) == "I sent them a DM."
    nothing = cards_command._Delivery(channel_message_id=None)
    assert "could not reach <@222>" in note(nothing, recipient_id=222)
    # None means still in flight - not a failure, so no false alarm.
    assert note(None, recipient_id=222) == "I am telling them now."


def test_public_reply_uses_an_ephemeral_followup_never_the_dispatcher_reply():
    """One missed flag would replace the public post with a private panel;
    _public_reply answers only through interaction.execute."""
    calls = []

    class Interaction:
        async def execute(self, **kwargs):
            calls.append(kwargs)

    # No .respond attribute at all: touching it would raise immediately.
    ctx = SimpleNamespace(
        interaction=Interaction(), user=SimpleNamespace(id=1)
    )
    asyncio.run(cards_command._public_reply(ctx, ["PRIVATE-PANEL"]))
    assert calls[0]["components"] == ["PRIVATE-PANEL"]
    assert calls[0]["flags"] & hikari.MessageFlag.EPHEMERAL
    assert calls[0]["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2

    class Broken:
        async def execute(self, **_kwargs):
            raise RuntimeError("token expired")

    # A dead token is logged, never raised into the dispatcher.
    asyncio.run(cards_command._public_reply(
        SimpleNamespace(interaction=Broken(), user=SimpleNamespace(id=1)),
        ["X"],
    ))


def test_a_wrong_member_public_click_gets_a_private_refusal(monkeypatch):
    """The shared bodies already gate on participants; the public adapter
    must deliver that refusal ephemerally and change nothing publicly."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 123)
    trade = _standing_post_trade()

    class Trades:
        async def find_one(self, _query):
            return dict(trade)

    async def _unchanged(_mongo, doc, **_kwargs):
        return dict(doc)

    monkeypatch.setattr(cards_command, "_expire_trade_if_needed", _unchanged)
    followups = []

    class Interaction:
        values = []

        async def execute(self, **kwargs):
            followups.append(kwargs)

    stranger = SimpleNamespace(
        guild_id=123, user=SimpleNamespace(id=999), interaction=Interaction(),
    )
    asyncio.run(cards_command.cards_pub_cancel(
        stranger, trade["_id"],
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(card_trades=Trades()),
        bot=SimpleNamespace(),
    ))

    assert len(followups) == 1
    assert followups[0]["flags"] & hikari.MessageFlag.EPHEMERAL
    assert "not yours" in _view_text(followups[0]["components"]).lower()


def _gem_ask_doc(**overrides):
    """A gem ask with everything the public post and the DMs render."""
    ask = {
        "_id": "gem:#ME:#H:balloon", "kind": "gem_ask", "status": "pending",
        "guild_id": 1, "card_id": "balloon", "gem_cost": 50,
        "asker_tag": "#ME", "asker_name": "Asker", "asker_discord_id": 111,
        "holder_tag": "#H", "holder_name": "Holder", "holder_discord_id": 222,
        "generation": 1000,
    }
    ask.update(overrides)
    return ask


def test_the_gem_ask_post_carries_the_answer_pair_only_while_pending():
    """The public V2 gem ask: yes/no while pending, one closed line after.

    The custom_ids embed the ask id, which itself contains colons - the
    dispatcher partitions on the FIRST colon only, exactly as the legacy
    cards_gem_yes DM buttons already rely on.
    """
    ask = _gem_ask_doc()
    view = cards_command._gem_ask_post(ask)
    ids = [str(n["custom_id"]) for n in _view_nodes(view) if "custom_id" in n]
    assert ids == [
        "cards_pub_gem_yes:gem:#ME:#H:balloon|1000",
        "cards_pub_gem_no:gem:#ME:#H:balloon|1000",
    ]
    name, _, action_id = ids[0].partition(":")
    assert name == "cards_pub_gem_yes", "first-colon routing reaches the pair"
    assert action_id == "gem:#ME:#H:balloon|1000"
    labels = _view_labels(view)
    assert "Yes, I will post it" in labels and "No thanks" in labels
    text = _view_text(view)
    assert "<@222>" in text, "the holder is addressed by mention"
    assert "Only <@222> can answer" in text
    assert "**Asker** is missing" in text
    assert "50 gems" in text and "you keep all your cards" in text
    assert "If you say yes" in text, "the same instructions as the DM"

    # Answered asks collapse to the compact closed form: the audit line
    # survives, nothing is clickable any more.
    for status in sorted(cards_command.GEM_ASK_TERMINAL_STATUSES):
        closed = cards_command._gem_ask_post(dict(ask, status=status))
        assert not [n for n in _view_nodes(closed) if "custom_id" in n], status
        closed_text = _view_text(closed)
        assert "answered" in closed_text, status
        expected = "yes" if status == "accepted" else "no"
        assert f"answered — {expected}" in closed_text, status
        assert "Asker" in closed_text and "Holder" in closed_text, (
            "the closed form still records who asked whom"
        )


def test_the_gem_ask_post_stays_far_below_the_component_ceiling():
    """Worst case: pending (both buttons), maximal names - headroom, not
    just "fits". (No _assert_discord_payload here: its one-colon pin does
    not apply to gem ids, which route on the first colon by design.)"""
    ask = _gem_ask_doc(asker_name="A" * 90, holder_name="H" * 90)
    payload = [component.build() for component in cards_command._gem_ask_post(ask)]
    nodes = list(_walk_payload(payload))
    used = len([n for n in nodes if "type" in n])
    assert used <= 12, f"gem ask post is at {used}/40"
    for node in nodes:
        if "custom_id" in node:
            assert len(str(node["custom_id"])) <= 100
        if "label" in node:
            assert len(str(node["label"])) <= 100


def test_a_gem_ask_posts_once_pinging_exactly_the_holder(monkeypatch):
    bot, mongo, rest, dms = _delivery_fixture(monkeypatch)
    ask = _gem_ask_doc()
    mongo.card_trades.docs[ask["_id"]] = dict(ask)

    delivery = asyncio.run(cards_command._deliver(
        bot, mongo, ask, event="gem_ask_posted"
    ))

    assert len(rest.messages) == 1, "exactly ONE new channel message"
    sent = rest.messages[0]
    assert sent["user_mentions"] == [222], "exactly the holder"
    assert "components" in sent, "the ask posts as V2"
    assert rest.edits == []
    assert dms.sent == [], "the DM is a fallback, never a copy"
    assert delivery.channel_message_id == 777
    assert delivery.pinged == (222,)
    # The stored ask remembers where its post lives so the answer can edit it.
    stored = mongo.card_trades.docs[ask["_id"]]
    assert stored["channel_message_id"] == 777
    assert stored["channel_post_v2"] is True


def test_a_failed_gem_ask_post_falls_back_to_the_unchanged_dm(monkeypatch):
    """dm="fallback": the old DM goes ONLY when the channel post failed,
    and its payload is the existing `_gem_ask_dm` builder, byte-identical."""
    bot, mongo, rest, dms = _delivery_fixture(monkeypatch)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", None)
    ask = _gem_ask_doc()
    mongo.card_trades.docs[ask["_id"]] = dict(ask)

    delivery = asyncio.run(cards_command._deliver(
        bot, mongo, ask, event="gem_ask_posted"
    ))

    assert rest.messages == []
    assert [recipient for recipient, _ in dms.sent] == [222]
    assert _view_text(dms.sent[0][1]) == _view_text(
        cards_command._gem_ask_dm(ask)
    )
    legacy_ids = [
        str(n["custom_id"]) for n in _view_nodes(dms.sent[0][1])
        if "custom_id" in n
    ]
    assert legacy_ids == [
        "cards_gem_yes:gem:#ME:#H:balloon|1000",
        "cards_gem_no:gem:#ME:#H:balloon|1000",
    ], "the fallback DM still carries the legacy pair, which stays registered"
    assert delivery.channel_message_id is None
    assert delivery.pinged == ()
    assert delivery.dm_sent == (222,)


def _open_requester_inventory(**overrides):
    """A complete, fresh #ME collection missing Root Rider with a spare
    Wizard - the smallest inventory an open request accepts."""
    inventory = _complete_inventory()
    inventory.update({
        "guild_id": 1, "discord_id": 111, "player_name": "Shaun",
        "town_hall": 17,
    })
    inventory["cards"]["root_rider"] = cards.MISSING
    inventory["cards"]["wizard"] = cards.DUPLICATE
    inventory.update(overrides)
    return inventory


def _open_request_document(**overrides):
    """A stored open request with everything the want-ad post renders."""
    created = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    base = {
        "_id": "req-a",
        "kind": "open_request",
        "status": "open",
        "generation": 1_755_000_000,
        "guild_id": 1,
        "category": "elixir",
        "wanted_card_id": "root_rider",
        "offer_card_ids": ["wizard", "dragon"],
        "requester_tag": "#ME",
        "requester_name": "Shaun",
        "requester_discord_id": 111,
        "requester_town_hall": 17,
        "requester_clan_tag": "#HOME",
        "requester_clan_name": "Morning Woods",
        "requester_clan_emoji": "",
        "channel_id": None,
        "channel_message_id": None,
        "claim_token": None,
        "claim_until": None,
        "claimed_by_discord_id": None,
        "claimed_by_tag": None,
        "claimed_at": None,
        "trade_id": None,
        "created_at": created,
        "updated_at": created,
        "expires_at": created + cards_command.OPEN_REQUEST_FOR,
        "open_request_key": "1:#ME:root_rider",
    }
    base.update(overrides)
    return base


def test_open_request_saves_the_spec_document_and_its_unique_key():
    trades = _FakeTradeCollection()

    request, error = asyncio.run(cards_command._create_open_request(
        SimpleNamespace(card_trades=trades),
        requester_inventory=_open_requester_inventory(),
        wanted_card_id="root_rider",
        guild_id=1,
    ))

    assert error is None
    saved = trades.docs[request["_id"]]
    assert saved["kind"] == "open_request"
    assert saved["status"] == "open"
    assert isinstance(saved["generation"], int)
    assert saved["guild_id"] == 1
    assert saved["category"] == "elixir"
    assert saved["wanted_card_id"] == "root_rider"
    assert saved["offer_card_ids"] == ["wizard"]
    assert saved["requester_tag"] == "#ME"
    assert saved["requester_name"] == "Shaun"
    assert saved["requester_discord_id"] == 111
    assert saved["requester_town_hall"] == 17
    # Copied at creation: a channel post must never depend on a later query.
    assert saved["requester_clan_tag"] == "#HOME"
    assert saved["requester_clan_name"] == "Home Clan"
    assert saved["requester_clan_emoji"] == ""
    assert saved["open_request_key"] == "1:#ME:root_rider"
    assert saved["expires_at"] == (
        saved["created_at"] + cards_command.OPEN_REQUEST_FOR
    )
    # Claim fields exist from birth so the claim CAS never needs $exists.
    for field in ("channel_id", "channel_message_id", "claim_token",
                  "claim_until", "claimed_by_discord_id", "claimed_by_tag",
                  "claimed_at", "trade_id"):
        assert saved[field] is None, field


def test_open_request_without_a_spare_is_refused_toward_ask_for_help():
    """The game's rule: no duplicate to give back, no trade from this side."""
    inventory = _open_requester_inventory()
    inventory["cards"]["wizard"] = cards.OWNED     # no elixir spare left
    trades = _FakeTradeCollection()

    request, error = asyncio.run(cards_command._create_open_request(
        SimpleNamespace(card_trades=trades),
        requester_inventory=inventory,
        wanted_card_id="root_rider",
        guild_id=1,
    ))

    assert request is None
    assert "Ask for help" in error, "the refusal names the working route"
    assert trades.docs == {}


def test_open_request_refuses_not_missing_incomplete_and_stale():
    mongo = SimpleNamespace(card_trades=_FakeTradeCollection())

    owned = _open_requester_inventory()
    owned["cards"]["root_rider"] = cards.OWNED
    _request, error = asyncio.run(cards_command._create_open_request(
        mongo, requester_inventory=owned,
        wanted_card_id="root_rider", guild_id=1,
    ))
    assert "not missing" in error

    unfinished = _open_requester_inventory()
    unfinished["complete_categories"] = [
        category.id for category in cards.CATEGORIES
        if category.id != "elixir"
    ]
    _request, error = asyncio.run(cards_command._create_open_request(
        mongo, requester_inventory=unfinished,
        wanted_card_id="root_rider", guild_id=1,
    ))
    assert "Finish entering" in error

    # Unmatchable (trading paused counts, same as the matcher itself).
    paused = _open_requester_inventory(trading_paused=True)
    _request, error = asyncio.run(cards_command._create_open_request(
        mongo, requester_inventory=paused,
        wanted_card_id="root_rider", guild_id=1,
    ))
    assert "fresh" in error.lower()
    assert mongo.card_trades.docs == {}


def test_open_requests_cap_at_three_per_account():
    trades = _FakeTradeCollection()
    for index in range(cards_command.MAX_OPEN_REQUESTS_PER_ACCOUNT):
        trades.docs[f"req-{index}"] = {
            "_id": f"req-{index}",
            "kind": "open_request",
            "guild_id": 1,
            "status": "open",
            "requester_tag": "#ME",
            "wanted_card_id": "balloon",
        }

    request, error = asyncio.run(cards_command._create_open_request(
        SimpleNamespace(card_trades=trades),
        requester_inventory=_open_requester_inventory(),
        wanted_card_id="root_rider",
        guild_id=1,
    ))

    assert request is None
    assert "3 open" in error
    assert len(trades.docs) == cards_command.MAX_OPEN_REQUESTS_PER_ACCOUNT


class _UniqueOpenRequestKeys(_FakeTradeCollection):
    """The sparse-unique open_request_key index, as the fake sees it."""

    async def insert_one(self, document):
        key = document.get("open_request_key")
        if key is not None and any(
            other.get("open_request_key") == key
            for other in self.docs.values()
        ):
            raise DuplicateKeyError("uniq_open_card_request")
        return await super().insert_one(document)


def test_second_open_request_for_the_same_card_is_a_clean_refusal():
    trades = _UniqueOpenRequestKeys()
    mongo = SimpleNamespace(card_trades=trades)
    first, error = asyncio.run(cards_command._create_open_request(
        mongo, requester_inventory=_open_requester_inventory(),
        wanted_card_id="root_rider", guild_id=1,
    ))
    assert error is None and first is not None

    second, error = asyncio.run(cards_command._create_open_request(
        mongo, requester_inventory=_open_requester_inventory(),
        wanted_card_id="root_rider", guild_id=1,
    ))

    assert second is None
    assert "already have an open request" in error
    assert "Root Rider" in error
    assert "My trades" in error
    assert len(trades.docs) == 1, "the loser wrote nothing"


def test_a_want_ad_posts_once_pings_nobody_and_stores_its_ids(monkeypatch):
    bot, mongo, rest, dms = _delivery_fixture(monkeypatch)
    request = _open_request_document()
    mongo.card_trades.docs[request["_id"]] = dict(request)

    delivery = asyncio.run(cards_command._deliver(
        bot, mongo, request, event="open_request_posted"
    ))

    assert len(rest.messages) == 1, "the want-ad IS the standing post"
    sent = rest.messages[0]
    assert sent["user_mentions"] == [], "a want-ad pings NOBODY"
    assert sent["mentions_everyone"] is False
    assert sent["role_mentions"] is False
    assert sent["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2
    assert rest.edits == [], "nothing to edit - this event creates the post"
    assert dms.sent == [], "never a DM: there is no recipient"
    assert delivery.pinged == ()
    assert delivery.channel_message_id == 777
    saved = mongo.card_trades.docs[request["_id"]]
    assert saved["channel_id"] == 999
    assert saved["channel_message_id"] == 777
    assert saved["channel_post_v2"] is True
    ids = [
        n["custom_id"] for n in _view_nodes(sent["components"])
        if "custom_id" in n
    ]
    assert ids == [f"cards_pub_claim:req-a|{request['generation']}"]


def test_the_want_ad_carries_one_claim_button_open_and_none_closed():
    request = _open_request_document()
    view = cards_command._open_request_post(request)
    _assert_discord_payload(view)
    ids = [n["custom_id"] for n in _view_nodes(view) if "custom_id" in n]
    assert ids == ["cards_pub_claim:req-a|1755000000"]
    for custom_id in ids:
        assert custom_id.count(":") == 1, "one colon per custom_id"
    assert "I have this card" in _view_labels(view)
    text = _view_text(view)
    assert "Root Rider" in text
    assert "Wizard" in text and "Dragon" in text, "the give-back list shows"
    assert "My trades" in text, "the footer names the owner's close route"

    # Terminal statuses collapse to the compact closed form: zero
    # interactive components, but the audit line survives.
    for status in sorted(cards_command.OPEN_REQUEST_TERMINAL_STATUSES):
        closed = cards_command._open_request_post(dict(request, status=status))
        _assert_discord_payload(closed)
        assert not [
            n for n in _view_nodes(closed) if "custom_id" in n
        ], status
        assert "Root Rider" in _view_text(closed), status


def test_the_want_ad_stays_far_below_the_component_ceiling():
    """Worst case: a maximal give-back list and long names - headroom,
    not just "fits"."""
    request = _open_request_document(
        requester_name="R" * 90,
        requester_clan_name="C" * 60,
        offer_card_ids=[card.id for card in cards.CATEGORY_CARDS["elixir"]],
    )
    view = cards_command._open_request_post(request)
    used = len([n for n in _view_nodes(view) if "type" in n])
    assert used <= 12, f"want-ad post is at {used}/40"
    _assert_discord_payload(view)


def test_closing_a_want_ad_is_owner_only_and_cas(monkeypatch):
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    request = _open_request_document(
        channel_id=999, channel_message_id=555, channel_post_v2=True,
    )
    trades = _FakeTradeCollection()
    trades.docs[request["_id"]] = dict(request)
    mongo = SimpleNamespace(card_trades=trades)
    rest = _RecordingRest()
    bot = SimpleNamespace(rest=rest)

    stranger = asyncio.run(cards_command.cards_req_close(
        _quantity_ctx(user_id=999), "req-a", mongo=mongo, bot=bot,
    ))
    assert "not yours" in _view_text(stranger).lower()
    assert trades.docs["req-a"]["status"] == "open", "a stranger changes nothing"
    assert rest.edits == []

    closed = asyncio.run(cards_command.cards_req_close(
        _quantity_ctx(user_id=111), "req-a", mongo=mongo, bot=bot,
    ))
    saved = trades.docs["req-a"]
    assert saved["status"] == "cancelled"
    assert "open_request_key" not in saved, "$unset frees the card for later"
    assert saved["claim_token"] is None, "claim fields untouched"
    assert saved["claimed_by_discord_id"] is None
    assert len(rest.edits) == 1, "the public post flips to the closed form"
    edited = rest.edits[0]
    assert edited["message"] == 555
    assert edited["user_mentions"] is False, "an edit cannot ping"
    assert not [
        n for n in _view_nodes(edited["components"]) if "custom_id" in n
    ], "the closed form is not clickable"
    assert "Request closed" in _view_text(closed)

    again = asyncio.run(cards_command.cards_req_close(
        _quantity_ctx(user_id=111), "req-a", mongo=mongo, bot=bot,
    ))
    assert "already" in _view_text(again).lower(), "second close: CAS lost"
    assert len(rest.edits) == 1, "and it edits nothing"


def test_my_trades_lists_open_requests_with_a_close_button():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._trades_view(
        account, [], open_requests=[_open_request_document()]
    )
    _assert_discord_payload(view)
    ids = [n["custom_id"] for n in _view_nodes(view) if "custom_id" in n]
    assert "cards_req_close:req-a" in ids
    text = _view_text(view)
    assert "Open request" in text
    assert "Root Rider" in text
    assert "No open trades" not in text, "a request is an open item"


def test_my_trades_pages_requests_and_trades_inside_one_budget():
    """Requests ride in the same paged list, so a full page of both can
    never exceed what the 5-trade page already proved fits."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    requests = [
        _open_request_document(_id=f"req-{index}")
        for index in range(cards_command.MAX_OPEN_REQUESTS_PER_ACCOUNT)
    ]
    trades = [
        {
            "_id": f"trade{index}",
            "status": "pending",
            "requester_tag": f"#OTHER{index}",
            "requester_name": f"Other {index}",
            "holder_tag": "#ME",
            "holder_name": "Member",
            "wanted_card_id": "root_rider",
            "given_card_id": "wizard",
        }
        for index in range(cards_command.TRADE_VIEW_LIMIT)
    ]
    first = cards_command._trades_view(
        account, trades, page=0, open_requests=requests
    )
    second = cards_command._trades_view(
        account, trades, page=1, open_requests=requests
    )
    for view in (first, second):
        _assert_discord_payload(view)
    first_ids = [
        n["custom_id"] for n in _view_nodes(first) if "custom_id" in n
    ]
    assert "cards_req_close:req-0" in first_ids
    assert any(i.startswith("cards_trades:#ME|") for i in first_ids), (
        "eight items must page"
    )
    second_ids = [
        n["custom_id"] for n in _view_nodes(second) if "custom_id" in n
    ]
    assert not any(
        i.startswith("cards_req_close:") for i in second_ids
    ), "requests render first, so page two is trades only"


def _claimer_inventory(*, tag="#CL", discord_id=222, name="Claimer Person",
                       missing=("wizard",), **overrides):
    """A complete, fresh collection holding a spare Root Rider - the
    smallest inventory that can claim the fixture want-ad."""
    inventory = _complete_inventory(tag=tag, clan_tag="#AWAY")
    inventory.update({
        "guild_id": 1, "discord_id": discord_id, "player_name": name,
        "town_hall": 18, "clan_name": "Edrag Rush",
    })
    inventory["cards"]["root_rider"] = cards.DUPLICATE
    for card_id in missing:
        inventory["cards"][card_id] = cards.MISSING
    inventory.update(overrides)
    return inventory


def _claim_account(tag="#CL", name="Claimer Person"):
    return Account(
        tag=tag, name=name, clan_tag="#AWAY",
        clan_name="Edrag Rush", town_hall=18,
    )


def _fake_linked_accounts(monkeypatch, accounts_by_user):
    """load_accounts as the claim path sees it, keyed by discord id.

    Yields once before returning, so two concurrent claimers both pass the
    status:"open" read before either reaches the claiming CAS - the exact
    interleaving the first-come-first-served fence exists for.
    """
    async def fake_load_accounts(_coc_client, discord_id, **_kwargs):
        await asyncio.sleep(0)
        return cards_command.AccountsData(entries=tuple(
            cards_command.AccountEntry(
                cards_command._normalize_tag(account.tag),
                cards_command.STATUS_LOADED,
                account,
            )
            for account in accounts_by_user.get(int(discord_id), ())
        ))

    monkeypatch.setattr(cards_command, "load_accounts", fake_load_accounts)


def _claim_env(monkeypatch, *, offers=("wizard", "dragon"), poster=None,
               claimers=None, accounts_by_user=None,
               live_clans=("#HOME", "#HOME")):
    """A posted want-ad plus (by default) one eligible claimer, on fakes."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    dms = _DmRecorder()
    monkeypatch.setattr(cards_command, "_send_trade_dm", dms)

    async def live(_mongo, _coc_client, _left, _right):
        return live_clans

    monkeypatch.setattr(cards_command, "_live_family_clans", live)
    _fake_linked_accounts(
        monkeypatch,
        accounts_by_user
        if accounts_by_user is not None
        else {222: [_claim_account()]},
    )
    request = _open_request_document(
        offer_card_ids=list(offers),
        channel_id=999, channel_message_id=555, channel_post_v2=True,
    )
    trades = _FakeTradeCollection()
    trades.docs[request["_id"]] = dict(request)
    inventories = _FakeInventoryCollection([
        poster if poster is not None else _open_requester_inventory(),
        *(claimers if claimers is not None else [_claimer_inventory()]),
    ])
    mongo = SimpleNamespace(card_trades=trades, card_inventories=inventories)
    rest = _RecordingRest()
    return SimpleNamespace(
        request=request, trades=trades, inventories=inventories, mongo=mongo,
        rest=rest, bot=SimpleNamespace(rest=rest), dms=dms,
    )


def _claim(env, *, user_id=222, generation=None, claim_tag=None,
           taken_card_id=None):
    return asyncio.run(cards_command._perform_open_request_claim(
        _quantity_ctx(user_id=user_id),
        request_id=env.request["_id"],
        generation=str(
            env.request["generation"] if generation is None else generation
        ),
        claim_tag=claim_tag,
        taken_card_id=taken_card_id,
        coc_client=SimpleNamespace(),
        mongo=env.mongo,
        bot=env.bot,
    ))


def test_two_concurrent_claims_have_exactly_one_winner(monkeypatch):
    """THE claim guarantee. Both coroutines read the request while it is
    still "open" (the fake account loader yields between the read and the
    CAS), so the only thing separating them is the claiming CAS fenced on
    (status:"open", generation) - which the fake collection honors exactly
    like Mongo does. One winner, always."""
    env = _claim_env(
        monkeypatch,
        claimers=[
            _claimer_inventory(),
            _claimer_inventory(tag="#CL2", discord_id=333, name="Second"),
        ],
        accounts_by_user={
            222: [_claim_account()],
            333: [_claim_account(tag="#CL2", name="Second")],
        },
    )

    async def both():
        return await asyncio.gather(*(
            cards_command._perform_open_request_claim(
                _quantity_ctx(user_id=user_id),
                request_id="req-a",
                generation=str(env.request["generation"]),
                coc_client=SimpleNamespace(), mongo=env.mongo, bot=env.bot,
            )
            for user_id in (222, 333)
        ))

    texts = [_view_text(view) for view in asyncio.run(both())]
    wins = [t for t in texts if "Trade accepted" in t]
    losses = [t for t in texts if "Somebody else just took this one" in t]
    assert len(wins) == 1, "exactly one winner"
    assert len(losses) == 1, "the loser hears it plainly"
    saved = env.trades.docs["req-a"]
    assert saved["status"] == "claimed"
    assert saved["claimed_by_discord_id"] in (222, 333)
    converted = [
        d for d in env.trades.docs.values() if d.get("kind") == "trade"
    ]
    assert len(converted) == 1, "one trade, never two"
    assert saved["trade_id"] == converted[0]["_id"]


def test_stale_wrong_guild_and_self_claims_are_refused(monkeypatch):
    env = _claim_env(monkeypatch)

    stale = _claim(env, generation="123")
    assert "no longer open" in _view_text(stale)

    own = _claim(env, user_id=111)
    own_text = _view_text(own)
    assert "your own request" in own_text.lower()
    assert "My trades" in own_text

    wrong_guild = asyncio.run(cards_command._perform_open_request_claim(
        SimpleNamespace(
            user=SimpleNamespace(id=222), guild_id=2,
            interaction=SimpleNamespace(values=[]),
        ),
        request_id="req-a", generation=str(env.request["generation"]),
        coc_client=SimpleNamespace(), mongo=env.mongo, bot=env.bot,
    ))
    assert "no longer open" in _view_text(wrong_guild)

    assert env.trades.docs["req-a"]["status"] == "open", (
        "refusals change nothing"
    )
    env.trades.docs["req-a"]["status"] = "claiming"
    raced = _claim(env)
    assert "already claimed" in _view_text(raced).lower()
    assert env.rest.messages == [] and env.rest.edits == [], (
        "a refused tap never alters the public post"
    )


def test_an_ineligible_claimer_hears_the_named_reason(monkeypatch):
    no_spare = _claimer_inventory()
    no_spare["cards"]["root_rider"] = cards.OWNED
    env = _claim_env(monkeypatch, claimers=[no_spare])
    text = _view_text(_claim(env))
    assert "no spare" in text and "Root Rider" in text
    assert "#CL" in text, "the refusal names the account"

    paused = _claim_env(
        monkeypatch, claimers=[_claimer_inventory(trading_paused=True)]
    )
    assert "trading paused" in _view_text(_claim(paused))

    unfinished = _claimer_inventory()
    unfinished["complete_categories"] = [
        category.id for category in cards.CATEGORIES
        if category.id != "elixir"
    ]
    behind = _claim_env(monkeypatch, claimers=[unfinished])
    assert "not finished" in _view_text(_claim(behind))

    elsewhere = _claim_env(
        monkeypatch, claimers=[_claimer_inventory(guild_id=2)]
    )
    assert "no card collection in this family" in _view_text(_claim(elsewhere))
    for env in (paused, behind, elsewhere):
        assert env.trades.docs["req-a"]["status"] == "open"
        assert env.rest.messages == [] and env.rest.edits == []


def test_a_failed_conversion_rolls_the_want_ad_back_open(monkeypatch):
    env = _claim_env(monkeypatch)

    async def refuse(_mongo, **_kwargs):
        return None, "That exact proposal is already open in My trades."

    monkeypatch.setattr(cards_command, "_create_trade_request", refuse)
    text = _view_text(_claim(env))
    assert "Could not start this trade" in text
    assert "already open in My trades" in text, "the exact error is shown"
    saved = env.trades.docs["req-a"]
    assert saved["status"] == "open", "the want-ad survives"
    for field in ("claim_token", "claim_until", "claimed_by_discord_id",
                  "claimed_by_tag", "claimed_at"):
        assert field not in saved, field
    # The key was never unset during "claiming", so the round trip could not
    # lose it: the one-request-per-card guard is intact.
    assert saved["open_request_key"] == "1:#ME:root_rider"
    assert env.rest.messages == [] and env.rest.edits == [], (
        "the public post is untouched; the want-ad simply stays up"
    )
    assert [
        d for d in env.trades.docs.values() if d.get("kind") == "trade"
    ] == []


def test_unverifiable_family_clans_roll_the_claim_back(monkeypatch):
    env = _claim_env(monkeypatch, live_clans=None)
    text = _view_text(_claim(env))
    assert "family clans" in text
    assert "stays open" in text
    saved = env.trades.docs["req-a"]
    assert saved["status"] == "open"
    assert "claim_token" not in saved
    assert saved["open_request_key"] == "1:#ME:root_rider"
    assert env.rest.messages == [] and env.rest.edits == []


def test_a_reservation_conflict_leaves_a_saved_pending_proposal(monkeypatch):
    env = _claim_env(monkeypatch)

    async def conflict(_mongo, _trade, **_kwargs):
        return "conflict", "pending"

    monkeypatch.setattr(cards_command, "_accept_trade_reservation", conflict)
    text = _view_text(_claim(env))
    assert "saved" in text.lower() and "My trades" in text
    assert "Accept" in text, "the claimer is told how to retry"
    saved = env.trades.docs["req-a"]
    assert saved["status"] == "claimed", "the request is spent either way"
    converted = [
        d for d in env.trades.docs.values() if d.get("kind") == "trade"
    ]
    assert len(converted) == 1
    trade = converted[0]
    assert trade["status"] == "pending", "NO rollback of the trade"
    assert saved["trade_id"] == trade["_id"]
    # The reused post is edited into the PENDING trade post, whose Accept
    # button is how the claimer retries the reservation later.
    assert len(env.rest.edits) == 1
    edited_ids = [
        n["custom_id"]
        for n in _view_nodes(env.rest.edits[0]["components"])
        if "custom_id" in n
    ]
    assert f"cards_pub_accept:{trade['_id']}" in edited_ids
    # The reply-note still pings the poster - its wording fits a claim that
    # is not yet reserved - but the accepted-trade DM is suppressed: it
    # would announce an acceptance that has not happened yet.
    assert len(env.rest.messages) == 1
    assert env.rest.messages[0]["user_mentions"] == [111]
    assert env.dms.sent == []


def test_a_successful_claim_converts_reuses_the_post_and_pings_the_poster(
    monkeypatch,
):
    env = _claim_env(monkeypatch)
    text = _view_text(_claim(env))
    assert "Trade accepted" in text, "the holder-accept screen, verbatim"

    saved = env.trades.docs["req-a"]
    assert saved["status"] == "claimed"
    assert saved["claimed_by_discord_id"] == 222
    assert saved["claimed_by_tag"] == "#CL"
    assert isinstance(saved["claimed_at"], datetime)
    for field in ("open_request_key", "claim_token", "claim_until"):
        assert field not in saved, field

    converted = [
        d for d in env.trades.docs.values() if d.get("kind") == "trade"
    ]
    assert len(converted) == 1
    trade = converted[0]
    assert saved["trade_id"] == trade["_id"]
    assert trade["requester_tag"] == "#ME", "poster = requester"
    assert trade["holder_tag"] == "#CL", "claimer = holder"
    assert trade["wanted_card_id"] == "root_rider"
    assert trade["given_card_id"] == "wizard"
    assert trade["status"] == "ready", "same live clan: one tap = accepted"
    # The want-ad's message becomes the trade's standing post.
    assert trade["channel_id"] == 999
    assert trade["channel_message_id"] == 555
    assert trade["channel_post_v2"] is True
    assert "channel_post_image" not in trade, "no strip was ever uploaded"

    # Exactly ONE new channel message - the reply-note - pinging exactly the
    # poster, threaded under the reused standing post.
    assert len(env.rest.messages) == 1
    sent = env.rest.messages[0]
    assert sent["user_mentions"] == [111]
    assert sent["reply"] == 555
    note_text = _view_text(sent["components"])
    assert "<@111>" in note_text and "My trades" in note_text
    # The standing post itself is edited in place into the trade post.
    assert len(env.rest.edits) == 1
    assert env.rest.edits[0]["message"] == 555
    assert "Root Rider" in _view_text(env.rest.edits[0]["components"])
    # dm="always" during the live-verification window: the poster's DM.
    assert [recipient for recipient, _ in env.dms.sent] == [111]


def test_a_lost_finalize_fence_never_reuses_the_want_ad_message(monkeypatch):
    """The audit's split-brain case: the claim stalls past its 2-minute
    lease, the recovery sweeper reopens the want-ad, and THEN the claim's
    finalize runs. The trade is real either way - but stamping the want-ad's
    message ids onto it anyway would make one channel message serve two live
    documents: the reopened request loses its board post, and the 48-hour
    expiry job would eventually paint "expired" over a live trade's post.
    A lost fence now means no reuse: the trade simply has no standing post
    yet, and the reply-note lands as an ordinary message."""
    env = _claim_env(monkeypatch)
    real_reserve = cards_command._accept_trade_reservation

    async def reserve_then_sweeper_reclaims(mongo, trade, **kwargs):
        outcome = await real_reserve(mongo, trade, **kwargs)
        # What _recover_stalled_claims does to a stale "claiming" doc,
        # landing in the gap before this claim's finalize.
        reclaimed = env.trades.docs["req-a"]
        reclaimed["status"] = "open"
        for field in (
            "claim_token", "claim_until", "claimed_by_discord_id",
            "claimed_by_tag", "claimed_at",
        ):
            reclaimed.pop(field, None)
        return outcome

    monkeypatch.setattr(
        cards_command, "_accept_trade_reservation",
        reserve_then_sweeper_reclaims,
    )
    text = _view_text(_claim(env))
    assert "Trade accepted" in text, "the claimer's trade is still real"

    assert env.trades.docs["req-a"]["status"] == "open", (
        "whoever holds the fence owns the want-ad - it stays reopened"
    )
    trade = next(
        d for d in env.trades.docs.values() if d.get("kind") == "trade"
    )
    for field in ("channel_id", "channel_message_id", "channel_post_v2"):
        assert field not in trade, (
            f"{field}: the reopened want-ad's message must not be reused"
        )
    assert env.rest.edits == [], "the want-ad's post is left untouched"
    assert len(env.rest.messages) == 1, "the reply-note still lands"
    assert env.rest.messages[0]["user_mentions"] == [111]
    assert env.rest.messages[0].get("reply") is None, (
        "no standing post to thread under"
    )


def test_a_multi_account_claim_gets_a_sections_picker_then_proceeds(
    monkeypatch,
):
    # The picker itself is an EPHEMERAL followup. Its buttons follow the
    # frozen public pattern: cards_pub_claim_as is registered no_return=True
    # too (pinned by test_every_public_cards_action_is_no_return) and
    # answers with a fresh followup of its own - the dispatcher must never
    # edit a message on behalf of a cards_pub_* click.
    env = _claim_env(
        monkeypatch,
        claimers=[
            _claimer_inventory(),
            _claimer_inventory(tag="#CL2", discord_id=222, name="Second Way"),
        ],
        accounts_by_user={222: [
            _claim_account(),
            _claim_account(tag="#CL2", name="Second Way"),
        ]},
    )
    picker = _claim(env)
    _assert_discord_payload(picker)
    nodes = _view_nodes(picker)
    ids = [n["custom_id"] for n in nodes if "custom_id" in n]
    generation = env.request["generation"]
    assert ids == [
        f"cards_pub_claim_as:req-a|{generation}|#CL",
        f"cards_pub_claim_as:req-a|{generation}|#CL2",
    ]
    for custom_id in ids:
        assert custom_id.count(":") == 1, "one colon per custom_id"
    sections = [
        n for n in nodes
        if n.get("type") == int(hikari.ComponentType.SECTION)
    ]
    assert len(sections) == 2, "a row of things is Sections, not a select"
    assert env.trades.docs["req-a"]["status"] == "open", (
        "a picker screen never holds the lock"
    )

    done = _claim(env, claim_tag="#CL2")
    assert "Trade accepted" in _view_text(done)
    assert env.trades.docs["req-a"]["claimed_by_tag"] == "#CL2"


def test_a_forged_or_stale_picker_tag_is_refused_with_the_reason(monkeypatch):
    env = _claim_env(monkeypatch)
    stranger = _claim(env, claim_tag="#SOMEBODY")
    assert "no longer claim" in _view_text(stranger).lower()
    assert env.trades.docs["req-a"]["status"] == "open"


def test_a_multi_card_claim_gets_a_chooser_then_takes_that_card(monkeypatch):
    poster = _open_requester_inventory()
    poster["cards"]["dragon"] = cards.DUPLICATE
    env = _claim_env(
        monkeypatch,
        poster=poster,
        claimers=[_claimer_inventory(missing=("wizard", "dragon"))],
    )
    chooser = _claim(env)
    _assert_discord_payload(chooser)
    menus = [n for n in _view_nodes(chooser) if "options" in n]
    assert len(menus) == 1
    generation = env.request["generation"]
    assert menus[0]["custom_id"] == f"cards_pub_take:req-a|{generation}|#CL"
    assert [
        str(option["value"]) for option in menus[0]["options"]
    ] == ["wizard", "dragon"], "the values ARE the card ids"
    assert env.trades.docs["req-a"]["status"] == "open", (
        "the chooser never holds the lock either"
    )

    # Answer through the real adapter, the way the select fires it: the
    # card id rides in the interaction values, and the reply is an
    # ephemeral followup (cards_pub_take is no_return=True like the rest).
    followups = []

    class Interaction:
        values = ["dragon"]

        async def execute(self, **kwargs):
            followups.append(kwargs)

    asyncio.run(cards_command.cards_pub_take(
        SimpleNamespace(
            guild_id=1, user=SimpleNamespace(id=222),
            interaction=Interaction(),
        ),
        f"req-a|{generation}|#CL",
        coc_client=SimpleNamespace(), mongo=env.mongo, bot=env.bot,
    ))
    assert len(followups) == 1
    assert followups[0]["flags"] & hikari.MessageFlag.EPHEMERAL
    assert "Trade accepted" in _view_text(followups[0]["components"])
    trade = next(
        d for d in env.trades.docs.values() if d.get("kind") == "trade"
    )
    assert trade["given_card_id"] == "dragon", "the poster gives that card"


def test_an_emptied_give_back_list_refuses_the_claim(monkeypatch):
    # The poster's only listed spare is gone, so there is nothing to take.
    poster = _open_requester_inventory()
    poster["cards"]["wizard"] = cards.OWNED
    env = _claim_env(monkeypatch, poster=poster)
    text = _view_text(_claim(env))
    assert "Their spares changed; nothing to take." in text
    assert env.trades.docs["req-a"]["status"] == "open"


def test_the_claimed_note_pings_the_poster_and_escapes_the_name():
    trade = _standing_post_trade(holder_name="Weird*_Name person")
    note = cards_command._claimed_channel_note(trade)
    _assert_discord_payload(note)
    text = _view_text(note)
    assert text.startswith("✅ <@111>"), "addressed to the poster, who pings"
    assert "has your **Root Rider**" in text
    assert "You give: **Wizard**" in text
    assert "You get: **Root Rider**" in text
    assert "`/cards` → **My trades**" in text
    assert "Weird\\*\\_Name" in text, "the claimer's name is escaped"
    assert not [n for n in _view_nodes(note) if "custom_id" in n], (
        "the note carries no controls; the standing post above it does"
    )


def test_holders_view_offers_post_a_request_only_with_a_spare():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    # The headline case: nobody holds the card at all.
    view = cards_command._holders_view(
        account, "root_rider", [], can_request=True
    )
    ids = [n["custom_id"] for n in _view_nodes(view) if "custom_id" in n]
    assert "cards_req_new:#ME|root_rider" in ids
    assert "Post a request" in _view_labels(view)
    without = cards_command._holders_view(account, "root_rider", [])
    assert not any(
        i.startswith("cards_req_new:")
        for n in [None]
        for i in [
            str(node["custom_id"])
            for node in _view_nodes(without)
            if "custom_id" in node
        ]
    ), "no spare, no button - the request would only be refused"

    # The gem branch: holders exist but none can be asked. The same button
    # rides beside the existing guidance, same precondition.
    inventory = _complete_inventory()
    inventory["cards"]["balloon"] = cards.MISSING
    holder = _complete_inventory(tag="#H", clan_tag="#HOME")
    holder["cards"]["balloon"] = cards.DUPLICATE
    holder["discord_id"] = 9
    holders = cards.holders_for_card(inventory, [holder], "balloon")
    gem_view = cards_command._holders_view(
        account, "balloon", holders, can_request=True
    )
    gem_text = _view_text(gem_view)
    gem_ids = [
        n["custom_id"] for n in _view_nodes(gem_view) if "custom_id" in n
    ]
    assert "What to do now" in gem_text
    assert "cards_req_new:#ME|balloon" in gem_ids
    plain = cards_command._holders_view(account, "balloon", holders)
    assert not any(
        str(n.get("custom_id", "")).startswith("cards_req_new:")
        for n in _view_nodes(plain)
    )


def test_matches_view_offers_the_request_picker_whenever_a_spare_exists():
    """Post a request is always on the board, not only when the matcher
    comes up empty - the owner wants a want-ad possible without naming a
    person. PRIMARY only when there is nothing else to do; beside live
    matches it goes grey, because the swap picker is the one primary thing.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    with_spare = _complete_inventory()
    with_spare["cards"]["root_rider"] = cards.MISSING
    with_spare["cards"]["wizard"] = cards.DUPLICATE
    view = cards_command._matches_view(account, with_spare, [])
    nodes = _view_nodes(view)
    ids = [n["custom_id"] for n in nodes if "custom_id" in n]
    assert "cards_req_pick:#ME" in ids
    empty_style = next(
        n["style"] for n in nodes
        if n.get("custom_id") == "cards_req_pick:#ME"
    )
    assert empty_style == hikari.ButtonStyle.PRIMARY

    match = cards.CardMatch(
        holder_tag="#HOLDER", holder_name="Holder",
        holder_discord_id=222, holder_clan_tag="#HOME",
        holder_clan_name="Home Clan",
        exchanges=(cards.CategoryExchange(
            "elixir", ("root_rider",), ("wizard",),
        ),),
        same_clan=True,
        confirmed_at=datetime.now(timezone.utc),
    )
    busy = cards_command._matches_view(account, with_spare, [match])
    busy_nodes = _view_nodes(busy)
    busy_style = next(
        n["style"] for n in busy_nodes
        if n.get("custom_id") == "cards_req_pick:#ME"
    )
    assert busy_style == hikari.ButtonStyle.SECONDARY, (
        "beside live matches the want-ad is the quieter option"
    )

    no_spare = _complete_inventory()
    no_spare["cards"]["root_rider"] = cards.MISSING
    bare = cards_command._matches_view(account, no_spare, [])
    assert not any(
        str(n.get("custom_id", "")).startswith("cards_req_pick:")
        for n in _view_nodes(bare)
    ), "without a spare the picker would be empty and the post refused"


def test_the_request_picker_draws_one_menu_per_requestable_category():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"].update({
        "root_rider": cards.MISSING,   # elixir: missing with a spare
        "wizard": cards.DUPLICATE,
        "hog_rider": cards.MISSING,    # dark elixir: missing, NO spare
    })
    requestable = cards_command._requestable_card_ids(inventory)
    assert "root_rider" in requestable
    assert "hog_rider" not in requestable, "no dark-elixir spare to give back"

    view = cards_command._open_request_picker_view(account, requestable)
    _assert_discord_payload(view)
    ids = [n["custom_id"] for n in _view_nodes(view) if "custom_id" in n]
    assert "cards_req_new:#ME|elixir" in ids
    assert "cards_req_new:#ME|dark_elixir" not in ids


def test_a_picker_choice_opens_the_consent_screen_for_that_card(monkeypatch):
    account = Account(
        tag="#ME", name="Shaun", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=17,
    )
    box = {"inventory": _open_requester_inventory()}

    async def load_target(_ctx, tag, **_kwargs):
        assert cards_command._normalize_tag(tag) == "#ME"
        return account, box["inventory"], None

    monkeypatch.setattr(cards_command, "_load_target", load_target)

    # The select form: the category rides in the id, the card in the values.
    view = asyncio.run(cards_command.cards_req_new(
        _quantity_ctx(user_id=111, values=["root_rider"]), "#ME|elixir",
        coc_client=SimpleNamespace(), mongo=SimpleNamespace(),
    ))
    text = _view_text(view)
    assert "Root Rider" in text
    assert "for everyone to see" in text, "consent before publication"
    assert "48 hours" in text
    assert "Wizard" in text, "the full give-back list is stated"
    ids = [n["custom_id"] for n in _view_nodes(view) if "custom_id" in n]
    assert "cards_req_post:#ME|root_rider" in ids

    # The button form carries the card directly.
    button_view = asyncio.run(cards_command.cards_req_new(
        _quantity_ctx(user_id=111), "#ME|root_rider",
        coc_client=SimpleNamespace(), mongo=SimpleNamespace(),
    ))
    assert "cards_req_post:#ME|root_rider" in [
        n["custom_id"] for n in _view_nodes(button_view) if "custom_id" in n
    ]

    # The art-bearing header option is a no-op, not an error.
    assert asyncio.run(cards_command.cards_req_new(
        _quantity_ctx(
            user_id=111, values=[cards_command.CATEGORY_HEADER_VALUE]
        ),
        "#ME|elixir",
        coc_client=SimpleNamespace(), mongo=SimpleNamespace(),
    )) is None

    # A spare-less member is routed to the gem ask instead.
    box["inventory"] = _open_requester_inventory()
    box["inventory"]["cards"]["wizard"] = cards.OWNED
    refusal = asyncio.run(cards_command.cards_req_new(
        _quantity_ctx(user_id=111), "#ME|root_rider",
        coc_client=SimpleNamespace(), mongo=SimpleNamespace(),
    ))
    assert "Ask for help" in _view_text(refusal)


def test_posting_a_request_delivers_through_the_funnel(monkeypatch):
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    account = Account(
        tag="#ME", name="Shaun", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=17,
    )

    async def load_target(_ctx, tag, **_kwargs):
        assert cards_command._normalize_tag(tag) == "#ME"
        return account, _open_requester_inventory(), None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    delivered = []

    async def deliver_soon(_bot, _mongo, document, *, event, **_kwargs):
        delivered.append((document["_id"], event))
        return cards_command._Delivery(channel_message_id=777)

    monkeypatch.setattr(cards_command, "_deliver_soon", deliver_soon)
    trades = _FakeTradeCollection()

    view = asyncio.run(cards_command.cards_req_post(
        _quantity_ctx(user_id=111), "#ME|root_rider",
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(card_trades=trades),
        bot=SimpleNamespace(),
    ))

    assert delivered and delivered[0][1] == "open_request_posted", (
        "one funnel decides delivery, and this is its event name"
    )
    saved = trades.docs[delivered[0][0]]
    assert saved["kind"] == "open_request"
    text = _view_text(view)
    assert "<#999>" in text, "the feedback names the channel"
    assert "Nobody is pinged" in text


class _FakeInventoryCollection:
    def __init__(self, documents, *, lose_reservation_before_card_write=()):
        self.documents = {document["_id"]: document for document in documents}
        self.update_calls = 0
        self.lose_reservation_before_card_write = set(
            lose_reservation_before_card_write
        )

    async def find_one(self, query):
        return next(
            (document for document in self.documents.values()
             if _matches_query(document, query)),
            None,
        )

    async def update_one(self, query, update, upsert=False):
        document = self.documents.get(query["_id"])
        if document is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        card_write = any(
            path.startswith("cards.") for path in update.get("$set", {})
        )
        if card_write and document["_id"] in self.lose_reservation_before_card_write:
            document["card_trade_reservations"]["root_rider"] = (
                "taken-over-trade:token"
            )
            self.lose_reservation_before_card_write.remove(document["_id"])
        if not _matches_query(document, query):
            return SimpleNamespace(matched_count=0, modified_count=0)
        _apply_update(document, update)
        if card_write:
            self.update_calls += 1
        return SimpleNamespace(matched_count=1, modified_count=1)

    async def update_many(self, query, update):
        matched = 0
        for document in self.documents.values():
            if _matches_query(document, query):
                matched += 1
                _apply_update(document, update)
        return SimpleNamespace(matched_count=matched, modified_count=matched)


class _FakeCategoryCollection:
    def __init__(self, document):
        self.document = document

    async def find_one(self, query):
        return self.document if _matches_query(self.document, query) else None

    async def update_one(self, query, update, upsert=False):
        if not _matches_query(self.document, query):
            return SimpleNamespace(matched_count=0, modified_count=0)
        _apply_update(self.document, update)
        for field, operation in update.get("$addToSet", {}).items():
            values = operation.get("$each", []) if isinstance(operation, dict) else [operation]
            target = self.document.setdefault(field, [])
            for value in values:
                if value not in target:
                    target.append(value)
        for field, value in update.get("$setOnInsert", {}).items():
            self.document.setdefault(field, value)
        return SimpleNamespace(matched_count=1, modified_count=1)


def test_final_manual_card_automatically_makes_the_category_matchable():
    """Manual trust opens matching in the same write as the final count."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    elixir_ids = [card.id for card in cards.CATEGORY_CARDS["elixir"]]
    document = {
        "_id": "#ME",
        "inventory_revision": 0,
        "cards": {card_id: cards.OWNED for card_id in elixir_ids}
        | {"root_rider": cards.MISSING, "wizard": 3},
        "trusted_card_ids": [
            card_id for card_id in elixir_ids if card_id != "root_rider"
        ],
        "complete_categories": [],
        "reviewed_lists": [],
        "confirmed_at": datetime.now(timezone.utc),
    }
    partner = {
        "_id": "#YOU",
        "player_name": "Partner",
        "cards": {"root_rider": cards.DUPLICATE, "wizard": cards.MISSING},
        "complete_categories": ["elixir"],
        "confirmed_at": datetime.now(timezone.utc),
    }
    mongo = SimpleNamespace(card_inventories=_FakeCategoryCollection(document))
    cards_command._inventory_locks.clear()

    assert cards.find_matches(document, [partner]) == []

    updated = asyncio.run(cards_command._write_card_state(
        mongo, account, document, "root_rider", cards.MISSING,
        expected_revision=0, discord_id=123, guild_id=456,
    ))

    assert updated["complete_categories"] == ["elixir"]
    assert set(updated["trusted_card_ids"]) == set(elixir_ids)
    assert set(updated["reviewed_lists"]) == {
        "elixir:missing", "elixir:duplicates",
    }
    assert updated["cards"]["root_rider"] == cards.MISSING
    assert updated["cards"]["wizard"] == 3
    assert cards.find_matches(updated, [partner]), "final count should open matching"


def test_legacy_ready_v1_manifest_is_frozen_to_the_launch_catalog():
    """Freeze the historical trust boundary from f4ca757 (2026-08-10)."""
    expected = {
        "elixir": frozenset({
            "barbarian", "archer", "giant", "goblin", "wall_breaker",
            "balloon", "wizard", "healer", "dragon", "pekka",
            "baby_dragon", "miner", "electro_dragon", "yeti",
            "dragon_rider", "electro_titan", "root_rider", "thrower",
            "meteor_golem",
        }),
        "dark_elixir": frozenset({
            "minion", "hog_rider", "valkyrie", "golem", "witch",
            "lava_hound", "bowler", "ice_golem", "headhunter",
            "apprentice_warden", "druid", "furnace", "rubble_witch",
        }),
        "builder_base": frozenset({
            "raged_barbarian", "sneaky_archer", "boxer_giant",
            "beta_minion", "bomber", "bb_baby_dragon", "cannon_cart",
            "night_witch", "drop_ship", "power_pekka", "hog_glider",
        }),
        "super_troop": frozenset({
            "super_barbarian", "super_archer", "super_giant",
            "sneaky_goblin", "super_wall_breaker", "rocket_balloon",
            "super_wizard", "super_dragon", "inferno_dragon",
            "super_miner", "super_yeti", "super_minion",
            "super_hog_rider", "super_valkyrie", "super_witch",
            "ice_hound", "super_bowler",
        }),
    }
    expected_counts = {
        "elixir": 19,
        "dark_elixir": 13,
        "builder_base": 11,
        "super_troop": 17,
    }
    expected_categories = {
        "elixir", "dark_elixir", "builder_base", "super_troop",
    }
    actual = cards_command._LEGACY_READY_CARD_IDS_V1_BY_CATEGORY

    assert set(expected) == expected_categories
    assert set(actual) == expected_categories
    assert {
        key: len(value) for key, value in actual.items()
    } == expected_counts
    all_ids = [card_id for card_ids in actual.values() for card_id in card_ids]
    assert len(all_ids) == 60
    assert len(set(all_ids)) == 60
    assert actual == expected


def test_a_historical_ready_inventory_is_trusted_and_stays_ready_when_edited():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    # No trusted_card_ids: this is the legacy shape already in production.
    document = _complete_inventory()
    document["inventory_revision"] = 0
    mongo = SimpleNamespace(card_inventories=_FakeCategoryCollection(document))
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_card_state(
        mongo, account, document, "wizard", 4,
        expected_revision=0, discord_id=1, guild_id=1,
    ))

    assert set(updated["trusted_card_ids"]) == {card.id for card in cards.CARDS}
    assert set(updated["complete_categories"]) == {
        category.id for category in cards.CATEGORIES
    }
    assert updated["cards"]["wizard"] == 4


def test_a_historical_ambiguous_partial_inventory_fails_closed():
    document = {
        "_id": "#ME",
        "cards": {"wizard": cards.DUPLICATE, "dragon": cards.MISSING},
        "complete_categories": [],
        # This legacy marker proves only Wizard was explicitly entered.
        "count_confirmed_card_ids": ["wizard"],
    }

    assert cards_command._trusted_card_ids(document) == {"wizard"}
    assert "dragon" in cards_command._untrusted_card_ids(document)
    trusted, ready, reviewed = cards_command._trust_projection(document)
    assert trusted == ["wizard"]
    assert ready == []
    assert reviewed == []


def test_safe_legacy_exact_counts_materialize_automatic_readiness():
    elixir_ids = [card.id for card in cards.CATEGORY_CARDS["elixir"]]
    document = {
        "_id": "#ME",
        "cards": {card_id: cards.OWNED for card_id in elixir_ids},
        "complete_categories": [],
        "reviewed_lists": [],
        "count_confirmed_card_ids": list(elixir_ids),
        "inventory_revision": 0,
    }
    mongo = SimpleNamespace(
        card_inventories=_FakeCategoryCollection(document)
    )

    materialized = asyncio.run(
        cards_command._materialize_legacy_trust(mongo, document)
    )

    assert materialized["trusted_card_ids"] == elixir_ids
    assert materialized["complete_categories"] == ["elixir"]
    assert set(materialized["reviewed_lists"]) == {
        "elixir:missing", "elixir:duplicates",
    }
    assert materialized["inventory_revision"] == 1


def test_legacy_ready_hidden_badge_stays_untrusted_and_reopens_its_category():
    document = _complete_inventory()
    document.pop("trusted_card_ids", None)
    document["scan_duplicate_unverified_card_ids"] = ["wizard"]
    document["inventory_revision"] = 0
    mongo = SimpleNamespace(
        card_inventories=_FakeCategoryCollection(document)
    )

    materialized = asyncio.run(
        cards_command._materialize_legacy_trust(mongo, document)
    )

    assert "wizard" not in materialized["trusted_card_ids"]
    assert "elixir" not in materialized["complete_categories"]
    assert set(materialized["complete_categories"]) == {
        "dark_elixir", "builder_base", "super_troop",
    }


def test_legacy_ready_does_not_trust_a_future_catalog_card(monkeypatch):
    """The V1 compatibility boundary must not expand with the live catalog."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document.pop("trusted_card_ids", None)
    document["inventory_revision"] = 0
    mongo = SimpleNamespace(
        card_inventories=_FakeCategoryCollection(document)
    )
    original_elixir_ids = {
        card.id for card in cards_command.CATEGORY_CARDS["elixir"]
    }
    future = cards.Card(
        "future_elixir", "Future Elixir", "elixir",
        len(cards_command.CATEGORY_CARDS["elixir"]) + 1,
    )
    monkeypatch.setattr(cards_command, "CARDS", (*cards_command.CARDS, future))
    monkeypatch.setattr(
        cards_command, "CARD_BY_ID",
        {**cards_command.CARD_BY_ID, future.id: future},
    )
    monkeypatch.setitem(
        cards_command.CATEGORY_CARDS, "elixir",
        (*cards_command.CATEGORY_CARDS["elixir"], future),
    )
    cards_command._inventory_locks.clear()

    materialized = asyncio.run(
        cards_command._materialize_legacy_trust(mongo, document)
    )

    assert original_elixir_ids <= set(materialized["trusted_card_ids"])
    assert future.id not in materialized["trusted_card_ids"]
    assert "elixir" not in materialized["complete_categories"]

    unrelated = asyncio.run(cards_command._write_card_state(
        mongo, account, materialized, "wizard", 4,
        expected_revision=1, discord_id=1, guild_id=1,
    ))
    assert future.id not in unrelated["trusted_card_ids"]
    assert "elixir" not in unrelated["complete_categories"]

    confirmed = asyncio.run(cards_command._write_card_state(
        mongo, account, unrelated, future.id, cards.OWNED,
        expected_revision=2, discord_id=1, guild_id=1,
    ))
    assert future.id in confirmed["trusted_card_ids"]
    assert "elixir" in confirmed["complete_categories"]


def test_one_reserved_card_no_longer_locks_the_rest_of_its_category():
    """The whole category used to be refused, which the new editor need not do.

    A whole-category select menu rewrote every card at once, so a single held
    card had to block all nineteen. Writes are now per card, so only the held
    card is refused - including when the card being edited sits in the same
    category as it.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trade = _trade_document()
    trade["reservation_token"] = "token-a"
    document = _reserve_inventory({
        "_id": "#ME",
        "cards": {},
        "complete_categories": [],
        "reviewed_lists": [],
        "inventory_revision": 0,
    }, trade)
    reserved_id = next(iter(cards_command._card_reservations(document)))
    same_category = next(
        card.id
        for card in cards.CATEGORY_CARDS[cards.CARD_BY_ID[reserved_id].category]
        if card.id != reserved_id
    )
    mongo = SimpleNamespace(card_inventories=_FakeCategoryCollection(document))
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_card_state(
        mongo, account, document, same_category, cards.DUPLICATE,
        expected_revision=0, discord_id=123, guild_id=1,
    ))
    assert updated["cards"][same_category] == cards.DUPLICATE
    assert same_category in updated["trusted_card_ids"]

    trusted_before = list(updated["trusted_card_ids"])
    revision_before = updated["inventory_revision"]
    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_card_state(
            mongo, account, updated, reserved_id, cards.MISSING,
            expected_revision=cards_command._inventory_revision_value(updated),
            discord_id=123, guild_id=1,
        ))
    assert reserved_id not in updated["cards"]
    assert updated["trusted_card_ids"] == trusted_before
    assert updated["inventory_revision"] == revision_before


def test_the_whole_category_is_visible_on_one_screen():
    """No pagination, because none is needed.

    The biggest category is nineteen cards against Discord's limit of
    twenty-five select options, so every card fits one menu and every count
    fits one text component. The paged version showed six at a time and hid
    thirteen.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    for category in cards.CATEGORIES:
        definitions = cards.CATEGORY_CARDS[category.id]
        assert len(definitions) <= 25, (
            f"{category.id} would no longer fit one select menu"
        )
        view = cards_command._quantity_editor(
            account,
            {"_id": "#ME", "cards": {}, "complete_categories": []},
            category.id,
        )
        text = _view_text(view)
        for card in definitions:
            assert card.name in text, f"{card.name} missing from {category.id}"

        menus = {
            str(n["custom_id"]).split(":")[0]: n
            for n in _view_nodes(view) if n.get("type") == 3
        }
        assert set(menus) == {"cards_qcat", "cards_qpick"}
        values = [str(o["value"]) for o in menus["cards_qpick"]["options"]]
        assert values == [card.id for card in definitions]
        # The category menu offers all four, so switching category never
        # needs a separate screen.
        assert [str(o["value"]) for o in menus["cards_qcat"]["options"]] == [
            c.id for c in cards.CATEGORIES
        ]

        # Every count sits in an inline code span, which Discord draws as a
        # small shaded box. That is what separates name from number, so the
        # row needs no bullet, no spacer emoji and no alignment.
        listing_text = next(
            str(n["content"]) for n in _view_nodes(view)
            if n.get("type") == 10
            and all(card.name in str(n["content"]) for card in definitions)
        )
        for line in listing_text.splitlines():
            if not line.strip():
                continue
            assert not line.startswith("- "), f"bullet came back: {line}"
        for card in definitions:
            assert (
                f"{card.name} · `" in listing_text
                or f"{card.name}** · `" in listing_text
            ), f"{card.name} lost its boxed count"

        # And the counts are one component, not one per card.
        listings = [
            n for n in _view_nodes(view)
            if n.get("type") == 10
            and all(card.name in str(n["content"]) for card in definitions)
        ]
        assert len(listings) == 1, "every quantity belongs to a single Text node"


def test_only_one_set_of_step_buttons_exists_for_the_whole_category():
    """The point of the shared controller.

    Six cards each carrying their own -1/+1 pair put twelve large buttons on a
    phone screen and still showed only six of nineteen cards.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._quantity_editor(
        account,
        {"_id": "#ME", "cards": {}, "complete_categories": []},
        "elixir",
    )
    custom_ids = [
        str(n["custom_id"]) for n in _view_nodes(view) if "custom_id" in n
    ]
    # Nothing selected yet, so there is nothing to act on and no controls are
    # drawn. They were briefly rendered disabled instead; three greyed-out
    # buttons under an empty menu read as broken rather than as waiting.
    assert not [cid for cid in custom_ids if cid.startswith("cards_qstep:")]
    assert not [cid for cid in custom_ids if cid.startswith("cards_qnum:")]
    # Same verb as the menu placeholder ("Choose a card to edit").
    assert "Choose a card below to change how many you have." in _view_text(view)

    # Pick a card and exactly one set of controls appears, aimed at it.
    chosen = cards.CATEGORY_CARDS["elixir"][4]
    picked = cards_command._quantity_editor(
        account,
        {"_id": "#ME", "cards": {}, "complete_categories": []},
        "elixir",
        card_id=chosen.id,
    )
    picked_ids = [
        str(n["custom_id"]) for n in _view_nodes(picked) if "custom_id" in n
    ]
    steps = [cid for cid in picked_ids if cid.startswith("cards_qstep:")]
    assert steps == [
        f"cards_qstep:#ME|{chosen.id}|-1",
        f"cards_qstep:#ME|{chosen.id}|1",
    ]
    assert picked_ids.count(f"cards_qnum:#ME|{chosen.id}") == 1
    # Set number is spelled out rather than hidden behind tapping the count.
    assert "Set number" in _view_labels(picked)
    # Trust is established by entering counts; there is no separate Ready tap.
    assert not any(cid.startswith("cards_ready:") for cid in custom_ids)
    assert "tap **Ready to trade**" not in _view_text(view)


def test_the_category_screen_never_renders_a_manual_ready_button():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    done = cards_command._quantity_editor(
        account, _complete_inventory(), "elixir",
    )
    ids = [str(n["custom_id"]) for n in _view_nodes(done) if "custom_id" in n]
    assert not any(custom_id.startswith("cards_ready:") for custom_id in ids)
    assert "Ready to trade." in _view_text(done)
    assert "Other players can see these spares." in _view_text(done)

    unfinished = cards_command._quantity_editor(
        account,
        {"_id": "#ME", "cards": {}, "complete_categories": []},
        "elixir",
    )
    unfinished_ids = [
        str(node["custom_id"])
        for node in _view_nodes(unfinished)
        if "custom_id" in node
    ]
    unfinished_text = _view_text(unfinished)
    assert not any(
        custom_id.startswith("cards_ready:") for custom_id in unfinished_ids
    )
    assert "tap **Ready to trade**" not in unfinished_text
    assert "still need" in unfinished_text


def test_every_rendered_custom_id_parses_back_to_what_drew_it():
    """The ids are split by hand, so parse the rendered ones, not a guess.

    Shipping a button whose id its handler could not read has happened twice on
    this command, both times because the test built the id itself.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    for category in cards.CATEGORIES:
        for card in cards.CATEGORY_CARDS[category.id]:
            view = cards_command._quantity_editor(
                account,
                {"_id": "#ME", "cards": {}, "complete_categories": []},
                category.id,
                card_id=card.id,
            )
            for node in _view_nodes(view):
                custom_id = str(node.get("custom_id", ""))
                head, _, rest = custom_id.partition(":")
                if head in ("cards_qstep", "cards_qnum"):
                    tag, parsed, delta = cards_command._parse_quantity_card(rest)
                    assert tag == "#ME", custom_id
                    assert parsed == card.id, custom_id
                    if head == "cards_qstep":
                        assert delta in (1, -1), custom_id
                elif head == "cards_qpick":
                    tag, parsed, _card = cards_command._parse_quantity_target(rest)
                    assert tag == "#ME", custom_id
                    assert parsed == category.id, custom_id


def test_a_stale_paged_custom_id_still_opens_the_new_screen():
    """Panels sent by the paged build must not answer "out of date".

    Those ids carried a trailing page number - cards_qty:#ME|elixir|2 and
    cards_qstep:#ME|barbarian|1|2. The extra field is tolerated and ignored,
    and the two retired names are registered as aliases.
    """
    from extensions.components import _resolve

    for retired in ("cards_qty", "cards_qjump"):
        assert _resolve(retired) is not None, retired

    tag, category_id, card_id = cards_command._parse_quantity_target(
        "#ME|elixir|2"
    )
    assert (tag, category_id, card_id) == ("#ME", "elixir", None)

    tag, parsed, delta = cards_command._parse_quantity_card("#ME|barbarian|1|2")
    assert (tag, parsed, delta) == ("#ME", "barbarian", 1)


def test_an_unknown_card_selects_nothing_rather_than_guessing():
    """The menu can then say "Choose a card to edit" instead of naming one.

    Falling back to the first card would have put a real card's number under
    controls the member never aimed at anything.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    for bogus in (None, "", "not_a_card", "night_witch"):
        # night_witch is real but belongs to another category, so it must not
        # be editable from the elixir screen.
        assert cards_command._quantity_selected("elixir", bogus) is None, bogus
        view = cards_command._quantity_editor(
            account,
            {"_id": "#ME", "cards": {}, "complete_categories": []},
            "elixir",
            card_id=bogus,
        )
        menu = next(n for n in _view_nodes(view) if n.get("type") == 3
                    and str(n.get("custom_id", "")).startswith("cards_qpick:"))
        assert not any(o.get("default") for o in menu["options"]), bogus
        # With no default option, the placeholder is what Discord draws.
        assert menu["placeholder"] == "Choose a card to edit"


def test_a_dm_can_answer_a_trade_but_a_stranger_cannot(monkeypatch):
    """Participation is the gate, not which server you clicked from.

    Requiring the family server meant a proposal delivered by DM could not be
    answered in that DM. What stops abuse is that every handler checks you are
    the requester or the holder, which a forged id cannot satisfy.
    """
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 123)

    looked_up: list[dict] = []

    class Trades:
        async def find_one(self, query):
            looked_up.append(query)
            return None

    mongo = SimpleNamespace(card_trades=Trades())
    # guild_id is None: this is a DM.
    ctx = SimpleNamespace(guild_id=None, user=SimpleNamespace(id=1))

    result = asyncio.run(cards_command.cards_trade_accept(
        ctx, "some-trade-id",
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    # It got past the scope check and searched, rather than refusing outright.
    assert looked_up, "a DM interaction was blocked before reaching the trade"
    # And it searched the configured family, not the (absent) DM guild.
    assert looked_up[0]["guild_id"] == 123
    # An id that matches nothing is simply not found. No write, no damage.
    assert result


def test_a_trade_action_is_refused_to_anyone_but_its_two_players(monkeypatch):
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 123)
    trade = _trade_document()
    trade.update({
        "status": "pending",
        "requester_discord_id": 111,
        "holder_discord_id": 222,
    })

    class Trades:
        async def find_one(self, _query):
            return dict(trade)

    async def _unchanged(_mongo, doc, **_kwargs):
        return dict(doc)

    monkeypatch.setattr(
        cards_command, "_expire_trade_if_needed", _unchanged
    )
    mongo = SimpleNamespace(card_trades=Trades())
    stranger = SimpleNamespace(guild_id=123, user=SimpleNamespace(id=999))

    result = asyncio.run(cards_command.cards_trade_cancel(
        stranger, trade["_id"],
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    assert "not yours" in _view_text(result).lower()




def test_allowed_guild_trade_lookup_is_scoped_to_that_guild(monkeypatch):
    class Trades:
        def __init__(self):
            self.query = None

        async def find_one(self, query):
            self.query = query
            return None

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 123)
    trades = Trades()
    ctx = SimpleNamespace(guild_id=123, user=SimpleNamespace(id=1))
    result = asyncio.run(cards_command.cards_trade_accept(
        ctx,
        "foreign-trade-id",
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(card_trades=trades),
        bot=SimpleNamespace(),
    ))

    assert result
    assert trades.query == {
        "_id": "foreign-trade-id",
        "kind": "trade",
        "guild_id": 123,
    }


def test_candidate_search_fails_closed_without_guild_or_configured_family_clans():
    """No guild is an empty result; a broken family boundary is a refusal.

    The distinction matters to the player: an empty list renders as "nobody
    has a spare", which is a false claim during a clans-database blip, so the
    boundary failure now raises and the caller says the search failed.
    """
    class Clans:
        async def distinct(self, field):
            assert field == "tag"
            return []

    class BrokenClans:
        async def distinct(self, field):
            raise RuntimeError("clans lookup down")

    class Inventories:
        def find(self, _query):
            raise AssertionError("inventory search must not broaden without family tags")

    mongo = SimpleNamespace(clans=Clans(), card_inventories=Inventories())
    requester = _complete_inventory()

    assert asyncio.run(cards_command._candidate_inventories(
        mongo, requester, guild_id=None
    )) == []
    with pytest.raises(cards_command.CandidateLookupUnavailable):
        asyncio.run(cards_command._candidate_inventories(
            mongo, requester, guild_id=123
        ))
    broken = SimpleNamespace(clans=BrokenClans(), card_inventories=Inventories())
    with pytest.raises(cards_command.CandidateLookupUnavailable):
        asyncio.run(cards_command._candidate_inventories(
            broken, requester, guild_id=123
        ))


def test_candidate_search_sanitizes_unopened_legacy_ready_hidden_spare():
    """A legacy hidden badge cannot leak through matching before migration.

    This holder has not opened ``/cards`` since the trust-ledger migration, so
    the stored document still says every category is Ready.  Candidate loading
    must project the legacy uncertainty on read instead of waiting for the
    owner's next dashboard open to persist the modern ledger.
    """
    class Clans:
        async def distinct(self, field):
            assert field == "tag"
            return ["#HOME"]

    class Inventories:
        def __init__(self, document):
            self.document = document
            self.query = None

        def find(self, query):
            self.query = query
            return _FakeCursor([self.document])

    requester = _complete_inventory(tag="#REQUESTER")
    requester["cards"]["wizard"] = cards.MISSING
    holder = _complete_inventory(tag="#HOLDER")
    holder.update({"guild_id": 123, "discord_id": 222})
    holder["cards"]["wizard"] = cards.DUPLICATE
    holder["scan_duplicate_unverified_card_ids"] = ["wizard"]
    assert "trusted_card_ids" not in holder
    assert cards.find_matches(requester, [holder]), (
        "the untouched legacy Ready row demonstrates the leak being guarded"
    )

    inventories = Inventories(holder)
    candidates = asyncio.run(cards_command._candidate_inventories(
        SimpleNamespace(clans=Clans(), card_inventories=inventories),
        requester,
        guild_id=123,
    ))

    assert inventories.query["guild_id"] == 123
    assert inventories.query["clan_tag"] == {"$in": ["#HOME"]}
    assert len(candidates) == 1
    safe_holder = candidates[0]
    assert "elixir" not in safe_holder["complete_categories"]
    assert safe_holder["cards"]["wizard"] == cards.OWNED
    assert cards.find_matches(requester, candidates) == []
    assert cards.holders_for_card(requester, candidates, "wizard") == []
    # Candidate reads are non-mutating: the unopened legacy row remains legacy
    # until its owner opens /cards and the normal materializer persists it.
    assert "trusted_card_ids" not in holder
    assert "elixir" in holder["complete_categories"]


def test_matching_snapshot_neutralizes_untrusted_counts_for_direct_summaries():
    """Raw partial-scan 0/2 values cannot become demand or supply claims."""
    inventory = _complete_inventory()
    inventory["cards"].update({
        "wizard": cards.MISSING,
        "dragon": cards.DUPLICATE,
        "archer": cards.MISSING,
        "barbarian": cards.DUPLICATE,
    })
    # Only the member-confirmed controls are trusted. The other raw values are
    # preserved scanner evidence, not trade data, even if stale readiness says
    # this category had once been complete.
    inventory["trusted_card_ids"] = ["archer", "barbarian"]

    safe = cards_command._without_reserved_cards(inventory)

    assert safe["cards"]["wizard"] == cards.OWNED
    assert safe["cards"]["dragon"] == cards.OWNED
    assert safe["cards"]["archer"] == cards.MISSING
    assert safe["cards"]["barbarian"] == cards.DUPLICATE
    assert "elixir" not in safe["complete_categories"]
    # The read boundary returns a snapshot; it does not rewrite preserved scan
    # evidence while hiding it from matching and summaries.
    assert inventory["cards"]["wizard"] == cards.MISSING
    assert inventory["cards"]["dragon"] == cards.DUPLICATE

    supply = {
        card_id: cards.CardSupply(
            card_id=card_id,
            holders=(),
            seekers=("#SEEKER",),
            reporting=1,
        )
        for card_id in ("dragon", "barbarian")
    }
    view = cards_command._demand_view(_scan_account(), safe, supply)
    text = _view_text(view)
    assert "Barbarian" in text
    assert "Dragon" not in text
    _assert_discord_payload(view)


def test_missing_or_taken_over_exact_card_token_blocks_every_completion_write():
    checked_at = datetime.now(timezone.utc)
    trade = _reserved_trade()
    owner = cards_command._reservation_owner(trade)
    for requester_reservations in (
        {"root_rider": "other-trade:token", "wizard": owner},
        {"root_rider": owner},
    ):
        requester = _reserve_inventory(_complete_inventory(), trade)
        requester["card_trade_reservations"] = requester_reservations
        holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
        requester["cards"].update({
            "root_rider": cards.MISSING,
            "wizard": cards.DUPLICATE,
        })
        holder["cards"].update({
            "root_rider": cards.DUPLICATE,
            "wizard": cards.MISSING,
        })
        collection = _FakeInventoryCollection([requester, holder])
        mongo = SimpleNamespace(card_inventories=collection)
        cards_command._inventory_locks.clear()

        result = asyncio.run(cards_command._apply_trade_inventory_updates(
            mongo, trade, now=checked_at
        ))

        assert result == {
            "requester": False,
            "holder": False,
            "requester_prevalidated": False,
            "holder_prevalidated": True,
        }
        assert collection.update_calls == 0
        assert requester["cards"]["root_rider"] == cards.MISSING
        assert requester["cards"]["wizard"] == cards.DUPLICATE
        assert holder["cards"]["root_rider"] == cards.DUPLICATE
        assert holder["cards"]["wizard"] == cards.MISSING


def test_completion_changes_neither_inventory_when_one_side_no_longer_matches():
    now = datetime.now(timezone.utc)
    trade = _reserved_trade()
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    requester["cards"].update({"root_rider": cards.MISSING, "wizard": cards.DUPLICATE})
    holder["cards"].update({"root_rider": cards.OWNED, "wizard": cards.MISSING})
    collection = _FakeInventoryCollection([requester, holder])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    result = asyncio.run(cards_command._apply_trade_inventory_updates(
        mongo, trade, now=now
    ))

    assert result == {
        "requester": False,
        "holder": False,
        "requester_prevalidated": True,
        "holder_prevalidated": False,
    }
    assert collection.update_calls == 0
    assert requester["cards"]["root_rider"] == cards.MISSING
    assert requester["cards"]["wizard"] == cards.DUPLICATE


def test_completion_updates_both_exact_pairs_when_all_four_legs_still_match():
    now = datetime.now(timezone.utc)
    trade = _reserved_trade()
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    requester["card_trade_reservations"]["super_barbarian"] = "other-trade:token"
    requester["cards"].update({"root_rider": cards.MISSING, "wizard": cards.DUPLICATE})
    holder["cards"].update({"root_rider": cards.DUPLICATE, "wizard": cards.MISSING})
    collection = _FakeInventoryCollection([requester, holder])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    result = asyncio.run(cards_command._apply_trade_inventory_updates(
        mongo, trade, now=now
    ))

    assert result == {
        "requester": True,
        "holder": True,
        "requester_prevalidated": True,
        "holder_prevalidated": True,
    }
    assert collection.update_calls == 2
    assert requester["cards"]["root_rider"] == cards.OWNED
    assert requester["cards"]["wizard"] == cards.OWNED
    assert holder["cards"]["root_rider"] == cards.OWNED
    assert holder["cards"]["wizard"] == cards.OWNED


def test_second_fenced_inventory_write_failure_is_reported_as_partial():
    now = datetime.now(timezone.utc)
    trade = _reserved_trade()
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    requester["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holder["cards"].update({
        "root_rider": cards.DUPLICATE,
        "wizard": cards.MISSING,
    })
    collection = _FakeInventoryCollection(
        [requester, holder],
        lose_reservation_before_card_write={"#HOLDER"},
    )
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    result = asyncio.run(cards_command._apply_trade_inventory_updates(
        mongo, trade, now=now
    ))

    assert result == {
        "requester": True,
        "holder": False,
        "requester_prevalidated": True,
        "holder_prevalidated": True,
    }
    assert collection.update_calls == 1
    assert requester["cards"]["root_rider"] == cards.OWNED
    assert requester["cards"]["wizard"] == cards.OWNED
    assert holder["card_trade_reservations"]["root_rider"] == (
        "taken-over-trade:token"
    )
    assert holder["cards"]["root_rider"] == cards.DUPLICATE
    assert holder["cards"]["wizard"] == cards.MISSING


def _accepted_trade_for_handler():
    trade = _reserved_trade()
    trade.update({
        "kind": "trade",
        "status": "ready",
        "requester_name": "Requester",
        "requester_discord_id": 111,
        "holder_name": "Holder",
        "holder_discord_id": 222,
        "updated_at": datetime.now(timezone.utc),
    })
    return trade


class _TradeHandlerRest:
    def __init__(self):
        self.messages = []

    async def create_dm_channel(self, discord_id):
        return f"dm-{discord_id}"

    async def create_message(self, *, channel, components, flags=None):
        self.messages.append((channel, _view_text(components)))


def _patch_trade_handler_dependencies(monkeypatch, account):
    async def load_actor(*_args, **_kwargs):
        return account, {}, None

    async def live_clans(*_args, **_kwargs):
        return "#HOME", "#HOME"

    async def verify(*_args, **_kwargs):
        return True

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_trade_actor", load_actor)
    monkeypatch.setattr(cards_command, "_live_family_clans", live_clans)
    monkeypatch.setattr(cards_command, "_verify_trade_reservation", verify)


def test_completion_second_write_exception_persists_review_and_releases(
    monkeypatch,
):
    class RaiseOnHolder(_FakeInventoryCollection):
        async def update_one(self, query, update, upsert=False):
            is_card_write = any(
                path.startswith("cards.") for path in update.get("$set", {})
            )
            if query.get("_id") == "#HOLDER" and is_card_write:
                raise RuntimeError("simulated second-write failure")
            return await super().update_one(query, update, upsert=upsert)

    trade = _accepted_trade_for_handler()
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    requester["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holder["cards"].update({
        "root_rider": cards.DUPLICATE,
        "wizard": cards.MISSING,
    })
    inventories = RaiseOnHolder([requester, holder])
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = trade
    mongo = SimpleNamespace(card_inventories=inventories, card_trades=trades)
    account = Account(
        tag="#ME", name="Requester", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    _patch_trade_handler_dependencies(monkeypatch, account)
    rest = _TradeHandlerRest()
    ctx = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=111))
    cards_command._inventory_locks.clear()

    result = asyncio.run(cards_command.cards_trade_complete(
        ctx,
        trade["_id"],
        coc_client=SimpleNamespace(),
        mongo=mongo,
        bot=SimpleNamespace(rest=rest),
    ))

    assert result
    assert trades.docs[trade["_id"]]["status"] == "needs_review"
    assert "inventory_update_exception:RuntimeError" == (
        trades.docs[trade["_id"]]["failure"]
    )
    assert requester["cards"]["root_rider"] == cards.OWNED
    assert holder["cards"]["root_rider"] == cards.DUPLICATE
    assert requester.get("card_trade_reservations") == {}
    assert holder.get("card_trade_reservations") == {}
    assert rest.messages and rest.messages[0][0] == "dm-222"


def test_completion_audit_exception_attempts_conservative_review(monkeypatch):
    class FinalizeFails(_FakeTradeCollection):
        async def update_one(self, query, update, upsert=False):
            if update.get("$set", {}).get("status") == "completed":
                raise RuntimeError("simulated lost final acknowledgement")
            return await super().update_one(query, update, upsert=upsert)

    trade = _accepted_trade_for_handler()
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    requester["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holder["cards"].update({
        "root_rider": cards.DUPLICATE,
        "wizard": cards.MISSING,
    })
    inventories = _FakeInventoryCollection([requester, holder])
    trades = FinalizeFails()
    trades.docs[trade["_id"]] = trade
    mongo = SimpleNamespace(card_inventories=inventories, card_trades=trades)
    account = Account(
        tag="#ME", name="Requester", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    _patch_trade_handler_dependencies(monkeypatch, account)
    rest = _TradeHandlerRest()
    ctx = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=111))
    cards_command._inventory_locks.clear()

    result = asyncio.run(cards_command.cards_trade_complete(
        ctx,
        trade["_id"],
        coc_client=SimpleNamespace(),
        mongo=mongo,
        bot=SimpleNamespace(rest=rest),
    ))

    assert result
    saved = trades.docs[trade["_id"]]
    assert saved["status"] == "needs_review"
    assert saved["failure"] == "audit_finalize_exception:RuntimeError"
    assert requester["cards"]["root_rider"] == cards.OWNED
    assert holder["cards"]["root_rider"] == cards.OWNED
    assert requester.get("card_trade_reservations") == {}
    assert holder.get("card_trade_reservations") == {}
    assert rest.messages and rest.messages[0][0] == "dm-222"


def test_needs_review_invalidates_both_categories_before_releasing_reservations():
    trade = _reserved_trade()
    owner = cards_command._reservation_owner(trade)
    trade.update({
        "kind": "trade",
        "status": "needs_review",
        "category": "elixir",
        "cleanup_pending": True,
        "cleanup_owner_token": owner,
        "cleanup_requested_at": datetime.now(timezone.utc),
    })
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    affected = {trade["wanted_card_id"], trade["given_card_id"]}
    expected_trusted = {card.id for card in cards.CARDS} - affected
    expected_reviewed = sorted(
        f"{category.id}:{mode}"
        for category in cards.CATEGORIES
        if category.id != "elixir"
        for mode in ("missing", "duplicates")
    )
    review_steps = ["elixir:missing", "elixir:duplicates", "builder_base:missing"]
    for document in (requester, holder):
        document["reviewed_lists"] = list(review_steps)
        document["count_confirmed_card_ids"] = [
            trade["wanted_card_id"], trade["given_card_id"], "barbarian",
        ]

    class OrderedInventories(_FakeInventoryCollection):
        async def update_one(self, query, update, upsert=False):
            if any(
                path.startswith("card_trade_reservations.")
                for path in update.get("$unset", {})
            ):
                assert all(
                    "elixir" not in document["complete_categories"]
                    and "elixir:missing" not in document["reviewed_lists"]
                    and "elixir:duplicates" not in document["reviewed_lists"]
                    and set(document["trusted_card_ids"]) == expected_trusted
                    for document in self.documents.values()
                )
            return await super().update_one(query, update, upsert=upsert)

    inventories = OrderedInventories([requester, holder])

    class OrderedTrades(_FakeTradeCollection):
        async def delete_many(self, query):
            if query.get("kind") == "lease":
                assert all(
                    "elixir" not in document["complete_categories"]
                    for document in inventories.documents.values()
                )
            return await super().delete_many(query)

    trades = OrderedTrades()
    trades.docs[trade["_id"]] = dict(trade)
    trades.docs.update(_lease_documents(trade))
    mongo = SimpleNamespace(
        card_inventories=inventories,
        card_trades=trades,
    )

    cleaned = asyncio.run(cards_command._finish_trade_cleanup(mongo, trade))

    assert cleaned is True
    assert set(trades.docs) == {trade["_id"]}
    saved_trade = trades.docs[trade["_id"]]
    assert saved_trade.get("cleanup_pending") is None
    assert saved_trade.get("released_at") is not None
    for document in inventories.documents.values():
        assert "elixir" not in document["complete_categories"]
        assert document["reviewed_lists"] == expected_reviewed
        assert set(document["trusted_card_ids"]) == expected_trusted
        assert affected.isdisjoint(document["trusted_card_ids"])
        assert "barbarian" in document["trusted_card_ids"], (
            "needs_review narrows uncertainty to the two trade legs"
        )
        assert document["count_confirmed_card_ids"] == ["barbarian"]
        assert document.get("card_trade_reservations") == {}
        assert trade["_id"] in document["card_trade_review_invalidations"]


def test_failed_review_cleanup_stays_queued_and_reconciles_on_retry():
    trade = _reserved_trade()
    owner = cards_command._reservation_owner(trade)
    trade.update({
        "kind": "trade",
        "status": "needs_review",
        "category": "elixir",
        "cleanup_pending": True,
        "cleanup_owner_token": owner,
        "cleanup_requested_at": datetime.now(timezone.utc),
    })
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    for document in (requester, holder):
        document["reviewed_lists"] = ["elixir:missing", "elixir:duplicates"]

    class FailOnceInventories(_FakeInventoryCollection):
        def __init__(self, documents):
            super().__init__(documents)
            self.fail_next_invalidation = True

        async def update_one(self, query, update, upsert=False):
            if self.fail_next_invalidation and "$pull" in update:
                self.fail_next_invalidation = False
                raise RuntimeError("temporary invalidation failure")
            return await super().update_one(query, update, upsert=upsert)

    inventories = FailOnceInventories([requester, holder])
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = dict(trade)
    trades.docs.update(_lease_documents(trade))
    mongo = SimpleNamespace(
        card_inventories=inventories,
        card_trades=trades,
    )

    assert asyncio.run(cards_command._finish_trade_cleanup(mongo, trade)) is False
    assert trades.docs[trade["_id"]]["cleanup_pending"] is True
    assert len(trades.docs) == 5
    assert all(
        document.get("card_trade_reservations")
        for document in inventories.documents.values()
    )

    reconciled = asyncio.run(cards_command._reconcile_trade_cleanups(
        mongo, guild_id=1
    ))

    assert reconciled == 1
    assert set(trades.docs) == {trade["_id"]}
    assert "cleanup_pending" not in trades.docs[trade["_id"]]
    assert all(
        document.get("card_trade_reservations") == {}
        and "elixir" not in document["complete_categories"]
        for document in inventories.documents.values()
    )


def test_verify_trade_reservation_requires_two_token_fences_and_four_leases():
    now = datetime.now(timezone.utc)
    trade = _reserved_trade()

    def reservation(*, fence_count, lease_count):
        requester = _reserve_inventory(_complete_inventory(), trade)
        holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
        if fence_count < 2:
            holder["card_trade_reservations"]["wizard"] = "other-trade:token"
        inventories = _FakeInventoryCollection([requester, holder])
        trades = _FakeTradeCollection()
        lease_documents = list(
            _lease_documents(trade).values()
        )[:lease_count]
        trades.docs.update({document["_id"]: document for document in lease_documents})
        return SimpleNamespace(
            card_inventories=inventories,
            card_trades=trades,
        )

    complete = reservation(fence_count=2, lease_count=4)
    assert asyncio.run(cards_command._verify_trade_reservation(
        complete, trade, now=now
    )) is True

    missing_fence = reservation(fence_count=1, lease_count=4)
    assert asyncio.run(cards_command._verify_trade_reservation(
        missing_fence, trade, now=now
    )) is False

    missing_lease = reservation(fence_count=2, lease_count=3)
    assert asyncio.run(cards_command._verify_trade_reservation(
        missing_lease, trade, now=now
    )) is False
    assert len(missing_lease.card_trades.docs) == 3


def test_legacy_string_markers_still_verify_complete_and_release():
    now = datetime.now(timezone.utc)
    trade = _reserved_trade()
    requester = _reserve_inventory(_complete_inventory(), trade, legacy=True)
    holder = _reserve_inventory(
        _complete_inventory(tag="#HOLDER"), trade, legacy=True
    )
    requester["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holder["cards"].update({
        "root_rider": cards.DUPLICATE,
        "wizard": cards.MISSING,
    })
    inventories = _FakeInventoryCollection([requester, holder])
    trades = _FakeTradeCollection()
    trades.docs.update(_lease_documents(trade))
    mongo = SimpleNamespace(
        card_inventories=inventories,
        card_trades=trades,
    )

    assert asyncio.run(cards_command._verify_trade_reservation(
        mongo, trade, now=now
    )) is True
    updated = asyncio.run(cards_command._apply_trade_inventory_updates(
        mongo, trade, now=now
    ))
    assert updated == {
        "requester": True,
        "holder": True,
        "requester_prevalidated": True,
        "holder_prevalidated": True,
    }

    asyncio.run(cards_command._release_trade_reservation(mongo, trade))

    assert trades.docs == {}
    assert all(
        document.get("card_trade_reservations") == {}
        for document in inventories.documents.values()
    )
    assert requester["cards"]["root_rider"] == cards.OWNED
    assert holder["cards"]["wizard"] == cards.OWNED


def test_late_duplicate_accept_does_not_touch_a_winners_reservations():
    class Trades:
        def find(self, _query):
            return _FakeCursor([])

        async def update_one(self, query, update):
            assert query["status"] == "pending"
            return SimpleNamespace(modified_count=0)

        async def delete_many(self, _query):
            raise AssertionError("losing accept released the winner's leases")

    class Inventories:
        async def find_one(self, _query):
            raise AssertionError("losing accept read or changed card reservations")

    trade = _trade_document()
    trade["status"] = "pending"
    mongo = SimpleNamespace(
        card_trades=Trades(),
        card_inventories=Inventories(),
    )

    outcome, _expires_at = asyncio.run(cards_command._accept_trade_reservation(
        mongo,
        trade,
        user_id=222,
        live_clans=("#HOME", "#HOME"),
        now=datetime.now(timezone.utc),
    ))

    assert outcome == "changed"


def test_stalled_reserving_recovery_does_not_clear_a_newer_token():
    class CopyingTrades(_FakeTradeCollection):
        def find(self, query):
            return _FakeCursor([
                dict(document)
                for document in self.docs.values()
                if _matches_query(document, query)
            ])

    now = datetime.now(timezone.utc)
    stale = _reserved_trade(token="old-token")
    stale.update({
        "kind": "trade",
        "status": "reserving",
        "reservation_until": now - timedelta(seconds=1),
        "updated_at": now - timedelta(minutes=1),
    })
    newer = _reserved_trade(token="new-token")
    trades = CopyingTrades()
    trades.docs[stale["_id"]] = dict(stale)
    trades.docs.update(_lease_documents(newer))
    requester = _reserve_inventory(_complete_inventory(), newer)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), newer)
    inventories = _FakeInventoryCollection([requester, holder])
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=inventories,
    )

    recovered = asyncio.run(cards_command._recover_stalled_reservations(
        mongo, now=now, guild_id=1
    ))

    assert recovered == 1
    assert trades.docs[stale["_id"]]["status"] == "pending"
    assert "reservation_token" not in trades.docs[stale["_id"]]
    assert len(trades.docs) == 5
    assert {
        document["owner_token"]
        for document in trades.docs.values()
        if document.get("kind") == "lease"
    } == {"trade-a:new-token"}
    for document in inventories.documents.values():
        assert {
            marker["owner"]
            for marker in document["card_trade_reservations"].values()
        } == {
            "trade-a:new-token"
        }


def test_pending_move_needed_and_ready_trades_remain_visible_without_deadlines():
    old = datetime.now(timezone.utc) - timedelta(days=30)
    trades = _FakeTradeCollection()
    for status in ("pending", "move_needed", "ready"):
        trade = _trade_document(trade_id=f"trade-{status}")
        trade.update({
            "kind": "trade",
            "status": status,
            "updated_at": old,
            "expires_at": old,
        })
        trades.docs[trade["_id"]] = trade
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))

    assert {trade["status"] for trade in active} == {
        "pending", "move_needed", "ready",
    }


@pytest.mark.parametrize("status", list(cards_command.SWAP_LIVE_STATUSES))
@pytest.mark.parametrize(
    ("confirmed_role", "viewer_tag", "visible"),
    [
        (None, "#ME", True),
        ("requester", "#ME", False),
        ("requester", "#HOLDER", True),
        ("holder", "#HOLDER", False),
        ("holder", "#ME", True),
    ],
)
def test_active_my_trades_visibility_tracks_the_selected_account_leg(
    status, confirmed_role, viewer_tag, visible,
):
    now = datetime.now(timezone.utc)
    trade = _trade_document(trade_id="participant-leg")
    trade.update({
        "kind": "trade",
        "status": status,
        "updated_at": now,
        # Both account roles may belong to one Discord user. The selected
        # account tag, not this shared owner ID, determines visibility.
        "requester_discord_id": 111,
        "holder_discord_id": 111,
    })
    if confirmed_role is not None:
        trade[f"{confirmed_role}_confirmed_at"] = now
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = trade
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag=viewer_tag, guild_id=1
    ))

    assert bool(active) is visible
    if visible:
        assert [row["_id"] for row in active] == [trade["_id"]]


@pytest.mark.parametrize("status", ["completing", "needs_review"])
def test_active_my_trades_keeps_recovery_states_visible_to_both_accounts(status):
    now = datetime.now(timezone.utc)
    trade = _trade_document(trade_id=f"recovery-{status}")
    trade.update({
        "kind": "trade",
        "status": status,
        "updated_at": now,
        "requester_confirmed_at": now,
        "expires_at": now + timedelta(minutes=5),
        "review_expires_at": now + timedelta(days=1),
    })
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = trade
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    for viewer_tag in ("#ME", "#HOLDER"):
        active = asyncio.run(cards_command._active_trades(
            mongo, tag=viewer_tag, guild_id=1
        ))
        assert [row["_id"] for row in active] == [trade["_id"]]


def test_completed_trade_remains_out_of_both_active_account_lists():
    now = datetime.now(timezone.utc)
    trade = _trade_document(trade_id="completed")
    trade.update({
        "kind": "trade",
        "status": "completed",
        "updated_at": now,
        "requester_confirmed_at": now,
        "holder_confirmed_at": now,
    })
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = trade
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    for viewer_tag in ("#ME", "#HOLDER"):
        assert asyncio.run(cards_command._active_trades(
            mongo, tag=viewer_tag, guild_id=1
        )) == []


def test_actionable_trades_are_returned_before_newer_review_records():
    now = datetime.now(timezone.utc)
    pending = _trade_document(trade_id="actionable")
    pending.update({
        "kind": "trade",
        "status": "pending",
        "updated_at": now - timedelta(days=2),
    })
    review = _trade_document(trade_id="review")
    review.update({
        "kind": "trade",
        "status": "needs_review",
        "updated_at": now,
        "review_expires_at": now + timedelta(days=1),
    })
    trades = _FakeTradeCollection()
    trades.docs.update({pending["_id"]: pending, review["_id"]: review})
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))

    assert [trade["_id"] for trade in active] == ["actionable", "review"]


def test_committed_trade_is_returned_before_newer_pending_proposal():
    now = datetime.now(timezone.utc)
    committed = _trade_document(trade_id="committed")
    committed.update({
        "kind": "trade",
        "status": "move_needed",
        "updated_at": now - timedelta(days=2),
    })
    pending = _trade_document(trade_id="pending")
    pending.update({
        "kind": "trade",
        "status": "pending",
        "updated_at": now,
    })
    trades = _FakeTradeCollection()
    trades.docs.update({committed["_id"]: committed, pending["_id"]: pending})
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))

    assert [trade["_id"] for trade in active] == ["committed", "pending"]


def test_committed_trade_cannot_be_hidden_by_more_than_proposal_fetch_limit():
    now = datetime.now(timezone.utc)
    committed = _trade_document(trade_id="committed")
    committed.update({
        "kind": "trade",
        "status": "ready",
        "updated_at": now - timedelta(days=2),
    })
    trades = _FakeTradeCollection()
    trades.docs[committed["_id"]] = committed
    for index in range(cards_command.PROPOSAL_TRADE_FETCH_LIMIT + 10):
        proposal = _trade_document(trade_id=f"proposal-{index}")
        proposal.update({
            "kind": "trade",
            "status": "pending",
            "updated_at": now + timedelta(seconds=index),
        })
        trades.docs[proposal["_id"]] = proposal
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))

    assert active[0]["_id"] == "committed"
    assert len(active) == cards_command.PROPOSAL_TRADE_FETCH_LIMIT + 1


def test_completed_legs_do_not_consume_the_committed_trade_fetch_limit():
    now = datetime.now(timezone.utc)
    trades = _FakeTradeCollection()
    unfinished = _trade_document(trade_id="unfinished")
    unfinished.update({
        "kind": "trade",
        "status": "ready",
        "updated_at": now - timedelta(days=2),
    })
    trades.docs[unfinished["_id"]] = unfinished
    for index in range(cards_command.COMMITTED_TRADE_FETCH_LIMIT + 10):
        completed_leg = _trade_document(trade_id=f"my-done-leg-{index}")
        completed_leg.update({
            "kind": "trade",
            "status": "ready",
            "updated_at": now + timedelta(seconds=index),
            "requester_confirmed_at": now,
        })
        trades.docs[completed_leg["_id"]] = completed_leg
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))

    assert [trade["_id"] for trade in active] == ["unfinished"]


def test_expired_completing_trade_remains_visible_as_needs_review():
    now = datetime.now(timezone.utc)
    expired_at = now - timedelta(minutes=1)
    trade = _reserved_trade()
    trade.update({
        "kind": "trade",
        "status": "completing",
        "expires_at": expired_at,
        "updated_at": expired_at,
    })
    trade_collection = _FakeTradeCollection()
    trade_collection.docs[trade["_id"]] = trade
    trade_collection.docs.update(
        _lease_documents(trade)
    )
    requester = _reserve_inventory(_complete_inventory(), trade)
    holder = _reserve_inventory(_complete_inventory(tag="#HOLDER"), trade)
    inventories = _FakeInventoryCollection([requester, holder])
    mongo = SimpleNamespace(
        card_trades=trade_collection,
        card_inventories=inventories,
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))

    assert len(active) == 1
    assert active[0]["_id"] == trade["_id"]
    assert active[0]["status"] == "needs_review"
    assert active[0]["failure"] == "completion_expired"
    assert active[0]["review_expires_at"] > now
    assert set(trade_collection.docs) == {trade["_id"]}
    assert all(
        document.get("card_trade_reservations") == {}
        for document in inventories.documents.values()
    )


def test_expired_completion_recovery_drains_more_than_twenty_rows():
    now = datetime.now(timezone.utc)
    trades = _FakeTradeCollection()
    for index in range(25):
        trade = _trade_document(trade_id=f"expired-{index}")
        trade.update({
            "kind": "trade",
            "status": "completing",
            "expires_at": now - timedelta(minutes=1),
            "updated_at": now - timedelta(minutes=1),
        })
        trades.docs[trade["_id"]] = trade
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=_FakeInventoryCollection([]),
    )

    active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))

    assert len(active) == 25
    assert {trade["status"] for trade in active} == {"needs_review"}


def test_holder_page_action_rebuilds_second_page_with_trade_selector(monkeypatch):
    now = datetime.now(timezone.utc)
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory(confirmed_at=now)
    inventory["cards"].update({
        "root_rider": cards.MISSING,
        "wizard": cards.DUPLICATE,
    })
    holders = [
        cards.CardMatch(
            holder_tag=f"#HOLDER{index}",
            holder_name=f"Holder {index}",
            holder_discord_id=20_000 + index,
            holder_clan_tag="#AWAY",
            holder_clan_name="Family Clan",
            exchanges=(cards.CategoryExchange(
                "elixir", ("root_rider",), ("wizard",),
            ),),
            same_clan=False,
            confirmed_at=now,
        )
        for index in range(cards_command.HOLDER_RESULT_LIMIT + 1)
    ]

    async def load_target(*_args, **_kwargs):
        return account, inventory, None

    async def candidates(*_args, **_kwargs):
        return []

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_candidate_inventories", candidates)
    monkeypatch.setattr(
        cards_command, "holders_for_card", lambda *_args, **_kwargs: holders
    )
    ctx = SimpleNamespace(guild_id=1)

    view = asyncio.run(cards_command.cards_holder_page(
        ctx,
        "#ME|root_rider|1",
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    payload = [component.build() for component in view]
    nodes = list(_walk_payload(payload))
    custom_ids = {
        str(node["custom_id"])
        for node in nodes
        if "custom_id" in node
    }
    # The select that repeated the holder names is gone. Each holder now
    # carries its own Ask button, so the holder tag rides in the custom_id.
    assert not [n for n in nodes if n.get("type") == 3]
    page_size = cards_command.HOLDER_RESULT_LIMIT
    last = f"#HOLDER{page_size}"
    assert f"cards_trade_holder:#ME|root_rider|{last}" in custom_ids
    assert "cards_holder_page:#ME|root_rider|0" in custom_ids
    assert "cards_holder_page:#ME|root_rider|1" in custom_ids
    _assert_discord_payload(view)


def test_my_trades_view_paginates_more_than_five_open_proposals():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trades = []
    for index in range(cards_command.TRADE_VIEW_LIMIT + 1):
        trade = _trade_document(trade_id=f"trade{index}")
        trade.update({
            "status": "pending",
            "requester_name": "Member",
            "holder_name": f"Holder {index}",
            "created_at": datetime.now(timezone.utc),
        })
        trades.append(trade)

    payload = [
        component.build()
        for component in cards_command._trades_view(account, trades, page=1)
    ]
    nodes = list(_walk_payload(payload))
    custom_ids = {
        str(node["custom_id"])
        for node in nodes
        if "custom_id" in node
    }
    labels = {str(node.get("label")) for node in nodes if "label" in node}

    assert "cards_trade_cancel:trade5" in custom_ids
    assert "cards_trade_cancel:trade0" not in custom_ids
    assert "cards_trades:#ME|0" in custom_ids
    assert "cards_trades:#ME|1" in custom_ids
    assert "cards_trades:#ME|2" in custom_ids
    assert "Page 2/2" in labels
    _assert_discord_payload(cards_command._trades_view(account, trades, page=1))


def test_dashboard_keeps_my_trades_enabled_before_category_setup():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account,
        {"_id": "#ME", "cards": {}, "complete_categories": []},
        account_count=1,
    )
    nodes = list(_walk_payload([component.build() for component in view]))
    button = next(
        node
        for node in nodes
        if node.get("custom_id") == "cards_trades:#ME"
    )
    assert button.get("disabled", False) is False


def test_dashboard_leads_with_the_board_and_carries_every_action():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 7
    views = [
        cards_command._dashboard(account, inventory, account_count=1),
    ]
    possible_spare = dict(inventory)
    possible_spare["scan_duplicate_unverified_card_ids"] = ["wizard"]
    views.append(cards_command._dashboard(
        account, possible_spare, account_count=1
    ))

    for view in views:
        nodes = _view_nodes(view)
        buttons = [node for node in nodes if node.get("type") == 2]
        # Two rows now, because the More router was dissolved into the board.
        assert len(buttons) <= 9
        rows = [node for node in nodes if node.get("type") == 1]
        # Rows went up when each group of controls was separated from the ones
        # it has nothing to do with - sort apart from rebuild, rebuild apart
        # from trading, admin on its own. That is the point, and rows are not
        # the constraint: the 40 components checked below are.
        assert len(rows) <= 10
        # The collection board is the landing surface, not an optional extra.
        assert any(node.get("type") == 12 for node in nodes)
        _assert_discord_payload(view)

    custom_ids = {
        node.get("custom_id")
        for node in _view_nodes(views[0])
        if node.get("custom_id")
    }
    assert custom_ids == {
        "cards_matches:#ME",
        "cards_trades:#ME",
        # Not setup-only: your cards keep changing after every category has
        # been reviewed, and marking one ready cannot be undone.
        "cards_advanced:#ME",
    }
    # The junk-drawer router is gone entirely.
    assert "cards_more:#ME" not in custom_ids


def test_dashboard_without_any_recorded_cards_still_shows_the_board():
    """A brand new member sees the collection greyed out, not a text stub."""
    account = Account(
        tag="#NEW", name="Newcomer", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account, {"_id": "#NEW"}, account_count=1
    )
    nodes = _view_nodes(view)

    assert any(node.get("type") == 12 for node in nodes)
    custom_ids = {
        node.get("custom_id") for node in nodes if node.get("custom_id")
    }
    # Editing is reachable immediately; there is no setup wall in front of it.
    assert "cards_advanced:#NEW" in custom_ids
    assert not any(cid.startswith("cards_pick:") for cid in custom_ids), (
        "the collection screen shows the collection; every edit lives behind "
        "Update collection"
    )
    _assert_discord_payload(view)


def test_runtime_dashboard_renders_the_board_off_the_event_loop(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    calls = []

    async def to_thread(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(cards_command.asyncio, "to_thread", to_thread)
    view = asyncio.run(cards_command._dashboard_view(
        account, inventory, account_count=1
    ))

    assert calls == [cards_command.render_inventory_card_board]
    assert any(node.get("type") == 12 for node in _view_nodes(view))
    _assert_discord_payload(view)


def test_event_links_are_buttons_not_trailing_small_print():
    """Three lines of footer subtext read as leftovers; buttons read as places."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account, _complete_inventory(), account_count=1
    )
    links = [
        n for n in _view_nodes(view)
        if n.get("style") == cards_command.hikari.ButtonStyle.LINK
    ]

    urls = {n["url"] for n in links}
    assert cards_command.COLLECTION_LINK in urls
    assert cards_command.GLOBAL_CHAT_LINK in urls
    assert "OpenGlobalChat" in cards_command.GLOBAL_CHAT_LINK
    # No leftover markdown link lines.
    assert "](" not in _view_text(view)
    _assert_discord_payload(view)


@pytest.mark.parametrize(
    ("handler_name", "initial", "expected"),
    [
        ("cards_editor_inc", cards.MISSING, cards.OWNED),
        ("cards_editor_inc", cards.OWNED, cards.DUPLICATE),
        ("cards_editor_dec", cards.DUPLICATE, cards.OWNED),
        ("cards_editor_dec", cards.OWNED, cards.MISSING),
    ],
)
def test_card_editor_plus_minus_handlers_apply_one_step_only(
    monkeypatch, handler_name, initial, expected,
):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 4
    document["cards"]["wizard"] = initial
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_target(*_args, **_kwargs):
        return account, collection.documents["#ME"], None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(getattr(cards_command, handler_name)(
        ctx,
        "#ME|wizard",
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    assert collection.documents["#ME"]["cards"]["wizard"] == expected
    assert collection.documents["#ME"]["inventory_revision"] == 5
    # The step handlers now return the focused card screen. A spare written by
    # this path is the scanner-style floor, so it reads as unconfirmed until a
    # member states the number.
    unconfirmed = expected == cards.DUPLICATE
    assert cards_command._card_state_words(
        expected, possible_spare=False, unconfirmed=unconfirmed
    ) in _view_text(view)


@pytest.mark.parametrize(
    ("handler_name", "expected"),
    [
        ("cards_editor_keep", cards.OWNED),
        ("cards_editor_inc", cards.DUPLICATE),
    ],
)
def test_possible_spare_editor_yes_no_saves_and_advances(
    monkeypatch, handler_name, expected,
):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 8
    document["scan_duplicate_unverified_card_ids"] = ["wizard", "dragon"]
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_target(*_args, **_kwargs):
        return account, collection.documents["#ME"], None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(getattr(cards_command, handler_name)(
        ctx,
        "#ME|wizard",
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    updated = collection.documents["#ME"]
    assert updated["cards"]["wizard"] == expected
    assert updated["scan_duplicate_unverified_card_ids"] == ["dragon"]
    assert "## Dragon" in _view_text(view)
    custom_ids = {
        node.get("custom_id")
        for node in _view_nodes(view)
        if node.get("custom_id")
    }
    # One row, one meaning: minus, how many you have, plus. The absolute
    # None / Have 1 buttons are gone - they turned green when they matched
    # the count, so they were the value readout pretending to be actions.
    assert {
        "cards_step:#ME|dragon|1",
        "cards_step:#ME|dragon|-1",
        "cards_count:#ME|dragon",
    } <= custom_ids
    assert not [i for i in custom_ids if i.startswith("cards_set:#ME|dragon|")]


def test_possible_spare_editor_missing_saves_only_that_card_and_advances(
    monkeypatch,
):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 8
    document["scan_duplicate_unverified_card_ids"] = ["wizard", "dragon"]
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_target(*_args, **_kwargs):
        return account, collection.documents["#ME"], None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(cards_command.cards_editor_dec(
        ctx,
        "#ME|wizard",
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    updated = collection.documents["#ME"]
    assert updated["cards"]["wizard"] == cards.MISSING
    assert updated["cards"]["dragon"] == cards.OWNED
    assert updated["scan_duplicate_unverified_card_ids"] == ["dragon"]
    assert updated["inventory_revision"] == 9
    assert "## Dragon" in _view_text(view)
    assert "**You have 1**" in _view_text(view)
    assert any(
        node.get("custom_id") == "cards_count:#ME|dragon"
        and node.get("label") == "Type a number"
        for node in _view_nodes(view)
    )
    assert len([node for node in _view_nodes(view) if "type" in node]) <= 40
    _assert_discord_payload(view)


def test_possible_spare_board_state_keeps_proven_ownership():
    inventory = _complete_inventory()
    inventory["scan_duplicate_unverified_card_ids"] = ["wizard"]
    values = cards_command._inventory_board_values(inventory)

    assert values["wizard"] == "owned_spare_unverified"
    board = cards_command.render_inventory_card_board(values, player_name="Member")
    assert board.collected_count == 60
    assert board.spare_unverified_card_ids == ("wizard",)

    draft = _complete_scan_draft(duplicate_unverified=["wizard"])
    assert cards_command._scan_board_values(draft)["wizard"] == (
        "owned_spare_unverified"
    )


def test_one_card_quick_update_uses_exact_card_reservation_and_revision_guards():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 3
    document["cards"]["root_rider"] = cards.MISSING
    document["card_trade_reservations"] = {
        "wizard": "trade-other:token",
    }
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_one_card(
        mongo,
        account,
        document,
        "root_rider",
        "found",
        expected_revision=3,
        discord_id=123,
        guild_id=1,
    ))
    assert updated["cards"]["root_rider"] == cards.OWNED
    assert updated["cards"]["wizard"] == cards.OWNED
    assert updated["inventory_revision"] == 4
    assert updated["update_source"] == "quick_card_update"

    with pytest.raises(cards_command.InventoryWriteConflict):
        asyncio.run(cards_command._write_one_card(
            mongo,
            account,
            updated,
            "root_rider",
            "missing",
            expected_revision=3,
            discord_id=123,
            guild_id=1,
        ))

    updated["card_trade_reservations"]["root_rider"] = "trade-this:token"
    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_one_card(
            mongo,
            account,
            updated,
            "root_rider",
            "missing",
            expected_revision=4,
            discord_id=123,
            guild_id=1,
        ))


def test_global_hidden_badge_review_saves_one_batch_and_clears_only_that_batch():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 5
    hidden = [card.id for card in cards.CARDS[:27]]
    document["trusted_card_ids"] = [
        card.id for card in cards.CARDS if card.id not in hidden
    ]
    document["complete_categories"] = ["builder_base", "super_troop"]
    document["scan_duplicate_unverified_card_ids"] = hidden
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    first_batch = hidden[:cards_command.HIDDEN_BADGE_BATCH_SIZE]
    updated = asyncio.run(cards_command._write_hidden_badge_batch(
        mongo,
        account,
        document,
        first_batch,
        [first_batch[0], first_batch[-1]],
        expected_revision=5,
        discord_id=123,
        guild_id=1,
    ))
    assert updated["cards"][first_batch[0]] == cards.DUPLICATE
    assert updated["cards"][first_batch[-1]] == cards.DUPLICATE
    assert all(
        updated["cards"][card_id] == cards.OWNED
        for card_id in first_batch[1:-1]
    )
    assert updated["scan_duplicate_unverified_card_ids"] == hidden[25:]
    assert set(first_batch) <= set(updated["trusted_card_ids"])
    assert set(hidden[25:]).isdisjoint(updated["trusted_card_ids"])
    assert "elixir" in updated["complete_categories"]
    assert "dark_elixir" not in updated["complete_categories"]
    assert updated["inventory_revision"] == 6
    # The leftovers are offered together in one more batch question, not two
    # more single-card screens.
    next_view = cards_command._hidden_badge_review(account, updated)
    nodes = _view_nodes(next_view)
    picker = next(
        node for node in nodes
        if node.get("custom_id") == "cards_hidden_pick:#ME"
    )
    assert {str(o["value"]) for o in picker["options"]} == set(hidden[25:])
    _assert_discord_payload(next_view)


def test_all_member_views_build_with_discord_component_limits():
    account = Account(
        tag="#ME",
        name="Member",
        clan_tag="#HOME",
        clan_name="Home Clan",
        town_hall=18,
    )
    empty = {
        "_id": "#ME",
        "cards": {},
        "complete_categories": [],
    }
    complete = _complete_inventory()
    complete["cards"]["root_rider"] = cards.MISSING
    complete["cards"]["wizard"] = cards.DUPLICATE
    now = datetime.now(timezone.utc)
    active = dict(complete)
    active["card_trade_reservations"] = {
        "root_rider": "active-trade:token",
    }
    worst_exchanges = tuple(
        cards.CategoryExchange(
            category.id,
            tuple(card.id for card in cards.CATEGORY_CARDS[category.id]),
            tuple(card.id for card in cards.CATEGORY_CARDS[category.id]),
        )
        for category in cards.CATEGORIES
    )
    broad_matches = [
        cards.CardMatch(
            holder_tag=f"#MATCH{index}",
            holder_name=f"Match {index}",
            holder_discord_id=10_000 + index,
            holder_clan_tag="#HOME",
            holder_clan_name="Home Clan",
            exchanges=worst_exchanges,
            same_clan=True,
            confirmed_at=now,
        )
        for index in range(cards_command.MATCH_RESULT_LIMIT)
    ]
    specific_matches = [
        cards.CardMatch(
            holder_tag=f"#HOLDER{index}",
            holder_name=f"Holder {index}",
            holder_discord_id=20_000 + index,
            holder_clan_tag="#HOME",
            holder_clan_name="Home Clan",
            exchanges=(cards.CategoryExchange(
                "elixir",
                ("root_rider",),
                tuple(
                    card.id
                    for card in cards.CATEGORY_CARDS["elixir"]
                    if card.id != "root_rider"
                ),
            ),),
            same_clan=True,
            confirmed_at=now,
        )
        for index in range(cards_command.HOLDER_RESULT_LIMIT + 10)
    ]
    active_trades = [
        {
            "_id": f"trade{index}",
            "status": "pending" if index % 2 == 0 else "ready",
            "requester_tag": "#ME",
            "requester_name": "Member",
            "holder_tag": f"#HOLDER{index}",
            "holder_name": f"Holder {index}",
            "wanted_card_id": "root_rider",
            "given_card_id": "wizard",
        }
        for index in range(cards_command.TRADE_VIEW_LIMIT)
    ]

    views = [
        cards_command._dashboard(account, empty, account_count=1),
        cards_command._dashboard(account, complete, account_count=2),
        cards_command._dashboard(account, active, account_count=2),
        cards_command._active_trade_notice(account.tag),
        cards_command._matches_view(account, complete, []),
        cards_command._matches_view(account, complete, broad_matches),
        cards_command._holders_view(account, "root_rider", []),
        cards_command._holders_view(account, "root_rider", specific_matches),
        cards_command._trade_offer_view(
            account, "root_rider", specific_matches[0]
        ),
        cards_command._trades_view(account, active_trades),
        cards_command._trade_feedback("Saved", "Ready", "#ME"),
    ]
    views.extend(
        cards_command._quantity_editor(
            account, empty, category.id, card_id=card.id
        )
        for category in cards.CATEGORIES
        for card in cards.CATEGORY_CARDS[category.id]
    )
    for view in views:
        _assert_discord_payload(view)


def _complete_scan_draft(*, duplicate_unverified=()):
    return {
        "version": 1,
        "capture_count": cards_command.CARD_SCAN_CAPTURE_COUNT,
        "card_states": {card.id: cards.OWNED for card in cards.CARDS},
        "card_confidences": {card.id: 0.99 for card in cards.CARDS},
        "card_warnings": {},
        "unknown_card_ids": [],
        "unseen_card_ids": [],
        "duplicate_unverified_card_ids": list(duplicate_unverified),
        "warnings": [],
        "errors": [],
        "identity_bound": True,
        "coverage_complete": True,
        "scanner_persistence_safe": False,
    }


def _view_nodes(view):
    return list(_walk_payload([component.build() for component in view]))


def _view_media(view):
    """The first media item mounted in a container, or None."""
    for node in _view_nodes(view):
        for item in node.get("items") or ():
            media = item.get("media") if isinstance(item, dict) else None
            if media is not None:
                return media
    return None


def _view_labels(view):
    return [
        str(node["label"])
        for node in _view_nodes(view)
        if node.get("type") == 2 and "label" in node
    ]


def _view_text(view):
    return "\n".join(
        str(node["content"])
        for node in _view_nodes(view)
        if "content" in node
    )


def _contains_raw_bytes(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, dict):
        return any(_contains_raw_bytes(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_raw_bytes(child) for child in value)
    return False


def _scan_account(tag="#ME", name="Member"):
    return Account(
        tag=tag,
        name=name,
        clan_tag="#HOME",
        clan_name="Home Clan",
        town_hall=18,
    )


def _scan_accounts_data(*accounts):
    return cards_command.AccountsData(entries=tuple(
        cards_command.AccountEntry(
            tag=account.tag,
            status=cards_command.STATUS_LOADED,
            account=account,
        )
        for account in accounts
    ))


def _slash_context(*, user_id=123, guild_id=1):
    class Interaction:
        def __init__(self):
            self.edits = []

        async def edit_initial_response(self, **kwargs):
            self.edits.append(kwargs)

    interaction = Interaction()
    deferred = []

    async def defer(*, ephemeral=False):
        deferred.append(ephemeral)

    async def respond(*args, **kwargs):
        raise AssertionError((args, kwargs))

    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        guild_id=guild_id,
        interaction=interaction,
        defer=defer,
        respond=respond,
        deferred=deferred,
    )


def test_cards_opens_the_existing_private_dashboard(monkeypatch):
    account = _scan_account()
    data = _scan_accounts_data(account)
    inventory = _complete_inventory()
    async def load_accounts(*_args, **_kwargs):
        return data

    async def ensure_inventory(*_args, **_kwargs):
        return inventory

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_ensure_inventory", ensure_inventory)
    command = SimpleNamespace()
    ctx = _slash_context()

    asyncio.run(cards_command.Cards.invoke._func(
        command,
        ctx,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert ctx.deferred == [True]
    assert len(ctx.interaction.edits) == 1
    nodes = _view_nodes(ctx.interaction.edits[0]["components"])
    assert any(
        node.get("custom_id") == "cards_advanced:#ME"
        for node in nodes
    )


def test_cards_command_has_no_page_fields_and_opens_compact_dashboard(monkeypatch):
    account = _scan_account()
    data = _scan_accounts_data(account)
    inventory = _complete_inventory()

    async def load_accounts(*_args, **_kwargs):
        return data

    async def ensure_inventory(*_args, **_kwargs):
        return inventory

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_ensure_inventory", ensure_inventory)

    assert not hasattr(cards_command.Cards, "page_1")
    assert not hasattr(cards_command.Cards, "page_5")
    ctx = _slash_context()
    asyncio.run(cards_command.Cards.invoke._func(
        SimpleNamespace(),
        ctx,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert ctx.deferred == [True]
    assert any(
        node.get("custom_id") == "cards_advanced:#ME"
        for node in _view_nodes(ctx.interaction.edits[0]["components"])
    )


def test_scan_button_opens_one_account_bound_private_dm_session(monkeypatch):
    account = _scan_account()
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 9
    inserted = []
    updated = []
    sent = []

    class ComponentState:
        async def delete_many(self, query):
            assert query == {"type": "cards_scan_upload", "user_id": 123}

    class Rest:
        async def create_dm_channel(self, user_id):
            assert user_id == 123
            return SimpleNamespace(id=777)

    async def load_target(*_args, **_kwargs):
        return account, inventory, None

    async def insert_state(_mongo, document, *, ttl):
        inserted.append((document, ttl))

    async def update_state(_mongo, query, update, **_kwargs):
        updated.append((query, update))
        return SimpleNamespace(matched_count=1)

    async def send(_bot, channel_id, components):
        sent.append((channel_id, components))
        return SimpleNamespace(id=888)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "insert_state", insert_state)
    monkeypatch.setattr(cards_command, "update_state", update_state)
    monkeypatch.setattr(cards_command, "_send_scan_dm_components", send)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    mongo = SimpleNamespace(component_state=ComponentState())
    bot = SimpleNamespace(rest=Rest())

    view = asyncio.run(cards_command.cards_scan_start(
        ctx,
        "#ME",
        coc_client=SimpleNamespace(),
        mongo=mongo,
        bot=bot,
    ))

    assert len(inserted) == 1
    document, ttl = inserted[0]
    assert ttl == cards_command.CARD_SCAN_DRAFT_FOR
    assert document["type"] == "cards_scan_upload"
    assert document["user_id"] == 123
    assert document["guild_id"] == 1
    assert document["account_tag"] == "#ME"
    assert document["base_revision"] == 9
    assert _contains_raw_bytes(document) is False
    assert sent[0][0] == 777
    prompt_text = _view_text(sent[0][1])
    assert "send all screenshots here in one message" in prompt_text.lower()
    assert "any order is fine" in prompt_text.lower()
    assert updated[0][1]["$set"] == {
        "upload_prompt_channel_id": 777,
        "upload_prompt_message_id": 888,
    }
    assert "Private upload ready" in _view_text(view)


def test_rapid_scan_starts_are_serialized_to_one_current_session(monkeypatch):
    account = _scan_account()
    inventory = _complete_inventory()
    active_ids = set()
    concurrent_deletes = 0
    max_concurrent_deletes = 0

    class ComponentState:
        async def delete_many(self, _query):
            nonlocal concurrent_deletes, max_concurrent_deletes
            concurrent_deletes += 1
            max_concurrent_deletes = max(max_concurrent_deletes, concurrent_deletes)
            active_ids.clear()
            await asyncio.sleep(0)
            concurrent_deletes -= 1

    class Rest:
        async def create_dm_channel(self, _user_id):
            return SimpleNamespace(id=777)

    async def load_target(*_args, **_kwargs):
        return account, inventory, None

    async def insert_state(_mongo, document, *, ttl):
        assert ttl == cards_command.CARD_SCAN_DRAFT_FOR
        active_ids.add(document["_id"])

    async def update_state(*_args, **_kwargs):
        return SimpleNamespace(matched_count=1)

    async def send(*_args, **_kwargs):
        return SimpleNamespace(id=888)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "insert_state", insert_state)
    monkeypatch.setattr(cards_command, "update_state", update_state)
    monkeypatch.setattr(cards_command, "_send_scan_dm_components", send)
    cards_command._card_upload_locks.clear()
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    mongo = SimpleNamespace(component_state=ComponentState())
    bot = SimpleNamespace(rest=Rest())

    async def start_twice():
        return await asyncio.gather(*(
            cards_command.cards_scan_start(
                ctx,
                "#ME",
                coc_client=SimpleNamespace(),
                mongo=mongo,
                bot=bot,
            )
            for _ in range(2)
        ))

    asyncio.run(start_twice())

    assert max_concurrent_deletes == 1
    assert len(active_ids) == 1
    cards_command._card_upload_locks.clear()


def test_bound_scan_ignores_failure_on_a_different_linked_account(monkeypatch):
    selected = _scan_account()
    data = cards_command.AccountsData(entries=(
        cards_command.AccountEntry(
            tag=selected.tag,
            status=cards_command.STATUS_LOADED,
            account=selected,
        ),
        cards_command.AccountEntry(
            tag="#OTHER",
            status=cards_command.STATUS_ERROR,
            account=None,
        ),
    ))
    inventory = _complete_inventory()

    async def load_accounts(*_args, **_kwargs):
        return data

    async def ensure_inventory(*_args, **_kwargs):
        return inventory

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_ensure_inventory", ensure_inventory)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=None)

    account, loaded_inventory, returned_data, problem = asyncio.run(
        cards_command._load_scan_bound_account(
            ctx,
            "draft-selected",
            "#ME",
            usable_until=datetime.now(timezone.utc) + timedelta(minutes=10),
            coc_client=SimpleNamespace(),
            mongo=SimpleNamespace(),
        )
    )

    assert account is selected
    assert loaded_inventory is inventory
    assert returned_data is data
    assert problem is None


def test_dm_upload_accepts_partial_any_order_and_keeps_only_checkpoint(monkeypatch):
    account = _scan_account()
    data = cards_command.AccountsData(entries=(
        cards_command.AccountEntry(
            tag=account.tag,
            status=cards_command.STATUS_LOADED,
            account=account,
        ),
        cards_command.AccountEntry(
            tag="#OTHER",
            status=cards_command.STATUS_ERROR,
            account=None,
        ),
    ))
    deadline = datetime.now(timezone.utc) + timedelta(minutes=15)
    state = {
        "_id": "cards_upload_test",
        "type": "cards_scan_upload",
        "user_id": 123,
        "guild_id": 1,
        "account_tag": "#ME",
        "base_revision": 4,
        "usable_until": deadline,
    }
    raw_payloads = (b"rows-5-6", b"rows-1-2", b"rows-3-4")
    reads = []
    scanned = []
    updates = []
    sent = []

    class Attachment:
        def __init__(self, payload, index):
            self.payload = payload
            self.size = len(payload)
            self.media_type = "image/png"
            self.filename = f"capture-{index}.png"

        async def read(self):
            reads.append(self.payload)
            return self.payload

    async def find_state(*_args, **_kwargs):
        return state

    async def get_state(*_args, **_kwargs):
        return state

    async def load_accounts(*_args, **_kwargs):
        return data

    def scan(payloads, *, prior_draft=None):
        scanned.append((payloads, prior_draft))
        return {
            "card_states": {},
            "card_confidences": {},
            "unknown_card_ids": [],
            "unseen_card_ids": [card.id for card in cards.CARDS[36:]],
            "missing_page_numbers": [4, 5],
            "missing_global_rows": [7, 8, 9, 10],
            "scan_checkpoint": {"accepted_pages": [1, 2, 3]},
            "coverage_complete": False,
            "identity_bound": True,
            "errors": [],
        }

    async def update_state(_mongo, query, update, **_kwargs):
        updates.append((query, update))
        return SimpleNamespace(matched_count=1)

    async def send(_bot, channel_id, components):
        sent.append((channel_id, components))
        return SimpleNamespace(id=999)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_find_card_upload_state", find_state)
    monkeypatch.setattr(cards_command, "get_state", get_state)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_scan_collection_payloads", scan)
    monkeypatch.setattr(cards_command, "update_state", update_state)
    monkeypatch.setattr(cards_command, "_send_scan_dm_components", send)
    event = SimpleNamespace(
        is_human=True,
        author_id=123,
        channel_id=777,
        message=SimpleNamespace(attachments=tuple(
            Attachment(payload, index)
            for index, payload in enumerate(raw_payloads)
        )),
    )

    asyncio.run(cards_command._handle_card_scan_dm_upload(
        event,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
        bot=SimpleNamespace(),
    ))

    assert reads == list(raw_payloads)
    assert scanned == [(raw_payloads, None)]
    saved_draft = updates[0][1]["$set"]["scan_draft"]
    assert saved_draft["scan_checkpoint"] == {"accepted_pages": [1, 2, 3]}
    assert _contains_raw_bytes(saved_draft) is False
    assert len(updates) == 1
    progress = _view_text(sent[0][1])
    assert "matched **3 of 5**" in progress
    assert "**Rows 7–10:**" in progress
    assert "→" in progress
    assert "Do not resend accepted rows." in progress


def test_dm_followup_merges_checkpoint_and_opens_account_bound_review(monkeypatch):
    account = _scan_account()
    data = _scan_accounts_data(account)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=10)
    prior = {
        "missing_page_numbers": [4, 5],
        "missing_global_rows": [7, 8, 9, 10],
        "scan_checkpoint": {"accepted_pages": [1, 2, 3]},
        "coverage_complete": False,
    }
    state = {
        "_id": "cards_upload_followup",
        "type": "cards_scan_upload",
        "user_id": 123,
        "guild_id": 1,
        "account_tag": "#ME",
        "base_revision": 4,
        "usable_until": deadline,
        "scan_draft": prior,
        "upload_prompt_channel_id": 777,
        "upload_prompt_message_id": 888,
    }
    updates = []
    sent = []
    prompt_edits = []

    class Attachment:
        size = 12
        media_type = "image/jpeg"
        filename = "missing.jpg"

        async def read(self):
            return b"missing-rows"

    async def find_state(*_args, **_kwargs):
        return state

    async def get_state(*_args, **_kwargs):
        return state

    async def load_accounts(*_args, **_kwargs):
        return data

    def scan(payloads, *, prior_draft=None):
        assert payloads == (b"missing-rows",)
        assert prior_draft is prior
        draft = _complete_scan_draft()
        draft.update({
            "missing_page_numbers": [],
            "missing_global_rows": [],
            "scan_checkpoint": {"accepted_pages": [1, 2, 3, 4, 5]},
        })
        return draft

    async def update_state(_mongo, query, update, **_kwargs):
        updates.append((query, update))
        return SimpleNamespace(matched_count=1)

    async def send(_bot, channel_id, components):
        sent.append((channel_id, components))
        return SimpleNamespace(id=999)

    async def ensure_inventory(*_args, **_kwargs):
        inventory = _complete_inventory()
        inventory["inventory_revision"] = 4
        return inventory

    async def mark_prompt(_bot, current_state, current_account):
        prompt_edits.append((current_state, current_account))

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_find_card_upload_state", find_state)
    monkeypatch.setattr(cards_command, "get_state", get_state)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_scan_collection_payloads", scan)
    monkeypatch.setattr(cards_command, "update_state", update_state)
    monkeypatch.setattr(cards_command, "_send_scan_dm_components", send)
    monkeypatch.setattr(cards_command, "_ensure_inventory", ensure_inventory)
    monkeypatch.setattr(cards_command, "_mark_scan_prompt_received", mark_prompt)
    event = SimpleNamespace(
        is_human=True,
        author_id=123,
        channel_id=777,
        message=SimpleNamespace(attachments=(Attachment(),)),
    )

    asyncio.run(cards_command._handle_card_scan_dm_upload(
        event,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
        bot=SimpleNamespace(),
    ))

    assert len(updates) == 2
    assert updates[0][1]["$set"]["scan_draft"]["coverage_complete"] is True
    assert updates[1][1] == {"$set": {"type": "cards_scan_draft"}}
    review = _view_text(sent[0][1])
    assert "Scan complete" in review
    assert "**Member** · `#ME`" in review
    assert prompt_edits == [(state, account)]


def test_dm_followup_scanner_failure_preserves_existing_checkpoint(monkeypatch):
    account = _scan_account()
    prior = {
        "missing_page_numbers": [4, 5],
        "missing_global_rows": [7, 8, 9, 10],
        "scan_checkpoint": {"accepted_pages": [1, 2, 3]},
        "coverage_complete": False,
    }
    state = {
        "_id": "cards_upload_preserve",
        "type": "cards_scan_upload",
        "user_id": 123,
        "guild_id": 1,
        "account_tag": "#ME",
        "usable_until": datetime.now(timezone.utc) + timedelta(minutes=10),
        "scan_draft": prior,
    }
    sent = []

    class Attachment:
        size = 12
        media_type = "image/png"
        filename = "retry.png"

        async def read(self):
            return b"retry"

    async def find_state(*_args, **_kwargs):
        return state

    async def get_state(*_args, **_kwargs):
        return state

    async def load_accounts(*_args, **_kwargs):
        return _scan_accounts_data(account)

    def scan(_payloads, *, prior_draft=None):
        assert prior_draft is prior
        return {"errors": ["scan_failed:RuntimeError"]}

    async def forbidden_update(*_args, **_kwargs):
        raise AssertionError("failed follow-up must not replace its checkpoint")

    async def send(_bot, channel_id, components):
        sent.append((channel_id, components))
        return SimpleNamespace(id=999)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_find_card_upload_state", find_state)
    monkeypatch.setattr(cards_command, "get_state", get_state)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_scan_collection_payloads", scan)
    monkeypatch.setattr(cards_command, "update_state", forbidden_update)
    monkeypatch.setattr(cards_command, "_send_scan_dm_components", send)
    event = SimpleNamespace(
        is_human=True,
        author_id=123,
        channel_id=777,
        message=SimpleNamespace(attachments=(Attachment(),)),
    )

    asyncio.run(cards_command._handle_card_scan_dm_upload(
        event,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
        bot=SimpleNamespace(),
    ))

    assert len(sent) == 1
    text = _view_text(sent[0][1])
    assert "previously matched pages are still saved" in text
    assert "no collection was changed" in text


def test_scan_adapter_never_defaults_unknown_or_unseen_cards_to_owned():
    first = cards.CARDS[0]
    draft = cards_command._normalize_collection_scan(
        {
            "cards": {
                first.id: {"state": cards.OWNED, "confidence": 0.99},
            },
            # A scanner cannot override the identity-based coverage check.
            "coverage_complete": True,
        },
        capture_count=5,
    )

    assert draft["card_states"] == {first.id: cards.OWNED}
    assert first.id not in draft["unseen_card_ids"]
    assert len(draft["unseen_card_ids"]) == 59
    assert draft["coverage_complete"] is False
    assert cards_command._scan_draft_confirmable(draft) is False

    view = cards_command._scan_review(
        _scan_account(),
        {"_id": "#ME"},
        "draft-unknown",
        draft,
    )
    nodes = _view_nodes(view)
    confirm = next(
        node for node in nodes
        if node.get("custom_id") == "cards_scan_confirm:draft-unknown"
    )
    assert confirm["disabled"] is True
    assert any(
        node.get("custom_id") == "cards_advanced:#ME"
        and node.get("disabled", False) is False
        for node in nodes
    )
    assert "Not visible:** 59 card positions" in _view_text(view)


def test_ambiguous_card_blocks_scan_confirm_and_leaves_manual_fallback():
    raw_cards = {
        card.id: {"state": cards.OWNED, "confidence": 0.99}
        for card in cards.CARDS
    }
    raw_cards["wizard"] = {"state": "unknown", "confidence": 0.99}
    draft = cards_command._normalize_collection_scan(
        {
            "cards": raw_cards,
            "unknown_card_ids": ["wizard"],
            "coverage_complete": True,
        },
        capture_count=5,
    )

    assert "wizard" not in draft["card_states"]
    assert draft["unknown_card_ids"] == ["wizard"]
    assert draft["unseen_card_ids"] == []
    assert cards_command._scan_draft_confirmable(draft) is False
    view = cards_command._scan_review(
        _scan_account(), {"_id": "#ME"}, "draft-ambiguous", draft
    )
    nodes = _view_nodes(view)
    assert next(
        node["disabled"]
        for node in nodes
        if node.get("custom_id") == "cards_scan_confirm:draft-ambiguous"
    ) is True
    assert any(node.get("custom_id") == "cards_advanced:#ME" for node in nodes)


def test_hidden_duplicate_badge_is_disclosed_but_safe_owned_minimum_can_confirm():
    hidden_card = cards.CARD_BY_ID["wizard"]
    draft = cards_command._normalize_collection_scan(
        {
            "cards": {
                card.id: {
                    "state": cards.OWNED,
                    "confidence": 0.99,
                    "warnings": (
                        ["duplicate_badge_unverified"]
                        if card.id == hidden_card.id
                        else []
                    ),
                }
                for card in cards.CARDS
            },
            "duplicate_unverified_card_ids": [hidden_card.id],
            "coverage_complete": True,
        },
        capture_count=5,
    )

    assert draft["card_states"][hidden_card.id] == cards.OWNED
    assert draft["duplicate_unverified_card_ids"] == [hidden_card.id]
    assert cards_command._scan_draft_confirmable(draft) is True
    view = cards_command._scan_review(
        _scan_account(), {"_id": "#ME"}, "draft-hidden", draft
    )
    nodes = _view_nodes(view)
    confirm = next(
        node for node in nodes
        if node.get("custom_id") == "cards_scan_confirm:draft-hidden"
    )
    assert confirm["disabled"] is False
    assert confirm["label"] == "Finish collection"
    review_text = _view_text(view)
    # The safe owned minimum may be saved, but the unread badge itself remains
    # a required manual count in the shared Finish collection queue.
    assert "spare" not in review_text.casefold()
    assert "59 of 60 cards" in review_text
    assert "1 still need a count" in review_text
    buttons = [node for node in nodes if node.get("type") == 2]
    assert [button.get("label") for button in buttons] == [
        "Finish collection",
        "Cancel",
    ]
    assert len([button for button in buttons if button.get("style") == 1]) == 1
    assert len([node for node in nodes if node.get("type") == 1]) == 1
    assert not any(node.get("type") == 12 for node in nodes)


def test_scan_confirm_is_explicit_and_private_session_checks_precede_db(monkeypatch):
    account = _scan_account()
    draft = _complete_scan_draft()
    draft["card_states"]["wizard"] = cards.DUPLICATE
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 4
    saved = dict(inventory, update_source="confirmed_screenshot_review")
    saved["cards"] = dict(inventory["cards"], wizard=cards.DUPLICATE)
    saved["trusted_card_ids"] = [card.id for card in cards.CARDS]
    saved["count_confirmed_card_ids"] = []
    writes = []
    discarded = []
    dashboard_calls = []
    dashboard_result = cards_command._notice(
        "Collection dashboard", "Full scan saved."
    )

    async def load_target(*_args, **_kwargs):
        return account, inventory, None

    async def write_scan(*args, **kwargs):
        writes.append((args, kwargs))
        return saved

    async def discard(_mongo, draft_id):
        discarded.append(draft_id)

    async def load_accounts(*_args, **_kwargs):
        return _scan_accounts_data(account)

    async def dashboard(account_arg, inventory_arg, **kwargs):
        dashboard_calls.append((account_arg, inventory_arg, kwargs))
        return dashboard_result

    def spare_count_detour(*_args, **_kwargs):
        raise AssertionError("an ordinary scanner 2+ must not open the old detour")

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_write_scan_draft", write_scan)
    monkeypatch.setattr(cards_command, "_discard_scan_state", discard)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_dashboard_view", dashboard)
    monkeypatch.setattr(cards_command, "_spare_counts_panel", spare_count_detour)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    # Rendering review is side-effect free; only its explicit button writes.
    cards_command._scan_review(account, inventory, "draft-confirm", draft)
    assert writes == []
    assert discarded == []

    result = asyncio.run(cards_command.cards_scan_confirm(
        ctx,
        "draft-confirm",
        scan_draft=draft,
        user_id=123,
        guild_id=1,
        account_tag="#ME",
        base_revision=4,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))
    assert len(writes) == 1
    assert writes[0][1]["expected_revision"] == 4
    assert discarded == ["draft-confirm"]
    assert result is dashboard_result
    assert len(dashboard_calls) == 1
    assert dashboard_calls[0][0] is account
    assert dashboard_calls[0][1] is saved
    assert saved["cards"]["wizard"] == cards.DUPLICATE
    assert "wizard" not in saved["count_confirmed_card_ids"]

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("unauthorized draft reached inventory access")

    monkeypatch.setattr(cards_command, "_load_target", forbidden)
    monkeypatch.setattr(cards_command, "_write_scan_draft", forbidden)
    wrong_user = SimpleNamespace(user=SimpleNamespace(id=999), guild_id=1)
    user_notice = asyncio.run(cards_command.cards_scan_confirm(
        wrong_user,
        "draft-private-user",
        scan_draft=draft,
        user_id=123,
        guild_id=1,
        account_tag="#ME",
        base_revision=4,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))
    assert "screenshot draft is private" in _view_text(user_notice).casefold()

    wrong_guild = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=2)
    guild_notice = asyncio.run(cards_command.cards_scan_confirm(
        wrong_guild,
        "draft-private-guild",
        scan_draft=draft,
        user_id=123,
        guild_id=2,
        account_tag="#ME",
        base_revision=4,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))
    assert "screenshot draft is private" in _view_text(guild_notice).casefold()
    assert len(writes) == 1
    assert discarded == ["draft-confirm"]


def test_scan_save_routes_hidden_badges_into_the_bulk_finish_queue(
    monkeypatch,
):
    account = _scan_account()
    hidden = ["wizard", "dragon"]
    draft = _complete_scan_draft(duplicate_unverified=hidden)
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 4
    saved = dict(inventory)
    saved["inventory_revision"] = 5
    saved["scan_duplicate_unverified_card_ids"] = hidden
    saved["trusted_card_ids"] = [
        card.id for card in cards.CARDS if card.id not in hidden
    ]
    saved["complete_categories"] = [
        "dark_elixir", "builder_base", "super_troop",
    ]
    inserted = []
    discarded = []

    async def load_target(*_args, **_kwargs):
        return account, inventory, None

    async def write_scan(*_args, **_kwargs):
        return saved

    async def load_accounts(*_args, **_kwargs):
        return _scan_accounts_data(account)

    async def insert_state(_mongo, document, *, ttl):
        inserted.append((document, ttl))

    async def discard(_mongo, draft_id):
        discarded.append(draft_id)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_write_scan_draft", write_scan)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "insert_state", insert_state)
    monkeypatch.setattr(cards_command, "_discard_scan_state", discard)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    view = asyncio.run(cards_command.cards_scan_confirm(
        ctx,
        "draft-hidden-review",
        scan_draft=draft,
        user_id=123,
        guild_id=1,
        account_tag="#ME",
        base_revision=4,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    nodes = _view_nodes(view)
    assert "Scan finished" in _view_text(view)
    assert "58 of 60 cards read" in _view_text(view)
    assert "2 still need a count" in _view_text(view)
    assert _view_labels(view) == ["Enter counts", "Finish later"]
    state = inserted[0][0]
    assert state["scope"] == "scan_finish"
    assert state["selected_ids"] == hidden
    assert state["required_entry_ids"] == hidden
    assert len([node for node in nodes if "type" in node]) <= 40
    _assert_discord_payload(view)
    assert discarded == ["draft-hidden-review"]


@pytest.mark.parametrize(
    ("handler_name", "expected"),
    [
        ("cards_scan_hidden_no", cards.OWNED),
        ("cards_scan_hidden_yes", cards.DUPLICATE),
    ],
)
def test_scan_possible_spare_yes_no_saves_one_card_and_advances(
    monkeypatch, handler_name, expected,
):
    account = _scan_account()
    document = _complete_inventory()
    document["inventory_revision"] = 5
    document["scan_duplicate_unverified_card_ids"] = ["wizard", "dragon"]
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_bound(*_args, **_kwargs):
        return account, collection.documents["#ME"], None, None

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_scan_bound_account", load_bound)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=None)
    view = asyncio.run(getattr(cards_command, handler_name)(
        ctx,
        "draft-hidden",
        user_id=123,
        guild_id=1,
        account_tag="#ME",
        usable_until=datetime.now(timezone.utc) + timedelta(minutes=10),
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    updated = collection.documents["#ME"]
    assert updated["cards"]["wizard"] == expected
    assert updated["scan_duplicate_unverified_card_ids"] == ["dragon"]
    assert "## Dragon" in _view_text(view)
    custom_ids = {
        node.get("custom_id")
        for node in _view_nodes(view)
        if node.get("custom_id")
    }
    assert {
        "cards_scan_hidden_missing:draft-hidden",
        "cards_scan_hidden_no:draft-hidden",
        "cards_scan_hidden_yes:draft-hidden",
    } <= custom_ids


def test_state_bound_scan_possible_spare_missing_saves_and_advances(
    monkeypatch,
):
    account = _scan_account()
    document = _complete_inventory()
    document["inventory_revision"] = 5
    document["scan_duplicate_unverified_card_ids"] = ["wizard", "dragon"]
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_bound(*_args, **_kwargs):
        return account, collection.documents["#ME"], None, None

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_scan_bound_account", load_bound)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=None)
    view = asyncio.run(cards_command.cards_scan_hidden_missing(
        ctx,
        "draft-hidden",
        user_id=123,
        guild_id=1,
        account_tag="#ME",
        usable_until=datetime.now(timezone.utc) + timedelta(minutes=10),
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    updated = collection.documents["#ME"]
    assert updated["cards"]["wizard"] == cards.MISSING
    assert updated["cards"]["dragon"] == cards.OWNED
    assert updated["scan_duplicate_unverified_card_ids"] == ["dragon"]
    assert updated["inventory_revision"] == 6
    assert "## Dragon" in _view_text(view)
    assert any(
        node.get("custom_id") == "cards_scan_hidden_missing:draft-hidden"
        and node.get("label") == "Missing — have 0"
        for node in _view_nodes(view)
    )
    assert len([node for node in _view_nodes(view) if "type" in node]) <= 40
    _assert_discord_payload(view)


def test_scan_save_persists_hidden_badges_until_that_duplicate_list_is_reviewed():
    account = _scan_account()
    elixir_hidden = cards.CATEGORY_CARDS["elixir"][0].id
    dark_hidden = cards.CATEGORY_CARDS["dark_elixir"][0].id
    draft = _complete_scan_draft(
        duplicate_unverified=(elixir_hidden, dark_hidden)
    )
    original = {
        "_id": "#ME",
        "inventory_revision": 0,
        "cards": {"wizard": cards.DUPLICATE},
        "complete_categories": [],
        "reviewed_lists": [],
    }
    collection = _FakeInventoryCollection([original])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    saved = asyncio.run(cards_command._write_scan_draft(
        mongo,
        account,
        draft,
        expected_revision=0,
        discord_id=123,
        guild_id=1,
    ))

    assert saved["cards"][elixir_hidden] == cards.OWNED
    assert saved["cards"][dark_hidden] == cards.OWNED
    assert saved["scan_duplicate_unverified_card_ids"] == [
        elixir_hidden,
        dark_hidden,
    ]
    assert elixir_hidden not in saved["trusted_card_ids"]
    assert dark_hidden not in saved["trusted_card_ids"]
    assert set(saved["complete_categories"]) == {
        "builder_base", "super_troop",
    }
    assert saved["update_source"] == "confirmed_screenshot_review"
    assert saved["inventory_revision"] == 1
    # The board routes unresolved scanner values into the canonical editor.
    board = cards_command._dashboard(account, saved, account_count=1)
    assert "2 cards still need a count" in _view_text(board)
    assert any(
        node.get("custom_id") == "cards_hidden:#ME"
        and node.get("label") == "Finish collection (2)"
        for node in _view_nodes(board)
    )

    # Answering one card clears that card's badge and no other. The old
    # duplicate list cleared a whole category in one submit, so answering about
    # a Barbarian also silently claimed the other eighteen had been checked.
    category_mongo = SimpleNamespace(
        card_inventories=_FakeCategoryCollection(saved)
    )
    cards_command._inventory_locks.clear()
    answered = asyncio.run(cards_command._write_card_state(
        category_mongo,
        account,
        saved,
        elixir_hidden,
        cards.DUPLICATE,
        expected_revision=cards_command._inventory_revision_value(saved),
        discord_id=123,
        guild_id=1,
    ))
    assert answered["scan_duplicate_unverified_card_ids"] == [dark_hidden]
    assert answered["cards"][elixir_hidden] == cards.DUPLICATE
    assert elixir_hidden in answered["trusted_card_ids"]
    assert "elixir" in answered["complete_categories"]

    # Only an actual answer can trust the remaining card. That final answer
    # clears the uncertainty and makes its category Ready in the same write.
    ready = asyncio.run(cards_command._write_card_state(
        category_mongo,
        account,
        answered,
        dark_hidden,
        cards.OWNED,
        expected_revision=cards_command._inventory_revision_value(answered),
        discord_id=123,
        guild_id=1,
    ))
    assert ready["scan_duplicate_unverified_card_ids"] == []
    assert dark_hidden in ready["trusted_card_ids"]
    assert set(ready["complete_categories"]) == {
        category.id for category in cards.CATEGORIES
    }


def test_a_full_successful_scan_trusts_every_card_and_scanner_two_plus_is_ready():
    account = _scan_account()
    draft = _complete_scan_draft()
    draft["card_states"]["wizard"] = cards.DUPLICATE
    document = {
        "_id": "#ME",
        "inventory_revision": 0,
        "cards": {},
        "complete_categories": [],
        "reviewed_lists": [],
    }
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()

    saved = asyncio.run(cards_command._write_scan_draft(
        mongo,
        account,
        draft,
        expected_revision=0,
        discord_id=123,
        guild_id=1,
    ))

    assert set(saved["trusted_card_ids"]) == {card.id for card in cards.CARDS}
    assert set(saved["complete_categories"]) == {
        category.id for category in cards.CATEGORIES
    }
    assert "wizard" not in saved.get("count_confirmed_card_ids", [])
    assert cards_command._inventory_board_values(saved)["wizard"] == (
        card_board.SPARE_FLOOR
    )
    assert "`2+`" in _view_text(
        cards_command._quantity_editor(account, saved, "elixir")
    )


def test_scan_save_stale_revision_and_active_reservation_cannot_overwrite():
    account = _scan_account()
    draft = _complete_scan_draft()

    stale_document = {
        "_id": "#ME",
        "inventory_revision": 3,
        "cards": {"wizard": cards.DUPLICATE},
    }
    stale_mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([stale_document])
    )
    cards_command._inventory_locks.clear()
    with pytest.raises(cards_command.ScanDraftStaleError):
        asyncio.run(cards_command._write_scan_draft(
            stale_mongo,
            account,
            draft,
            expected_revision=2,
            discord_id=123,
            guild_id=1,
        ))
    assert stale_document["cards"] == {"wizard": cards.DUPLICATE}
    assert stale_document["inventory_revision"] == 3

    reserved_document = {
        "_id": "#ME",
        "inventory_revision": 2,
        "cards": {"wizard": cards.DUPLICATE},
        "card_trade_reservations": {
            "wizard": {
                "owner": "trade-a:token-a",
                "until": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        },
    }
    reserved_mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([reserved_document])
    )
    cards_command._inventory_locks.clear()
    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_scan_draft(
            reserved_mongo,
            account,
            draft,
            expected_revision=2,
            discord_id=123,
            guild_id=1,
        ))
    assert reserved_document["cards"] == {"wizard": cards.DUPLICATE}
    assert reserved_document["inventory_revision"] == 2


def _supply_document(tag, *, cards_map, complete=None, confirmed_at=None):
    return {
        "_id": tag,
        "player_name": tag,
        "cards": cards_map,
        "complete_categories": (
            list(complete)
            if complete is not None
            else [category.id for category in cards.CATEGORIES]
        ),
        "confirmed_at": confirmed_at or datetime.now(timezone.utc),
    }


def test_family_supply_counts_holders_and_seekers_per_card():
    values = {card.id: cards.OWNED for card in cards.CARDS}
    holder = dict(values, barbarian=cards.DUPLICATE)
    seeker = dict(values, barbarian=cards.MISSING)
    other_seeker = dict(values, barbarian=cards.MISSING)

    supply = cards.family_supply([
        _supply_document("#H", cards_map=holder),
        _supply_document("#S", cards_map=seeker),
        _supply_document("#T", cards_map=other_seeker),
    ])

    barbarian = supply["barbarian"]
    assert barbarian.holders == ("#H",)
    assert barbarian.seekers == ("#S", "#T")
    assert barbarian.reporting == 3
    assert barbarian.spare_count == 1
    assert barbarian.demand == 2
    # A card everybody owns once has neither a spare nor a seeker.
    assert supply["archer"].holders == ()
    assert supply["archer"].seekers == ()


def test_family_supply_ignores_paused_and_unreviewed_collections():
    """Age no longer removes anyone; opting out does.

    An event that runs for weeks made the old 72-hour cutoff remove people
    whose cards were perfectly accurate, purely for not opening Discord, and
    it never told them.
    """
    values = {card.id: cards.DUPLICATE for card in cards.CARDS}
    paused = _supply_document("#OFF", cards_map=values)
    paused["trading_paused"] = True
    unreviewed = _supply_document("#NEW", cards_map=values, complete=[])

    supply = cards.family_supply([paused, unreviewed])

    assert supply["barbarian"].holders == ()
    assert supply["barbarian"].reporting == 0


def test_family_supply_keeps_an_old_but_active_collection():
    values = {card.id: cards.DUPLICATE for card in cards.CARDS}
    old = _supply_document(
        "#OLD",
        cards_map=values,
        confirmed_at=datetime.now(timezone.utc) - timedelta(days=20),
    )

    supply = cards.family_supply([old])

    assert supply["barbarian"].holders == ("#OLD",)


def test_family_supply_only_counts_reviewed_categories_of_a_partial_member():
    values = {card.id: cards.MISSING for card in cards.CARDS}
    partial = _supply_document("#P", cards_map=values, complete=["elixir"])

    supply = cards.family_supply([partial])

    assert supply["barbarian"].seekers == ("#P",)   # elixir, reviewed
    assert supply["minion"].seekers == ()           # dark elixir, not reviewed


def _brute_force_max_trades(pairs):
    best = 0
    for mask in range(1 << len(pairs)):
        used = set()
        count = 0
        ok = True
        for index, (left, right) in enumerate(pairs):
            if not mask & (1 << index):
                continue
            if left in used or right in used:
                ok = False
                break
            used.add(left)
            used.add(right)
            count += 1
        if ok:
            best = max(best, count)
    return best


def test_one_spare_offered_to_many_partners_is_still_one_trade():
    spare = ("#ME", "wizard")
    pairs = [
        (spare, ("#A", "dragon")),
        (spare, ("#B", "golem")),
        (spare, ("#C", "witch")),
    ]

    assert cards.max_achievable_trades(pairs) == 1
    assert len(pairs) == 3  # the raw count that used to be reported


def test_independent_trades_all_complete_together():
    pairs = [
        (("#A", "wizard"), ("#B", "dragon")),
        (("#C", "golem"), ("#D", "witch")),
    ]

    assert cards.max_achievable_trades(pairs) == 2


def test_greedy_matches_brute_force_on_small_inputs():
    resources = [(f"#{owner}", card) for owner in "ABCD" for card in ("x", "y")]
    cases = [
        [(resources[0], resources[1])],
        [(resources[0], resources[1]), (resources[1], resources[2])],
        [
            (resources[0], resources[1]),
            (resources[2], resources[3]),
            (resources[0], resources[3]),
        ],
        [
            (resources[0], resources[1]),
            (resources[1], resources[2]),
            (resources[2], resources[3]),
            (resources[3], resources[4]),
        ],
        [
            (resources[0], resources[1]),
            (resources[0], resources[2]),
            (resources[3], resources[4]),
            (resources[5], resources[6]),
            (resources[1], resources[6]),
        ],
    ]

    for pairs in cases:
        greedy = cards.max_achievable_trades(pairs)
        exact = _brute_force_max_trades(pairs)
        assert greedy <= exact
        # The documented worst case for this greedy is half the true maximum.
        assert greedy * 2 >= exact


def test_achievable_trade_count_is_independent_of_input_order():
    pairs = [
        (("#A", "wizard"), ("#B", "dragon")),
        (("#B", "dragon"), ("#C", "golem")),
        (("#C", "golem"), ("#D", "witch")),
    ]

    assert cards.max_achievable_trades(pairs) == cards.max_achievable_trades(
        list(reversed(pairs))
    )


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (cards.MISSING, cards.DUPLICATE),   # no edge existed for this before
        (cards.DUPLICATE, cards.MISSING),
        (cards.OWNED, cards.MISSING),
        (cards.MISSING, cards.OWNED),
        (cards.OWNED, cards.OWNED),         # idempotent
    ],
)
def test_cards_set_writes_the_absolute_state(monkeypatch, initial, target):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 4
    document["cards"]["wizard"] = initial
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_target(*_args, **_kwargs):
        return account, collection.documents["#ME"], None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(cards_command.cards_set(
        ctx,
        f"#ME|wizard|{target}",
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    assert collection.documents["#ME"]["cards"]["wizard"] == target
    assert collection.documents["#ME"]["inventory_revision"] == 5
    assert "## Wizard" in _view_text(view)
    _assert_discord_payload(view)


def test_cards_set_refuses_a_reserved_card(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 4
    document["cards"]["wizard"] = cards.DUPLICATE
    document["card_trade_reservations"] = {
        "wizard": {
            "owner": "trade-1",
            "until": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    }
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_target(*_args, **_kwargs):
        return account, collection.documents["#ME"], None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(cards_command.cards_set(
        ctx,
        "#ME|wizard|0",
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    assert collection.documents["#ME"]["cards"]["wizard"] == cards.DUPLICATE
    assert "reserved" in _view_text(view).lower()


@pytest.mark.parametrize("payload", ["#ME|wizard|abc", "#ME|wizard|100", "#ME|nope|2"])
def test_cards_set_rejects_an_unparseable_target(payload):
    """Counts above MAX_COPIES, non-numbers, and unknown cards all fail closed."""
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(cards_command.cards_set(
        ctx,
        payload,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert "Card unavailable" in _view_text(view)


@pytest.mark.parametrize(
    ("initial", "delta", "expected"),
    [
        (cards.DUPLICATE, 1, 3),
        (3, 1, 4),
        (4, -1, 3),
        (cards.DUPLICATE, -1, cards.OWNED),
        (cards.MISSING, -1, cards.MISSING),   # floors, never negative
    ],
)
def test_cards_step_adjusts_the_copy_count(monkeypatch, initial, delta, expected):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 4
    document["cards"]["wizard"] = initial
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    async def load_target(*_args, **_kwargs):
        return account, collection.documents["#ME"], None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    view = asyncio.run(cards_command.cards_step(
        ctx,
        f"#ME|wizard|{delta}",
        coc_client=SimpleNamespace(),
        mongo=mongo,
    ))

    assert collection.documents["#ME"]["cards"]["wizard"] == expected
    _assert_discord_payload(view)


def test_a_count_above_two_survives_normalisation_and_still_trades():
    """Storing four must not read as "no spare" anywhere in the rules."""
    values = {card.id: cards.OWNED for card in cards.CARDS}
    values["wizard"] = 4

    normalized = cards.normalize_cards(values)
    assert normalized["wizard"] == 4

    summary = cards.inventory_summary(
        values, [category.id for category in cards.CATEGORIES]
    )
    assert summary.duplicates == 1
    assert summary.collected == 60


def test_card_focus_marks_the_current_state_and_keeps_the_menu():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["wizard"] = cards.DUPLICATE

    view = cards_command._card_focus(account, inventory, "wizard")
    nodes = _view_nodes(view)

    # The count is a NUMBER now, not a green button. Colour used to carry the
    # current value - the matching absolute button went SUCCESS - which left
    # the actual figure nowhere on screen and made two rows of controls look
    # like rival ways to change one thing.
    count = next(
        n for n in nodes if n.get("custom_id") == "cards_count:#ME|wizard"
    )
    # The count is TEXT, not a button. As the middle button it read as a
    # display anyway, which hid the modal behind it and made tapping what
    # looked like a readout do something unexpected.
    assert count["label"] == "Type a number"
    # "or more" because a spare whose exact number was never confirmed is
    # stored as the floor of two. It says so rather than claim a figure.
    assert "**You have 2 or more**" in _view_text(view)
    assert any(
        str(n.get("label")) == "Set to 2" for n in nodes
    ), "an unconfirmed spare keeps its one-tap answer"
    # None (0) and Have 1 are gone - they were the disguised readout. Set to 2
    # survives as cards_set:...|2, but only while the spare is unconfirmed.
    assert not [
        n for n in nodes
        if str(n.get("custom_id", "")) in (
            "cards_set:#ME|wizard|0", "cards_set:#ME|wizard|1",
        )
    ], "the absolute state buttons were the readout in disguise"

    # Navigation belongs outside the row that changes the number.
    value_row = next(
        n for n in nodes
        if n.get("type") == 1
        and any(
            str(c.get("custom_id", "")).startswith("cards_step:")
            for c in n.get("components", [])
        )
    )
    assert not [
        c for c in value_row["components"]
        if str(c.get("custom_id", "")).startswith("cards_dashboard:")
    ]
    custom_ids = {
        node.get("custom_id") for node in _view_nodes(view) if node.get("custom_id")
    }
    # The category menu stays mounted so several cards can be fixed in a row.
    assert "cards_pick:#ME|elixir" in custom_ids
    _assert_discord_payload(view)


def test_scan_saving_asks_how_many_spares_before_the_dashboard():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["wizard"] = cards.DUPLICATE
    inventory["cards"]["dragon"] = cards.DUPLICATE

    view = cards_command._spare_counts_panel(account, inventory)
    text = _view_text(view)

    assert "How many spares?" in text
    assert "2 cards" in text
    offered = {
        str(option["value"])
        for node in _walk_payload([c.build() for c in view])
        for option in (node.get("options") or ())
    }
    assert offered == {"wizard", "dragon"}
    custom_ids = {
        node.get("custom_id") for node in _view_nodes(view) if node.get("custom_id")
    }
    assert "cards_dashboard:#ME" in custom_ids
    _assert_discord_payload(view)


def test_no_spare_prompt_when_nothing_came_back_as_a_spare():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    assert cards_command._spare_counts_panel(account, _complete_inventory()) is None


def test_a_refined_count_is_not_asked_about_again():
    """Only the unrefined 2+ entries are worth a question."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["wizard"] = 5

    assert cards_command._spare_counts_panel(account, inventory) is None


def test_giving_away_one_of_several_copies_keeps_the_rest():
    """A member holding four who trades one must end on three, not one."""
    values = {card.id: cards.OWNED for card in cards.CARDS}
    values["wizard"] = 4
    values["dragon"] = cards.MISSING

    # The matcher must see four copies as a spare, exactly like two.
    holder = {
        "_id": "#H",
        "cards": values,
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }
    requester_values = {card.id: cards.OWNED for card in cards.CARDS}
    requester_values["wizard"] = cards.MISSING
    requester_values["dragon"] = cards.DUPLICATE
    requester = {
        "_id": "#R",
        "cards": requester_values,
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }

    assert cards.reciprocal_trade_error(
        requester, holder, "wizard", "dragon"
    ) is None

    matches = cards.holders_for_card(requester, [holder], "wizard")
    assert [m.holder_tag for m in matches] == ["#H"]


def test_used_spare_decrements_instead_of_collapsing_to_one(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document = _complete_inventory()
    document["inventory_revision"] = 4
    document["cards"]["wizard"] = 4
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_one_card(
        mongo,
        account,
        collection.documents["#ME"],
        "wizard",
        "used",
        expected_revision=4,
        discord_id=123,
        guild_id=1,
    ))

    assert updated["cards"]["wizard"] == 3


def test_a_member_confirmed_two_loses_the_plus():
    """The scanner's 2 reads 2+; a member's 2 reads 2."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    scanned = _complete_inventory()
    scanned["cards"]["wizard"] = cards.DUPLICATE

    values = cards_command._inventory_board_values(scanned)
    assert values["wizard"] == card_board.SPARE_FLOOR
    assert card_board._spare_badge_text(card_board.SPARE_FLOOR) == "x2+"

    confirmed = dict(scanned, count_confirmed_card_ids=["wizard"])
    values = cards_command._inventory_board_values(confirmed)
    assert values["wizard"] == cards.DUPLICATE
    assert card_board._spare_badge_text(cards.DUPLICATE) == "x2"

    # The confirm button only exists while there is something to confirm.
    unconfirmed_view = cards_command._card_focus(account, scanned, "wizard")
    confirmed_view = cards_command._card_focus(account, confirmed, "wizard")
    unconfirmed_ids = {
        n.get("custom_id") for n in _view_nodes(unconfirmed_view) if n.get("custom_id")
    }
    confirmed_ids = {
        n.get("custom_id") for n in _view_nodes(confirmed_view) if n.get("custom_id")
    }
    assert "cards_set:#ME|wizard|2" in unconfirmed_ids
    assert "cards_set:#ME|wizard|2" not in confirmed_ids
    _assert_discord_payload(unconfirmed_view)
    _assert_discord_payload(confirmed_view)


def test_focus_screen_never_repeats_a_custom_id_at_any_count():
    """Discord rejects a message carrying the same custom_id twice."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    for value in (0, 1, 2, 3, 12):
        inventory = _complete_inventory()
        inventory["cards"]["wizard"] = value
        for confirmed in ([], ["wizard"]):
            inventory["count_confirmed_card_ids"] = confirmed
            view = cards_command._card_focus(account, inventory, "wizard")
            _assert_discord_payload(view)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "You have no Balloon."),
        (1, "You have 1 Balloon, none to spare."),
        (2, "You have 2 Balloon · 1 spare copy to trade."),
        (4, "You have 4 Balloon · 3 spare copies to trade."),
    ],
)
def test_saved_line_says_what_you_hold_not_an_internal_state(count, expected):
    assert cards_command._saved_count_line("Balloon", count) == expected


def test_the_tile_and_the_board_never_disagree_about_a_spare():
    """A confirmed 2 reads x2 on both; an unconfirmed 2 reads x2+ on both."""
    assert card_board._spare_badge_text(cards.DUPLICATE) == "x2"
    assert card_board._spare_badge_text(card_board.SPARE_FLOOR) == "x2+"
    assert card_board._spare_badge_text(5) == "x5"

    confirmed = card_board.render_card_thumbnail("balloon", cards.DUPLICATE)
    floored = card_board.render_card_thumbnail("balloon", card_board.SPARE_FLOOR)
    assert confirmed.png_bytes != floored.png_bytes


def test_copy_steppers_are_colour_coded():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["wizard"] = 3
    inventory["count_confirmed_card_ids"] = ["wizard"]

    view = cards_command._card_focus(account, inventory, "wizard")
    buttons = {
        node["custom_id"]: node
        for node in _view_nodes(view)
        if node.get("custom_id", "").startswith("cards_step:")
    }

    assert buttons["cards_step:#ME|wizard|-1"]["style"] == 4   # DANGER
    assert buttons["cards_step:#ME|wizard|1"]["style"] == 3    # SUCCESS


def test_account_picker_lists_accounts_in_one_select_with_town_hall_emoji():
    """Sections were tried here and are worse: on mobile the accessory button
    wraps below its text, so 37 linked accounts became seven pages of scrolling.
    """
    accounts = [
        Account(tag=f"#A{i}", name=f"Member {i}", clan_tag="#HOME",
                clan_name="Home Clan", town_hall=17 - i)
        for i in range(3)
    ]
    data = _scan_accounts_data(*accounts)

    view = cards_command._account_picker(data)
    nodes = list(_walk_payload([c.build() for c in view]))

    selects = [n for n in nodes if n.get("type") == 3]
    assert len(selects) == 1
    assert {str(o["value"]) for o in selects[0]["options"]} == {a.tag for a in accounts}
    assert not [n for n in nodes if n.get("type") == 9]
    _assert_discord_payload(view)


def test_account_picker_paginates_without_a_dead_counter_button():
    accounts = [
        Account(tag=f"#A{i}", name=f"Member {i}", clan_tag="#HOME",
                clan_name="Home Clan", town_hall=16)
        for i in range(30)
    ]
    data = _scan_accounts_data(*accounts)

    first = cards_command._account_picker(data, 0)
    second = cards_command._account_picker(data, 1)

    assert "Accounts 1–25 of 30" in _view_text(first)
    assert "Accounts 26–30 of 30" in _view_text(second)
    assert not [
        n for n in _view_nodes(first)
        if n.get("type") == 2 and n.get("disabled") and "Page" in str(n.get("label"))
    ]
    _assert_discord_payload(first)
    _assert_discord_payload(second)


def test_destination_buttons_say_what_is_waiting_there():
    """The count rides in the label, so the row that carried it is not needed."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["wizard"] = cards.MISSING
    inventory["cards"]["dragon"] = cards.MISSING
    inventory["cards"]["golem"] = 3

    view = cards_command._dashboard(account, inventory, account_count=1)
    labels = [n.get("label", "") for n in _view_nodes(view) if n.get("type") == 2]

    assert any("Find trades" in label and "2 needed" in label for label in labels)
    assert any("My trades" in label for label in labels)
    # A label Discord will truncate is worse than no count at all.
    for label in labels:
        assert len(label) <= 80, f"too long for a button: {label}"
    _assert_discord_payload(view)


def test_find_trades_stays_open_on_an_old_collection():
    """Idle is not the same as wrong, and this event runs for weeks."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    old = _complete_inventory(
        confirmed_at=datetime.now(timezone.utc) - timedelta(days=20)
    )

    view = cards_command._dashboard(account, old, account_count=1)
    find = next(
        n for n in _view_nodes(view)
        if n.get("custom_id") == "cards_matches:#ME"
    )

    assert find["disabled"] is False
    _assert_discord_payload(view)


def test_find_trades_is_closed_while_trading_is_paused():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    paused = _complete_inventory()
    paused["trading_paused"] = True

    view = cards_command._dashboard(account, paused, account_count=1)
    find = next(
        n for n in _view_nodes(view)
        if n.get("custom_id") == "cards_matches:#ME"
    )

    assert find["disabled"] is True
    _assert_discord_payload(view)


def test_board_destinations_are_buttons_not_two_line_rows():
    """Two Sections cost two lines each and wrapped on mobile; buttons do not."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account, _complete_inventory(), account_count=1
    )
    nodes = _view_nodes(view)

    assert [n for n in nodes if n.get("type") == 9] == []
    assert "Update collection" in _view_labels(view)
    ids = {n.get("custom_id") for n in nodes}
    assert {"cards_matches:#ME", "cards_trades:#ME"} <= ids
    _assert_discord_payload(view)


def test_every_scan_button_carries_the_scan_mark():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    views = [
        cards_command._dashboard(account, _complete_inventory(), account_count=1),
        cards_command._scan_dm_unavailable(account),
    ]
    seen = 0
    for view in views:
        for node in _view_nodes(view):
            if str(node.get("custom_id", "")).startswith("cards_scan_start:"):
                emoji = node.get("emoji") or {}
                assert emoji.get("id") == "1536807847042613398", node.get("label")
                seen += 1
    assert seen == 1, f"only checked {seen} scan buttons"



def test_collection_group_hides_controls_that_would_do_nothing():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    done = cards_command._dashboard(
        account, _complete_inventory(), account_count=1
    )
    partial = cards_command._dashboard(
        account,
        dict(_complete_inventory(), complete_categories=["elixir"]),
        account_count=2,
    )
    done_ids = {n.get("custom_id") for n in _view_nodes(done)}
    partial_ids = {n.get("custom_id") for n in _view_nodes(partial)}

    # Switch account needs a second account. Bulk edit is NOT setup - your
    # cards keep changing after review, so it stays on both.
    assert "cards_account_page:0|#ME" not in done_ids
    assert "cards_advanced:#ME" in done_ids
    assert "cards_advanced:#ME" in partial_ids
    assert "cards_account_page:0|#ME" in partial_ids
    # Scanning is always available.
    assert "cards_scan_start:#ME" not in done_ids, (
        "scanning moved inside Update collection"
    )


def test_scan_review_does_not_ask_for_a_retake_once_cards_are_resolved():
    """Answering every uncertain card by hand must clear the retake notice.

    It previously sat next to an enabled Save button, telling the member to
    retake a page they had just finished correcting.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    draft = {
        "card_states": {card.id: cards.OWNED for card in cards.CARDS},
        "unknown_card_ids": [],
        "unseen_card_ids": [],
        "errors": [],
        "capture_issues": [{"image": 1, "reasons": ["blurry"]}],
    }

    view = cards_command._scan_review(
        account, _complete_inventory(), "draft-1", draft
    )
    text = _view_text(view)

    assert "retake" not in text.lower()
    assert "Send these pages again" not in text


def test_scan_review_still_asks_when_positions_were_never_seen():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    states = {card.id: cards.OWNED for card in cards.CARDS}
    for card in cards.CARDS[:6]:
        states.pop(card.id)
    draft = {
        "card_states": states,
        "unknown_card_ids": [],
        "unseen_card_ids": [card.id for card in cards.CARDS[:6]],
        "errors": [],
        "capture_issues": [{"image": 1, "reasons": ["page 1 missing"]}],
    }

    text = _view_text(cards_command._scan_review(
        account, _complete_inventory(), "draft-2", draft
    ))

    assert "Send these pages again" in text


def test_card_name_lists_carry_troop_art_everywhere():
    """One formatter feeds scan review, trade offers and holder lists."""
    from utils import troop_emoji

    troop_emoji.clear()
    troop_emoji.prime([
        {"slug": "wizard", "emoji_id": 111111111111111111, "name": "troop_wizard"},
    ])
    try:
        named = cards_command._card_names(["wizard", "dragon"])
        assert "<:troop_wizard:111111111111111111> Wizard" in named
        # A troop with no synced emoji still reads cleanly.
        assert "Dragon" in named
        assert "None Dragon" not in named

        scanned = cards_command._scan_card_names(["wizard"])
        assert "<:troop_wizard:111111111111111111> Wizard" in scanned
    finally:
        troop_emoji.clear()

    # With nothing synced at all, both degrade to plain names.
    assert cards_command._card_names(["wizard"]) == "Wizard"
    assert cards_command._scan_card_names(["wizard"]) == "Wizard"
    assert cards_command._card_names([]) == "none"
    assert cards_command._scan_card_names([]) == "None"


def test_several_hidden_badges_are_one_question_not_one_each():
    """The reward bar hides a whole row at a time, so ask once."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    pending = ["wizard", "dragon", "golem", "witch", "bowler"]
    inventory["scan_duplicate_unverified_card_ids"] = pending

    view = cards_command._hidden_badge_review(account, inventory)
    nodes = _view_nodes(view)
    picker = next(
        n for n in nodes if n.get("custom_id") == "cards_hidden_pick:#ME"
    )

    assert {str(o["value"]) for o in picker["options"]} == set(pending)
    assert picker["max_values"] == len(pending)
    assert picker["min_values"] == 0          # ticking nothing is a real answer
    assert any(
        n.get("custom_id") == "cards_hidden_none_of_these:#ME" for n in nodes
    )
    # A single leftover still gets the simple three-button screen.
    inventory["scan_duplicate_unverified_card_ids"] = ["wizard"]
    single = _view_nodes(cards_command._hidden_badge_review(account, inventory))
    assert not [n for n in single if n.get("custom_id") == "cards_hidden_pick:#ME"]
    _assert_discord_payload(view)


def test_category_progress_bars_align_in_a_code_span():
    """Proportional text will not align padded plain text; a code span will."""
    inventory = {"cards": {card.id: cards.OWNED for card in cards.CARDS}}
    complete = cards_command._category_progress(inventory)

    for line in complete.split("\n"):
        # Emoji outside the backticks so it renders as art; bar and tally
        # inside so the column lines up.
        assert line.count("`") == 2
        bar = line.split("`")[1]
        assert bar.startswith(cards_command.PROGRESS_FULL * cards_command.PROGRESS_WIDTH)
        assert line.endswith("\u2713")

    empty = cards_command._category_progress({"cards": {}})
    assert cards_command.PROGRESS_EMPTY not in complete.split("`")[1]
    # An untouched collection defaults to owned, so nothing is claimed empty
    # that the member never said was empty.
    assert len(empty.split("\n")) == len(cards.CATEGORIES)


def test_progress_bar_width_is_constant_so_the_column_never_jitters():
    for held in (0, 1, 7, 19):
        values = {card.id: cards.MISSING for card in cards.CARDS}
        for card in cards.CATEGORY_CARDS["elixir"][:held]:
            values[card.id] = cards.OWNED
        line = cards_command._category_progress({"cards": values}).split("\n")[0]
        bar = line.split("`")[1].split(" ")[0]
        assert len(bar) == cards_command.PROGRESS_WIDTH


def _many_holders(inventory, count, missing_ids):
    """`count` family collections, each able to supply some missing card."""
    base = {card.id: cards.OWNED for card in cards.CARDS}
    out = []
    for index in range(count):
        values = dict(base)
        for offset, card_id in enumerate(missing_ids):
            values[card_id] = cards.DUPLICATE if index % (offset + 2) == 0 else cards.OWNED
        # Only some of them need the requester's spare, so both sections fill.
        values["wizard"] = cards.MISSING if index % 3 == 0 else cards.OWNED
        out.append({
            "_id": f"#H{index}",
            "player_name": f"Player {index}",
            "cards": values,
            "complete_categories": [c.id for c in cards.CATEGORIES],
            "confirmed_at": datetime.now(timezone.utc),
        })
    return out


def test_find_trades_is_card_shaped_so_it_does_not_grow_with_the_family():
    """One block per holder did not survive a hundred-member family."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    missing_ids = ["root_rider", "druid", "cannon_cart"]
    inventory = _complete_inventory()
    for card_id in missing_ids:
        inventory["cards"][card_id] = cards.MISSING
    inventory["cards"]["wizard"] = cards.DUPLICATE

    small = cards.find_matches(inventory, _many_holders(inventory, 3, missing_ids))
    large = cards.find_matches(inventory, _many_holders(inventory, 120, missing_ids))
    assert len(large) > len(small)

    small_text = _view_text(cards_command._matches_view(account, inventory, small))
    large_text = _view_text(cards_command._matches_view(account, inventory, large))

    # The panel is bounded by missing cards, not by how many people matched.
    assert len(large_text.split("\n")) == len(small_text.split("\n"))
    _assert_discord_payload(
        cards_command._matches_view(account, inventory, large)
    )


def test_dashboard_states_each_fact_once():
    """Four representations of the same counts read as thrown together."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["barbarian"] = cards.MISSING

    view = cards_command._dashboard(account, inventory, account_count=1)
    text = _view_text(view)

    # The board image already draws a counted pill per category, so the panel
    # must not also print progress bars for them.
    assert cards_command.PROGRESS_FULL not in text
    assert cards_command.PROGRESS_EMPTY not in text
    # One summary line, not a stack of them.
    assert text.count("collected") == 1
    _assert_discord_payload(view)


def test_find_trades_absorbs_what_who_has_what_uniquely_showed():
    """Who has what mostly repeated this screen; its one distinct part moved."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING
    inventory["cards"]["wizard"] = cards.DUPLICATE

    base = {card.id: cards.OWNED for card in cards.CARDS}
    holders = [{
        "_id": "#H", "player_name": "Holder",
        "cards": dict(base, root_rider=cards.DUPLICATE, wizard=cards.MISSING),
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]
    matches = cards.find_matches(inventory, holders)
    view = cards_command._matches_view(
        account, inventory, matches,
        supply=cards.family_supply([inventory, *holders]),
        achievable=cards_command._achievable_from_matches(matches, "#ME"),
    )
    text = _view_text(view)

    # And the part that was pure noise is gone: cards nobody can supply.
    assert "Nobody has a spare yet" not in text
    assert any(
        n.get("custom_id") == "cards_demand:#ME" for n in _view_nodes(view)
    ), "no way through to the demand list"
    _assert_discord_payload(view)

    demand = cards_command._demand_view(
        account, inventory, cards.family_supply([inventory, *holders])
    )
    assert "Your spares others want" in _view_text(demand)
    assert "Wizard" in _view_text(demand)
    _assert_discord_payload(demand)


def test_board_controls_wrap_instead_of_dropping_the_sixth():
    """Every control the board decides to show must actually be rendered."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    # The state that produces the most controls at once: some categories set
    # up but not all, a pending spare check, and more than one linked account.
    inventory = _complete_inventory()
    inventory["complete_categories"] = ["elixir"]
    inventory["confirmed_at"] = datetime.now(timezone.utc) - timedelta(days=5)
    inventory["scan_duplicate_unverified_card_ids"] = ["wizard"]

    view = cards_command._dashboard(account, inventory, account_count=3)
    ids = {n.get("custom_id") for n in _view_nodes(view)}

    for expected in (
        "cards_hidden:#ME",
        "cards_advanced:#ME",
        "cards_account_page:0|#ME",
    ):
        assert expected in ids, f"{expected} was dropped from the board"
    for node in _view_nodes(view):
        if node.get("type") == 1:
            assert len(node.get("components", [])) <= 5
    _assert_discord_payload(view)


def test_refresh_and_pagination_use_the_uploaded_control_emoji():
    """Every control resolves to the emoji the registry names for it.

    Pinned to the registry rather than to literal snowflakes: the ids change
    whenever an emoji is re-uploaded, and a test that hardcodes them fails on
    a swap that is entirely correct, which teaches people to edit the numbers
    until it passes. What must not break is a control silently losing its
    mark - _safe_partial returns UNDEFINED instead of raising, so a malformed
    entry would go unnoticed.
    """
    for name, resolved in (
        ("refresh", cards_command.REFRESH_EMOJI),
        ("next_page", cards_command.NEXT_EMOJI),
        ("previous_page", cards_command.PREVIOUS_EMOJI),
        ("return_arrow", cards_command.RETURN_EMOJI),
        ("magnifier", cards_command.SEARCH_EMOJI),
        ("no", cards_command.CANCEL_EMOJI),
        ("inbox", cards_command.TRADES_EMOJI),
        ("switch", cards_command.SWITCH_EMOJI),
        ("scan", cards_command.SCAN_EMOJI),
        ("home", cards_command.HOME_EMOJI),
        ("card_give", cards_command.GIVE_EMOJI),
        ("card_swap", cards_command.SWAP_EMOJI),
        ("card_hot", cards_command.HOT_EMOJI),
        ("gems", cards_command.GEMS_EMOJI),
    ):
        assert resolved is not hikari.UNDEFINED, f"{name} lost its emoji"
        assert resolved.id == getattr(
            cards_command.emojis, name
        ).partial_emoji.id


def _offer_holder(returns):
    """A match whose reciprocal leg offers exactly `returns`."""
    return SimpleNamespace(
        holder_tag="#H", holder_name="Holder", holder_discord_id=7,
        holder_clan_tag="#C", holder_clan_name="Clan", same_clan=True,
        confirmed_at=datetime.now(timezone.utc),
        exchanges=(cards.CategoryExchange(
            category="elixir", offers=("balloon",), returns=tuple(returns),
        ),),
    )


def test_a_single_giveable_card_sends_without_a_menu():
    """A one-entry menu asks the member to decide something already decided."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._trade_offer_view(
        account, "balloon", _offer_holder(["electro_dragon"])
    )
    nodes = _view_nodes(view)

    assert [n for n in nodes if n.get("type") == 3] == [], "still a menu"
    send = next(
        n for n in nodes
        if str(n.get("custom_id", "")).startswith("cards_trade_request:")
    )
    # Everything the select would have carried now rides in the custom_id.
    assert send["custom_id"] == "cards_trade_request:#ME|balloon|#H|electro_dragon"
    assert "Electro Dragon" in send["label"]
    assert "Electro Dragon" in _view_text(view)
    _assert_discord_payload(view)


def test_several_giveable_cards_still_offer_a_choice_with_art():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    returns = ["electro_dragon", "dragon", "wizard"]
    # The troop cache is primed from Mongo at startup, so it is empty here.
    # Without priming, this test would pass whether or not the menu asks for
    # the art, because partial() returns UNDEFINED either way.
    troop_emoji.prime([
        {"slug": slug, "emoji_id": 1000 + index, "name": f"troop_{slug}"}
        for index, slug in enumerate(returns)
    ])
    try:
        view = cards_command._trade_offer_view(
            account, "balloon", _offer_holder(returns)
        )
        menu = next(n for n in _view_nodes(view) if n.get("type") == 3)

        assert [o["value"] for o in menu["options"]] == [
            f"#H|{r}" for r in returns
        ]
        # Every other card menu shows the troop art; this one was words only.
        for option in menu["options"]:
            assert option.get("emoji"), f"{option['label']} has no art"
        _assert_discord_payload(view)
    finally:
        troop_emoji.clear()


def test_the_direct_send_custom_id_fits_discords_limit():
    """Four segments in one id; the longest card names must still fit."""
    account = Account(
        tag="#ME000000000", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    longest = max((c.id for c in cards.CARDS), key=len)
    elixir = [c.id for c in cards.CATEGORY_CARDS["elixir"]]
    target = longest if longest in elixir else elixir[0]
    view = cards_command._trade_offer_view(
        account, "balloon", _offer_holder([target])
    )
    send = next(
        n for n in _view_nodes(view)
        if str(n.get("custom_id", "")).startswith("cards_trade_request:")
    )

    assert len(send["custom_id"]) <= 100
    assert send["custom_id"].count(":") == 1


def test_my_trades_and_switch_account_use_the_uploaded_emoji():
    """The same destination must not be marked differently on different screens."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING
    holders = [{
        "_id": "#H", "player_name": "Holder", "discord_id": 7,
        "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]
    views = [
        cards_command._dashboard(account, inventory, account_count=3),
        cards_command._matches_view(
            account, inventory, cards.find_matches(inventory, holders)
        ),
        cards_command._active_trade_notice(account.tag),
        cards_command._trade_feedback("Saved", "Ready", "#ME"),
    ]
    seen = 0
    for view in views:
        for node in _view_nodes(view):
            if str(node.get("label", "")) == "My trades":
                emoji = node.get("emoji") or {}
                assert emoji.get("id") == "1536798617736847431", node
                seen += 1
    assert seen >= 4, f"only checked {seen} My trades buttons"

    switch = next(
        n for n in _view_nodes(views[0])
        if n.get("custom_id") == "cards_account_page:0|#ME"
    )
    assert (switch.get("emoji") or {}).get("id") == "1536798904056815806"


def test_search_and_cancel_buttons_use_the_uploaded_emoji():
    """Find and cancel are their own kinds of control; each gets one mark."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING

    board = cards_command._dashboard(account, inventory, account_count=1)
    find = next(
        n for n in _view_nodes(board)
        if n.get("custom_id") == "cards_matches:#ME"
    )
    assert (find.get("emoji") or {}).get("id") == "1536797595089899540"

    # Cancel keeps its own mark: aborting a scan is not going back a screen.
    cancels = 0
    for view in (
        cards_command._scan_upload_prompt(account, "draft", usable_until=None),
        cards_command._trades_view(account, []),
    ):
        for node in _view_nodes(view):
            if "cancel" in str(node.get("label", "")).lower():
                emoji = node.get("emoji") or {}
                assert emoji.get("id") == "1397096986506825778", node.get("label")
                assert emoji.get("id") != str(cards_command.RETURN_EMOJI.id)
                cancels += 1
    assert cancels, "no cancel button was actually checked"


def test_the_count_modal_fits_every_card_name():
    """"How many <card> cards do you have?" does not fit and was rejected.

    A modal title caps at 45 characters. Super Wall Breaker takes that phrasing
    to 46, and the code truncates - so the longest names would have lost their
    question mark silently. The title is the card name and the field carries
    the question instead, in the same words as the screen you came from.
    """
    for card in cards.CARDS:
        assert len(card.name) <= 45, f"{card.name} cannot title a modal"
        assert len(f"How many {card.name} cards do you have?") <= 45 or True
    # The phrasing that was rejected, kept here so the reason is testable.
    longest = max(cards.CARDS, key=lambda c: len(c.name))
    assert len(f"How many {longest.name} cards do you have?") > 45
    assert len("How many do you have?") <= 45


def test_the_card_screen_says_you_can_keep_editing():
    """The category menu stays mounted, and nothing said so.

    Pick, set, pick, set without returning to the collection is the fastest
    way to edit - and you only found it by noticing the menu had not gone
    away. It cannot be said in the menu: the default-marked header option is
    drawn in place of the placeholder, so the placeholder is never seen.
    """
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    view = cards_command._card_focus(
        account, _complete_inventory(), "barbarian"
    )
    text = _view_text(view)
    menus = [
        n for n in _view_nodes(view)
        if n.get("type") == 3
        and str(n.get("custom_id", "")).startswith("cards_pick:")
    ]

    assert menus, "the category menu must stay on the card screen"
    assert "Pick another card to keep editing" in text
    _assert_discord_payload(view)


def test_the_editor_never_uses_a_tick_to_mean_three_different_things():
    """Green and a tick meant "there are none", "reviewed" and "done" at once.

    The worst of it: the clear buttons turned SUCCESS once their list was
    already empty, so "✅ No missing cards" rendered directly beneath three
    missing cards and read as the bot contradicting itself.
    """
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    for card_id in ("balloon", "thrower", "meteor_golem"):
        inventory["cards"][card_id] = cards.MISSING

    inventory["cards"]["barbarian"] = 3

    for complete in ([], ["elixir"]):
        inventory["complete_categories"] = complete
        for card in cards.CATEGORY_CARDS["elixir"]:
            view = cards_command._quantity_editor(
                account, inventory, "elixir", card_id=card.id
            )
            for button in [n for n in _view_nodes(view) if n.get("type") == 2]:
                assert not (button.get("emoji") or {}).get("name") == "\u2705", (
                    "no tick anywhere: it meant none, reviewed and done at once"
                )
            # Green survives on +1 alone, where it means "add" rather than
            # "this is your current state". Nothing green ever reports a value.
            green = [
                str(n.get("label"))
                for n in _view_nodes(view)
                if n.get("type") == 2 and n.get("style") == 3
            ]
            assert green == ["+1"], green

    # Status says what finishing buys you, not that a list was "reviewed".
    text = _view_text(
        cards_command._quantity_editor(account, inventory, "elixir")
    )
    assert "reviewed" not in text.lower()
    assert "Ready to trade." in text
    assert "Other players can see these spares." in text
    # One word for the concept, on every page. The rest of the command says
    # "spare" everywhere, so this screen must not introduce "duplicate" as a
    # second name for the same thing.
    view = cards_command._quantity_editor(account, inventory, "elixir")
    written = (_view_text(view) + " ".join(_view_labels(view))).lower()
    assert "duplicate" not in written

    # Counts are digits, not five different English phrasings of a digit. The
    # one token that survives is 2+, which is the scanner's floor and means
    # something a flat 2 would not.
    counts = {
        line.rsplit(" \u00b7 ", 1)[-1].strip("*`")
        for line in _view_text(view).splitlines()
        if " \u00b7 " in line and not line.startswith(("#", "-#"))
    }
    assert counts <= {"0", "1", "2", "3", "2+"}, counts
    for banned in ("Missing", "Have 1", "copies", "Might be"):
        assert banned not in _view_text(view), banned


def test_every_button_back_to_the_collection_names_it():
    """Audited by destination, not by label.

    The terminology sweep searched for the old labels and replaced those, so a
    button that had always just said "Back" was never found - it shipped
    saying "Back" on a screen where everything else said "collection". Reading
    the source for `cards_dashboard` targets is the only check that cannot
    miss one.

    Deliberate exceptions are listed by name: they answer a question rather
    than navigate, and "Not now" must not become "Back to collection".
    """
    intentional = {
        "Done", "Later", "Not now", "Skip, 2+ is fine", "Collection",
    }
    source = pathlib.Path(
        cards_command.__file__.replace(".pyc", ".py")
    ).read_text(encoding="utf-8")

    offenders = []
    for match in re.finditer(r"Button\((.*?)\)\s*,?\s*\n", source, re.S):
        block = match.group(1)
        target = re.search(r'custom_id=f?"([^"]+)"', block)
        label = re.search(r'label=f?"([^"]+)"', block)
        if not target or not label:
            continue
        if target.group(1).split(":")[0] != "cards_dashboard":
            continue
        text = label.group(1)
        if text in intentional or text == "Back to collection":
            continue
        offenders.append((source[:match.start()].count("\n") + 1, text))

    assert not offenders, (
        "buttons returning to the collection without naming it: "
        + ", ".join(f"line {line}: {text!r}" for line, text in offenders)
    )


def test_no_back_button_is_left_on_a_unicode_arrow():
    """A mix of uploaded and unicode arrows on the same kind of button reads sloppy."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING
    holders = [{
        "_id": "#H", "player_name": "Holder", "discord_id": 7,
        "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]
    views = [
        cards_command._matches_view(
            account, inventory, cards.find_matches(inventory, holders)
        ),
        cards_command._holders_view(
            account, "root_rider",
            cards.holders_for_card(inventory, holders, "root_rider"),
        ),
        cards_command._quantity_editor(account, inventory, "elixir"),
        cards_command._trades_view(account, []),
        cards_command._active_trade_notice(account.tag),
    ]
    seen = 0
    for view in views:
        for node in _view_nodes(view):
            label = str(node.get("label", "")).lower()
            if not any(
                word in label
                # "collection" is here because the buttons that used to be
                # labelled "Dashboard" are now "Collection" - one name for one
                # screen. Without it this scan quietly checked one fewer.
                for word in (
                    "back", "dashboard", "collection", "return", "all categories"
                )
            ):
                continue
            emoji = node.get("emoji") or {}
            assert "⬅" not in str(emoji.get("name") or ""), (
                f"{label!r} still uses the unicode arrow"
            )
            assert emoji.get("id"), f"{label!r} carries no return emoji"
            seen += 1
    assert seen >= 6, f"only checked {seen} back buttons"


def test_no_control_button_is_left_on_a_stand_in_emoji():
    """A mix of uploaded and unicode marks on the same kind of button reads sloppy."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING
    # More holders than fit one page, so the pagination row actually renders -
    # otherwise this test passes without ever seeing a next/previous button.
    holders = [{
        "_id": f"#H{index}", "player_name": f"Holder{index}",
        "discord_id": index,
        "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    } for index in range(cards_command.HOLDER_RESULT_LIMIT + 2)]
    matches = cards.find_matches(inventory, holders)
    views = [
        cards_command._dashboard(account, inventory, account_count=1),
        cards_command._matches_view(account, inventory, matches),
        cards_command._holders_view(
            account, "root_rider", cards.holders_for_card(
                inventory, holders, "root_rider"
            )
        ),
        # Find trades no longer carries Refresh - it was one control too many
        # on the screen people got lost on - so My trades is where it lives.
        cards_command._trades_view(account, []),
    ]
    wanted = {"refresh", "next", "previous"}
    seen = set()
    for view in views:
        for node in _view_nodes(view):
            label = str(node.get("label", "")).lower()
            word = next((w for w in wanted if w in label), None)
            if word is None:
                continue
            emoji = node.get("emoji") or {}
            assert emoji.get("id"), f"{label!r} still uses a stand-in emoji"
            seen.add(word)
    assert seen == wanted, f"never rendered: {wanted - seen}"


def test_every_category_has_its_uploaded_emoji():
    """All four categories resolve, in both the text and the component form."""
    expected = {
        "elixir": "<:Elixer:1536777630278357164>",
        "dark_elixir": "<:Dark_Elixer:1536777729511391322>",
        "builder_base": "<:buildervillage:1536777943710310421>",
        "super_troop": "<:SuperTroops:1536777871111225374>",
    }
    assert {c.id for c in cards.CATEGORIES} == set(expected)
    for category_id, markup in expected.items():
        assert cards_command.category_markup(category_id) == markup
        partial = cards_command.category_partial(category_id)
        assert partial is not hikari.UNDEFINED
        assert f"<:{partial.name}:{partial.id}>" == markup


def test_unknown_category_emoji_degrades_instead_of_raising():
    """A bad id must not take down every panel that names a category."""
    assert cards_command.category_markup("not_a_category") == ""
    assert cards_command.category_partial("not_a_category") is hikari.UNDEFINED


def test_category_headings_carry_the_uploaded_emoji():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    text = _view_text(
        cards_command._quantity_editor(account, _complete_inventory(), "dark_elixir")
    )
    assert "<:Dark_Elixer:1536777729511391322>" in text


def test_select_placeholders_never_carry_custom_emoji_markup():
    """A placeholder is plain text; markup would print as `<:Elixer:123>`."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING
    base = {card.id: cards.DUPLICATE for card in cards.CARDS}
    holders = [{
        "_id": "#H", "player_name": "Holder", "cards": base,
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]
    views = [
        cards_command._dashboard(account, inventory, account_count=1),
        cards_command._matches_view(
            account, inventory, cards.find_matches(inventory, holders)
        ),
        cards_command._quantity_editor(account, inventory, "elixir"),
    ]
    for view in views:
        for node in _view_nodes(view):
            placeholder = node.get("placeholder")
            if placeholder:
                assert "<:" not in placeholder, placeholder


def test_find_trades_survives_a_hundred_family_accounts():
    """The screen must be bounded by the 60 cards, not by the family size."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    for card in cards.CARDS[:40]:
        inventory["cards"][card.id] = cards.MISSING
    inventory["cards"]["wizard"] = cards.DUPLICATE

    holders = [{
        "_id": f"#H{index}", "player_name": f"Holder{index}",
        "discord_id": index,
        "cards": dict(
            {card.id: cards.DUPLICATE for card in cards.CARDS},
            wizard=cards.MISSING,
        ),
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    } for index in range(100)]
    matches = cards.find_matches(inventory, holders)
    supply = cards.family_supply([inventory, *holders])

    # 100 holders, and every screen still has to fit inside one message.
    assert len({m.holder_tag for m in matches}) == 100
    _assert_discord_payload(cards_command._matches_view(
        account, inventory, matches, supply=supply,
        achievable=cards_command._achievable_from_matches(matches, "#ME"),
    ))
    for page in range(3):
        _assert_discord_payload(
            cards_command._favours_view(account, matches, page=page)
        )
        _assert_discord_payload(
            cards_command._demand_view(account, inventory, supply, page=page)
        )


def test_match_lists_page_rather_than_truncate():
    """Silently dropping the tail is what the 25-option menu used to do."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    missing = [c.id for c in cards.CARDS[:40]]
    for card_id in missing:
        inventory["cards"][card_id] = cards.MISSING
    holders = [{
        "_id": "#H", "player_name": "Holder", "discord_id": 1,
        "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]
    matches = cards.find_matches(inventory, holders)

    view = cards_command._favours_view(account, matches)
    seen = {
        option["value"]
        for node in _view_nodes(view)
        if node.get("type") == 3
        for option in node["options"]
    } - {cards_command.CATEGORY_HEADER_VALUE}

    # Forty cards, no Next button: one menu per category holds all of them,
    # because the biggest category is 19 and the cap is 25.
    assert seen == set(missing), f"never reachable: {set(missing) - seen}"
    assert not [
        n for n in _view_nodes(view)
        if str(n.get("label", "")).startswith("Page ")
    ], "Ask for help should no longer page"


def test_find_trades_explains_a_swap_hidden_by_a_reservation():
    """A perfect swap vanishing with no reason reads as a broken bot."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["balloon"] = cards.DUPLICATE
    inventory["cards"]["electro_dragon"] = cards.MISSING
    holders = [{
        "_id": "#H", "player_name": "Holder", "discord_id": 7,
        "cards": dict(
            {card.id: cards.OWNED for card in cards.CARDS},
            electro_dragon=cards.DUPLICATE, balloon=cards.MISSING,
        ),
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]

    # Free, the swap is obvious and shows up.
    free = cards.find_matches(inventory, holders)
    assert free, "the fixture itself must produce an even swap"
    open_text = _view_text(
        cards_command._matches_view(account, inventory, free)
    )
    assert "promised to an accepted trade" not in open_text

    # Reserved by an accepted trade, both legs are masked out and the swap
    # disappears - so the screen has to say why.
    inventory["card_trade_reservations"] = {
        "balloon": "trade-1", "electro_dragon": "trade-1",
    }
    masked = cards_command._without_reserved_cards(inventory)
    assert not cards.find_matches(masked, holders), "reservation should mask it"

    view = cards_command._matches_view(
        account, masked, [],
        reserved=len(cards_command._card_reservations(inventory)),
    )
    text = _view_text(view)
    assert "2 of your cards are promised to an accepted trade" in text
    assert "My trades" in text
    _assert_discord_payload(view)


def test_different_clans_names_both_of_them():
    """"You are in different clans" is useless when somebody has to move."""
    trade = {
        "requester_clan_name": "Morning Woods", "requester_clan_tag": "#HOME",
        "holder_clan_name": "Edrag Rush", "holder_clan_tag": "#AWAY",
    }
    holder_view = cards_command._trade_location_line(trade, role="holder")
    requester_view = cards_command._trade_location_line(trade, role="requester")

    # Both clans named, and "you" points at whoever is reading.
    for text in (holder_view, requester_view):
        assert "Morning Woods" in text and "#HOME" in text
        assert "Edrag Rush" in text and "#AWAY" in text
    assert holder_view.startswith("you are in Edrag Rush")
    assert requester_view.startswith("you are in Morning Woods")

    # The channel post is read by everyone, so it names neither side "you".
    everyone = cards_command._trade_location_line(trade)
    assert "you are in" not in everyone
    assert "Morning Woods" in everyone and "Edrag Rush" in everyone

    together = cards_command._trade_location_line(
        dict(trade, holder_clan_tag="#HOME", holder_clan_name="Morning Woods"),
        role="holder",
    )
    assert together == "You are both in Morning Woods • `#HOME`"


@pytest.mark.parametrize("stored", [
    None, "", "   ", "my clan", "<:Broken:notanumber>", "<:Broken:",
    "<:Bad:-5>", ":shrug:", 12345,
    # A logo URL is not an emoji: it is a full-size image and would render as
    # a link rather than a mark on the line.
    "https://res.cloudinary.com/x/clan.png",
])
def test_a_bad_clan_emoji_falls_back_to_a_shield(stored):
    """The field is hand-edited through the clan dashboard, so it holds anything."""
    assert cards_command._clan_emoji_markup(stored) == (
        cards_command.CLAN_FALLBACK_EMOJI
    )


def test_a_usable_clan_emoji_is_kept():
    markup = "<:Elixer:1536777630278357164>"
    assert cards_command._clan_emoji_markup(markup) == markup


def test_a_player_line_survives_every_piece_being_missing():
    """A DM must render even when the clan, tag and town hall are all absent."""
    bare = cards_command._player_line("You", None, None, None, None, None)
    assert "**You:**" in bare

    full = cards_command._player_line(
        "Them", "Sir UwU", "#ME", 18, "Edrag Rush",
        "<:Elixer:1536777630278357164>",
    )
    assert "Sir UwU" in full and "#ME" in full and "Edrag Rush" in full
    assert str(cards_command.emojis.TH18) in full
    assert "<:Elixer:1536777630278357164>" in full


@pytest.mark.parametrize("level", [None, "", 0, -3, 99, "eighteen", object()])
def test_an_unknown_town_hall_contributes_nothing(level):
    assert cards_command._th_markup(level) == ""


def test_a_known_town_hall_renders():
    assert cards_command._th_markup(18) == str(cards_command.emojis.TH18)
    assert cards_command._th_markup("17") == str(cards_command.emojis.TH17)


def test_who_has_what_destination_is_gone():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account, _complete_inventory(), account_count=1
    )
    ids = {n.get("custom_id") for n in _view_nodes(view)}

    assert "cards_family:#ME" not in ids
    assert not hasattr(cards_command, "cards_family")
    assert not hasattr(cards_command, "_family_board")


def test_the_real_proposal_dm_carries_accept_and_decline():
    """The DM is answerable in the DM; that was the whole point."""
    class Rest:
        def __init__(self):
            self.sent = []

        async def create_dm_channel(self, _discord_id):
            return "dm-channel"

        async def create_message(self, *, channel, components, flags=None):
            self.sent.append(components)

    rest = Rest()
    trade = _trade_document()
    trade.update({
        "requester_name": "Shaun", "requester_discord_id": 111,
        "holder_name": "Holder", "holder_discord_id": 222,
        "compatible_card_ids": ["wizard", "dragon"],
    })
    asyncio.run(cards_command._notify_trade_holder(
        SimpleNamespace(rest=rest), trade
    ))

    ids = {
        n.get("custom_id") for n in _view_nodes(rest.sent[0])
        if n.get("custom_id")
    }
    assert any(str(i).startswith("cards_dm_accept:") for i in ids), ids
    assert any(str(i).startswith("cards_dm_decline:") for i in ids), ids
    # Live buttons, not the disabled preview ones.
    for node in _view_nodes(rest.sent[0]):
        if str(node.get("custom_id", "")).startswith("cards_dm_"):
            assert node.get("disabled") is not True


def test_the_accepter_may_only_take_a_card_the_requester_offered():
    """compatible_card_ids is the requester's consent and bounds the choice."""
    trade = _trade_document()
    trade.update({
        "given_card_id": "wizard",
        "compatible_card_ids": ["wizard", "dragon"],
    })

    allowed = cards_command._trade_choice_ids(trade)
    assert allowed[0] == "wizard", "the proposed card comes first"
    assert set(allowed) == {"wizard", "dragon"}
    assert "root_rider" not in allowed


def test_choice_ids_ignore_unknown_and_duplicate_cards():
    trade = _trade_document()
    trade.update({
        "given_card_id": "wizard",
        "compatible_card_ids": ["wizard", "not_a_card", "dragon", "dragon"],
    })
    assert cards_command._trade_choice_ids(trade) == ["wizard", "dragon"]


def test_both_accept_entry_points_share_one_body():
    """The DM path must not be able to drift from the server path.

    Read from the file rather than via inspect: the handlers are wrapped by
    lightbulb's dependency injection, so getsource cannot see through them.
    """
    source = pathlib.Path(cards_command.__file__).read_text(encoding="utf-8")
    for entry in ("cards_trade_accept", "cards_dm_accept"):
        start = source.index(f"async def {entry}(")
        body = source[start:start + 1200]
        assert "_perform_trade_accept(" in body, entry


class _ConfirmInventories:
    """Two collections that honour the reservation fence."""

    def __init__(self, documents):
        self.documents = {d["_id"]: d for d in documents}

    async def find_one(self, query):
        return self.documents.get(query.get("_id"))

    async def update_one(self, query, update):
        document = self.documents.get(query.get("_id"))
        if document is None:
            return SimpleNamespace(modified_count=0)
        for clause in query.get("$or") or ():
            path, want = next(iter(clause.items()))
            card = path.split(".")[1]
            marker = document.get("card_trade_reservations", {}).get(card)
            owner = marker.get("owner") if isinstance(marker, dict) else marker
            if owner == want:
                break
        else:
            if query.get("$or"):
                return SimpleNamespace(modified_count=0)
        for key, want in query.items():
            if not key.startswith("cards."):
                continue
            have = document.get("cards", {}).get(key.split(".")[1], 1)
            if isinstance(want, dict) and have < want.get("$gte", 0):
                return SimpleNamespace(modified_count=0)
        for key, value in (update.get("$set") or {}).items():
            if key.startswith("cards."):
                document.setdefault("cards", {})[key.split(".")[1]] = value
        for key, delta in (update.get("$inc") or {}).items():
            if key.startswith("cards."):
                card = key.split(".")[1]
                document["cards"][card] = document["cards"].get(card, 0) + delta
        for key in (update.get("$unset") or {}):
            if key.startswith("card_trade_reservations."):
                document.get("card_trade_reservations", {}).pop(
                    key.split(".")[1], None
                )
        return SimpleNamespace(modified_count=1)


def _agreed_trade():
    trade = _trade_document()
    trade.update({
        "status": "ready",
        "reservation_token": "tok",
        "requester_discord_id": 111,
        "holder_discord_id": 222,
    })
    return trade


def test_confirming_moves_only_your_own_card():
    """Nobody waits for the other player; that was the whole point."""
    trade = _agreed_trade()
    owner = cards_command._reservation_owner(trade)
    given, wanted = trade["given_card_id"], trade["wanted_card_id"]
    trusted = [card.id for card in cards.CARDS]
    ready = [category.id for category in cards.CATEGORIES]
    inventories = _ConfirmInventories([
        {"_id": "#ME", "cards": {given: 3, wanted: 0},
         "trusted_card_ids": trusted, "complete_categories": ready,
         "card_trade_reservations": {given: owner, wanted: owner}},
        {"_id": "#HOLDER", "cards": {given: 0, wanted: 2},
         "trusted_card_ids": trusted, "complete_categories": ready,
         "card_trade_reservations": {given: owner, wanted: owner}},
    ])
    mongo = SimpleNamespace(card_inventories=inventories)

    moved, remaining = asyncio.run(cards_command._confirm_swap_leg(
        mongo, trade, role="requester", now=datetime.now(timezone.utc)
    ))

    assert moved is True
    assert remaining == 2, "one copy left, not the whole stack"
    # The card they sent moved to the other side.
    assert inventories.documents["#HOLDER"]["cards"][given] == cards.OWNED
    # And the holder's own card has NOT moved: they have not answered yet.
    assert inventories.documents["#HOLDER"]["cards"][wanted] == 2
    assert inventories.documents["#ME"]["cards"][wanted] == 0
    assert inventories.documents["#ME"]["trusted_card_ids"] == trusted
    assert inventories.documents["#HOLDER"]["trusted_card_ids"] == trusted
    assert inventories.documents["#ME"]["complete_categories"] == ready
    assert inventories.documents["#HOLDER"]["complete_categories"] == ready
    # Only the transferred card is unreserved, on both inventory documents.
    # The other participant's promised card remains fenced until their leg.
    for tag in ("#ME", "#HOLDER"):
        reservations = inventories.documents[tag]["card_trade_reservations"]
        assert given not in reservations
        assert wanted in reservations


def test_real_first_leg_hides_only_the_completed_same_owner_account():
    now = datetime.now(timezone.utc)
    trade = _agreed_trade()
    trade.update({
        "kind": "trade",
        "updated_at": now,
        "requester_discord_id": 111,
        "holder_discord_id": 111,
    })
    owner = cards_command._reservation_owner(trade)
    given, wanted = trade["given_card_id"], trade["wanted_card_id"]
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = dict(trade)
    trades.docs.update(_lease_documents(trade))
    inventories = _FakeInventoryCollection([
        {
            "_id": "#ME",
            "guild_id": 1,
            "cards": {given: cards.DUPLICATE, wanted: cards.MISSING},
            "card_trade_reservations": {given: owner, wanted: owner},
        },
        {
            "_id": "#HOLDER",
            "guild_id": 1,
            "cards": {given: cards.MISSING, wanted: cards.DUPLICATE},
            "card_trade_reservations": {given: owner, wanted: owner},
        },
    ])
    mongo = SimpleNamespace(
        card_trades=trades,
        card_inventories=inventories,
    )

    outcome, remaining, saved = asyncio.run(
        cards_command._run_swap_leg_confirmation(
            mongo,
            trade,
            role="requester",
            now=now,
            record_no_spare=False,
        )
    )

    assert outcome == "moved"
    assert remaining == cards.OWNED
    assert saved["status"] == "ready"
    assert saved["requester_confirmed_at"] == now
    assert "holder_confirmed_at" not in saved
    assert inventories.documents["#ME"]["cards"][given] == cards.OWNED
    assert inventories.documents["#ME"]["cards"][wanted] == cards.MISSING
    assert inventories.documents["#HOLDER"]["cards"][given] == cards.OWNED
    assert inventories.documents["#HOLDER"]["cards"][wanted] == cards.DUPLICATE
    for inventory in inventories.documents.values():
        assert set(inventory["card_trade_reservations"]) == {wanted}
    assert len([
        row for row in trades.docs.values() if row.get("kind") == "lease"
    ]) == 4, "terminal cleanup must not release the other leg's leases"

    requester_active = asyncio.run(cards_command._active_trades(
        mongo, tag="#ME", guild_id=1
    ))
    holder_active = asyncio.run(cards_command._active_trades(
        mongo, tag="#HOLDER", guild_id=1
    ))
    unrelated_active = asyncio.run(cards_command._active_trades(
        mongo, tag="#THIRD", guild_id=1
    ))

    assert requester_active == []
    assert [row["_id"] for row in holder_active] == [trade["_id"]]
    assert unrelated_active == []
    holder_ids = {
        str(node.get("custom_id")) for node in _view_nodes(
            cards_command._trades_view(
                Account(
                    tag="#HOLDER", name="Holder", clan_tag="#HOME",
                    clan_name="Home Clan", town_hall=18,
                ),
                holder_active,
            )
        )
    }
    assert "cards_swap_sent:trade-a|holder" in holder_ids


def test_confirming_a_card_you_no_longer_hold_moves_nothing():
    trade = _agreed_trade()
    owner = cards_command._reservation_owner(trade)
    given = trade["given_card_id"]
    inventories = _ConfirmInventories([
        {"_id": "#ME", "cards": {given: 1},
         "card_trade_reservations": {given: owner}},
        {"_id": "#HOLDER", "cards": {given: 0},
         "card_trade_reservations": {given: owner}},
    ])
    mongo = SimpleNamespace(card_inventories=inventories)

    moved, _remaining = asyncio.run(cards_command._confirm_swap_leg(
        mongo, trade, role="requester", now=datetime.now(timezone.utc)
    ))

    assert moved is False
    assert inventories.documents["#HOLDER"]["cards"][given] == 0


def test_only_the_unanswered_side_is_asked():
    trade = _agreed_trade()
    assert cards_command._awaiting_confirmation(trade, role="requester")
    assert cards_command._awaiting_confirmation(trade, role="holder")

    trade["requester_confirmed_at"] = datetime.now(timezone.utc)
    assert not cards_command._awaiting_confirmation(trade, role="requester")
    assert cards_command._awaiting_confirmation(trade, role="holder")

    # A closed swap asks nobody.
    trade["status"] = "completed"
    assert not cards_command._awaiting_confirmation(trade, role="holder")


def test_the_second_confirmation_closes_the_swap():
    trade = _agreed_trade()
    trade["requester_confirmed_at"] = datetime.now(timezone.utc)
    writes = []

    class Trades:
        async def update_one(self, query, update):
            writes.append((query, update))

        async def find_one(self, _query):
            return dict(trade)

    async def _no_cleanup(*_args, **_kwargs):
        return True

    mongo = SimpleNamespace(card_trades=Trades())
    import extensions.commands.cards as module
    original = module._finish_trade_cleanup
    module._finish_trade_cleanup = _no_cleanup
    try:
        updated = asyncio.run(cards_command._record_swap_confirmation(
            mongo, trade, role="holder", now=datetime.now(timezone.utc)
        ))
    finally:
        module._finish_trade_cleanup = original

    assert updated["status"] == "completed"
    assert writes[0][1]["$set"]["status"] == "completed"


def test_the_first_confirmation_starts_the_other_sides_clock():
    trade = _agreed_trade()
    writes = []

    class Trades:
        async def update_one(self, query, update):
            writes.append(update)

    mongo = SimpleNamespace(card_trades=Trades())
    now = datetime.now(timezone.utc)
    updated = asyncio.run(cards_command._record_swap_confirmation(
        mongo, trade, role="requester", now=now
    ))

    assert updated["status"] == "ready", "one answer does not finish a swap"
    deadline = writes[0]["$set"]["confirm_deadline_at"]
    assert deadline == now + cards_command.SWAP_CONFIRM_FOR


def test_the_two_back_buttons_do_not_wear_the_same_mark():
    """Two identically-marked buttons side by side read as one duplicated."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING
    holders = [{
        "_id": "#H", "player_name": "Holder", "discord_id": 7,
        "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]
    matches = cards.find_matches(inventory, holders)

    views = [
        cards_command._favours_view(account, matches),
        cards_command._holders_view(
            account, "root_rider",
            cards.holders_for_card(inventory, holders, "root_rider"),
        ),
    ]
    checked = 0
    for view in views:
        marks = {}
        for node in _view_nodes(view):
            label = str(node.get("label", ""))
            if label in ("Back to collection", "Back to Find trades"):
                marks[label] = (node.get("emoji") or {}).get("id")
        if len(marks) < 2:
            continue
        checked += 1
        assert marks["Back to collection"] == str(cards_command.HOME_EMOJI.id)
        assert marks["Back to Find trades"] == str(
            cards_command.RETURN_EMOJI.id
        )
        assert marks["Back to collection"] != marks["Back to Find trades"]
    assert checked == 2, f"only checked {checked} screens"


def _two_way_and_one_way():
    """A fixture with one even swap and three one-way offers."""
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#H",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["electro_dragon"] = cards.MISSING   # even swap
    inventory["cards"]["balloon"] = cards.DUPLICATE
    for card_id in ("bomber", "super_minion", "hog_rider"):
        inventory["cards"][card_id] = cards.MISSING        # one-way
    holder_cards = dict(
        {card.id: cards.OWNED for card in cards.CARDS},
        electro_dragon=cards.DUPLICATE, balloon=cards.MISSING,
    )
    for card_id in ("bomber", "super_minion", "hog_rider"):
        holder_cards[card_id] = cards.DUPLICATE
    holders = [{
        "_id": "#UWU", "player_name": "Sir UwU", "discord_id": 5,
        "clan_tag": "#H", "clan_name": "Morning Woods",
        "cards": holder_cards,
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    }]
    return account, inventory, holders, cards.find_matches(inventory, holders)


def _menu_values(view):
    return {
        option["value"]
        for node in _view_nodes(view)
        if node.get("type") == 3
        for option in node["options"]
        if option["value"] != cards_command.CATEGORY_HEADER_VALUE
    }


def test_the_card_you_read_is_the_card_you_tap():
    """Naming a card in text above an unrelated menu is what lost people.

    A member could read "Electro Dragon" under Even swaps and then had to
    work out on their own that it lived behind a menu called "Elixir".
    """
    account, inventory, _holders, matches = _two_way_and_one_way()
    view = cards_command._matches_view(account, inventory, matches)

    assert "electro_dragon" in _menu_values(view), "the even swap is not tappable"
    # And it is not ALSO printed as unreachable text above the menu.
    text = _view_text(view)
    assert "Electro Dragon" not in text
    # Nothing one-way leaks onto the front screen.
    assert _menu_values(view) == {"electro_dragon"}
    _assert_discord_payload(view)


def test_every_match_is_tappable_on_one_screen_or_the_other():
    account, inventory, _holders, matches = _two_way_and_one_way()
    per_card = cards_command._offers_by_card(matches)

    front = _menu_values(cards_command._matches_view(account, inventory, matches))
    favours = _menu_values(cards_command._favours_view(account, matches))

    assert front | favours == set(per_card), "a match is reachable nowhere"
    assert not (front & favours), "the same card is offered on both screens"
    assert favours == {"bomber", "super_minion", "hog_rider"}


def test_a_long_list_splits_by_category_but_still_names_cards():
    """Four labelled menus, and inside them the labels stay card names.

    The only non-card option is each menu's own category header, which is the
    default-marked row that puts the category art on the closed menu.
    """
    account, inventory, holders, _matches = _two_way_and_one_way()
    for card in cards.CARDS[:40]:
        inventory["cards"][card.id] = cards.MISSING
    holders[0]["cards"] = {card.id: cards.DUPLICATE for card in cards.CARDS}
    matches = cards.find_matches(inventory, holders)

    view = cards_command._favours_view(account, matches)
    menus = [n for n in _view_nodes(view) if n.get("type") == 3]

    assert len(menus) == len(cards.CATEGORIES)
    for menu in menus:
        assert len(menu["options"]) <= 25
        headers = [
            option for option in menu["options"]
            if option["value"] == cards_command.CATEGORY_HEADER_VALUE
        ]
        assert len(headers) == 1 and headers[0].get("default") is True
        for option in menu["options"]:
            if option["value"] == cards_command.CATEGORY_HEADER_VALUE:
                continue
            assert option["label"] in {c.name for c in cards.CARDS}
    _assert_discord_payload(view)


def test_find_trades_keeps_the_control_count_low():
    """Eight controls with no instruction is what lost people."""
    account, inventory, _holders, matches = _two_way_and_one_way()
    view = cards_command._matches_view(
        account, inventory, matches,
        achievable=cards_command._achievable_from_matches(matches, "#ME"),
    )
    controls = [
        node for node in _view_nodes(view)
        if node.get("type") in (2, 3)
    ]

    assert len(controls) <= 5, [n.get("label") or n.get("placeholder") for n in controls]
    # And the screen says what to do, before it says anything else.
    text = _view_text(view)
    assert "Pick a card from the menu below" in text
    assert text.index("Pick a card") < text.index("collection")


def test_no_screen_overflows_with_a_hundred_family_members():
    """Discord rejects the WHOLE message past 40 components, not the extras.

    hikari does not catch it locally, so an overflow only ever shows up in
    production, on the panel belonging to whoever has the most matches.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#H",
        clan_name="Morning Woods", town_hall=18,
    )
    # Missing 59 of 60 cards, one spare, and everybody holds everything.
    inventory = _complete_inventory()
    for card in cards.CARDS[1:]:
        inventory["cards"][card.id] = cards.MISSING
    inventory["cards"][cards.CARDS[0].id] = cards.DUPLICATE
    holders = [{
        "_id": f"#H{index}",
        # Long names, because they widen the text but not the component count.
        "player_name": "Holder" * 8,
        "discord_id": index,
        "clan_tag": "#H", "clan_name": "Morning Woods",
        "cards": dict(
            {card.id: cards.DUPLICATE for card in cards.CARDS},
            **{cards.CARDS[0].id: cards.MISSING},
        ),
        "complete_categories": [c.id for c in cards.CATEGORIES],
        "confirmed_at": datetime.now(timezone.utc),
    } for index in range(100)]
    matches = cards.find_matches(inventory, holders)
    supply = cards.family_supply([inventory, *holders])

    def used(view):
        payload = [component.build() for component in view]
        return len([n for n in _walk_payload(payload) if "type" in n])

    screens = {
        "find trades": cards_command._matches_view(
            account, inventory, matches, supply=supply,
            achievable=cards_command._achievable_from_matches(matches, "#ME"),
        ),
        "ask for help": cards_command._favours_view(account, matches),
        "spares in demand": cards_command._demand_view(
            account, inventory, supply
        ),
        "who has": cards_command._holders_view(
            account, cards.CARDS[1].id,
            cards.holders_for_card(inventory, holders, cards.CARDS[1].id),
        ),
    }
    for name, view in screens.items():
        # Headroom, not just "fits": a screen at 39 breaks on the next edit.
        assert used(view) <= 36, f"{name} is at {used(view)}/40"
        _assert_discord_payload(view)

    # And no menu can exceed Discord's 25 options.
    for name, view in screens.items():
        for node in _view_nodes(view):
            if node.get("type") == 3:
                assert len(node["options"]) <= 25, name


def test_ask_for_help_says_you_pay_and_quotes_the_real_price():
    """It said the SENDER pays, which is backwards, and quoted no figure.

    The gems cover the card you cannot supply a duplicate of, so they come out
    of the asker's pocket, and the price is fixed per category.
    """
    account, _inventory, _holders, matches = _two_way_and_one_way()
    text = _view_text(cards_command._favours_view(account, matches))

    assert "you pay gems instead" in text
    for cost in (50, 70, 90, 110):
        assert str(cost) in text
    # The holder posts the offer in this direction, not the asker.
    assert "posts the trade in game" in text


def test_the_proposal_dm_states_the_category_rule_and_never_gems():
    """A card-for-card proposal must not mention gems at all.

    This trade cannot cost gems; the real gem path is the separate Ask for
    help flow, which states payer and price before anything is sent. The
    earlier hypothetical price line made a plain swap read as a paid one.
    """
    trade = {
        "_id": "t1", "guild_id": 1,
        "wanted_card_id": "balloon",
        "given_card_id": "wizard",
        "requester_name": "Asker", "requester_tag": "#ME",
        "holder_name": "Holder", "holder_tag": "#H",
        "requester_clan_tag": "#A", "holder_clan_tag": "#A",
    }
    text = _view_text(cards_command._trade_proposal_dm(trade))

    assert "gem" not in text.lower()
    assert "Same-category trade" in text


def test_who_has_tells_you_what_to_do_when_you_cannot_ask():
    """It listed people and stopped, with no button and no explanation."""
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["clan_tag"] = "#MW"
    inventory["cards"]["balloon"] = cards.MISSING     # elixir, and no spares
    holder = _complete_inventory(tag="#H", clan_tag="#MW")
    holder["cards"]["balloon"] = cards.DUPLICATE
    holder["player_name"] = "Holder"
    holder["discord_id"] = 9

    view = cards_command._holders_view(
        account, "balloon",
        cards.holders_for_card(inventory, [holder], "balloon"),
    )
    text = _view_text(view)
    labels = [
        str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
    ]

    assert "Ask to swap" not in labels, "no spare means no swap is possible"
    assert "What to do now" in text
    assert "50 gems" in text
    # It must point at the button on this screen, not tell somebody to go and
    # write a message by hand - the approvals are meant to live in the app.
    assert "Tap **Ask for help**" in text
    assert "Message one of the players" not in text
    # It is still an ask, just not a swap - the bot sends it either way.
    ids = [
        str(n.get("custom_id")) for n in _view_nodes(view) if n.get("type") == 2
    ]
    assert any(i.startswith("cards_gem_ask:") for i in ids)


def test_the_what_to_do_heading_tells_the_truth_about_your_spares():
    """The heading said "You have no spare" even when the member held one
    that no listed holder needed. The wording now follows `can_request`,
    which is exactly "holds a same-category spare"."""
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["clan_tag"] = "#MW"
    inventory["cards"]["balloon"] = cards.MISSING
    holder = _complete_inventory(tag="#H", clan_tag="#MW")
    holder["cards"]["balloon"] = cards.DUPLICATE
    holder["player_name"] = "Holder"
    holder["discord_id"] = 9
    holders = cards.holders_for_card(inventory, [holder], "balloon")

    spareless = _view_text(cards_command._holders_view(
        account, "balloon", holders
    ))
    assert "You have no spare" in spareless
    assert "None of these players need" not in spareless

    with_spare = _view_text(cards_command._holders_view(
        account, "balloon", holders, can_request=True
    ))
    assert "None of these players need your spare" in with_spare
    assert "You have no spare" not in with_spare
    assert "cannot start this trade. They start it for you." in with_spare


def test_a_spare_everyone_owns_is_still_a_spare_you_can_offer():
    """Two Barbarians is a real card to trade, and it was ignored.

    holders_for_card only counted a duplicate when the holder was MISSING it.
    Everybody owns a Barbarian, so a genuine spare counted for nobody and the
    screen told the player to pay gems instead of offering the swap.
    """
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["clan_tag"] = "#MW"
    inventory["cards"]["meteor_golem"] = cards.MISSING
    inventory["cards"]["barbarian"] = cards.DUPLICATE      # the two barbarians
    holder = _complete_inventory(tag="#H", clan_tag="#MW")
    holder["cards"]["meteor_golem"] = cards.DUPLICATE
    holder["cards"]["barbarian"] = cards.OWNED             # they have one too
    holder["player_name"] = "Holder"
    holder["discord_id"] = 9

    found = cards.holders_for_card(inventory, [holder], "meteor_golem")
    assert found[0].returns == ("barbarian",)

    view = cards_command._holders_view(account, "meteor_golem", found)
    labels = [
        str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
    ]
    text = _view_text(view)

    assert "Ask to swap" in labels
    assert "Ask for help" not in labels
    assert "no spare to give" not in text
    assert "What to do now" not in text


def test_who_has_fits_discord_with_a_full_page_of_holders():
    """Every holder now carries a button, so the page had to be re-measured."""
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["clan_tag"] = "#MW"
    inventory["cards"]["meteor_golem"] = cards.MISSING
    holders = []
    for index in range(60):
        holder = _complete_inventory(tag=f"#H{index}", clan_tag="#MW")
        holder["cards"]["meteor_golem"] = cards.DUPLICATE
        holder["player_name"] = f"Holder {index}"
        holder["discord_id"] = 1000 + index
        holders.append(holder)

    found = cards.holders_for_card(inventory, holders, "meteor_golem")
    assert len(found) == 60, "the page must be capped, not the search"
    _assert_discord_payload(
        cards_command._holders_view(account, "meteor_golem", found)
    )


def test_the_ask_for_help_button_id_actually_parses(monkeypatch):
    """It shipped answering "Out of date" to every single click.

    The button was built with three parts but read with _parse_target, which
    only returns a second value when it is a CATEGORY id. No view test could
    see it: the button rendered perfectly and the handler rejected it.
    """
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["clan_tag"] = "#MW"
    inventory["cards"]["balloon"] = cards.MISSING
    holder = _complete_inventory(tag="#H", clan_tag="#MW")
    holder["cards"]["balloon"] = cards.DUPLICATE
    holder["player_name"] = "Holder"
    holder["discord_id"] = 9

    view = cards_command._holders_view(
        account, "balloon",
        cards.holders_for_card(inventory, [holder], "balloon"),
    )
    custom_id = next(
        str(n["custom_id"]) for n in _view_nodes(view)
        if str(n.get("custom_id", "")).startswith("cards_gem_ask:")
    )
    action_id = custom_id.split(":", 1)[1]

    # Read it back exactly as the handler does.
    parts = action_id.split("|")
    assert cards_command._normalize_tag(parts[0]) == "#ME"
    assert cards_command.CARD_BY_ID.get(parts[1]) is not None
    assert cards_command._normalize_tag(parts[2]) == "#H"


class _GemInventoryCollection:
    def __init__(self, documents):
        self.documents = {document["_id"]: document for document in documents}

    def find(self, query):
        return _FakeCursor([
            document
            for document in self.documents.values()
            if _matches_query(document, query)
        ])


class _GemClans:
    def __init__(self, tags=("#HOME",)):
        self.tags = list(tags)

    async def distinct(self, field):
        assert field == "tag"
        return list(self.tags)


def _gem_handler_env(monkeypatch):
    now = datetime.now(timezone.utc)
    account = Account(
        tag="#ME", name="Asker", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    requester = _complete_inventory(tag="#ME", confirmed_at=now)
    requester.update({"guild_id": 1, "discord_id": 123})
    requester["trusted_card_ids"] = [card.id for card in cards.CARDS]
    requester["cards"]["balloon"] = cards.MISSING

    holder = _complete_inventory(tag="#H", confirmed_at=now)
    holder.update({
        "guild_id": 1,
        "discord_id": 222,
        "player_name": "Holder",
    })
    holder["trusted_card_ids"] = [card.id for card in cards.CARDS]
    holder["cards"]["balloon"] = cards.DUPLICATE

    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, requester)
    )
    mongo = SimpleNamespace(
        card_inventories=_GemInventoryCollection([requester, holder]),
        card_trades=_FakeTradeCollection(),
        clans=_GemClans(),
    )
    return account, requester, holder, mongo


@pytest.mark.parametrize(
    "stale_state",
    [
        "requester_demand_untrusted",
        "requester_category_incomplete",
        "holder_supply_untrusted",
        "holder_category_incomplete",
        "requester_now_has_a_return",
        "requester_left_family",
        "holder_left_family",
    ],
)
def test_gem_confirmation_revalidates_normal_matching_eligibility(
    monkeypatch, stale_state
):
    """A rendered help button is not evidence that either raw count is safe."""
    _account, requester, holder, mongo = _gem_handler_env(monkeypatch)
    if stale_state == "requester_demand_untrusted":
        requester["trusted_card_ids"].remove("balloon")
        assert requester["cards"]["balloon"] == cards.MISSING
    elif stale_state == "requester_category_incomplete":
        requester["trusted_card_ids"].remove("barbarian")
    elif stale_state == "holder_supply_untrusted":
        holder["trusted_card_ids"].remove("balloon")
        assert holder["cards"]["balloon"] == cards.DUPLICATE
    elif stale_state == "holder_category_incomplete":
        holder["trusted_card_ids"].remove("barbarian")
    elif stale_state == "requester_now_has_a_return":
        requester["cards"]["wizard"] = cards.DUPLICATE
    elif stale_state == "requester_left_family":
        requester["clan_tag"] = "#OUTSIDE"
    elif stale_state == "holder_left_family":
        holder["clan_tag"] = "#OUTSIDE"

    result = asyncio.run(cards_command.cards_gem_ask(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))

    assert "no longer available" in _view_text(result)
    assert not any(
        str(node.get("custom_id", "")).startswith("cards_gem_send:")
        for node in _view_nodes(result)
    )


@pytest.mark.parametrize(
    "stale_state",
    [
        "requester_demand_untrusted", "holder_supply_untrusted",
        "requester_left_family", "holder_left_family",
    ],
)
def test_gem_send_revalidates_a_stale_confirmation_before_dm(
    monkeypatch, stale_state
):
    """Final send repeats trust and family checks after the price screen."""
    _account, requester, holder, mongo = _gem_handler_env(monkeypatch)

    async def no_delivery(*_args, **_kwargs):
        raise AssertionError("a refused send must deliver nothing")

    monkeypatch.setattr(cards_command, "_deliver_soon", no_delivery)
    confirmation = asyncio.run(cards_command.cards_gem_ask(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))
    send_id = next(
        str(node["custom_id"]).split(":", 1)[1]
        for node in _view_nodes(confirmation)
        if str(node.get("custom_id", "")).startswith("cards_gem_send:")
    )

    if stale_state == "requester_demand_untrusted":
        requester["trusted_card_ids"].remove("balloon")
    elif stale_state == "holder_supply_untrusted":
        holder["trusted_card_ids"].remove("balloon")
    elif stale_state == "requester_left_family":
        requester["clan_tag"] = "#OUTSIDE"
    elif stale_state == "holder_left_family":
        holder["clan_tag"] = "#OUTSIDE"

    dms = []

    async def fake_dm(_bot, recipient_id, _components, **_kwargs):
        dms.append(recipient_id)
        return True

    monkeypatch.setattr(cards_command, "_send_trade_dm", fake_dm)
    result = asyncio.run(cards_command.cards_gem_send(
        _quantity_ctx(), send_id,
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    assert "no longer available" in _view_text(result)
    assert dms == []
    assert mongo.card_trades.docs == {}


def test_gem_send_uses_live_eligibility_and_replayed_stale_button_fails_closed(
    monkeypatch,
):
    _account, _requester, holder, mongo = _gem_handler_env(monkeypatch)
    delivered = []

    async def deliver_soon(_bot, _mongo, document, *, event, **_kwargs):
        delivered.append((document["_id"], event))
        return cards_command._Delivery(channel_message_id=777, pinged=(222,))

    monkeypatch.setattr(cards_command, "_deliver_soon", deliver_soon)
    first = asyncio.run(cards_command.cards_gem_send(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))
    text = _view_text(first)
    assert "Asked" in text
    assert "pinged **Holder**" in text, "feedback states the real delivery"
    assert delivered == [("gem:#ME:#H:balloon", "gem_ask_posted")]
    assert set(mongo.card_trades.docs) == {"gem:#ME:#H:balloon"}

    # The same indefinitely clickable button must not send again once the
    # holder's value is no longer trusted, even though the raw 2 is preserved.
    holder["trusted_card_ids"].remove("balloon")
    replay = asyncio.run(cards_command.cards_gem_send(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))
    assert "no longer available" in _view_text(replay)
    assert delivered == [("gem:#ME:#H:balloon", "gem_ask_posted")]


def test_gem_send_deletes_the_ask_only_on_total_delivery_failure(monkeypatch):
    """The old branch deleted on ANY DM failure; the honest version deletes
    only when the channel post AND the fallback DM both failed - a DM
    failure alone no longer unwinds an ask the channel already carries."""
    _account, _requester, _holder, mongo = _gem_handler_env(monkeypatch)

    async def total_failure(_bot, _mongo, _document, *, event, **_kwargs):
        assert event == "gem_ask_posted"
        return cards_command._Delivery(
            channel_message_id=None, dm_failed=(222,)
        )

    monkeypatch.setattr(cards_command, "_deliver_soon", total_failure)
    result = asyncio.run(cards_command.cards_gem_send(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    text = _view_text(result)
    assert "nothing was asked" in text, "the notice is honest"
    assert mongo.card_trades.docs == {}, "no orphaned ask survives"


def test_gem_send_keeps_the_ask_when_only_the_post_failed(monkeypatch):
    """Channel post failed but the fallback DM landed: the ask is alive."""
    _account, _requester, _holder, mongo = _gem_handler_env(monkeypatch)

    async def dm_fallback(_bot, _mongo, _document, *, event, **_kwargs):
        return cards_command._Delivery(
            channel_message_id=None, dm_sent=(222,)
        )

    monkeypatch.setattr(cards_command, "_deliver_soon", dm_fallback)
    result = asyncio.run(cards_command.cards_gem_send(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    text = _view_text(result)
    assert "Asked" in text
    assert "DM instead" in text
    assert set(mongo.card_trades.docs) == {"gem:#ME:#H:balloon"}


def test_gem_send_timeout_keeps_the_ask_and_does_not_claim_success(monkeypatch):
    """None from _deliver_soon means still in flight - the post still lands,
    so the ask is kept and the feedback says posting, not posted."""
    _account, _requester, _holder, mongo = _gem_handler_env(monkeypatch)

    async def timed_out(*_args, **_kwargs):
        return None

    monkeypatch.setattr(cards_command, "_deliver_soon", timed_out)
    result = asyncio.run(cards_command.cards_gem_send(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    text = _view_text(result)
    assert "I am posting the ask" in text
    assert "pinged" not in text, "no success claim without a delivery result"
    assert set(mongo.card_trades.docs) == {"gem:#ME:#H:balloon"}


def test_gem_send_reaps_a_total_failure_that_outlives_the_patience_window(monkeypatch):
    """The audit's orphan window: a delivery that fails BOTH surfaces after
    the 3-second patience ran out used to leave the ask pending forever -
    delivered nowhere, yet blocking every repeat ask for that pair and card.
    The reaper rides inside the delivery task, so it tracks the real outcome
    rather than the caller's view of it."""
    _account, _requester, _holder, mongo = _gem_handler_env(monkeypatch)

    release = asyncio.Event()

    async def slow_total_failure(_bot, _mongo, _document, *, event, **_kwargs):
        await release.wait()
        return cards_command._Delivery(
            channel_message_id=None, dm_failed=(222,)
        )

    monkeypatch.setattr(cards_command, "_deliver", slow_total_failure)

    async def scenario():
        # Zero patience stands in for a delivery that outlives the window.
        real = cards_command._deliver_soon

        async def impatient(*args, **kwargs):
            kwargs.setdefault("timeout", 0)
            return await real(*args, **kwargs)

        monkeypatch.setattr(cards_command, "_deliver_soon", impatient)
        result = await cards_command.cards_gem_send(
            _quantity_ctx(), "#ME|balloon|#H",
            coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
        )
        assert "I am posting the ask" in _view_text(result), (
            "the member is answered before the outcome is known"
        )
        assert set(mongo.card_trades.docs) == {"gem:#ME:#H:balloon"}, (
            "the ask is still alive while delivery is in flight"
        )
        release.set()
        await asyncio.gather(*cards_command._DELIVERY_TASKS)
        assert mongo.card_trades.docs == {}, (
            "the late total failure still deletes the undelivered ask"
        )

    asyncio.run(scenario())


def test_gem_takeover_clears_the_previous_asks_channel_post_ids(monkeypatch):
    """A re-ask must not inherit its answered predecessor's channel post.

    Left in place, those ids meant that if the NEW ask's post failed, the
    eventual answer's edit would rewrite the OLD terminal post - publicly
    flipping an already-answered ask to a different, later answer."""
    _account, _requester, _holder, mongo = _gem_handler_env(monkeypatch)
    mongo.card_trades.docs["gem:#ME:#H:balloon"] = {
        "_id": "gem:#ME:#H:balloon",
        "kind": "gem_ask",
        "status": "declined",
        "channel_id": 999,
        "channel_message_id": 424242,
        "channel_post_v2": True,
    }

    async def posted(_bot, _mongo, _document, *, event, **_kwargs):
        return cards_command._Delivery(channel_message_id=555)

    monkeypatch.setattr(cards_command, "_deliver_soon", posted)
    asyncio.run(cards_command.cards_gem_send(
        _quantity_ctx(), "#ME|balloon|#H",
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    taken_over = mongo.card_trades.docs["gem:#ME:#H:balloon"]
    assert taken_over["status"] == "pending", "the takeover happened"
    for stale in ("channel_id", "channel_message_id", "channel_post_v2"):
        assert stale not in taken_over, (
            f"{stale} must not survive onto the fresh ask"
        )


def test_the_gem_ask_states_the_price_before_anything_is_sent():
    """Gems are real money, so the number comes before the commit."""
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    view = cards_command._gem_ask_confirm_view(
        account, cards.CARD_BY_ID["balloon"], "Holder", "#H",
    )
    text = _view_text(view)

    assert "50 gems" in text
    assert "They post the trade in game." in text
    assert "Nothing is reserved" in text
    # A price without the gem mark reads as points or coins to somebody
    # skimming in a second language.
    assert str(cards_command.emojis.gems) in text
    _assert_discord_payload(view)


def test_every_screen_that_names_a_price_shows_the_gem_mark():
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["clan_tag"] = "#MW"
    inventory["cards"]["balloon"] = cards.MISSING
    holder = _complete_inventory(tag="#H", clan_tag="#MW")
    holder["cards"]["balloon"] = cards.DUPLICATE
    holder["player_name"] = "Holder"
    holder["discord_id"] = 9

    # The proposal DM is deliberately absent here: a card-for-card proposal
    # names no price any more, so there is no price to mark.
    screens = [
        cards_command._holders_view(
            account, "balloon",
            cards.holders_for_card(inventory, [holder], "balloon"),
        ),
        cards_command._gem_ask_dm({
            "_id": "gem:#ME:#H:balloon", "card_id": "balloon",
            "gem_cost": 50, "asker_name": "A", "holder_name": "H",
        }),
    ]
    for view in screens:
        text = _view_text(view)
        assert "gems" in text
        assert str(cards_command.emojis.gems) in text


def test_the_gem_ask_dm_tells_the_holder_they_post_it():
    """The holder has to act in game; the DM has to say so plainly."""
    ask = {
        "_id": "gem:#ME:#H:balloon", "card_id": "balloon", "gem_cost": 50,
        "asker_name": "Sir Ruggie", "holder_name": "Holder",
    }
    text = _view_text(cards_command._gem_ask_dm(ask))

    assert "spare to give back" in text
    assert "50 gems" in text
    assert "**If you say yes**" in text
    assert "Post the trade in game." in text
    # It is not a trade record, so nothing may claim to be held.
    assert "reserved" not in text.lower().replace(
        "nothing is reserved", ""
    )


def test_the_gem_prices_match_the_event():
    """Wrong numbers here cost somebody real money, so they are pinned."""
    assert cards.TRADE_GEM_COST == {
        "elixir": 50,
        "dark_elixir": 70,
        "builder_base": 90,
        "super_troop": 110,
    }
    # Every category has a price, or a screen would quote a blank one.
    assert set(cards.TRADE_GEM_COST) == {c.id for c in cards.CATEGORIES}


def test_a_card_they_already_own_is_still_a_legal_offer():
    """The rule that hid most trades: they never had to be missing it."""
    requester = _complete_inventory()
    requester["cards"]["root_rider"] = cards.MISSING
    requester["cards"]["wizard"] = cards.DUPLICATE
    holder = _complete_inventory(tag="#H")
    holder["cards"]["root_rider"] = cards.DUPLICATE
    holder["cards"]["wizard"] = cards.OWNED      # they already have one

    assert cards.reciprocal_trade_error(
        requester, holder, "root_rider", "wizard"
    ) is None


def test_the_same_category_rule_is_still_absolute():
    """Elixir for elixir, dark for dark. Nothing relaxed this."""
    requester = _complete_inventory()
    requester["cards"]["root_rider"] = cards.MISSING      # elixir
    requester["cards"]["ice_hound"] = cards.DUPLICATE     # dark elixir
    holder = _complete_inventory(tag="#H")
    holder["cards"]["root_rider"] = cards.DUPLICATE

    assert cards.reciprocal_trade_error(
        requester, holder, "root_rider", "ice_hound"
    ) == "Both cards must belong to the same category."


def test_holders_in_your_clan_are_listed_first():
    """Same-clan holders can trade now; everyone else must move an account."""
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["clan_tag"] = "#MW"
    inventory["cards"]["balloon"] = cards.MISSING
    inventory["cards"]["electro_dragon"] = cards.DUPLICATE

    def holder(tag, name, clan_tag, clan_name):
        return {
            "_id": tag, "player_name": name, "discord_id": abs(hash(tag)) % 9999,
            "clan_tag": clan_tag, "clan_name": clan_name,
            "cards": dict(
                {card.id: cards.OWNED for card in cards.CARDS},
                balloon=cards.DUPLICATE, electro_dragon=cards.MISSING,
            ),
            "complete_categories": [c.id for c in cards.CATEGORIES],
            "confirmed_at": datetime.now(timezone.utc),
        }

    holders = cards.holders_for_card(inventory, [
        holder("#A", "Faraway", "#CT", "ClashofThrones"),
        holder("#B", "Neighbour", "#MW", "Morning Woods"),
        holder("#C", "AlsoFar", "#CT", "ClashofThrones"),
    ], "balloon")
    assert any(m.same_clan for m in holders), "fixture produced no same-clan match"

    view = cards_command._holders_view(account, "balloon", holders)
    text = _view_text(view)

    assert text.index("Neighbour") < text.index("Faraway")
    assert "are in your clan and can trade right away" in text
    # The give/get pair is stated once, not repeated under every holder.
    assert text.count("**You get:**") == 1
    _assert_discord_payload(view)


def test_my_trades_exact_move_needed_state_exposes_canonical_sent_action(monkeypatch):
    """The live different-clan, reserved swap must be finishable here."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trade = _trade_document()
    trade.update({
        "kind": "trade",
        "status": "move_needed",
        "wanted_card_id": "healer",
        "given_card_id": "archer",
        "requester_name": "Member",
        "holder_name": "Other account",
        # A member may legitimately trade between two of their linked accounts.
        "requester_discord_id": 111,
        "holder_discord_id": 111,
        "requester_clan_tag": "#WU",
        "requester_clan_name": "Warriors United",
        "holder_clan_tag": "#WW",
        "holder_clan_name": "WONDER WALL",
        "reservation_token": "exact-card-reservation",
        "reservation_until": datetime.now(timezone.utc) + timedelta(days=7),
    })

    async def load_target(*_args, **_kwargs):
        return account, _complete_inventory(), None

    async def active_trades(_mongo, *, tag, guild_id, bot):
        assert tag == "#ME" and guild_id == 1
        return [trade]

    async def no_open_requests(_mongo, *, tag, guild_id):
        assert tag == "#ME" and guild_id == 1
        return []

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_active_trades", active_trades)
    monkeypatch.setattr(cards_command, "_open_requests_for", no_open_requests)
    view = asyncio.run(cards_command.cards_trades(
        _quantity_ctx(user_id=111),
        "#ME",
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
        bot=SimpleNamespace(),
    ))
    controls = {
        str(node.get("label")): str(node.get("custom_id"))
        for node in _view_nodes(view) if node.get("type") == 2
    }
    text = _view_text(view)

    assert "Accepted · move needed" in text
    assert "Warriors United" in text and "WONDER WALL" in text
    assert "Exact cards are reserved" in text
    assert controls["I sent my card"] == "cards_swap_sent:trade-a|requester"
    assert "Cancel" in controls
    assert "Check clans" not in controls
    assert "Trade completed" not in controls


@pytest.mark.parametrize("status", ["ready", "accepted"])
def test_my_trades_same_clan_live_swap_exposes_the_same_action(status):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trade = _trade_document()
    trade.update({
        "status": status,
        "requester_discord_id": 111,
        "holder_discord_id": 222,
        "requester_clan_tag": "#HOME",
        "holder_clan_tag": "#HOME",
        "reservation_token": "exact-card-reservation",
    })

    ids = {
        str(node.get("custom_id")) for node in _view_nodes(
            cards_command._trades_view(account, [trade])
        )
    }

    assert "cards_swap_sent:trade-a|requester" in ids


def test_my_trades_confirmed_side_waits_while_other_side_is_pending():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trade = _trade_document()
    trade.update({
        "status": "move_needed",
        "requester_discord_id": 111,
        "holder_discord_id": 222,
        "requester_name": "Member",
        "holder_name": "Other player",
        "requester_clan_tag": "#HOME",
        "requester_clan_name": "Warriors United",
        "holder_clan_tag": "#AWAY",
        "holder_clan_name": "WONDER WALL",
        "requester_confirmed_at": datetime.now(timezone.utc),
    })
    view = cards_command._trades_view(account, [trade])
    labels = [
        str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
    ]

    assert "I sent my card" not in labels
    assert "Cancel" in labels
    assert "already marked your card sent" in _view_text(view)
    assert "Waiting for **Other player**" in _view_text(view)


def test_my_trades_other_confirmation_does_not_hide_my_pending_action():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trade = _trade_document()
    trade.update({
        "status": "move_needed",
        "requester_discord_id": 111,
        "holder_discord_id": 222,
        "holder_confirmed_at": datetime.now(timezone.utc),
    })

    ids = {
        str(node.get("custom_id")) for node in _view_nodes(
            cards_command._trades_view(account, [trade])
        )
    }

    assert "cards_swap_sent:trade-a|requester" in ids


@pytest.mark.parametrize(
    "status",
    ["completed", "completing", "needs_review", "cancelled", "expired", "abandoned"],
)
def test_my_trades_never_exposes_confirmation_for_non_live_states(status):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trade = _trade_document()
    trade.update({
        "status": status,
        "requester_discord_id": 111,
        "holder_discord_id": 222,
    })
    if status == "completed":
        confirmed = datetime.now(timezone.utc)
        trade.update({
            "requester_confirmed_at": confirmed,
            "holder_confirmed_at": confirmed,
        })

    ids = {
        str(node.get("custom_id")) for node in _view_nodes(
            cards_command._trades_view(account, [trade])
        )
    }

    assert not any(custom_id.startswith("cards_swap_sent:") for custom_id in ids)


def test_same_owner_my_trades_click_records_only_the_selected_account_leg(monkeypatch):
    """The old Discord-only resolver made this holder click hit requester."""
    trade = _agreed_trade()
    trade.update({
        "status": "move_needed",
        "requester_discord_id": 111,
        "holder_discord_id": 111,
    })

    class Trades:
        async def find_one(self, _query):
            return dict(trade)

    loaded_tags = []
    recorded_roles = []

    async def load_target(_ctx, tag, **_kwargs):
        loaded_tags.append(tag)
        return (
            Account(
                tag=tag, name="Member", clan_tag="#HOME",
                clan_name="Home Clan", town_hall=18,
            ),
            _complete_inventory(tag=tag),
            None,
        )

    async def record(_mongo, current, *, role, now, **_kwargs):
        recorded_roles.append(role)
        updated = dict(current)
        updated[f"{role}_confirmed_at"] = now
        trade.update(updated)
        return "moved", 1, updated

    async def notify(*_args, **_kwargs):
        return True

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_run_swap_leg_confirmation", record)
    monkeypatch.setattr(cards_command, "_notify_trade_status", notify)
    mongo = SimpleNamespace(card_trades=Trades())

    holder_account = Account(
        tag="#HOLDER", name="Holder", clan_tag="#AWAY",
        clan_name="Away Clan", town_hall=18,
    )
    holder_view = cards_command._trades_view(holder_account, [trade])
    holder_sent_id = next(
        str(node["custom_id"]) for node in _view_nodes(holder_view)
        if node.get("label") == "I sent my card"
    )
    assert holder_sent_id == "cards_swap_sent:trade-a|holder"

    panel_ids = {
        str(node.get("custom_id")) for node in _view_nodes(
            cards_command._swap_confirm_view(trade, role="holder")
        )
    }
    assert "cards_swap_sent:trade-a|holder" in panel_ids

    asyncio.run(cards_command.cards_swap_sent(
        _quantity_ctx(user_id=111),
        holder_sent_id.partition(":")[2],
        coc_client=SimpleNamespace(),
        mongo=mongo,
        bot=SimpleNamespace(),
    ))

    assert loaded_tags == ["#HOLDER"]
    assert recorded_roles == ["holder"]
    assert "holder_confirmed_at" in trade
    assert "requester_confirmed_at" not in trade

    requester_account = Account(
        tag="#ME", name="Requester", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    requester_ids = {
        str(node.get("custom_id")) for node in _view_nodes(
            cards_command._trades_view(requester_account, [trade])
        )
    }
    assert "cards_swap_sent:trade-a|requester" in requester_ids

    holder_after = cards_command._trades_view(holder_account, [trade])
    assert not any(
        str(node.get("custom_id", "")).startswith("cards_swap_sent:")
        for node in _view_nodes(holder_after)
    )
    assert "already marked your card sent" in _view_text(holder_after)


def test_confirmation_role_hint_cannot_claim_the_other_participant(monkeypatch):
    trade = _agreed_trade()

    class Trades:
        async def find_one(self, _query):
            return dict(trade)

    async def explode(*_args, **_kwargs):
        raise AssertionError("an unauthorized role must stop before account loading")

    monkeypatch.setattr(cards_command, "_load_target", explode)
    loaded, problem = asyncio.run(cards_command._load_swap_for_confirm(
        _quantity_ctx(user_id=111),
        f"{trade['_id']}|holder",
        mongo=SimpleNamespace(card_trades=Trades()),
    ))

    assert loaded is None
    assert "not yours" in _view_text(problem)


def test_legacy_same_owner_confirmation_control_fails_cleanly():
    """An old role-less control must not guess which linked account sent."""
    trade = _agreed_trade()
    trade.update({
        "requester_discord_id": 111,
        "holder_discord_id": 111,
    })

    class Trades:
        async def find_one(self, _query):
            return dict(trade)

    loaded, problem = asyncio.run(cards_command._load_swap_for_confirm(
        _quantity_ctx(user_id=111),
        trade["_id"],
        mongo=SimpleNamespace(card_trades=Trades()),
    ))

    assert loaded is None
    assert "Reopen **My trades**" in _view_text(problem)


def test_the_clan_check_is_gone_entirely():
    assert not hasattr(cards_command, "cards_trade_ready")


# ---- Looking a player up by name ----------------------------------------


def _spare_inventory(tag, *, discord_id, name, clan_tag="#HOME", spares=()):
    inventory = _complete_inventory(tag=tag, clan_tag=clan_tag)
    inventory["discord_id"] = discord_id
    inventory["player_name"] = name
    for card_id in spares:
        inventory["cards"][card_id] = cards.DUPLICATE
    return inventory


def _picker_options(rows):
    return [
        option
        for node in _walk_payload([row.build() for row in rows])
        for option in (node.get("options") or ())
    ]


class _BrowseInventories:
    def __init__(self, documents):
        self.documents = list(documents)
        self.query = None

    def find(self, query):
        self.query = query
        allowed_clans = set(query.get("clan_tag", {}).get("$in", ()))
        rows = []
        for document in self.documents:
            if int(document.get("guild_id") or 0) != int(query["guild_id"]):
                continue
            if document.get("trading_paused") is True:
                continue
            if allowed_clans and document.get("clan_tag") not in allowed_clans:
                continue
            if "discord_id" in query and document.get("discord_id") != query["discord_id"]:
                continue
            if "_id" in query and document.get("_id") != query["_id"]:
                continue
            rows.append(document)
        return _FakeCursor(rows)


class _BrowseClans:
    async def distinct(self, field):
        assert field == "tag"
        return ["#HOME"]


def _run_player_lookup(monkeypatch, documents, picked, *, viewer=None):
    account = Account(
        tag="#ME", name="Viewer", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    viewer = viewer or _complete_inventory()
    viewer.update({
        "guild_id": 1,
        "discord_id": 77,
    })
    viewer.setdefault("trusted_card_ids", [card.id for card in cards.CARDS])
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, viewer),
    )
    inventories = _BrowseInventories(documents)
    mongo = SimpleNamespace(
        clans=_BrowseClans(), card_inventories=inventories,
    )
    result = asyncio.run(cards_command.cards_browse(
        _quantity_ctx(user_id=77, values=[picked]),
        "#ME",
        coc_client=SimpleNamespace(),
        mongo=mongo,
        bot=SimpleNamespace(cache=SimpleNamespace(
            get_member=lambda _guild_id, _user_id: SimpleNamespace(
                display_name="Viewer",
            ),
        )),
    ))
    return result, inventories


def test_real_player_lookup_handles_the_invokers_seven_linked_accounts(monkeypatch):
    """The live d:<self> choice must fit both Discord message budgets."""
    trusted = [card.id for card in cards.CARDS]
    documents = []
    for index in range(7):
        document = _spare_inventory(
            "#ME" if index == 0 else f"#ALT{index}",
            discord_id=77,
            name=f"Own account {index}",
        )
        document.update({
            "guild_id": 1,
            "trusted_card_ids": trusted,
            "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
        })
        documents.append(document)

    picker = cards_command._browse_picker(
        "#ME", documents[1:], names={77: "Viewer"}, clan_tag="#HOME",
    )
    option = _picker_options(picker)[0]
    assert option["value"] == "d:77"

    view, inventories = _run_player_lookup(
        monkeypatch, documents, option["value"], viewer=documents[0],
    )

    text = _view_text(view)
    assert "Own account 0" in text
    assert "Own account 1" not in text
    payload = [component.build() for component in view]
    nodes = list(_walk_payload(payload))
    selects = [
        node for node in nodes
        if int(node.get("type", -1)) == int(hikari.ComponentType.TEXT_SELECT_MENU)
    ]
    assert len(selects) == 1
    assert selects[0]["custom_id"] == "cards_browse:#ME"
    account_options = selects[0]["options"]
    assert [entry["value"] for entry in account_options] == [
        "d:77|a:#ME",
        *(f"d:77|a:#ALT{index}" for index in range(1, 7)),
    ]
    assert all(
        f"Own account {index}" in account_options[index]["label"]
        for index in range(7)
    )
    assert inventories.query == {
        "guild_id": 1,
        "trading_paused": {"$ne": True},
        "discord_id": 77,
        "clan_tag": {"$in": ["#HOME"]},
    }
    _assert_discord_payload(view)

    # Every linked account remains losslessly reachable through the same
    # canonical cards_browse custom ID. No account body is silently clipped.
    for index, entry in enumerate(account_options):
        focused, _ = _run_player_lookup(
            monkeypatch, documents, entry["value"], viewer=documents[0],
        )
        focused_text = _view_text(focused)
        assert f"Own account {index}" in focused_text
        assert all(card.name in focused_text for card in cards.CARDS)
        assert all(
            f"Own account {other}" not in focused_text
            for other in range(7)
            if other != index
        )
        _assert_discord_payload(focused)


def test_real_player_lookup_handles_one_self_linked_account(monkeypatch):
    document = _spare_inventory(
        "#ME", discord_id=77, name="Only own account", spares=["wizard"],
    )
    document.update({
        "guild_id": 1,
        "trusted_card_ids": [card.id for card in cards.CARDS],
    })

    view, inventories = _run_player_lookup(
        monkeypatch, [document], "d:77", viewer=document,
    )

    assert "Only own account" in _view_text(view)
    assert "Wizard" in _view_text(view)
    assert inventories.query["discord_id"] == 77
    assert not _picker_options(view)
    _assert_discord_payload(view)


def test_real_player_lookup_handles_another_users_multiple_accounts(monkeypatch):
    documents = [
        _spare_inventory(
            "#OTHER1", discord_id=88, name="Other main", spares=["wizard"],
        ),
        _spare_inventory(
            "#OTHER2", discord_id=88, name="Other alt", spares=["minion"],
        ),
    ]
    for document in documents:
        document.update({
            "guild_id": 1,
            "trusted_card_ids": [card.id for card in cards.CARDS],
        })

    view, inventories = _run_player_lookup(monkeypatch, documents, "d:88")

    text = _view_text(view)
    assert "Other main" in text
    assert "Other alt" in text
    assert "Wizard" in text
    assert "Minion" in text
    assert inventories.query["discord_id"] == 88
    _assert_discord_payload(view)


def test_self_lookup_focus_keeps_target_and_viewer_trust_separate(monkeypatch):
    viewer = _spare_inventory("#ME", discord_id=77, name="Viewer")
    viewer.update({
        "guild_id": 1,
        "trusted_card_ids": [
            card.id for card in cards.CARDS if card.id != "night_witch"
        ],
    })
    viewer["cards"].update({
        "night_witch": cards.MISSING,
        "minion": cards.MISSING,
    })

    alt = _spare_inventory("#ALT", discord_id=77, name="Own alt")
    alt.update({
        "guild_id": 1,
        "trusted_card_ids": [
            card.id for card in cards.CARDS if card.id != "wizard"
        ],
    })
    alt["cards"].update({
        "wizard": cards.DUPLICATE,
        "night_witch": cards.DUPLICATE,
        "minion": cards.DUPLICATE,
    })

    view, _inventories = _run_player_lookup(
        monkeypatch, [viewer, alt], "d:77|a:#ALT", viewer=viewer,
    )

    text = _view_text(view)
    assert "Own alt" in text
    assert "Wizard" not in text  # untrusted raw target supply is neutralized
    night_witch_line = next(
        line for line in text.splitlines() if "Night Witch" in line
    )
    minion_line = next(line for line in text.splitlines() if "Minion" in line)
    assert "you need this" not in night_witch_line  # untrusted viewer 0 is neutralized
    assert "you need this" in minion_line      # trusted viewer need remains canonical
    _assert_discord_payload(view)


def test_self_lookup_full_needed_account_stays_within_total_text_budget(monkeypatch):
    trusted = [card.id for card in cards.CARDS]
    viewer = _spare_inventory("#ME", discord_id=77, name="Viewer")
    viewer.update({
        "guild_id": 1,
        "trusted_card_ids": trusted,
        "cards": {card.id: cards.MISSING for card in cards.CARDS},
    })
    alt = _spare_inventory("#ALT", discord_id=77, name="Own full alt")
    alt.update({
        "guild_id": 1,
        "trusted_card_ids": trusted,
        "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
    })

    view, _inventories = _run_player_lookup(
        monkeypatch, [viewer, alt], "d:77|a:#ALT", viewer=viewer,
    )

    text = _view_text(view)
    assert all(card.name in text for card in cards.CARDS)
    assert text.count("you need this") == len(cards.CARDS)
    _assert_discord_payload(view)


def test_real_player_lookup_stale_focused_account_fails_cleanly(monkeypatch):
    document = _spare_inventory(
        "#ME", discord_id=77, name="Viewer", spares=["wizard"],
    )
    document.update({
        "guild_id": 1,
        "trusted_card_ids": [card.id for card in cards.CARDS],
    })

    view, _inventories = _run_player_lookup(
        monkeypatch, [document], "d:77|a:#GONE", viewer=document,
    )

    assert "Nothing to show" in _view_text(view)
    _assert_discord_payload(view)


def test_real_player_lookup_shows_other_player_but_sanitizes_untrusted_spares(
    monkeypatch,
):
    document = _spare_inventory(
        "#OTHER", discord_id=88, name="Other player",
        spares=["wizard", "minion"],
    )
    document.update({
        "guild_id": 1,
        # A stale Ready category cannot make its untrusted raw duplicate
        # visible. Dark Elixir remains fully trusted and displayable.
        "trusted_card_ids": [
            card.id for card in cards.CARDS if card.id != "wizard"
        ],
    })

    view, inventories = _run_player_lookup(
        monkeypatch, [document], "d:88",
    )

    text = _view_text(view)
    assert "Other player" in text
    assert "Minion" in text
    assert "Wizard" not in text
    assert inventories.query["discord_id"] == 88
    _assert_discord_payload(view)


def test_real_player_lookup_keeps_legacy_tag_values_compatible(monkeypatch):
    document = _spare_inventory(
        "#LEGACY", discord_id=None, name="Legacy player", spares=["minion"],
    )
    document.update({
        "guild_id": 1,
        "trusted_card_ids": [card.id for card in cards.CARDS],
    })

    view, inventories = _run_player_lookup(
        monkeypatch, [document], "t:#LEGACY",
    )

    assert "Legacy player" in _view_text(view)
    assert "Minion" in _view_text(view)
    assert inventories.query["_id"] == "#LEGACY"
    _assert_discord_payload(view)


@pytest.mark.parametrize(
    ("picked", "message"),
    [
        ("d:not-a-number", "Unknown player"),
        ("d:0", "Unknown player"),
        ("d:-1", "Unknown player"),
        ("d:77|bad-focus", "Unknown player"),
        ("d:77|a:", "Unknown player"),
        ("d:999", "Nothing to show"),
        ("t:#GONE", "Nothing to show"),
    ],
)
def test_real_player_lookup_stale_values_fail_cleanly(
    monkeypatch, picked, message,
):
    view, _inventories = _run_player_lookup(monkeypatch, [], picked)

    assert message in _view_text(view)
    _assert_discord_payload(view)


def test_browse_picker_hides_players_who_turned_trading_off():
    """Browsing somebody who opted out would route requests straight at them."""
    here = _spare_inventory("#A", discord_id=1, name="Stays", spares=["wizard"])
    gone = _spare_inventory("#B", discord_id=2, name="Opted Out")
    gone["trading_paused"] = True

    options = _picker_options(
        cards_command._browse_picker("#ME", [here, gone], names={}, clan_tag=None)
    )

    assert [option["label"] for option in options] == ["Stays"]


def test_browse_picker_puts_clanmates_first():
    """Past 25 people the cap decides who survives, so relevance sorts first."""
    away = _spare_inventory("#A", discord_id=1, name="Aaa", clan_tag="#OTHER")
    home = _spare_inventory("#B", discord_id=2, name="Zzz", clan_tag="#HOME")

    options = _picker_options(
        cards_command._browse_picker(
            "#ME", [away, home], names={}, clan_tag="#HOME"
        )
    )

    assert [option["label"] for option in options] == ["Zzz", "Aaa"]


def test_browse_picker_gives_one_person_one_row():
    """Two accounts are still one human being, and you look up the human."""
    main = _spare_inventory("#A", discord_id=7, name="Main", spares=["wizard"])
    alt = _spare_inventory("#B", discord_id=7, name="Alt", spares=["archer"])

    options = _picker_options(
        cards_command._browse_picker("#ME", [main, alt], names={}, clan_tag=None)
    )

    assert len(options) == 1
    assert "2 accounts" in options[0]["description"]
    # Summed across both, because the count only decides whether the lookup is
    # worth making.
    assert options[0]["description"].startswith("2 spares")


def test_browse_picker_leads_with_the_discord_name():
    """People are known by their handle in chat, not by their in-game name."""
    document = _spare_inventory("#A", discord_id=9, name="SomeCoCName")

    options = _picker_options(
        cards_command._browse_picker(
            "#ME", [document], names={9: "PoppaSlayer"}, clan_tag=None
        )
    )

    assert options[0]["label"] == "PoppaSlayer · SomeCoCName"
    assert options[0]["value"] == "d:9"


def test_browse_picker_falls_back_when_the_member_cache_misses():
    document = _spare_inventory("#A", discord_id=9, name="SomeCoCName")

    options = _picker_options(
        cards_command._browse_picker("#ME", [document], names={}, clan_tag=None)
    )

    assert options[0]["label"] == "SomeCoCName"


def test_browse_picker_keeps_people_with_no_spares_listed():
    """A missing name reads as a bug; a zero answers itself."""
    document = _spare_inventory("#A", discord_id=9, name="Empty")

    options = _picker_options(
        cards_command._browse_picker("#ME", [document], names={}, clan_tag=None)
    )

    assert options[0]["description"].startswith("0 spares")


def test_player_spares_view_never_merges_their_accounts():
    """You trade with one account in one clan; a merged list would misdirect."""
    main = _spare_inventory("#A", discord_id=7, name="Main", spares=["wizard"])
    main["clan_name"] = "Home Clan"
    alt = _spare_inventory("#B", discord_id=7, name="Alt", spares=["archer"])
    alt["clan_name"] = "Far Clan"

    text = _view_text(cards_command._player_spares_view(
        "#ME", _complete_inventory(), [main, alt], display_name="Poppa",
    ))

    assert "Main" in text and "Home Clan" in text
    assert "Alt" in text and "Far Clan" in text


def test_player_spares_view_marks_the_ones_you_need():
    mine = _complete_inventory()
    mine["cards"]["wizard"] = cards.MISSING
    theirs = _spare_inventory(
        "#A", discord_id=7, name="Them", spares=["wizard", "archer"]
    )

    text = _view_text(cards_command._player_spares_view(
        "#ME", mine, [theirs], display_name="Them",
    ))

    wanted = [line for line in text.split("\n") if "you need this" in line]
    assert len(wanted) == 1
    assert "Wizard" in wanted[0]


def test_player_spares_view_says_so_when_they_have_nothing():
    theirs = _spare_inventory("#A", discord_id=7, name="Them")

    text = _view_text(cards_command._player_spares_view(
        "#ME", _complete_inventory(), [theirs], display_name="Them",
    ))

    assert "no duplicates to give" in text


def test_find_trades_only_says_pick_a_card_when_there_is_a_card_menu():
    """With no even swaps the only menu on screen was the player lookup."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["root_rider"] = cards.MISSING

    # A holder with the card and nothing of ours worth taking: one-way only.
    holder = _complete_inventory(tag="#H")
    holder["cards"]["root_rider"] = cards.DUPLICATE
    oneway = cards.find_matches(inventory, [holder])
    text = _view_text(cards_command._matches_view(account, inventory, oneway))

    assert "Pick a card from the menu below" not in text
    assert "No even swaps right now" in text

    # And the card menu still leads when an even swap does exist.
    inventory["cards"]["wizard"] = cards.DUPLICATE
    holder["cards"]["wizard"] = cards.MISSING
    mutual = cards.find_matches(inventory, [holder])
    mutual_text = _view_text(
        cards_command._matches_view(account, inventory, mutual)
    )

    assert "Pick a card from the menu below" in mutual_text
    assert "Even swaps" in mutual_text


def test_find_trades_still_fits_discord_with_the_lookup_menu():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    for card_id in ("root_rider", "druid", "cannon_cart"):
        inventory["cards"][card_id] = cards.MISSING
    inventory["cards"]["wizard"] = cards.DUPLICATE
    holders = _many_holders(inventory, 40, ["root_rider", "druid", "cannon_cart"])
    browse = cards_command._browse_picker(
        "#ME", holders, names={}, clan_tag="#HOME"
    )

    assert browse, "40 holders should produce a lookup menu"
    _assert_discord_payload(cards_command._matches_view(
        account, inventory, cards.find_matches(inventory, holders), browse=browse,
    ))


# ---- Admin panel ---------------------------------------------------------


def test_admin_view_leads_with_the_adoption_gap():
    """The gap between opened and entered is the number that matters."""
    view = cards_command._admin_view(
        {
            "opened": 30, "entered": 12, "finished": 4, "hidden": 2,
            "active": 9, "proposed": 20, "completed": 7, "expired": 5,
            "live": 3, "stalled": [], "stalled_total": 0,
        },
        names={},
        tag="#ME",
    )
    text = _view_text(view)

    assert "**12 of 30 people**" in text
    assert "18 entered nothing on any account" in text
    _assert_discord_payload(view)


def test_admin_view_names_the_people_worth_a_nudge():
    view = cards_command._admin_view(
        {
            "opened": 2, "entered": 1, "finished": 0, "hidden": 0,
            "active": 1, "proposed": 0, "completed": 0, "expired": 0,
            "live": 0, "stalled_total": 1,
            "stalled": [{"_id": "#A", "discord_id": 55, "player_name": "InGame"}],
        },
        names={55: "PoppaSlayer"},
        tag="#ME",
    )
    text = _view_text(view)

    assert "<@55>" in text
    _assert_discord_payload(view)


def test_admin_view_always_offers_a_way_back():
    """It replaces the board, so with no control it was a dead end."""
    view = cards_command._admin_view(
        {
            "opened": 0, "entered": 0, "finished": 0, "hidden": 0,
            "active": 0, "proposed": 0, "completed": 0, "expired": 0,
            "live": 0, "stalled": [], "stalled_total": 0,
        },
        names={},
        tag="#ME",
    )
    ids = [
        str(n.get("custom_id")) for n in _view_nodes(view) if n.get("type") == 2
    ]

    assert "cards_dashboard:#ME" in ids


def test_admin_view_says_when_the_nudge_list_is_truncated():
    """Fifty stalled people must not silently render as ten."""
    view = cards_command._admin_view(
        {
            "opened": 60, "entered": 10, "finished": 0, "hidden": 0,
            "active": 5, "proposed": 0, "completed": 0, "expired": 0,
            "live": 0, "stalled_total": 50,
            "stalled": [
                {"_id": f"#T{i}", "discord_id": 100 + i} for i in range(10)
            ],
        },
        names={},
        tag="#ME",
    )
    text = _view_text(view)

    assert "Showing 10 of 50" in text
    # The whole point of the cap: the panel still fits whatever the number is.
    _assert_discord_payload(view)


class _FakeRole:
    def __init__(self, role_id, permissions):
        self.id = role_id
        self.permissions = permissions


class _FakeGuild:
    def __init__(self, guild_id, roles, owner_id=0):
        self.id = guild_id
        self.owner_id = owner_id
        self._roles = {role.id: role for role in roles}

    def get_role(self, role_id):
        return self._roles.get(role_id)


class _FakeCache:
    def __init__(self, guild, member):
        self._guild = guild
        self._member = member

    def get_guild(self, _guild_id):
        return self._guild

    def get_member(self, _guild_id, _user_id):
        return self._member


def _admin_ctx(member=None, user_id=1):
    return SimpleNamespace(member=member, user=SimpleNamespace(id=user_id))


def _admin_bot(*, admin: bool):
    permissions = (
        hikari.Permissions.ADMINISTRATOR if admin
        else hikari.Permissions.SEND_MESSAGES
    )
    guild = _FakeGuild(500, [
        _FakeRole(10, permissions),
        _FakeRole(500, hikari.Permissions.NONE),
    ])
    return SimpleNamespace(
        cache=_FakeCache(guild, SimpleNamespace(id=1, role_ids=[10]))
    )


def test_an_admin_is_recognised_from_a_dm(monkeypatch):
    """/cards runs in DMs, where the interaction carries no member at all."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 500)

    assert cards_command._is_cards_admin(
        _admin_ctx(), bot=_admin_bot(admin=True)
    ) is True


def test_an_ordinary_member_is_not(monkeypatch):
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 500)

    assert cards_command._is_cards_admin(
        _admin_ctx(), bot=_admin_bot(admin=False)
    ) is False


def test_the_admin_check_never_takes_the_panel_down(monkeypatch):
    """A cache that misbehaves should hide one button, not break /cards."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 500)

    class _Broken:
        def get_guild(self, _guild_id):
            raise RuntimeError("cache exploded")

        def get_member(self, _guild_id, _user_id):
            raise RuntimeError("cache exploded")

    bot = SimpleNamespace(cache=_Broken())
    assert cards_command._is_cards_admin(_admin_ctx(), bot=bot) is False
    assert cards_command._is_cards_admin_id(1, bot=bot) is False


def test_the_category_editor_opens_showing_what_you_already_have():
    """Doing nothing must change nothing, and the screen must say so.

    Both menus mark your current state as the default selection, each list
    saves through its own handler, and Done is navigation carrying no select
    data - so leaving without submitting cannot alter anything. The old copy
    said "unselected cards are treated as 1 copy", which describes submitting
    ONE list but reads as a threat over the whole screen.
    """
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["balloon"] = cards.MISSING
    inventory["cards"]["wizard"] = 3

    listing = _view_text(
        cards_command._quantity_editor(account, inventory, "elixir")
    )

    # Every card states its own count, all on the one screen. The old editor
    # could only say missing, one or spare, so the real number lived
    # elsewhere; the paged one showed six cards out of nineteen.
    assert "Balloon \u00b7 `0`" in listing
    assert "Wizard \u00b7 `3`" in listing

    view = cards_command._quantity_editor(account, inventory, "elixir")
    text = _view_text(view)
    assert "Update collection" in text, "continuity with the button that opened it"
    assert "Changes save automatically." in text
    # Dropped deliberately: a change saves on its own, so telling people what
    # happens when they leave raises a question nobody had.
    assert "Leaving" not in text
    assert "treated as **1 copy**" not in text
    assert "Sir Ruggie" not in text
    _assert_discord_payload(view)




def test_rebuild_a_category_survives_reviewing_every_category():
    """It vanished for anyone who finished reviewing, and never came back.

    Reviewing a category cannot be undone, so the only route back to a full
    category rebuild was gone for good - on a collection that still had 28
    missing cards and a bad scan to redo.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    reviewed = _complete_inventory()      # all four categories reviewed
    assert len(reviewed["complete_categories"]) == len(cards.CATEGORIES)

    view = cards_command._dashboard(account, reviewed, account_count=1)
    labels = [
        str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
    ]

    assert "Update collection" in labels
    _assert_discord_payload(view)


def test_the_admin_button_is_only_drawn_for_admins():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()

    def labels(is_admin):
        view = cards_command._dashboard(
            account, inventory, account_count=1, is_admin=is_admin
        )
        return [
            str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
        ]

    assert "Admin" in labels(True)
    assert "Admin" not in labels(False)


class _AdminInventories:
    def __init__(self, documents):
        self.documents = documents

    async def distinct(self, field, query=None):
        return [d.get(field) for d in self.documents if d.get(field)]

    def find(self, _query):
        return _AdminCursor(self.documents)


class _AdminCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, length=None):
        return self.rows[:length] if length else self.rows


class _AdminTrades:
    async def count_documents(self, _query):
        return 0


def test_an_admin_actually_gets_the_panel_from_the_button(monkeypatch):
    """The unit checks passed while the handler still refused every admin.

    The gate was called with its arguments the wrong way round, which no test
    of the gate itself could ever see. This runs the handler.
    """
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 500)
    bot = _admin_bot(admin=True)
    mongo = SimpleNamespace(
        card_inventories=_AdminInventories([
            {"_id": "#A", "discord_id": 1, "cards": {"wizard": 2}},
        ]),
        card_trades=_AdminTrades(),
    )

    view = asyncio.run(cards_command.cards_admin(
        _admin_ctx(), "#ME", mongo=mongo, bot=bot
    ))
    text = _view_text(view)

    assert "Admins only" not in text
    assert "Cards · admin" in text


def test_a_non_admin_is_turned_away_but_not_stranded(monkeypatch):
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 500)

    view = asyncio.run(cards_command.cards_admin(
        _admin_ctx(), "#ME",
        mongo=SimpleNamespace(), bot=_admin_bot(admin=False),
    ))

    assert "Admins only" in _view_text(view)
    # Every notice replaces the whole panel, so one without a control leaves
    # running /cards again as the only way out.
    ids = [
        str(n.get("custom_id")) for n in _view_nodes(view) if n.get("type") == 2
    ]
    assert "cards_dashboard:#ME" in ids


def test_the_board_resolves_admin_itself_on_every_screen(monkeypatch):
    """Threading a flag meant the button showed on some screens, not others."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 500)
    monkeypatch.setattr(
        cards_command.bot_data, "data", {"bot": _admin_bot(admin=True)}
    )
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["discord_id"] = 1

    # No is_admin argument at all, which is how every call site renders it.
    view = cards_command._dashboard(account, inventory, account_count=1)
    labels = [
        str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
    ]

    assert "Admin" in labels


def _fake_load_target(account, document):
    async def load_target(*_args, **_kwargs):
        # The live document, not a snapshot: _write_card_state checks the
        # revision it was handed against the one in the database, so a stale
        # copy here would fail the second write for the wrong reason.
        return account, document, None
    return load_target


def _quantity_ctx(user_id=123, values=()):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        guild_id=1,
        interaction=SimpleNamespace(values=list(values)),
    )


def _run_rendered(custom_id, *, mongo, coc_client, values=()):
    """Dispatch a rendered custom_id the way extensions/components.py does.

    The id is split here exactly as _dispatch splits it - on the first colon -
    and the handler is looked up in the real registry. Building the action_id
    by hand is how two shipped buttons were wrong before: cards_gem_ask went
    out answering "Out of date" to every click, and the admin gate refused
    every admin, both because the test called the function directly with
    arguments the dispatcher would never have produced.
    """
    from extensions.components import _resolve

    command_name, _, action_id = str(custom_id).partition(":")
    action = _resolve(command_name)
    assert action is not None, f"{command_name} is not registered"
    handler = getattr(cards_command, command_name)
    return asyncio.run(handler(
        _quantity_ctx(values=values),
        action_id,
        coc_client=coc_client,
        mongo=mongo,
    ))


def _quantity_env(cards_state=None, complete=()):
    document = {
        "_id": "#ME",
        "discord_id": 123,
        "inventory_revision": 0,
        "cards": dict(cards_state or {}),
        "complete_categories": list(complete),
        "reviewed_lists": [],
        "confirmed_at": datetime.now(timezone.utc),
    }
    mongo = SimpleNamespace(
        card_inventories=_FakeCategoryCollection(document),
    )
    cards_command._inventory_locks.clear()
    return document, mongo


def test_the_plus_button_writes_and_keeps_the_card_selected(monkeypatch):
    """End to end through the real dispatcher, on the real rendered id."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document, mongo = _quantity_env()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    # Not the default card, so a handler that forgot the selection would be
    # visibly editing the wrong one.
    target = cards.CATEGORY_CARDS["elixir"][7]
    view = cards_command._quantity_editor(
        account, document, "elixir", card_id=target.id
    )
    plus = next(
        str(n["custom_id"]) for n in _view_nodes(view)
        if str(n.get("custom_id", "")) == f"cards_qstep:#ME|{target.id}|1"
    )

    result = _run_rendered(plus, mongo=mongo, coc_client=SimpleNamespace())

    assert document["cards"][target.id] == cards.OWNED + 1
    ids = [str(n["custom_id"]) for n in _view_nodes(result) if "custom_id" in n]
    assert f"cards_qstep:#ME|{target.id}|1" in ids, "selection must survive a step"
    # The closed menu is the only place the chosen card is named now, so its
    # default-marked option has to carry the NEW number. A default option is
    # drawn in place of the placeholder, which is what makes that readable.
    menu = next(
        n for n in _view_nodes(result)
        if n.get("type") == 3
        and str(n.get("custom_id", "")).startswith("cards_qpick:")
    )
    default = [o for o in menu["options"] if o.get("default")]
    assert [o["value"] for o in default] == [target.id]
    assert default[0]["label"] == f"{target.name} · 2"
    assert "Editing" not in _view_text(result), (
        "the menu carries the selection; a second line could fall out of step"
    )


def test_the_minus_button_stops_at_missing_and_never_goes_negative(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document, mongo = _quantity_env({"barbarian": cards.OWNED})
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    minus = "cards_qstep:#ME|barbarian|-1"

    _run_rendered(minus, mongo=mongo, coc_client=SimpleNamespace())
    assert document["cards"]["barbarian"] == cards.MISSING

    # The button renders disabled at this point, but a stale click must still
    # be harmless rather than writing -1.
    _run_rendered(minus, mongo=mongo, coc_client=SimpleNamespace())
    assert document["cards"]["barbarian"] == cards.MISSING


def test_a_legacy_ready_button_refreshes_without_granting_trust(monkeypatch):
    """Old Discord messages must not bypass the per-card trust invariant."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document, mongo = _quantity_env({"root_rider": cards.MISSING, "wizard": 3})
    document["trusted_card_ids"] = ["wizard"]
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    result = _run_rendered(
        "cards_ready:#ME|elixir", mongo=mongo, coc_client=SimpleNamespace(),
    )

    assert document["complete_categories"] == []
    assert document["trusted_card_ids"] == ["wizard"]
    assert document["inventory_revision"] == 0
    assert document["cards"]["wizard"] == 3
    assert document["cards"]["root_rider"] == cards.MISSING
    assert "Ready to trade." not in _view_text(result)
    assert not any(
        str(node.get("custom_id", "")).startswith("cards_ready:")
        for node in _view_nodes(result)
    )


def test_choosing_a_card_points_the_controller_at_it(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document, mongo = _quantity_env()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    view = cards_command._quantity_editor(account, document, "elixir")
    picker = next(
        str(n["custom_id"]) for n in _view_nodes(view)
        if str(n.get("custom_id", "")).startswith("cards_qpick:")
    )
    last = cards.CATEGORY_CARDS["elixir"][-1]

    result = _run_rendered(
        picker, mongo=mongo, coc_client=SimpleNamespace(), values=[last.id],
    )
    ids = [str(n["custom_id"]) for n in _view_nodes(result) if "custom_id" in n]
    assert f"cards_qstep:#ME|{last.id}|1" in ids
    assert f"cards_qnum:#ME|{last.id}" in ids
    assert last.name in _view_text(result)


def test_the_category_screen_stays_far_below_the_component_ceiling():
    """Discord rejects the whole message past 40 components.

    The paged build sat at 37 of 40. Listing the category as one text
    component instead of six rows of buttons costs about a third of that, and
    the number does not move with the size of the category.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    worst = 0
    for category in cards.CATEGORIES:
        for complete in ([], [category.id]):
            inventory = {
                "_id": "#ME",
                "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
                "complete_categories": complete,
            }
            for card in cards.CATEGORY_CARDS[category.id]:
                view = cards_command._quantity_editor(
                    account, inventory, category.id, card_id=card.id,
                    saved="A saved line, which is the widest this ever gets.",
                )
                worst = max(
                    worst, len([n for n in _view_nodes(view) if "type" in n])
                )
                _assert_discord_payload(view)
    # Scanning and the category menu sit on this screen, and it remains far
    # below Discord's ceiling. The removed Ready row saves three components;
    # the worst case still includes Set to 2 for an unconfirmed scanner 2+.
    assert worst == 24, f"expected a fixed 24, got {worst}"


def test_set_number_opens_a_modal_for_the_selected_card():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document, _mongo = _quantity_env()
    target = cards.CATEGORY_CARDS["elixir"][5]
    view = cards_command._quantity_editor(
        account, document, "elixir", card_id=target.id
    )
    opener = next(
        str(n["custom_id"]) for n in _view_nodes(view)
        if str(n.get("custom_id", "")).startswith("cards_qnum:")
    )
    opened = {}

    class ModalCtx:
        user = SimpleNamespace(id=123)
        guild_id = 1
        interaction = SimpleNamespace(values=[])

        async def respond_with_modal(self, *, title, custom_id, components):
            opened["title"] = title
            opened["custom_id"] = custom_id

    asyncio.run(cards_command.cards_qnum(ModalCtx(), opener.split(":", 1)[1]))

    assert opened["title"] == target.name[:45]
    assert opened["custom_id"] == f"cards_qnum_submit:#ME|{target.id}"


class _SubmitCtx:
    user = SimpleNamespace(id=123)
    guild_id = 1

    def __init__(self, raw, sink):
        self._sink = sink
        self.interaction = SimpleNamespace(
            components=[[SimpleNamespace(custom_id="copies", value=raw)]],
            edit_initial_response=self._edit,
        )

    async def defer(self, *_args, **_kwargs):
        return None

    async def _edit(self, components=None, **_kwargs):
        self._sink["view"] = components


def test_typing_an_exact_number_saves_and_stays_on_the_category(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document, mongo = _quantity_env()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    sent = {}
    target = cards.CATEGORY_CARDS["elixir"][5]

    asyncio.run(cards_command.cards_qnum_submit(
        _SubmitCtx("7", sent), f"#ME|{target.id}",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))
    assert document["cards"][target.id] == 7
    assert f"{target.name}** · `7`" in _view_text(sent["view"])

    # Junk in, nothing changed, and the member is told so on the same screen.
    asyncio.run(cards_command.cards_qnum_submit(
        _SubmitCtx("lots", sent), f"#ME|{target.id}",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))
    assert document["cards"][target.id] == 7
    assert "not a number" in _view_text(sent["view"])
    assert target.name in _view_text(sent["view"])


def test_a_number_beyond_the_maximum_is_clamped_not_rejected(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    document, mongo = _quantity_env()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    sent = {}
    asyncio.run(cards_command.cards_qnum_submit(
        _SubmitCtx("99", sent), "#ME|barbarian",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))
    assert document["cards"]["barbarian"] == cards.MAX_COPIES


def test_the_pencil_marks_only_the_row_being_edited():
    """One mark, on one row, at the end of it.

    Bold alone can only be spotted by comparing a row against the eighteen
    around it. A mark that appears exactly once is found without comparing
    anything - so it has to appear exactly once.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = {"_id": "#ME", "cards": {"wizard": 3}, "complete_categories": []}
    pencil = str(emojis.editing_pencil)

    # Nothing selected: no pencil anywhere on the screen.
    blank = cards_command._quantity_editor(account, inventory, "elixir")
    assert pencil not in _view_text(blank)

    for card in cards.CATEGORY_CARDS["elixir"]:
        view = cards_command._quantity_editor(
            account, inventory, "elixir", card_id=card.id
        )
        text = _view_text(view)
        assert text.count(pencil) == 1, card.id
        marked = [
            line for line in text.splitlines() if pencil in line
        ]
        assert len(marked) == 1
        # On the chosen card's row, after its count, and that row is also the
        # bold one - the two marks agree rather than pointing at different
        # cards.
        assert card.name in marked[0], marked[0]
        assert marked[0].rstrip().endswith(pencil), marked[0]
        assert f"**{card.name}**" in marked[0], marked[0]


def test_a_selected_card_still_reports_a_clean_count():
    """The pencil sits outside the code span, so the number stays readable."""
    import re

    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = {
        "_id": "#ME",
        "cards": {"wizard": 3, "barbarian": 0},
        "complete_categories": [],
    }
    view = cards_command._quantity_editor(
        account, inventory, "elixir", card_id="wizard"
    )
    listing = next(
        str(n["content"]) for n in _view_nodes(view)
        if n.get("type") == 10 and "Meteor Golem" in str(n["content"])
    )
    counts = set(re.findall(r"`([^`]+)`", listing))
    assert counts <= {"0", "1", "2", "2+", "3"}, counts
    assert "`3`" in listing and "`0`" in listing


def _switcher_account(name, town_hall, clan, tag):
    return SimpleNamespace(
        name=name, town_hall=town_hall, clan_name=clan, tag=tag, clan_tag="#C",
    )


def _switcher_data(count=37):
    from extensions.commands.accounts import AccountEntry, AccountsData

    return AccountsData(entries=tuple(
        AccountEntry(
            tag=f"#T{index:04d}",
            status=cards_command.STATUS_LOADED,
            account=_switcher_account(
                f"Alt {index}", 18 - (index % 4), "Warriors United",
                f"#T{index:04d}",
            ),
        )
        for index in range(count)
    ))


def _switcher_options(view):
    return [
        option
        for node in _view_nodes(view)
        for option in (node.get("options") or ())
    ]


def test_an_account_with_no_town_hall_does_not_read_th_none():
    """It printed "THNone", in the name and in the line under it.

    The town hall is missing whenever the profile lookup came back thin. No
    level at all is better than a wrong one.
    """
    from extensions.commands.accounts import AccountEntry, AccountsData

    for missing in (None, 0):
        data = AccountsData(entries=(AccountEntry(
            tag="#GHOST",
            status=cards_command.STATUS_LOADED,
            account=_switcher_account("Ghost", missing, "Some Clan", "#GHOST"),
        ),))
        option = _switcher_options(cards_command._account_picker(data))[0]
        assert "None" not in option["label"], option["label"]
        assert "None" not in option["description"], option["description"]
        assert "TH0" not in option["description"], option["description"]
        # What is known is still shown.
        assert "Some Clan" in option["description"]
        assert "#GHOST" in option["description"]


def test_a_missing_clan_reads_as_no_clan_not_as_nothing():
    from extensions.commands.accounts import AccountEntry, AccountsData

    data = AccountsData(entries=(AccountEntry(
        tag="#LONE",
        status=cards_command.STATUS_LOADED,
        account=_switcher_account("Loner", 18, None, "#LONE"),
    ),))
    option = _switcher_options(cards_command._account_picker(data))[0]
    assert option["description"] == "TH18 · No clan · #LONE"


def test_long_names_and_clans_stay_inside_discord_limits():
    """Discord rejects a select option label over 100 or description over 100."""
    from extensions.commands.accounts import AccountEntry, AccountsData

    data = AccountsData(entries=(AccountEntry(
        tag="#LONG",
        status=cards_command.STATUS_LOADED,
        account=_switcher_account("N" * 200, 17, "C" * 200, "#LONG"),
    ),))
    option = _switcher_options(cards_command._account_picker(data))[0]
    assert len(option["label"]) <= 100
    assert len(option["description"]) <= 100


def test_the_switcher_pages_at_discords_twenty_five_option_limit():
    """A select menu takes 25 options, which is why this pages at all."""
    assert cards_command.ACCOUNT_PAGE_SIZE == 25
    data = _switcher_data(37)

    first = cards_command._account_picker(data, 0, back_tag="#ME")
    last = cards_command._account_picker(data, 1, back_tag="#ME")

    assert len(_switcher_options(first)) == 25
    assert len(_switcher_options(last)) == 12

    def pager(view):
        return {
            str(n.get("label")): bool(n.get("disabled"))
            for n in _view_nodes(view)
            if str(n.get("custom_id", "")).startswith("cards_account_page:")
        }

    assert pager(first) == {"Previous": True, "Next": False}
    assert pager(last) == {"Previous": False, "Next": True}

    # The range sits above the menu, so the reader knows which stretch of
    # accounts they are opening before they open it, and it carries the total
    # rather than repeating it on a second line.
    text = _view_text(first)
    assert "Accounts 1–25 of 37" in text
    assert "Accounts 26–37 of 37" in _view_text(last)
    assert text.count("37") == 1, "the total belongs on one line only"
    assert "linked" not in text


def test_one_page_of_accounts_needs_no_pager():
    data = _switcher_data(5)
    view = cards_command._account_picker(data, 0, back_tag="#ME")
    assert not [
        n for n in _view_nodes(view)
        if str(n.get("custom_id", "")).startswith("cards_account_page:")
    ]
    assert "5 accounts · Each has its own collection." in _view_text(view)


def test_the_switcher_offers_a_way_back_to_the_collection_it_replaced():
    """It edits the panel in place, so there is nothing underneath.

    The dispatcher answers a component with `respond(edit=True)` and the whole
    /cards panel is ephemeral, so opening the switcher replaces the collection
    entirely. Without this button, changing your mind meant running /cards
    again.
    """
    data = _switcher_data(37)
    view = cards_command._account_picker(data, 0, back_tag="#ME")
    ids = [str(n["custom_id"]) for n in _view_nodes(view) if "custom_id" in n]
    assert "cards_dashboard:#ME" in ids
    assert "Back to collection" in _view_labels(view)
    # Both pagers carry the tag too, or paging once would lose the way back.
    assert "cards_account_page:1|#ME" in ids


def test_a_switcher_opened_without_a_tag_simply_has_no_back_button():
    """Buttons sent before the tag was threaded through must still work."""
    page, tag = cards_command._parse_account_page("0")
    assert (page, tag) == (0, None)
    page, tag = cards_command._parse_account_page("1|#ME")
    assert (page, tag) == (1, "#ME")

    view = cards_command._account_picker(_switcher_data(37), 0)
    ids = [str(n["custom_id"]) for n in _view_nodes(view) if "custom_id" in n]
    assert not any(cid.startswith("cards_dashboard:") for cid in ids)
    # And it still pages.
    assert "cards_account_page:1" in ids


# --- partial scan success and the manual fallback ---------------------------


def _partial_scan_draft(*, accepted_rows=(1, 2), duplicate_unverified=()):
    """What the row scanner produces when only some rows were confirmed."""
    confirmed = [
        card.id
        for row in accepted_rows
        for card in cards.CARDS[(row - 1) * 6:row * 6]
    ]
    unseen = [card.id for card in cards.CARDS if card.id not in confirmed]
    manual_rows = [row for row in range(1, 11) if row not in accepted_rows]
    return {
        "version": 2,
        "capture_count": 5,
        "card_states": {card_id: cards.OWNED for card_id in confirmed},
        "card_confidences": {card_id: 0.95 for card_id in confirmed},
        "card_warnings": {},
        "unknown_card_ids": [],
        "unseen_card_ids": unseen,
        "duplicate_unverified_card_ids": list(duplicate_unverified),
        "capture_issues": [],
        "warnings": ["manual_review_required"],
        "errors": [],
        "identity_bound": True,
        "coverage_complete": False,
        "missing_page_numbers": sorted({(row + 1) // 2 for row in manual_rows}),
        "missing_global_rows": manual_rows,
        "accepted_global_rows": list(accepted_rows),
        "manual_required_global_rows": manual_rows,
        "manual_required_card_ids": unseen,
        "row_decisions": [
            {
                "image": 1,
                "row_index": 0,
                "accepted": True,
                "outcome": "accepted",
                "reason": "",
                "proposed_row": accepted_rows[0],
                "catalog_row": accepted_rows[0],
                "identity_top1": 2.5,
                "identity_gap": 52.0,
            },
        ],
        "scanner_version": "wu-cards scanner development freeze 2026-08-13",
    }


def _one_unknown_scan_draft(card_id="wizard"):
    draft = _partial_scan_draft(accepted_rows=tuple(range(1, 11)))
    draft["card_states"].pop(card_id)
    draft["card_confidences"].pop(card_id)
    draft["unknown_card_ids"] = [card_id]
    draft["manual_required_card_ids"] = [card_id]
    draft["warnings"] = ["manual_review_required"]
    return draft


def test_a_partial_scan_makes_finish_collection_the_primary_recovery():
    draft = _partial_scan_draft()

    assert cards_command._scan_draft_confirmable(draft) is False
    assert cards_command._scan_draft_partially_savable(draft) is True

    view = cards_command._scan_review(
        _scan_account(), {"_id": "#ME"}, "draft-partial", draft
    )
    labels = _view_labels(view)
    ids = {node.get("custom_id") for node in _view_nodes(view)}
    text = _view_text(view)

    assert labels == ["Finish collection", "Cancel"]
    assert "cards_scan_save_partial:draft-partial" in ids
    assert "cards_advanced:#ME" not in ids
    assert "cards_scan_confirm:draft-partial" not in ids
    assert "I read 12 of 60 cards." in text
    assert "Nothing is saved yet." in text
    assert "Nothing was guessed." in text
    assert "48 still need a count." in text
    assert "Finish collection" in text
    assert "opens the remaining cards for exact counts" in text
    assert "try again" in text, "screenshot retry remains a secondary hint"
    assert "not ready to trade" in text
    # Scanner diagnostics belong in the evidence, never in player copy.
    for jargon in ("top1", "hash", "hamming", "margin", "pitch", "gate"):
        assert jargon not in text.lower()
    _assert_discord_payload(view)


def test_a_partial_scan_saves_only_confirmed_rows_and_drops_stale_readiness():
    account = _scan_account()
    draft = _partial_scan_draft(duplicate_unverified=("archer",))
    document = {
        "_id": "#ME",
        "inventory_revision": 2,
        "cards": {card.id: cards.MISSING for card in cards.CARDS},
        "complete_categories": ["elixir"],
        "reviewed_lists": ["elixir:missing"],
        "count_confirmed_card_ids": ["barbarian", "super_bowler"],
        "confirmed_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_scan_partial(
        mongo,
        account,
        draft,
        expected_revision=2,
        discord_id=123,
        guild_id=1,
    ))

    confirmed_ids = {card.id for card in cards.CARDS[:12]}
    assert all(updated["cards"][card_id] == cards.OWNED for card_id in confirmed_ids)
    assert all(
        updated["cards"][card.id] == cards.MISSING
        for card in cards.CARDS
        if card.id not in confirmed_ids
    )
    # Rows 1 and 2 are elixir, and elixir cards further down still need
    # checking, so elixir cannot stay ready to trade.
    assert updated["complete_categories"] == []
    assert updated["reviewed_lists"] == []
    assert set(updated["trusted_card_ids"]) == confirmed_ids - {"archer"}
    assert "archer" not in updated["trusted_card_ids"], (
        "an uncertain duplicate badge is not a trusted count"
    )
    # The accepted save refreshes candidate lookup; complete_categories still
    # keeps every unchecked category out of matching.
    assert updated["confirmed_at"] > datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert updated["update_source"] == "confirmed_partial_screenshot_review"
    assert updated["inventory_revision"] == 3
    # A scanner floor cannot inherit a member's exact count.
    assert updated["count_confirmed_card_ids"] == ["super_bowler"]
    assert updated["scan_duplicate_unverified_card_ids"] == ["archer"]


def test_a_partial_scan_with_one_unknown_card_exposes_no_untrusted_match():
    unknown_id = "wizard"
    document = {
        "_id": "#ME",
        "inventory_revision": 0,
        "cards": {card.id: cards.OWNED for card in cards.CARDS},
        "complete_categories": [],
        "reviewed_lists": [],
    }
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_scan_partial(
        mongo,
        _scan_account(),
        _one_unknown_scan_draft(unknown_id),
        expected_revision=0,
        discord_id=123,
        guild_id=1,
    ))

    assert len(updated["trusted_card_ids"]) == len(cards.CARDS) - 1
    assert unknown_id not in updated["trusted_card_ids"]
    assert "elixir" not in updated["complete_categories"]
    assert set(updated["complete_categories"]) == {
        "dark_elixir", "builder_base", "super_troop",
    }
    assert updated["confirmed_at"] is not None

    partner = _complete_inventory(tag="#YOU")
    partner["cards"][unknown_id] = cards.DUPLICATE
    updated["cards"][unknown_id] = cards.MISSING
    assert cards.find_matches(updated, [partner]) == []


def test_a_partial_scan_write_keeps_revision_and_reservation_protection():
    account = _scan_account()
    draft = _partial_scan_draft()

    stale = {
        "_id": "#ME",
        "inventory_revision": 3,
        "cards": {"wizard": cards.DUPLICATE},
    }
    stale_mongo = SimpleNamespace(card_inventories=_FakeInventoryCollection([stale]))
    cards_command._inventory_locks.clear()
    with pytest.raises(cards_command.ScanDraftStaleError):
        asyncio.run(cards_command._write_scan_partial(
            stale_mongo, account, draft,
            expected_revision=2, discord_id=123, guild_id=1,
        ))
    assert stale["cards"] == {"wizard": cards.DUPLICATE}
    assert stale["inventory_revision"] == 3

    reserved = {
        "_id": "#ME",
        "inventory_revision": 2,
        "cards": {"wizard": cards.DUPLICATE},
        "card_trade_reservations": {
            "wizard": {
                "owner": "trade-a:token-a",
                "until": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        },
    }
    reserved_mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([reserved])
    )
    cards_command._inventory_locks.clear()
    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_scan_partial(
            reserved_mongo, account, draft,
            expected_revision=2, discord_id=123, guild_id=1,
        ))
    assert reserved["cards"] == {"wizard": cards.DUPLICATE}
    assert reserved["inventory_revision"] == 2


def test_a_card_from_a_rejected_row_can_never_be_saved():
    """Row atomicity at the write boundary, not only in the scanner."""
    draft = _partial_scan_draft(accepted_rows=(1,))
    stowaway = cards.CARDS[7].id            # a card from unconfirmed row 2
    draft["card_states"][stowaway] = cards.DUPLICATE
    draft["card_confidences"][stowaway] = 0.99
    draft["unseen_card_ids"] = [
        card_id for card_id in draft["unseen_card_ids"] if card_id != stowaway
    ]

    assert cards_command._scan_draft_partially_savable(draft) is False

    document = {"_id": "#ME", "inventory_revision": 0, "cards": {}}
    mongo = SimpleNamespace(card_inventories=_FakeInventoryCollection([document]))
    cards_command._inventory_locks.clear()
    with pytest.raises(ValueError):
        asyncio.run(cards_command._write_scan_partial(
            mongo, _scan_account(), draft,
            expected_revision=0, discord_id=123, guild_id=1,
        ))
    assert document["cards"] == {}


def test_a_partial_draft_cannot_use_the_full_save_path(monkeypatch):
    account = _scan_account()
    draft = _partial_scan_draft()
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 4
    writes = []

    async def load_bound(*_args, **_kwargs):
        return account, inventory, _scan_accounts_data(account), None

    async def write_scan(*args, **kwargs):
        writes.append((args, kwargs))
        return inventory

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_scan_bound_account", load_bound)
    monkeypatch.setattr(cards_command, "_write_scan_draft", write_scan)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    view = asyncio.run(cards_command._confirm_scan_draft(
        ctx,
        "draft-partial",
        scan_draft=draft,
        user_id=123,
        guild_id=1,
        account_tag="#ME",
        base_revision=4,
        usable_until=None,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert writes == []
    assert "Finish collection" in _view_labels(view)


def test_saving_a_partial_scan_hands_untrusted_cards_to_bulk_finish(monkeypatch):
    account = _scan_account()
    draft = _partial_scan_draft()
    saved_inventory = _complete_inventory()
    saved_inventory["inventory_revision"] = 5
    saved_inventory["complete_categories"] = []
    saved_inventory["trusted_card_ids"] = [
        card.id for card in cards.CARDS[:12]
    ]
    discarded = []
    writes = []
    created = []

    async def load_bound(*_args, **_kwargs):
        return account, saved_inventory, _scan_accounts_data(account), None

    async def write_partial(_mongo, _account, _draft, **kwargs):
        writes.append(kwargs)
        return saved_inventory

    async def discard(_mongo, draft_id):
        discarded.append(draft_id)

    async def create_bulk(
        _ctx, _account, inventory, *, mongo, category_id, scope, selected_ids,
    ):
        created.append({
            "inventory": inventory,
            "mongo": mongo,
            "category_id": category_id,
            "scope": scope,
            "selected_ids": list(selected_ids),
        })
        state = {
            "account_name": account.name,
            "account_tag": account.tag,
            "category_id": category_id,
            "selected_ids": list(selected_ids),
        }
        return "cards_finish_test|ME|elixir", state

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_scan_bound_account", load_bound)
    monkeypatch.setattr(cards_command, "_write_scan_partial", write_partial)
    monkeypatch.setattr(cards_command, "_discard_scan_state", discard)
    monkeypatch.setattr(cards_command, "_create_bulk_state", create_bulk)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    view = asyncio.run(cards_command._save_partial_scan_draft(
        ctx,
        "draft-partial",
        scan_draft=draft,
        user_id=123,
        guild_id=1,
        account_tag="#ME",
        base_revision=4,
        usable_until=None,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert writes == [{
        "expected_revision": 4, "discord_id": 123, "guild_id": 1,
    }]
    assert discarded == ["draft-partial"]
    unresolved = [card.id for card in cards.CARDS[12:]]
    assert len(created) == 1
    assert created[0]["inventory"] is saved_inventory
    assert created[0]["category_id"] == cards.CARD_BY_ID[unresolved[0]].category
    assert created[0]["scope"] == "scan_finish"
    assert created[0]["selected_ids"] == unresolved
    text = _view_text(view)
    ids = {node.get("custom_id") for node in _view_nodes(view)}
    assert "Scan finished" in text
    assert "12 of 60 cards read" in text
    assert "48 still need a count" in text
    assert "Finish these cards to complete your collection" in text
    assert "Ready to trade" not in text
    assert "cards_bulk_continue:cards_finish_test|ME|elixir" in ids
    assert "cards_bulk_finish:cards_finish_test|ME|elixir" in ids
    assert not any(str(value).startswith("cards_ready:") for value in ids)
    _assert_discord_payload(view)


def test_scanner_finish_state_preselects_a_cross_category_required_queue(
    monkeypatch,
):
    account = _scan_account()
    unresolved = [
        cards.CATEGORY_CARDS["elixir"][-2].id,
        cards.CATEGORY_CARDS["elixir"][-1].id,
        *[card.id for card in cards.CATEGORY_CARDS["dark_elixir"][:5]],
    ]
    inventory = {
        "_id": "#ME",
        "inventory_revision": 7,
        "cards": {card.id: cards.DUPLICATE for card in cards.CARDS},
        "trusted_card_ids": [
            card.id for card in cards.CARDS if card.id not in unresolved
        ],
        "complete_categories": ["builder_base", "super_troop"],
    }
    inserted = []

    async def insert(_mongo, document, *, ttl):
        inserted.append((document, ttl))

    monkeypatch.setattr(cards_command, "insert_state", insert)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)
    state_id, state = asyncio.run(cards_command._create_bulk_state(
        ctx,
        account,
        inventory,
        mongo=SimpleNamespace(),
        category_id="elixir",
        scope="scan_finish",
        selected_ids=unresolved,
    ))

    assert state_id.startswith("cards_finish_")
    assert state["scope"] == "scan_finish"
    assert state["editable_ids"] == unresolved
    assert state["selected_ids"] == unresolved
    assert state["required_entry_ids"] == unresolved
    assert state["unconfirmed_ids"] == [], (
        "untrusted scanner values require an answer even when stored as 2+"
    )
    assert state["expected_revision"] == 7
    assert state["phase"] == "continue"
    assert cards_command._bulk_state_well_formed(state) is True
    assert inserted and inserted[0][0]["_id"] == state_id

    modal = cards_command._bulk_exact_modal(state_id, state)
    assert modal["title"] == "Finish collection · 1-5 of 7"
    assert modal["custom_id"] == f"cards_bulk_submit:{state_id}"
    nodes = list(_walk_payload([
        component.build() for component in modal["components"]
    ]))
    inputs = [node for node in nodes if node.get("type") == 4]
    assert len(inputs) == 5
    assert all(node["required"] is True for node in inputs)
    assert all("value" not in node for node in inputs), (
        "stored uncertain values must not prefill a required manual answer"
    )


def test_scanner_finish_batches_autosave_and_the_final_batch_makes_ready():
    account = _scan_account()
    unresolved = [
        cards.CATEGORY_CARDS["elixir"][-2].id,
        cards.CATEGORY_CARDS["elixir"][-1].id,
        *[card.id for card in cards.CATEGORY_CARDS["dark_elixir"][:5]],
    ]
    document = {
        "_id": "#ME",
        "inventory_revision": 0,
        "cards": {card.id: cards.OWNED for card in cards.CARDS},
        "trusted_card_ids": [
            card.id for card in cards.CARDS if card.id not in unresolved
        ],
        "complete_categories": ["builder_base", "super_troop"],
        "reviewed_lists": [],
    }
    collection = _FakeInventoryCollection([document])
    mongo = SimpleNamespace(card_inventories=collection)
    cards_command._inventory_locks.clear()

    first_ids = unresolved[:5]
    first_values = dict(zip(first_ids, (0, 1, 2, 3, 4), strict=True))
    after_first = asyncio.run(cards_command._write_exact_card_batch(
        mongo,
        account,
        document,
        first_ids,
        first_values,
        expected_revision=0,
        discord_id=123,
        guild_id=1,
        allowed_ids=unresolved,
    ))

    assert after_first["inventory_revision"] == 1
    assert all(
        after_first["cards"][card_id] == value
        for card_id, value in first_values.items()
    )
    assert set(first_ids) <= set(after_first["trusted_card_ids"])
    assert set(unresolved[5:]).isdisjoint(after_first["trusted_card_ids"])
    assert "elixir" in after_first["complete_categories"]
    assert "dark_elixir" not in after_first["complete_categories"]

    final_ids = unresolved[5:]
    after_final = asyncio.run(cards_command._write_exact_card_batch(
        mongo,
        account,
        after_first,
        final_ids,
        {card_id: 2 for card_id in final_ids},
        expected_revision=1,
        discord_id=123,
        guild_id=1,
        allowed_ids=unresolved,
    ))

    assert after_final["inventory_revision"] == 2
    assert set(after_final["trusted_card_ids"]) == {
        card.id for card in cards.CARDS
    }
    assert set(after_final["complete_categories"]) == {
        category.id for category in cards.CATEGORIES
    }
    assert set(final_ids) <= set(after_final["count_confirmed_card_ids"])


def test_the_dm_review_appears_as_soon_as_one_row_is_confirmed(monkeypatch):
    account = _scan_account()
    data = _scan_accounts_data(account)
    state = {
        "_id": "cards_upload_partial",
        "type": "cards_scan_upload",
        "user_id": 123,
        "guild_id": 1,
        "account_tag": "#ME",
        "base_revision": 4,
        "usable_until": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    updates = []
    sent = []

    class Attachment:
        size = 12
        media_type = "image/png"
        filename = "rows.png"

        async def read(self):
            return b"rows"

    async def find_state(*_args, **_kwargs):
        return state

    async def get_state(*_args, **_kwargs):
        return state

    async def load_accounts(*_args, **_kwargs):
        return data

    def scan(_payloads, *, prior_draft=None):
        return _partial_scan_draft()

    async def update_state(_mongo, query, update, **_kwargs):
        updates.append((query, update))
        return SimpleNamespace(matched_count=1)

    async def send(_bot, channel_id, components):
        sent.append((channel_id, components))
        return SimpleNamespace(id=999)

    async def ensure_inventory(*_args, **_kwargs):
        inventory = _complete_inventory()
        inventory["inventory_revision"] = 4
        return inventory

    async def mark_prompt(*_args, **_kwargs):
        return None

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_find_card_upload_state", find_state)
    monkeypatch.setattr(cards_command, "get_state", get_state)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "_scan_collection_payloads", scan)
    monkeypatch.setattr(cards_command, "update_state", update_state)
    monkeypatch.setattr(cards_command, "_send_scan_dm_components", send)
    monkeypatch.setattr(cards_command, "_ensure_inventory", ensure_inventory)
    monkeypatch.setattr(cards_command, "_mark_scan_prompt_received", mark_prompt)
    event = SimpleNamespace(
        is_human=True,
        author_id=123,
        channel_id=777,
        message=SimpleNamespace(attachments=(Attachment(),)),
    )

    asyncio.run(cards_command._handle_card_scan_dm_upload(
        event,
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
        bot=SimpleNamespace(),
    ))

    text = _view_text(sent[0][1])
    assert "Scan complete" in text
    assert "Nothing is saved yet." in text
    assert "Finish collection" in _view_labels(sent[0][1])
    # The draft was stored, and the upload stays open so more screenshots can
    # still reach the same draft.
    assert len(updates) == 1
    assert updates[0][1]["$set"]["scan_draft"]["accepted_global_rows"] == [1, 2]
    assert _contains_raw_bytes(updates[0][1]["$set"]["scan_draft"]) is False


def test_the_adapter_keeps_row_provenance_and_stays_bson_safe():
    draft = cards_command._normalize_collection_scan(
        {
            "cards": {
                card.id: {"state": cards.OWNED, "confidence": 0.95}
                for card in cards.CARDS[:6]
            },
            "unseen_card_ids": [card.id for card in cards.CARDS[6:]],
            "missing_global_rows": [2, 3, 4, 5, 6, 7, 8, 9, 10],
            "missing_page_numbers": [1, 2, 3, 4, 5],
            "accepted_global_rows": [1],
            "row_decisions": [
                SimpleNamespace(
                    input_index=1, row_index=0, accepted=True,
                    outcome="accepted", reason="", proposed_row=1,
                    catalog_row=1, identity_top1=3.1667, identity_gap=56.5,
                ),
                SimpleNamespace(
                    input_index=1, row_index=1, accepted=False,
                    outcome="separation", reason="rival gap 24.83 under 46.00",
                    proposed_row=5, catalog_row=None, identity_top1=34.67,
                    identity_gap=24.83,
                ),
            ],
            "scanner_version": "wu-cards scanner development freeze 2026-08-13",
            "identity_bound": True,
        },
        capture_count=1,
    )

    assert draft["accepted_global_rows"] == [1]
    assert draft["manual_required_global_rows"] == [2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert len(draft["manual_required_card_ids"]) == 54
    accepted, rejected = draft["row_decisions"]
    assert accepted["catalog_row"] == 1 and accepted["accepted"] is True
    # A rejected row keeps its proposal as evidence and no identity.
    assert rejected["proposed_row"] == 5
    assert rejected["catalog_row"] is None
    assert rejected["outcome"] == "separation"
    assert rejected["identity_gap"] == 24.83
    assert cards_command._scan_draft_partially_savable(draft) is True

    def assert_bson_safe(value):
        if isinstance(value, dict):
            assert all(isinstance(key, str) for key in value)
            for nested in value.values():
                assert_bson_safe(nested)
            return
        if isinstance(value, (list, tuple)):
            for nested in value:
                assert_bson_safe(nested)
            return
        assert value is None or type(value) in (bool, int, float, str)

    assert_bson_safe(draft)


def test_a_draft_with_one_uncertain_count_uses_the_shared_bulk_finish_flow():
    draft = _complete_scan_draft()
    uncertain = cards.CARDS[26].id
    draft["card_states"].pop(uncertain)
    draft["card_confidences"].pop(uncertain)
    draft["unknown_card_ids"] = [uncertain]
    draft["accepted_global_rows"] = list(range(1, 11))
    draft["manual_required_global_rows"] = []
    draft["manual_required_card_ids"] = [uncertain]

    assert cards_command._scan_draft_correctable(draft) is True
    assert cards_command._scan_draft_partially_savable(draft) is True

    view = cards_command._scan_review(
        _scan_account(), {"_id": "#ME"}, "draft-correctable", draft
    )
    labels = _view_labels(view)
    ids = {node.get("custom_id") for node in _view_nodes(view)}

    assert labels == ["Finish collection", "Cancel"]
    assert "cards_scan_save_partial:draft-correctable" in ids
    assert "cards_scan_confirm:draft-correctable" not in ids
    assert not any(str(value).startswith("cards_scan_fix_") for value in ids)
    text = _view_text(view)
    assert "59 of 60 cards" in text
    assert "1 still need a count" in text
    assert "opens the remaining cards for exact counts" in text


def test_a_partial_review_names_an_uncertain_card_inside_a_confirmed_row():
    draft = _partial_scan_draft(accepted_rows=(1, 2))
    uncertain = cards.CARDS[4].id
    draft["card_states"].pop(uncertain)
    draft["card_confidences"].pop(uncertain)
    draft["unknown_card_ids"] = [uncertain]
    draft["manual_required_card_ids"] = [
        uncertain, *draft["manual_required_card_ids"],
    ]

    text = _view_text(cards_command._scan_review(
        _scan_account(), {"_id": "#ME"}, "draft-loose", draft
    ))

    assert "49 still need a count" in text
    assert "**Rows 3–10:**" in text
    assert f"**Also:** {cards.CARD_BY_ID[uncertain].name}" in text


# --- row atomicity, all three layers ---------------------------------------


def _sparse_partial_draft(kept_positions):
    """An accepted row that arrived with only some of its six positions.

    The scanner cannot produce this. A stale or edited persisted draft can, and
    the answer to it is the same at every layer: refuse.
    """
    draft = _partial_scan_draft(accepted_rows=(1, 2))
    dropped = [
        card.id
        for index, card in enumerate(cards.CARDS[:6])
        if index not in set(kept_positions)
    ]
    for card_id in dropped:
        draft["card_states"].pop(card_id, None)
        draft["card_confidences"].pop(card_id, None)
    draft["unseen_card_ids"] = [*dropped, *draft["unseen_card_ids"]]
    draft["manual_required_card_ids"] = [
        *dropped, *draft["manual_required_card_ids"],
    ]
    return draft


def test_an_accepted_row_with_one_saved_card_is_refused():
    draft = _sparse_partial_draft((0,))

    assert cards_command._scan_draft_partially_savable(draft) is False


def test_an_accepted_row_missing_one_card_is_refused():
    draft = _sparse_partial_draft((0, 1, 2, 3, 4))

    assert cards_command._scan_draft_partially_savable(draft) is False


def test_an_accepted_row_with_all_six_cards_is_allowed():
    draft = _sparse_partial_draft((0, 1, 2, 3, 4, 5))

    assert cards_command._scan_draft_partially_savable(draft) is True
    assert set(draft["card_states"]) == {
        card.id for card in cards.CARDS[:12]
    }


def test_an_accepted_row_may_hold_an_unknown_count_and_still_save_the_rest():
    """Row identity and card state are separate claims.

    The frozen model can prove a row is that row and still fail to read one
    card's count. That position is explicitly unknown, not unseen: the row
    arrived whole, so the other five are safe to keep and the unknown one goes
    to manual review.
    """
    draft = _partial_scan_draft(accepted_rows=(1, 2))
    uncertain = cards.CARDS[3].id
    draft["card_states"].pop(uncertain)
    draft["card_confidences"].pop(uncertain)
    draft["unknown_card_ids"] = [uncertain]
    draft["manual_required_card_ids"] = [
        uncertain, *draft["manual_required_card_ids"],
    ]

    assert cards_command._scan_draft_partially_savable(draft) is True

    document = {
        "_id": "#ME",
        "inventory_revision": 0,
        "cards": {card.id: cards.MISSING for card in cards.CARDS},
    }
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()
    updated = asyncio.run(cards_command._write_scan_partial(
        mongo, _scan_account(), draft,
        expected_revision=0, discord_id=123, guild_id=1,
    ))

    assert updated["cards"][cards.CARDS[2].id] == cards.OWNED
    # The unread count keeps whatever the collection already said.
    assert updated["cards"][uncertain] == cards.MISSING


def test_the_adapter_refuses_an_accepted_row_that_did_not_arrive_whole():
    """Layer one: normalization will not publish an inconsistent claim."""
    draft = cards_command._normalize_collection_scan(
        {
            "cards": {
                card.id: {"state": cards.OWNED, "confidence": 0.95}
                for card in cards.CARDS[:5]
            },
            "unseen_card_ids": [card.id for card in cards.CARDS[5:]],
            "accepted_global_rows": [1],
            "missing_global_rows": list(range(2, 11)),
            "identity_bound": True,
        },
        capture_count=1,
    )

    assert draft["identity_bound"] is False
    assert draft["coverage_complete"] is False
    assert draft["accepted_global_rows"] == []
    assert cards_command._scan_draft_partially_savable(draft) is False
    assert cards_command._scan_draft_confirmable(draft) is False


def test_the_write_refuses_an_incomplete_accepted_row_on_its_own(monkeypatch):
    """Layer three: the write boundary does not delegate its own safety."""
    draft = _sparse_partial_draft((0, 1, 2, 3, 4))
    monkeypatch.setattr(
        cards_command, "_scan_draft_partially_savable", lambda _draft: True
    )
    document = {"_id": "#ME", "inventory_revision": 0, "cards": {}}
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()

    with pytest.raises(ValueError):
        asyncio.run(cards_command._write_scan_partial(
            mongo, _scan_account(), draft,
            expected_revision=0, discord_id=123, guild_id=1,
        ))
    assert document["cards"] == {}


def test_the_write_refuses_a_state_outside_an_accepted_row_on_its_own(
    monkeypatch,
):
    draft = _partial_scan_draft(accepted_rows=(1,))
    stowaway = cards.CARDS[7].id
    draft["card_states"][stowaway] = cards.DUPLICATE
    draft["card_confidences"][stowaway] = 0.99
    draft["unseen_card_ids"] = [
        card_id for card_id in draft["unseen_card_ids"] if card_id != stowaway
    ]
    monkeypatch.setattr(
        cards_command, "_scan_draft_partially_savable", lambda _draft: True
    )
    document = {"_id": "#ME", "inventory_revision": 0, "cards": {}}
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()

    with pytest.raises(ValueError):
        asyncio.run(cards_command._write_scan_partial(
            mongo, _scan_account(), draft,
            expected_revision=0, discord_id=123, guild_id=1,
        ))
    assert document["cards"] == {}


# --- readiness cannot survive a half answered category ----------------------


def _partial_write(draft, document):
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()
    return asyncio.run(cards_command._write_scan_partial(
        mongo,
        _scan_account(),
        draft,
        expected_revision=int(document.get("inventory_revision", 0)),
        discord_id=123,
        guild_id=1,
    ))


def _ready_inventory(**overrides):
    document = {
        "_id": "#ME",
        "inventory_revision": 2,
        "cards": {card.id: cards.OWNED for card in cards.CARDS},
        "complete_categories": [category.id for category in cards.CATEGORIES],
        "reviewed_lists": sorted(
            f"{category.id}:{mode}"
            for category in cards.CATEGORIES
            for mode in ("missing", "duplicates")
        ),
        "confirmed_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }
    document.update(overrides)
    return document


def test_a_partial_scan_cannot_preserve_readiness_for_a_half_answered_category():
    # Rows 1 and 2 are elixir; elixir also owns cards in rows 3 and 4, which
    # this scan could not read.
    updated = _partial_write(
        _partial_scan_draft(accepted_rows=(1, 2)), _ready_inventory()
    )

    assert "elixir" not in updated["complete_categories"]
    assert "elixir:missing" not in updated["reviewed_lists"]
    assert "elixir:duplicates" not in updated["reviewed_lists"]


def test_a_partial_scan_keeps_readiness_for_a_category_it_fully_answered():
    # Rows 1 to 4 cover every elixir card and the first dark elixir cards.
    updated = _partial_write(
        _partial_scan_draft(accepted_rows=(1, 2, 3, 4)), _ready_inventory()
    )

    assert "elixir" in updated["complete_categories"]
    assert "elixir:missing" in updated["reviewed_lists"]
    # Dark elixir was written into and still has cards needing review.
    assert "dark_elixir" not in updated["complete_categories"]
    assert "dark_elixir:missing" not in updated["reviewed_lists"]


def test_a_collection_wide_partial_scan_untrusts_every_unread_card():
    updated = _partial_write(
        _partial_scan_draft(accepted_rows=(9, 10)), _ready_inventory()
    )

    assert updated["complete_categories"] == []
    assert updated["reviewed_lists"] == []
    assert set(updated["trusted_card_ids"]) == {
        card.id for card in cards.CARDS[48:60]
    }


def test_a_partial_scan_cannot_make_a_player_matchable_on_an_unread_category():
    """The end the invalidation exists for, checked through the domain rules.

    `_matchable` falls back to `updated_at`, which this write refreshes, so
    without the invalidation an inventory with no confirmation date at all
    would become matchable the moment a partial scan saved.
    """
    document = _ready_inventory(
        cards={card.id: cards.MISSING for card in cards.CARDS},
        complete_categories=["elixir"],
        reviewed_lists=["elixir:missing", "elixir:duplicates"],
    )
    document.pop("confirmed_at")
    wanted = cards.CARDS[12].id            # elixir, row 3, not scanned
    partner = {
        "_id": "#YOU",
        "player_name": "Partner",
        "cards": {card.id: cards.OWNED for card in cards.CARDS}
        | {wanted: cards.DUPLICATE, cards.CARDS[0].id: cards.MISSING},
        "complete_categories": ["elixir"],
        "confirmed_at": datetime.now(timezone.utc),
    }

    updated = _partial_write(_partial_scan_draft(accepted_rows=(1, 2)), document)

    # The write did refresh updated_at, so the collection is "matchable" in the
    # age sense - and still matches nothing, because elixir is no longer ready.
    assert cards.inventory_is_matchable(updated) is True
    assert cards.find_matches(updated, [partner]) == []
    assert cards.family_supply([updated])[wanted].seekers == ()
    # Proof that readiness was the only thing standing in the way.
    would_have_matched = dict(updated, complete_categories=["elixir"])
    assert cards.find_matches(would_have_matched, [partner])


def test_manual_counts_restore_readiness_after_a_partial_scan_without_ready_tap():
    document = _ready_inventory(
        cards={card.id: cards.MISSING for card in cards.CARDS},
    )
    mongo = SimpleNamespace(card_inventories=_FakeCategoryCollection(document))
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_scan_partial(
        mongo,
        _scan_account(),
        _partial_scan_draft(accepted_rows=(1, 2)),
        expected_revision=2,
        discord_id=123,
        guild_id=1,
    ))
    assert "elixir" not in updated["complete_categories"]

    remaining = [
        card.id
        for card in cards.CATEGORY_CARDS["elixir"]
        if card.id not in cards_command._trusted_card_ids(updated)
    ]
    assert remaining
    restored = updated
    for index, card_id in enumerate(remaining):
        restored = asyncio.run(cards_command._write_card_state(
            mongo,
            _scan_account(),
            restored,
            card_id,
            restored["cards"][card_id],
            expected_revision=cards_command._inventory_revision_value(restored),
            discord_id=123,
            guild_id=1,
        ))
        if index < len(remaining) - 1:
            assert "elixir" not in restored["complete_categories"]

    assert "elixir" in restored["complete_categories"]
    assert {"elixir:missing", "elixir:duplicates"} <= set(
        restored["reviewed_lists"]
    )
    assert restored["confirmed_at"] is not None
    assert cards.inventory_is_matchable(restored) is True


# --- a scan session must be resolvable where it is created ------------------


class _UploadSessionStore:
    """Just enough component_state to prove a session can be looked up.

    Scalar equality only: the TTL clause is not what these tests are about.
    """

    def __init__(self):
        self.documents: list[dict] = []

    async def delete_many(self, query):
        self.documents = [
            document for document in self.documents
            if not all(
                document.get(key) == value for key, value in query.items()
            )
        ]

    async def find_one(self, query, sort=None):
        for document in self.documents:
            if all(
                document.get(key) == value
                for key, value in query.items()
                if not isinstance(value, dict)
            ):
                return document
        return None


def _scan_start_harness(monkeypatch, *, guild_id, sessions=None):
    account = _scan_account()
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 9
    calls = {"load_target": 0, "inserted": [], "ensured": []}
    store = sessions if sessions is not None else _UploadSessionStore()

    async def load_target(*_args, **_kwargs):
        calls["load_target"] += 1
        return account, inventory, None

    async def ensure_inventory(_mongo, _account, *, discord_id, guild_id):
        calls["ensured"].append(guild_id)
        return inventory

    async def insert_state(_mongo, document, *, ttl):
        calls["inserted"].append(document)
        store.documents.append(document)

    async def update_state(_mongo, _query, _update, **_kwargs):
        return SimpleNamespace(matched_count=1)

    async def send(_bot, _channel_id, _components):
        return SimpleNamespace(id=888)

    class Rest:
        async def create_dm_channel(self, user_id):
            return SimpleNamespace(id=777)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_ensure_inventory", ensure_inventory)
    monkeypatch.setattr(cards_command, "insert_state", insert_state)
    monkeypatch.setattr(cards_command, "update_state", update_state)
    monkeypatch.setattr(cards_command, "_send_scan_dm_components", send)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=guild_id)
    mongo = SimpleNamespace(component_state=store)
    bot = SimpleNamespace(rest=Rest())
    view = asyncio.run(cards_command.cards_scan_start(
        ctx, "#ME", coc_client=SimpleNamespace(), mongo=mongo, bot=bot,
    ))
    return view, calls, store


def test_a_scan_started_in_the_configured_server_creates_a_valid_session(
    monkeypatch,
):
    view, calls, store = _scan_start_harness(monkeypatch, guild_id=1)

    assert len(calls["inserted"]) == 1
    assert calls["inserted"][0]["guild_id"] == 1
    assert "Private upload ready" in _view_text(view)

    found = asyncio.run(cards_command._find_card_upload_state(
        SimpleNamespace(component_state=store), 123
    ))
    assert found is not None
    assert found["_id"] == calls["inserted"][0]["_id"]


def test_a_scan_cannot_start_outside_the_configured_family_server(monkeypatch):
    """The bug: the session stored the wrong guild and nothing could find it."""
    view, calls, store = _scan_start_harness(monkeypatch, guild_id=999)

    assert calls["inserted"] == []
    assert store.documents == []
    # Nothing was loaded, so nothing rescoped the inventory on the way in.
    assert calls["load_target"] == 0
    assert calls["ensured"] == []
    text = _view_text(view)
    assert "Scanning only works in the family server" in text
    assert "Nothing was changed here." in text


def test_a_scan_started_from_a_dm_binds_to_the_configured_family(monkeypatch):
    view, calls, store = _scan_start_harness(monkeypatch, guild_id=None)

    assert calls["inserted"][0]["guild_id"] == 1
    assert asyncio.run(cards_command._find_card_upload_state(
        SimpleNamespace(component_state=store), 123
    )) is not None
    assert "Private upload ready" in _view_text(view)


def test_a_valid_session_survives_its_own_ownership_recheck(monkeypatch):
    _view, calls, _store = _scan_start_harness(monkeypatch, guild_id=1)
    document = calls["inserted"][0]
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    assert cards_command._scan_session_problem(
        ctx, document["user_id"], document["guild_id"]
    ) is None
    # And the same session cannot be driven from another server.
    elsewhere = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=999)
    assert cards_command._scan_session_problem(
        elsewhere, document["user_id"], document["guild_id"]
    ) is not None


def test_the_scan_session_never_rescopes_the_inventory_guild(monkeypatch):
    """A scan may only ever bind a collection to the configured family."""
    _view, calls, _store = _scan_start_harness(monkeypatch, guild_id=1)

    assert calls["inserted"][0]["guild_id"] == cards_command.CARDS_GUILD_ID
    assert all(
        guild_id == cards_command.CARDS_GUILD_ID for guild_id in calls["ensured"]
    )


# --- a card may not be classified two ways at once --------------------------


def _row_scanner_result(*, accepted_rows, uncertain=(), extra_unseen=()):
    """A scanner result shaped the way `utils/card_scan.py` really shapes one.

    An unseen position has no state, so the scanner reports it as unknown as
    well: on a real partial scan the two lists genuinely overlap. This fixture
    reproduces that rather than an idealised disjoint version, so the tests run
    against what production actually receives.
    """
    accepted_ids = [
        card.id
        for row in accepted_rows
        for card in cards.CARDS[(row - 1) * 6:row * 6]
    ]
    stated = [card_id for card_id in accepted_ids if card_id not in uncertain]
    unseen = [
        card.id for card in cards.CARDS if card.id not in accepted_ids
    ]
    unseen.extend(extra_unseen)
    return {
        "cards": {
            card_id: {"state": cards.OWNED, "confidence": 0.95}
            for card_id in stated
        },
        "unknown_card_ids": [*uncertain, *unseen],
        "unseen_card_ids": unseen,
        "accepted_global_rows": list(accepted_rows),
        "missing_global_rows": [
            row for row in range(1, 11) if row not in accepted_rows
        ],
        "identity_bound": True,
    }


def _normalized_row_scan(**kwargs):
    return cards_command._normalize_collection_scan(
        _row_scanner_result(**kwargs), capture_count=5
    )


def _attempt_partial_write(draft):
    """Run the real writer and report whether anything reached the document."""
    document = {
        "_id": "#ME",
        "inventory_revision": 0,
        "cards": {card.id: cards.MISSING for card in cards.CARDS},
    }
    mongo = SimpleNamespace(
        card_inventories=_FakeInventoryCollection([document])
    )
    cards_command._inventory_locks.clear()
    try:
        return cards_command._inventory_revision_value(
            asyncio.run(cards_command._write_scan_partial(
                mongo, _scan_account(), draft,
                expected_revision=0, discord_id=123, guild_id=1,
            ))
        ), document
    except ValueError as error:
        return error, document


def test_normalization_turns_the_scanner_classifications_into_a_partition():
    """The overlap is real and legitimate; leaving it in place is not.

    Unseen is the stronger claim, so it wins. Without this an accepted row
    could look complete through an "unknown" card that was in fact never
    observed, which is the bypass this pins shut.
    """
    draft = _normalized_row_scan(accepted_rows=(1, 2), uncertain=())
    unknown = set(draft["unknown_card_ids"])
    unseen = set(draft["unseen_card_ids"])
    stated = set(draft["card_states"])

    assert unknown & unseen == set()
    assert stated & (unknown | unseen) == set()
    assert stated | unknown | unseen == set(cards.CARD_BY_ID)
    # Nothing was lost: everything the scanner could not answer for is still
    # manual-required.
    assert set(cards_command._scan_manual_required_ids(draft)) == unknown | unseen


def test_an_accepted_row_card_called_both_unknown_and_unseen_is_rejected():
    """Codex's bypass: five states rode along behind a contradictory sixth."""
    sixth = cards.CARDS[5].id
    draft = _normalized_row_scan(
        accepted_rows=(1, 2), uncertain=(sixth,), extra_unseen=(sixth,)
    )

    # 1. normalization refuses to publish the accepted-row identity
    assert draft["identity_bound"] is False
    assert draft["accepted_global_rows"] == []
    assert draft["coverage_complete"] is False
    # 2. the partial-save gate refuses
    assert cards_command._scan_draft_partially_savable(draft) is False
    assert cards_command._scan_draft_confirmable(draft) is False
    # 3. and nothing reaches the collection
    outcome, document = _attempt_partial_write(draft)
    assert isinstance(outcome, ValueError)
    assert all(state == cards.MISSING for state in document["cards"].values())


def test_the_writer_refuses_the_contradiction_even_with_the_gate_stubbed(
    monkeypatch,
):
    """The writer does not lean on any earlier layer having looked."""
    sixth = cards.CARDS[5].id
    draft = _normalized_row_scan(accepted_rows=(1, 2), uncertain=(sixth,))
    # Reintroduce the contradiction after normalization tidied it away, then
    # bypass every gate in front of the writer.
    draft["unseen_card_ids"] = [sixth, *draft["unseen_card_ids"]]
    monkeypatch.setattr(
        cards_command, "_scan_draft_partially_savable", lambda _draft: True
    )

    outcome, document = _attempt_partial_write(draft)

    assert isinstance(outcome, ValueError)
    assert "both unknown and unseen" in str(outcome)
    assert all(state == cards.MISSING for state in document["cards"].values())


def test_an_accepted_row_card_with_a_state_and_unseen_is_rejected(monkeypatch):
    first = cards.CARDS[0].id
    draft = _normalized_row_scan(accepted_rows=(1, 2), extra_unseen=(first,))

    assert draft["identity_bound"] is False
    assert draft["accepted_global_rows"] == []
    assert cards_command._scan_draft_partially_savable(draft) is False

    # And again straight at the writer, with the state membership forced back.
    forced = _normalized_row_scan(accepted_rows=(1, 2))
    forced["unseen_card_ids"] = [first, *forced["unseen_card_ids"]]
    monkeypatch.setattr(
        cards_command, "_scan_draft_partially_savable", lambda _draft: True
    )
    outcome, document = _attempt_partial_write(forced)
    assert isinstance(outcome, ValueError)
    assert "contradicts its own card states" in str(outcome)
    assert all(state == cards.MISSING for state in document["cards"].values())


def test_five_states_and_one_clean_unknown_still_save_the_five():
    """The valid UNKNOWN semantics survive the fix."""
    sixth = cards.CARDS[5].id
    draft = _normalized_row_scan(accepted_rows=(1, 2), uncertain=(sixth,))

    assert draft["identity_bound"] is True
    assert draft["accepted_global_rows"] == [1, 2]
    assert sixth in draft["unknown_card_ids"]
    assert sixth not in draft["unseen_card_ids"]
    assert cards_command._scan_draft_partially_savable(draft) is True

    outcome, document = _attempt_partial_write(draft)

    assert not isinstance(outcome, ValueError)
    written = [
        card.id for card in cards.CARDS
        if document["cards"][card.id] == cards.OWNED
    ]
    assert len(written) == 11
    assert sixth not in written
    assert sixth in cards_command._scan_manual_required_ids(draft)


def test_a_whole_six_state_accepted_row_still_saves():
    draft = _normalized_row_scan(accepted_rows=(1, 2))

    assert cards_command._scan_draft_partially_savable(draft) is True

    outcome, document = _attempt_partial_write(draft)

    assert not isinstance(outcome, ValueError)
    assert sum(
        document["cards"][card.id] == cards.OWNED for card in cards.CARDS
    ) == 12


def test_unseen_cards_from_rejected_rows_stay_ordinary_manual_work():
    """Rejected rows are unresolved data, not a contradiction."""
    draft = _normalized_row_scan(accepted_rows=(1, 2))
    rejected_ids = [card.id for card in cards.CARDS[12:]]

    assert set(draft["unseen_card_ids"]) == set(rejected_ids)
    assert set(draft["unknown_card_ids"]) == set()
    assert set(cards_command._scan_manual_required_ids(draft)) == set(rejected_ids)
    assert draft["manual_required_global_rows"] == list(range(3, 11))
    assert cards_command._scan_draft_partially_savable(draft) is True

    text = _view_text(cards_command._scan_review(
        _scan_account(), {"_id": "#ME"}, "draft-rejected-rows", draft
    ))
    assert "Still to check: 48 cards" in text
    assert "Rows 3–10" in text


# --- 2026-08-14 bug-pass regressions ----------------------------------------


def _gate_account():
    return Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )


class _PendingSwapTrades:
    """card_trades holding one live swap awaiting #ME's answer."""

    def __init__(self):
        self.trade = dict(_agreed_trade(), accepted_at=datetime.now(timezone.utc))

    def find(self, _query):
        rows = [dict(self.trade)]

        class Cursor:
            def sort(self, *_a, **_k):
                return self

            async def to_list(self, length=None):
                return rows

        return Cursor()


def test_not_yet_bypasses_the_swap_gate_for_one_render(monkeypatch):
    """"Not yet" must reach the collection, not re-render the question.

    The gate re-finds the same unanswered swap on every dashboard render, so
    without the one-render bypass the button that promises "asks again next
    time" asked again immediately and trapped the player.
    """
    sentinel = ["DASHBOARD"]
    monkeypatch.setattr(
        cards_command, "_dashboard", lambda *_a, **_k: sentinel
    )

    async def fake_board(*_a, **_k):
        return None

    monkeypatch.setattr(
        cards_command, "_render_inventory_board_async", fake_board
    )
    mongo = SimpleNamespace(card_trades=_PendingSwapTrades())
    inventory = {"_id": "#ME"}

    gated = asyncio.run(cards_command._dashboard_view(
        _gate_account(), inventory, account_count=1, mongo=mongo, guild_id=1,
    ))
    ids = [str(n.get("custom_id", "")) for n in _view_nodes(gated)]
    assert any(cid.startswith("cards_swap_sent:") for cid in ids), (
        "without the bypass the swap question renders"
    )

    passed = asyncio.run(cards_command._dashboard_view(
        _gate_account(), inventory, account_count=1, mongo=mongo, guild_id=1,
        skip_swap_gate=True,
    ))
    assert passed is sentinel, "the bypass shows the board exactly once"


def test_not_now_on_the_paused_screen_reaches_the_board(monkeypatch):
    """The paused screen's Not now carries |paused; the handler must honor it.

    It parsed the suffix off and re-rendered the paused screen, so the only
    working exit was turning trading back on.
    """
    sentinel = ["DASHBOARD"]
    monkeypatch.setattr(
        cards_command, "_dashboard", lambda *_a, **_k: sentinel
    )

    async def fake_board(*_a, **_k):
        return None

    monkeypatch.setattr(
        cards_command, "_render_inventory_board_async", fake_board
    )
    account = _gate_account()
    paused = {"_id": "#ME", "trading_paused": True}
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, paused)
    )

    async def fake_accounts(*_a, **_k):
        return _scan_accounts_data(account)

    monkeypatch.setattr(cards_command, "load_accounts", fake_accounts)

    class NoSwaps:
        def find(self, _query):
            class Cursor:
                def sort(self, *_a, **_k):
                    return self

                async def to_list(self, length=None):
                    return []

            return Cursor()

    mongo = SimpleNamespace(card_trades=NoSwaps())
    ctx = _quantity_ctx()

    still_gated = asyncio.run(cards_command.cards_dashboard(
        ctx, "#ME", coc_client=SimpleNamespace(), mongo=mongo,
        bot=SimpleNamespace(),
    ))
    labels = _view_labels(still_gated)
    assert "Not now" in labels, "a plain open still shows the paused screen"

    passed = asyncio.run(cards_command.cards_dashboard(
        ctx, "#ME|paused", coc_client=SimpleNamespace(), mongo=mongo,
        bot=SimpleNamespace(),
    ))
    assert passed is sentinel, "|paused passes the gate for one render"


class _PanelModalCtx(_SubmitCtx):
    """A modal submit that arrived from a component-launched modal."""

    def __init__(self, raw, sink):
        super().__init__(raw, sink)
        self.deferred = []
        self.responses = []
        self.interaction.message = SimpleNamespace(id=42)
        self.interaction.create_initial_response = self._initial

    async def defer(self, *_args, **_kwargs):
        self.deferred.append(True)
        return None

    async def _initial(self, response_type, **_kwargs):
        self.responses.append(response_type)


def test_set_number_updates_the_panel_instead_of_sending_a_second_one(monkeypatch):
    """The modal answer must edit the panel the modal came from.

    ModalContext.defer can only DEFERRED_MESSAGE_CREATE, which answers with a
    brand-new message; in a DM every Set number added another Update
    collection panel under the old one, and the old one kept the stale count.
    """
    account = _gate_account()
    document, mongo = _quantity_env()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    target = cards.CATEGORY_CARDS["elixir"][5]
    sent = {}
    ctx = _PanelModalCtx("7", sent)

    asyncio.run(cards_command.cards_qnum_submit(
        ctx, f"#ME|{target.id}",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))

    assert ctx.responses == [hikari.ResponseType.DEFERRED_MESSAGE_UPDATE]
    assert ctx.deferred == [], "a create-defer would add a second message"
    assert document["cards"][target.id] == 7
    assert f"{target.name}** · `7`" in _view_text(sent["view"])

    # The focused-card twin shares the fix.
    focus_sent = {}
    focus_ctx = _PanelModalCtx("5", focus_sent)
    asyncio.run(cards_command.cards_count_submit(
        focus_ctx, f"#ME|{target.id}",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))
    assert focus_ctx.responses == [hikari.ResponseType.DEFERRED_MESSAGE_UPDATE]
    assert focus_ctx.deferred == []


def test_a_scanner_two_plus_offers_set_to_2_in_the_quantity_editor(monkeypatch):
    """Confirming "exactly 2" must be one tap, not a workaround through 3.

    The write layer always confirmed an explicit member write, but the
    category screen offered no direct control, so members stepped 2+ -> 3 ->
    2 to make the plus go away.
    """
    account = _gate_account()
    document, mongo = _quantity_env({"wizard": cards.DUPLICATE})
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    view = cards_command._quantity_editor(
        account, document, "elixir", card_id="wizard"
    )
    ids = [str(n.get("custom_id", "")) for n in _view_nodes(view)]
    assert "cards_qset:#ME|wizard|2" in ids
    assert "`2+`" in _view_text(view)

    result = _run_rendered(
        "cards_qset:#ME|wizard|2", mongo=mongo, coc_client=SimpleNamespace(),
    )

    assert document["cards"]["wizard"] == cards.DUPLICATE
    assert "wizard" in document["count_confirmed_card_ids"]
    text = _view_text(result)
    assert "`2+`" not in text, "the confirmed count drops the plus"
    ids = [str(n.get("custom_id", "")) for n in _view_nodes(result)]
    assert "cards_qset:#ME|wizard|2" not in ids, (
        "the confirm control disappears once there is nothing to confirm"
    )


def test_writing_the_same_number_still_confirms_the_count(monkeypatch):
    """Set number = 2 on a stored 2 must confirm, not skip as a no-op."""
    account = _gate_account()
    document, mongo = _quantity_env({"wizard": cards.DUPLICATE})
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_card_state(
        mongo, account, document, "wizard", cards.DUPLICATE,
        expected_revision=0, discord_id=123, guild_id=1,
    ))

    assert updated["cards"]["wizard"] == cards.DUPLICATE
    assert "wizard" in updated["count_confirmed_card_ids"]


def test_the_receiver_is_credited_even_when_their_fence_is_gone():
    """moved=True must mean both legs, not just the giver's decrement.

    The receiver update was fire-and-forget: a lost receiver fence meant the
    giver lost a copy, the bot said "it is now in your collection", and the
    receiver never got the card.
    """
    trade = _agreed_trade()
    owner = cards_command._reservation_owner(trade)
    given = trade["given_card_id"]
    inventories = _FakeInventoryCollection([
        {"_id": "#ME", "guild_id": 1, "cards": {given: 3},
         "card_trade_reservations": {given: owner}},
        # The receiver's fence is already gone and the card is missing.
        {"_id": "#HOLDER", "guild_id": 1, "cards": {given: cards.MISSING},
         "card_trade_reservations": {}},
    ])
    mongo = SimpleNamespace(card_inventories=inventories)

    moved, remaining = asyncio.run(cards_command._confirm_swap_leg(
        mongo, trade, role="requester", now=datetime.now(timezone.utc)
    ))

    assert moved is True
    assert remaining == 2
    assert inventories.documents["#HOLDER"]["cards"][given] == cards.OWNED


def test_the_receiver_fallback_never_downgrades_a_hand_set_count():
    """If the receiver already recorded copies, the credit must not shrink them."""
    trade = _agreed_trade()
    owner = cards_command._reservation_owner(trade)
    given = trade["given_card_id"]
    inventories = _FakeInventoryCollection([
        {"_id": "#ME", "guild_id": 1, "cards": {given: 3},
         "card_trade_reservations": {given: owner}},
        {"_id": "#HOLDER", "guild_id": 1, "cards": {given: 4},
         "card_trade_reservations": {}},
    ])
    mongo = SimpleNamespace(card_inventories=inventories)

    moved, _remaining = asyncio.run(cards_command._confirm_swap_leg(
        mongo, trade, role="requester", now=datetime.now(timezone.utc)
    ))

    assert moved is True
    assert inventories.documents["#HOLDER"]["cards"][given] == 4


def _fully_trusted_swap_inventory(tag, *, owner, given, wanted, values):
    trusted = [card.id for card in cards.CARDS]
    ready = [category.id for category in cards.CATEGORIES]
    return {
        "_id": tag,
        "guild_id": 1,
        "inventory_revision": 0,
        "cards": {card.id: cards.OWNED for card in cards.CARDS} | values,
        "trusted_card_ids": list(trusted),
        "count_confirmed_card_ids": list(trusted),
        "complete_categories": list(ready),
        "reviewed_lists": [
            f"{category_id}:{mode}"
            for category_id in ready
            for mode in ("missing", "duplicates")
        ],
        "card_trade_reservations": {given: owner, wanted: owner},
    }


class _ReceiverCreditFailureInventories(_FakeInventoryCollection):
    """Fail once before the receiver credit while recording cleanup order."""

    def __init__(self, documents, *, giver, receiver, card_id, other_card_id):
        super().__init__(documents)
        self.giver = giver
        self.receiver = receiver
        self.card_id = card_id
        self.other_card_id = other_card_id
        self.failed_credit = False
        self.giver_debits = 0
        self.events = []

    async def update_one(self, query, update, upsert=False):
        receiver_credit = (
            query.get("_id") == self.receiver
            and f"cards.{self.card_id}" in (update.get("$set") or {})
            and bool(query.get("$or"))
        )
        if receiver_credit and not self.failed_credit:
            self.failed_credit = True
            self.events.append("receiver_credit_failed")
            # The exception is injected at the exact blocker boundary: the
            # giver write committed, but the receiver write did not.
            assert self.documents[self.giver]["cards"][self.card_id] == 2
            assert self.card_id not in self.documents[self.giver][
                "card_trade_reservations"
            ]
            assert self.other_card_id in self.documents[self.giver][
                "card_trade_reservations"
            ]
            assert set(self.documents[self.receiver]["card_trade_reservations"]) == {
                self.card_id, self.other_card_id,
            }
            raise RuntimeError("injected receiver write failure")

        result = await super().update_one(query, update, upsert=upsert)
        if not getattr(result, "modified_count", 0):
            return result
        if f"cards.{self.card_id}" in (update.get("$inc") or {}):
            self.giver_debits += 1
            self.events.append("giver_debited")
        elif "trusted_card_ids" in (update.get("$set") or {}):
            self.events.append(f"invalidated:{query['_id']}")
        elif any(
            path.startswith("card_trade_reservations.")
            for path in (update.get("$unset") or {})
        ):
            self.events.append(f"released:{query['_id']}")
        return result


def _review_failure_swap_fixture(*, trade_id="trade-review-failure"):
    trade = _agreed_trade()
    trade.update({
        "_id": trade_id,
        "kind": "trade",
        "backstop_at": datetime.now(timezone.utc) - timedelta(days=1),
    })
    owner = cards_command._reservation_owner(trade)
    given, wanted = trade["given_card_id"], trade["wanted_card_id"]
    inventories = _ReceiverCreditFailureInventories(
        [
            _fully_trusted_swap_inventory(
                "#ME", owner=owner, given=given, wanted=wanted,
                values={given: 3, wanted: cards.MISSING},
            ),
            _fully_trusted_swap_inventory(
                "#HOLDER", owner=owner, given=given, wanted=wanted,
                values={given: cards.MISSING, wanted: 3},
            ),
        ],
        giver="#ME",
        receiver="#HOLDER",
        card_id=given,
        other_card_id=wanted,
    )
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = dict(trade)
    return trade, SimpleNamespace(
        card_trades=trades,
        card_inventories=inventories,
    )


def test_receiver_exception_enters_durable_review_without_a_second_debit():
    """The one-sided write blocker is fenced, auditable, and fail closed."""
    from extensions.tasks import cards_deadlines as sweeper

    trade, mongo = _review_failure_swap_fixture()
    given, wanted = trade["given_card_id"], trade["wanted_card_id"]

    with pytest.raises(cards_command._SwapLegNeedsReview) as raised:
        asyncio.run(cards_command._run_swap_leg_confirmation(
            mongo,
            trade,
            role="requester",
            now=datetime.now(timezone.utc),
            record_no_spare=False,
        ))

    saved = mongo.card_trades.docs[trade["_id"]]
    assert raised.value.trade["status"] == "needs_review"
    assert saved["status"] == "needs_review"
    assert saved["failure"].startswith("swap_leg_partial_failure:")
    assert saved["swap_leg_progress"]["role"] == "requester"
    assert saved["swap_leg_progress"]["card_id"] == given
    assert saved["swap_leg_progress"]["phase"] == "receiver_credit_unknown"
    assert saved["swap_leg_progress"]["giver_debited"] is True
    assert saved["swap_leg_progress"]["receiver_credit"] == "unknown"
    assert "requester_confirmed_at" not in saved

    requester = mongo.card_inventories.documents["#ME"]
    holder = mongo.card_inventories.documents["#HOLDER"]
    assert requester["cards"][given] == 2
    assert holder["cards"][given] == cards.MISSING, (
        "an exception before the receiver write must not invent a credit"
    )
    assert mongo.card_inventories.giver_debits == 1

    for inventory in (requester, holder):
        assert {given, wanted}.isdisjoint(inventory["trusted_card_ids"])
        assert {given, wanted}.isdisjoint(inventory["count_confirmed_card_ids"])
        assert "elixir" not in inventory["complete_categories"]
        assert not any(
            marker.startswith("elixir:")
            for marker in inventory["reviewed_lists"]
        )
        assert inventory["card_trade_reservations"] == {}
        assert trade["_id"] in inventory["card_trade_review_invalidations"]

    invalidations = [
        index for index, event in enumerate(mongo.card_inventories.events)
        if event.startswith("invalidated:")
    ]
    releases = [
        index for index, event in enumerate(mongo.card_inventories.events)
        if event.startswith("released:")
    ]
    assert len(invalidations) == 2
    assert releases and min(releases) > max(invalidations), (
        "remaining reservation fences must stay until both inventories fail closed"
    )

    # A replay holding the original live document cannot claim again after the
    # durable needs_review transition, so the giver is never debited twice.
    outcome, _remaining, replayed = asyncio.run(
        cards_command._run_swap_leg_confirmation(
            mongo,
            trade,
            role="requester",
            now=datetime.now(timezone.utc),
            record_no_spare=False,
        )
    )
    assert outcome == "changed"
    assert replayed["status"] == "needs_review"
    assert requester["cards"][given] == 2
    assert mongo.card_inventories.giver_debits == 1

    # Even with an overdue backstop, ordinary expiry only selects live states.
    closed = asyncio.run(sweeper._close_abandoned_swaps(
        mongo, SimpleNamespace(), now=datetime.now(timezone.utc)
    ))
    assert closed == 0
    assert saved["status"] == "needs_review"


def test_expired_claimed_swap_leg_recovers_to_review_not_ordinary_expiry():
    """A worker restart cannot strand or normally expire an unknown write."""
    from extensions.tasks import cards_deadlines as sweeper

    trade, mongo = _review_failure_swap_fixture(
        trade_id="trade-expired-swap-leg"
    )
    now = datetime.now(timezone.utc)
    trade.update({
        "status": "completing",
        "completion_kind": "swap_leg",
        "completion_started_at": now - timedelta(minutes=2),
        "expires_at": now - timedelta(seconds=1),
        "swap_leg_progress": {
            "attempt_nonce": "durable-attempt",
            "role": "requester",
            "card_id": trade["given_card_id"],
            "giver_tag": "#ME",
            "receiver_tag": "#HOLDER",
            "previous_status": "ready",
            "phase": "inventory_update_started",
            "started_at": now - timedelta(minutes=2),
        },
    })
    mongo.card_trades.docs[trade["_id"]] = dict(trade)

    recovered = asyncio.run(sweeper._recover_interrupted_completions(
        mongo, None, now=now
    ))

    saved = mongo.card_trades.docs[trade["_id"]]
    assert recovered == 1
    assert saved["status"] == "needs_review"
    assert saved["failure"] == "completion_expired"
    assert saved["swap_leg_progress"]["attempt_nonce"] == "durable-attempt"
    assert saved["swap_leg_progress"]["phase"] == "inventory_update_started"
    for inventory in mongo.card_inventories.documents.values():
        assert {
            trade["wanted_card_id"], trade["given_card_id"],
        }.isdisjoint(inventory["trusted_card_ids"])
        assert inventory["card_trade_reservations"] == {}

    closed = asyncio.run(sweeper._close_abandoned_swaps(
        mongo, SimpleNamespace(), now=now + timedelta(days=30)
    ))
    assert closed == 0
    assert saved["status"] == "needs_review"


def test_confirming_a_cancelled_swap_does_not_stamp_it(monkeypatch):
    """A confirm racing a cancel must not mark a closed trade confirmed."""
    trade = dict(_agreed_trade(), status="cancelled")
    document = dict(trade)

    class Trades:
        async def update_one(self, query, update):
            if not _matches_query(document, query):
                return SimpleNamespace(matched_count=0, modified_count=0)
            _apply_update(document, update)
            return SimpleNamespace(matched_count=1, modified_count=1)

    mongo = SimpleNamespace(card_trades=Trades())
    asyncio.run(cards_command._record_swap_confirmation(
        mongo, trade, role="requester", now=datetime.now(timezone.utc)
    ))

    assert "requester_confirmed_at" not in document
    assert document["status"] == "cancelled"


def test_i_sent_it_rechecks_that_the_account_is_still_yours(monkeypatch):
    """The one mutating swap handler must revalidate live ownership."""
    trade = _agreed_trade()

    class Trades:
        async def find_one(self, _query):
            return dict(trade)

    problem = ["NOT-YOURS"]

    async def refuse_target(*_a, **_k):
        return None, None, problem

    monkeypatch.setattr(cards_command, "_load_target", refuse_target)

    def explode(*_a, **_k):
        raise AssertionError("no inventory may move without ownership")

    monkeypatch.setattr(cards_command, "_confirm_swap_leg", explode)
    ctx = _quantity_ctx(user_id=111)

    result = asyncio.run(cards_command.cards_swap_sent(
        ctx, trade["_id"],
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(card_trades=Trades()),
        bot=SimpleNamespace(),
    ))

    assert result is problem


def test_cancelling_after_one_leg_moved_tells_the_truth():
    """"No tracked inventory changed" is false once one card moved."""
    trade = _agreed_trade()
    assert cards_command._swap_cancel_note(trade, "requester") == (
        "No tracked inventory changed."
    )

    trade["requester_confirmed_at"] = datetime.now(timezone.utc)
    mine = cards_command._swap_cancel_note(trade, "requester")
    theirs = cards_command._swap_cancel_note(trade, "holder")
    assert "stays removed from your collection" in mine
    assert "was not added" in mine
    assert "stays in your collection" in theirs
    assert "Your card was not removed" in theirs
    assert "No tracked inventory changed" not in mine
    assert "No tracked inventory changed" not in theirs

    # The "It was cancelled" question screen stops claiming both cards free.
    view = cards_command._swap_cancel_check_view(trade, role="holder")
    text = _view_text(view)
    assert "frees both cards" not in text
    assert "stays in your collection" in text


def test_a_gem_answer_cannot_flip_or_be_replayed(monkeypatch):
    """The first answer wins; stale buttons and strangers change nothing."""
    ask = {
        "_id": "gem:#ME:#H:balloon", "kind": "gem_ask", "status": "pending",
        "card_id": "balloon", "gem_cost": 50,
        "asker_name": "Asker", "asker_discord_id": 111,
        "holder_name": "Holder", "holder_discord_id": 222,
        "generation": 1000,
    }
    document = dict(ask)
    mongo = SimpleNamespace(card_trades=_FakeCategoryCollection(document))
    dms = []

    async def fake_dm(_bot, recipient_id, _components, **_kwargs):
        dms.append(recipient_id)
        return True

    monkeypatch.setattr(cards_command, "_send_trade_dm", fake_dm)

    # A stranger cannot answer at all.
    stranger = _quantity_ctx(user_id=999)
    refused = asyncio.run(cards_command._answer_gem_ask(
        stranger, mongo, SimpleNamespace(), ask["_id"], agreed=True
    ))
    assert "not yours" in _view_text(refused)
    assert document["status"] == "pending" and dms == []

    # A button from an older generation of the same ask is out of date.
    holder = _quantity_ctx(user_id=222)
    stale = asyncio.run(cards_command._answer_gem_ask(
        holder, mongo, SimpleNamespace(), f"{ask['_id']}|999", agreed=True
    ))
    assert "no longer open" in _view_text(stale)
    assert document["status"] == "pending" and dms == []

    # The real answer lands once.
    first = asyncio.run(cards_command._answer_gem_ask(
        holder, mongo, SimpleNamespace(), f"{ask['_id']}|1000", agreed=True
    ))
    assert "Thanks for helping" in _view_text(first)
    assert document["status"] == "accepted"
    assert dms == [111]

    # Pressing No afterwards must not flip the recorded answer.
    second = asyncio.run(cards_command._answer_gem_ask(
        holder, mongo, SimpleNamespace(), f"{ask['_id']}|1000", agreed=False
    ))
    assert "Already answered" in _view_text(second)
    assert document["status"] == "accepted"
    assert dms == [111], "no second DM after a refused replay"


def test_a_failed_answer_dm_is_not_reported_as_delivered(monkeypatch):
    ask = {
        "_id": "gem:#ME:#H:balloon", "kind": "gem_ask", "status": "pending",
        "card_id": "balloon", "gem_cost": 50,
        "asker_name": "Asker", "asker_discord_id": 111,
        "holder_name": "Holder", "holder_discord_id": 222,
    }
    mongo = SimpleNamespace(card_trades=_FakeCategoryCollection(dict(ask)))

    async def failing_dm(*_a, **_k):
        return False

    monkeypatch.setattr(cards_command, "_send_trade_dm", failing_dm)
    holder = _quantity_ctx(user_id=222)

    result = asyncio.run(cards_command._answer_gem_ask(
        holder, mongo, SimpleNamespace(), ask["_id"], agreed=False
    ))
    text = _view_text(result)
    assert "could not reach <@111>" in text, "built from the real _Delivery"
    assert "I sent them a DM" not in text


def _posted_gem_ask_env(monkeypatch, **overrides):
    """A pending gem ask whose public post is already up in the channel."""
    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "CARDS_CHANNEL_ID", 999)
    ask = _gem_ask_doc(
        channel_id=999, channel_message_id=555, channel_post_v2=True,
        **overrides,
    )
    trades = _FakeTradeCollection()
    trades.docs[ask["_id"]] = dict(ask)
    rest = _RecordingRest()
    dms = _DmRecorder()
    monkeypatch.setattr(cards_command, "_send_trade_dm", dms)
    return ask, trades, SimpleNamespace(rest=rest), rest, dms


def _public_gem_ctx(user_id, followups):
    class Interaction:
        values = []

        async def execute(self, **kwargs):
            followups.append(kwargs)

    return SimpleNamespace(
        guild_id=1, user=SimpleNamespace(id=user_id),
        interaction=Interaction(),
    )


def test_a_public_gem_yes_closes_the_post_silently_and_dms_the_asker(
    monkeypatch,
):
    """The answer edits the standing post to its terminal form (an edit
    cannot ping), DMs the asker exactly as informatively as before, and
    creates NO new channel message. A raced second answer changes nothing."""
    ask, trades, bot, rest, dms = _posted_gem_ask_env(monkeypatch)
    followups = []
    ctx = _public_gem_ctx(222, followups)

    asyncio.run(cards_command.cards_pub_gem_yes(
        ctx, f"{ask['_id']}|1000",
        mongo=SimpleNamespace(card_trades=trades), bot=bot,
    ))

    assert trades.docs[ask["_id"]]["status"] == "accepted"
    assert rest.messages == [], "no new channel post - answers never ping"
    assert len(rest.edits) == 1
    edited = rest.edits[0]
    assert edited["message"] == 555
    assert edited["user_mentions"] is False, "structurally silent"
    closed_text = _view_text(edited["components"])
    assert "answered — yes" in closed_text
    assert not any(
        "custom_id" in n for n in _view_nodes(edited["components"])
    ), "the terminal post has zero interactive components"
    assert [recipient for recipient, _ in dms.sent] == [111]
    assert "They said yes" in _view_text(dms.sent[0][1])
    assert len(followups) == 1
    assert followups[0]["flags"] & hikari.MessageFlag.EPHEMERAL
    reply_text = _view_text(followups[0]["components"])
    assert "Thanks for helping" in reply_text
    assert "I sent them a DM." in reply_text

    # The CAS refuses a second answer: nothing flips, nothing is re-sent.
    followups.clear()
    asyncio.run(cards_command.cards_pub_gem_no(
        _public_gem_ctx(222, followups), f"{ask['_id']}|1000",
        mongo=SimpleNamespace(card_trades=trades), bot=bot,
    ))
    assert "Already answered" in _view_text(followups[0]["components"])
    assert trades.docs[ask["_id"]]["status"] == "accepted"
    assert len(rest.edits) == 1 and rest.messages == []
    assert [recipient for recipient, _ in dms.sent] == [111]


def test_a_wrong_member_public_gem_answer_changes_nothing_publicly(
    monkeypatch,
):
    """Holder-only, and the refusal goes through the ephemeral followup:
    the public post and the stored ask are untouched."""
    ask, trades, bot, rest, dms = _posted_gem_ask_env(monkeypatch)
    followups = []

    asyncio.run(cards_command.cards_pub_gem_yes(
        _public_gem_ctx(999, followups), f"{ask['_id']}|1000",
        mongo=SimpleNamespace(card_trades=trades), bot=bot,
    ))

    assert len(followups) == 1
    assert followups[0]["flags"] & hikari.MessageFlag.EPHEMERAL
    assert "not yours" in _view_text(followups[0]["components"])
    assert trades.docs[ask["_id"]]["status"] == "pending"
    assert rest.messages == [] and rest.edits == []
    assert dms.sent == []

    # A stale generation from an earlier ask for the same card is refused
    # the same way - the guard carried over from the DM pair unchanged.
    followups.clear()
    asyncio.run(cards_command.cards_pub_gem_yes(
        _public_gem_ctx(222, followups), f"{ask['_id']}|999",
        mongo=SimpleNamespace(card_trades=trades), bot=bot,
    ))
    assert "no longer open" in _view_text(followups[0]["components"])
    assert trades.docs[ask["_id"]]["status"] == "pending"
    assert rest.messages == [] and rest.edits == []
    assert dms.sent == []


def test_a_legacy_dm_gem_answer_also_closes_the_public_post(monkeypatch):
    """cards_gem_yes/no stay registered forever for DMs already sent; they
    route through the same rewired body, so an answer from an old DM edits
    the public post to its terminal form too."""
    ask, trades, bot, rest, dms = _posted_gem_ask_env(monkeypatch)

    result = asyncio.run(cards_command.cards_gem_no(
        _quantity_ctx(user_id=222), f"{ask['_id']}|1000",
        mongo=SimpleNamespace(card_trades=trades), bot=bot,
    ))

    assert "Declined" in _view_text(result)
    assert trades.docs[ask["_id"]]["status"] == "declined"
    assert rest.messages == []
    assert len(rest.edits) == 1
    assert "answered — no" in _view_text(rest.edits[0]["components"])
    assert [recipient for recipient, _ in dms.sent] == [111]
    assert "They said no" in _view_text(dms.sent[0][1])


def test_player_lookup_refuses_when_the_family_boundary_is_unavailable(monkeypatch):
    """cards_browse must fail closed like the candidate search, not widen."""
    account = _gate_account()
    inventory = _complete_inventory()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, inventory),
    )

    class BrokenClans:
        async def distinct(self, _field):
            raise RuntimeError("clans down")

    class Inventories:
        def find(self, _query):
            raise AssertionError("no lookup may run without the family filter")

    mongo = SimpleNamespace(
        clans=BrokenClans(), card_inventories=Inventories(),
    )
    ctx = _quantity_ctx(values=["t:#SOMEBODY"])

    result = asyncio.run(cards_command.cards_browse(
        ctx, "#ME", coc_client=SimpleNamespace(), mongo=mongo,
        bot=SimpleNamespace(),
    ))
    assert "not available right now" in _view_text(result)


def test_the_spares_lookup_hides_categories_not_marked_ready():
    """Supply no trade path would accept must not be advertised."""
    viewer = _complete_inventory()
    holder = {
        "_id": "#H", "player_name": "Holder", "clan_name": "Home Clan",
        "cards": {"wizard": 3, "minion": 2},
        "complete_categories": ["elixir"],
    }
    assert cards.CARD_BY_ID["wizard"].category == "elixir"
    assert cards.CARD_BY_ID["minion"].category == "dark_elixir"

    view = cards_command._player_spares_view(
        "#ME", viewer, [holder], display_name="Holder",
    )
    text = _view_text(view)
    assert "Wizard" in text
    assert "Minion" not in text, "that category was never marked Ready"


def test_a_search_failure_is_not_reported_as_nobody_has_a_spare(monkeypatch):
    account = _gate_account()
    inventory = _complete_inventory()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, inventory),
    )

    class BrokenClans:
        async def distinct(self, _field):
            raise RuntimeError("clans down")

    mongo = SimpleNamespace(clans=BrokenClans())
    ctx = _quantity_ctx()

    result = asyncio.run(cards_command.cards_favours(
        ctx, "#ME", coc_client=SimpleNamespace(), mongo=mongo,
    ))
    text = _view_text(result)
    assert "Search is not available right now" in text
    assert "Nobody" not in text


def test_accept_without_a_chosen_card_shows_the_chooser(monkeypatch):
    """A plain Accept on a multi-card proposal must offer the choice.

    When the proposal DM never arrived, My trades was the only accept path
    and it silently took the default card.
    """
    trade = {
        "_id": "t1", "kind": "trade", "guild_id": 1, "status": "pending",
        "wanted_card_id": "balloon", "given_card_id": "wizard",
        "compatible_card_ids": ["witch", "healer"],
        "requester_tag": "#ME", "requester_name": "Asker",
        "requester_discord_id": 111,
        "holder_tag": "#H", "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_clan_tag": "#A", "holder_clan_tag": "#A",
    }

    class Trades:
        async def find_one(self, _query):
            return dict(trade)

    class Inventories:
        async def find_one(self, _query):
            return _complete_inventory()

    monkeypatch.setattr(cards_command, "_guild_scope_error", lambda _ctx: None)

    async def keep(mongo, t, **_k):
        return t

    monkeypatch.setattr(cards_command, "_expire_trade_if_needed", keep)

    async def actor(*_a, **_k):
        return _gate_account(), _complete_inventory(tag="#H"), None

    monkeypatch.setattr(cards_command, "_load_trade_actor", actor)

    def explode(*_a, **_k):
        raise AssertionError("nothing may reserve before a card is chosen")

    monkeypatch.setattr(cards_command, "_accept_trade_reservation", explode)
    mongo = SimpleNamespace(card_trades=Trades(), card_inventories=Inventories())
    ctx = _quantity_ctx(user_id=222)

    view = asyncio.run(cards_command._perform_trade_accept(
        ctx, "t1", chosen_card_id=None,
        coc_client=SimpleNamespace(), mongo=mongo, bot=SimpleNamespace(),
    ))

    ids = [str(n.get("custom_id", "")) for n in _view_nodes(view)]
    assert "cards_dm_accept:t1" in ids, "the pick-and-accept select renders"
    assert any(cid.startswith("cards_dm_decline:") for cid in ids)


def test_the_accepted_dm_is_self_contained_and_carries_optional_regions():
    trade = {
        "_id": "t1", "status": "move_needed",
        "wanted_card_id": "balloon", "given_card_id": "wizard",
        "requester_tag": "#ME", "requester_name": "Asker",
        "requester_discord_id": 111,
        "holder_tag": "#H", "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_clan_tag": "#A", "requester_clan_name": "Alpha",
        "holder_clan_tag": "#B", "holder_clan_name": "Bravo",
    }
    view = cards_command._accepted_trade_dm(trade)
    text = _view_text(view)

    assert "<@222>" in text, "the partner's Discord identity is present"
    assert "`#H`" in text
    assert "-# Your account:" in text and "`#ME`" in text
    assert "**Trading with:**" in text
    assert "**Their clan:**" in text
    assert "[Open their clan]" in text
    assert "OpenClanProfile&tag=B" in text
    # Different clans: the optional meeting place renders as one quiet line
    # inside the main Container - never another card. The settled shape is
    # one main Container, plus the compact callout only when FWA earns it.
    def containers(items):
        found = []
        for item in items:
            built = item.build()
            payload = built[0] if isinstance(built, tuple) else built
            if int(payload["type"]) == 17:
                found.append(payload)
        return found

    assert len(containers(view)) == 1, "exactly one main Container"
    assert "-# ℹ️ Need a place to trade?" in text
    assert "#8VPQCR2R" in text
    # No FWA flag, no warning block.
    assert "FWA" not in text

    warned = cards_command._accepted_trade_dm(trade, fwa_relevant=True)
    warned_text = _view_text(warned)
    assert len(containers(warned)) == 1, (
        "the FWA warning rides inside the one main Container"
    )
    assert "> ### ⚠️ FWA — Wait for war" in warned_text
    assert "> Do not trade until war starts." in warned_text

    same_clan = cards_command._accepted_trade_dm(
        dict(trade, status="ready", holder_clan_tag="#A"), fwa_relevant=False
    )
    assert "Noahs Ark" not in _view_text(same_clan), (
        "a same-clan trade needs no meeting place"
    )


def test_fwa_membership_comes_from_the_clans_collection(monkeypatch):
    trade = {
        "_id": "t1",
        "requester_clan_tag": "#A", "holder_clan_tag": "#B",
    }

    class Clans:
        def __init__(self, row):
            self.row = row
            self.queries = []

        async def find_one(self, query, _projection=None):
            self.queries.append(query)
            return self.row

    fwa = Clans({"_id": "x"})
    assert asyncio.run(cards_command._trade_involves_fwa(
        SimpleNamespace(clans=fwa), trade
    )) is True
    assert fwa.queries[0]["type"] == "FWA"

    assert asyncio.run(cards_command._trade_involves_fwa(
        SimpleNamespace(clans=Clans(None)), trade
    )) is False

    class Broken:
        async def find_one(self, *_a, **_k):
            raise RuntimeError("down")

    assert asyncio.run(cards_command._trade_involves_fwa(
        SimpleNamespace(clans=Broken()), trade
    )) is False, "an FWA lookup failure must never block acceptance"


def test_swap_sent_view_promises_seven_days_not_twenty_four_hours():
    trade = _agreed_trade()
    view = cards_command._swap_sent_view(
        trade, role="requester", remaining=2, other_confirmed=False,
    )
    text = _view_text(view)
    assert "7 days" in text
    assert "24 hours" not in text


# --- 2026-08-14 live smoke-test follow-up -----------------------------------


class _OrderedModalCtx(_SubmitCtx):
    """Records the full modal-response lifecycle in order."""

    def __init__(self, raw, sink):
        super().__init__(raw, sink)
        self.sequence = []
        self.interaction.message = SimpleNamespace(id=42)
        self.interaction.create_initial_response = self._initial
        self.interaction.edit_initial_response = self._ordered_edit

    async def defer(self, *_args, **_kwargs):
        self.sequence.append("defer_create")
        return None

    async def _initial(self, response_type, **_kwargs):
        self.sequence.append(("ack", response_type))

    async def _ordered_edit(self, components=None, **_kwargs):
        self.sequence.append("edit_initial")
        self._sink["view"] = components


def test_the_modal_lifecycle_is_ack_update_then_edit_in_order(monkeypatch):
    """The exact response sequence Discord needs to edit the source panel.

    DEFERRED_MESSAGE_UPDATE acknowledges the modal against the message the
    modal was launched from, and the @original edit then lands on that same
    panel. Any DEFERRED_MESSAGE_CREATE in this sequence would answer with a
    brand-new message instead - the live duplicate-panel failure.
    """
    account = _gate_account()
    document, mongo = _quantity_env()
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )
    target = cards.CATEGORY_CARDS["elixir"][3]
    sent = {}
    ctx = _OrderedModalCtx("4", sent)

    asyncio.run(cards_command.cards_qnum_submit(
        ctx, f"#ME|{target.id}",
        coc_client=SimpleNamespace(), mongo=mongo,
    ))

    assert ctx.sequence == [
        ("ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE),
        "edit_initial",
    ], "one update-ack, one @original edit, nothing that creates a message"
    assert document["cards"][target.id] == 4


def test_freshness_confirmation_is_gone_and_legacy_button_redirects(monkeypatch):
    """The freshness-confirmation concept is removed from the rendered UI.

    Its stamp never affected matching (MATCHABLE_FOR is ten years and every
    member write refreshes confirmed_at), so the dashboard no longer asks for
    meaningless maintenance. The old cards_confirm button on messages already
    posted must still work: it opens the collection and writes nothing.
    """
    account = _gate_account()
    old = datetime.now(timezone.utc) - timedelta(days=10)
    inventory = {
        "_id": "#ME",
        "cards": {"wizard": 3},
        "complete_categories": ["elixir"],
        "confirmed_at": old,
    }
    view = cards_command._dashboard(account, inventory, account_count=1)
    text = _view_text(view)
    for phrase in (
        "Still accurate",
        "Still correct",
        "saves today's date",
        "keep matching",
        "Matching does not stop",
    ):
        assert phrase not in text, f"freshness copy survived: {phrase}"
    ids = {n.get("custom_id") for n in _view_nodes(view)}
    assert not any(
        str(i).startswith("cards_confirm:") for i in ids if i
    ), "the dashboard still renders the removed freshness button"

    # A legacy button click redirects to the collection and stamps nothing.
    document = dict(inventory)
    monkeypatch.setattr(
        cards_command, "_load_target", _fake_load_target(account, document),
    )

    async def fake_accounts(*_a, **_k):
        return _scan_accounts_data(account)

    monkeypatch.setattr(cards_command, "load_accounts", fake_accounts)
    monkeypatch.setattr(
        cards_command, "_dashboard", lambda *_a, **_k: ["BOARD"]
    )

    async def fake_board(*_a, **_k):
        return None

    monkeypatch.setattr(
        cards_command, "_render_inventory_board_async", fake_board
    )

    class Inventories:
        def __init__(self):
            self.sets = []

        async def update_one(self, _query, update):
            self.sets.append(update["$set"])
            document.update(update["$set"])
            return SimpleNamespace(modified_count=1)

        async def find_one(self, _query):
            return dict(document)

    class NoSwaps:
        def find(self, _query):
            class Cursor:
                def sort(self, *_a, **_k):
                    return self

                async def to_list(self, length=None):
                    return []

            return Cursor()

    inventories = Inventories()
    mongo = SimpleNamespace(card_inventories=inventories, card_trades=NoSwaps())

    result = asyncio.run(cards_command.cards_confirm(
        _quantity_ctx(), "#ME", coc_client=SimpleNamespace(), mongo=mongo,
    ))

    assert result == ["BOARD"], "the legacy button must land on the collection"
    assert inventories.sets == [], (
        "the legacy freshness button must not write confirmed_at"
    )
    assert document["confirmed_at"] == old


def test_scan_prompt_does_not_require_two_rows_per_image():
    """The row scanner accepts any complete six-card rows in any order."""
    account = _gate_account()
    prompt = _view_text(cards_command._scan_upload_prompt(
        account, "session-1", usable_until=None,
    ))
    assert "two complete rows" not in prompt.lower()
    assert "every row of six cards" in prompt.lower()
    assert "overlap is fine" in prompt.lower()
    assert "any order is fine" in prompt.lower()

    progress = _view_text(cards_command._scan_upload_progress(
        account, "session-1", {"missing_global_rows": list(range(3, 11))},
        usable_until=None,
    ))
    assert "two-row" not in progress.lower()
    assert "two full six-card rows" not in progress.lower()


def test_every_deadline_string_matches_its_actual_timer():
    """Each player-facing duration is tied to the constant that enforces it."""
    from extensions.tasks import cards_deadlines as sweeper

    assert cards_command.SWAP_CONFIRM_FOR == timedelta(days=7)
    assert "7 days" in sweeper.AUTO_DEDUCT_DETAIL_MOVED
    assert "7 days" in sweeper.AUTO_DEDUCT_DETAIL_NO_SPARE
    assert "24 hours" not in sweeper.AUTO_DEDUCT_DETAIL_MOVED
    assert "24 hours" not in sweeper.AUTO_DEDUCT_DETAIL_NO_SPARE

    assert cards_command.SWAP_ACCEPT_FOR == timedelta(hours=12)
    assert "12 hours" in sweeper.PROPOSAL_EXPIRED_DETAIL

    # The check-in really is 24 hours; that copy is correct and stays.
    assert cards_command.CHECKIN_ANSWER_FOR == timedelta(hours=24)
    checkin = _view_text(cards_command._checkin_dm("#ME", "Member"))
    assert "24 hours" in checkin


class _PreviewRest:
    def __init__(self):
        self.messages = []

    async def create_dm_channel(self, _user_id):
        return SimpleNamespace(id=777)

    async def create_message(self, channel=None, components=None, flags=None):
        self.messages.append(components)
        return SimpleNamespace(id=1)


class _PreviewClans:
    def find(self, _query, _projection=None):
        class Cursor:
            async def to_list(self, length=None):
                return []

        return Cursor()

    async def find_one(self, _query, _projection=None):
        return None


def test_the_preview_actually_sends_the_fwa_warning_state():
    """The accepted-with-FWA preview must exist AND be emitted when asked.

    The live review never saw the FWA region because the deployed build
    predates the state; this pins that the harness in this tree sends it and
    that it renders the separate warning treatment.
    """
    import extensions.commands.cards_preview as preview

    rest = _PreviewRest()
    bot = SimpleNamespace(rest=rest)
    mongo = SimpleNamespace(clans=_PreviewClans())

    sent = asyncio.run(preview._send_previews(
        "accepted_fwa", me=1, bot=bot, mongo=mongo,
    ))

    assert sent == [("13 · Accepted with FWA warning", True)]
    assert len(rest.messages) == 1
    text = _view_text(rest.messages[0])
    assert "> ### ⚠️ FWA — Wait for war" in text
    assert "> Do not trade until war starts." in text
    assert "Trade accepted" in text, (
        "the warning rides inside the accepted message as the inline callout"
    )


def test_the_preview_auto_deduct_state_says_seven_days():
    """The state the live review saw saying '24 hours' now shares the
    production string, which says 7 days."""
    import extensions.commands.cards_preview as preview

    rest = _PreviewRest()
    bot = SimpleNamespace(rest=rest)
    mongo = SimpleNamespace(clans=_PreviewClans())

    sent = asyncio.run(preview._send_previews(
        "auto_deduct", me=1, bot=bot, mongo=mongo,
    ))

    assert sent and sent[0][1] is True
    text = _view_text(rest.messages[0])
    assert "7 days" in text
    assert "24 hours" not in text

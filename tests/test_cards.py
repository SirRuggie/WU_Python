import asyncio
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands import cards as cards_command
from utils import cards
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
    assert found[1].returns == ()


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
        elif operator not in {"$exists", "$gt", "$gte", "$lt", "$lte", "$in"}:
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

        async def create_message(self, *, channel, content, attachment=None):
            assert channel == "dm-channel"
            self.messages.append((content, attachment))

    rest = Rest()
    bot = SimpleNamespace(rest=rest)
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

    assert asyncio.run(cards_command._notify_trade_holder(bot, trade)) is True
    assert len(rest.messages) == 1
    content, attachment = rest.messages[0]
    assert "Root Rider" in content
    assert "Wizard" in content
    assert "Dragon" in content
    assert "Shaun needs your duplicate Root Rider" in content
    assert "Shaun has **Wizard, Dragon** duplicates that you need" in content
    assert "different family clans" in content
    assert "token" not in content.casefold()
    assert "password" not in content.casefold()
    assert attachment.filename == "card-trade-root_rider-wizard.png"
    assert attachment.mimetype == "image/png"

    channel_copy = cards_command._trade_channel_content(trade)
    assert "Shaun needs your duplicate Root Rider" in channel_copy
    assert "Wizard, Dragon" in channel_copy
    assert "different family clans" in channel_copy

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
    assert "attachment" not in rest.messages[0]
    assert "Shaun needs your duplicate Root Rider" in rest.messages[0]["content"]


def test_follow_up_status_dm_identifies_both_account_tags():
    class Rest:
        def __init__(self):
            self.messages = []

        async def create_dm_channel(self, discord_id):
            assert discord_id == 222
            return "dm-channel"

        async def create_message(self, *, channel, content):
            assert channel == "dm-channel"
            self.messages.append(content)

    trade = _trade_document()
    trade.update({
        "requester_name": "Shaun",
        "holder_name": "Holder",
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
    assert "`#ME`" in rest.messages[0]
    assert "`#HOLDER`" in rest.messages[0]


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
    assert sent["attachment"].filename == "card-trade-root_rider-wizard.png"
    assert sent["attachment"].mimetype == "image/png"
    assert trades.docs[trade["_id"]]["channel_id"] == 999
    assert trades.docs[trade["_id"]]["channel_message_id"] == 777

    wrong_rest = Rest(guild_id=2)
    rejected = asyncio.run(cards_command._post_trade_channel(
        SimpleNamespace(rest=wrong_rest), mongo, dict(trade, _id="trade-wrong")
    ))
    assert rejected is False
    assert wrong_rest.messages == []


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


def test_category_is_not_searchable_until_both_exception_lists_are_reviewed():
    account = Account(
        tag="#ME",
        name="Member",
        clan_tag="#HOME",
        clan_name="Home Clan",
        town_hall=18,
    )
    document = {
        "_id": "#ME",
        "cards": {},
        "complete_categories": [],
        "reviewed_lists": [],
    }
    mongo = SimpleNamespace(card_inventories=_FakeCategoryCollection(document))
    cards_command._inventory_locks.clear()

    after_missing = asyncio.run(cards_command._write_category(
        mongo,
        account,
        document,
        "elixir",
        ["root_rider"],
        mode="missing",
        discord_id=123,
        guild_id=456,
    ))
    assert after_missing["complete_categories"] == []
    assert after_missing["reviewed_lists"] == ["elixir:missing"]
    assert after_missing["cards"]["root_rider"] == cards.MISSING

    after_duplicates = asyncio.run(cards_command._write_category(
        mongo,
        account,
        after_missing,
        "elixir",
        ["wizard"],
        mode="duplicates",
        discord_id=123,
        guild_id=456,
    ))
    assert after_duplicates["complete_categories"] == ["elixir"]
    assert set(after_duplicates["reviewed_lists"]) == {
        "elixir:missing",
        "elixir:duplicates",
    }
    assert after_duplicates["cards"]["root_rider"] == cards.MISSING
    assert after_duplicates["cards"]["wizard"] == cards.DUPLICATE


def test_category_revision_retry_merges_a_cross_process_list_update():
    class RacingCategory(_FakeCategoryCollection):
        def __init__(self, document):
            super().__init__(document)
            self.raced = False

        async def update_one(self, query, update, upsert=False):
            if not self.raced:
                self.raced = True
                self.document.setdefault("cards", {})["wizard"] = cards.DUPLICATE
                self.document.setdefault("reviewed_lists", []).append(
                    "elixir:duplicates"
                )
                self.document["inventory_revision"] = 1
                return SimpleNamespace(matched_count=0, modified_count=0)
            return await super().update_one(query, update, upsert=upsert)

    account = Account(
        tag="#ME",
        name="Member",
        clan_tag="#HOME",
        clan_name="Home Clan",
        town_hall=18,
    )
    document = {
        "_id": "#ME",
        "cards": {},
        "complete_categories": [],
        "reviewed_lists": [],
    }
    mongo = SimpleNamespace(card_inventories=RacingCategory(document))
    cards_command._inventory_locks.clear()

    merged = asyncio.run(cards_command._write_category(
        mongo,
        account,
        document,
        "elixir",
        ["root_rider"],
        mode="missing",
        discord_id=123,
        guild_id=456,
    ))

    assert merged["cards"]["wizard"] == cards.DUPLICATE
    assert merged["cards"]["root_rider"] == cards.MISSING
    assert set(merged["reviewed_lists"]) == {
        "elixir:duplicates",
        "elixir:missing",
    }
    assert merged["complete_categories"] == ["elixir"]
    assert merged["inventory_revision"] == 2


def test_category_editor_uses_explicit_clear_buttons_not_a_none_select_option():
    account = Account(
        tag="#ME",
        name="Member",
        clan_tag="#HOME",
        clan_name="Home Clan",
        town_hall=18,
    )
    payload = [
        component.build()
        for component in cards_command._category_editor(
            account,
            {"_id": "#ME", "cards": {}, "complete_categories": []},
            "elixir",
        )
    ]
    nodes = list(_walk_payload(payload))
    option_values = {
        str(option["value"])
        for node in nodes
        for option in node.get("options", [])
    }
    custom_ids = {
        str(node["custom_id"])
        for node in nodes
        if "custom_id" in node
    }

    assert "__none__" not in option_values
    assert "cards_clear_missing:#ME|elixir" in custom_ids
    assert "cards_clear_duplicates:#ME|elixir" in custom_ids


def test_collection_edit_allows_unrelated_category_but_rejects_reserved_category():
    account = Account(
        tag="#ME",
        name="Member",
        clan_tag="#HOME",
        clan_name="Home Clan",
        town_hall=18,
    )
    trade = _trade_document()
    trade["reservation_token"] = "token-a"
    document = _reserve_inventory({
        "_id": "#ME",
        "cards": {},
        "complete_categories": [],
        "reviewed_lists": [],
    }, trade)
    mongo = SimpleNamespace(card_inventories=_FakeCategoryCollection(document))
    cards_command._inventory_locks.clear()

    updated = asyncio.run(cards_command._write_category(
        mongo,
        account,
        document,
        "builder_base",
        ["night_witch"],
        mode="missing",
        discord_id=123,
        guild_id=1,
    ))
    assert updated["cards"]["night_witch"] == cards.MISSING

    with pytest.raises(cards_command.ActiveCardTradeError):
        asyncio.run(cards_command._write_category(
            mongo,
            account,
            document,
            "elixir",
            ["root_rider"],
            mode="missing",
            discord_id=123,
            guild_id=1,
        ))
    assert "root_rider" not in document["cards"]


def test_trade_component_scope_rejects_wrong_guild_before_database_access(monkeypatch):
    class NoDatabaseAccess:
        def __getattr__(self, name):
            raise AssertionError(f"database was accessed through {name}")

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 123)
    ctx = SimpleNamespace(guild_id=999, user=SimpleNamespace(id=1))
    mongo = SimpleNamespace(card_trades=NoDatabaseAccess())

    for handler in (
        cards_command.cards_trade_accept,
        cards_command.cards_trade_ready,
        cards_command.cards_trade_decline,
        cards_command.cards_trade_cancel,
        cards_command.cards_trade_complete,
    ):
        result = asyncio.run(handler(
            ctx,
            "forged-trade-id",
            coc_client=SimpleNamespace(),
            mongo=mongo,
            bot=SimpleNamespace(),
        ))
        assert result


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
    class Clans:
        async def distinct(self, field):
            assert field == "tag"
            return []

    class Inventories:
        def find(self, _query):
            raise AssertionError("inventory search must not broaden without family tags")

    mongo = SimpleNamespace(clans=Clans(), card_inventories=Inventories())
    requester = _complete_inventory()

    assert asyncio.run(cards_command._candidate_inventories(
        mongo, requester, guild_id=None
    )) == []
    assert asyncio.run(cards_command._candidate_inventories(
        mongo, requester, guild_id=123
    )) == []


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

    async def create_message(self, *, channel, content):
        self.messages.append((channel, content))


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


def test_cross_clan_swap_becomes_ready_after_accounts_move_together(monkeypatch):
    trade = _reserved_trade()
    trade.update({
        "kind": "trade",
        "status": "move_needed",
        "requester_name": "Requester",
        "requester_discord_id": 111,
        "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_clan_tag": "#HOME",
        "holder_clan_tag": "#AWAY",
        "updated_at": datetime.now(timezone.utc),
    })
    trades = _FakeTradeCollection()
    trades.docs[trade["_id"]] = trade
    account = Account(
        tag="#ME", name="Requester", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )

    async def load_actor(*_args, **_kwargs):
        return account, {}, None

    async def live_clans(*_args, **_kwargs):
        return "#FAMILY", "#FAMILY"

    async def verify(*_args, **_kwargs):
        return True

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_trade_actor", load_actor)
    monkeypatch.setattr(cards_command, "_live_family_clans", live_clans)
    monkeypatch.setattr(cards_command, "_verify_trade_reservation", verify)
    rest = _TradeHandlerRest()
    ctx = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=111))

    result = asyncio.run(cards_command.cards_trade_ready(
        ctx,
        trade["_id"],
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(card_trades=trades),
        bot=SimpleNamespace(rest=rest),
    ))

    assert result
    saved = trades.docs[trade["_id"]]
    assert saved["status"] == "ready"
    assert saved["requester_clan_tag"] == "#FAMILY"
    assert saved["holder_clan_tag"] == "#FAMILY"
    assert saved["clan_tag"] == "#FAMILY"
    assert "expires_at" not in saved
    assert rest.messages and rest.messages[0][0] == "dm-222"


def test_ready_check_cas_loser_does_not_cleanup_or_notify(monkeypatch):
    trade = _reserved_trade()
    trade.update({
        "kind": "trade",
        "status": "move_needed",
        "requester_name": "Requester",
        "requester_discord_id": 111,
        "holder_name": "Holder",
        "holder_discord_id": 222,
    })

    class CasLoserTrades(_FakeTradeCollection):
        def __init__(self):
            super().__init__()
            self.review_attempts = 0

        async def update_one(self, query, update, upsert=False):
            if update.get("$set", {}).get("status") == "needs_review":
                self.review_attempts += 1
                return SimpleNamespace(matched_count=0, modified_count=0)
            return await super().update_one(query, update, upsert=upsert)

    trades = CasLoserTrades()
    trades.docs[trade["_id"]] = dict(trade)
    account = Account(
        tag="#ME", name="Requester", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )

    async def load_actor(*_args, **_kwargs):
        return account, {}, None

    async def live_clans(*_args, **_kwargs):
        return "#FAMILY", "#FAMILY"

    async def missing_reservation(*_args, **_kwargs):
        return False

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("CAS loser performed cleanup or notification")

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_trade_actor", load_actor)
    monkeypatch.setattr(cards_command, "_live_family_clans", live_clans)
    monkeypatch.setattr(
        cards_command, "_verify_trade_reservation", missing_reservation
    )
    monkeypatch.setattr(cards_command, "_finish_trade_cleanup", forbidden)
    monkeypatch.setattr(cards_command, "_notify_trade_status", forbidden)
    monkeypatch.setattr(cards_command, "_update_trade_channel", forbidden)
    ctx = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=111))

    result = asyncio.run(cards_command.cards_trade_ready(
        ctx,
        trade["_id"],
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(card_trades=trades),
        bot=SimpleNamespace(),
    ))

    assert result
    assert trades.review_attempts == 1
    assert trades.docs[trade["_id"]]["status"] == "move_needed"
    assert "cleanup_pending" not in trades.docs[trade["_id"]]


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
    review_steps = ["elixir:missing", "elixir:duplicates", "builder_base:missing"]
    for document in (requester, holder):
        document["reviewed_lists"] = list(review_steps)

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
        assert document["reviewed_lists"] == ["builder_base:missing"]
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
    options = [
        option
        for node in nodes
        if node.get("custom_id") == "cards_trade_holder:#ME|root_rider"
        for option in node.get("options", [])
    ]
    assert [option["value"] for option in options] == ["#HOLDER20"]
    assert "cards_holder_page:#ME|root_rider|0" in custom_ids
    assert "cards_holder_page:#ME|root_rider|1" in custom_ids
    assert "cards_holder_page:#ME|root_rider|2" in custom_ids
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


def test_dashboard_is_compact_with_one_primary_action_at_most():
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
        primary = [node for node in buttons if node.get("style") == 1]
        assert len(buttons) <= 5
        assert len(primary) <= 1
        assert not any(node.get("type") == 12 for node in nodes)
        _assert_discord_payload(view)

    custom_ids = {
        node.get("custom_id")
        for node in _view_nodes(views[0])
        if node.get("custom_id")
    }
    assert custom_ids == {
        "cards_editor:#ME|barbarian",
        "cards_matches:#ME",
        "cards_trades:#ME",
        "cards_more:#ME",
    }


def test_runtime_dashboard_does_not_render_the_optional_full_board(monkeypatch):
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

    assert calls == []
    assert not any(node.get("type") == 12 for node in _view_nodes(view))
    _assert_discord_payload(view)


def test_optional_full_board_page_has_only_the_board_and_back_action():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._review(account, _complete_inventory())
    nodes = _view_nodes(view)
    buttons = [node for node in nodes if node.get("type") == 2]

    assert len([node for node in nodes if node.get("type") == 12]) == 1
    assert len(buttons) == 1
    assert buttons[0]["custom_id"] == "cards_dashboard:#ME"
    assert buttons[0]["label"] == "Back"
    assert buttons[0]["style"] == 2
    _assert_discord_payload(view)


@pytest.mark.parametrize("selected_category", [category.id for category in cards.CATEGORIES])
def test_category_browser_has_four_counted_chips_and_selected_category_accent(
    selected_category,
):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["barbarian"] = cards.MISSING

    view = cards_command._category_browser(
        account, inventory, selected_category, page=0
    )
    nodes = _view_nodes(view)
    chip_ids = {
        f"cards_editor_category:#ME|{category.id}|0|chip"
        for category in cards.CATEGORIES
    }
    chips = {
        node["custom_id"]: node
        for node in nodes
        if node.get("custom_id") in chip_ids
    }

    assert len(chips) == 4
    for category in cards.CATEGORIES:
        expected_count = (
            f"18/{len(cards.CATEGORY_CARDS[category.id])}"
            if category.id == "elixir"
            else (
                f"{len(cards.CATEGORY_CARDS[category.id])}/"
                f"{len(cards.CATEGORY_CARDS[category.id])}"
            )
        )
        label = chips[
            f"cards_editor_category:#ME|{category.id}|0|chip"
        ]["label"]
        assert expected_count in label
        assert label.startswith("• ") is (category.id == selected_category)
        assert label.endswith(" ✓") is (category.id != "elixir")
        assert chips[
            f"cards_editor_category:#ME|{category.id}|0|chip"
        ]["style"] == cards_command.hikari.ButtonStyle.SECONDARY

    container = next(node for node in nodes if node.get("type") == 17)
    assert container["accent_color"] == cards_command.CATEGORY_ACCENTS[
        selected_category
    ]
    _assert_discord_payload(view)


@pytest.mark.parametrize("category_id", [category.id for category in cards.CATEGORIES])
def test_category_browser_paginates_every_card_within_discord_component_limit(
    category_id,
):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    definitions = list(cards.CATEGORY_CARDS[category_id])
    page_count = math.ceil(len(definitions) / cards_command.CARD_BROWSER_PAGE_SIZE)
    seen_card_ids = []

    for page in range(page_count):
        view = cards_command._category_browser(
            account, inventory, category_id, page=page
        )
        nodes = _view_nodes(view)
        component_count = len([node for node in nodes if "type" in node])
        visible_ids = [
            str(node["custom_id"]).split("|", 1)[1]
            for node in nodes
            if str(node.get("custom_id", "")).startswith(
                "cards_editor_inc:#ME|"
            )
        ]
        expected_visible = definitions[
            page * cards_command.CARD_BROWSER_PAGE_SIZE:
            (page + 1) * cards_command.CARD_BROWSER_PAGE_SIZE
        ]
        previous = next(node for node in nodes if node.get("label") == "Previous")
        following = next(node for node in nodes if node.get("label") == "Next")

        assert component_count <= 40
        assert visible_ids == [card.id for card in expected_visible]
        assert len([node for node in nodes if node.get("type") == 9]) == len(
            expected_visible
        )
        assert len([node for node in nodes if node.get("type") == 11]) == len(
            expected_visible
        )
        assert previous["disabled"] is (page == 0)
        assert following["disabled"] is (page == page_count - 1)
        seen_card_ids.extend(visible_ids)
        _assert_discord_payload(view)

    assert seen_card_ids == [card.id for card in definitions]


@pytest.mark.parametrize(
    ("state", "state_text", "dec_disabled", "inc_disabled"),
    [
        (cards.MISSING, "Missing · 0 copies", True, False),
        (cards.OWNED, "Owned · 1 copy", False, False),
        (cards.DUPLICATE, "Spare available · 2+ copies", False, True),
    ],
)
def test_card_editor_shows_accessible_card_tiles_and_valid_copy_controls(
    state, state_text, dec_disabled, inc_disabled,
):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["wizard"] = state

    view = cards_command._card_editor(account, inventory, "wizard")
    nodes = _view_nodes(view)
    buttons = {
        node["custom_id"]: node
        for node in nodes
        if "custom_id" in node
    }
    thumbnails = [node for node in nodes if node.get("type") == 11]
    thumbnail = next(
        node for node in thumbnails
        if str(node.get("description", "")).startswith("Wizard")
    )
    expected_thumbnail = cards_command.render_card_thumbnail("wizard", state)

    assert f"## Wizard\n**{state_text}**" in _view_text(view)
    assert thumbnail["media"]["url"] == (
        f"attachment://{expected_thumbnail.filename}"
    )
    assert thumbnail["description"] == expected_thumbnail.alt_text
    assert buttons["cards_editor_dec:#ME|wizard"]["disabled"] is dec_disabled
    assert buttons["cards_editor_inc:#ME|wizard"]["disabled"] is inc_disabled
    assert len(thumbnails) == cards_command.CARD_BROWSER_PAGE_SIZE
    visible_ids = ["wall_breaker", "balloon", "wizard", "healer"]
    for card_id in visible_ids:
        assert f"cards_editor_dec:#ME|{card_id}" in buttons
        assert f"cards_editor_inc:#ME|{card_id}" in buttons
    assert not any(
        node.get("type") == 2 and node.get("style") == 1
        for node in nodes
    )
    _assert_discord_payload(view)


def test_more_panel_links_directly_to_global_card_chat():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._more_panel(
        account, _complete_inventory(), account_count=1
    )
    links = [
        node
        for node in _view_nodes(view)
        if node.get("label") == "Global Card Chat"
    ]

    assert len(links) == 1
    assert links[0]["style"] == cards_command.hikari.ButtonStyle.LINK
    assert links[0]["url"] == cards_command.GLOBAL_CHAT_LINK
    assert "OpenGlobalChat" in links[0]["url"]
    assert "chatId=" in links[0]["url"]
    _assert_discord_payload(view)


def test_card_editor_disables_copy_changes_while_the_card_is_reserved():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["card_trade_reservations"] = {"wizard": "trade:token"}

    view = cards_command._card_editor(account, inventory, "wizard")
    buttons = {
        node["custom_id"]: node
        for node in _view_nodes(view)
        if "custom_id" in node
    }

    assert "Reserved by an accepted trade" in _view_text(view)
    assert buttons["cards_editor_dec:#ME|wizard"]["disabled"] is True
    assert buttons["cards_editor_inc:#ME|wizard"]["disabled"] is True


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
    assert cards_command._editor_state_text(
        expected, possible_spare=False, reserved=False
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
    assert {
        "cards_editor_keep:#ME|dragon",
        "cards_editor_inc:#ME|dragon",
    } <= custom_ids


def test_card_editor_and_more_handlers_route_to_the_requested_account(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    loaded_tags = []

    async def load_target(_ctx, tag, **_kwargs):
        loaded_tags.append(tag)
        return account, inventory, None

    async def load_accounts(*_args, **_kwargs):
        return _scan_accounts_data(account)

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    editor = asyncio.run(cards_command.cards_editor(
        ctx, "#ME|wizard", coc_client=SimpleNamespace(), mongo=SimpleNamespace()
    ))
    more = asyncio.run(cards_command.cards_more(
        ctx, "#ME", coc_client=SimpleNamespace(), mongo=SimpleNamespace()
    ))

    assert loaded_tags == ["#ME", "#ME"]
    assert "## Wizard" in _view_text(editor)
    more_nodes = _view_nodes(more)
    assert {
        node.get("custom_id")
        for node in more_nodes
        if node.get("custom_id")
    } == {
        "cards_scan_start:#ME",
        "cards_review:#ME",
        "cards_advanced:#ME",
        "cards_confirm:#ME",
        "cards_dashboard:#ME",
    }
    assert not any(
        node.get("type") == 2 and node.get("style") == 1
        for node in more_nodes
    )


def test_card_editor_search_modal_and_submit_route_to_card_choices(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()

    class MenuCtx:
        def __init__(self):
            self.modals = []

        async def respond_with_modal(self, **kwargs):
            self.modals.append(kwargs)

    menu_ctx = MenuCtx()
    asyncio.run(cards_command.cards_editor_find(menu_ctx, "#ME"))
    assert menu_ctx.modals[0]["custom_id"] == "cards_editor_find_submit:#ME"
    assert menu_ctx.modals[0]["title"] == "Find a card"

    class Interaction:
        components = [[SimpleNamespace(
            custom_id="card_name", value="root ridr"
        )]]

        def __init__(self):
            self.edits = []

        async def edit_initial_response(self, **kwargs):
            self.edits.append(kwargs)

    modal_ctx = SimpleNamespace(
        user=SimpleNamespace(id=123),
        guild_id=1,
        interaction=Interaction(),
        deferred=[],
    )

    async def defer(*, ephemeral=False):
        modal_ctx.deferred.append(ephemeral)

    async def load_target(*_args, **_kwargs):
        assert modal_ctx.deferred == [True]
        return account, inventory, None

    modal_ctx.defer = defer
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    asyncio.run(cards_command.cards_editor_find_submit(
        modal_ctx,
        "#ME",
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    choice_nodes = _view_nodes(
        modal_ctx.interaction.edits[0]["components"]
    )
    assert any(
        node.get("custom_id") == "cards_editor:#ME|root_rider"
        and node.get("label") == "Root Rider"
        for node in choice_nodes
    )


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


def test_card_name_modal_lookup_is_exact_or_typo_tolerant_then_confirms():
    assert [card.id for card in cards_command._card_name_matches("Root Rider")] == [
        "root_rider"
    ]
    assert cards_command._card_name_matches("root ridr")[0].id == "root_rider"
    assert cards_command._card_name_matches("not a real card") == ()

    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 9
    inventory["cards"]["root_rider"] = cards.MISSING
    nodes = _view_nodes(cards_command._quick_confirmation(
        account, inventory, "found", "root ridr"
    ))
    assert any(
        node.get("custom_id") == "cards_quick_apply:#ME|found|root_rider|9"
        for node in nodes
    )
    assert "Did you mean" in _view_text(cards_command._quick_confirmation(
        account, inventory, "found", "root ridr"
    ))


def test_quick_card_modal_opens_without_waiting_for_account_io():
    class Ctx:
        def __init__(self):
            self.modals = []

        async def respond_with_modal(self, **kwargs):
            self.modals.append(kwargs)

    ctx = Ctx()
    asyncio.run(cards_command.cards_quick_modal(ctx, "#ME|spare"))

    assert len(ctx.modals) == 1
    assert ctx.modals[0]["title"] == "Got a spare"
    assert ctx.modals[0]["custom_id"] == "cards_quick_submit:#ME|spare"


def test_quick_modal_submit_defers_before_loading_account(monkeypatch):
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 4

    class Interaction:
        components = [[SimpleNamespace(custom_id="card_name", value="Wizard")]]

        def __init__(self):
            self.edits = []

        async def edit_initial_response(self, **kwargs):
            self.edits.append(kwargs)

    class Ctx:
        def __init__(self):
            self.deferred = False
            self.interaction = Interaction()
            self.user = SimpleNamespace(id=123)
            self.guild_id = 1

        async def defer(self, *, ephemeral=False):
            assert ephemeral is True
            self.deferred = True

    ctx = Ctx()

    async def load_target(*_args, **_kwargs):
        assert ctx.deferred is True
        return account, inventory, None

    monkeypatch.setattr(cards_command, "_load_target", load_target)
    asyncio.run(cards_command.cards_quick_submit(
        ctx,
        "#ME|spare",
        coc_client=SimpleNamespace(),
        mongo=SimpleNamespace(),
    ))

    assert len(ctx.interaction.edits) == 1
    assert any(
        node.get("custom_id") == "cards_quick_apply:#ME|spare|wizard|4"
        for node in _view_nodes(ctx.interaction.edits[0]["components"])
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
    assert updated["inventory_revision"] == 6
    next_view = cards_command._hidden_badge_review(account, updated)
    assert "2 remaining" in _view_text(next_view)
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
        cards_command._update_overview(account, empty),
        cards_command._review(account, complete),
        cards_command._review(account, active),
        cards_command._active_trade_notice(account.tag),
        cards_command._matches_view(account, complete, []),
        cards_command._matches_view(account, complete, broad_matches),
        cards_command._find_category_view(account, complete, "elixir"),
        cards_command._holders_view(account, "root_rider", []),
        cards_command._holders_view(account, "root_rider", specific_matches),
        cards_command._trade_offer_view(
            account, "root_rider", specific_matches[0]
        ),
        cards_command._trades_view(account, active_trades),
        cards_command._trade_feedback("Saved", "Ready", "#ME"),
    ]
    views.extend(
        cards_command._category_editor(account, empty, category.id)
        for category in cards.CATEGORIES
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
        node.get("custom_id") == "cards_editor:#ME|barbarian"
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
        node.get("custom_id") == "cards_more:#ME"
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
    assert "send all of its screenshots" in prompt_text.lower()
    assert "any order is fine" in prompt_text.lower()
    assert updated[0][1]["$set"] == {
        "upload_prompt_channel_id": 777,
        "upload_prompt_message_id": 888,
    }
    assert "Private Upload Ready" in _view_text(view)


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
    assert "do **not** need to resend" in progress


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
    assert confirm["label"] == "Save collection"
    review_text = _view_text(view)
    assert "1 cards still need a duplicate check" in review_text
    buttons = [node for node in nodes if node.get("type") == 2]
    assert [button.get("label") for button in buttons] == [
        "Save collection",
        "Cancel",
    ]
    assert len([button for button in buttons if button.get("style") == 1]) == 1
    assert len([node for node in nodes if node.get("type") == 1]) == 1
    assert not any(node.get("type") == 12 for node in nodes)


def test_scan_confirm_is_explicit_and_private_session_checks_precede_db(monkeypatch):
    account = _scan_account()
    draft = _complete_scan_draft()
    inventory = _complete_inventory()
    inventory["inventory_revision"] = 4
    writes = []
    discarded = []

    async def load_target(*_args, **_kwargs):
        return account, inventory, None

    async def write_scan(*args, **kwargs):
        writes.append((args, kwargs))
        return dict(inventory, update_source="confirmed_screenshot_review")

    async def discard(_mongo, draft_id):
        discarded.append(draft_id)

    async def load_accounts(*_args, **_kwargs):
        return _scan_accounts_data(account)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_write_scan_draft", write_scan)
    monkeypatch.setattr(cards_command, "_discard_scan_state", discard)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    ctx = SimpleNamespace(user=SimpleNamespace(id=123), guild_id=1)

    # Rendering review is side-effect free; only its explicit button writes.
    cards_command._scan_review(account, inventory, "draft-confirm", draft)
    assert writes == []
    assert discarded == []

    asyncio.run(cards_command.cards_scan_confirm(
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


def test_scan_save_continues_hidden_spare_review_directly_in_private_session(
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
    state_updates = []
    discarded = []

    async def load_target(*_args, **_kwargs):
        return account, inventory, None

    async def write_scan(*_args, **_kwargs):
        return saved

    async def load_accounts(*_args, **_kwargs):
        return _scan_accounts_data(account)

    async def update_state(_mongo, query, update):
        state_updates.append((query, update))

    async def discard(_mongo, draft_id):
        discarded.append(draft_id)

    monkeypatch.setattr(cards_command, "CARDS_GUILD_ID", 1)
    monkeypatch.setattr(cards_command, "_load_target", load_target)
    monkeypatch.setattr(cards_command, "_write_scan_draft", write_scan)
    monkeypatch.setattr(cards_command, "load_accounts", load_accounts)
    monkeypatch.setattr(cards_command, "update_state", update_state)
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
    assert any(
        node.get("custom_id") == "cards_scan_hidden_no:draft-hidden-review"
        for node in nodes
    )
    assert any(
        node.get("custom_id") == "cards_scan_hidden_yes:draft-hidden-review"
        for node in nodes
    )
    assert discarded == []
    assert state_updates[0][1]["$set"]["type"] == "cards_hidden_badge_review"
    assert state_updates[0][1]["$set"]["base_revision"] == 5


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
        "cards_scan_hidden_no:draft-hidden",
        "cards_scan_hidden_yes:draft-hidden",
    } <= custom_ids


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
    assert saved["update_source"] == "confirmed_screenshot_review"
    assert saved["inventory_revision"] == 1
    quick_update = cards_command._quick_update_panel(account, saved)
    assert "2 possible spares need one check" in _view_text(quick_update)
    assert any(
        node.get("custom_id") == "cards_hidden:#ME"
        for node in _view_nodes(quick_update)
    )

    category_collection = _FakeCategoryCollection(saved)
    category_mongo = SimpleNamespace(card_inventories=category_collection)
    after_missing = asyncio.run(cards_command._write_category(
        category_mongo,
        account,
        saved,
        "elixir",
        [],
        mode="missing",
        discord_id=123,
        guild_id=1,
    ))
    assert after_missing["scan_duplicate_unverified_card_ids"] == [
        elixir_hidden,
        dark_hidden,
    ]

    after_duplicates = asyncio.run(cards_command._write_category(
        category_mongo,
        account,
        after_missing,
        "elixir",
        [],
        mode="duplicates",
        discord_id=123,
        guild_id=1,
    ))
    assert after_duplicates["scan_duplicate_unverified_card_ids"] == [dark_hidden]


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

import asyncio
import math
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands import cards as cards_command
from utils import card_board, cards, troop_emoji
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
    assert "**Shaun** wants your" in content
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
    assert "wants your" in _view_text(sent)
    assert "Root Rider" in _view_text(sent)


def test_follow_up_status_dm_identifies_both_account_tags():
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
        "cards_scan_start:#ME",
        "cards_matches:#ME",
        "cards_trades:#ME",
        "cards_sort:#ME",
        # Not setup-only: your cards keep changing after every category has
        # been reviewed, and reviewing cannot be undone.
        "cards_advanced:#ME",
        "cards_pick:#ME|elixir",
        "cards_pick:#ME|dark_elixir",
        "cards_pick:#ME|builder_base",
        "cards_pick:#ME|super_troop",
    }
    # The junk-drawer router is gone entirely.
    assert "cards_more:#ME" not in custom_ids


def test_landing_reaches_every_card_in_one_interaction():
    """All sixty cards are menu options on the first screen, no pagination."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account, _complete_inventory(), account_count=1
    )
    payload = [component.build() for component in view]
    offered = {
        str(option["value"])
        for node in _walk_payload(payload)
        for option in (node.get("options") or ())
        if option["value"] != cards_command.CATEGORY_HEADER_VALUE
    }

    assert offered == {card.id for card in cards.CARDS}
    assert len(offered) == 60
    _assert_discord_payload(view)


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
    assert "cards_pick:#NEW|elixir" in custom_ids
    assert "cards_scan_start:#NEW" in custom_ids
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
    # Absolute state controls plus the copy-count steppers replace the
    # increment/decrement/keep trio.
    assert {
        "cards_set:#ME|dragon|0",
        "cards_set:#ME|dragon|1",
        "cards_step:#ME|dragon|1",
        "cards_step:#ME|dragon|-1",
        "cards_count:#ME|dragon",
    } <= custom_ids


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
    assert any(
        node.get("custom_id") == "cards_set:#ME|dragon|0"
        and node.get("label") == "None"
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
        cards_command._update_overview(account, empty),
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


def _view_media(view):
    """The first media item mounted in a container, or None."""
    for node in _view_nodes(view):
        for item in node.get("items") or ():
            media = item.get("media") if isinstance(item, dict) else None
            if media is not None:
                return media
    return None


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
        node.get("custom_id") == "cards_pick:#ME|elixir"
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
        node.get("custom_id") == "cards_pick:#ME|elixir"
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
    # Several hidden badges are asked about together, not one screen each.
    assert any(
        node.get("custom_id") == "cards_hidden_pick:#ME"
        for node in nodes
    )
    assert any(
        node.get("custom_id") == "cards_hidden_none_of_these:#ME"
        for node in nodes
    )
    # Every unread badge is offered in one multi-select.
    picker = next(n for n in nodes if n.get("custom_id") == "cards_hidden_pick:#ME")
    assert {str(o["value"]) for o in picker["options"]} == set(hidden[:25])
    assert picker["max_values"] == len(hidden[:25])
    assert len([node for node in nodes if "type" in node]) <= 40
    _assert_discord_payload(view)
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
    assert saved["update_source"] == "confirmed_screenshot_review"
    assert saved["inventory_revision"] == 1
    # The board both reports the pending check and carries the button for it.
    board = cards_command._dashboard(account, saved, account_count=1)
    assert "2 cards need a duplicate check" in _view_text(board)
    assert any(
        node.get("custom_id") == "cards_hidden:#ME"
        for node in _view_nodes(board)
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
    buttons = {
        node["custom_id"]: node
        for node in _view_nodes(view)
        if node.get("custom_id", "").startswith("cards_set:")
    }

    # Style 3 is SUCCESS: the button matching the saved state is the green one.
    assert buttons["cards_set:#ME|wizard|2"]["style"] == 3
    assert buttons["cards_set:#ME|wizard|1"]["style"] == 2
    assert buttons["cards_set:#ME|wizard|0"]["style"] == 2
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

    assert "Accounts 1-25 of 30" in _view_text(first)
    assert "Accounts 26-30 of 30" in _view_text(second)
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
    assert "**Your cards**" in _view_text(view)
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
    assert seen == 2, f"only checked {seen} scan buttons"


def test_the_sort_button_is_marked_in_every_order():
    """The label changes as it cycles; the mark identifying it must not."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    for order in cards_command.CARD_SORTS:
        inventory = _complete_inventory()
        inventory["card_sort"] = order
        view = cards_command._dashboard(account, inventory, account_count=1)
        button = next(
            n for n in _view_nodes(view)
            if n.get("custom_id") == "cards_sort:#ME"
        )
        assert (button.get("emoji") or {}).get("id") == "1536804681555247144"
        assert button["label"] == cards_command.CARD_SORT_LABELS[order]


def test_sort_control_sits_with_the_menus_it_sorts():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account, _complete_inventory(), account_count=1
    )
    rows = [n for n in _view_nodes(view) if n.get("type") == 1]

    def row_with(prefix):
        return next(
            i for i, row in enumerate(rows)
            if any(
                str(c.get("custom_id", "")).startswith(prefix)
                for c in row.get("components", [])
            )
        )

    # Sort sits with the menus it acts on, above the places you can go next.
    assert row_with("cards_sort:") < row_with("cards_matches:")
    assert row_with("cards_pick:") < row_with("cards_sort:")

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
    assert "cards_account_page:0" not in done_ids
    assert "cards_advanced:#ME" in done_ids
    assert "cards_advanced:#ME" in partial_ids
    assert "cards_account_page:0" in partial_ids
    # Scanning is always available.
    assert "cards_scan_start:#ME" in done_ids and "cards_scan_start:#ME" in partial_ids


def test_card_menus_can_be_sorted_by_quantity():
    """Game order matches the board; the other two put actionable cards on top."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    inventory = _complete_inventory()
    inventory["cards"]["giant"] = cards.MISSING
    inventory["cards"]["barbarian"] = 4
    inventory["cards"]["archer"] = 2

    def order(sort):
        inv = dict(inventory, card_sort=sort)
        row = cards_command._category_select_row(account, inv, "elixir", sort)
        return [
            o.value for o in row.components[0].options
            if o.value != cards_command.CATEGORY_HEADER_VALUE
        ]

    game = order("game")
    need = order("need")
    have = order("have")

    assert game[:3] == ["barbarian", "archer", "giant"]     # catalog order
    assert need[0] == "giant"                               # missing first
    assert have[0] == "barbarian"                           # 4 copies first
    assert have[1] == "archer"                              # then 2
    assert set(game) == set(need) == set(have)              # nothing lost


def test_sort_cycles_and_persists():
    assert cards_command._next_sort("game") == "need"
    assert cards_command._next_sort("need") == "have"
    assert cards_command._next_sort("have") == "game"
    # An unknown stored value falls back rather than raising.
    assert cards_command._inventory_sort({"card_sort": "nonsense"}) == "game"
    assert cards_command._inventory_sort({"card_sort": "have"}) == "have"
    assert cards_command._inventory_sort({}) == "game"


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
    # up but not all, a stale confirmation, a pending spare check, and more
    # than one linked account.
    inventory = _complete_inventory()
    inventory["complete_categories"] = ["elixir"]
    inventory["confirmed_at"] = datetime.now(timezone.utc) - timedelta(days=5)
    inventory["scan_duplicate_unverified_card_ids"] = ["wizard"]

    view = cards_command._dashboard(account, inventory, account_count=3)
    ids = {n.get("custom_id") for n in _view_nodes(view)}

    # Six controls: one more than a row holds, so the last one is exactly what
    # the old slice discarded.
    for expected in (
        "cards_scan_start:#ME",
        "cards_sort:#ME",
        "cards_hidden:#ME",
        "cards_advanced:#ME",
        "cards_confirm:#ME",
        "cards_account_page:0",
    ):
        assert expected in ids, f"{expected} was dropped from the board"
    for node in _view_nodes(view):
        if node.get("type") == 1:
            assert len(node.get("components", [])) <= 5
    _assert_discord_payload(view)


def test_each_board_dropdown_is_visually_distinct(monkeypatch):
    """Four identically-styled menus are hard to tell apart at a glance."""
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    view = cards_command._dashboard(
        account, _complete_inventory(), account_count=1
    )
    menus = [
        n for n in _view_nodes(view)
        if str(n.get("custom_id", "")).startswith("cards_pick:")
    ]

    assert len(menus) == len(cards.CATEGORIES)
    for menu in menus:
        category_id = menu["custom_id"].split("|")[1]
        header = menu["options"][0]
        # The default option is what Discord draws on a closed menu, so this
        # is the only place the uploaded category art can appear there.
        assert header["value"] == cards_command.CATEGORY_HEADER_VALUE
        assert header["default"] is True
        assert header["emoji"]["id"] == str(
            cards_command.category_partial(category_id).id
        ), f"{category_id} menu is unmarked"
        assert cards.CATEGORY_BY_ID[category_id].short_name in header["label"]


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
        ("sort", cards_command.SORT_EMOJI),
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
        if n.get("custom_id") == "cards_account_page:0"
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
        cards_command._update_overview(account, inventory),
        cards_command._category_editor(account, inventory, "elixir"),
        cards_command._trades_view(account, []),
        cards_command._active_trade_notice(account.tag),
    ]
    seen = 0
    for view in views:
        for node in _view_nodes(view):
            label = str(node.get("label", "")).lower()
            if not any(
                word in label
                for word in ("back", "dashboard", "return", "all categories")
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
        cards_command._category_editor(account, _complete_inventory(), "dark_elixir")
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
        cards_command._category_editor(account, inventory, "elixir"),
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
    inventories = _ConfirmInventories([
        {"_id": "#ME", "cards": {given: 3, wanted: 0},
         "card_trade_reservations": {given: owner, wanted: owner}},
        {"_id": "#HOLDER", "cards": {given: 0, wanted: 2},
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
    # Only the confirmed card is unreserved.
    assert given not in inventories.documents["#ME"]["card_trade_reservations"]
    assert wanted in inventories.documents["#ME"]["card_trade_reservations"]


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
            if label in ("Back to board", "Back to Find trades"):
                marks[label] = (node.get("emoji") or {}).get("id")
        if len(marks) < 2:
            continue
        checked += 1
        assert marks["Back to board"] == str(cards_command.HOME_EMOJI.id)
        assert marks["Back to Find trades"] == str(
            cards_command.RETURN_EMOJI.id
        )
        assert marks["Back to board"] != marks["Back to Find trades"]
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


def test_the_proposal_dm_states_the_category_rule_and_the_gem_price():
    """The DM never mentioned gems, so a missing spare read as a dead trade."""
    trade = {
        "_id": "t1", "guild_id": 1,
        "wanted_card_id": "balloon",          # elixir, so 50 gems
        "given_card_id": "wizard",
        "requester_name": "Asker", "requester_tag": "#ME",
        "holder_name": "Holder", "holder_tag": "#H",
        "requester_clan_tag": "#A", "holder_clan_tag": "#A",
    }
    text = _view_text(cards_command._trade_proposal_dm(trade))

    assert "50 gems" in text
    assert "Only same-category trades exist" in text


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
    assert "they** post the trade offer" in text
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

    screens = [
        cards_command._holders_view(
            account, "balloon",
            cards.holders_for_card(inventory, [holder], "balloon"),
        ),
        cards_command._gem_ask_dm({
            "_id": "gem:#ME:#H:balloon", "card_id": "balloon",
            "gem_cost": 50, "asker_name": "A", "holder_name": "H",
        }),
        cards_command._trade_proposal_dm({
            "_id": "t1", "guild_id": 1,
            "wanted_card_id": "balloon", "given_card_id": "wizard",
            "requester_name": "A", "requester_tag": "#ME",
            "holder_name": "H", "holder_tag": "#H",
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

    assert "no spare" in text
    assert "50 gems" in text
    assert "you post the trade offer in game" in text
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


def test_a_live_swap_offers_one_button_whatever_the_clans_say():
    """The clan check used to be the ONLY control while a swap was move_needed.

    Somebody who had already sent their card in game could not record it until
    a scan agreed they were in the same clan. The bot cannot verify the clans
    at the moment cards actually move, so it no longer stands in the way.
    """
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    for status in ("move_needed", "ready", "accepted"):
        trade = _trade_document()
        trade.update({
            "status": status,
            "requester_discord_id": 111,
            "holder_discord_id": 222,
        })
        view = cards_command._trades_view(account, [trade])
        labels = [
            str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
        ]
        assert "I sent my card" in labels, status
        assert "Check clans" not in labels, status
        assert "Trade completed" not in labels, status


def test_a_side_that_already_confirmed_is_not_asked_again():
    account = Account(
        tag="#ME", name="Member", clan_tag="#HOME",
        clan_name="Home Clan", town_hall=18,
    )
    trade = _trade_document()
    trade.update({
        "status": "ready",
        "requester_discord_id": 111,
        "holder_discord_id": 222,
        "requester_confirmed_at": datetime.now(timezone.utc),
    })
    view = cards_command._trades_view(account, [trade])
    labels = [
        str(n.get("label")) for n in _view_nodes(view) if n.get("type") == 2
    ]

    assert "I sent my card" not in labels
    assert "Cancel" in labels


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
    inventory["cards"]["wizard"] = cards.DUPLICATE

    view = cards_command._category_editor(account, inventory, "elixir")
    nodes = _view_nodes(view)
    text = _view_text(view)

    menus = {
        str(n["custom_id"]).split(":")[0]: n
        for n in nodes if n.get("type") == 3
    }
    defaults = {
        name: {o["value"] for o in menu["options"] if o.get("default")}
        for name, menu in menus.items()
    }

    assert defaults["cards_set_missing"] == {"balloon"}
    assert defaults["cards_set_duplicates"] == {"wizard"}
    # Two menus, two handlers: one list can never overwrite the other.
    assert set(menus) == {"cards_set_missing", "cards_set_duplicates"}

    assert "Bulk edit" in text, "continuity with the button that opened it"
    assert "leaving without submitting changes nothing" in text
    assert "treated as **1 copy**" not in text
    assert "Sir Ruggie" not in text
    _assert_discord_payload(view)


def test_bulk_edit_screen_names_itself_and_the_step():
    """It read as a settings dialog from another product.

    Titled "Advanced manual editor" - which is not what the button that opens
    it says - and four buttons with no heading, so nothing told you what they
    were for. It also repeated the name and tag from the board one tap back.
    """
    account = Account(
        tag="#ME", name="Sir Ruggie", clan_tag="#MW",
        clan_name="Morning Woods", town_hall=18,
    )
    view = cards_command._update_overview(account, _complete_inventory())
    text = _view_text(view)

    assert "Bulk edit" in text
    assert "Advanced manual editor" not in text
    assert "Choose a category" in text
    # The board named them one tap ago; repeating it spends the best space on
    # the least useful fact.
    assert "Sir Ruggie" not in text
    assert "#ME" not in text
    # The single-card route is where most people should actually go.
    assert "category menus on the board" in text
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

    assert "Bulk edit" in labels
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

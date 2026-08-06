"""Regression tests for cross-clan /todo discovery and bounded retention."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.tasks import clan_history_tracker
from utils import clan_history, todo_data


class _Collection:
    def __init__(self, documents=None):
        self.operations = []
        self.documents = documents or []
        self.query = None

    async def bulk_write(self, operations, ordered=False):
        self.operations.extend(operations)
        return SimpleNamespace()

    def find(self, query, projection=None):
        self.query = query
        return _Cursor(self.documents)


class _Cursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length=None):
        return list(self.documents)


class _Mongo:
    def __init__(
        self,
        documents=None,
        clan_documents=None,
        watch_documents=None,
        roster_documents=None,
    ):
        self.player_clan_candidates = _Collection(documents)
        self.player_clan_watches = _Collection(watch_documents)
        self.clans = _Collection(clan_documents)
        self.clan_roster_snapshots = _Collection(roster_documents)


class _Member:
    def __init__(self, tag, attacks=0):
        self.tag = tag
        self.attacks = [object()] * attacks


class _Side:
    def __init__(self, tag, name, members):
        self.tag = tag
        self.name = name
        self.members = members
        self.badge = None


class _War:
    def __init__(self, clan_tag, clan_name, members, attacks_per_member):
        self.state = "inWar"
        self.clan = _Side(clan_tag, clan_name, members)
        self.opponent = _Side("#OPP", "Opponent", [])
        self.attacks_per_member = attacks_per_member
        self.end_time = None
        self.start_time = None

    def get_member(self, player_tag):
        return next((m for m in self.clan.members if m.tag == player_tag), None)


def _account():
    return todo_data.Account(
        tag="#PLAYER",
        name="Player",
        clan_tag="#HOME",
        clan_name="Home",
        town_hall=17,
    )


def test_history_and_watch_rows_have_bounded_ttl(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    monkeypatch.setattr(clan_history, "_indexes_failed", False)
    mongo = _Mongo()
    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)

    asyncio.run(clan_history.record_presence(
        mongo,
        [clan_history.ClanPresence("#PLAYER", "#CLAN", "Clan")],
        observed_at=now,
    ))
    asyncio.run(clan_history.watch_players(mongo, ["#PLAYER"], observed_at=now))
    asyncio.run(clan_history.save_roster_snapshots(
        mongo, {"#CLAN": {"#PLAYER"}}, observed_at=now
    ))

    history_update = mongo.player_clan_candidates.operations[0]._doc
    watch_update = mongo.player_clan_watches.operations[0]._doc
    roster_update = mongo.clan_roster_snapshots.operations[0]._doc
    assert history_update["$set"]["purge_at"] == now + timedelta(days=30)
    assert watch_update["$set"]["expires_at"] == now + timedelta(hours=48)
    assert roster_update["$set"]["purge_at"] == now + timedelta(days=30)


def test_candidate_query_accepts_recent_presence_or_active_roster(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    monkeypatch.setattr(clan_history, "_indexes_failed", False)
    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    mongo = _Mongo([{
        "player_tag": "#PLAYER",
        "clan_tag": "#CWL",
        "clan_name": "CWL Clan",
        "cwl_until": now + timedelta(hours=1),
    }])

    result = asyncio.run(clan_history.load_candidates(
        mongo, ["#PLAYER"], observed_at=now
    ))

    assert result["#PLAYER"][0].clan_tag == "#CWL"
    assert result["#PLAYER"][0].check_war is False
    assert result["#PLAYER"][0].check_cwl is True
    conditions = mongo.player_clan_candidates.query["$or"]
    assert {"last_seen_at": {"$gte": now - timedelta(hours=48)}} in conditions
    assert {"war_until": {"$gte": now}} in conditions
    assert {"cwl_until": {"$gte": now}} in conditions


def test_regular_war_and_cwl_can_come_from_different_clans(monkeypatch):
    account = _account()
    candidates = {
        "#PLAYER": [clan_history.ClanCandidate("#CWL", "CWL Clan")]
    }
    home_war = _War("#HOME", "Home", [_Member("#PLAYER", attacks=1)], 2)
    cwl_war = _War("#CWL", "CWL Clan", [_Member("#PLAYER", attacks=0)], 1)

    async def fake_war(_client, clan_tag):
        return ("war", home_war) if clan_tag == "#HOME" else ("none", None)

    async def fake_cwl(_client, clan_tag):
        return ("war", cwl_war) if clan_tag == "#CWL" else ("none", None)

    monkeypatch.setattr(todo_data, "_get_war", fake_war)
    monkeypatch.setattr(todo_data, "_get_cwl_round", fake_cwl)

    war_view = asyncio.run(todo_data.build_war_view(
        object(), [account], candidates=candidates
    ))
    cwl_view = asyncio.run(todo_data.build_cwl_view(
        object(), [account], candidates=candidates
    ))

    assert [(row.clan_tag, row.used, row.limit) for row in war_view.rows] == [
        ("#HOME", 1, 2)
    ]
    assert [(row.clan_tag, row.used, row.limit) for row in cwl_view.rows] == [
        ("#CWL", 0, 1)
    ]


def test_historical_candidate_not_on_roster_is_not_a_zero_attack_row(monkeypatch):
    candidate_war = _War("#OLD", "Old Clan", [_Member("#SOMEONE")], 2)

    async def fake_war(_client, clan_tag):
        if clan_tag == "#OLD":
            return "war", candidate_war
        return "none", None

    monkeypatch.setattr(todo_data, "_get_war", fake_war)
    view = asyncio.run(todo_data.build_war_view(
        object(),
        [_account()],
        candidates={"#PLAYER": [clan_history.ClanCandidate("#OLD", "Old Clan")]},
    ))

    assert view.rows == []


def test_historical_private_clan_appears_in_private_view(monkeypatch):
    async def fake_war(_client, clan_tag):
        if clan_tag == "#OLD":
            return "private", None
        return "none", None

    monkeypatch.setattr(todo_data, "_get_war", fake_war)
    view = asyncio.run(todo_data.build_blocked_view(
        object(),
        [_account()],
        candidates={"#PLAYER": [clan_history.ClanCandidate("#OLD", "Old Clan")]},
    ))

    assert [(row.tag, row.clan_tag, row.reason) for row in view.rows] == [
        ("#PLAYER", "#OLD", "private")
    ]


def test_private_only_war_result_is_marked_incomplete(monkeypatch):
    async def fake_war(_client, _clan_tag):
        return "private", None

    monkeypatch.setattr(todo_data, "_get_war", fake_war)
    view = asyncio.run(todo_data.build_war_view(object(), [_account()]))

    assert view.rows == []
    assert view.ok is True
    assert "private war logs" in view.incomplete
    assert view.notes == []


def test_cwl_only_candidate_is_not_checked_in_private_war_view(monkeypatch):
    requested = []

    async def fake_war(_client, clan_tag):
        requested.append(clan_tag)
        return "none", None

    monkeypatch.setattr(todo_data, "_get_war", fake_war)
    candidate = clan_history.ClanCandidate(
        "#CWL", "CWL Clan", check_war=False, check_cwl=True
    )
    asyncio.run(todo_data.build_blocked_view(
        object(), [_account()], candidates={"#PLAYER": [candidate]}
    ))

    assert requested == ["#HOME"]


def test_cwl_roster_candidate_does_not_trigger_regular_war_lookup(monkeypatch):
    requested = []

    async def fake_war(_client, clan_tag):
        requested.append(clan_tag)
        return "none", None

    monkeypatch.setattr(todo_data, "_get_war", fake_war)
    candidate = clan_history.ClanCandidate(
        "#CWL", "CWL Clan", check_war=False, check_cwl=True
    )
    asyncio.run(todo_data.build_war_view(
        object(), [_account()], candidates={"#PLAYER": [candidate]}
    ))

    assert requested == ["#HOME"]


def test_tracker_bootstraps_player_from_active_cwl_roster(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    monkeypatch.setattr(clan_history, "_indexes_failed", False)
    mongo = _Mongo(clan_documents=[{"tag": "#CWL", "type": "CWL"}])
    cwl_war = _War("#CWL", "CWL Clan", [_Member("#PLAYER")], 1)

    class _Client:
        async def get_clan(self, clan_tag):
            return _Side(clan_tag, "CWL Clan", [])

        async def get_player(self, player_tag):
            raise AssertionError(f"unexpected watched player {player_tag}")

    async def no_regular_war(_client, _clan_tag):
        return "none", None

    async def active_cwl(_client, _clan_tag):
        return "war", cwl_war

    monkeypatch.setattr(todo_data, "_get_war", no_regular_war)
    monkeypatch.setattr(todo_data, "_get_cwl_round", active_cwl)

    counts = asyncio.run(clan_history_tracker.run_scan(mongo, _Client()))

    assert counts["cwl_roster"] == 1
    cwl_updates = [
        operation._doc
        for operation in mongo.player_clan_candidates.operations
        if "cwl_until" in operation._doc.get("$max", {})
    ]
    assert len(cwl_updates) == 1
    assert cwl_updates[0]["$set"]["player_tag"] == "#PLAYER"


def test_tracker_follows_family_players_linked_alt_into_random_clan(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    monkeypatch.setattr(clan_history, "_indexes_failed", False)
    mongo = _Mongo(
        clan_documents=[{"tag": "#FAMILY", "type": "FWA"}],
        roster_documents=[{"_id": "#FAMILY", "members": ["#HOME"]}],
    )

    family_clan = _Side("#FAMILY", "Family", [])
    random_clan = SimpleNamespace(tag="#RANDOM", name="Random Clan", badge=None)

    class _Client:
        async def get_clan(self, clan_tag):
            assert clan_tag == "#FAMILY"
            return family_clan

        async def get_player(self, player_tag):
            clan = family_clan if player_tag == "#HOME" else random_clan
            return SimpleNamespace(tag=player_tag, clan=clan)

    async def linked_accounts(player_tags):
        assert player_tags == ["#HOME"]
        return ["#HOME", "#ALT"]

    async def no_regular_war(_client, _clan_tag):
        return "none", None

    monkeypatch.setattr(
        clan_history_tracker, "resolve_family_linked_tags", linked_accounts
    )
    monkeypatch.setattr(todo_data, "_get_war", no_regular_war)

    counts = asyncio.run(clan_history_tracker.run_scan(mongo, _Client()))

    assert counts["family_players"] == 0
    assert counts["departed_players"] == 1
    assert counts["movement_players"] == 2
    assert counts["watched_players"] == 2
    random_updates = [
        operation
        for operation in mongo.player_clan_candidates.operations
        if operation._filter == {"_id": "#ALT:#RANDOM"}
    ]
    assert len(random_updates) == 1


def test_stable_family_roster_does_not_rewrite_member_history(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    monkeypatch.setattr(clan_history, "_indexes_failed", False)
    mongo = _Mongo(
        clan_documents=[{"tag": "#FAMILY", "type": "FWA"}],
        roster_documents=[{"_id": "#FAMILY", "members": ["#HOME"]}],
    )
    family_clan = _Side("#FAMILY", "Family", [_Member("#HOME")])

    class _Client:
        async def get_clan(self, _clan_tag):
            return family_clan

        async def get_player(self, player_tag):
            raise AssertionError(f"unexpected watched player {player_tag}")

    async def no_regular_war(_client, _clan_tag):
        return "none", None

    monkeypatch.setattr(todo_data, "_get_war", no_regular_war)
    counts = asyncio.run(clan_history_tracker.run_scan(mongo, _Client()))

    assert counts["roster_changes"] == 0
    assert counts["departed_players"] == 0
    assert mongo.player_clan_candidates.operations == []


def test_link_expansion_backoff_does_not_extend_watch_retention(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    mongo = _Mongo()
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)

    result = asyncio.run(clan_history.postpone_link_expansions(
        mongo, {"#PLAYER": 0}, observed_at=now
    ))

    assert result is True
    update = mongo.player_clan_watches.operations[0]._doc
    assert update["$set"]["link_retry_at"] == now + timedelta(minutes=10)
    assert update["$inc"]["link_retry_count"] == 1
    assert "expires_at" not in update["$set"]


def test_link_expansion_backoff_clamps_large_retry_counts(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    mongo = _Mongo()
    now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)

    result = asyncio.run(clan_history.postpone_link_expansions(
        mongo, {"#PLAYER": 10_000}, observed_at=now
    ))

    assert result is True
    update = mongo.player_clan_watches.operations[0]._doc
    assert update["$set"]["link_retry_at"] == now + timedelta(hours=6)


def test_departure_link_failure_is_queued_for_later_retry(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    monkeypatch.setattr(clan_history, "_indexes_failed", False)
    mongo = _Mongo(
        clan_documents=[{"tag": "#FAMILY", "type": "FWA"}],
        roster_documents=[{
            "_id": "#FAMILY", "members": ["#HOME", "#DEPARTED"]
        }],
    )
    family_clan = _Side("#FAMILY", "Family", [_Member("#HOME")])
    random_clan = SimpleNamespace(tag="#RANDOM", name="Random Clan", badge=None)

    class _Client:
        async def get_clan(self, _clan_tag):
            return family_clan

        async def get_player(self, player_tag):
            return SimpleNamespace(tag=player_tag, clan=random_clan)

    async def link_service_down(player_tags):
        assert player_tags == ["#DEPARTED"]
        return None

    async def no_regular_war(_client, _clan_tag):
        return "none", None

    monkeypatch.setattr(
        clan_history_tracker, "resolve_family_linked_tags", link_service_down
    )
    monkeypatch.setattr(todo_data, "_get_war", no_regular_war)

    counts = asyncio.run(clan_history_tracker.run_scan(mongo, _Client()))

    assert counts["departed_players"] == 1
    source_updates = [
        operation._doc
        for operation in mongo.player_clan_watches.operations
        if operation._filter.get("_id") == "#DEPARTED"
    ]
    assert source_updates[0]["$set"]["link_expand_pending"] is True
    assert source_updates[1]["$inc"]["link_retry_count"] == 1
    assert mongo.clan_roster_snapshots.operations


def test_tracker_retries_link_expansion_after_roster_is_already_stable(monkeypatch):
    monkeypatch.setattr(clan_history, "_indexes_ready", True)
    monkeypatch.setattr(clan_history, "_indexes_failed", False)
    now = datetime.now(timezone.utc)
    mongo = _Mongo(
        clan_documents=[{"tag": "#FAMILY", "type": "FWA"}],
        watch_documents=[{
            "_id": "#DEPARTED",
            "expires_at": now + timedelta(hours=12),
            "link_expand_pending": True,
            "link_retry_at": now - timedelta(minutes=1),
            "link_retry_count": 1,
        }],
        roster_documents=[{"_id": "#FAMILY", "members": ["#HOME"]}],
    )
    family_clan = _Side("#FAMILY", "Family", [_Member("#HOME")])
    random_clan = SimpleNamespace(tag="#RANDOM", name="Random Clan", badge=None)

    class _Client:
        async def get_clan(self, _clan_tag):
            return family_clan

        async def get_player(self, player_tag):
            return SimpleNamespace(tag=player_tag, clan=random_clan)

    async def linked_accounts(player_tags):
        assert player_tags == ["#DEPARTED"]
        return ["#DEPARTED", "#ALT"]

    async def no_regular_war(_client, _clan_tag):
        return "none", None

    monkeypatch.setattr(
        clan_history_tracker, "resolve_family_linked_tags", linked_accounts
    )
    monkeypatch.setattr(todo_data, "_get_war", no_regular_war)

    counts = asyncio.run(clan_history_tracker.run_scan(mongo, _Client()))

    assert counts["departed_players"] == 0
    assert counts["watched_players"] == 2
    expiring_watch_ids = {
        operation._filter["_id"]
        for operation in mongo.player_clan_watches.operations
        if "expires_at" in operation._doc.get("$set", {})
    }
    assert expiring_watch_ids == {"#ALT"}
    random_ids = {
        operation._filter["_id"]
        for operation in mongo.player_clan_candidates.operations
    }
    assert "#ALT:#RANDOM" in random_ids
    completion_updates = [
        operation._doc
        for operation in mongo.player_clan_watches.operations
        if "$unset" in operation._doc
    ]
    assert len(completion_updates) == 1

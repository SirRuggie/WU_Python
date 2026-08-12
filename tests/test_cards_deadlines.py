import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from extensions.commands import cards as cards_command
from extensions.tasks import cards_deadlines as sweeper


class _Trades:
    def __init__(self, documents):
        self.docs = {d["_id"]: d for d in documents}

    def find(self, query):
        return _Cursor(list(self._matching(query)))

    def _matching(self, query):
        for doc in self.docs.values():
            if _matches(doc, query):
                yield dict(doc)

    async def find_one(self, query):
        return next(iter(self._matching(query)), None)

    async def update_one(self, query, update):
        doc = self.docs.get(query.get("_id"))
        if doc is None or not _matches(doc, query):
            return SimpleNamespace(modified_count=0)
        doc.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        return SimpleNamespace(modified_count=1)


class _Inventories:
    def __init__(self, documents):
        self.docs = {d["_id"]: d for d in documents}

    def find(self, query):
        return _Cursor([
            dict(d) for d in self.docs.values() if _matches(d, query)
        ])

    async def find_one(self, query):
        doc = self.docs.get(query.get("_id"))
        return dict(doc) if doc else None

    async def find_one_and_update(self, query, update, **_kwargs):
        doc = self.docs.get(query.get("_id"))
        if doc is None:
            return None
        for key, delta in (update.get("$inc") or {}).items():
            doc[key] = int(doc.get(key) or 0) + delta
        doc.update(update.get("$set", {}))
        return dict(doc)

    async def update_one(self, query, update):
        doc = self.docs.get(query.get("_id"))
        if doc is None or not _matches(doc, query):
            return SimpleNamespace(modified_count=0)
        # Dotted paths are nested writes, not literal keys - getting this wrong
        # made the fake silently disagree with Mongo.
        for key, value in (update.get("$set") or {}).items():
            _write(doc, key, value)
        for key, delta in (update.get("$inc") or {}).items():
            _write(doc, key, int(_read(doc, key) or 0) + delta)
        for key in update.get("$unset", {}):
            head, _, leaf = key.partition(".")
            if leaf:
                doc.get(head, {}).pop(leaf, None)
            else:
                doc.pop(head, None)
        return SimpleNamespace(modified_count=1)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, length=None):
        return self.rows[:length] if length else self.rows


def _read(doc, path):
    for part in path.split("."):
        doc = (doc or {}).get(part) if isinstance(doc, dict) else None
    return doc


def _write(doc, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


def _matches(doc, query) -> bool:
    for key, want in query.items():
        if key in ("$or", "$and"):
            continue
        have = doc
        for part in key.split("."):
            have = (have or {}).get(part) if isinstance(have, dict) else None
        if isinstance(want, dict):
            if "$lte" in want and not (have is not None and have <= want["$lte"]):
                return False
            if "$gte" in want and not (have is not None and have >= want["$gte"]):
                return False
            if "$in" in want and have not in want["$in"]:
                return False
            if "$ne" in want and have == want["$ne"]:
                return False
            if "$exists" in want and (have is not None) != want["$exists"]:
                return False
        elif have != want:
            return False
    return True


class _Rest:
    def __init__(self):
        self.dms = []

    async def create_dm_channel(self, discord_id):
        return f"dm-{discord_id}"

    async def create_message(self, **kwargs):
        self.dms.append(kwargs)
        return SimpleNamespace(id=1)


def _install(monkeypatch, trades, inventories):
    rest = _Rest()
    monkeypatch.setattr(sweeper, "bot_instance", SimpleNamespace(rest=rest))
    monkeypatch.setattr(
        sweeper, "mongo_client",
        SimpleNamespace(card_trades=trades, card_inventories=inventories),
    )

    async def _noop(*_a, **_k):
        return True

    for name in (
        "_release_proposal_slots", "_finish_trade_cleanup",
    ):
        monkeypatch.setattr(cards_command, name, _noop)
    return rest


def _pending(trade_id, *, overdue: bool, holder="#HOLDER"):
    now = datetime.now(timezone.utc)
    return {
        "_id": trade_id, "kind": "trade", "status": "pending",
        "guild_id": 1,
        "wanted_card_id": "balloon", "given_card_id": "electro_dragon",
        "requester_tag": "#ME", "requester_name": "Requester",
        "requester_discord_id": 111,
        "holder_tag": holder, "holder_name": "Holder",
        "holder_discord_id": 222,
        "accept_deadline_at": now - timedelta(hours=1) if overdue
        else now + timedelta(hours=11),
    }


def test_an_unanswered_proposal_expires_and_counts_against_the_holder(monkeypatch):
    trades = _Trades([_pending("t1", overdue=True)])
    inventories = _Inventories([{"_id": "#HOLDER", "player_name": "Holder"}])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert trades.docs["t1"]["status"] == "expired"
    assert inventories.docs["#HOLDER"]["ignored_requests"] == 1
    # Both sides are told, so neither is left waiting on a dead proposal.
    assert len(rest.dms) == 2


def test_a_proposal_inside_its_window_is_left_alone(monkeypatch):
    trades = _Trades([_pending("t1", overdue=False)])
    inventories = _Inventories([{"_id": "#HOLDER"}])
    _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert trades.docs["t1"]["status"] == "pending"
    assert "ignored_requests" not in inventories.docs["#HOLDER"]


def test_the_second_ignored_request_triggers_the_check_in(monkeypatch):
    trades = _Trades([_pending("t1", overdue=True)])
    inventories = _Inventories([
        {"_id": "#HOLDER", "player_name": "Holder", "ignored_requests": 1},
    ])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert inventories.docs["#HOLDER"]["ignored_requests"] == 2
    assert inventories.docs["#HOLDER"]["checkin_sent_at"] is not None
    text = " ".join(str(dm) for dm in rest.dms)
    assert "still trading" in text.lower()


def test_the_check_in_is_only_ever_sent_once(monkeypatch):
    """Otherwise every later expiry would ask again and never resolve."""
    trades = _Trades([_pending("t1", overdue=True)])
    inventories = _Inventories([{
        "_id": "#HOLDER", "player_name": "Holder",
        "ignored_requests": 5,
        "checkin_sent_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    text = " ".join(str(dm) for dm in rest.dms)
    assert "still trading" not in text.lower()


def test_silence_after_the_check_in_hides_them(monkeypatch):
    trades = _Trades([])
    inventories = _Inventories([{
        "_id": "#QUIET",
        "checkin_sent_at": datetime.now(timezone.utc) - timedelta(hours=25),
    }])
    _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert inventories.docs["#QUIET"]["trading_paused"] is True
    # The stamp is cleared so re-enabling does not immediately re-pause them.
    assert inventories.docs["#QUIET"]["checkin_sent_at"] is None


def test_someone_still_inside_the_check_in_window_is_untouched(monkeypatch):
    trades = _Trades([])
    inventories = _Inventories([{
        "_id": "#THINKING",
        "checkin_sent_at": datetime.now(timezone.utc) - timedelta(hours=2),
    }])
    _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert inventories.docs["#THINKING"].get("trading_paused") is not True


def test_a_quiet_side_is_auto_confirmed_after_seven_days(monkeypatch):
    now = datetime.now(timezone.utc)
    owner = "t9:tok"
    trades = _Trades([{
        "_id": "t9", "kind": "trade", "status": "ready", "guild_id": 1,
        "reservation_token": "tok",
        "wanted_card_id": "balloon", "given_card_id": "electro_dragon",
        "requester_tag": "#ME", "requester_name": "Requester",
        "requester_discord_id": 111,
        "holder_tag": "#HOLDER", "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_confirmed_at": now - timedelta(days=8),
        "confirm_deadline_at": now - timedelta(days=1),
    }])
    inventories = _Inventories([
        {"_id": "#ME", "guild_id": 1,
         "cards": {"electro_dragon": 2, "balloon": 0},
         "card_trade_reservations": {"balloon": owner}},
        {"_id": "#HOLDER", "guild_id": 1,
         "cards": {"balloon": 3, "electro_dragon": 0},
         "card_trade_reservations": {
             "balloon": owner, "electro_dragon": owner,
         }},
    ])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    # The holder never answered, so their card moved for them.
    assert inventories.docs["#HOLDER"]["cards"]["balloon"] == 2
    assert inventories.docs["#ME"]["cards"]["balloon"] == cards_command.OWNED
    assert trades.docs["t9"]["holder_confirmed_at"] is not None
    text = " ".join(str(dm) for dm in rest.dms)
    assert "deducted automatically" in text


def test_a_swap_neither_side_confirms_is_closed_and_freed(monkeypatch):
    now = datetime.now(timezone.utc)
    trades = _Trades([{
        "_id": "t7", "kind": "trade", "status": "move_needed", "guild_id": 1,
        "reservation_token": "tok",
        "wanted_card_id": "balloon", "given_card_id": "electro_dragon",
        "requester_tag": "#ME", "requester_name": "Requester",
        "requester_discord_id": 111,
        "holder_tag": "#HOLDER", "holder_name": "Holder",
        "holder_discord_id": 222,
        "backstop_at": now - timedelta(hours=1),
    }])
    inventories = _Inventories([{"_id": "#ME"}, {"_id": "#HOLDER"}])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert trades.docs["t7"]["status"] == "expired"
    text = " ".join(str(dm) for dm in rest.dms)
    assert "Neither of you confirmed" in text


def test_a_swap_one_side_confirmed_is_not_hit_by_the_backstop(monkeypatch):
    """The backstop exists only for swaps nobody answered at all."""
    now = datetime.now(timezone.utc)
    trades = _Trades([{
        "_id": "t8", "kind": "trade", "status": "ready", "guild_id": 1,
        "reservation_token": "tok",
        "wanted_card_id": "balloon", "given_card_id": "electro_dragon",
        "requester_tag": "#ME", "requester_name": "R",
        "requester_discord_id": 111,
        "holder_tag": "#HOLDER", "holder_name": "H", "holder_discord_id": 222,
        "requester_confirmed_at": now - timedelta(days=1),
        "backstop_at": now - timedelta(hours=1),
        "confirm_deadline_at": now + timedelta(days=6),
    }])
    inventories = _Inventories([{"_id": "#ME"}, {"_id": "#HOLDER"}])
    _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert trades.docs["t8"]["status"] == "ready"


def test_the_confirm_window_is_seven_days_not_one():
    assert cards_command.SWAP_CONFIRM_FOR == timedelta(days=7)
    assert cards_command.SWAP_ACCEPT_FOR == timedelta(hours=12)
    assert cards_command.SWAP_BACKSTOP_FOR == timedelta(days=7)
    assert cards_command.CHECKIN_ANSWER_FOR == timedelta(hours=24)
    assert cards_command.IGNORED_BEFORE_CHECKIN == 2

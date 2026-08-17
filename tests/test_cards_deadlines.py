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
        if key == "$or":
            if not any(_matches(doc, branch) for branch in want):
                return False
            continue
        if key == "$and":
            if not all(_matches(doc, branch) for branch in want):
                return False
            continue
        have = doc
        for part in key.split("."):
            have = (have or {}).get(part) if isinstance(have, dict) else None
        if isinstance(want, dict):
            if "$lte" in want and not (have is not None and have <= want["$lte"]):
                return False
            if "$gte" in want and not (have is not None and have >= want["$gte"]):
                return False
            if "$lt" in want and not (have is not None and have < want["$lt"]):
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
        self.edits = []
        self.fetched = []

    async def create_dm_channel(self, discord_id):
        return f"dm-{discord_id}"

    async def create_message(self, **kwargs):
        self.dms.append(kwargs)
        return SimpleNamespace(id=1)

    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(id=kwargs.get("message"))

    async def fetch_channel(self, channel_id):
        # Only a NEW channel post fetches the channel first; recording the
        # fetch lets a test pin that a job never even tried to post.
        self.fetched.append(int(channel_id))
        return SimpleNamespace(guild_id=0)


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
    # The "expired" policy row: nobody is DMed about a proposal neither
    # player touched for 12 hours - the standing post (when one exists) is
    # the only surface that changes.
    assert rest.dms == []


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

    # The holder never answered, so their WHOLE side settled for them:
    # their card was deducted and the card they agreed to receive came in.
    assert inventories.docs["#HOLDER"]["cards"]["balloon"] == 2
    assert inventories.docs["#HOLDER"]["cards"]["electro_dragon"] == (
        cards_command.OWNED
    )
    assert inventories.docs["#HOLDER"]["card_trade_reservations"] == {}
    # The requester's stuck old-style incoming credit was delivered by the
    # confirmed-side sweeper, and their lock released with it.
    assert inventories.docs["#ME"]["cards"]["balloon"] == cards_command.OWNED
    assert inventories.docs["#ME"]["card_trade_reservations"] == {}
    assert trades.docs["t9"]["holder_confirmed_at"] is not None
    assert trades.docs["t9"]["status"] == "completed"
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


def test_a_no_spare_auto_settle_still_settles_the_side_and_stays_quiet(
    monkeypatch,
):
    """No spare on the silent side no longer touches the waiting player.

    The silent side's debit is refused by the spare guard, but their side
    still settles: their incoming card is credited, their locks release, and
    the trade completes recording the unmoved leg. The waiting player's own
    confirmation is what credits THEIR card (delivered by the confirmed-side
    sweeper for old-style confirms), so the old "was not added" DM to them
    is retired - there is nothing left to break the news about.
    """
    now = datetime.now(timezone.utc)
    owner = "t10:tok"
    trades = _Trades([{
        "_id": "t10", "kind": "trade", "status": "ready", "guild_id": 1,
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
        # The holder's spare is gone, so the guarded move must refuse.
        {"_id": "#HOLDER", "guild_id": 1,
         "cards": {"balloon": 1, "electro_dragon": 0},
         "card_trade_reservations": {
             "balloon": owner, "electro_dragon": owner,
         }},
    ])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    # The refused debit: the holder's last copy stays theirs.
    assert inventories.docs["#HOLDER"]["cards"]["balloon"] == 1
    # But their side still settles: incoming credit and released locks.
    assert inventories.docs["#HOLDER"]["cards"]["electro_dragon"] == (
        cards_command.OWNED
    )
    assert inventories.docs["#HOLDER"]["card_trade_reservations"] == {}
    # The waiting player's card came from their own confirmation, not from
    # the silent side's spare situation.
    assert inventories.docs["#ME"]["cards"]["balloon"] == cards_command.OWNED
    assert inventories.docs["#ME"]["card_trade_reservations"] == {}
    # The trade still closes - that is the documented design - but the
    # document records that this leg never moved.
    assert trades.docs["t10"]["status"] == "completed"
    assert trades.docs["t10"]["holder_auto_settled"] == "no_spare"
    text = " ".join(str(dm) for dm in rest.dms)
    assert "your card was not removed" in text, "the silent side is told"
    assert "was not added" not in text, "the owed-player DM is retired"
    assert all(dm.get("channel") == "dm-222" for dm in rest.dms), (
        "only the auto-settled side is DMed"
    )


def _half_confirmed_old_style(trade_id="t11"):
    """A live trade whose requester confirmed under the OLD semantics.

    Their sent card already moved on both accounts back then, so both
    electro_dragon markers are gone - but their incoming card (balloon) is
    still reserved on their inventory and was never credited. This is the
    exact mid-flight shape the migration sweeper exists for.
    """
    now = datetime.now(timezone.utc)
    owner = f"{trade_id}:tok"
    trades = _Trades([{
        "_id": trade_id, "kind": "trade", "status": "ready", "guild_id": 1,
        "reservation_token": "tok",
        "wanted_card_id": "balloon", "given_card_id": "electro_dragon",
        "requester_tag": "#ME", "requester_name": "Requester",
        "requester_discord_id": 111,
        "holder_tag": "#HOLDER", "holder_name": "Holder",
        "holder_discord_id": 222,
        "requester_confirmed_at": now - timedelta(hours=2),
        # The partner still has days: only the migration job may act.
        "confirm_deadline_at": now + timedelta(days=6),
    }])
    inventories = _Inventories([
        {"_id": "#ME", "guild_id": 1,
         "cards": {"electro_dragon": 2, "balloon": 0},
         "card_trade_reservations": {"balloon": owner}},
        {"_id": "#HOLDER", "guild_id": 1,
         "cards": {"balloon": 3, "electro_dragon": 1},
         "card_trade_reservations": {"balloon": owner}},
    ])
    return trades, inventories


def test_a_stuck_old_style_credit_is_delivered_silently(monkeypatch):
    """The migration sweeper frees the member who did everything right.

    The live report: a member confirmed, their sent card moved, and their
    incoming card sat at "in a trade · 0" for days because the partner went
    quiet. The sweeper credits it (fenced on the marker + owner, guarded
    below OWNED), releases their locks, and tells nobody - their own tap
    already said everything.
    """
    trades, inventories = _half_confirmed_old_style()
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    me = inventories.docs["#ME"]
    assert me["cards"]["balloon"] == cards_command.OWNED
    assert me["card_trade_reservations"] == {}
    assert me["inventory_revision"] == 1
    # The quiet partner is untouched: their deadline has not passed.
    assert inventories.docs["#HOLDER"]["cards"]["balloon"] == 3
    assert inventories.docs["#HOLDER"]["cards"]["electro_dragon"] == 1
    assert "balloon" in inventories.docs["#HOLDER"]["card_trade_reservations"]
    assert trades.docs["t11"]["status"] == "ready"
    # Zero DMs, zero posts: the silent policy.
    assert rest.dms == []
    assert rest.edits == []
    assert rest.fetched == []


def test_the_confirmed_side_settle_is_idempotent(monkeypatch):
    """Running the sweeper twice changes nothing the second time."""
    trades, inventories = _half_confirmed_old_style()
    _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())
    first_me = dict(inventories.docs["#ME"])
    first_holder = dict(inventories.docs["#HOLDER"])

    asyncio.run(sweeper.sweep_once())

    assert inventories.docs["#ME"] == first_me
    assert inventories.docs["#HOLDER"] == first_holder
    assert inventories.docs["#ME"]["inventory_revision"] == 1, (
        "the guarded credit must not re-apply"
    )


def test_a_new_style_confirmed_side_is_left_alone(monkeypatch):
    """A side settled by its own tap carries no marker; the sweeper no-ops."""
    trades, inventories = _half_confirmed_old_style(trade_id="t12")
    # Per-side settlement already ran for the requester: credit delivered,
    # markers gone.
    inventories.docs["#ME"]["cards"]["balloon"] = cards_command.OWNED
    inventories.docs["#ME"]["card_trade_reservations"] = {}
    _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert inventories.docs["#ME"]["cards"]["balloon"] == cards_command.OWNED
    assert "inventory_revision" not in inventories.docs["#ME"], (
        "no write may land on an already-settled side"
    )


def _open_request(request_id, *, overdue: bool, message_id=901):
    now = datetime.now(timezone.utc)
    return {
        "_id": request_id, "kind": "open_request", "status": "open",
        "guild_id": 1, "generation": 1723800000,
        "category": "elixir",
        "wanted_card_id": "balloon",
        "offer_card_ids": ["electro_dragon"],
        "requester_tag": "#ME", "requester_name": "Requester",
        "requester_discord_id": 111, "requester_town_hall": 17,
        "channel_id": 555, "channel_message_id": message_id,
        "channel_post_v2": True,
        "claim_token": None, "claim_until": None,
        "claimed_by_discord_id": None, "claimed_by_tag": None,
        "claimed_at": None, "trade_id": None,
        "open_request_key": f"1:#ME:balloon:{request_id}",
        "expires_at": now - timedelta(hours=1) if overdue
        else now + timedelta(hours=1),
    }


def _claiming(request_id, *, stalled: bool):
    now = datetime.now(timezone.utc)
    doc = _open_request(request_id, overdue=False)
    doc.update(
        status="claiming",
        claim_token="tok",
        claim_until=(
            now - timedelta(seconds=30) if stalled
            else now + timedelta(seconds=90)
        ),
        claimed_by_discord_id=222,
        claimed_by_tag="#CLAIMER",
    )
    return doc


def test_an_expired_open_request_closes_silently(monkeypatch):
    """State + key unset + terminal edit - and NOBODY is told.

    A want-ad expiring after 48 quiet hours is the definition of
    nobody-needs-to-know: no DM, no ping, no new post.
    """
    trades = _Trades([_open_request("r1", overdue=True)])
    rest = _install(monkeypatch, trades, _Inventories([]))

    asyncio.run(sweeper.sweep_once())

    doc = trades.docs["r1"]
    assert doc["status"] == "expired"
    assert "open_request_key" not in doc, "$unset frees the card for later"
    assert rest.dms == []
    assert rest.fetched == [], "expiry may never create a channel message"
    assert len(rest.edits) == 1
    assert rest.edits[0]["message"] == 901
    assert "Expired" in str(rest.edits[0]["components"])


def test_an_open_request_inside_its_window_is_left_alone(monkeypatch):
    trades = _Trades([_open_request("r1", overdue=False)])
    rest = _install(monkeypatch, trades, _Inventories([]))

    asyncio.run(sweeper.sweep_once())

    assert trades.docs["r1"]["status"] == "open"
    assert "open_request_key" in trades.docs["r1"]
    assert rest.edits == []


def test_a_stalled_claim_returns_to_the_board(monkeypatch):
    trades = _Trades([_claiming("r2", stalled=True)])
    rest = _install(monkeypatch, trades, _Inventories([]))

    asyncio.run(sweeper.sweep_once())

    doc = trades.docs["r2"]
    assert doc["status"] == "open"
    for field in (
        "claim_token", "claim_until", "claimed_by_discord_id",
        "claimed_by_tag", "claimed_at",
    ):
        assert field not in doc, f"{field} must be unset by the recovery"
    # The one-request-per-card key was never unset during claiming, so the
    # round trip leaves the duplicate guard intact.
    assert doc["open_request_key"] == "1:#ME:balloon:r2"
    # The public post never changed during claiming: no edit, no DM.
    assert rest.edits == []
    assert rest.dms == []


def test_a_fresh_claim_survives_the_recovery_sweep(monkeypatch):
    trades = _Trades([_claiming("r3", stalled=False)])
    _install(monkeypatch, trades, _Inventories([]))

    asyncio.run(sweeper.sweep_once())

    assert trades.docs["r3"]["status"] == "claiming"
    assert trades.docs["r3"]["claim_token"] == "tok"


def test_a_claim_refreshed_between_read_and_write_survives():
    """The recovery CAS is fenced on the stale deadline, not just status.

    The sweeper's query saw a stale claim, but by the time it writes, a
    second member has re-claimed with a fresh claim_until. The write must
    miss - only the deadline it read as expired may be reverted.
    """
    past = datetime.now(timezone.utc) - timedelta(seconds=30)

    class _StaleRead(_Trades):
        def find(self, _query):
            return _Cursor([
                dict(doc, claim_until=past) for doc in self.docs.values()
            ])

    trades = _StaleRead([_claiming("r4", stalled=False)])

    asyncio.run(sweeper._recover_stalled_claims(
        SimpleNamespace(card_trades=trades), None,
        now=datetime.now(timezone.utc),
    ))

    assert trades.docs["r4"]["status"] == "claiming"
    assert trades.docs["r4"]["claim_token"] == "tok"


def test_proposal_expiry_edits_the_post_and_dms_nobody(monkeypatch):
    """Expiry routes through the delivery policy: the standing post
    collapses to its closed form, with zero DMs and zero new messages."""
    trade = _pending("t1", overdue=True)
    trade.update(channel_id=555, channel_message_id=901, channel_post_v2=True)
    trades = _Trades([trade])
    inventories = _Inventories([{"_id": "#HOLDER", "player_name": "Holder"}])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert trades.docs["t1"]["status"] == "expired"
    assert rest.dms == []
    assert rest.fetched == [], "expiry may never create a channel message"
    assert len(rest.edits) == 1
    assert rest.edits[0]["message"] == 901
    assert "Closed" in str(rest.edits[0]["components"])


def test_expiry_still_sends_the_checkin_when_the_threshold_hits(monkeypatch):
    """The check-in DM is the deliberate exception to silent expiry."""
    trade = _pending("t1", overdue=True)
    trade.update(channel_id=555, channel_message_id=901, channel_post_v2=True)
    trades = _Trades([trade])
    inventories = _Inventories([
        {"_id": "#HOLDER", "player_name": "Holder", "ignored_requests": 1},
    ])
    rest = _install(monkeypatch, trades, inventories)

    asyncio.run(sweeper.sweep_once())

    assert len(rest.edits) == 1, "the silent post edit still happens"
    text = " ".join(str(dm) for dm in rest.dms)
    assert "still trading" in text.lower(), "the check-in DM is preserved"


def test_over_budget_edits_still_change_state_and_drain_next_pass(monkeypatch):
    """A CAS is never deferred for a cosmetic edit; the edit rides later."""
    monkeypatch.setattr(sweeper, "SWEEP_CHANNEL_EDIT_BUDGET", 1)
    trades = _Trades([
        _open_request("r1", overdue=True, message_id=901),
        _open_request("r2", overdue=True, message_id=902),
    ])
    rest = _install(monkeypatch, trades, _Inventories([]))

    asyncio.run(sweeper.sweep_once())

    # Both state transitions landed in the SAME pass.
    assert trades.docs["r1"]["status"] == "expired"
    assert trades.docs["r2"]["status"] == "expired"
    assert len(rest.edits) == 1
    pending = [
        doc for doc in trades.docs.values()
        if doc.get("channel_edit_pending")
    ]
    assert len(pending) == 1, "the over-budget doc is marked, not lost"

    asyncio.run(sweeper.sweep_once())

    # The deferred edit drains on the next pass and the marker comes off.
    assert {edit["message"] for edit in rest.edits} == {901, 902}
    assert not any(
        doc.get("channel_edit_pending") for doc in trades.docs.values()
    )


def test_sweep_once_wires_every_job_through_one_shared_budget(monkeypatch):
    calls = []

    def _record(name):
        async def _job(*_a, **kwargs):
            calls.append((name, kwargs.get("edit_budget")))
            return 0
        return _job

    jobs = (
        "_drain_pending_channel_edits", "_expire_unanswered_proposals",
        "_pause_silent_members", "_recover_interrupted_completions",
        # Stuck credits deliver BEFORE the seven-day settle can complete and
        # clean up the same trades.
        "_settle_confirmed_sides",
        "_finish_one_sided_swaps", "_close_abandoned_swaps",
        "_expire_open_requests", "_recover_stalled_claims",
    )
    for name in jobs:
        monkeypatch.setattr(sweeper, name, _record(name))
    monkeypatch.setattr(sweeper, "bot_instance", SimpleNamespace())
    monkeypatch.setattr(sweeper, "mongo_client", SimpleNamespace())

    asyncio.run(sweeper.sweep_once())

    assert [name for name, _budget in calls] == list(jobs)
    budgets = {
        id(budget) for _name, budget in calls if budget is not None
    }
    assert len(budgets) == 1, "one budget must bound the whole pass"
    assert [name for name, budget in calls if budget is not None] == [
        "_drain_pending_channel_edits",
        "_expire_unanswered_proposals",
        "_expire_open_requests",
    ], "exactly the jobs that edit standing posts share the cap"

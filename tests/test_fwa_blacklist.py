import asyncio
from types import SimpleNamespace

from extensions.commands.fwa import blacklist, war_plans
from utils import fwa_blacklist


class _UpdateResult:
    pass


class _DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class _FindResult:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction=1):
        self._docs.sort(key=lambda d: d.get(field), reverse=(direction < 0))
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    """Fake mongo.fwa_blacklist keyed by _id, close enough to real Mongo
    semantics for $set / $setOnInsert / $in to be exercised here."""

    def __init__(self, docs=None):
        self.docs = {doc["_id"]: dict(doc) for doc in (docs or [])}

    async def find_one(self, query):
        return self.docs.get(query["_id"])

    async def update_one(self, query, update, upsert=False):
        _id = query["_id"]
        existing = self.docs.get(_id)
        if existing is None:
            if not upsert:
                return _UpdateResult()
            doc = {"_id": _id}
            doc.update(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            self.docs[_id] = doc
        else:
            existing.update(update.get("$set", {}))
        return _UpdateResult()

    async def delete_one(self, query):
        _id = query["_id"]
        if _id in self.docs:
            del self.docs[_id]
            return _DeleteResult(1)
        return _DeleteResult(0)

    def find(self, query=None, projection=None):
        query = query or {}
        if "_id" in query and "$in" in query["_id"]:
            wanted = set(query["_id"]["$in"])
            return _FindResult([doc for _id, doc in self.docs.items() if _id in wanted])
        return _FindResult(list(self.docs.values()))


class _Mongo:
    def __init__(self, collection):
        self.fwa_blacklist = collection


def test_add_blacklisted_keeps_original_added_at_and_source_on_refresh():
    collection = _FakeCollection()
    mongo = _Mongo(collection)

    asyncio.run(fwa_blacklist.add_blacklisted(
        mongo, "#abc123", "Old Name", 111, "Staffer1", "war-plans",
        our_clan_tag="OURTAG", war_end_time="2026-09-08T20:00:00",
    ))
    first_added_at = collection.docs["ABC123"]["added_at"]

    asyncio.run(fwa_blacklist.add_blacklisted(
        mongo, "abc123", "New Name", 222, "Staffer2", "manual",
        our_clan_tag="OURTAG2", war_end_time="2026-09-09T20:00:00",
    ))

    doc = collection.docs["ABC123"]
    assert doc["name"] == "New Name"
    assert doc["last_seen_clan_tag"] == "OURTAG2"
    assert doc["last_war_end_time"] == "2026-09-09T20:00:00"
    # Untouched on the second (refresh) call.
    assert doc["added_at"] == first_added_at
    assert doc["added_by_id"] == 111
    assert doc["added_by_name"] == "Staffer1"
    assert doc["source"] == "war-plans"


def test_remove_blacklisted_returns_false_when_missing():
    collection = _FakeCollection()
    mongo = _Mongo(collection)

    assert asyncio.run(fwa_blacklist.remove_blacklisted(mongo, "NOTHERE")) is False


def test_remove_blacklisted_returns_true_and_deletes_existing():
    collection = _FakeCollection([{"_id": "ABC123", "name": "Some Clan"}])
    mongo = _Mongo(collection)

    assert asyncio.run(fwa_blacklist.remove_blacklisted(mongo, "#abc123")) is True
    assert "ABC123" not in collection.docs


def test_is_blacklisted():
    collection = _FakeCollection([{"_id": "ABC123", "name": "Some Clan"}])
    mongo = _Mongo(collection)

    assert asyncio.run(fwa_blacklist.is_blacklisted(mongo, "#ABC123")) is True
    assert asyncio.run(fwa_blacklist.is_blacklisted(mongo, "#OTHER")) is False


def test_blacklisted_tags_returns_only_matching_sanitized_tags():
    collection = _FakeCollection([
        {"_id": "ABC123", "name": "Clan A"},
        {"_id": "DEF456", "name": "Clan B"},
    ])
    mongo = _Mongo(collection)

    result = asyncio.run(fwa_blacklist.blacklisted_tags(mongo, ["#abc123", "#zzz999"]))
    assert result == {"ABC123"}


def test_blacklisted_tags_empty_input_short_circuits():
    collection = _FakeCollection()
    mongo = _Mongo(collection)

    assert asyncio.run(fwa_blacklist.blacklisted_tags(mongo, [])) == set()


def test_list_blacklisted_sorted_by_name():
    collection = _FakeCollection([
        {"_id": "B", "name": "Zeta"},
        {"_id": "A", "name": "Alpha"},
    ])
    mongo = _Mongo(collection)

    entries = asyncio.run(fwa_blacklist.list_blacklisted(mongo))
    assert [e["name"] for e in entries] == ["Alpha", "Zeta"]


# ---------------------------------------------------------------------------
# war_plans._add_war_opponent_to_blacklist - the /fwa war-plans Blacklisted
# helper. war_plans.py has no test file of its own; this is the focused test
# of the one helper it added.
# ---------------------------------------------------------------------------

class _FakeCocClient:
    def __init__(self, war=None, error=None):
        self.war = war
        self.error = error

    async def get_clan_war(self, tag):
        if self.error is not None:
            raise self.error
        return self.war


def _fake_war(state, opponent_tag="#OPPONENT", opponent_name="Opponent Clan", end_time=None):
    opponent = SimpleNamespace(tag=opponent_tag, name=opponent_name)
    end = SimpleNamespace(time=end_time) if end_time is not None else None
    return SimpleNamespace(state=state, opponent=opponent, end_time=end)


def test_add_war_opponent_to_blacklist_success_adds_entry():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    coc_client = _FakeCocClient(war=_fake_war("preparation"))

    note = asyncio.run(war_plans._add_war_opponent_to_blacklist(
        coc_client, mongo, "#OURTAG", 111, "Staffer1", "Opponent Clan",
    ))

    assert note == "Added Opponent Clan (#OPPONENT) to the FWA blacklist."
    assert collection.docs["OPPONENT"]["name"] == "Opponent Clan"
    assert collection.docs["OPPONENT"]["source"] == "war-plans"
    assert collection.docs["OPPONENT"]["last_seen_clan_tag"] == "OURTAG"


def test_add_war_opponent_to_blacklist_get_clan_war_raises():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    coc_client = _FakeCocClient(error=RuntimeError("private war log"))

    note = asyncio.run(war_plans._add_war_opponent_to_blacklist(
        coc_client, mongo, "#OURTAG", 111, "Staffer1", "Opponent Clan",
    ))

    assert note == war_plans.BLACKLIST_UNREADABLE_NOTE
    assert collection.docs == {}


def test_add_war_opponent_to_blacklist_not_in_a_war():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    coc_client = _FakeCocClient(war=_fake_war("warEnded"))

    note = asyncio.run(war_plans._add_war_opponent_to_blacklist(
        coc_client, mongo, "#OURTAG", 111, "Staffer1", "Opponent Clan",
    ))

    assert note == war_plans.BLACKLIST_UNREADABLE_NOTE
    assert collection.docs == {}


def test_add_war_opponent_to_blacklist_name_matches_case_and_whitespace_insensitive():
    # Casefold + whitespace-collapse comparison: extra spaces and different
    # case in either name must still count as a match.
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    coc_client = _FakeCocClient(war=_fake_war("preparation", opponent_name="Opponent  Clan"))

    note = asyncio.run(war_plans._add_war_opponent_to_blacklist(
        coc_client, mongo, "#OURTAG", 111, "Staffer1", "opponent clan",
    ))

    assert note == "Added Opponent  Clan (#OPPONENT) to the FWA blacklist."
    assert "OPPONENT" in collection.docs


def test_add_war_opponent_to_blacklist_name_mismatch_adds_nothing():
    # Regression for the previous-war bug: state is still "preparation"/"inWar"
    # for a war whose opponent is NOT the one the rep typed on the plan (e.g.
    # the previous war hasn't ended yet) - nothing should be blacklisted, and
    # the note must name both clans so staff can see the mismatch.
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    coc_client = _FakeCocClient(war=_fake_war("inWar", opponent_name="Previous Opponent"))

    note = asyncio.run(war_plans._add_war_opponent_to_blacklist(
        coc_client, mongo, "#OURTAG", 111, "Staffer1", "New Opponent",
    ))

    assert collection.docs == {}
    assert "Previous Opponent" in note
    assert "New Opponent" in note
    assert "/fwa blacklist add" in note


# ---------------------------------------------------------------------------
# extensions/commands/fwa/blacklist.py - the /fwa blacklist list/add/remove
# command bodies themselves, exercised with fake ctx/mongo/coc objects.
# lightbulb's Option descriptor has no __set__, so a plain instance attribute
# (cmd.tag = "...") shadows it without needing full option resolution.
# ---------------------------------------------------------------------------

class _Member:
    def __init__(self, role_ids, display_name="Staffer"):
        self.role_ids = tuple(role_ids)
        self.display_name = display_name


class _BlacklistContext:
    def __init__(self, member=None, user_id=999, username="Someone"):
        self.member = member
        self.user = SimpleNamespace(id=user_id, username=username)
        self.responses = []

    async def defer(self, **kwargs):
        pass

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


class _FakeCocClientForAdd:
    def __init__(self, name=None, error=None):
        self.name = name
        self.error = error

    async def get_clan(self, tag):
        if self.error is not None:
            raise self.error
        return SimpleNamespace(name=self.name)


def _container_text(container) -> str:
    return "\n".join(c.content for c in container.components if hasattr(c, "content"))


def test_blacklist_add_denies_member_without_role():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    ctx = _BlacklistContext(member=_Member(role_ids=[1]))
    cmd = blacklist.BlacklistAdd()
    cmd.tag = "ABC123"
    cmd.name = ""

    asyncio.run(cmd.invoke(ctx, mongo=mongo, coc_client=_FakeCocClientForAdd()))

    assert len(ctx.responses) == 1
    args, _ = ctx.responses[0]
    assert "FWA Clan Rep role" in args[0]
    assert collection.docs == {}


def test_blacklist_add_invalid_tag_replies_error_and_writes_nothing():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    ctx = _BlacklistContext(member=_Member(role_ids=[blacklist.FWA_CLAN_REP_ROLE_ID]))
    cmd = blacklist.BlacklistAdd()
    cmd.tag = "!!!"
    cmd.name = ""

    asyncio.run(cmd.invoke(ctx, mongo=mongo, coc_client=_FakeCocClientForAdd()))

    args, _ = ctx.responses[0]
    assert "Invalid tag" in args[0]
    assert collection.docs == {}


def test_blacklist_add_without_name_fetches_clan_name_from_coc_client():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    ctx = _BlacklistContext(member=_Member(role_ids=[blacklist.FWA_CLAN_REP_ROLE_ID]))
    cmd = blacklist.BlacklistAdd()
    cmd.tag = "#abc123"
    cmd.name = ""

    asyncio.run(cmd.invoke(ctx, mongo=mongo, coc_client=_FakeCocClientForAdd(name="Looked Up Clan")))

    assert collection.docs["ABC123"]["name"] == "Looked Up Clan"
    assert collection.docs["ABC123"]["source"] == "manual"
    args, _ = ctx.responses[0]
    assert "Looked Up Clan" in args[0]


def test_blacklist_list_pagination_shows_page_footer():
    docs = [
        {
            "_id": f"TAG{i:03d}",
            "name": f"Clan {i:03d}",
            "source": "manual",
            "added_at": "2026-09-01T00:00:00+00:00",
        }
        for i in range(30)
    ]
    collection = _FakeCollection(docs)
    mongo = _Mongo(collection)
    ctx = _BlacklistContext()
    cmd = blacklist.BlacklistList()
    cmd.page = 1

    asyncio.run(cmd.invoke(ctx, mongo=mongo))

    _, kwargs = ctx.responses[0]
    text = _container_text(kwargs["components"][0])
    assert "page 1 of 2, 30 total" in text
    assert text.count("Clan ") == 25  # one page's worth of entries rendered


def test_blacklist_remove_missing_tag_replies_not_on_the_list():
    collection = _FakeCollection()
    mongo = _Mongo(collection)
    ctx = _BlacklistContext(member=_Member(role_ids=[blacklist.FWA_CLAN_REP_ROLE_ID]))
    cmd = blacklist.BlacklistRemove()
    cmd.tag = "#NOTHERE"

    asyncio.run(cmd.invoke(ctx, mongo=mongo))

    args, _ = ctx.responses[0]
    assert "not on the FWA blacklist" in args[0]

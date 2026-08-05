import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from extensions.commands.recruit import questions


def _matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue

        exists = key in document
        actual = document.get(key)
        if isinstance(expected, dict):
            for operator, value in expected.items():
                if operator == "$exists" and exists is not value:
                    return False
                if operator == "$gt" and (actual is None or actual <= value):
                    return False
                if operator == "$lte" and (actual is None or actual > value):
                    return False
                if operator == "$in" and actual not in value:
                    return False
        elif actual != expected:
            return False
    return True


class _Result:
    def __init__(self, *, deleted=0, matched=0, upserted_id=None):
        self.deleted_count = deleted
        self.matched_count = matched
        self.upserted_id = upserted_id


class _Cursor:
    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]

    async def to_list(self, length=None):
        return deepcopy(self.documents[:length] if length else self.documents)

    def __aiter__(self):
        self.iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return deepcopy(next(self.iterator))
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, documents=(), *, index_error=None):
        self.documents = {document["_id"]: deepcopy(document) for document in documents}
        self.index_error = index_error
        self.index_calls = []

    def find(self, query):
        return _Cursor(
            document for document in self.documents.values() if _matches(document, query)
        )

    async def find_one(self, query):
        for document in self.documents.values():
            if _matches(document, query):
                return deepcopy(document)
        return None

    @staticmethod
    def _apply(document, update):
        document.update(deepcopy(update.get("$set", {})))
        for key in update.get("$unset", {}):
            document.pop(key, None)
        for key, amount in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + amount

    async def update_one(self, query, update, upsert=False):
        for document in self.documents.values():
            if _matches(document, query):
                self._apply(document, update)
                return _Result(matched=1)
        if not upsert:
            return _Result()
        document = {"_id": query["_id"]}
        self._apply(document, update)
        self.documents[document["_id"]] = document
        return _Result(upserted_id=document["_id"])

    async def update_many(self, query, update):
        matched = 0
        for document in self.documents.values():
            if _matches(document, query):
                self._apply(document, update)
                matched += 1
        return _Result(matched=matched)

    async def find_one_and_update(self, query, update, **kwargs):
        for document in self.documents.values():
            if _matches(document, query):
                before = deepcopy(document)
                self._apply(document, update)
                return before
        return None

    async def delete_one(self, query):
        for document_id, document in list(self.documents.items()):
            if _matches(document, query):
                del self.documents[document_id]
                return _Result(deleted=1)
        return _Result()

    async def delete_many(self, query):
        deleted = 0
        for document_id, document in list(self.documents.items()):
            if _matches(document, query):
                del self.documents[document_id]
                deleted += 1
        return _Result(deleted=deleted)

    async def create_index(self, keys, **kwargs):
        self.index_calls.append((keys, deepcopy(kwargs)))
        if self.index_error:
            raise self.index_error
        return kwargs.get("name")


class _Mongo:
    def __init__(self, *, challenges=(), legacy=(), index_error=None):
        self.recruit_challenges = _Collection(challenges, index_error=index_error)
        self.recruit_onboarding = _Collection(legacy)


class _Rest:
    def __init__(self):
        self.created = []
        self.deleted = []
        self.fail_create = False

    async def fetch_member(self, guild_id, user_id):
        return SimpleNamespace(display_name="Recruiter")

    async def create_message(self, **kwargs):
        if self.fail_create:
            raise RuntimeError("Discord unavailable")
        self.created.append(kwargs)
        return SimpleNamespace(id=1000 + len(self.created))

    async def delete_message(self, channel_id, message_id):
        self.deleted.append((channel_id, message_id))


def _event(content, *, message_id=500):
    return SimpleNamespace(
        is_bot=False,
        content=content,
        author_id=22,
        channel_id=33,
        guild_id=44,
        message=SimpleNamespace(id=message_id),
        author=SimpleNamespace(mention="<@22>"),
    )


def test_parser_accepts_visual_variants_and_rejects_wrong_codes():
    accepted = {
        "⚔️⚔️⚔️": "⚔️⚔️⚔️",
        "⚔⚔⚔": "⚔️⚔️⚔️",
        "⚔️ ⚔️ ⚔️": "⚔️⚔️⚔️",
        "**⚔\u200b🍻⚔**": "⚔️🍻⚔️",
        "||⚔ ☠ ⚔||": "⚔️☠️⚔️",
    }
    for content, expected in accepted.items():
        assert questions.match_family_code(content) == expected

    assert questions.match_family_code("⚔️⚔️") is None
    assert questions.match_family_code("⚔️⚔️⚔️⚔️") is None
    assert questions.match_family_code("code: ⚔️⚔️⚔️") is None
    assert questions.looks_like_family_code_attempt("⚔️⚔️")
    assert not questions.looks_like_family_code_attempt("ordinary conversation")


def test_opening_again_replaces_state_and_clears_old_cooldown():
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo()

    async def scenario():
        await questions.open_family_code_challenge(
            mongo,
            interaction_id=1,
            guild_id=44,
            channel_id=33,
            user_id=22,
            moderator_id=11,
            now=now,
        )
        state = mongo.recruit_challenges.documents["family_codes:33:22"]
        state["warning_available_at"] = now + timedelta(minutes=2)
        await questions.open_family_code_challenge(
            mongo,
            interaction_id=2,
            guild_id=44,
            channel_id=33,
            user_id=22,
            moderator_id=12,
            now=now + timedelta(minutes=1),
        )

    asyncio.run(scenario())

    assert len(mongo.recruit_challenges.documents) == 1
    state = mongo.recruit_challenges.documents["family_codes:33:22"]
    assert state["session_id"] == "2"
    assert state["moderator_id"] == 12
    assert state["expires_at"] == now + timedelta(minutes=1) + questions.FAMILY_CODE_TTL
    assert "warning_available_at" not in state


def test_invalid_attempt_warns_once_per_cooldown_and_tracks_auto_delete(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest)
    scheduled = []
    monkeypatch.setattr(questions, "utcnow", lambda: now)
    monkeypatch.setattr(
        questions,
        "_schedule_warning_deletion",
        lambda *args: scheduled.append(args),
    )

    async def scenario():
        await questions.open_family_code_challenge(
            mongo,
            interaction_id=1,
            guild_id=44,
            channel_id=33,
            user_id=22,
            moderator_id=11,
            now=now,
        )
        await questions.on_family_code_response(_event("⚔️🍺⚔️"), mongo=mongo, bot=bot)
        await questions.on_family_code_response(_event("⚔️⚔️"), mongo=mongo, bot=bot)

    asyncio.run(scenario())

    assert len(rest.created) == 1
    assert rest.created[0]["user_mentions"] == [22]
    assert len(scheduled) == 1
    assert scheduled[0][2:] == ("family_codes:33:22", 33, 1001)
    state = mongo.recruit_challenges.documents["family_codes:33:22"]
    assert state["invalid_attempts"] == 1
    assert state["warning_available_at"] == now + timedelta(minutes=2)
    assert state["warning_delete_at"] == now + timedelta(seconds=30)


def test_valid_code_bypasses_warning_cooldown_and_completes_once(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest)
    monkeypatch.setattr(questions, "utcnow", lambda: now)

    async def scenario():
        await questions.open_family_code_challenge(
            mongo,
            interaction_id=1,
            guild_id=44,
            channel_id=33,
            user_id=22,
            moderator_id=11,
            now=now,
        )
        mongo.recruit_challenges.documents["family_codes:33:22"][
            "warning_available_at"
        ] = now + timedelta(minutes=2)
        mongo.recruit_challenges.documents["family_codes:33:22"][
            "warning_message_id"
        ] = 777
        event = _event("⚔ ⚔ ⚔")
        await questions.on_family_code_response(event, mongo=mongo, bot=bot)
        await questions.on_family_code_response(event, mongo=mongo, bot=bot)

    asyncio.run(scenario())

    assert len(rest.created) == 1
    assert rest.deleted == [(33, 777)]
    assert mongo.recruit_challenges.documents == {}


def test_confirmation_failure_restores_the_exact_challenge(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo()
    rest = _Rest()
    rest.fail_create = True
    bot = SimpleNamespace(rest=rest)
    monkeypatch.setattr(questions, "utcnow", lambda: now)

    async def scenario():
        await questions.open_family_code_challenge(
            mongo,
            interaction_id=1,
            guild_id=44,
            channel_id=33,
            user_id=22,
            moderator_id=11,
            now=now,
        )
        with pytest.raises(RuntimeError, match="Discord unavailable"):
            await questions.on_family_code_response(
                _event("⚔️⚔️⚔️"),
                mongo=mongo,
                bot=bot,
            )

    asyncio.run(scenario())

    state = mongo.recruit_challenges.documents["family_codes:33:22"]
    assert state["status"] == "active"
    assert "processing_message_id" not in state
    assert "code_used" not in state


def test_warning_send_failure_releases_cooldown(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    mongo = _Mongo()
    rest = _Rest()
    rest.fail_create = True
    bot = SimpleNamespace(rest=rest)
    monkeypatch.setattr(questions, "utcnow", lambda: now)

    async def scenario():
        await questions.open_family_code_challenge(
            mongo,
            interaction_id=1,
            guild_id=44,
            channel_id=33,
            user_id=22,
            moderator_id=11,
            now=now,
        )
        with pytest.raises(RuntimeError, match="Discord unavailable"):
            await questions.on_family_code_response(
                _event("⚔️⚔️"),
                mongo=mongo,
                bot=bot,
            )

    asyncio.run(scenario())

    state = mongo.recruit_challenges.documents["family_codes:33:22"]
    assert "warning_available_at" not in state


def test_warning_delete_clears_only_its_persisted_message(monkeypatch):
    mongo = _Mongo(challenges=[{
        "_id": "family_codes:33:22",
        "warning_message_id": 777,
        "warning_delete_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
    }])
    rest = _Rest()
    bot = SimpleNamespace(rest=rest)

    async def no_delay(seconds):
        return None

    monkeypatch.setattr(questions.asyncio, "sleep", no_delay)
    asyncio.run(questions._delete_warning_after(
        bot,
        mongo,
        "family_codes:33:22",
        33,
        777,
    ))

    assert rest.deleted == [(33, 777)]
    state = mongo.recruit_challenges.documents["family_codes:33:22"]
    assert "warning_message_id" not in state
    assert "warning_delete_at" not in state


def test_legacy_migration_keeps_latest_recent_open_attempt_only():
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    legacy = [
        {"_id": "old", "type": "family_codes", "channel_id": 33, "user_id": 22,
         "moderator_id": 10, "created_at": now - timedelta(hours=2), "completed": False},
        {"_id": "new", "type": "family_codes", "channel_id": 33, "user_id": 22,
         "moderator_id": 11, "created_at": now - timedelta(hours=1), "completed": False},
        {"_id": "done", "type": "family_codes", "channel_id": 33, "user_id": 22,
         "created_at": now, "completed": True},
        {"_id": "expired", "type": "family_codes", "channel_id": 55, "user_id": 66,
         "created_at": now - timedelta(days=2), "completed": False},
        {"_id": "invalid", "type": "family_codes", "completed": False},
    ]
    mongo = _Mongo(legacy=legacy)

    counts = asyncio.run(questions.migrate_legacy_family_codes(mongo, now=now))

    assert counts == {"migrated": 1, "removed": 5, "failed": 0}
    assert mongo.recruit_onboarding.documents == {}
    state = mongo.recruit_challenges.documents["family_codes:33:22"]
    assert state["moderator_id"] == 11
    assert state["expires_at"] == now - timedelta(hours=1) + questions.FAMILY_CODE_TTL


def test_ttl_index_failure_preserves_all_legacy_rows():
    legacy = [{
        "_id": "legacy",
        "type": "family_codes",
        "channel_id": 33,
        "user_id": 22,
        "created_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
        "completed": False,
    }]
    mongo = _Mongo(legacy=legacy, index_error=RuntimeError("no index permission"))
    bot = SimpleNamespace(rest=_Rest())

    asyncio.run(questions.prepare_family_code_storage(None, mongo=mongo, bot=bot))

    assert mongo.recruit_onboarding.documents == {"legacy": legacy[0]}
    assert mongo.recruit_challenges.documents == {}


def test_startup_removes_warning_left_by_prior_process():
    challenge = {
        "_id": "family_codes:33:22",
        "type": "family_codes",
        "status": "active",
        "channel_id": 33,
        "warning_message_id": 777,
        "warning_delete_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
    }
    mongo = _Mongo(challenges=[challenge])
    rest = _Rest()
    bot = SimpleNamespace(rest=rest)

    asyncio.run(questions.prepare_family_code_storage(None, mongo=mongo, bot=bot))

    assert rest.deleted == [(33, 777)]
    state = mongo.recruit_challenges.documents["family_codes:33:22"]
    assert "warning_message_id" not in state
    assert mongo.recruit_challenges.index_calls == [(
        "expires_at",
        {"expireAfterSeconds": 0, "name": questions.FAMILY_CODE_TTL_INDEX},
    )]

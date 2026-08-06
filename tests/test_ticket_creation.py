import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError

from extensions.commands.tickets import handlers, store


class FakeCreationCollection:
    def __init__(self, document=None):
        self.document = document
        self.index_calls = 0
        self.deleted = []

    async def create_index(self, *args, **kwargs):
        self.index_calls += 1
        return kwargs.get("name")

    async def find_one(self, query):
        if self.document and self.document.get("_id") == query.get("_id"):
            return dict(self.document)
        return None

    async def find_one_and_update(self, query, update, **_kwargs):
        now_limit = query["$or"][0]["lease_until"]["$lte"]
        if self.document:
            lease = self.document.get("lease_until")
            if lease is not None and lease > now_limit:
                return None
        base = dict(self.document or {"_id": query["_id"]})
        if self.document is None:
            base.update(update.get("$setOnInsert", {}))
        base.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            base.pop(key, None)
        self.document = base
        return dict(base)

    async def update_one(self, query, update):
        matched = bool(self.document and self.document.get("_id") == query.get("_id"))
        if matched and "state" in query:
            matched = self.document.get("state") == query["state"]
        if matched:
            self.document.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                self.document.pop(key, None)
        return SimpleNamespace(matched_count=int(matched))

    async def delete_one(self, query):
        self.deleted.append(query)
        matched = bool(
            self.document
            and all(self.document.get(key) == value for key, value in query.items())
        )
        if matched:
            self.document = None
        return SimpleNamespace(deleted_count=int(matched))


class FakeSetupCollection:
    def __init__(self, config=None):
        self.config = dict(config or {"_id": "config"})

    async def find_one(self, _query, _projection=None):
        return dict(self.config)

    async def find_one_and_update(self, _query, update, **_kwargs):
        for field, amount in update.get("$inc", {}).items():
            self.config[field] = self.config.get(field, 0) + amount
        return dict(self.config)


class FakeReplaceCollection:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.documents = {}

    async def replace_one(self, query, document, **_kwargs):
        if self.fail:
            raise RuntimeError("mirror unavailable")
        self.documents[query["_id"]] = dict(document)


def test_ticket_insert_commits_primary_when_mirror_fails(caplog):
    primary = FakeReplaceCollection()
    secondary = FakeReplaceCollection(fail=True)
    mongo = SimpleNamespace(
        ticket_setup=FakeSetupCollection({"ticket_store": store.STORE_BUTTON}),
        button_store=primary,
        tickets=secondary,
    )
    ticket = {"_id": "ticket_42", "type": "ticket", "status": "open"}

    asyncio.run(store.insert_one(mongo, ticket))

    assert primary.documents["ticket_42"] == ticket
    assert "primary remains authoritative" in caplog.text


def test_creation_claim_is_atomic_bounded_and_blocks_duplicate(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    collection = FakeCreationCollection()
    mongo = SimpleNamespace(ticket_creation_state=collection)
    monkeypatch.setattr(handlers, "_creation_index_ready", False)

    first_acquired, first = asyncio.run(handlers.claim_ticket_creation(
        mongo, 1, 2, "main", now=now,
    ))
    second_acquired, second = asyncio.run(handlers.claim_ticket_creation(
        mongo, 1, 2, "main", now=now + timedelta(seconds=1),
    ))

    assert first_acquired is True
    assert second_acquired is False
    assert first["lease_until"] == now + handlers.CREATION_LEASE
    assert first["expires_at"] == now + handlers.CREATION_RETENTION
    assert second["_id"] == "1:2:main"
    assert collection.index_calls == 1


def test_creation_state_with_discord_channel_cannot_be_reclaimed(monkeypatch):
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    collection = FakeCreationCollection({
        "_id": "1:2:main",
        "state": "cleanup_required",
        "channel_id": 42,
        "lease_until": now - timedelta(hours=1),
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    monkeypatch.setattr(handlers, "_creation_index_ready", True)

    acquired, state = asyncio.run(handlers.claim_ticket_creation(
        mongo, 1, 2, "main", now=now,
    ))

    assert acquired is False
    assert state["channel_id"] == 42


def test_naive_mongo_lease_does_not_raise_during_duplicate_claim(monkeypatch):
    class Collection(FakeCreationCollection):
        async def find_one_and_update(self, *_args, **_kwargs):
            raise DuplicateKeyError("active lease owns the key")

    collection = Collection({
        "_id": "1:2:main",
        "state": "creating",
        # PyMongo returns naive UTC unless tz_aware=True.
        "lease_until": datetime(2026, 8, 5, 12, 10),
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    monkeypatch.setattr(handlers, "_creation_index_ready", True)

    acquired, state = asyncio.run(handlers.claim_ticket_creation(
        mongo,
        1,
        2,
        "main",
        now=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    ))

    assert acquired is False
    assert state["state"] == "creating"


def test_ticket_number_reservation_is_atomic():
    setup = FakeSetupCollection({"main_ticket_counter": 8})
    mongo = SimpleNamespace(ticket_setup=setup)

    first = asyncio.run(handlers.reserve_ticket_number(mongo, "main"))
    second = asyncio.run(handlers.reserve_ticket_number(mongo, "main"))

    assert (first, second) == (9, 10)


def test_ticket_error_detail_redacts_credentials_and_tokens():
    detail = handlers._error_detail(RuntimeError(
        "mongodb://name:password@db.example/test?access_token=secret-value"
    ))

    assert "name:password" not in detail
    assert "secret-value" not in detail
    assert "mongodb://***@" in detail
    assert "access_token=***" in detail


def test_rollback_deletes_incomplete_channel_and_releases_claim():
    class Rest:
        def __init__(self):
            self.deleted = []

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    collection = FakeCreationCollection({"_id": "claim", "state": "creating"})
    mongo = SimpleNamespace(ticket_creation_state=collection)
    bot = SimpleNamespace(rest=Rest())

    result = asyncio.run(handlers.rollback_ticket_creation(
        bot, mongo, "claim", 42, RuntimeError("thread failed"),
    ))

    assert result is True
    assert bot.rest.deleted == [42]
    assert collection.document is None


def test_failed_discord_rollback_retains_duplicate_blocker(capsys):
    class Rest:
        async def delete_channel(self, _channel_id, **_kwargs):
            raise RuntimeError("Discord unavailable")

    collection = FakeCreationCollection({"_id": "claim", "state": "creating"})
    mongo = SimpleNamespace(ticket_creation_state=collection)
    bot = SimpleNamespace(rest=Rest())

    result = asyncio.run(handlers.rollback_ticket_creation(
        bot, mongo, "claim", 42, RuntimeError("Mongo unavailable"),
    ))

    assert result is False
    assert collection.document["state"] == "cleanup_required"
    assert collection.document["channel_id"] == 42
    assert "creation_rollback_failed" in capsys.readouterr().out


def test_missing_incomplete_channel_releases_stale_blocker():
    class Rest:
        async def fetch_channel(self, _channel_id):
            raise handlers.hikari.NotFoundError(
                "https://discord.test/channels/42",
                {},
                b"",
                "channel is gone",
            )

    collection = FakeCreationCollection({
        "_id": "claim",
        "state": "cleanup_required",
        "channel_id": 42,
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    bot = SimpleNamespace(rest=Rest())

    released = asyncio.run(handlers.release_missing_channel_blocker(
        bot, mongo, dict(collection.document),
    ))

    assert released is True
    assert collection.document is None


def test_missing_named_channel_releases_uncertain_blocker():
    class Rest:
        async def fetch_guild_channels(self, _guild_id):
            return []

    collection = FakeCreationCollection({
        "_id": "claim",
        "state": "cleanup_required",
        "guild_id": 11,
        "category_id": 100,
        "channel_name": "🆕main-1-Tester",
    })
    mongo = SimpleNamespace(ticket_creation_state=collection)
    bot = SimpleNamespace(rest=Rest())

    released = asyncio.run(handlers.release_missing_channel_blocker(
        bot, mongo, dict(collection.document),
    ))

    assert released is True
    assert collection.document is None


def test_uncertain_channel_lookup_retries_before_concluding_missing(monkeypatch):
    class Rest:
        def __init__(self):
            self.calls = 0

        async def fetch_guild_channels(self, _guild_id):
            self.calls += 1
            if self.calls < 3:
                return []
            return [SimpleNamespace(
                id=42,
                name="🆕MAIN-1-TESTER",
                parent_id=100,
            )]

    sleeps = []

    async def no_wait(delay):
        sleeps.append(delay)

    monkeypatch.setattr(handlers.asyncio, "sleep", no_wait)
    bot = SimpleNamespace(rest=Rest())

    channel = asyncio.run(handlers.locate_uncertain_channel(
        bot, 11, 100, "🆕main-1-Tester",
    ))

    assert channel.id == 42
    assert bot.rest.calls == 3
    assert sleeps == [1, 1]


class FakeInteraction:
    def __init__(self):
        self.responses = []

    async def edit_initial_response(self, *, content):
        self.responses.append(content)


class FakeContext:
    def __init__(self):
        self.user = SimpleNamespace(id=22, username="Tester")
        self.guild_id = 11
        self.interaction = FakeInteraction()

    async def defer(self, **_kwargs):
        return None


def _handler_mongo():
    return SimpleNamespace(
        ticket_setup=FakeSetupCollection({
            "main_category": 100,
            "main_ticket_counter": 0,
        }),
        ticket_creation_state=FakeCreationCollection(),
    )


def _patch_handler_dependencies(monkeypatch, *, existing=None):
    async def category_space(*_args, **_kwargs):
        return 49

    async def find_open(*_args, **_kwargs):
        return existing

    async def claim(*_args, **_kwargs):
        return True, {"_id": "11:22:main", "state": "creating"}

    async def reserve(*_args, **_kwargs):
        return 1

    async def update_state(*_args, **_kwargs):
        return None

    async def complete_state(*_args, **_kwargs):
        return None

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(handlers, "check_category_space", category_space)
    monkeypatch.setattr(handlers, "find_open_ticket", find_open)
    monkeypatch.setattr(handlers, "claim_ticket_creation", claim)
    monkeypatch.setattr(handlers, "reserve_ticket_number", reserve)
    monkeypatch.setattr(handlers, "update_creation_state", update_state)
    monkeypatch.setattr(handlers, "complete_creation_state", complete_state)
    monkeypatch.setattr(handlers.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(handlers, "user_cooldowns", {})


def test_handler_rolls_back_channel_when_thread_creation_fails(monkeypatch):
    class Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            return SimpleNamespace(id=42)

        async def create_thread(self, *_args, **_kwargs):
            raise RuntimeError("thread unavailable")

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    _patch_handler_dependencies(monkeypatch)
    ctx = FakeContext()
    bot = SimpleNamespace(rest=Rest())
    mongo = _handler_mongo()

    asyncio.run(handlers.handle_create_ticket(ctx, "main", bot=bot, mongo=mongo))

    assert bot.rest.deleted == [42]
    assert "Nothing was left behind" in ctx.interaction.responses[-1]


def test_lost_discord_create_response_locates_and_rolls_back_channel(monkeypatch):
    class Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            raise TimeoutError("Discord response lost")

        async def fetch_guild_channels(self, _guild_id):
            return [SimpleNamespace(
                id=42,
                name="🆕main-1-Tester",
                parent_id=100,
            )]

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    _patch_handler_dependencies(monkeypatch)
    ctx = FakeContext()
    bot = SimpleNamespace(rest=Rest())

    asyncio.run(handlers.handle_create_ticket(
        ctx, "main", bot=bot, mongo=_handler_mongo(),
    ))

    assert bot.rest.deleted == [42]
    assert "Nothing was left behind" in ctx.interaction.responses[-1]


def test_unconfirmable_discord_create_keeps_duplicate_blocker(monkeypatch):
    class Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            raise TimeoutError("Discord response lost")

        async def fetch_guild_channels(self, _guild_id):
            raise RuntimeError("Discord still unavailable")

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    _patch_handler_dependencies(monkeypatch)
    ctx = FakeContext()
    bot = SimpleNamespace(rest=Rest())
    mongo = _handler_mongo()
    mongo.ticket_creation_state.document = {
        "_id": "11:22:main",
        "state": "creating",
    }

    asyncio.run(handlers.handle_create_ticket(ctx, "main", bot=bot, mongo=mongo))

    assert bot.rest.deleted == []
    assert mongo.ticket_creation_state.document["state"] == "cleanup_required"
    assert "could not confirm" in ctx.interaction.responses[-1]


def test_handler_rolls_back_discord_when_primary_ticket_write_fails(monkeypatch):
    class Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            return SimpleNamespace(id=42)

        async def create_thread(self, *_args, **_kwargs):
            return SimpleNamespace(id=43)

        async def add_thread_member(self, *_args, **_kwargs):
            return None

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    async def failed_insert(_mongo, _document):
        raise RuntimeError("primary Mongo unavailable")

    async def not_committed(_mongo, _query):
        return None

    _patch_handler_dependencies(monkeypatch)
    monkeypatch.setattr(handlers.store, "insert_one", failed_insert)
    monkeypatch.setattr(handlers.store, "find_one", not_committed)
    ctx = FakeContext()
    bot = SimpleNamespace(
        rest=Rest(),
        get_me=lambda: SimpleNamespace(id=999),
    )

    asyncio.run(handlers.handle_create_ticket(
        ctx, "main", bot=bot, mongo=_handler_mongo(),
    ))

    assert bot.rest.deleted == [42]
    assert "Nothing was left behind" in ctx.interaction.responses[-1]


def test_timed_out_primary_write_is_confirmed_before_discord_rollback(monkeypatch):
    class Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            return SimpleNamespace(id=42)

        async def create_thread(self, *_args, **_kwargs):
            return SimpleNamespace(id=43)

        async def add_thread_member(self, *_args, **_kwargs):
            return None

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    committed = {}

    async def timed_out_insert(_mongo, document):
        committed.update(document)
        raise TimeoutError("response lost after commit")

    async def find_committed(_mongo, query):
        return dict(committed) if committed.get("_id") == query.get("_id") else None

    _patch_handler_dependencies(monkeypatch)
    monkeypatch.setattr(handlers.store, "insert_one", timed_out_insert)
    monkeypatch.setattr(handlers.store, "find_one", find_committed)
    ctx = FakeContext()
    bot = SimpleNamespace(
        rest=Rest(),
        get_me=lambda: SimpleNamespace(id=999),
    )

    asyncio.run(handlers.handle_create_ticket(
        ctx, "main", bot=bot, mongo=_handler_mongo(),
    ))

    assert committed["_id"] == "ticket_42"
    assert bot.rest.deleted == []
    assert "was created" in ctx.interaction.responses[-1]


def test_unconfirmable_primary_write_keeps_channel_and_duplicate_blocker(monkeypatch):
    class Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            return SimpleNamespace(id=42)

        async def create_thread(self, *_args, **_kwargs):
            return SimpleNamespace(id=43)

        async def add_thread_member(self, *_args, **_kwargs):
            return None

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    async def timed_out_insert(_mongo, _document):
        raise TimeoutError("write result unknown")

    async def unavailable_confirmation(_mongo, _query):
        raise RuntimeError("Mongo still unavailable")

    _patch_handler_dependencies(monkeypatch)
    monkeypatch.setattr(handlers.store, "insert_one", timed_out_insert)
    monkeypatch.setattr(handlers.store, "find_one", unavailable_confirmation)
    ctx = FakeContext()
    bot = SimpleNamespace(
        rest=Rest(),
        get_me=lambda: SimpleNamespace(id=999),
    )
    mongo = _handler_mongo()
    mongo.ticket_creation_state.document = {
        "_id": "11:22:main",
        "state": "creating",
    }

    asyncio.run(handlers.handle_create_ticket(ctx, "main", bot=bot, mongo=mongo))

    assert bot.rest.deleted == []
    assert mongo.ticket_creation_state.document["state"] == "cleanup_required"
    assert mongo.ticket_creation_state.document["channel_id"] == 42
    assert "could not be confirmed safely" in ctx.interaction.responses[-1]


def test_handler_returns_existing_open_ticket_without_creating_channel(monkeypatch):
    class Rest:
        async def create_guild_text_channel(self, **_kwargs):
            raise AssertionError("duplicate channel creation attempted")

    _patch_handler_dependencies(
        monkeypatch,
        existing={"_id": "ticket_77", "channel_id": 77},
    )
    ctx = FakeContext()
    bot = SimpleNamespace(rest=Rest())

    asyncio.run(handlers.handle_create_ticket(
        ctx, "main", bot=bot, mongo=_handler_mongo(),
    ))

    assert "already have an open" in ctx.interaction.responses[-1]
    assert "<#77>" in ctx.interaction.responses[-1]


def test_postcommit_message_failure_still_reports_created_ticket(monkeypatch, capsys):
    class Rest:
        def __init__(self):
            self.deleted = []

        async def create_guild_text_channel(self, **_kwargs):
            return SimpleNamespace(id=42)

        async def create_thread(self, *_args, **_kwargs):
            return SimpleNamespace(id=43)

        async def add_thread_member(self, *_args, **_kwargs):
            return None

        async def create_message(self, *_args, **_kwargs):
            raise RuntimeError("message unavailable")

        async def delete_channel(self, channel_id, **_kwargs):
            self.deleted.append(channel_id)

    inserted = []

    async def insert(_mongo, document):
        inserted.append(document)

    _patch_handler_dependencies(monkeypatch)
    monkeypatch.setattr(handlers.store, "insert_one", insert)
    ctx = FakeContext()
    bot = SimpleNamespace(
        rest=Rest(),
        get_me=lambda: SimpleNamespace(id=999),
    )

    asyncio.run(handlers.handle_create_ticket(
        ctx, "main", bot=bot, mongo=_handler_mongo(),
    ))

    assert len(inserted) == 1
    assert bot.rest.deleted == []
    assert "has been created" in ctx.interaction.responses[-1]
    assert "ticket_postcommit_setup_failed" in capsys.readouterr().out

"""Regression tests for the section-4 "fix now on main" bugs in
docs/mongodb-refactor.md, for modules that had no existing test file of
their own."""

import asyncio
import logging
from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError

from extensions.commands.clan.dashboard import update_clan_info
import utils.mongo as mongo_module


class _FakeCollection:
    """Minimal Mongo collection double: enough $setOnInsert/upsert semantics
    to prove a repeat insert does not create a second document."""

    def __init__(self):
        self.documents: dict = {}
        self.index_calls: list = []
        self.create_index_error: Exception | None = None

    async def create_index(self, keys, **kwargs):
        self.index_calls.append((keys, kwargs))
        if self.create_index_error is not None:
            raise self.create_index_error
        return kwargs.get("name")

    async def update_one(self, query, update, upsert=False):
        existing = None
        for doc in self.documents.values():
            if all(doc.get(k) == v for k, v in query.items()):
                existing = doc
                break
        if existing is not None:
            return SimpleNamespace(matched_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, upserted_id=None)
        new_doc = {**query, **update.get("$setOnInsert", {})}
        doc_id = new_doc.setdefault("_id", f"id{len(self.documents) + 1}")
        self.documents[doc_id] = new_doc
        return SimpleNamespace(matched_count=0, upserted_id=doc_id)


class _FakeMongo:
    def __init__(self):
        self.clans = _FakeCollection()


class _FakeComponent:
    def __init__(self, custom_id, value):
        self.custom_id = custom_id
        self.value = value


class _FakeInteraction:
    def __init__(self, clan_tag):
        self.components = [[_FakeComponent("clantag", clan_tag)]]
        self.responses = []
        self.edits = []

    async def create_initial_response(self, *args, **kwargs):
        self.responses.append((args, kwargs))

    async def edit_initial_response(self, *args, **kwargs):
        self.edits.append((args, kwargs))


class _FakeCtx:
    def __init__(self, clan_tag):
        self.interaction = _FakeInteraction(clan_tag)
        self.responded = []

    async def respond(self, *args, **kwargs):
        self.responded.append((args, kwargs))


class _FakeClan:
    def __init__(self, tag, name="Test Clan"):
        self.tag = tag
        self.name = name


class _FakeCocClient:
    def __init__(self, clan):
        self._clan = clan

    async def get_clan(self, tag):
        return self._clan


def _reset_clan_tag_index_state():
    mongo_module._clan_tag_index_ready = False
    mongo_module._clan_tag_index_failed = False
    mongo_module._clan_tag_index_retry_at = 0.0


def test_ensure_clan_tag_index_creates_once_and_caches(monkeypatch):
    _reset_clan_tag_index_state()
    mongo = _FakeMongo()

    ready = asyncio.run(mongo_module.ensure_clan_tag_index(mongo))
    assert ready is True
    assert mongo.clans.index_calls == [("tag", {"unique": True, "name": "uniq_clan_tag"})]

    # Second call must not create the index again.
    ready_again = asyncio.run(mongo_module.ensure_clan_tag_index(mongo))
    assert ready_again is True
    assert len(mongo.clans.index_calls) == 1


def test_ensure_clan_tag_index_duplicate_key_logs_error_and_continues(monkeypatch, caplog):
    _reset_clan_tag_index_state()
    mongo = _FakeMongo()
    mongo.clans.create_index_error = DuplicateKeyError("E11000 duplicate key error")

    with caplog.at_level(logging.ERROR, logger="utils.mongo"):
        ready = asyncio.run(mongo_module.ensure_clan_tag_index(mongo))

    assert ready is False
    assert any(
        "duplicate clan tags exist; run tools/find_duplicate_clans.py" in record.message
        for record in caplog.records
    )
    _reset_clan_tag_index_state()


def test_repeat_add_clan_upserts_instead_of_duplicating(monkeypatch):
    """docs/mongodb-refactor.md section 4: add the same tag twice, assert
    clan_data holds exactly one document for that tag."""
    _reset_clan_tag_index_state()
    mongo = _FakeMongo()
    clan = _FakeClan("#ABC123")
    coc_client = _FakeCocClient(clan)

    async def fake_clan_edit_menu(ctx, *, action_id, mongo, tag):
        return []

    monkeypatch.setattr(update_clan_info, "clan_edit_menu", fake_clan_edit_menu)

    handler = update_clan_info.add_clan_modal.__wrapped__._func

    ctx1 = _FakeCtx("#ABC123")
    asyncio.run(handler(ctx=ctx1, coc_client=coc_client, mongo=mongo))

    ctx2 = _FakeCtx("#ABC123")
    asyncio.run(handler(ctx=ctx2, coc_client=coc_client, mongo=mongo))

    matching = [doc for doc in mongo.clans.documents.values() if doc.get("tag") == "#ABC123"]
    assert len(matching) == 1
    _reset_clan_tag_index_state()

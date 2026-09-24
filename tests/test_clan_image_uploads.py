import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extensions.commands.clan.dashboard import image_uploads as uploads


class Collection:
    def __init__(self, document=None, *, matched=1):
        self.document = document
        self.matched = matched
        self.writes = []
        self.inserted = []

    async def find_one(self, query):
        if self.document is None:
            return None
        if query.get("_id") and self.document.get("_id") != query["_id"]:
            return None
        if query.get("tag") and self.document.get("tag") != query["tag"]:
            return None
        return dict(self.document)

    async def update_one(self, query, update, **kwargs):
        self.writes.append((query, update, kwargs))
        return SimpleNamespace(matched_count=self.matched)

    async def insert_one(self, document):
        self.document = dict(document)
        self.inserted.append(dict(document))


class Ctx:
    def __init__(self, interaction, *, allowed=True, order=None):
        self.interaction = interaction
        self.member = SimpleNamespace(get_roles=lambda: [SimpleNamespace(id=uploads.ROLE_ID)] if allowed else [])
        self.modal = None
        self.responses = []
        self.order = order if order is not None else []

    async def respond_with_modal(self, **kwargs):
        self.modal = kwargs

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))

    async def defer(self, **kwargs):
        self.order.append("ack")


def click_interaction(*, guild=1, user=2, channel=3, message=4):
    return SimpleNamespace(
        guild_id=guild, channel_id=channel, user=SimpleNamespace(id=user),
        message=SimpleNamespace(id=message),
    )


def modal_interaction(*, guild=1, user=2, channel=3, message=SimpleNamespace(id=4)):
    return SimpleNamespace(
        id=99, custom_id="dashboard_image_submit:token", guild_id=guild,
        channel_id=channel, user=SimpleNamespace(id=user), message=message,
        create_initial_response=AsyncMock(), edit_initial_response=AsyncMock(),
    )


def mongo_for(kind, slot, key, old="https://old.example/image.png"):
    clan = Collection({"_id": "clan-id", "tag": "#ABC", "name": "Clan Name", "logo": old, "banner": old})
    fwa = Collection({
        "_id": "fwa_config",
        "war_base_images": {"th16": old, "th16_new": old},
        "active_base_images": {"th16": old, "th16_new": old},
    })
    return SimpleNamespace(clans=clan, fwa_data=fwa)


@pytest.fixture(autouse=True)
def clear_pending_and_maps():
    old_war = dict(uploads.FWA_WAR_BASE)
    old_active = dict(uploads.FWA_ACTIVE_WAR_BASE)
    uploads._PENDING.clear()
    uploads.FWA_WAR_BASE.clear()
    uploads.FWA_ACTIVE_WAR_BASE.clear()
    yield
    uploads._PENDING.clear()
    uploads.FWA_WAR_BASE.clear()
    uploads.FWA_WAR_BASE.update(old_war)
    uploads.FWA_ACTIVE_WAR_BASE.clear()
    uploads.FWA_ACTIVE_WAR_BASE.update(old_active)


@pytest.mark.parametrize("kind,action_id,slot,key", [
    ("clan", "logo:#ABC", "logo", "#ABC"),
    ("clan", "banner:#ABC", "banner", "#ABC"),
    ("fwa", "war:th16_new", "war", "th16_new"),
    ("fwa", "active:th16", "active", "th16"),
])
def test_open_handlers_bind_all_four_supported_targets(kind, action_id, slot, key):
    async def run():
        mongo = mongo_for(kind, slot, key)
        ctx = Ctx(click_interaction())
        await uploads._open(ctx, action_id, mongo, kind)
        assert ctx.modal["custom_id"].startswith("dashboard_image_submit:")
        token = ctx.modal["custom_id"].split(":", 1)[1]
        pending = uploads._PENDING[token][1]
        assert (pending.kind, pending.slot, pending.key) == (kind, slot, key)
        assert (pending.guild_id, pending.owner_id, pending.source_channel_id, pending.source_message_id) == (1, 2, 3, 4)
        assert pending.old_value == "https://old.example/image.png"
        assert ctx.modal["components"][0].custom_id == "image"
    asyncio.run(run())


@pytest.mark.parametrize("kind,slot,key", [
    ("clan", "logo", "#ABC"),
    ("clan", "banner", "#ABC"),
    ("fwa", "war", "th16"),
    ("fwa", "active", "th16_new"),
])
def test_submit_saves_only_selected_field_after_ack_and_updates_fwa_map(monkeypatch, kind, slot, key):
    async def run():
        mongo = mongo_for(kind, slot, key)
        target = uploads.UploadTarget(
            kind=kind, slot=slot, key=key, old_value="https://old.example/image.png",
            guild_id=1, owner_id=2, source_channel_id=3, source_message_id=4,
            clan_name="Clan Name", clan_id="clan-id",
        )
        uploads._PENDING["token"] = (uploads.time.monotonic(), target)
        order = []
        interaction = modal_interaction()
        ctx = Ctx(interaction, order=order)

        async def acknowledged(*args, **kwargs):
            order.append("ack")

        interaction.create_initial_response = AsyncMock(side_effect=acknowledged)
        media = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://img.example/new.png"))
        monkeypatch.setattr(uploads, "pop_file_upload", lambda *args: {
            "size": 100, "url": "https://cdn.discordapp.com/attachments/1/2/image.png",
        })

        async def download(*args):
            order.append("download")
            return b"image"

        monkeypatch.setattr(uploads.asyncio, "to_thread", download)
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=ctx, action_id="token", mongo=mongo, media=media)
        assert order == ["ack", "download"]
        collection = mongo.clans if kind == "clan" else mongo.fwa_data
        query, update, kwargs = collection.writes[-1]
        field = slot if kind == "clan" else f"{slot}_base_images.{key}"
        assert update == {"$set": {field: "https://img.example/new.png"}}
        assert set(update["$set"]) == {field}
        if kind == "clan":
            assert query["_id"] == "clan-id"
            assert media.upload_bytes.await_args.kwargs["folder"] == "clans/Clan_Name"
        else:
            target_map = uploads.FWA_WAR_BASE if slot == "war" else uploads.FWA_ACTIVE_WAR_BASE
            assert target_map[key] == "https://img.example/new.png"
        payload, _ = uploads._success_panel(target, "https://img.example/new.png")[0].build()
        assert any(component["type"] == 12 for component in payload["components"])
    asyncio.run(run())


@pytest.mark.parametrize("changed", [
    {"guild": 9}, {"user": 9}, {"channel": 9}, {"message": SimpleNamespace(id=9)}, {"message": None},
])
def test_submit_rejects_wrong_bound_editor_or_source_without_write(monkeypatch, changed):
    async def run():
        mongo = mongo_for("clan", "logo", "#ABC")
        target = uploads.UploadTarget("clan", "logo", "#ABC", "old", 1, 2, 3, 4, "Clan Name", "clan-id")
        uploads._PENDING["token"] = (uploads.time.monotonic(), target)
        interaction = modal_interaction(**changed)
        ctx = Ctx(interaction)
        media = SimpleNamespace(upload_bytes=AsyncMock())
        monkeypatch.setattr(uploads, "pop_file_upload", lambda *args: {"size": 1, "url": "https://cdn.discordapp.com/attachments/1/2/a.png"})
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=ctx, action_id="token", mongo=mongo, media=media)
        media.upload_bytes.assert_not_awaited()
        assert not mongo.clans.writes
        interaction.edit_initial_response.assert_awaited_once()
    asyncio.run(run())


def test_expired_invalid_or_unprivileged_submissions_do_not_write(monkeypatch):
    async def run():
        mongo = mongo_for("clan", "logo", "#ABC")
        target = uploads.UploadTarget("clan", "logo", "#ABC", "old", 1, 2, 3, 4, "Clan Name", "clan-id")
        media = SimpleNamespace(upload_bytes=AsyncMock())
        monkeypatch.setattr(uploads, "pop_file_upload", lambda *args: {"size": 11 * 1024 * 1024, "url": "https://cdn.discordapp.com/attachments/1/2/a.png"})
        # Expiry consumes the stale token without any database call.
        uploads._PENDING["token"] = (uploads.time.monotonic() - uploads.TTL_SECONDS - 1, target)
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=Ctx(modal_interaction()), action_id="token", mongo=mongo, media=media)
        # Invalid attachment has a known target, so it offers recovery controls but does not write.
        uploads._PENDING["token"] = (uploads.time.monotonic(), target)
        invalid_ctx = Ctx(modal_interaction())
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=invalid_ctx, action_id="token", mongo=mongo, media=media)
        payload = invalid_ctx.interaction.edit_initial_response.await_args.kwargs["components"][0].build()[0]
        assert any(c["type"] == 1 for c in payload["components"])
        # Role loss is checked again after acknowledgement.
        uploads._PENDING["token"] = (uploads.time.monotonic(), target)
        denied = Ctx(modal_interaction(), allowed=False)
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=denied, action_id="token", mongo=mongo, media=media)
        media.upload_bytes.assert_not_awaited()
        assert not mongo.clans.writes
    asyncio.run(run())


def test_failed_persistence_keeps_fwa_memory_map_unchanged(monkeypatch):
    async def run():
        mongo = mongo_for("fwa", "war", "th16")
        mongo.fwa_data.matched = 0
        target = uploads.UploadTarget("fwa", "war", "th16", "old", 1, 2, 3, 4)
        uploads._PENDING["token"] = (uploads.time.monotonic(), target)
        ctx = Ctx(modal_interaction())
        monkeypatch.setattr(uploads, "pop_file_upload", lambda *args: {"size": 1, "url": "https://cdn.discordapp.com/attachments/1/2/a.png"})
        monkeypatch.setattr(uploads.asyncio, "to_thread", AsyncMock(return_value=b"image"))
        media = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://img.example/new.png"))
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=ctx, action_id="token", mongo=mongo, media=media)
        assert "th16" not in uploads.FWA_WAR_BASE
        assert mongo.fwa_data.writes
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["download", "storage"])
def test_download_or_storage_failure_has_recovery_without_database_write(monkeypatch, failure):
    async def run():
        mongo = mongo_for("fwa", "war", "th16")
        target = uploads.UploadTarget("fwa", "war", "th16", "old", 1, 2, 3, 4)
        uploads._PENDING["token"] = (uploads.time.monotonic(), target)
        ctx = Ctx(modal_interaction())
        media = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://img.example/new.png"))
        monkeypatch.setattr(uploads, "pop_file_upload", lambda *args: {"size": 1, "url": "https://cdn.discordapp.com/attachments/1/2/a.png"})
        if failure == "download":
            monkeypatch.setattr(uploads.asyncio, "to_thread", AsyncMock(side_effect=uploads.requests.RequestException("offline")))
        else:
            monkeypatch.setattr(uploads.asyncio, "to_thread", AsyncMock(return_value=b"image"))
            media.upload_bytes.side_effect = uploads.MediaStoreError("invalid image")
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=ctx, action_id="token", mongo=mongo, media=media)
        assert not mongo.fwa_data.writes
        assert "th16" not in uploads.FWA_WAR_BASE
        payload = ctx.interaction.edit_initial_response.await_args.kwargs["components"][0].build()[0]
        assert any(component["type"] == 1 for component in payload["components"])
    asyncio.run(run())


def test_mongo_exception_never_claims_save_or_updates_fwa_map(monkeypatch):
    async def run():
        mongo = mongo_for("fwa", "active", "th16")
        async def broken_update(*args, **kwargs):
            raise RuntimeError("network uncertain")
        mongo.fwa_data.update_one = broken_update
        target = uploads.UploadTarget("fwa", "active", "th16", "old", 1, 2, 3, 4)
        uploads._PENDING["token"] = (uploads.time.monotonic(), target)
        ctx = Ctx(modal_interaction())
        monkeypatch.setattr(uploads, "pop_file_upload", lambda *args: {"size": 1, "url": "https://cdn.discordapp.com/attachments/1/2/a.png"})
        monkeypatch.setattr(uploads.asyncio, "to_thread", AsyncMock(return_value=b"image"))
        media = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://img.example/new.png"))
        await uploads.dashboard_image_submit.__wrapped__._func(ctx=ctx, action_id="token", mongo=mongo, media=media)
        assert "th16" not in uploads.FWA_ACTIVE_WAR_BASE
        payload = ctx.interaction.edit_initial_response.await_args.kwargs["components"][0].build()[0]
        contents = " ".join(c.get("content", "") for c in payload["components"])
        assert "could not confirm" in contents
        assert "saved" not in contents.lower()
    asyncio.run(run())


def test_pending_cache_is_bounded_and_each_token_is_one_shot():
    target = uploads.UploadTarget("clan", "logo", "#ABC", None, 1, 2, 3, 4)
    now = uploads.time.monotonic()
    for number in range(uploads.MAX_PENDING + 2):
        uploads._PENDING[str(number)] = (now, target)
        uploads._prune_pending()
    assert len(uploads._PENDING) <= uploads.MAX_PENDING
    uploads._PENDING["once"] = (now, target)
    assert uploads._consume("once") == target
    assert uploads._consume("once") is None


def test_two_open_modals_keep_their_target_and_old_value_independent():
    async def run():
        mongo = mongo_for("clan", "logo", "#ABC")
        mongo.clans.document["banner"] = "https://old.example/banner.png"
        ctx = Ctx(click_interaction())
        await uploads._open(ctx, "logo:#ABC", mongo, "clan")
        first = ctx.modal["custom_id"].split(":", 1)[1]
        await uploads._open(ctx, "banner:#ABC", mongo, "clan")
        second = ctx.modal["custom_id"].split(":", 1)[1]
        assert first != second
        assert uploads._PENDING[first][1].slot == "logo"
        assert uploads._PENDING[first][1].old_value == "https://old.example/image.png"
        assert uploads._PENDING[second][1].slot == "banner"
        assert uploads._PENDING[second][1].old_value == "https://old.example/banner.png"
    asyncio.run(run())

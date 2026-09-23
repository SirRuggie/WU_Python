import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import hikari
import pytest
from hikari.impl.rest import RESTClientImpl

from utils import cwl_media as media
from utils.media_store import MediaStoreError


@pytest.fixture(autouse=True)
def clear_pending():
    media._pending.clear()
    yield
    media._pending.clear()


def event(**overrides):
    payload = {
        "type": 5, "id": "55", "guild_id": "100", "member": {"user": {"id": "200"}},
        "token": "must-not-be-retained",
        "data": {
            "custom_id": "cwl_image_submit:draft",
            "components": [{"type": 18, "component": {
                "type": 19, "custom_id": "cwl_image", "values": ["300"],
            }}],
            "resolved": {"attachments": {"300": {
                "id": "300", "size": 100, "filename": "image.png",
                "url": "https://cdn.discordapp.com/ephemeral-attachments/100/300/image.png?ex=123",
            }}},
        },
    }
    payload.update(overrides)
    return SimpleNamespace(name="INTERACTION_CREATE", payload=payload)


def interaction(**overrides):
    return SimpleNamespace(**({
        "id": 55, "guild_id": 100, "user": SimpleNamespace(id=200),
        "custom_id": "cwl_image_submit:draft",
    } | overrides))


def test_upload_modal_serializes_through_pinned_hikari_rest():
    async def run():
        rest = object.__new__(RESTClientImpl)
        rest._entity_factory = MagicMock()
        with patch.object(RESTClientImpl, "_request", new_callable=AsyncMock, return_value={}) as request:
            await rest.create_modal_response(55, "token", title="Change image", custom_id="cwl_image_submit:draft", components=media.upload_modal_components())
        body = request.call_args.kwargs["json"]
        assert body["type"] == hikari.ResponseType.MODAL
        label = body["data"]["components"][0]
        assert label["type"] == 18
        assert label["component"] == {
            "type": 19, "custom_id": "cwl_image", "min_values": 1,
            "max_values": 1, "required": True,
            "file_types": [".png", ".jpg", ".jpeg", ".gif", ".webp"],
        }
    asyncio.run(run())


def test_upload_consumes_exact_attachment_without_retaining_token():
    async def run():
        await media.capture_upload_payload(event())
        assert "must-not-be-retained" not in repr(media._pending)
        store = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://images.example/new.png"))
        with patch.object(media.asyncio, "to_thread", new_callable=AsyncMock, return_value=b"image") as download:
            result = await media.upload_from_modal(interaction(), store, guild_id=100, message_id="reminder-1", audience="main")
        assert result == "https://images.example/new.png"
        download.assert_awaited_once()
        store.upload_bytes.assert_awaited_once_with(b"image", folder="content/cwl/100/reminder-1", name="main")
        assert not media._pending
        with pytest.raises(MediaStoreError, match="expired"):
            await media.upload_from_modal(interaction(), store, guild_id=100, message_id="reminder-1", audience="main")
    asyncio.run(run())


@pytest.mark.parametrize("changed", [
    {"user": SimpleNamespace(id=201)}, {"guild_id": 101}, {"custom_id": "cwl_image_submit:other"},
])
def test_upload_rejects_wrong_owner_guild_or_draft(changed):
    async def run():
        await media.capture_upload_payload(event())
        store = SimpleNamespace(upload_bytes=AsyncMock())
        with pytest.raises(MediaStoreError, match="another editor"):
            await media.upload_from_modal(interaction(**changed), store, guild_id=100, message_id="open", audience="main")
        store.upload_bytes.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("attachment", [
    {"size": 11 * 1024 * 1024}, {"url": "http://cdn.discordapp.com/attachments/1/2/a.png"},
    {"url": "https://example.com/a.png"}, {"url": "https://cdn.discordapp.com.evil.test/attachments/a.png"},
    {"url": "https://cdn.discordapp.com/other/a.png"}, {"url": "https://user@cdn.discordapp.com/attachments/a.png"},
])
def test_invalid_attachment_never_downloaded(attachment):
    async def run():
        raw = event()
        raw.payload["data"]["resolved"]["attachments"]["300"].update(attachment)
        await media.capture_upload_payload(raw)
        with patch.object(media.asyncio, "to_thread", new_callable=AsyncMock) as download:
            with pytest.raises(MediaStoreError):
                await media.upload_from_modal(interaction(), MagicMock(), guild_id=100, message_id="open", audience="main")
        download.assert_not_awaited()
    asyncio.run(run())


def test_listener_ignores_other_modals_and_bounds_retained_data():
    async def run():
        raw = event()
        raw.payload["data"]["custom_id"] = "another_modal:1"
        await media.capture_upload_payload(raw)
        assert not media._pending
        for index in range(media.MAX_PENDING + 5):
            await media.capture_upload_payload(event(id=str(index)))
        assert len(media._pending) == media.MAX_PENDING
        assert 0 not in media._pending
        with patch.object(media.time, "monotonic", return_value=media.time.monotonic() + media.TTL_SECONDS + 1):
            media._prune()
        assert not media._pending
    asyncio.run(run())


def test_raw_gateway_listener_can_arrive_after_typed_handler():
    async def run():
        task = asyncio.create_task(media.capture_upload_payload(event()))
        store = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://images.example/new.png"))
        with patch.object(media.asyncio, "to_thread", new_callable=AsyncMock, return_value=b"image"):
            assert await media.upload_from_modal(interaction(), store, guild_id=100, message_id="open", audience="lazy")
        await task
    asyncio.run(run())

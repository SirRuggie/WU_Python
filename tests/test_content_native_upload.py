"""Integration coverage for Discord's native modal file-upload compatibility path."""

import asyncio
import dataclasses
from datetime import timedelta
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions import components
from extensions.commands import content
from extensions.commands.setup import recruit_aboutus
from utils import discord_file_upload
from utils.component_state import utcnow
from utils.media_store import MediaStoreError


class _Collection:
    def __init__(self, documents=()):
        self.documents = {item["_id"]: dict(item) for item in documents}

    async def find_one(self, query, projection=None):
        item = self.documents.get(query["_id"])
        return dict(item) if item is not None else None

    async def insert_one(self, document):
        self.documents[document["_id"]] = dict(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def delete_one(self, query):
        self.documents.pop(query["_id"], None)
        return SimpleNamespace(deleted_count=1)


class _ModalInteraction:
    def __init__(self, interaction_id, custom_id, *, user_id=10, guild_id=20,
                 permissions=hikari.Permissions.MANAGE_GUILD, modal_components=()):
        self.id = hikari.Snowflake(interaction_id)
        self.custom_id = custom_id
        self.guild_id = hikari.Snowflake(guild_id)
        self.member = SimpleNamespace(permissions=permissions)
        self.user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(channel_id=30, id=40)
        self.components = modal_components
        self.initial_responses = []
        self.edits = []

    async def create_initial_response(self, response_type):
        self.initial_responses.append(response_type)

    async def edit_initial_response(self, **kwargs):
        self.edits.append(kwargs)


class _ModalContext:
    def __init__(self, interaction):
        self.interaction = interaction
        self.user = interaction.user
        self.responses = []

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))

    async def defer(self, **kwargs):
        raise AssertionError("the modal handler must acknowledge through its source message")


def _mongo(*states):
    return SimpleNamespace(
        component_state=_Collection(states),
        button_store=_Collection(),
    )


def _state(state_id="draft", **changes):
    result = {
        "_id": state_id,
        "user_id": 10,
        "guild_id": 20,
        "view": "document",
        "document": "about-us",
        "sections": recruit_aboutus.default_sections(),
        "revision": 0,
        "media": {},
        "selected_media_slot": "welcome",
        "expires_at": utcnow() + timedelta(minutes=30),
    }
    result.update(changes)
    return result


def _raw_payload(interaction_id, custom_id, *, attachment_id="777", size=68):
    return {
        "application_id": "999",
        "id": str(interaction_id),
        "type": 5,
        "app_permissions": "0",
        "locale": "en-US",
        "channel": {"id": "30", "type": 0},
        "user": {
            "id": "10", "username": "editor", "discriminator": "0",
            "avatar": None, "global_name": "Editor", "public_flags": 0,
        },
        "token": "interaction-token",
        "version": 1,
        "authorizing_integration_owners": {},
        "context": 0,
        "attachment_size_limit": 10_000_000,
        "data": {
            "custom_id": custom_id,
            "components": [{
                "type": 18,
                "id": 1,
                "component": {
                    "type": 19,
                    "id": 2,
                    "custom_id": "image",
                    "values": [attachment_id],
                },
            }],
            "resolved": {"attachments": {attachment_id: {
                "id": attachment_id,
                "filename": "replacement.png",
                "content_type": "image/png",
                "size": size,
                "url": "https://cdn.discordapp.com/ephemeral-attachments/1/777/replacement.png",
                "proxy_url": "https://media.discordapp.net/ephemeral-attachments/1/777/replacement.png",
                "height": 1,
                "width": 1,
                "ephemeral": True,
            }}},
        },
    }


def _capture(payload):
    """Feed the documented payload through Hikari's public interaction adapter."""
    factory = hikari.impl.EntityFactoryImpl(SimpleNamespace())
    return factory.deserialize_interaction(payload)


def test_builder_emits_discord_label_wrapping_one_required_image_upload():
    built, attachments = discord_file_upload.FileUploadModalComponentBuilder(
        custom_id="image", label="Welcome banner", description="Choose an image"
    ).build()

    assert attachments == ()
    assert built == {
        "type": 18,
        "label": "Welcome banner",
        "description": "Choose an image",
        "component": {
            "type": 19,
            "custom_id": "image",
            "min_values": 1,
            "max_values": 1,
            "required": True,
            "file_types": [".png", ".jpg", ".jpeg", ".gif", ".webp"],
        },
    }


def test_installation_before_factory_construction_captures_gateway_payload():
    """main.py installs the adapter before GatewayBot constructs this factory."""
    script = """
import json
from types import SimpleNamespace
import hikari
from utils import discord_file_upload as upload
upload.install_file_upload_capture()
factory = hikari.impl.EntityFactoryImpl(SimpleNamespace())
payload = json.loads(%r)
interaction = factory.deserialize_interaction(payload)
assert interaction.id == 509
assert upload.pop_file_upload(509, payload['data']['custom_id'], 'image')['id'] == '777'
""" % json.dumps(_raw_payload(509, "content_upload_submit:before"))
    subprocess.run([sys.executable, "-c", script], check=True)


def test_main_installs_capture_before_gateway_constructs_cached_factory():
    source = (content.__file__.replace("extensions/commands/content.py", "main.py"))
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert text.index("install_file_upload_capture()") < text.index("hikari.GatewayBot(")


def test_open_upload_uses_native_builder_accepted_by_modal_response_path():
    async def check():
        state = _state()
        captured = []
        interaction = _ModalInteraction(510, "content_upload:draft")
        ctx = _ModalContext(interaction)

        async def respond_with_modal(**kwargs):
            captured.append(kwargs)

        ctx.respond_with_modal = respond_with_modal
        await content.open_upload_modal(ctx=ctx, action_id="draft", mongo=_mongo(state))

        assert captured[0]["custom_id"].startswith("content_upload_submit:")
        payload, attachments = captured[0]["components"][0].build()
        assert payload["type"] == 18
        assert payload["component"]["type"] == 19
        assert attachments == ()

    asyncio.run(check())


def test_selected_image_panel_never_exceeds_discord_action_row_limit():
    dashboard = content.panel(_state())
    rows = [
        item for item in dashboard[0].components
        if item.type == hikari.ComponentType.ACTION_ROW
    ]
    assert rows
    assert all(len(row.components) <= 5 for row in rows)


def test_documented_payload_survives_hikari_26_deserialization_loss_and_is_one_shot():
    payload = _raw_payload(501, "content_upload_submit:draft")
    _capture(payload)

    attachment = discord_file_upload.pop_file_upload(
        501, "content_upload_submit:draft", "image"
    )
    assert attachment["id"] == "777"
    assert attachment["ephemeral"] is True
    assert discord_file_upload.pop_file_upload(
        501, "content_upload_submit:draft", "image"
    ) is None


def test_raw_payload_routes_through_dispatcher_uploads_and_edits_same_panel(monkeypatch):
    async def check():
        interaction_id = 502
        custom_id = "content_upload_submit:draft"
        _capture(_raw_payload(interaction_id, custom_id))
        interaction = _ModalInteraction(interaction_id, custom_id)
        ctx = _ModalContext(interaction)
        media = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://media.example/new.png"))
        mongo = _mongo(_state())

        action = components.registered_functions["content_upload_submit"]

        async def invoke(**kwargs):
            return await content.submit_upload(mongo=mongo, media=media, **kwargs)

        monkeypatch.setitem(
            components.registered_functions,
            "content_upload_submit",
            dataclasses.replace(action, fn=invoke),
        )
        monkeypatch.setattr(hikari.Attachment, "read", AsyncMock(return_value=b"valid-image"))

        await components._dispatch(ctx, mongo)

        assert interaction.initial_responses == [hikari.ResponseType.DEFERRED_MESSAGE_UPDATE]
        assert len(interaction.edits) == 1
        assert ctx.responses == []
        media.upload_bytes.assert_awaited_once()
        inserted = [row for key, row in mongo.component_state.documents.items() if key != "draft"]
        assert inserted[-1]["media"] == {"welcome": "https://media.example/new.png"}

    asyncio.run(check())


@pytest.mark.parametrize("state,interaction_kwargs", [
    (None, {}),
    (_state(user_id=999), {}),
    (_state(guild_id=999), {}),
    (_state(expires_at=utcnow() - timedelta(seconds=1)), {}),
    (_state(), {"permissions": hikari.Permissions.NONE}),
])
def test_expired_or_unauthorized_upload_is_rejected_before_download(
    monkeypatch, state, interaction_kwargs
):
    async def check():
        interaction_id = 520 + len(discord_file_upload._SUBMISSIONS)
        custom_id = "content_upload_submit:draft"
        _capture(_raw_payload(interaction_id, custom_id))
        interaction = _ModalInteraction(interaction_id, custom_id, **interaction_kwargs)
        media = SimpleNamespace(upload_bytes=AsyncMock())
        mongo = _mongo(*(() if state is None else (state,)))
        monkeypatch.setattr(hikari.Attachment, "read", AsyncMock())

        await content.submit_upload(
            ctx=_ModalContext(interaction), action_id="draft", mongo=mongo, media=media
        )

        hikari.Attachment.read.assert_not_awaited()
        media.upload_bytes.assert_not_awaited()
        assert len(interaction.edits) == 1

    asyncio.run(check())


def test_cancelled_or_malformed_upload_preserves_source_panel_and_draft(monkeypatch):
    async def check():
        payload = _raw_payload(530, "content_upload_submit:draft")
        payload["data"]["components"][0]["component"]["values"] = []
        _capture(payload)
        interaction = _ModalInteraction(530, "content_upload_submit:draft")
        read = AsyncMock()
        monkeypatch.setattr(hikari.Attachment, "read", read)
        mongo = _mongo(_state())
        media = SimpleNamespace(upload_bytes=AsyncMock())

        await content.submit_upload(
            ctx=_ModalContext(interaction), action_id="draft", mongo=mongo, media=media
        )

        read.assert_not_awaited()
        media.upload_bytes.assert_not_awaited()
        assert set(mongo.component_state.documents) == {"draft"}
        assert interaction.initial_responses == [hikari.ResponseType.DEFERRED_MESSAGE_UPDATE]
        assert interaction.edits[-1]["components"]

    asyncio.run(check())


@pytest.mark.parametrize("failure", [hikari.BadRequestError, OSError])
def test_attachment_download_failure_preserves_draft(monkeypatch, failure):
    async def check():
        interaction_id = 531 if failure is OSError else 532
        custom_id = "content_upload_submit:draft"
        _capture(_raw_payload(interaction_id, custom_id))
        if failure is OSError:
            error = OSError("network")
        else:
            error = hikari.BadRequestError("https://discord.test", {}, b"bad", None)
        monkeypatch.setattr(hikari.Attachment, "read", AsyncMock(side_effect=error))
        mongo = _mongo(_state())
        media = SimpleNamespace(upload_bytes=AsyncMock())

        await content.submit_upload(
            ctx=_ModalContext(_ModalInteraction(interaction_id, custom_id)),
            action_id="draft", mongo=mongo, media=media,
        )

        media.upload_bytes.assert_not_awaited()
        assert set(mongo.component_state.documents) == {"draft"}

    asyncio.run(check())


def test_declared_oversize_attachment_is_rejected_before_download(monkeypatch):
    async def check():
        interaction_id = 505
        custom_id = "content_upload_submit:draft"
        _capture(_raw_payload(interaction_id, custom_id, size=content.MAX_IMAGE_BYTES + 1))
        interaction = _ModalInteraction(interaction_id, custom_id)
        read = AsyncMock()
        monkeypatch.setattr(hikari.Attachment, "read", read)
        media = SimpleNamespace(upload_bytes=AsyncMock())

        await content.submit_upload(
            ctx=_ModalContext(interaction), action_id="draft", mongo=_mongo(_state()), media=media
        )

        read.assert_not_awaited()
        media.upload_bytes.assert_not_awaited()
        limit = content.MAX_IMAGE_BYTES // (1024 * 1024)
        assert f"under {limit} MB" in str(interaction.edits[-1]["components"][0].build())

    asyncio.run(check())


def test_downloaded_non_image_is_rejected_without_changing_draft(monkeypatch):
    async def check():
        interaction_id = 511
        custom_id = "content_upload_submit:draft"
        _capture(_raw_payload(interaction_id, custom_id))
        interaction = _ModalInteraction(interaction_id, custom_id)
        monkeypatch.setattr(hikari.Attachment, "read", AsyncMock(return_value=b"not an image"))
        media = SimpleNamespace(
            upload_bytes=AsyncMock(side_effect=MediaStoreError("Only image files are supported."))
        )
        mongo = _mongo(_state())

        await content.submit_upload(
            ctx=_ModalContext(interaction), action_id="draft", mongo=mongo, media=media
        )

        assert set(mongo.component_state.documents) == {"draft"}
        assert "Only image files are supported" in str(
            interaction.edits[-1]["components"][0].build()
        )

    asyncio.run(check())


def test_existing_text_modal_submission_still_reads_hikari_action_rows(monkeypatch):
    async def check():
        state = _state(selected_block=0)
        text = SimpleNamespace(custom_id="content", value="Updated native text path")
        interaction = _ModalInteraction(
            506, "content_submit:draft", modal_components=((text,),)
        )
        mongo = _mongo(state)

        await content.submit_block(
            ctx=_ModalContext(interaction), action_id="draft", mongo=mongo
        )

        assert interaction.initial_responses == [hikari.ResponseType.DEFERRED_MESSAGE_UPDATE]
        inserted = [row for key, row in mongo.component_state.documents.items() if key != "draft"]
        assert inserted[-1]["sections"][0] == "Updated native text path"

    asyncio.run(check())

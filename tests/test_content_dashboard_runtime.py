import asyncio
import dataclasses
import itertools
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions import components
from extensions.commands import content
from extensions.commands.setup import (
    recruit_aboutus,
    recruit_familyparticulars,
    recruit_strikesystem,
)


def _run(coro):
    return asyncio.run(coro)


def _as_discord_models(builders):
    """Convert native builders to the concrete models returned by REST fetches."""
    ids = itertools.count(1)

    def convert(item):
        component_id = next(ids)
        if item.type == hikari.ComponentType.TEXT_DISPLAY:
            return hikari.TextDisplayComponent(
                type=item.type, id=component_id, content=item.content
            )
        if item.type == hikari.ComponentType.SEPARATOR:
            spacing = item.spacing
            if spacing is hikari.UNDEFINED:
                spacing = hikari.SpacingType.SMALL
            divider = item.divider
            if divider is hikari.UNDEFINED:
                divider = True
            return hikari.SeparatorComponent(
                type=item.type, id=component_id, spacing=spacing, divider=divider
            )
        if item.type == hikari.ComponentType.MEDIA_GALLERY:
            # The dashboard compares the component tree, not media item payloads.
            # This is still the concrete model Discord's entity factory returns.
            return hikari.MediaGalleryComponent(type=item.type, id=component_id, items=())
        if item.type == hikari.ComponentType.BUTTON:
            return hikari.ButtonComponent(
                type=item.type,
                id=component_id,
                style=item.style,
                label=item.label,
                emoji=None,
                custom_id=item.custom_id,
                url=getattr(item, "url", None),
                is_disabled=item.is_disabled,
            )
        if item.type == hikari.ComponentType.ACTION_ROW:
            return hikari.ActionRowComponent(
                type=item.type,
                id=component_id,
                components=tuple(convert(child) for child in item.components),
            )
        if item.type == hikari.ComponentType.CONTAINER:
            accent = item.accent_color
            if accent is hikari.UNDEFINED:
                accent = None
            return hikari.ContainerComponent(
                type=item.type,
                id=component_id,
                accent_color=accent,
                is_spoiler=item.is_spoiler,
                components=tuple(convert(child) for child in item.components),
            )
        raise AssertionError(f"Unhandled builder type {item.type!r}")

    return tuple(convert(item) for item in builders)


def _custom_ids(items):
    return [
        child.custom_id
        for item in items
        for child in getattr(item, "components", ())
        if getattr(child, "custom_id", None)
    ] + [
        custom_id
        for item in items
        for child in getattr(item, "components", ())
        for custom_id in _custom_ids((child,))
    ]


class _PanelContext:
    """Interaction context that records the real dispatcher edit contract."""
    def __init__(self, custom_id, values=()):
        self.user = SimpleNamespace(id=10)
        self.events = []
        self.interaction = SimpleNamespace(
            custom_id=custom_id,
            values=values,
            member=SimpleNamespace(permissions=hikari.Permissions.MANAGE_GUILD),
            message=SimpleNamespace(channel_id=30, id=40),
            app=SimpleNamespace(rest=SimpleNamespace(edit_message=AsyncMock())),
            guild_id=20,
            application_id=999,
        )

    async def defer(self, *, edit=False):
        self.events.append(("defer", edit))

    async def respond(self, *args, **kwargs):
        self.events.append(("respond", args, kwargs))


def _dispatch_content_action(monkeypatch, name, function, mongo):
    """Exercise the real dispatcher while supplying this test's explicit DI."""
    action = components.registered_functions[name]

    async def invoke(**kwargs):
        return await function(mongo=mongo, **kwargs)

    monkeypatch.setitem(components.registered_functions, name, dataclasses.replace(action, fn=invoke))


class _ConfigCollection:
    def __init__(self, documents=None, *, lease_busy=False):
        self.documents = dict(documents or {})
        self.lease_busy = lease_busy
        self.updates = []
        self.inserts = []
        self.deletes = []

    async def find_one(self, query):
        return self.documents.get(query["_id"])

    async def insert_one(self, document):
        if document["_id"] in self.documents:
            raise DuplicateKeyError("duplicate")
        self.documents[document["_id"]] = dict(document)
        self.inserts.append(dict(document))
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update, *, upsert=False):
        self.updates.append((query, update, upsert))
        if query["_id"].startswith("content_publish:"):
            if self.lease_busy:
                raise DuplicateKeyError("busy")
            return SimpleNamespace(matched_count=0, upserted_id=query["_id"])
        current = self.documents.get(query["_id"])
        matched = bool(current and current.get("revision") == query.get("revision"))
        if matched:
            current.update(update["$set"])
        return SimpleNamespace(matched_count=int(matched), upserted_id=None)

    async def delete_one(self, query):
        self.deletes.append(query)
        return SimpleNamespace(deleted_count=1)


class _Context:
    def __init__(self, *, guild_id=20, user_id=10, application_id=999):
        self.user = SimpleNamespace(id=user_id)
        self.channel_id = 30
        self.interaction = SimpleNamespace(
            guild_id=guild_id,
            application_id=application_id,
            member=SimpleNamespace(permissions=hikari.Permissions.MANAGE_GUILD),
            edit_initial_response=self._edit_initial_response,
        )
        self.events = []

    async def defer(self, **kwargs):
        self.events.append(("defer", kwargs))

    async def respond(self, *args, **kwargs):
        self.events.append(("respond", args, kwargs))

    async def _edit_initial_response(self, *args, **kwargs):
        self.events.append(("edit_initial_response", args, kwargs))


def test_real_hikari_models_adopt_existing_post_and_keep_template_revision(monkeypatch):
    async def check():
        document = content.DOCUMENTS["about-us"]
        baseline = await content.baseline(document)
        models = _as_discord_models(baseline)
        sections = [node.content for node in content.text_nodes(models)]
        config = _ConfigCollection({
            "content:about-us:20": {
                "_id": "content:about-us:20", "sections": sections, "revision": 7
            }
        })
        captured = []

        async def capture_draft(_mongo, state):
            captured.append(dict(state))
            return dict(state, _id="draft")

        monkeypatch.setattr(content, "new_draft", capture_draft)
        message = SimpleNamespace(author=SimpleNamespace(id=999), components=models)
        rest = SimpleNamespace(
            fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),
            fetch_message=AsyncMock(return_value=message),
        )
        command = content.ContentDashboard()
        command.message_link = "https://discord.com/channels/20/30/40"
        ctx = _Context()
        await command.invoke(ctx, mongo=SimpleNamespace(bot_config=config), bot=SimpleNamespace(rest=rest))

        assert captured[-1]["document"] == "about-us"
        assert captured[-1]["sections"] == sections
        assert captured[-1]["revision"] == 7
        assert captured[-1]["target"] == {
            "channel_id": 30, "message_id": 40, "original": sections
        }
        assert ctx.events[0] == ("defer", {"ephemeral": True})
        assert ctx.events[-1][0] == "edit_initial_response"

    _run(check())


def test_adoption_rejects_real_model_with_noncanonical_type_tree(monkeypatch):
    async def check():
        document = content.DOCUMENTS["about-us"]
        models = list(_as_discord_models(await content.baseline(document)))
        container = models[1]
        models[1] = hikari.ContainerComponent(
            type=container.type,
            id=container.id,
            accent_color=container.accent_color,
            is_spoiler=container.is_spoiler,
            components=tuple(
                child for child in container.components
                if child.type != hikari.ComponentType.SEPARATOR
            ),
        )
        created = []

        async def capture_draft(_mongo, state):
            created.append(state)
            return dict(state, _id="draft")

        monkeypatch.setattr(content, "new_draft", capture_draft)
        command = content.ContentDashboard()
        command.message_link = "https://discord.com/channels/20/30/40"
        ctx = _Context()
        await command.invoke(
            ctx,
            mongo=SimpleNamespace(bot_config=_ConfigCollection()),
            bot=SimpleNamespace(rest=SimpleNamespace(
                fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),
                fetch_message=AsyncMock(return_value=SimpleNamespace(
                    author=SimpleNamespace(id=999), components=tuple(models)
                )),
            )),
        )

        assert created
        edited = next(event for event in ctx.events if event[0] == "edit_initial_response")
        assert "That post's structure is not a supported content document." in "\n".join(
            item.content for item in edited[2]["components"][0].components
            if isinstance(item, hikari.impl.TextDisplayComponentBuilder)
        )

    _run(check())


def test_real_hikari_model_publish_updates_linked_post_without_mentions(monkeypatch):
    async def check():
        document = content.DOCUMENTS["strike-system"]
        models = _as_discord_models(await content.baseline(document))
        original = [node.content for node in content.text_nodes(models)]
        edited = list(original)
        edited[0] = edited[0] + " edited"
        state = {
            "_id": "draft",
            "user_id": 10,
            "guild_id": 20,
            "document": "strike-system",
            "sections": edited,
            "revision": 1,
            "target": {"channel_id": 30, "message_id": 40, "original": original},
        }

        async def load_state(*_args):
            return state, None

        async def next_draft(_mongo, value):
            return dict(value, _id="next")

        monkeypatch.setattr(content, "load", load_state)
        monkeypatch.setattr(content, "new_draft", next_draft)
        config = _ConfigCollection()
        edit_message = AsyncMock()
        rest = SimpleNamespace(
            fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),
            fetch_message=AsyncMock(return_value=SimpleNamespace(
                author=SimpleNamespace(id=999), components=models
            )),
            edit_message=edit_message,
        )
        ctx = _Context()
        panel = await content.publish.__wrapped__._func(
            ctx=ctx,
            action_id="draft",
            mongo=SimpleNamespace(bot_config=config),
            bot=SimpleNamespace(rest=rest),
        )

        assert edit_message.await_count == 1
        args = edit_message.await_args.args
        kwargs = edit_message.await_args.kwargs
        assert args[:2] == (30, 40)
        assert kwargs["user_mentions"] is False
        assert kwargs["role_mentions"] is False
        assert kwargs["mentions_everyone"] is False
        rendered_text = [node.content for node in content.text_nodes(kwargs["components"])]
        assert rendered_text == edited
        assert content.acknowledgement_id(kwargs["components"], document)
        assert config.deletes and config.deletes[-1]["token"]
        assert "Selected post updated." in panel[0].components[2].content

    _run(check())


def test_publish_refuses_cross_guild_and_active_lease_without_edit(monkeypatch):
    async def check():
        document = content.DOCUMENTS["about-us"]
        original = [node.content for node in content.text_nodes(await content.baseline(document))]
        state = {
            "_id": "draft", "user_id": 10, "guild_id": 20, "document": "about-us",
            "sections": original, "revision": 0,
            "target": {"channel_id": 30, "message_id": 40, "original": original},
        }

        async def load_state(*_args):
            return state, None

        monkeypatch.setattr(content, "load", load_state)
        edit = AsyncMock()
        cross = _ConfigCollection()
        ctx = _Context()
        await content.publish.__wrapped__._func(
            ctx=ctx, action_id="x", mongo=SimpleNamespace(bot_config=cross),
            bot=SimpleNamespace(rest=SimpleNamespace(
                fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=21)),
                edit_message=edit,
            )),
        )
        assert edit.await_count == 0
        assert cross.deletes, "cross-guild refusal must release its lease"

        busy = _ConfigCollection(lease_busy=True)
        fetch_channel = AsyncMock()
        await content.publish.__wrapped__._func(
            ctx=_Context(), action_id="x", mongo=SimpleNamespace(bot_config=busy),
            bot=SimpleNamespace(rest=SimpleNamespace(
                fetch_channel=fetch_channel, edit_message=edit
            )),
        )
        assert fetch_channel.await_count == 0
        assert edit.await_count == 0

    _run(check())


def test_publish_refuses_stale_real_model_without_edit(monkeypatch):
    async def check():
        document = content.DOCUMENTS["family-particulars"]
        models = list(_as_discord_models(await content.baseline(document)))
        original = [node.content for node in content.text_nodes(models)]
        changed_container = models[1]
        changed_children = list(changed_container.components)
        first = changed_children[0]
        changed_children[0] = hikari.TextDisplayComponent(
            type=first.type, id=first.id, content=first.content + " changed elsewhere"
        )
        models[1] = hikari.ContainerComponent(
            type=changed_container.type,
            id=changed_container.id,
            accent_color=changed_container.accent_color,
            is_spoiler=changed_container.is_spoiler,
            components=tuple(changed_children),
        )
        state = {
            "_id": "draft", "user_id": 10, "guild_id": 20, "document": document.key,
            "sections": original, "revision": 0,
            "target": {"channel_id": 30, "message_id": 40, "original": original},
        }

        async def load_state(*_args):
            return state, None

        monkeypatch.setattr(content, "load", load_state)
        edit = AsyncMock()
        config = _ConfigCollection()
        await content.publish.__wrapped__._func(
            ctx=_Context(),
            action_id="x",
            mongo=SimpleNamespace(bot_config=config),
            bot=SimpleNamespace(rest=SimpleNamespace(
                fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),
                fetch_message=AsyncMock(return_value=SimpleNamespace(
                    author=SimpleNamespace(id=999), components=tuple(models)
                )),
                edit_message=edit,
            )),
        )
        edit.assert_not_awaited()
        assert config.deletes, "stale refusal must release its lease"

    _run(check())


def test_legacy_about_sections_migrate_with_new_key_revision_zero():
    async def check():
        document = content.DOCUMENTS["about-us"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        collection = _ConfigCollection({
            "recruit_aboutus:20": {
                "_id": "recruit_aboutus:20", "sections": sections, "revision": 9
            }
        })
        loaded, revision = await content.sections_for(
            SimpleNamespace(bot_config=collection), document, 20
        )
        assert loaded == sections
        assert revision == 0

    _run(check())


def test_template_save_uses_revision_compare_and_swap():
    async def check():
        key = "content:about-us:20"
        collection = _ConfigCollection({
            key: {"_id": key, "sections": ["old"], "revision": 4}
        })
        state = {
            "document": "about-us", "guild_id": 20,
            "sections": ["new"], "revision": 4,
        }
        ctx = _Context()
        assert await content._save(ctx, state, SimpleNamespace(bot_config=collection)) is True
        assert collection.documents[key]["revision"] == 5

        stale = dict(state, sections=["stale"])
        assert await content._save(ctx, stale, SimpleNamespace(bot_config=collection)) is False
        assert collection.documents[key]["sections"] == ["new"]

    _run(check())


@pytest.mark.parametrize(
    ("key", "command_type"),
    [
        ("about-us", recruit_aboutus.RecruitAboutUs),
        ("strike-system", recruit_strikesystem.RecruitStrikeSystem),
        ("family-particulars", recruit_familyparticulars.RecruitFamilyParticulars),
    ],
)
def test_setup_posters_defer_before_storage_and_use_saved_text_without_mentions(
    key, command_type
):
    async def check():
        document = content.DOCUMENTS[key]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        sections[0] = sections[0] + " saved"
        events = []

        class Collection:
            async def find_one(self, query):
                events.append(("find", query["_id"]))
                return {"_id": query["_id"], "sections": sections, "revision": 1}

        class Interaction:
            async def delete_initial_response(self):
                events.append(("delete",))

        class Context:
            guild_id = 20
            channel_id = 30
            interaction = Interaction()

            async def defer(self, **kwargs):
                events.append(("defer", kwargs))

            async def respond(self, *args, **kwargs):
                events.append(("respond", args, kwargs))

        class Rest:
            async def create_message(self, **kwargs):
                events.append(("create", kwargs))

        await command_type().invoke(
            Context(),
            bot=SimpleNamespace(rest=Rest()),
            mongo=SimpleNamespace(bot_config=Collection()),
        )

        assert events[0][0] == "defer"
        assert events[1][0] == "find"
        create = next(event[1] for event in events if event[0] == "create")
        assert content.text_nodes(create["components"])[0].content == sections[0]
        assert create["user_mentions"] is False
        assert create["role_mentions"] is False
        assert create["mentions_everyone"] is False

    _run(check())


@pytest.mark.parametrize(
    ("key", "command_type", "expected_total"),
    [
        ("about-us", recruit_aboutus.RecruitAboutUs, 2819),
        ("strike-system", recruit_strikesystem.RecruitStrikeSystem, 3585),
        ("family-particulars", recruit_familyparticulars.RecruitFamilyParticulars, 3992),
    ],
)
def test_setup_posters_fall_back_from_malformed_saved_template(
    key, command_type, expected_total
):
    async def check():
        events = []

        class Collection:
            async def find_one(self, query):
                if query["_id"].startswith("content:"):
                    return {"_id": query["_id"], "sections": ["incomplete"]}
                return None

        class Interaction:
            async def delete_initial_response(self):
                events.append(("delete",))

        class Context:
            guild_id = 20
            channel_id = 30
            interaction = Interaction()

            async def defer(self, **kwargs):
                events.append(("defer", kwargs))

            async def respond(self, *args, **kwargs):
                events.append(("respond", args, kwargs))

        class Rest:
            async def create_message(self, **kwargs):
                events.append(("create", kwargs))

        await command_type().invoke(
            Context(),
            bot=SimpleNamespace(rest=Rest()),
            mongo=SimpleNamespace(bot_config=Collection()),
        )
        create = next(event[1] for event in events if event[0] == "create")
        assert sum(len(node.content) for node in content.text_nodes(create["components"])) == expected_total
        assert create["user_mentions"] is False
        assert create["role_mentions"] is False
        assert create["mentions_everyone"] is False

    _run(check())


def test_document_select_and_back_edit_the_same_ephemeral_panel(monkeypatch):
    async def check():
        root = {"_id": "root", "user_id": 10, "guild_id": 20, "view": "root"}
        document = content.DOCUMENTS["about-us"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]

        async def state_for(_mongo, sid):
            return root if sid == "root" else dict(
                root, _id="document", view="document", document=document.key,
                sections=sections, revision=0,
            )

        async def draft_for(_mongo, state):
            return dict(state, _id="document" if state.get("view") == "document" else "root-next")

        monkeypatch.setattr(content, "get_state", state_for)
        monkeypatch.setattr(content, "new_draft", draft_for)
        mongo = SimpleNamespace(bot_config=_ConfigCollection())
        _dispatch_content_action(monkeypatch, "content_document", content.choose_document.__wrapped__._func, mongo)
        _dispatch_content_action(monkeypatch, "content_back_root", content.back_to_root.__wrapped__._func, mongo)
        ctx = _PanelContext("content_document:root", ("about-us",))
        await components._dispatch(ctx, mongo=mongo)

        assert ctx.events[0] == ("defer", True)
        assert len(ctx.events) == 2 and ctx.events[-1][2]["edit"] is True
        document_panel = ctx.events[-1][2]["components"]
        assert document_panel[0].components[0].content == "## About Us"
        ids = _custom_ids(document_panel)
        assert any(custom_id.startswith("content_block:document") for custom_id in ids)
        assert any(custom_id.startswith("content_back_root:document") for custom_id in ids)
        assert not any(custom_id.startswith("content_document:") for custom_id in ids)
        assert ctx.interaction.app.rest.edit_message.await_count == 0

        back = _PanelContext("content_back_root:document")
        await components._dispatch(back, mongo=mongo)
        root_panel = back.events[-1][2]["components"]
        root_ids = _custom_ids(root_panel)
        assert any(custom_id.startswith("content_document:root-next") for custom_id in root_ids)
        assert not any(custom_id.startswith("content_block:") for custom_id in root_ids)

    _run(check())


def test_preview_reuses_the_acknowledgement_slot_for_back_at_the_component_limit(monkeypatch):
    async def check():
        document = content.DOCUMENTS["family-particulars"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        state = {
            "_id": "family", "user_id": 10, "guild_id": 20,
            "view": "document", "document": document.key,
            "sections": sections, "revision": 0,
        }

        async def state_for(_mongo, _sid):
            return state

        monkeypatch.setattr(content, "get_state", state_for)
        mongo = SimpleNamespace(bot_config=_ConfigCollection())
        _dispatch_content_action(monkeypatch, "content_preview", content.preview.__wrapped__._func, mongo)
        _dispatch_content_action(monkeypatch, "content_back_document", content.back_to_document.__wrapped__._func, mongo)
        ctx = _PanelContext("content_preview:family")
        await components._dispatch(ctx, mongo=mongo)

        preview = ctx.events[-1][2]["components"]
        assert content.component_count(preview) == 40
        ids = _custom_ids(preview)
        assert "content_back_document:family" in ids
        assert not any(custom_id.startswith(document.acknowledgement + ":") for custom_id in ids)
        assert ctx.interaction.app.rest.edit_message.await_count == 0

        back = _PanelContext("content_back_document:family")
        await components._dispatch(back, mongo=mongo)
        assert back.events[-1][2]["components"][0].components[0].content == "## Family Particulars"

    _run(check())


def test_modal_submit_updates_its_source_panel_without_a_followup(monkeypatch):
    async def check():
        document = content.DOCUMENTS["about-us"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        state = {
            "_id": "modal", "user_id": 10, "guild_id": 20,
            "view": "document", "document": document.key, "sections": sections,
            "revision": 0, "selected_block": 0,
        }
        events = []

        async def state_for(_mongo, _sid):
            return state

        async def draft_for(_mongo, value):
            return dict(value, _id="updated")

        async def acknowledge(response_type):
            events.append(("ack", response_type))

        async def edit_initial_response(**kwargs):
            events.append(("edit", kwargs))

        ctx = SimpleNamespace(
            user=SimpleNamespace(id=10),
            interaction=SimpleNamespace(
                guild_id=20,
                message=SimpleNamespace(id=40),
                member=SimpleNamespace(permissions=hikari.Permissions.MANAGE_GUILD),
                components=((SimpleNamespace(custom_id="content", value=sections[0] + " edited"),),),
                create_initial_response=acknowledge,
                edit_initial_response=edit_initial_response,
            ),
            defer=AsyncMock(),
            respond=AsyncMock(),
        )
        monkeypatch.setattr(content, "get_state", state_for)
        monkeypatch.setattr(content, "new_draft", draft_for)
        await content.submit_block.__wrapped__._func(ctx=ctx, action_id="modal", mongo=SimpleNamespace())

        assert events[0] == ("ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        assert events[1][0] == "edit"
        assert "Block updated." in events[1][1]["components"][0].components[2].content
        ctx.respond.assert_not_awaited()
        ctx.defer.assert_not_awaited()

    _run(check())


def test_link_error_replaces_the_initial_ephemeral_response(monkeypatch):
    async def check():
        captured = []

        async def draft_for(_mongo, state):
            return dict(state, _id="root")

        async def edit_initial_response(**kwargs):
            captured.append(kwargs)

        ctx = _Context()
        ctx.interaction.edit_initial_response = edit_initial_response
        monkeypatch.setattr(content, "new_draft", draft_for)
        command = content.ContentDashboard()
        command.message_link = "https://discord.com/channels/21/30/40"
        await command.invoke(ctx, mongo=SimpleNamespace(), bot=SimpleNamespace(rest=SimpleNamespace()))

        assert ctx.events == [("defer", {"ephemeral": True})]
        assert "Paste a message link from this server." in captured[0]["components"][0].components[1].content

    _run(check())


def test_save_and_publish_navigate_with_dispatcher_edits_not_followups(monkeypatch):
    async def check():
        document = content.DOCUMENTS["about-us"]
        sections = [node.content for node in content.text_nodes(await content.baseline(document))]
        saved_state = {
            "_id": "save", "user_id": 10, "guild_id": 20,
            "view": "document", "document": document.key,
            "sections": sections, "revision": 0,
        }
        mongo = SimpleNamespace(bot_config=_ConfigCollection())

        async def saved_state_for(_mongo, _sid):
            return saved_state

        async def next_draft(_mongo, value):
            return dict(value, _id="next")

        monkeypatch.setattr(content, "get_state", saved_state_for)
        monkeypatch.setattr(content, "new_draft", next_draft)
        _dispatch_content_action(monkeypatch, "content_save", content.save.__wrapped__._func, mongo)
        save = _PanelContext("content_save:save")
        await components._dispatch(save, mongo=mongo)
        assert save.events[0] == ("defer", True)
        assert len(save.events) == 2 and save.events[-1][2]["edit"] is True
        assert "Template saved for future posts in this server." in save.events[-1][2]["components"][0].components[2].content
        assert save.interaction.app.rest.edit_message.await_count == 0

        models = _as_discord_models(await content.baseline(document))
        linked_state = dict(
            saved_state, _id="publish", revision=1,
            target={"channel_id": 30, "message_id": 40, "original": sections},
        )

        async def linked_state_for(_mongo, _sid):
            return linked_state

        monkeypatch.setattr(content, "get_state", linked_state_for)
        public_edit = AsyncMock()
        bot = SimpleNamespace(rest=SimpleNamespace(
            fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=20)),
            fetch_message=AsyncMock(return_value=SimpleNamespace(
                author=SimpleNamespace(id=999), components=models
            )),
            edit_message=public_edit,
        ))
        action = components.registered_functions["content_publish"]

        async def publish_with_explicit_di(**kwargs):
            return await content.publish.__wrapped__._func(mongo=mongo, bot=bot, **kwargs)

        monkeypatch.setitem(components.registered_functions, "content_publish", dataclasses.replace(action, fn=publish_with_explicit_di))
        publish = _PanelContext("content_publish:publish")
        await components._dispatch(publish, mongo=mongo)
        assert publish.events[0] == ("defer", True)
        assert len(publish.events) == 2 and publish.events[-1][2]["edit"] is True
        assert public_edit.await_count == 1
        assert publish.interaction.app.rest.edit_message.await_count == 0

    _run(check())

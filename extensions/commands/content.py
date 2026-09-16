"""Private, schema-driven editor for published Warriors United content."""

import copy
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

import hikari
import lightbulb
from pymongo.errors import DuplicateKeyError

from extensions.components import register_action
from utils.component_state import get_state, insert_state, utcnow
from utils.mongo import MongoClient


loader = lightbulb.Loader()
content = lightbulb.Group("content", "Manage published server content")
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
MESSAGE_LINK = re.compile(r"<?https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)/?>?")


@dataclass(frozen=True)
class Document:
    key: str
    label: str
    acknowledgement: str
    legacy_key: str | None = None


DOCUMENTS = {
    "about-us": Document("about-us", "About Us", "aboutus_acknowledge", "recruit_aboutus"),
    "strike-system": Document("strike-system", "WU Strike System", "strikesystem_acknowledge"),
    "family-particulars": Document("family-particulars", "Family Particulars", "familyparticulars_acknowledge"),
}
BLOCK_LABELS = {
    "about-us": ("Welcome heading", "Welcome overview", "Tactical heading", "Tactical details", "Flexible Fun heading", "Flexible Fun details", "FWA heading", "FWA details", "Disclaimer heading", "Disclaimer", "Next step heading", "Next step"),
    "strike-system": ("Basic rules heading", "Basic rules", "Strike overview heading", "Strike overview", "Main clan heading", "Main clan note", "FWA heading", "FWA note", "Terms heading", "Terms", "Acknowledgement heading", "Acknowledgement"),
    "family-particulars": ("Family heading", "Golden rule heading", "Golden rule", "Friendly challenges heading", "Friendly challenges", "Clan games heading", "Clan games", "War rules heading", "War eligibility heading", "War eligibility", "Prep day heading", "Prep day", "Battle day heading", "Battle day", "CWL heading", "CWL overview", "CWL principles heading", "CWL principles", "Acknowledgement heading", "Acknowledgement"),
}
_baselines: dict[str, list] = {}


def can_edit(ctx):
    member = getattr(ctx.interaction, "member", None)
    permissions = getattr(member, "permissions", hikari.Permissions.NONE)
    return ctx.interaction.guild_id is not None and bool(
        permissions & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD)
    )


async def require_editor(ctx, state=None):
    if not can_edit(ctx):
        await ctx.respond("You need Manage Server permission to edit published content.", ephemeral=True)
        return False
    if state and (state["user_id"] != int(ctx.user.id) or state["guild_id"] != int(ctx.interaction.guild_id)):
        await ctx.respond("Open your own `/content dashboard`.", ephemeral=True)
        return False
    return True


def text_nodes(components):
    return [child for component in components for child in getattr(component, "components", ())
            if getattr(child, "type", None) == hikari.ComponentType.TEXT_DISPLAY]


def component_count(items):
    return sum(1 + component_count(getattr(item, "components", ())) for item in items)


def component_shape(items):
    return tuple((int(item.type), component_shape(getattr(item, "components", ()))) for item in items)


async def baseline(document: Document):
    if document.key in _baselines:
        return copy.deepcopy(_baselines[document.key])
    from extensions.commands.setup import recruit_aboutus, recruit_familyparticulars, recruit_strikesystem
    build = {
        "about-us": recruit_aboutus.build_aboutus,
        "strike-system": recruit_strikesystem.build_strikesystem,
        "family-particulars": recruit_familyparticulars.build_familyparticulars,
    }[document.key]
    _baselines[document.key] = build()
    return copy.deepcopy(_baselines[document.key])


async def render(document: Document, sections, *, action_id="preview", preview=False):
    components = await baseline(document)
    if component_count(components) > 40:
        raise ValueError("This document exceeds Discord's 40-component message limit.")
    nodes = text_nodes(components)
    if len(sections) != len(nodes) or any(not isinstance(value, str) or not value.strip() for value in sections):
        raise ValueError("This saved content is incomplete. Reopen the dashboard and correct every block.")
    if sum(map(len, sections)) > 4000:
        raise ValueError("This document must fit Discord's 4,000-character total.")
    values = iter(sections)
    for position, component in enumerate(components):
        if isinstance(component, hikari.impl.ContainerComponentBuilder):
            children = [hikari.impl.TextDisplayComponentBuilder(content=next(values)) if isinstance(child, hikari.impl.TextDisplayComponentBuilder) else child for child in component.components]
            components[position] = hikari.impl.ContainerComponentBuilder(accent_color=component.accent_color, components=children)
    for component in components:
        for child in getattr(component, "components", ()):
            if isinstance(child, hikari.impl.MessageActionRowBuilder):
                for button in child.components:
                    if getattr(button, "custom_id", "").startswith(document.acknowledgement + ":"):
                        button.set_custom_id(f"{document.acknowledgement}:{action_id}")
                        if preview:
                            button.set_is_disabled(True)
    return components


async def sections_for(mongo, document, guild_id):
    saved = await mongo.bot_config.find_one({"_id": f"content:{document.key}:{guild_id}"})
    if saved and isinstance(saved.get("sections"), list):
        try:
            await render(document, saved["sections"])
            return list(saved["sections"]), int(saved.get("revision", 0))
        except ValueError:
            pass
    if document.legacy_key:
        legacy = await mongo.bot_config.find_one({"_id": f"{document.legacy_key}:{guild_id}"})
        if legacy and isinstance(legacy.get("sections"), list):
            try:
                await render(document, legacy["sections"])
                # Migration writes a new content key, so legacy revision cannot
                # participate in that key's compare-and-swap predicate.
                return list(legacy["sections"]), 0
            except ValueError:
                pass
    components = await baseline(document)
    return [node.content for node in text_nodes(components)], 0


def editable_blocks(document, sections):
    labels = BLOCK_LABELS[document.key]
    # Decorative text displays in Family Particulars are retained verbatim,
    # never offered as edit fields, and still count toward the rendered limit.
    fixed = {3, 6, 9, 13, 16, 19, 22, 25} if document.key == "family-particulars" else set()
    indexes = [index for index in range(len(sections)) if index not in fixed]
    return tuple(zip(indexes, labels, strict=True))


def acknowledgement_id(components, document):
    for component in components:
        for child in getattr(component, "components", ()):
            for button in getattr(child, "components", ()):
                custom_id = getattr(button, "custom_id", "") or ""
                if custom_id.startswith(document.acknowledgement + ":"):
                    return custom_id.partition(":")[2]
    return None


async def new_draft(mongo, state):
    state = {key: value for key, value in state.items() if key not in {"_id", "created_at", "expires_at", "component_state"}}
    state["_id"] = uuid.uuid4().hex
    await insert_state(mongo, state, ttl=timedelta(minutes=30))
    return state


def panel(state, notice=None):
    sid = state["_id"]
    notice = notice or state.get("notice")
    if state.get("view") == "root" or not state.get("document"):
        choose = hikari.impl.MessageActionRowBuilder()
        menu = choose.add_text_menu(f"content_document:{sid}", min_values=1, placeholder="Choose content to edit")
        for document in DOCUMENTS.values():
            menu.add_option(document.label, document.key)
        rows = [
            hikari.impl.TextDisplayComponentBuilder(
                content="## :shield: Warriors United Content Dashboard\nChoose the published document to edit. Drafts preserve Markdown, media, separators, and acknowledgement buttons."
            ),
        ]
        if notice:
            rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
        rows.append(choose)
        return [hikari.impl.ContainerComponentBuilder(accent_color=0xEEEEAA, components=rows)]

    document = DOCUMENTS[state["document"]]
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=f"## {document.label}"),
        hikari.impl.TextDisplayComponentBuilder(
            content=f"{sum(map(len, state['sections']))}/4,000 characters · draft expires in 30 minutes."
        ),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    blocks = hikari.impl.MessageActionRowBuilder()
    menu = blocks.add_text_menu(f"content_block:{sid}", min_values=1, placeholder="Choose a block to edit")
    for index, label in editable_blocks(document, state["sections"]):
        menu.add_option(label, str(index))
    buttons = hikari.impl.MessageActionRowBuilder()
    buttons.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"content_preview:{sid}", label="Preview")
    buttons.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"content_save:{sid}", label="Save template")
    if state.get("target"):
        buttons.add_interactive_button(hikari.ButtonStyle.SUCCESS, f"content_publish:{sid}", label="Update selected post")
    buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_root:{sid}", label="Back")
    return [hikari.impl.ContainerComponentBuilder(accent_color=0xEEEEAA, components=rows + [blocks, buttons])]


def error_panel(message):
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=0xAA4444,
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"## Content Dashboard\n{message}")],
    )]


async def preview_panel(state):
    """Keep the post layout intact while turning its inert CTA into Back."""
    document = DOCUMENTS[state["document"]]
    components = await render(document, state["sections"], preview=True)
    for component in components:
        for child in getattr(component, "components", ()):
            if isinstance(child, hikari.impl.MessageActionRowBuilder):
                for button in child.components:
                    if getattr(button, "custom_id", "").startswith(document.acknowledgement + ":"):
                        # Family Particulars already reaches Discord's 40-component
                        # ceiling. Reusing this preview-only, disabled CTA slot keeps
                        # all text/media/separators visible and makes Back available.
                        button.set_custom_id(f"content_back_document:{state['_id']}")
                        button.set_label("Back to editor")
                        button.set_emoji("↩️")
                        button.set_is_disabled(False)
                        return components
    raise ValueError("This preview is missing its acknowledgement control.")


def state_problem(ctx, state):
    if not state:
        return "This draft expired. Run `/content dashboard` again."
    if not can_edit(ctx):
        return "You need Manage Server permission to edit published content."
    if state.get("user_id") != int(ctx.user.id) or state.get("guild_id") != int(ctx.interaction.guild_id):
        return "Open your own `/content dashboard`."
    return None


async def edit_modal_source(ctx, components):
    """Acknowledge a modal by replacing its source panel, never following up."""
    interaction = ctx.interaction
    if getattr(interaction, "message", None) is not None:
        await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)
    await interaction.edit_initial_response(components=components, **NO_MENTIONS)


async def initial_panel(ctx, mongo, state, notice=None):
    draft = await new_draft(mongo, state)
    await ctx.interaction.edit_initial_response(components=panel(draft, notice), **NO_MENTIONS)
    return draft


async def load(ctx, mongo, sid):
    state = await get_state(mongo, sid)
    return state, state_problem(ctx, state)


@content.register()
class ContentDashboard(lightbulb.SlashCommand, name="dashboard", description="Edit published server content"):
    message_link = lightbulb.string("message-link", "Optional existing content message link", default=None)
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED):
        if not await require_editor(ctx): return
        await ctx.defer(ephemeral=True)
        state = {"user_id": int(ctx.user.id), "guild_id": int(ctx.interaction.guild_id), "view": "root"}
        if self.message_link:
            match = MESSAGE_LINK.fullmatch(self.message_link.strip())
            if not match or int(match[1]) != state["guild_id"]:
                await initial_panel(ctx, mongo, state, "Paste a message link from this server."); return
            try:
                channel = await bot.rest.fetch_channel(int(match[2]))
                if int(getattr(channel, "guild_id", 0)) != state["guild_id"]:
                    raise ValueError("Paste a message link from this server.")
                message = await bot.rest.fetch_message(int(match[2]), int(match[3]))
            except (ValueError, hikari.NotFoundError, hikari.ForbiddenError) as exc:
                await initial_panel(ctx, mongo, state, str(exc) if isinstance(exc, ValueError) else "The bot cannot read that message."); return
            document = next((item for item in DOCUMENTS.values() if int(message.author.id) == int(ctx.interaction.application_id) and acknowledgement_id(message.components, item)), None)
            if not document:
                await initial_panel(ctx, mongo, state, "Choose a supported post created by this bot."); return
            sections = [node.content for node in text_nodes(message.components)]
            try:
                if component_shape(message.components) != component_shape(await baseline(document)):
                    raise ValueError("That post's layout is not a supported content document.")
                await render(document, sections)
            except ValueError:
                await initial_panel(ctx, mongo, state, "That post's structure is not a supported content document."); return
            _template, revision = await sections_for(mongo, document, state["guild_id"])
            state.update(view="document", document=document.key, sections=sections, revision=revision, target={"channel_id": int(match[2]), "message_id": int(match[3]), "original": sections})
        await initial_panel(ctx, mongo, state)


@register_action("content_document", preload_state=False)
@lightbulb.di.with_di
async def choose_document(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    value = getattr(ctx.interaction, "values", ())
    if len(value) != 1 or value[0] not in DOCUMENTS:
        return panel(state, "Choose one supported document.")
    document = DOCUMENTS[value[0]]; sections, revision = await sections_for(mongo, document, state["guild_id"])
    target = state.get("target") if state.get("document") == document.key else None
    return panel(await new_draft(mongo, dict(state, view="document", document=document.key, sections=sections, revision=revision, target=target)))


@register_action("content_back_root", preload_state=False)
@lightbulb.di.with_di
async def back_to_root(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    return panel(await new_draft(mongo, dict(state, view="root")))


@register_action("content_back_document", preload_state=False)
@lightbulb.di.with_di
async def back_to_document(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    return panel(state)


@register_action("content_block", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def choose_block(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id); values = getattr(ctx.interaction, "values", ())
    if problem:
        await edit_modal_source(ctx, error_panel(problem)); return
    if len(values) != 1 or not values[0].isdigit() or int(values[0]) >= len(state["sections"]):
        await edit_modal_source(ctx, panel(state, "Choose one editable block.")); return
    index = int(values[0]); document = DOCUMENTS[state["document"]]
    choices = dict(editable_blocks(document, state["sections"]))
    if index not in choices:
        await edit_modal_source(ctx, panel(state, "Choose one editable block.")); return
    title = choices[index]
    draft = await new_draft(mongo, dict(state, selected_block=index))
    await ctx.respond_with_modal(title=title[:45], custom_id=f"content_submit:{draft['_id']}", components=[hikari.impl.ModalActionRowBuilder().add_text_input("content", "Markdown", value=state["sections"][index], required=True, min_length=1, max_length=4000, style=hikari.TextInputStyle.PARAGRAPH)])


@register_action("content_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_block(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    interaction = ctx.interaction
    if getattr(interaction, "message", None) is not None:
        await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        await interaction.edit_initial_response(components=error_panel(problem), **NO_MENTIONS); return
    if not isinstance(state.get("selected_block"), int):
        await interaction.edit_initial_response(components=panel(state, "Choose a block before submitting an edit."), **NO_MENTIONS); return
    value = next((str(item.value) for row in ctx.interaction.components for item in row if item.custom_id == "content"), "")
    sections = list(state["sections"]); sections[state["selected_block"]] = value
    try: await render(DOCUMENTS[state["document"]], sections)
    except ValueError as exc:
        await interaction.edit_initial_response(components=panel(state, str(exc)), **NO_MENTIONS); return
    await interaction.edit_initial_response(components=panel(await new_draft(mongo, dict(state, sections=sections)), "Block updated."), **NO_MENTIONS)


async def _save(ctx, state, mongo):
    key = f"content:{state['document']}:{state['guild_id']}"; revision = state["revision"]
    update = {"sections": state["sections"], "revision": revision + 1, "updated_by": int(ctx.user.id), "updated_at": utcnow()}
    try:
        if revision == 0: await mongo.bot_config.insert_one(dict(update, _id=key)); return True
        return (await mongo.bot_config.update_one({"_id": key, "revision": revision}, {"$set": update})).matched_count == 1
    except DuplicateKeyError: return False


@register_action("content_save", preload_state=False)
@lightbulb.di.with_di
async def save(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if not state.get("document"):
        return panel(state, "Choose a document before saving.")
    if not await _save(ctx, state, mongo):
        return panel(state, "The template changed. Reopen the dashboard to avoid overwriting it.")
    return panel(await new_draft(mongo, dict(state, revision=state["revision"] + 1)), "Template saved for future posts in this server.")


@register_action("content_preview", preload_state=False)
@lightbulb.di.with_di
async def preview(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if not state.get("document"):
        return panel(state, "Choose a document before previewing.")
    try:
        return await preview_panel(state)
    except ValueError as exc:
        return panel(state, str(exc))


@register_action("content_publish", preload_state=False)
@lightbulb.di.with_di
async def publish(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if not state.get("target") or not state.get("document"):
        return panel(state, "Choose a linked post before updating it.")
    target = state["target"]; document = DOCUMENTS[state["document"]]; token = uuid.uuid4().hex
    lease_key = f"content_publish:{target['channel_id']}:{target['message_id']}"
    try:
        await mongo.bot_config.update_one({"_id": lease_key, "until": {"$lte": utcnow()}}, {"$set": {"until": utcnow() + timedelta(minutes=1), "token": token}}, upsert=True)
    except DuplicateKeyError:
        return panel(state, "Another update is in progress. Try again shortly.")
    try:
        channel = await bot.rest.fetch_channel(target["channel_id"])
        if int(getattr(channel, "guild_id", 0)) != state["guild_id"]: raise ValueError("The selected post is not in this server.")
        message = await bot.rest.fetch_message(target["channel_id"], target["message_id"])
        if int(message.author.id) != int(ctx.interaction.application_id) or [node.content for node in text_nodes(message.components)] != target["original"]:
            raise ValueError("That post changed since this draft opened. Reopen the dashboard to review it.")
        acknowledgement = acknowledgement_id(message.components, document)
        if not acknowledgement: raise ValueError("That is not the selected content type.")
        await bot.rest.edit_message(target["channel_id"], target["message_id"], components=await render(document, state["sections"], action_id=acknowledgement), **NO_MENTIONS)
    except (ValueError, hikari.NotFoundError, hikari.ForbiddenError) as exc:
        return panel(state, str(exc) if isinstance(exc, ValueError) else "The bot cannot update that message. Your draft is still available.")
    finally:
        await mongo.bot_config.delete_one({"_id": lease_key, "token": token})
    return panel(
        await new_draft(mongo, dict(state, target=dict(target, original=state["sections"]))),
        "Selected post updated.",
    )


loader.command(content)

"""Private, schema-driven editor for published Warriors United content."""

import asyncio
import copy
import re
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import hikari
import lightbulb
from pymongo.errors import DuplicateKeyError

from extensions.components import register_action
from utils.component_state import get_state, insert_state, utcnow
from utils.discord_file_upload import (
    FileUploadModalComponentBuilder,
    install_file_upload_capture,
    pop_file_upload,
)
from utils.media_store import MediaStore, MediaStoreError, recruit_content_folder
from utils.mongo import MongoClient
from utils.constants import GOLDENROD_ACCENT
from utils.url_safety import MAX_IMAGE_BYTES
from utils.recruit_setup_checks import require_ready
from utils.manage_ui import breadcrumb, button_emoji


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
    "join-family": Document("join-family", "Join the Family", "join_family_acknowledge"),
    "about-us": Document("about-us", "About Us", "aboutus_acknowledge", "recruit_aboutus"),
    "strike-system": Document("strike-system", "WU Strike System", "strikesystem_acknowledge"),
    "family-particulars": Document("family-particulars", "Family Particulars", "familyparticulars_acknowledge"),
}
BLOCK_LABELS = {
    "join-family": ("Heading", "Welcome", "What happens next", "Call to action"),
    "about-us": ("Welcome heading", "Welcome overview", "Tactical heading", "Tactical details", "Flexible Fun heading", "Flexible Fun details", "FWA heading", "FWA details", "Disclaimer heading", "Disclaimer", "Next step heading", "Next step"),
    "strike-system": ("Basic rules heading", "Basic rules", "Strike overview heading", "Strike overview", "Main clan heading", "Main clan note", "FWA heading", "FWA note", "Terms heading", "Terms", "Acknowledgement heading", "Acknowledgement"),
    "family-particulars": ("Family heading", "Golden rule heading", "Golden rule", "Friendly challenges heading", "Friendly challenges", "Clan games heading", "Clan games", "War rules heading", "War eligibility heading", "War eligibility", "Prep day heading", "Prep day", "Battle day heading", "Battle day", "CWL heading", "CWL overview", "CWL principles heading", "CWL principles", "Acknowledgement heading", "Acknowledgement"),
}
MEDIA_SLOTS = {
    "join-family": (("welcome", "Welcome banner"),),
    "about-us": (("welcome", "Welcome banner"),),
    "strike-system": (
        ("rules", "Basic rules banner"),
        ("main-strikes", "Main clan strike chart"),
        ("fwa-strikes", "FWA strike chart"),
    ),
    "family-particulars": (("welcome", "Welcome banner"), ("cwl", "CWL banner")),
}
_baselines: dict[str, list] = {}
_DESTINATION_TYPES = frozenset((hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS))


def acknowledgement_setup(document_key: str) -> tuple[int, int]:
    # Pull from the live acknowledgement handlers; a posting destination does
    # not change their role assignments or fixed next-step channels.
    from extensions.commands.setup import (
        recruit_aboutus,
        recruit_strikesystem,
        recruit_familyparticulars,
        recruit_join_family,
    )
    return {
        "join-family": (recruit_join_family.JOIN_FAMILY_ROLE_ID, recruit_join_family.ABOUT_US_CHANNEL_ID),
        "about-us": (recruit_aboutus.ABOUT_US_ROLE_ID, recruit_aboutus.STRIKE_SYSTEM_CHANNEL_ID),
        "strike-system": (recruit_strikesystem.STRIKE_SYSTEM_ROLE_ID, recruit_strikesystem.FAMILY_PARTICULARS_CHANNEL_ID),
        "family-particulars": (recruit_familyparticulars.CLAN_RULES_READ_ROLE_ID, recruit_familyparticulars.APPLY_HERE_CHANNEL_ID),
    }[document_key]


# Hikari 2.6 predates Discord's modal Label/File Upload models. Install the
# narrow deserialization adapter before the gateway receives interactions.
install_file_upload_capture()


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
        await ctx.respond("Open your own Recruit Gauntlet editor from `/manage`.", ephemeral=True)
        return False
    return True


def text_nodes(components):
    return [child for component in components for child in getattr(component, "components", ())
            if getattr(child, "type", None) == hikari.ComponentType.TEXT_DISPLAY]


def component_count(items):
    return sum(1 + component_count(getattr(item, "components", ())) for item in items)


def component_shape(items):
    return tuple((int(item.type), component_shape(getattr(item, "components", ()))) for item in items)


def media_galleries(items):
    """Return galleries in their rendered order, including galleries in cards."""
    result = []
    for item in items:
        if getattr(item, "type", None) == hikari.ComponentType.MEDIA_GALLERY:
            result.append(item)
        result.extend(media_galleries(getattr(item, "components", ())))
    return result


def media_url(item):
    value = getattr(item, "media", None)
    url = getattr(value, "url", value)
    return str(url) if url is not None else ""


def canonical_media_url(value: str) -> str:
    """Ignore Discord's rotating attachment signatures, and nothing else."""
    parsed = urlparse(value)
    if (
        parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net", "cdn.discordapp.net"}
        and parsed.path.startswith("/attachments/")
    ):
        query = urlencode([
            (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key not in {"ex", "is", "hm"}
        ])
        return urlunparse(parsed._replace(query=query))
    return value


def discord_attachment_id(value: str) -> str | None:
    """The stable Discord attachment id behind a CDN or media-proxy URL."""
    parsed = urlparse(value)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net", "cdn.discordapp.net"}
        and len(parts) >= 4
        and parts[0] == "attachments"
        and parts[2].isdigit()
    ):
        return parts[2]
    return None


def media_snapshot(components):
    """The one image URL in each named gallery, in schema order."""
    values = []
    for gallery in media_galleries(components):
        items = getattr(gallery, "items", ())
        if len(items) != 1:
            raise ValueError("This post's media layout is not supported by the content dashboard.")
        value = canonical_media_url(media_url(items[0]))
        if not value:
            raise ValueError("This post has an empty media slot.")
        values.append(value)
    return values


def normal_media(document: Document, media):
    """Validate sparse saved overrides; omitted slots retain the native art."""
    if media is None:
        return {}
    if not isinstance(media, dict):
        raise ValueError("Saved image settings are invalid. Reopen the dashboard.")
    names = {name for name, _label in MEDIA_SLOTS[document.key]}
    if set(media) - names or any(
        not isinstance(url, str) or urlparse(url).scheme != "https" or not urlparse(url).netloc
        for url in media.values()
    ):
        raise ValueError("Saved image settings are invalid. Reopen the dashboard.")
    return {name: url.strip() for name, url in media.items()}


def media_slots(document: Document):
    return MEDIA_SLOTS[document.key]


async def baseline(document: Document):
    if document.key in _baselines:
        return copy.deepcopy(_baselines[document.key])
    from extensions.commands.setup import recruit_aboutus, recruit_familyparticulars, recruit_strikesystem, recruit_join_family
    build = {
        "join-family": recruit_join_family.build_join_family,
        "about-us": recruit_aboutus.build_aboutus,
        "strike-system": recruit_strikesystem.build_strikesystem,
        "family-particulars": recruit_familyparticulars.build_familyparticulars,
    }[document.key]
    _baselines[document.key] = build()
    return copy.deepcopy(_baselines[document.key])


def document_renderer(document: Document):
    from extensions.commands.setup import recruit_aboutus, recruit_familyparticulars, recruit_strikesystem, recruit_join_family
    return {
        "join-family": recruit_join_family.build_join_family,
        "about-us": recruit_aboutus.build_aboutus,
        "strike-system": recruit_strikesystem.build_strikesystem,
        "family-particulars": recruit_familyparticulars.build_familyparticulars,
    }[document.key]


async def render(document: Document, sections, *, media=None, action_id="preview", preview=False):
    baseline_components = await baseline(document)
    if component_count(baseline_components) > 40:
        raise ValueError("This document exceeds Discord's 40-component message limit.")
    nodes = text_nodes(baseline_components)
    if len(sections) != len(nodes) or any(not isinstance(value, str) or not value.strip() for value in sections):
        raise ValueError("This saved content is incomplete. Reopen the dashboard and correct every block.")
    if sum(map(len, sections)) > 4000:
        raise ValueError("This document exceeds the editor's 4,000-character total.")
    overrides = normal_media(document, media)
    components = document_renderer(document)(
        sections, media=overrides, action_id=action_id, preview=preview
    )
    galleries = media_galleries(components)
    if len(galleries) != len(media_slots(document)):
        raise ValueError("This document's media layout is not supported by the content dashboard.")
    return components


async def template_for(mongo, document: Document, guild_id: int):
    """Read text, image overrides, and revision from the same stored version."""
    saved = await mongo.bot_config.find_one({"_id": f"content:{document.key}:{guild_id}"})
    if saved and isinstance(saved.get("sections"), list):
        try:
            media = normal_media(document, saved.get("media"))
            await render(document, saved["sections"], media=media)
            return list(saved["sections"]), media, int(saved.get("revision", 0))
        except ValueError:
            pass
    if document.legacy_key:
        legacy = await mongo.bot_config.find_one({"_id": f"{document.legacy_key}:{guild_id}"})
        if legacy and isinstance(legacy.get("sections"), list):
            try:
                await render(document, legacy["sections"])
                # Migration writes a new content key, so legacy revision cannot
                # participate in that key's compare-and-swap predicate.
                return list(legacy["sections"]), {}, 0
            except ValueError:
                pass
    components = await baseline(document)
    return [node.content for node in text_nodes(components)], {}, 0


async def sections_for(mongo, document, guild_id):
    """Compatibility wrapper for setup and older callers that need only text."""
    sections, _media, revision = await template_for(mongo, document, guild_id)
    return sections, revision


async def saved_media_for(mongo, document: Document, guild_id: int):
    """Return valid saved overrides without allowing a bad row to break setup."""
    _sections, media, _revision = await template_for(mongo, document, guild_id)
    return media


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


def destination_key(guild_id: int, document_key: str) -> str:
    if document_key not in DOCUMENTS or int(guild_id) <= 0:
        raise ValueError("Choose a Recruit Gauntlet document in this server.")
    return f"content_destination:{int(guild_id)}:{document_key}"


async def destination_for(mongo, guild_id: int, document_key: str) -> int | None:
    row = await mongo.bot_config.find_one({"_id": destination_key(guild_id, document_key)})
    if row is None:
        return None
    try:
        channel_id = int(row["channel_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if row.get("guild_id") != int(guild_id) or row.get("document") != document_key or channel_id <= 0:
        return None
    return channel_id


def _apply_overwrite(base: hikari.Permissions, overwrite) -> hikari.Permissions:
    return hikari.Permissions(
        (int(base) & ~int(getattr(overwrite, "deny", 0)))
        | int(getattr(overwrite, "allow", 0))
    )


async def destination_permissions(bot, guild_id: int, channel) -> hikari.Permissions:
    """Resolve the bot's permissions in the selected channel, including overwrites."""
    roles = tuple(await bot.rest.fetch_roles(guild_id))
    member = await bot.rest.fetch_my_member(guild_id)
    role_ids = {int(value) for value in getattr(member, "role_ids", ())}
    role_ids.add(guild_id)
    roles_by_id = {int(role.id): role for role in roles}
    if guild_id not in roles_by_id:
        raise ValueError("I cannot verify my permissions in that channel.")
    base = hikari.Permissions.NONE
    for role_id in role_ids:
        role = roles_by_id.get(role_id)
        if role is not None:
            base |= hikari.Permissions(getattr(role, "permissions", 0))
    if base & hikari.Permissions.ADMINISTRATOR:
        return base
    overwrites = getattr(channel, "permission_overwrites", None)
    if overwrites is None:
        raise ValueError("I cannot verify my permissions in that channel.")
    by_id = {int(key): value for key, value in overwrites.items()}
    everyone = by_id.get(guild_id)
    if everyone is not None:
        base = _apply_overwrite(base, everyone)
    role_overwrites = [by_id[role_id] for role_id in role_ids - {guild_id} if role_id in by_id]
    if role_overwrites:
        denied = 0
        allowed = 0
        for overwrite in role_overwrites:
            denied |= int(getattr(overwrite, "deny", 0))
            allowed |= int(getattr(overwrite, "allow", 0))
        base = hikari.Permissions((int(base) & ~denied) | allowed)
    member_id = getattr(member, "id", None) or getattr(getattr(member, "user", None), "id", None)
    if member_id is None:
        raise ValueError("I cannot verify my permissions in that channel.")
    personal = by_id.get(int(member_id))
    if personal is not None:
        base = _apply_overwrite(base, personal)
    return base


async def _ready_for_destination(ctx, bot, channel, permissions, document_key: str) -> tuple[bool, str | None]:
    """Run the existing role and next-channel check against destination permissions."""
    messages = []
    async def capture(message, **_):
        messages.append(message)
    proxy = SimpleNamespace(
        interaction=SimpleNamespace(
            guild_id=ctx.interaction.guild_id,
            channel=channel,
            app_permissions=permissions,
            member=ctx.interaction.member,
        ),
        respond=capture,
    )
    role_id, next_channel_id = acknowledgement_setup(document_key)
    ready = await require_ready(proxy, bot, role_id=role_id, next_channel_id=next_channel_id)
    return ready, messages[0] if messages else None


def draft_snapshot(state):
    """Snapshot only template fields, excluding immediately saved channel settings."""
    document = DOCUMENTS[state["document"]]
    media = normal_media(document, state.get("media"))
    return {
        "sections": copy.deepcopy(state["sections"]),
        "media": {slot: canonical_media_url(url) for slot, url in media.items()},
    }


def has_unsaved_edits(state):
    saved = state.get("saved_snapshot")
    if not isinstance(saved, dict) or set(saved) != {"sections", "media"}:
        # Older live panels did not record their starting version. Warn rather
        # than silently discarding a draft whose origin cannot be proved.
        return True
    try:
        return draft_snapshot(state) != saved
    except (KeyError, ValueError, TypeError):
        return True


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
            hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet")),
            hikari.impl.TextDisplayComponentBuilder(
                content=("## Recruit Gauntlet\nManage onboarding content." if state.get("manage_token") else "## :shield: Warriors United Content Dashboard\nChoose an onboarding document to edit.")
            ),
        ]
        if notice:
            rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
        rows.append(choose)
        if state.get("manage_token"):
            home = hikari.impl.MessageActionRowBuilder()
            home.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"manage_home:{state['manage_token']}", label="Management Home", emoji=button_emoji("Management Home"))
            rows.append(home)
        return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]

    document = DOCUMENTS[state["document"]]
    overrides = normal_media(document, state.get("media"))
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", document.label)),
        hikari.impl.TextDisplayComponentBuilder(content=f"## {document.label}"),
        hikari.impl.TextDisplayComponentBuilder(
            content=f"{'Unsaved changes' if has_unsaved_edits(state) else 'Saved'} · {sum(map(len, state['sections']))}/4,000 characters · draft expires in 30 minutes."
        ),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    blocks = hikari.impl.MessageActionRowBuilder()
    menu = blocks.add_text_menu(f"content_block:{sid}", min_values=1, placeholder="Choose a block to edit")
    for index, label in editable_blocks(document, state["sections"]):
        menu.add_option(label, str(index))
    images = hikari.impl.MessageActionRowBuilder()
    selected_slot = state.get("selected_media_slot")
    image_menu = images.add_text_menu(
        f"content_media:{sid}", min_values=1, placeholder="Choose an image to edit"
    )
    for slot, label in media_slots(document):
        source = "custom image" if slot in overrides else "default image"
        image_menu.add_option(f"{label} ({source})", slot, is_default=slot == selected_slot)
    destination = state.get("destination_channel_id")
    destination_menu = hikari.impl.MessageActionRowBuilder()
    destination_menu.add_channel_menu(
        f"content_destination:{sid}",
        channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
        placeholder="Choose a posting channel", min_values=1, max_values=1,
    )
    destination_status = (
        f"Posting target: <#{destination}>. Send to channel posts this draft; Save template keeps it for future editing."
        if destination else
        "Posting target: No channel selected. Choose a channel below to send this draft; Save template keeps it for future editing."
    )
    send_buttons = hikari.impl.MessageActionRowBuilder()
    send_buttons.add_interactive_button(
        hikari.ButtonStyle.PRIMARY, f"content_send:{sid}", label="Send to channel", emoji=button_emoji("Send to channel"),
        is_disabled=not destination,
    )
    buttons = hikari.impl.MessageActionRowBuilder()
    buttons.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"content_preview:{sid}", label="Preview", emoji=button_emoji("Preview"))
    buttons.add_interactive_button(hikari.ButtonStyle.SUCCESS, f"content_save:{sid}", label="Save template", emoji=button_emoji("Save template"))
    if state.get("target"):
        buttons.add_interactive_button(hikari.ButtonStyle.SUCCESS, f"content_publish:{sid}", label="Update selected post", emoji=button_emoji("Update selected post"))
    selected_buttons = None
    if state.get("selected_media_slot"):
        selected_buttons = hikari.impl.MessageActionRowBuilder()
        selected_buttons.add_interactive_button(
            hikari.ButtonStyle.PRIMARY, f"content_upload:{sid}", label="Upload replacement", emoji=button_emoji("Upload replacement")
        )
        selected_buttons.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, f"content_reset_media:{sid}", label="Restore default image", emoji=button_emoji("Restore default image"),
            is_disabled=selected_slot not in overrides,
        )
    footer = hikari.impl.MessageActionRowBuilder()
    footer.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_root:{sid}", label="Back to Recruit Gauntlet", emoji=button_emoji("Back to Recruit Gauntlet"))
    if state.get("manage_token"):
        footer.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_manage_review:{sid}", label="Management Home", emoji=button_emoji("Management Home"))
    target = state.get("target")
    if target:
        target_url = f"https://discord.com/channels/{state['guild_id']}/{target['channel_id']}/{target['message_id']}"
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"Selected post to update: [View post]({target_url}) in <#{target['channel_id']}>."))
    controls = [
        blocks, images,
        hikari.impl.SeparatorComponentBuilder(divider=True),
        hikari.impl.TextDisplayComponentBuilder(content=destination_status),
        destination_menu, send_buttons,
    ]
    slots = dict(media_slots(document))
    if selected_slot in slots:
        # Use the public renderer's exact slot/default resolution so linked,
        # saved, newly uploaded, and reset images all match the current draft.
        galleries = media_galleries(document_renderer(document)(media=overrides, preview=True))
        gallery = galleries[list(slots).index(selected_slot)]
        controls.extend([
            hikari.impl.TextDisplayComponentBuilder(
                content=f"### {slots[selected_slot]}\n-# Current image in this draft"
            ),
            gallery,
            hikari.impl.TextDisplayComponentBuilder(
                content="-# Restore default image brings back the original artwork. Use Save template to keep your changes."
            ),
        ])
    controls.append(buttons)
    if selected_buttons is not None:
        controls.append(selected_buttons)
    controls.extend([hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL), footer])
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows + controls)]


def error_panel(message):
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=0xAA4444,
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"## Content Dashboard\n{message}")],
    )]


async def preview_panel(state):
    """Keep the post layout intact while turning its inert CTA into Back."""
    document = DOCUMENTS[state["document"]]
    components = await render(document, state["sections"], media=state.get("media"), preview=True)
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
                        button.set_emoji(button_emoji("Back to editor"))
                        button.set_is_disabled(False)
                        return components
    raise ValueError("This preview is missing its acknowledgement control.")


def state_problem(ctx, state):
    if not state:
        return "This draft expired. Run `/manage` and choose Recruit Gauntlet again."
    if not can_edit(ctx):
        return "You need Manage Server permission to edit published content."
    if state.get("user_id") != int(ctx.user.id) or state.get("guild_id") != int(ctx.interaction.guild_id):
        return "Open your own Recruit Gauntlet editor from `/manage`."
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


class ContentDashboard(lightbulb.SlashCommand, name="dashboard", description="Edit published server content"):
    message_link = lightbulb.string("message-link", "Optional existing content message link", default=None)
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED):
        await open_dashboard(ctx, mongo, bot=bot, message_link=self.message_link)


async def open_dashboard(ctx, mongo: MongoClient, *, bot: hikari.GatewayBot | None = None,
                         message_link: str | None = None, manage_token: str | None = None, deferred: bool = False):
        if not await require_editor(ctx): return
        if not deferred and not getattr(ctx.interaction, "custom_id", None):
            await ctx.defer(ephemeral=True)
        state = {"user_id": int(ctx.user.id), "guild_id": int(ctx.interaction.guild_id), "view": "root"}
        if manage_token:
            state["manage_token"] = manage_token
        if message_link:
            match = MESSAGE_LINK.fullmatch(message_link.strip())
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
                original_media = media_snapshot(message.components)
                if len(original_media) != len(media_slots(document)):
                    raise ValueError("That post's media layout is not supported by the content dashboard.")
                await render(document, sections)
            except ValueError:
                await initial_panel(ctx, mongo, state, "That post's structure is not a supported content document."); return
            _template, _media, revision = await template_for(mongo, document, state["guild_id"])
            state.update(
                view="document", document=document.key, sections=sections, revision=revision,
                media=dict(zip((slot for slot, _label in media_slots(document)), original_media, strict=True)),
                target={
                    "channel_id": int(match[2]), "message_id": int(match[3]),
                    "original": sections, "original_media": original_media,
                },
                destination_channel_id=await destination_for(mongo, state["guild_id"], document.key),
            )
            state["saved_snapshot"] = draft_snapshot(state)
        await initial_panel(ctx, mongo, state)


@register_action("content_manage_review", preload_state=False)
@lightbulb.di.with_di
async def manage_review(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    token = state.get("manage_token")
    if not token:
        return panel(state)
    if not has_unsaved_edits(state):
        from extensions.commands.manage import home
        return await home(ctx=ctx, action_id=token, mongo=mongo)
    buttons = hikari.impl.MessageActionRowBuilder()
    buttons.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"content_back_document:{state['_id']}", label="Keep editing", emoji=button_emoji("Keep editing"))
    buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"manage_home:{token}", label="Leave without saving", emoji=button_emoji("Leave without saving"))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", DOCUMENTS[state["document"]].label)),
        hikari.impl.TextDisplayComponentBuilder(content="## Leave content editor?"),
        hikari.impl.TextDisplayComponentBuilder(content="Reopening Recruit Gauntlet starts a new draft. Unsaved edits in this draft will not be restored. Save the template before leaving if you want to keep them."),
        buttons,
    ])]


@register_action("content_cwl", preload_state=False, no_return=True)
@lightbulb.di.with_di
async def open_cwl(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        await ctx.interaction.edit_initial_response(components=error_panel(problem), **NO_MENTIONS)
        return
    from extensions.commands.cwl_dashboard import open_dashboard
    await open_dashboard(ctx, mongo, manage_token=state.get("manage_token"))


@register_action("content_document", preload_state=False)
@lightbulb.di.with_di
async def choose_document(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    value = getattr(ctx.interaction, "values", ())
    if len(value) != 1 or value[0] not in DOCUMENTS:
        return panel(state, "Choose one supported document.")
    document = DOCUMENTS[value[0]]
    sections, media, revision = await template_for(mongo, document, state["guild_id"])
    destination_channel_id = await destination_for(mongo, state["guild_id"], document.key)
    target = state.get("target") if state.get("document") == document.key else None
    draft_state = dict(
        state, view="document", document=document.key, sections=sections,
        revision=revision, media=media, target=target,
        destination_channel_id=destination_channel_id, selected_media_slot=None,
    )
    draft_state["saved_snapshot"] = draft_snapshot(draft_state)
    return panel(await new_draft(mongo, draft_state))


@register_action("content_destination", preload_state=False)
@lightbulb.di.with_di
async def choose_destination(
    ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_,
):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    document_key = state.get("document")
    values = getattr(ctx.interaction, "values", ()) or ()
    if document_key not in DOCUMENTS or len(values) != 1:
        return panel(state, "Choose one text or announcement channel.")
    try:
        channel_id = int(values[0])
        if channel_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return panel(state, "Choose one text or announcement channel.")
    try:
        channel = await bot.rest.fetch_channel(channel_id)
    except (hikari.HTTPError, OSError):
        return panel(state, "I cannot read that channel. Choose another channel.")
    if (int(getattr(channel, "guild_id", 0)) != state["guild_id"]
            or getattr(channel, "type", None) not in _DESTINATION_TYPES):
        return panel(state, "Choose a text or announcement channel in this server.")
    await mongo.bot_config.update_one(
        {"_id": destination_key(state["guild_id"], document_key)},
        {"$set": {
            "guild_id": state["guild_id"], "document": document_key,
            "channel_id": channel_id, "updated_by": int(ctx.user.id),
            "updated_at": utcnow(),
        }},
        upsert=True,
    )
    draft = await new_draft(mongo, dict(state, destination_channel_id=channel_id))
    return panel(draft, f"Posting channel saved as <#{channel_id}> for {DOCUMENTS[document_key].label}.")


@register_action("content_send", preload_state=False)
@lightbulb.di.with_di
async def send_to_channel(
    ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_,
):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    document_key = state.get("document")
    channel_id = state.get("destination_channel_id")
    if document_key not in DOCUMENTS or not isinstance(channel_id, int) or channel_id <= 0:
        return panel(state, "Choose and save a posting channel before sending.")
    try:
        channel = await bot.rest.fetch_channel(channel_id)
    except (hikari.HTTPError, OSError):
        return panel(state, "I cannot read the selected posting channel. Your draft is unchanged.")
    if (int(getattr(channel, "guild_id", 0)) != state["guild_id"]
            or getattr(channel, "type", None) not in _DESTINATION_TYPES):
        return panel(state, "The selected posting channel must be a text or announcement channel in this server.")
    try:
        permissions = await destination_permissions(bot, state["guild_id"], channel)
    except (ValueError, hikari.HTTPError, OSError) as exc:
        return panel(state, str(exc) if isinstance(exc, ValueError) else "I cannot verify my permissions in that channel.")
    needed = (hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
              | hikari.Permissions.ATTACH_FILES)
    if not (permissions & hikari.Permissions.ADMINISTRATOR) and permissions & needed != needed:
        return panel(state, "I need View Channel, Send Messages, and Attach Files permissions in the selected channel.")
    ready, issue = await _ready_for_destination(ctx, bot, channel, permissions, document_key)
    if not ready:
        return panel(state, issue or "The acknowledgement role or next onboarding channel needs attention.")
    try:
        rendered = await render(
            DOCUMENTS[document_key], state["sections"], media=state.get("media"),
            action_id=uuid.uuid4().hex,
        )
    except ValueError as exc:
        return panel(state, str(exc))
    # One unique claim per editor token. It survives a process restart and
    # prevents two clicks on the same stale panel from posting twice.
    claim_key = f"content_send:{action_id}"
    try:
        await mongo.bot_config.insert_one({
            "_id": claim_key, "guild_id": state["guild_id"],
            "document": document_key, "channel_id": channel_id,
            "requested_by": int(ctx.user.id), "created_at": utcnow(),
        })
    except DuplicateKeyError:
        return panel(state, "This Send action was already used. Reopen the document to send another post.")
    try:
        message = await bot.rest.create_message(
            channel=channel_id, components=rendered, **NO_MENTIONS,
        )
    except (hikari.HTTPError, OSError):
        draft = await new_draft(mongo, state)
        return panel(draft, "I could not confirm the post. Check the channel before sending again; this draft is still available.")
    draft = await new_draft(mongo, state)
    link = f"https://discord.com/channels/{state['guild_id']}/{channel_id}/{message.id}"
    return panel(draft, f"Sent the current draft to <#{channel_id}>: [View posted message]({link}).")


@register_action("content_back_root", preload_state=False)
@lightbulb.di.with_di
async def back_to_root(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if state.get("manage_token") and state.get("document") and has_unsaved_edits(state):
        buttons = hikari.impl.MessageActionRowBuilder()
        buttons.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"content_back_document:{state['_id']}", label="Keep editing", emoji=button_emoji("Keep editing"))
        buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_root_confirm:{state['_id']}", label="Leave without saving", emoji=button_emoji("Leave without saving"))
        return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=[
            hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", DOCUMENTS[state["document"]].label)),
            hikari.impl.TextDisplayComponentBuilder(content="## Return to Recruit Gauntlet?"),
            hikari.impl.TextDisplayComponentBuilder(content="Reopening this document starts a new draft. Unsaved edits in this draft will not be restored. Save the template first if you want to keep them."),
            buttons,
        ])]
    return panel(await new_draft(mongo, dict(state, view="root")))


@register_action("content_back_root_confirm", preload_state=False)
@lightbulb.di.with_di
async def back_to_root_confirm(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
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


@register_action("content_media", preload_state=False)
@lightbulb.di.with_di
async def choose_media(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    values = getattr(ctx.interaction, "values", ())
    document = DOCUMENTS.get(state.get("document"))
    if not document or len(values) != 1 or values[0] not in {slot for slot, _label in media_slots(document)}:
        return panel(state, "Choose one image slot.")
    label = dict(media_slots(document))[values[0]]
    draft = await new_draft(mongo, dict(state, selected_media_slot=values[0]))
    return panel(
        draft,
        f"{label} selected. Upload a replacement or restore the original artwork.",
    )


@register_action("content_upload", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def open_upload_modal(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        await edit_modal_source(ctx, error_panel(problem)); return
    document = DOCUMENTS.get(state.get("document"))
    slot = state.get("selected_media_slot")
    if not document or slot not in {name for name, _label in media_slots(document)}:
        await edit_modal_source(ctx, panel(state, "Choose an image slot before uploading.")); return
    draft = await new_draft(mongo, state)
    await ctx.respond_with_modal(
        title="Upload replacement image",
        custom_id=f"content_upload_submit:{draft['_id']}",
        components=[FileUploadModalComponentBuilder(
            custom_id="image",
            label=dict(media_slots(document))[slot],
            description="PNG, JPG, GIF, or WEBP; maximum 10 MB",
        )],
    )


def _modal_attachment(payload):
    """Convert Discord's resolved attachment payload to Hikari's URL resource."""
    try:
        size = int(payload["size"])
        if size < 0:
            return None
        return hikari.Attachment(
            id=hikari.Snowflake(payload["id"]),
            filename=payload["filename"],
            title=payload.get("title"),
            description=payload.get("description"),
            media_type=payload.get("content_type"),
            size=size,
            url=payload["url"],
            proxy_url=payload.get("proxy_url", payload["url"]),
            height=payload.get("height"),
            width=payload.get("width"),
            is_ephemeral=payload.get("ephemeral", False),
            duration=payload.get("duration_secs"),
            waveform=payload.get("waveform"),
        )
    except (KeyError, TypeError, ValueError):
        return None


@register_action("content_upload_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_upload(
    ctx,
    action_id,
    mongo: MongoClient = lightbulb.di.INJECTED,
    media: MediaStore = lightbulb.di.INJECTED,
    **_,
):
    interaction = ctx.interaction
    # Consume the raw payload even when the draft is invalid, so it cannot be
    # reused and the compatibility cache cannot retain rejected submissions.
    payload = pop_file_upload(interaction.id, interaction.custom_id, "image")
    if getattr(interaction, "message", None) is not None:
        await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        # This should only occur for a forged/out-of-band modal submit. It still
        # gets a private response instead of failing the interaction silently.
        await ctx.defer(ephemeral=True)
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        await interaction.edit_initial_response(components=error_panel(problem), **NO_MENTIONS); return
    document = DOCUMENTS.get(state.get("document"))
    slot = state.get("selected_media_slot")
    if not document or slot not in {name for name, _label in media_slots(document)}:
        await interaction.edit_initial_response(
            components=panel(state, "Choose an image slot before uploading."), **NO_MENTIONS
        ); return
    attachment = _modal_attachment(payload) if payload is not None else None
    if attachment is None:
        await interaction.edit_initial_response(
            components=panel(state, "No valid attachment was submitted. Your draft is unchanged."),
            **NO_MENTIONS,
        ); return
    if attachment.size > MAX_IMAGE_BYTES:
        await interaction.edit_initial_response(
            components=panel(state, f"Images must be under {MAX_IMAGE_BYTES // (1024 * 1024)} MB. Your draft is unchanged."),
            **NO_MENTIONS,
        ); return
    try:
        data = await attachment.read()
    except (hikari.HTTPError, OSError, asyncio.TimeoutError):
        await interaction.edit_initial_response(
            components=panel(state, "I could not download that attachment. Your draft is unchanged; try again shortly."),
            **NO_MENTIONS,
        ); return
    try:
        url = await media.upload_bytes(
            data,
            folder=recruit_content_folder(int(interaction.guild_id), document.key),
            name=slot,
        )
    except MediaStoreError as exc:
        await interaction.edit_initial_response(
            components=panel(state, f"{exc} Your draft is unchanged."), **NO_MENTIONS
        ); return
    draft = await new_draft(mongo, dict(
        state,
        media=normal_media(document, state.get("media")) | {slot: url},
        selected_media_slot=slot,
    ))
    label = dict(media_slots(document))[slot]
    await interaction.edit_initial_response(
        components=panel(draft, f"{label} uploaded to this draft. Preview, save, or update the selected post."),
        **NO_MENTIONS,
    )


@register_action("content_reset_media", preload_state=False)
@lightbulb.di.with_di
async def reset_media(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    document = DOCUMENTS.get(state.get("document"))
    slot = state.get("selected_media_slot")
    if not document or slot not in {name for name, _label in media_slots(document)}:
        return panel(state, "Choose an image slot before resetting it.")
    media = normal_media(document, state.get("media"))
    media.pop(slot, None)
    label = dict(media_slots(document))[slot]
    return panel(
        await new_draft(mongo, dict(state, media=media, selected_media_slot=slot)),
        f"Original artwork restored for {label}. Use Save template to keep this change, or Update selected post to apply it to the linked message.",
    )


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
    document = DOCUMENTS[state["document"]]
    update = {
        "sections": state["sections"], "media": normal_media(document, state.get("media")),
        "revision": revision + 1, "updated_by": int(ctx.user.id), "updated_at": utcnow(),
    }
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
    saved_state = dict(state, revision=state["revision"] + 1)
    saved_state["saved_snapshot"] = draft_snapshot(saved_state)
    return panel(await new_draft(mongo, saved_state), "Template saved for future posts in this server.")


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
        if (
            int(message.author.id) != int(ctx.interaction.application_id)
            or component_shape(message.components) != component_shape(await baseline(document))
            or [node.content for node in text_nodes(message.components)] != target["original"]
            or (
                target.get("original_media") is not None
                and media_snapshot(message.components) != target["original_media"]
            )
        ):
            raise ValueError("That post changed since this draft opened. Reopen the dashboard to review it.")
        acknowledgement = acknowledgement_id(message.components, document)
        if not acknowledgement: raise ValueError("That is not the selected content type.")
        rendered = await render(
            document, state["sections"], media=state.get("media"), action_id=acknowledgement
        )
        referenced_attachment_ids = {
            attachment_id for url in media_snapshot(rendered)
            if (attachment_id := discord_attachment_id(url)) is not None
        }
        retained_attachments = [
            attachment for attachment in getattr(message, "attachments", ())
            if str(attachment.id) in referenced_attachment_ids
        ]
        updated_message = await bot.rest.edit_message(
            target["channel_id"], target["message_id"],
            components=rendered,
            attachments=retained_attachments,
            **NO_MENTIONS,
        )
    except (ValueError, hikari.NotFoundError, hikari.ForbiddenError) as exc:
        return panel(state, str(exc) if isinstance(exc, ValueError) else "The bot cannot update that message. Your draft is still available.")
    finally:
        await mongo.bot_config.delete_one({"_id": lease_key, "token": token})
    return panel(
        await new_draft(mongo, dict(
            state,
            target=dict(
                target, original=state["sections"],
                original_media=media_snapshot(getattr(updated_message, "components", ())),
            ),
        )),
        "Selected post updated.",
    )

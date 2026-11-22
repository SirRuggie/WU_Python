"""Private, schema-driven editor for published Warriors United content."""

import asyncio
import copy
import re
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from datetime import timedelta
from urllib.parse import urlparse

import hikari
import lightbulb
from pymongo.errors import DuplicateKeyError, PyMongoError

from extensions.components import register_action
from utils.component_state import get_state, insert_state, update_state, utcnow
from utils.info_channel_content import load_family_clans, validate_rendered_text, strip_manual_clan_prefix
from utils.content_media import (
    media_galleries,
    media_url,
    canonical_media_url,
    discord_attachment_id,
    media_snapshot,
)
from utils.discord_file_upload import (
    FileUploadModalComponentBuilder,
    install_file_upload_capture,
    pop_file_upload,
)
from utils.media_store import MediaStore, MediaStoreError, recruit_content_folder
from utils.mongo import MongoClient
from utils.constants import WU_GOLD, WU_RED
from utils.url_safety import MAX_IMAGE_BYTES
from utils.recruit_setup_checks import fetch_bot_member, require_ready
from utils.manage_ui import breadcrumb, button_emoji


loader = lightbulb.Loader()
content = lightbulb.Group("content", "Manage published server content")
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
MESSAGE_LINK = re.compile(r"<?https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)/?>?")


@dataclass(frozen=True)
class Document:
    key: str
    label: str
    acknowledgement: str | None
    legacy_key: str | None = None


DOCUMENTS = {
    "join-family": Document("join-family", "Join the Family", "join_family_acknowledge"),
    "about-us": Document("about-us", "About Us", "aboutus_acknowledge", "recruit_aboutus"),
    "strike-system": Document("strike-system", "WU Strike System", "strikesystem_acknowledge"),
    "family-particulars": Document("family-particulars", "Family Particulars", "familyparticulars_acknowledge"),
    "apply": Document("apply", "Apply / Clan Entry", "ticket_v2_rite_open"),
    "warrior_desk": Document("warrior_desk", "Warrior Desk", "ticket_v2_create"),
    "rite-of-passage": Document("rite-of-passage", "Rite of Passage", "ticket_v2_rite_choose"),
    "family-rules": Document("family-rules", "Family Rules", None),
    "wu-faq": Document("wu-faq", "WU FAQ", None),
}
from utils.gauntlet_content import BOXES, LENGTHS, LEGACY_LENGTHS, sections_for as box_sections, validate_sections, project_public, merge_public, layout_for, layout_notice, logical_sections, require_writable, save_sections, LAYOUT_VERSION
from utils.gauntlet_content import AMBIGUOUS_NOTICE

BLOCK_LABELS = {
    "join-family": ("Heading", "Welcome", "What happens next", "Call to action"),
    "about-us": ("Welcome heading", "Welcome overview", "Tactical heading", "Tactical details", "Flexible Fun heading", "Flexible Fun details", "FWA heading", "FWA details", "Disclaimer heading", "Disclaimer", "Next step heading", "Next step"),
    "strike-system": ("How strikes work heading", "How strikes work", "At 4 strikes heading", "At 4 strikes", "Main clan heading", "Main clan note", "FWA heading", "FWA note", "Terms heading", "Terms", "Acknowledgement heading", "Acknowledgement"),
    "family-particulars": ("Family heading", "Intro heading", "Intro", "Friendly challenges heading", "Friendly challenges", "Clan games heading", "Clan games", "War rules heading", "War eligibility heading", "War eligibility", "Prep day heading", "Prep day", "Battle day heading", "Battle day", "CWL heading", "CWL overview", "CWL principles heading", "CWL principles", "Acknowledgement heading", "Acknowledgement"),
    "apply": ("Heading", "Body"),
    "warrior_desk": ("Heading", "Body"),
    "rite-of-passage": ("Heading", "Introduction", "Main path", "FWA path", "Closing"),
    "family-rules": ("Heading", "Body"),
    "wu-faq": ("Questions heading", "Questions", "Who we are heading", "Who we are", "Our Clans heading", "Tactical description", "Flexible Fun description", "FWA description", "Clans footer"),
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
    "apply": (("footer", "Footer image"),),
    "warrior_desk": (("footer", "Footer image"),),
    "rite-of-passage": (("guide", "Rite of Passage guide"),),
    "family-rules": (),
    "wu-faq": (),
}
# Panels bound to one live post owned by the ticket rollout (no posting channel).
_BOUND_PANELS = frozenset({"apply", "warrior_desk"})
BOUND_PANELS = _BOUND_PANELS  # public name for the web content/publish adapters
_baselines: dict[str, list] = {}
_DESTINATION_TYPES = frozenset((hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS))


def has_posting_channel(document_key):
    return document_key in DOCUMENTS and document_key not in {*_BOUND_PANELS, "rite-of-passage", "family-rules"}


def is_template_only(document_key):
    return document_key in {"rite-of-passage", "family-rules"}


def acknowledgement_setup(document_key: str, guild_id: int = 644963518025826315) -> tuple[int, int]:
    from utils.gauntlet_routes import route_for
    route = route_for(document_key, guild_id)
    if route is None:
        raise ValueError("This onboarding step is not configured for this server.")
    return route


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
    from extensions.commands.setup import recruit_aboutus, recruit_familyparticulars, recruit_strikesystem, recruit_join_family, recruit_wu_faq
    from extensions.commands.tickets import setup as ticket_setup, rite
    build = {
        "join-family": recruit_join_family.build_join_family,
        "about-us": recruit_aboutus.build_aboutus,
        "family-rules": recruit_wu_faq.build_family_rules,
        "wu-faq": recruit_wu_faq.build_wu_faq,
        "strike-system": recruit_strikesystem.build_strikesystem,
        "family-particulars": recruit_familyparticulars.build_familyparticulars,
        "apply": ticket_setup.create_public_ticket_embed,
        "warrior_desk": ticket_setup.create_warrior_desk_embed,
        "rite-of-passage": rite.build_rite,
    }[document.key]
    _baselines[document.key] = build()
    return copy.deepcopy(_baselines[document.key])


def document_renderer(document: Document):
    from extensions.commands.setup import recruit_aboutus, recruit_familyparticulars, recruit_strikesystem, recruit_join_family, recruit_wu_faq
    from extensions.commands.tickets import setup as ticket_setup, rite
    return {
        "join-family": recruit_join_family.build_join_family,
        "about-us": recruit_aboutus.build_aboutus,
        "family-rules": recruit_wu_faq.build_family_rules,
        "wu-faq": recruit_wu_faq.build_wu_faq,
        "strike-system": recruit_strikesystem.build_strikesystem,
        "family-particulars": recruit_familyparticulars.build_familyparticulars,
        "apply": ticket_setup.create_public_ticket_embed,
        "warrior_desk": ticket_setup.create_warrior_desk_embed,
        "rite-of-passage": rite.build_rite,
    }[document.key]


def editable_text_nodes(document, components):
    nodes = text_nodes(components)
    if document.key in {"about-us", "strike-system", "family-particulars"}:
        texts = [node.content for node in nodes]
        new_layout = ((document.key == "about-us" and len(components) == 5 and len(texts) == 11)
                      or (document.key == "strike-system" and len(components) == 6 and len(texts) == 12)
                      or (document.key == "family-particulars" and len(components) == 7 and len(texts) == 14))
        if not new_layout and document.key == "about-us" and len(texts) == 14:
            texts = texts[:10] + texts[12:]
        fields = project_public(document.key, texts, legacy=not new_layout)
        return [hikari.impl.TextDisplayComponentBuilder(content=value) for value in fields]
    if document.key == "wu-faq":
        if len(nodes) == 4:
            from utils.info_channel_defaults import WU_FAQ_NEW_FIELDS
            return nodes[2:] + [hikari.impl.TextDisplayComponentBuilder(content=value) for value in WU_FAQ_NEW_FIELDS]
        if len(nodes) == 14:
            return [nodes[index] for index in (12, 13, 0, 1, 2, 3, 5, 7, 9)]
        if len(nodes) == 11:
            from utils.gauntlet_content import without_label, faq_type_body
            from utils.info_channel_content import strip_manual_clan_suffix
            fields = box_sections("wu-faq")
            for target, source in {2:0,3:1,4:2,8:6,0:9,1:10}.items():
                fields[target] = nodes[source].content
            for target, source, kind in ((5,3,"Tactical"),(6,4,"Flexible Fun"),(7,5,"FWA")):
                body = strip_manual_clan_suffix(without_label(kind, nodes[source].content))
                if body != faq_type_body(kind, fields[target]):
                    fields[target] = body
            return [hikari.impl.TextDisplayComponentBuilder(content=value) for value in fields]
    return nodes


async def validate_template(document, sections, media=None):
    if document.key in BOXES:
        validate_sections(document.key, sections)
    else:
        expected = len(editable_text_nodes(document, await baseline(document)))
        if (not isinstance(sections, list) or len(sections) != expected
                or any(not isinstance(value, str) or not value.strip() for value in sections)):
            raise ValueError("The saved text layout is invalid. Reopen the content dashboard.")
    return normal_media(document, media)


async def render(document: Document, sections, *, media=None, action_id="preview", preview=False,
                 mongo=None, guild_id=None):
    if document.key in BOXES:
        sections = box_sections(document.key, sections)
    overrides = await validate_template(document, sections, media)
    resolved = {}
    if document.key in {"about-us", "wu-faq"}:
        if mongo is None or guild_id is None or int(guild_id) <= 0:
            raise ValueError("This preview needs its server and clan registry. Reopen Recruit Gauntlet.")
        try:
            rules, _rules_media, _rules_revision = await template_for(mongo, DOCUMENTS["family-rules"], int(guild_id))
        except (PyMongoError, OSError) as error:
            raise ValueError("I cannot read Family Rules right now. No post was changed. Try Preview again later.") from error
        resolved["family_rules"] = rules
        resolved["clans"] = await load_family_clans(mongo)
    components = document_renderer(document)(
        sections, media=overrides, action_id=action_id, preview=preview, **resolved
    )
    if component_count(components) > 40:
        raise ValueError("This document exceeds Discord's 40-component message limit.")
    validate_rendered_text([node.content for node in text_nodes(components)])
    if len(media_galleries(components)) != len(media_slots(document)):
        raise ValueError("This document's media layout is not supported by the content dashboard.")
    return components


async def template_for(mongo, document: Document, guild_id: int, *, allow_ambiguous_display=False):
    """Read one saved version; unknown Particulars layouts never become defaults.

    Only the read-only Publish page opts into displaying unknown all-string list
    lengths. Normal editor, queue, setup and worker reads reject those layouts.
    The existing raw28/34 ambiguity handling remains unchanged.
    """
    saved = await mongo.bot_config.find_one({"_id": f"content:{document.key}:{guild_id}"})
    if saved and isinstance(saved.get("sections"), list):
        try:
            media = normal_media(document, saved.get("media"))
            sections = list(saved["sections"])
            if (document.key == "family-particulars" and all(isinstance(value, str) for value in sections)
                    and len(sections) not in (28, 34)):
                if allow_ambiguous_display:
                    return sections, media, int(saved.get("revision", 0))
                raise ValueError(AMBIGUOUS_NOTICE)
            if document.key in BOXES:
                sections = box_sections(document.key, sections)
                # An ambiguous legacy Strike split remains editable, not a
                # default fallback that discards staff text. Render/Save validate.
            else:
                await validate_template(document, sections, media=media)
            return sections, media, int(saved.get("revision", 0))
        except ValueError:
            if document.key == "family-particulars":
                # Invalid text/media and unsupported lengths must not silently
                # substitute a publishable built-in template.
                raise
            if document.key in LEGACY_LENGTHS and LEGACY_LENGTHS[document.key] < len(saved["sections"]) < LENGTHS[document.key]:
                raise
            if document.key == "family-rules":
                raise ValueError("The saved Family Rules are incomplete. Correct their heading and body before posting.") from None
    elif saved:
        if document.key == "family-rules":
            raise ValueError("The saved Family Rules are incomplete. Correct their heading and body before posting.")
        if document.key == "family-particulars":
            raise ValueError("The saved info document has invalid text. Reopen it for review.")
    if document.legacy_key:
        legacy = await mongo.bot_config.find_one({"_id": f"{document.legacy_key}:{guild_id}"})
        if legacy and isinstance(legacy.get("sections"), list):
            try:
                sections = box_sections(document.key, legacy["sections"]) if document.key in BOXES else list(legacy["sections"])
                await validate_template(document, sections)
                # Migration writes a new content key, so legacy revision cannot
                # participate in that key's compare-and-swap predicate.
                return sections, {}, 0
            except ValueError:
                pass
    components = await baseline(document)
    return [node.content for node in editable_text_nodes(document, components)], {}, 0


async def sections_for(mongo, document, guild_id):
    """Compatibility wrapper for setup and older callers that need only text."""
    sections, _media, revision = await template_for(mongo, document, guild_id)
    return sections, revision


async def saved_media_for(mongo, document: Document, guild_id: int):
    """Return valid saved overrides without allowing a bad row to break setup."""
    _sections, media, _revision = await template_for(mongo, document, guild_id)
    return media


def editable_blocks(document, sections):
    if document.key in BOXES:
        return tuple((index, label) for box, fields in BOXES[document.key] for index, label in fields)
    return tuple(enumerate(BLOCK_LABELS[document.key]))


def editable_groups(document, sections):
    """Keep a section's heading and body in the same modal."""
    if document.key in BOXES:
        return tuple((label, tuple((index, field, "full") for index, field in fields))
                     for label, fields in BOXES[document.key])
    blocks = editable_blocks(document, sections)
    if document.key == "family-rules":
        return (("Family Rules", ((0, "Heading", "full"), (1, "Body", "full"))),)
    if document.key == "join-family":
        return (
            ("Welcome", ((blocks[0][0], "Heading", "full"), (blocks[1][0], "Body", "full"))),
            ("What happens next", ((blocks[2][0], "Title", "title"), (blocks[2][0], "Body", "body"))),
            ("Call to action", ((blocks[3][0], "Title", "title"), (blocks[3][0], "Body", "body"))),
        )
    if document.key in _BOUND_PANELS:
        return (("Apply panel" if document.key == "apply" else "Warrior Desk panel",
                 ((0, "Heading", "full"), (1, "Body", "full"))),)
    if document.key == "rite-of-passage":
        return (
            ("Introduction", ((0, "Heading", "full"), (1, "Body", "full"))),
            ("Main path", ((2, "Title", "title"), (2, "Body", "body"))),
            ("FWA path", ((3, "Title", "title"), (3, "Body", "body"))),
            ("Closing", ((4, "Title", "title"), (4, "Body", "body"))),
        )
    groups = []
    position = 0
    while position < len(blocks):
        index, label = blocks[position]
        if label.lower().endswith("heading") and position + 1 < len(blocks) and not blocks[position + 1][1].lower().endswith("heading"):
            body_index, _ = blocks[position + 1]
            groups.append((label.rsplit(" ", 1)[0], ((index, "Heading / Title", "full"), (body_index, "Body", "full"))))
            position += 2
        else:
            groups.append((label, ((index, "Heading / Title" if label.lower().endswith("heading") else "Body", "full"),)))
            position += 1
    return tuple(groups)


def modal_field_value(section, part):
    if part == "full":
        return section
    title, separator, body = section.partition("\n")
    if not separator:
        raise ValueError("This section needs a title and body separated by a line break.")
    return title if part == "title" else body


def target_matches_destination(state):
    target = state.get("target")
    channel_id = state.get("destination_channel_id")
    return bool(target) and (channel_id is None or int(target["channel_id"]) == int(channel_id))


def acknowledgement_id(components, document):
    if document.acknowledgement is None:
        return None
    for component in components:
        for child in getattr(component, "components", ()):
            for button in getattr(child, "components", ()):
                custom_id = getattr(button, "custom_id", "") or ""
                if document.key == "apply" and custom_id == document.acknowledgement:
                    return "public"
                if custom_id.startswith(document.acknowledgement + ":"):
                    return custom_id.partition(":")[2]
    return None


def destination_key(guild_id: int, document_key: str) -> str:
    if document_key not in DOCUMENTS or document_key == "family-rules" or int(guild_id) <= 0:
        raise ValueError("Select a Recruit Gauntlet document in this server.")
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


def published_key(guild_id: int, document_key: str) -> str:
    if document_key not in DOCUMENTS or int(guild_id) <= 0:
        raise ValueError("Select a Recruit Gauntlet document in this server.")
    return f"content_published:{int(guild_id)}:{document_key}"


async def published_for(mongo, guild_id: int, document_key: str):
    if is_template_only(document_key):
        return None
    if document_key in _BOUND_PANELS:
        from extensions.commands import ticket_runtime
        rollout = await ticket_runtime.get_rollout(mongo)
        source = (
            rollout.thread_intake if document_key == "apply" else rollout.desk_intake
        ) if rollout.valid else None
        if source is None or source.guild_id != int(guild_id):
            return None
        return {"channel_id": source.channel_id, "message_id": source.message_id}
    row = await mongo.bot_config.find_one({"_id": published_key(guild_id, document_key)})
    if not row:
        return None
    try:
        channel_id, message_id = int(row["channel_id"]), int(row["message_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if row.get("guild_id") != int(guild_id) or row.get("document") != document_key or channel_id <= 0 or message_id <= 0:
        return None
    return {"channel_id": channel_id, "message_id": message_id}


async def remember_published(mongo, guild_id: int, document_key: str, channel_id: int, message_id: int, user_id: int):
    await mongo.bot_config.update_one(
        {"_id": published_key(guild_id, document_key)},
        {"$set": {
            "guild_id": guild_id, "document": document_key,
            "channel_id": channel_id, "message_id": message_id,
            "updated_by": user_id, "updated_at": utcnow(),
        }},
        upsert=True,
    )


async def loaded_published_target(bot, guild_id: int, document: Document, coordinates, application_id: int):
    """Validate the saved pointer and snapshot its live text/media for stale checks."""
    recovery = (
        "Complete ticket setup to restore the active public Apply post."
        if document.key == "apply" else
        "Post the Warrior Desk panel again from Ticket settings."
        if document.key == "warrior_desk" else
        "Check the channel. If you need a new post, select Send to channel."
    )
    try:
        channel = await bot.rest.fetch_channel(coordinates["channel_id"])
        if int(getattr(channel, "guild_id", 0)) != guild_id:
            raise ValueError(f"The published post is outside this server. {recovery}")
        message = await bot.rest.fetch_message(coordinates["channel_id"], coordinates["message_id"])
        if (int(message.author.id) != application_id
                or not await supported_post_shape(document, message.components)
                or document.acknowledgement and not acknowledgement_id(message.components, document)):
            raise ValueError(f"The saved message is not supported now. {recovery}")
        sections = [node.content for node in text_nodes(message.components)]
        original_media = media_snapshot(message.components)
        if len(original_media) != len(media_slots(document)):
            raise ValueError("The saved post's images changed. Check the channel. If you need a new post, select Send to channel.")
        await validate_template(document, [node.content for node in editable_text_nodes(document, message.components)])
    except (hikari.NotFoundError, hikari.ForbiddenError):
        raise ValueError(f"The saved post cannot be found or opened. {recovery}") from None
    except (hikari.HTTPError, OSError):
        raise ValueError("I cannot read the published post right now. Your draft is still available.") from None
    return dict(coordinates, original=sections, original_media=original_media,
                editable_original=[node.content for node in editable_text_nodes(document, message.components)],
                tracked=True)


async def shared_rule_targets(mongo, bot, guild_id, application_id):
    """Snapshot existing posts when an update is offered, without registry reads."""
    targets, errors = {}, {}
    for key in ("wu-faq", "about-us"):
        try:
            coordinates = await published_for(mongo, guild_id, key)
            if not coordinates:
                continue
            targets[key] = await loaded_published_target(bot, guild_id, DOCUMENTS[key], coordinates, application_id)
        except ValueError as error:
            errors[key] = str(error)
        except (PyMongoError, OSError):
            errors[key] = "I cannot read this linked post right now. It was not updated. Reopen the editor to review it later."
    return targets, errors


async def supported_post_shape(document, components):
    shape = component_shape(components)
    if shape == component_shape(await baseline(document)):
        return True
    text, separator, image, row = (10, ()), (14, ()), (12, ()), (1, ((2, ()),))
    box = lambda *children: (17, tuple(children))
    legacy = {
        "about-us": (
            image, box(text,separator,text,separator,text,text), box(text,text),
            box(text,text,separator,text,text), box(text,text), box(text,text,row)),
        "strike-system": (
            image, box(text,separator,text), box(text,separator,text),
            box(text,separator,text,image), box(text,separator,text,image),
            box(text,separator,text), box(text,separator,text,row)),
        "family-particulars": (
            image, box(text,separator,*([text]*9)), box(text,separator,*([text]*9)),
            box(text,separator,*([text]*5),image), box(text,separator,text,row)),
        "wu-faq": (box(text,text),box(text,text)),
    }
    if shape == legacy.get(document.key):
        return True
    if document.key == "about-us":
        old = legacy["about-us"]
        return shape == old[:4] + old[5:]
    if document.key == "wu-faq":
        return shape == (box(text,text),box(*([text]*8)),box(text,text),box(text,text))
    return False


def _apply_overwrite(base: hikari.Permissions, overwrite) -> hikari.Permissions:
    return hikari.Permissions(
        (int(base) & ~int(getattr(overwrite, "deny", 0)))
        | int(getattr(overwrite, "allow", 0))
    )


async def destination_permissions(bot, guild_id: int, channel) -> hikari.Permissions:
    """Resolve the bot's permissions in the selected channel, including overwrites."""
    roles = tuple(await bot.rest.fetch_roles(guild_id))
    member = await fetch_bot_member(bot, guild_id)
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
    if document_key == "wu-faq":
        return True, None
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
    try:
        role_id, next_channel_id = acknowledgement_setup(document_key, ctx.interaction.guild_id)
    except ValueError as exc:
        return False, str(exc)
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
    if state.get("document") in BOXES:
        normalize = lambda values: box_sections(state["document"], values)
        state["sections"] = normalize(state["sections"])
        if state.get("saved_snapshot"):
            state["saved_snapshot"] = dict(state["saved_snapshot"], sections=normalize(state["saved_snapshot"]["sections"]))
    if state.get("document") == "family-particulars":
        state["layout_version"] = LAYOUT_VERSION
    state["_id"] = uuid.uuid4().hex
    await insert_state(mongo, state, ttl=timedelta(minutes=30))
    return state


def panel(state, notice=None):
    sid = state["_id"]
    notice = notice or state.get("notice")
    if state.get("view") == "root" or not state.get("document"):
        choose = hikari.impl.MessageActionRowBuilder()
        menu = choose.add_text_menu(f"content_document:{sid}", min_values=1, placeholder="Select content to edit")
        for document in DOCUMENTS.values():
            menu.add_option(document.label, document.key)
        rows = [
            hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet")),
            hikari.impl.TextDisplayComponentBuilder(
                content=("## Recruit Gauntlet\nManage onboarding content." if state.get("manage_token") else "## :shield: Warriors United Content Dashboard\nSelect an onboarding document to edit.")
            ),
        ]
        if notice:
            rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
        rows.append(choose)
        help_settings = hikari.impl.MessageActionRowBuilder()
        help_settings.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, f"gauntlet_help:{sid}",
            label="Help & reminders", emoji=button_emoji("Settings"),
        )
        rows.append(help_settings)
        if state.get("manage_token"):
            home = hikari.impl.MessageActionRowBuilder()
            home.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"manage_home:{state['manage_token']}", label="Management Home", emoji=button_emoji("Management Home"))
            rows.append(home)
        return [hikari.impl.ContainerComponentBuilder(accent_color=WU_GOLD, components=rows)]

    document = DOCUMENTS[state["document"]]
    overrides = normal_media(document, state.get("media"))
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", document.label)),
        hikari.impl.TextDisplayComponentBuilder(content=f"## {document.label}"),
        hikari.impl.TextDisplayComponentBuilder(
            content=(f"{'Unsaved changes' if has_unsaved_edits(state) else 'Saved'} · Preview checks the whole post · draft expires in 30 minutes." if document.key in BOXES else f"{'Unsaved changes' if has_unsaved_edits(state) else 'Saved'} · {sum(map(len, state['sections']))}/4,000 characters · draft expires in 30 minutes.")
        ),
    ]
    if document.key in {"about-us", "wu-faq"}:
        rows.append(hikari.impl.TextDisplayComponentBuilder(
            content="Preview checks the complete post, including current Family Rules and registry clan lists, against the 4,000-character limit."
        ))
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    readonly_notice = layout_notice(document.key, state["sections"]) if layout_for(document.key, state["sections"]) == "ambiguous" else None
    if layout_for(document.key, state["sections"]) == "compact":
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=layout_notice(document.key, state["sections"])))
    if readonly_notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=readonly_notice))
        choose = hikari.impl.MessageActionRowBuilder()
        menu = choose.add_text_menu(f"content_block:{sid}", min_values=1, placeholder="View saved values")
        for index in range(min(25, len(state["sections"]))):
            menu.add_option(f"Raw saved fields 25–{len(state['sections'])}" if index == 24 and len(state["sections"]) > 25 else f"Raw saved field {index + 1}", str(index))
        # Remaining fields are included together in the final paged raw screen.
        rows.append(choose)
        buttons = hikari.impl.MessageActionRowBuilder()
        buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_root:{sid}", label="Back")
        rows.append(buttons)
        return [hikari.impl.ContainerComponentBuilder(accent_color=WU_GOLD, components=rows)]
    blocks = hikari.impl.MessageActionRowBuilder()
    menu = blocks.add_text_menu(f"content_block:{sid}", min_values=1, placeholder="Select a section to edit")
    for index, (label, _fields) in enumerate(editable_groups(document, state["sections"])):
        menu.add_option(label, str(index))
    if media_slots(document):
        menu.add_option("Images", "images")
    images = hikari.impl.MessageActionRowBuilder()
    selected_slot = state.get("selected_media_slot")
    image_menu = images.add_text_menu(
        f"content_media:{sid}", min_values=1, placeholder="Select an image to edit"
    )
    for slot, label in media_slots(document):
        source = "custom image" if slot in overrides else "default image"
        image_menu.add_option(f"{label} ({source})", slot, is_default=slot == selected_slot)
    private_only = is_template_only(document.key)
    fixed_public = document.key in _BOUND_PANELS
    destination = state.get("destination_channel_id")
    destination_menu = hikari.impl.MessageActionRowBuilder()
    destination_menu.add_channel_menu(
        f"content_destination:{sid}",
        channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
        placeholder="Select a posting channel", min_values=1, max_values=1,
    )
    destination_status = (
        f"Posting channel: <#{destination}>. Send to channel posts this draft. Save template keeps it so you can edit it later."
        if destination else
        "Posting channel: No channel selected. Select a channel below to send this draft. Save template keeps it so you can edit it later."
    )
    send_buttons = hikari.impl.MessageActionRowBuilder()
    send_buttons.add_interactive_button(
        hikari.ButtonStyle.PRIMARY, f"content_send:{sid}", label="Send to channel", emoji=button_emoji("Send to channel"),
        is_disabled=not destination,
    )
    buttons = hikari.impl.MessageActionRowBuilder()
    buttons.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"content_preview:{sid}", label="Preview", emoji=button_emoji("Preview"))
    buttons.add_interactive_button(hikari.ButtonStyle.SUCCESS, f"content_save:{sid}", label="Save template", emoji=button_emoji("Save template"))
    if not private_only and target_matches_destination(state):
        buttons.add_interactive_button(hikari.ButtonStyle.SUCCESS, f"content_publish:{sid}", label="Update published post", emoji=button_emoji("Update selected post"))
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
    if target and target_matches_destination(state):
        target_url = f"https://discord.com/channels/{state['guild_id']}/{target['channel_id']}/{target['message_id']}"
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"Published post to update: [View post]({target_url}) in <#{target['channel_id']}>."))
        if state["sections"] != target.get("editable_original", target["original"]):
            rows.append(hikari.impl.TextDisplayComponentBuilder(content="The saved template is not the same as the published post. This draft shows the saved template. To start from the published text, select Load published copy first."))
            load_buttons = hikari.impl.MessageActionRowBuilder()
            load_buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_load_published:{sid}", label="Load published copy")
            rows.append(load_buttons)
    if target and not target_matches_destination(state) and not fixed_public:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="The saved post is in a different channel. If you send here, a new post is made. To update the saved post, select its original channel."))
    controls = [blocks]
    if media_slots(document) and state.get("selected_box") == "Images":
        controls.append(images)
    controls.append(hikari.impl.SeparatorComponentBuilder(divider=True))
    if private_only:
        controls.append(hikari.impl.TextDisplayComponentBuilder(
            content=("Family Rules is shared by WU FAQ and About Us. Saving does not change a published post."
                     if document.key == "family-rules" else
                     "Save template updates future private Rite of Passage panels.")
        ))
    elif fixed_public:
        controls.append(hikari.impl.TextDisplayComponentBuilder(
            content=(("Warrior Desk is linked to its saved panel. Save template keeps the text for later posts. "
                      "Update published post changes the linked panel now." if target else
                      "No Warrior Desk panel is linked. Use Post Warrior Desk panel in Ticket settings. You can still save this template.")
                     if document.key == "warrior_desk" else
                     ("Apply is linked to the public ticket post. Save template keeps the text for later posts. "
                      "Update published post changes the public post now." if target else
                      "No public Apply post is linked. Complete ticket setup before you update the public post. "
                      "You can still save this template."))
        ))
    else:
        controls.extend([hikari.impl.TextDisplayComponentBuilder(content=destination_status),
                         destination_menu, send_buttons])
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
                content="-# Restore default image puts back the original artwork. Use Save template to keep your changes."
            ),
        ])
    controls.append(buttons)
    if document.key == "family-rules":
        controls.extend(shared_rules_offer(state))
    if selected_buttons is not None:
        controls.append(selected_buttons)
    controls.extend([hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL), footer])
    return [hikari.impl.ContainerComponentBuilder(accent_color=WU_GOLD, components=rows + controls)]


def shared_rules_offer(state):
    targets = state.get("shared_targets", {})
    errors = state.get("shared_target_errors", {})
    results = state.get("shared_update_results", {})
    rows = []
    for key in ("wu-faq", "about-us"):
        target = targets.get(key)
        if key in results:
            message = results[key]["message"]
        elif target:
            link = f"https://discord.com/channels/{state['guild_id']}/{target['channel_id']}/{target['message_id']}"
            message = f"[Published post]({link}) can be updated after you save."
        else:
            message = errors.get(key, "No linked published post. No new message will be sent.")
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"**{DOCUMENTS[key].label}:** {message}"))
    if targets and state.get("revision", 0) > 0 and not has_unsaved_edits(state) and not state.get("shared_update_started"):
        row = hikari.impl.MessageActionRowBuilder()
        row.add_interactive_button(hikari.ButtonStyle.SUCCESS, f"content_rules_publish:{state['_id']}", label="Update linked posts")
        rows.append(row)
    if state.get("shared_update_started") and not results:
        rows.append(hikari.impl.TextDisplayComponentBuilder(
            content="This update was already started. Check both posts before reopening the editor; it will not retry automatically."
        ))
    return rows


def error_panel(message):
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=WU_RED,
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"## Content Dashboard\n{message}")],
    )]


async def preview_panel(state, mongo=None):
    """Keep the post layout intact while turning its inert CTA into Back."""
    document = DOCUMENTS[state["document"]]
    components = await render(document, state["sections"], media=state.get("media"), preview=True,
                              mongo=mongo, guild_id=state["guild_id"])
    if document.acknowledgement is None:
        back = hikari.impl.MessageActionRowBuilder()
        back.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_document:{state['_id']}", label="Back to editor")
        components.append(back)
        return components
    for component in components:
        for child in getattr(component, "components", ()):
            if isinstance(child, hikari.impl.MessageActionRowBuilder):
                for button in child.components:
                    custom_id = getattr(button, "custom_id", "")
                    if (custom_id.startswith(document.acknowledgement + ":")
                            or document.key == "apply" and custom_id == document.acknowledgement):
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
        return "This draft expired. Run `/manage` and select Recruit Gauntlet again."
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
    problem = state_problem(ctx, state)
    if not problem and state.get("document") == "family-particulars" and state.get("layout_version") != LAYOUT_VERSION:
        return state, "This content draft predates the corrected field mapping. Reopen Family Particulars before editing or updating it."
    if not problem and state.get("document") in BOXES:
        state = copy.deepcopy(state)
        normalize = lambda values: box_sections(state["document"], values)
        state["sections"] = normalize(state["sections"])
        if state.get("saved_snapshot"):
            state["saved_snapshot"]["sections"] = normalize(state["saved_snapshot"]["sections"])
    return state, problem


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
            if document and document.key in {*_BOUND_PANELS, "rite-of-passage"}:
                source = await published_for(mongo, state["guild_id"], document.key)
                if source != {"channel_id": int(match[2]), "message_id": int(match[3])}:
                    await initial_panel(ctx, mongo, state, "Open Warrior Desk from Ticket settings. Only the bound Warrior Desk panel can be updated." if document.key == "warrior_desk" else "Open this ticket panel from Recruit Gauntlet. Apply updates only the active public ticket post."); return
            if not document:
                await initial_panel(ctx, mongo, state, "Select a supported post."); return
            original_sections = [node.content for node in text_nodes(message.components)]
            sections = [node.content for node in editable_text_nodes(document, message.components)]
            try:
                if not await supported_post_shape(document, message.components):
                    raise ValueError("The content dashboard does not support the layout of that post.")
                original_media = media_snapshot(message.components)
                if len(original_media) != len(media_slots(document)):
                    raise ValueError("The content dashboard does not support the image layout of that post.")
                await validate_template(document, sections)
            except ValueError:
                await initial_panel(ctx, mongo, state, "The content dashboard does not support the layout of that post."); return
            _template, _media, revision = await template_for(mongo, document, state["guild_id"])
            if document.key in BOXES:
                sections = merge_public(document.key, _template, sections)
            destination_row = (await mongo.bot_config.find_one({"_id": destination_key(state["guild_id"], document.key)})
                       if document.key != "family-rules" else None)
            state.update(
                view="document", document=document.key, sections=sections, revision=revision,
                media=dict(zip((slot for slot, _label in media_slots(document)), original_media, strict=True)),
                target={
                    "channel_id": int(match[2]), "message_id": int(match[3]),
                    "original": original_sections, "original_media": original_media,
                    "editable_original": sections,
                },
                destination_channel_id=(destination_row or {}).get("channel_id"),
                destination_baseline=destination_row,
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
    return [hikari.impl.ContainerComponentBuilder(accent_color=WU_GOLD, components=[
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", DOCUMENTS[state["document"]].label)),
        hikari.impl.TextDisplayComponentBuilder(content="## Leave content editor?"),
        hikari.impl.TextDisplayComponentBuilder(content="If you open Recruit Gauntlet again, it starts a new draft. Unsaved edits are not restored. To keep your edits, save the template before you leave."),
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
async def choose_document(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                          bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    value = getattr(ctx.interaction, "values", ())
    if len(value) != 1 or value[0] not in DOCUMENTS:
        return panel(state, "Select one supported document.")
    document = DOCUMENTS[value[0]]
    sections, media, revision = await template_for(mongo, document, state["guild_id"])
    destination_row = (await mongo.bot_config.find_one({"_id": destination_key(state["guild_id"], document.key)})
                       if document.key != "family-rules" else None)
    destination_channel_id = ((destination_row or {}).get("channel_id")
                              if has_posting_channel(document.key) else None)
    target = state.get("target") if state.get("document") == document.key and document.key not in _BOUND_PANELS else None
    notice = None
    if target is None:
        coordinates = await published_for(mongo, state["guild_id"], document.key)
        if coordinates:
            try:
                target = await loaded_published_target(
                    bot, state["guild_id"], document, coordinates, int(ctx.interaction.application_id)
                )
            except ValueError as exc:
                notice = str(exc)
                target = None
            if destination_channel_id is None:
                destination_channel_id = coordinates["channel_id"]
    draft_state = dict(
        state, view="document", document=document.key, sections=sections,
        revision=revision, media=media, target=target,
        destination_channel_id=destination_channel_id, selected_media_slot=None,
        destination_baseline=destination_row,
    )
    if document.key in _BOUND_PANELS and target is None and notice is None:
        notice = ("No active public Apply post is bound. Complete ticket setup before updating the post."
                  if document.key == "apply" else
                  "No Warrior Desk post is bound. Post it from Ticket settings before updating the post.")
    for name in ("shared_targets", "shared_target_errors", "shared_update_started", "shared_update_results"):
        draft_state.pop(name, None)
    if document.key == "family-rules":
        targets, errors = await shared_rule_targets(mongo, bot, state["guild_id"], int(ctx.interaction.application_id))
        draft_state.update(shared_targets=targets, shared_target_errors=errors)
    draft_state["saved_snapshot"] = draft_snapshot(draft_state)
    return panel(await new_draft(mongo, draft_state), notice)


@register_action("content_load_published", preload_state=False)
@lightbulb.di.with_di
async def load_published_copy(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if not problem:
        problem = layout_notice(state.get("document"), state.get("sections")) if layout_for(state.get("document"), state.get("sections")) == "ambiguous" else None
    if problem:
        return error_panel(problem)
    if not target_matches_destination(state) or state.get("document") not in DOCUMENTS:
        return panel(state, "The published post is unavailable in this posting channel.")
    document = DOCUMENTS[state["document"]]
    target = state["target"]
    sections = list(target.get("editable_original", target["original"]))
    if document.key in BOXES:
        sections = merge_public(document.key, state["sections"], sections)
    media = dict(zip((slot for slot, _ in media_slots(document)), target["original_media"], strict=True))
    try:
        await validate_template(document, sections, media=media)
    except ValueError as exc:
        return panel(state, str(exc))
    # Keep the original saved snapshot so loading live text remains an unsaved
    # draft until the editor explicitly saves it.
    draft = await new_draft(mongo, dict(state, sections=sections, media=media))
    return panel(draft, "Published text and images loaded into this draft. Save the template to keep them for future edits.")


@register_action("content_destination", preload_state=False)
@lightbulb.di.with_di
async def choose_destination(
    ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_,
):
    state, problem = await load(ctx, mongo, action_id)
    if not problem:
        problem = layout_notice(state.get("document"), state.get("sections")) if layout_for(state.get("document"), state.get("sections")) == "ambiguous" else None
    if problem:
        return error_panel(problem)
    document_key = state.get("document")
    values = getattr(ctx.interaction, "values", ()) or ()
    if document_key in {*_BOUND_PANELS, "rite-of-passage", "family-rules"}:
        return panel(state, "Warrior Desk uses its saved channel. Use Ticket settings → Warrior Desk." if document_key == "warrior_desk" else "This ticket panel does not support a posting channel. Use ticket setup for the public Apply post.")
    if document_key not in DOCUMENTS or len(values) != 1:
        return panel(state, "Select one text or announcement channel.")
    try:
        channel_id = int(values[0])
        if channel_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return panel(state, "Select one text or announcement channel.")
    try:
        channel = await bot.rest.fetch_channel(channel_id)
    except (hikari.HTTPError, OSError):
        return panel(state, "I cannot read that channel. Select another channel.")
    if (int(getattr(channel, "guild_id", 0)) != state["guild_id"]
            or getattr(channel, "type", None) not in _DESTINATION_TYPES):
        return panel(state, "Select a text or announcement channel in this server.")
    if "destination_baseline" not in state:
        return panel(state, "This edit expired. Select the message again before changing its channel.")
    key = destination_key(state["guild_id"], document_key)
    baseline = state["destination_baseline"]
    data = {
        "guild_id": state["guild_id"], "document": document_key,
        "channel_id": channel_id, "updated_by": int(ctx.user.id),
        "updated_at": utcnow(),
    }
    try:
        if baseline is None:
            await mongo.bot_config.insert_one(dict(data, _id=key))
        else:
            expected = baseline.get("channel_id", {"$exists": False})
            result = await mongo.bot_config.update_one(
                {"_id": key, "channel_id": expected}, {"$set": data},
            )
            if not result.matched_count:
                return panel(state, "The posting channel changed in Discord or the dashboard. Select the message again to review it.")
    except DuplicateKeyError:
        return panel(state, "The posting channel changed in Discord or the dashboard. Select the message again to review it.")
    draft = await new_draft(mongo, dict(state, destination_channel_id=channel_id,
                                      destination_baseline=dict(data, _id=key)))
    return panel(draft, f"Posting channel saved as <#{channel_id}> for {DOCUMENTS[document_key].label}.")


@register_action("content_send", preload_state=False)
@lightbulb.di.with_di
async def send_to_channel(
    ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_,
):
    state, problem = await load(ctx, mongo, action_id)
    if not problem:
        problem = layout_notice(state.get("document"), state.get("sections")) if layout_for(state.get("document"), state.get("sections")) == "ambiguous" else None
    if problem:
        return error_panel(problem)
    document_key = state.get("document")
    if document_key in {*_BOUND_PANELS, "rite-of-passage", "family-rules"}:
        return panel(state, "Use Post Warrior Desk panel in Ticket settings → Warrior Desk." if document_key == "warrior_desk" else "This ticket panel cannot send a new post. Use ticket setup for the public Apply post.")
    channel_id = state.get("destination_channel_id")
    if not has_posting_channel(document_key) or not isinstance(channel_id, int) or channel_id <= 0:
        return panel(state, "Select and save a posting channel before sending.")
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
        return panel(state, issue or "Check the acknowledgement role and the next onboarding channel.")
    try:
        rendered = await render(
            DOCUMENTS[document_key], state["sections"], media=state.get("media"),
            action_id=uuid.uuid4().hex, mongo=mongo, guild_id=state["guild_id"],
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
        return panel(state, "You already used this Send button. Reopen the document to send another post.")
    try:
        message = await bot.rest.create_message(
            channel=channel_id, components=rendered, **NO_MENTIONS,
        )
    except (hikari.HTTPError, OSError):
        draft = await new_draft(mongo, state)
        return panel(draft, "I could not confirm the post. Check the channel before you send again. This draft is still available.")
    try:
        await remember_published(mongo, state["guild_id"], document_key, channel_id, int(message.id), int(ctx.user.id))
        remembered = True
    except Exception:
        # The post exists. Never offer an automatic second send when persistence
        # fails; the administrator can reconnect using its link.
        remembered = False
    target = {
        "channel_id": channel_id, "message_id": int(message.id),
        "original": [node.content for node in text_nodes(rendered)], "original_media": media_snapshot(rendered),
        "editable_original": [node.content for node in editable_text_nodes(DOCUMENTS[document_key], rendered)],
        "tracked": remembered,
    }
    draft = await new_draft(mongo, dict(state, target=target))
    link = f"https://discord.com/channels/{state['guild_id']}/{channel_id}/{message.id}"
    notice = (f"{DOCUMENTS[document_key].label} sent to <#{channel_id}>: [View posted message]({link})."
              if remembered else
              f"{DOCUMENTS[document_key].label} sent to <#{channel_id}>: [View posted message]({link}). I could not save its ID. To update this post later, reopen it with this message link.")
    if not remembered and document_key == "wu-faq":
        notice = (f"{DOCUMENTS[document_key].label} sent: [View posted message]({link}). I could not save its published-post reference. "
                  "Do not send again. Keep this editor and the link; this draft can still update that exact post.")
    return panel(draft, notice)


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
        return [hikari.impl.ContainerComponentBuilder(accent_color=WU_GOLD, components=[
            hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", DOCUMENTS[state["document"]].label)),
            hikari.impl.TextDisplayComponentBuilder(content="## Return to Recruit Gauntlet?"),
            hikari.impl.TextDisplayComponentBuilder(content="If you reopen this document, you start a new draft. Unsaved edits are not kept. To keep them, save the template first."),
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
    state, problem = await load(ctx, mongo, action_id)
    values = getattr(ctx.interaction, "values", ())
    if problem:
        await edit_modal_source(ctx, error_panel(problem)); return
    document = DOCUMENTS.get(state.get("document"))
    readonly_notice = layout_notice(document.key, state["sections"]) if document and layout_for(document.key, state["sections"]) == "ambiguous" else None
    if readonly_notice:
        if len(values) != 1 or not values[0].isdigit():
            await edit_modal_source(ctx, panel(state, readonly_notice)); return
        selected = int(values[0])
        if not 0 <= selected < min(25, len(state["sections"])):
            await edit_modal_source(ctx, panel(state, readonly_notice)); return
        indexes = range(selected, len(state["sections"])) if selected == 24 else (selected,)
        text = "\n\n".join(f"Raw saved field {i + 1}\n{state['sections'][i]}" for i in indexes)
        draft = await new_draft(mongo, dict(state, raw_view_text=text, raw_view_page=0))
        await edit_modal_source(ctx, raw_view_panel(draft))
        return
    groups = editable_groups(document, state["sections"]) if document else ()
    if values == ("images",) or values == ["images"]:
        if not document or not media_slots(document):
            await edit_modal_source(ctx, panel(state, "This document has no editable images.")); return
        draft = await new_draft(mongo, dict(state, selected_box="Images"))
        await edit_modal_source(ctx, panel(draft, "Select an image to edit.")); return
    if len(values) != 1 or not values[0].isdigit() or int(values[0]) >= len(groups):
        await edit_modal_source(ctx, panel(state, "Select one editable section.")); return
    title, fields = groups[int(values[0])]
    if not fields and title == "Family Rules":
        rules, _, _ = await template_for(mongo, DOCUMENTS["family-rules"], state["guild_id"])
        row = hikari.impl.MessageActionRowBuilder()
        row.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_rules_editor:{state['_id']}", label="Edit shared Family Rules")
        row.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_document:{state['_id']}", label="Back to document")
        await edit_modal_source(ctx, [hikari.impl.ContainerComponentBuilder(accent_color=None, components=[
            *[hikari.impl.TextDisplayComponentBuilder(content=value) for value in rules],
            hikari.impl.TextDisplayComponentBuilder(content="Shared by WU FAQ and About Us. Save this draft before opening the shared editor."), row])])
        return
    edit_sections = save_sections(document.key, state["sections"]) if document.key in BOXES else state["sections"]
    try:
        modal_rows = [
            hikari.impl.ModalActionRowBuilder().add_text_input(
                f"content_{position}", label, value=modal_field_value(edit_sections[index], part),
                required=True, min_length=1, max_length=4000,
                style=hikari.TextInputStyle.SHORT if label == "Heading" else hikari.TextInputStyle.PARAGRAPH,
            )
            for position, (index, label, part) in enumerate(fields)
        ]
    except ValueError as exc:
        await edit_modal_source(ctx, panel(state, str(exc))); return
    draft = await new_draft(mongo, dict(state, sections=edit_sections, selected_fields=[list(field) for field in fields], selected_box=title, selected_media_slot=None))
    await ctx.respond_with_modal(title=title[:45], custom_id=f"content_submit:{draft['_id']}", components=modal_rows)


def raw_view_panel(state):
    """Read-only paging keeps every original byte under Discord's text budget."""
    text = state["raw_view_text"]
    page = state.get("raw_view_page", 0)
    pages = max(1, (len(text) + 2999) // 3000)
    page = max(0, min(page, pages - 1))
    buttons = hikari.impl.MessageActionRowBuilder()
    if page:
        buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_raw_previous:{state['_id']}", label="Previous")
    if page + 1 < pages:
        buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_raw_next:{state['_id']}", label="Next")
    buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_document:{state['_id']}", label="Back to document")
    return [hikari.impl.ContainerComponentBuilder(components=[
        hikari.impl.TextDisplayComponentBuilder(content=layout_notice(state["document"], state["sections"])),
        hikari.impl.TextDisplayComponentBuilder(content=f"Read-only saved values · {page + 1}/{pages}"),
        hikari.impl.TextDisplayComponentBuilder(content=text[page * 3000:(page + 1) * 3000] or "(empty)"), buttons])]


async def raw_view_page(ctx, action_id, mongo, step):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if layout_for(state.get("document"), state.get("sections")) != "ambiguous" or not isinstance(state.get("raw_view_text"), str):
        return panel(state, "Select saved values to view.")
    pages = max(1, (len(state["raw_view_text"]) + 2999) // 3000)
    draft = await new_draft(mongo, dict(state, raw_view_page=max(0, min(pages - 1, state.get("raw_view_page", 0) + step))))
    return raw_view_panel(draft)


@register_action("content_raw_next", preload_state=False)
@lightbulb.di.with_di
async def raw_view_next(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    return await raw_view_page(ctx, action_id, mongo, 1)


@register_action("content_raw_previous", preload_state=False)
@lightbulb.di.with_di
async def raw_view_previous(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    return await raw_view_page(ctx, action_id, mongo, -1)


@register_action("content_rules_editor", preload_state=False)
@lightbulb.di.with_di
async def open_shared_rules(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                            bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if has_unsaved_edits(state):
        return panel(state, "Save this draft before opening the shared Family Rules editor.")
    rules, media, revision = await template_for(mongo, DOCUMENTS["family-rules"], state["guild_id"])
    targets, errors = await shared_rule_targets(mongo, bot, state["guild_id"], int(ctx.interaction.application_id))
    draft = dict(state, document="family-rules", sections=rules, media=media, revision=revision,
                 target=None, destination_channel_id=None, shared_targets=targets, shared_target_errors=errors)
    draft["saved_snapshot"] = draft_snapshot(draft)
    return panel(await new_draft(mongo, draft))


@register_action("content_media", preload_state=False)
@lightbulb.di.with_di
async def choose_media(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if not problem:
        problem = layout_notice(state.get("document"), state.get("sections")) if layout_for(state.get("document"), state.get("sections")) == "ambiguous" else None
    if problem:
        return error_panel(problem)
    values = getattr(ctx.interaction, "values", ())
    document = DOCUMENTS.get(state.get("document"))
    if not document or len(values) != 1 or values[0] not in {slot for slot, _label in media_slots(document)}:
        return panel(state, "Select one image slot.")
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
    if not problem:
        problem = layout_notice(state.get("document"), state.get("sections")) if layout_for(state.get("document"), state.get("sections")) == "ambiguous" else None
    if problem:
        await edit_modal_source(ctx, error_panel(problem)); return
    document = DOCUMENTS.get(state.get("document"))
    slot = state.get("selected_media_slot")
    if not document or slot not in {name for name, _label in media_slots(document)}:
        await edit_modal_source(ctx, panel(state, "Select an image slot before uploading.")); return
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
    if not problem:
        problem = layout_notice(state.get("document"), state.get("sections")) if layout_for(state.get("document"), state.get("sections")) == "ambiguous" else None
    if problem:
        await interaction.edit_initial_response(components=error_panel(problem), **NO_MENTIONS); return
    document = DOCUMENTS.get(state.get("document"))
    slot = state.get("selected_media_slot")
    if not document or slot not in {name for name, _label in media_slots(document)}:
        await interaction.edit_initial_response(
            components=panel(state, "Select an image slot before uploading."), **NO_MENTIONS
        ); return
    attachment = _modal_attachment(payload) if payload is not None else None
    if attachment is None:
        await interaction.edit_initial_response(
            components=panel(state, "You did not send a valid file. Your draft is unchanged."),
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
            components=panel(state, "I could not download that file. Your draft is unchanged. Try again in a few minutes."),
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
        components=panel(draft, f"{label} uploaded to this draft. Preview, save, or update the published post."),
        **NO_MENTIONS,
    )


@register_action("content_reset_media", preload_state=False)
@lightbulb.di.with_di
async def reset_media(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if not problem:
        problem = layout_notice(state.get("document"), state.get("sections")) if layout_for(state.get("document"), state.get("sections")) == "ambiguous" else None
    if problem:
        return error_panel(problem)
    document = DOCUMENTS.get(state.get("document"))
    slot = state.get("selected_media_slot")
    if not document or slot not in {name for name, _label in media_slots(document)}:
        return panel(state, "Select an image slot before resetting it.")
    media = normal_media(document, state.get("media"))
    media.pop(slot, None)
    label = dict(media_slots(document))[slot]
    return panel(
        await new_draft(mongo, dict(state, media=media, selected_media_slot=slot)),
        f"Original artwork restored for {label}. Use Save template to keep this change, or Update published post to apply it to the published post.",
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
    if layout_for(state["document"], state["sections"]) == "ambiguous":
        await interaction.edit_initial_response(components=panel(state), **NO_MENTIONS); return
    fields = state.get("selected_fields")
    if not fields and isinstance(state.get("selected_block"), int):
        # Modals opened before the rollout may still be submitted.
        fields = [[state["selected_block"], "Body", "full"]]
        field_ids = ["content"]
    else:
        field_ids = [f"content_{position}" for position in range(len(fields or ())) ]
    if not fields or len(fields) > 5:
        await interaction.edit_initial_response(components=panel(state, "Select a section before submitting an edit."), **NO_MENTIONS); return
    submitted = {item.custom_id: str(item.value) for row in interaction.components for item in row}
    if set(field_ids) - submitted.keys() or any(not submitted[key].strip() for key in field_ids):
        await interaction.edit_initial_response(components=panel(state, "Complete all fields before saving this section."), **NO_MENTIONS); return
    sections = list(state["sections"])
    replacements = {}
    for field_id, (index, _label, part) in zip(field_ids, fields, strict=True):
        if not isinstance(index, int) or index < 0 or index >= len(sections) or part not in {"full", "title", "body"}:
            await interaction.edit_initial_response(components=panel(state, "This section is no longer valid. Reopen the editor."), **NO_MENTIONS); return
        replacements.setdefault(index, {})[part] = submitted[field_id]
    for index, parts in replacements.items():
        if "full" in parts:
            sections[index] = parts["full"]
        else:
            try:
                title = parts.get("title", modal_field_value(sections[index], "title"))
                body = parts.get("body", modal_field_value(sections[index], "body"))
            except ValueError as exc:
                await interaction.edit_initial_response(components=panel(state, str(exc)), **NO_MENTIONS); return
            sections[index] = f"{title}\n{body}"
    try:
        await validate_template(DOCUMENTS[state["document"]], sections, media=state.get("media"))
    except ValueError as exc:
        await interaction.edit_initial_response(components=panel(state, str(exc)), **NO_MENTIONS); return
    draft = await new_draft(mongo, dict(state, sections=sections))
    if draft.get("document") != "rite-of-passage" and target_matches_destination(draft):
        await interaction.edit_initial_response(components=update_prompt(draft), **NO_MENTIONS)
    else:
        await interaction.edit_initial_response(components=panel(draft, "Section updated."), **NO_MENTIONS)


def update_prompt(state):
    target = state["target"]
    link = f"https://discord.com/channels/{state['guild_id']}/{target['channel_id']}/{target['message_id']}"
    buttons = hikari.impl.MessageActionRowBuilder()
    buttons.add_interactive_button(hikari.ButtonStyle.SUCCESS, f"content_save_publish:{state['_id']}", label="Save and update post", emoji=button_emoji("Confirm"))
    buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"content_back_document:{state['_id']}", label="Keep editing", emoji=button_emoji("Keep editing"))
    return [hikari.impl.ContainerComponentBuilder(accent_color=WU_GOLD, components=[
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", DOCUMENTS[state["document"]].label)),
        hikari.impl.TextDisplayComponentBuilder(content="## Section updated"),
        hikari.impl.TextDisplayComponentBuilder(content=f"Save this draft as the template and apply it to the [published post]({link})?"),
        buttons,
    ])]


async def _save(ctx, state, mongo, *, dashboard=False):
    require_writable(state["document"], state["sections"])
    if dashboard:return await _save_untracked(ctx,state,mongo)
    from utils.dashboard_native_history import save_message
    async def writer(*args):return await _save_untracked(ctx,state,mongo)
    return await save_message(writer,'gauntlet',mongo,state['guild_id'],state['document'],int(ctx.user.id))


async def _save_untracked(ctx, state, mongo):
    require_writable(state["document"], state["sections"])
    key = f"content:{state['document']}:{state['guild_id']}"; revision = state["revision"]
    document = DOCUMENTS[state["document"]]
    if document.key in BOXES:
        state = dict(state, sections=validate_sections(document.key, save_sections(document.key, state["sections"])))
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
async def save(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
               bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if not state.get("document"):
        return panel(state, "Select a document before saving.")
    try:
        await validate_template(DOCUMENTS[state["document"]], state["sections"], media=state.get("media"))
    except ValueError as exc:
        return panel(state, str(exc))
    if layout_for(state["document"], state["sections"]) == "ambiguous":
        return panel(state, layout_notice(state["document"], state["sections"]))
    if state["document"] in BOXES:
        state = dict(state, sections=save_sections(state["document"], state["sections"]))
    if not await _save(ctx, state, mongo):
        return panel(state, "The template changed. Reopen the dashboard. If you save now, you replace the new template.")
    saved_state = dict(state, revision=state["revision"] + 1)
    if state["document"] == "family-rules":
        targets, errors = await shared_rule_targets(mongo, bot, state["guild_id"], int(ctx.interaction.application_id))
        saved_state.update(shared_targets=targets, shared_target_errors=errors)
        saved_state.pop("shared_update_started", None)
        saved_state.pop("shared_update_results", None)
    saved_state["saved_snapshot"] = draft_snapshot(saved_state)
    return panel(await new_draft(mongo, saved_state), "Template saved for future posts in this server.")


@register_action("content_preview", preload_state=False)
@lightbulb.di.with_di
async def preview(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if not state.get("document"):
        return panel(state, "Select a document before previewing.")
    try:
        return await preview_panel(state, mongo)
    except ValueError as exc:
        return panel(state, str(exc))


@register_action("content_save_publish", preload_state=False)
@lightbulb.di.with_di
async def save_and_publish(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if is_template_only(state.get("document")):
        return panel(state, ("Rite of Passage is private. Save the template to update future choice panels."
                             if state.get("document") == "rite-of-passage" else
                             "Family Rules is shared. Save it, then review its linked posts."))
    if not state.get("document") or not target_matches_destination(state):
        return panel(state, "The published post is unavailable in this posting channel. Your draft is unchanged.")
    if state["document"] in _BOUND_PANELS:
        source = await published_for(mongo, state["guild_id"], state["document"])
        target = state.get("target") or {}
        if not source or any(target.get(key) != value for key, value in source.items()):
            return panel(state, "The Warrior Desk post changed or is missing. Use Post Warrior Desk panel in Ticket settings, then reopen this editor. Your draft is unchanged." if state["document"] == "warrior_desk" else "The public Apply post changed or is missing. Complete ticket setup, then reopen Recruit Gauntlet. Your draft is unchanged.")
    try:
        await validate_template(DOCUMENTS[state["document"]], state["sections"], media=state.get("media"))
    except ValueError as exc:
        return panel(state, str(exc))
    if layout_for(state["document"], state["sections"]) == "ambiguous":
        return panel(state, layout_notice(state["document"], state["sections"]))
    if state["document"] in BOXES:
        state = dict(state, sections=save_sections(state["document"], state["sections"]))
    if not await _save(ctx, state, mongo):
        return panel(state, "The template changed. Reopen the dashboard. The post was not updated.")
    saved_state = dict(state, revision=state["revision"] + 1)
    saved_state["saved_snapshot"] = draft_snapshot(saved_state)
    return await publish_state(ctx, saved_state, mongo, bot, saved_template=True)


@register_action("content_publish", preload_state=False)
@lightbulb.di.with_di
async def publish(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if is_template_only(state.get("document")):
        return panel(state, ("Rite of Passage is private. Save the template to update future choice panels."
                             if state.get("document") == "rite-of-passage" else
                             "Family Rules is shared. Save it, then review its linked posts."))
    if not state.get("target") or not state.get("document"):
        return panel(state, "Select a published post before updating it.")
    return await publish_state(ctx, state, mongo, bot)


async def publish_state(ctx, state, mongo, bot, *, saved_template=False, return_outcome=False):
    def answer(message, *, ok=False, uncertain=False, updated_state=None):
        if return_outcome:
            return {"ok": ok, "uncertain": uncertain, "message": message}
        return panel(updated_state or state, message)

    if is_template_only(state.get("document")):
        return answer("Rite of Passage is private. Save the template to update future choice panels."
                      if state.get("document") == "rite-of-passage" else
                      "Family Rules is shared. Save it, then review its linked posts.")
    if layout_for(state.get("document"), state.get("sections")) == "ambiguous":
        return answer(layout_notice(state["document"], state["sections"]))
    target = state.get("target")
    if state.get("document") in _BOUND_PANELS:
        authoritative = await published_for(mongo, state["guild_id"], state["document"])
        if not authoritative or not target or any(target.get(key) != value for key, value in authoritative.items()):
            return answer(
                "The public Apply post changed or is missing. Complete ticket setup, then reopen Recruit Gauntlet. Your draft is unchanged."
                if state.get("document") == "apply" else
                "The Warrior Desk post changed or is missing. Use Post Warrior Desk panel in Ticket settings, then reopen this editor. Your draft is unchanged."
            )
    if not target_matches_destination(state):
        return answer("The posting channel is not the channel of this post. Select the original channel, then update the post.")
    document = DOCUMENTS[state["document"]]
    if document.key in _BOUND_PANELS or target.get("tracked"):
        current = await published_for(mongo, state["guild_id"], document.key)
        if not current or any(current.get(key) != target.get(key) for key in ("channel_id", "message_id")):
            return answer("The linked published post changed. Reopen the editor to review the current post.")
    token = uuid.uuid4().hex
    lease_key = f"content_publish:{target['channel_id']}:{target['message_id']}"
    try:
        await mongo.bot_config.update_one(
            {"_id": lease_key, "until": {"$lte": utcnow()}},
            {"$set": {"until": utcnow() + timedelta(minutes=1), "token": token}}, upsert=True,
        )
    except DuplicateKeyError:
        return answer("Another update is in progress. Try again in a few minutes.")
    attempted_edit = False
    try:
        channel = await bot.rest.fetch_channel(target["channel_id"])
        if int(getattr(channel, "guild_id", 0)) != state["guild_id"]:
            raise ValueError("The published post is not in this server.")
        message = await bot.rest.fetch_message(target["channel_id"], target["message_id"])
        if (int(message.author.id) != int(ctx.interaction.application_id)
                or not await supported_post_shape(document, message.components)
                or [node.content for node in text_nodes(message.components)] != target["original"]
                or target.get("original_media") is not None and media_snapshot(message.components) != target["original_media"]):
            raise ValueError("That post changed since this draft opened. Reopen the dashboard to review it.")
        acknowledgement = acknowledgement_id(message.components, document)
        if document.acknowledgement and not acknowledgement:
            raise ValueError("That is not the selected content type.")
        if document.key in _BOUND_PANELS or target.get("tracked"):
            current = await published_for(mongo, state["guild_id"], document.key)
            if current != {"channel_id": target["channel_id"], "message_id": target["message_id"]}:
                raise ValueError("The active linked post changed. Reopen the editor before updating it.")
        rendered = await render(
            document, state["sections"], media=state.get("media"), action_id=acknowledgement or "public",
            mongo=mongo, guild_id=state["guild_id"],
        )
        if "_rules_revision" in state:
            rules = await mongo.bot_config.find_one({"_id": f"content:family-rules:{state['guild_id']}"})
            if not rules or rules.get("revision") != state["_rules_revision"]:
                raise ValueError("Family Rules changed. Reopen the editor before updating this post.")
        referenced_ids = {attachment_id for url in media_snapshot(rendered)
                          if (attachment_id := discord_attachment_id(url)) is not None}
        attachments = [attachment for attachment in getattr(message, "attachments", ())
                       if str(attachment.id) in referenced_ids]
        attempted_edit = True
        updated_message = await bot.rest.edit_message(
            target["channel_id"], target["message_id"], components=rendered,
            attachments=attachments, **NO_MENTIONS,
        )
    except (ValueError, hikari.HTTPError, OSError) as error:
        uncertain = attempted_edit and not isinstance(error, ValueError)
        if uncertain:
            reason = "I could not confirm the update. Check this post before trying again; it will not retry automatically."
        else:
            reason = str(error) if isinstance(error, ValueError) else "The bot cannot read or update that message."
            reason += " The template was saved, but the post is unchanged." if saved_template else " Your draft is still available."
        return answer(reason, uncertain=uncertain)
    finally:
        await mongo.bot_config.delete_one({"_id": lease_key, "token": token})
    link = f"https://discord.com/channels/{state['guild_id']}/{target['channel_id']}/{target['message_id']}"
    notice = f"{document.label}: " + ("Template saved and published post updated." if saved_template else "Published post updated.") + f" [View posted message]({link})."
    if return_outcome:
        return answer(notice, ok=True)
    public_components = getattr(updated_message, "components", ()) or rendered
    updated_state = await new_draft(mongo, dict(state, target=dict(
        target, original=[node.content for node in text_nodes(public_components)],
        editable_original=[node.content for node in editable_text_nodes(document, public_components)],
        original_media=media_snapshot(public_components),
    )))
    return answer(notice, ok=True, updated_state=updated_state)


@register_action("content_rules_publish", preload_state=False)
@lightbulb.di.with_di
async def publish_shared_rules(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                               bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    state, problem = await load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if state.get("document") != "family-rules" or has_unsaved_edits(state):
        return panel(state, "Save Family Rules before updating linked posts.")
    rules = await mongo.bot_config.find_one({"_id": f"content:family-rules:{state['guild_id']}"})
    if (not rules or rules.get("revision") != state.get("revision")
            or rules.get("sections") != state.get("sections")):
        return panel(state, "Family Rules changed. Reopen the editor to review them before updating any post.")
    if not state.get("shared_targets"):
        return panel(state, "No linked published posts are available. No new message will be sent.")
    claim = await update_state(mongo, {
        "_id": state["_id"], "user_id": state["user_id"], "guild_id": state["guild_id"],
        "shared_update_started": {"$ne": True},
    }, {"$set": {"shared_update_started": True}})
    if claim.matched_count != 1:
        return panel(state, "This update was already started. Check the posts; it will not retry automatically.")
    results = {}
    for key in ("wu-faq", "about-us"):
        target = state["shared_targets"].get(key)
        if not target:
            continue
        # Persist an uncertain state before delivery. A restart must not repeat
        # an edit whose Discord acknowledgement may have been lost.
        results[key] = {"ok": False, "uncertain": True, "message": "Update started; check this post before another attempt."}
        try:
            await update_state(mongo, state["_id"], {"$set": {"shared_update_results": results}})
        except (PyMongoError, OSError):
            results[key] = {"ok": False, "uncertain": False, "message": "Result storage is unavailable; this edit was not attempted."}
            return shared_results_unavailable(state, results)
        try:
            current = await published_for(mongo, state["guild_id"], key)
            if current != {"channel_id": target["channel_id"], "message_id": target["message_id"]}:
                result = {"ok": False, "uncertain": False, "message": "The linked post changed. Reopen the editor to review it."}
            else:
                child = dict(state, document=key, sections=list(target["editable_original"]),
                             media=dict(zip((slot for slot, _ in media_slots(DOCUMENTS[key])), target["original_media"], strict=True)),
                             target=target, destination_channel_id=target["channel_id"], _rules_revision=state["revision"])
                result = await publish_state(ctx, child, mongo, bot, return_outcome=True)
        except (PyMongoError, OSError):
            result = {"ok": False, "uncertain": True, "message": "I could not confirm this update. Check the post; it will not retry automatically."}
        results[key] = result
        try:
            await update_state(mongo, state["_id"], {"$set": {"shared_update_results": results}})
        except (PyMongoError, OSError):
            return shared_results_unavailable(state, results)
    updated = await new_draft(mongo, dict(state, shared_update_started=True, shared_update_results=results))
    return panel(updated, "Family Rules remain saved. Each linked-post result is shown separately; no new message was sent.")


def shared_results_unavailable(state, results):
    for key in state.get("shared_targets", {}):
        results.setdefault(key, {"ok": False, "uncertain": False,
                                 "message": "Not attempted because result storage became unavailable."})
    return panel(dict(state, shared_update_started=True, shared_update_results=results),
                 "The results below could not all be persisted. No further edits were attempted. "
                 "Keep this editor and check the posts before reopening; there is no automatic retry.")

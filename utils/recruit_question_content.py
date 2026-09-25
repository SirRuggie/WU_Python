"""Guild-scoped editable recruitment messages across all four question groups."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

import hikari
from hikari.impl import (
    ContainerComponentBuilder as Container, InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow, TextSelectMenuBuilder as TextSelectMenu,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem, SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)
from pymongo.errors import DuplicateKeyError
from utils.constants import GOLDENROD_ACCENT
from utils.emoji import emojis

VARIANTS = (
    "attack_strategies", "discord_basic_skills", "family_codes",
    "leaders_checking_you_out", "welcome_to_family", "warriors_united_cwl",
)
VARIANT_LABELS = {
    "attack_strategies": "Attack Strategy Breakdown",
    "discord_basic_skills": "Discord Basics Check",
    "family_codes": "Keeping it in the Family",
    "leaders_checking_you_out": "Application Under Review",
    "welcome_to_family": "Welcome to the Family",
    "warriors_united_cwl": "Warriors United CWL",
}
BLOCK_LABELS = {variant: ("Heading", "Question message", "Request credit") for variant in VARIANTS}
VALID_EMOJI_CODES = ("⚔️⚔️⚔️", "⚔️🍻⚔️", "⚔️☠️⚔️")
FAMILY_CODES_DISPLAY = "\n".join(f"**{code}**" for code in VALID_EMOJI_CODES)
_DEFAULT_FOOTERS = {
    "attack_strategies": "assets/Gold_Footer.png", "discord_basic_skills": None,
    "family_codes": "assets/Gold_Footer.png", "leaders_checking_you_out": "assets/Red_Footer.png",
    "welcome_to_family": "assets/Gold_Footer.png", "warriors_united_cwl": "assets/recruit/static/CW_Leagues.png",
}
_DEFAULT_SECTIONS = {
    "attack_strategies": (
        "## ⚔️ **Attack Strategy Breakdown** · {recruit}",
        "Help us understand your go-to attack strategies!\n\n"
        f"{emojis.red_arrow_right} **Main Village strategies**\n"
        f"{emojis.blank}{emojis.white_arrow_right} _e.g. Hybrid, Queen Charge w/ Hydra, Lalo_\n\n"
        f"{emojis.red_arrow_right} **Clan Capital Attack Strategies**\n"
        f"{emojis.blank}{emojis.white_arrow_right} _e.g. Super Miners w/ Freeze_\n\n"
        f"{emojis.red_arrow_right} **Highest Clan Capital Hall level you’ve attacked**\n"
        f"{emojis.blank}{emojis.white_arrow_right} _e.g. CH 8, CH 9, etc.\n\n_"
        "*Your detailed breakdown helps us match you to the perfect clan!*",
        "-# Requested by {recruiter}",
    ),
    "discord_basic_skills": (
        "## 🎓 **Discord Basics Check** · {recruit}",
        "We utilize three main methods to communicate within the Warriors United Server:\n\n"
        "1️⃣ A comment\n2️⃣ A ping within that comment to a specific person/role.\n"
        "3️⃣ An emoji reaction to a comment.\n\n"
        "**You've proven #1. Now prove to us you can do #2 and #3...👍🏼**\n\n"
        "**Click/touch the🛡below to begin.**",
        "-# Requested by {recruiter}",
    ),
    "family_codes": (
        "## 🏰 **Keeping it in the Family** · {recruit}",
        "Warriors United family members may move around the family for donations, "
        "a Friendly Challenge with an available member, helping with Clan Games, "
        "or participation in a Family Event. When sending a Clan Request use one "
        "of these three emoji combos as your request message....\n\n"
        "{family_codes}\n\n"
        "**DO NOT** use the default join message... I'd like to join your clan.\n\n"
        "Acknowledge you understand this by sending one of the above three codes "
        "down below in chat. Just as you would if you were going to request to join!",
        "-# Requested by {recruiter}",
    ),
    "leaders_checking_you_out": (
        "## 🔍 **Application Under Review** · {recruit}",
        "Thank you for completing your application! 🎉\n\n"
        "Our leadership team is now reviewing your responses to find the perfect clan match. "
        "Please sit tight, we’ll be with you shortly! ⏳\n\n"
        "We truly appreciate your interest in Warrior's United and can’t wait to welcome you aboard!",
        "-# Requested by {recruiter}",
    ),
    "welcome_to_family": (
        "## 🛡️ **Welcome to the Family!** · {recruit}",
        "Welcome to the Family!\n\n"
        "You are all good to go {recruit}! Several channels will be available to you "
        "on the Main Server shortly. You will receive a ping in the "
        "<#1128966424082255872> and all the appropriate server roles you will need: "
        "as well as a link to assigned Clan.\n\n"
        "**Once you receive the aforementioned ping, __ping__ your Recruiter to acknowledge you're there.**\n\n"
        "They will in turn kick off a server walkthrough guiding you to important "
        "channels related to your day to day play.\n\n"
        "# Welcome to the Family...here's your 🛡️! Let's get you into Battle!",
        "-# Requested by {recruiter}",
    ),
    "warriors_united_cwl": (
        "## <:warriorcat:947992348971905035> Warriors United CWL <:warriorcat:947992348971905035> · {recruit}",
        "We have 20 Clans that we utilize for CWL; with League's ranging from Master 1 to Gold 1. "
        "All but our High Tactical Clans split up into these clans for CWL.\n\n"
        "Three factors determine the League you'll be placed in:\n\n"
        "1) War activity\n2) War performance\n3) Account strength\n\n"
        "All are relative to the League you'll be placed in.\n\n"
        "If you are new to the family with no war history then your first CWL season "
        "might be lower league for support and/or strength. Nothing personal, your "
        "new so we don't know you yet. *Exceptions may be granted*\n\n"
        "Signing up for CWL is mandatory and is done by way of a Google Form. "
        "Sign-ups go live around Clan Games every month so we can prepare Rosters. "
        "It's a super easy form that takes less then a minute.\n\n"
        "## Any issues with filling out a simple form and moving to another clan for CWL?",
        "-# Requested by {recruiter}",
    ),
}
_SCHEMA_VERSION = 1
_TOKEN = re.compile(r"\{([a-z_]+)\}")
_ALLOWED_TOKENS = frozenset({"recruit", "recruiter", "family_codes"})
_MAX_BLOCK = 2000
_MAX_TOTAL_TEXT = 4000

class TemplateConflict(ValueError):
    """The saved template changed after this editor loaded it."""

def _primary_default_template(variant: str) -> dict:
    if variant not in VARIANTS:
        raise ValueError("Choose an active recruitment question.")
    return {"variant": variant, "sections": list(_DEFAULT_SECTIONS[variant]),
            "footer_url": _DEFAULT_FOOTERS[variant], "accent": int(GOLDENROD_ACCENT), "revision": 0}

def _replace(value: str, values: dict[str, str]) -> str:
    tokens = _TOKEN.findall(value)
    if any(token not in _ALLOWED_TOKENS for token in tokens):
        raise ValueError("Only recruit, recruiter, and family_codes placeholders are supported.")
    remainder = _TOKEN.sub("", value)
    if "{" in remainder or "}" in remainder:
        raise ValueError("Use only supported placeholders inside braces.")
    return _TOKEN.sub(lambda match: values[match.group(1)], value)

def _footer_ok(value: str | None, variant: str) -> bool:
    if value == _DEFAULT_FOOTERS[variant]:
        return True
    if variant == "discord_basic_skills" or not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if "." not in host or host.lower() == "localhost" or host.lower().endswith((".local", ".internal")):
            return False
        if not parsed.path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            return False
    except ValueError:
        return False
    return True

def _primary_validate_template(variant: str, template: dict) -> dict:
    if variant not in VARIANTS or not isinstance(template, dict) or template.get("variant") != variant:
        raise ValueError("Choose an active recruitment question.")
    sections = template.get("sections")
    if not isinstance(sections, list) or len(sections) != len(BLOCK_LABELS[variant]):
        raise ValueError("This question has the wrong number of text blocks.")
    if any(not isinstance(part, str) or not part.strip() for part in sections):
        raise ValueError("Every question text block needs content.")
    if variant == "family_codes" and sections[1].count("{family_codes}") != 1:
        raise ValueError("Keep the {family_codes} placeholder in the family-code question.")
    for index, part in enumerate(sections):
        if "{family_codes}" in part and (variant != "family_codes" or index != 1):
            raise ValueError("The family-code list belongs in its question message.")
    footer_url = template.get("footer_url")
    if not _footer_ok(footer_url, variant):
        raise ValueError("Choose a public HTTPS image URL or the original artwork.")
    accent = template.get("accent")
    if isinstance(accent, bool) or not isinstance(accent, int) or not 0 <= accent <= 0xFFFFFF:
        raise ValueError("Choose a valid six-digit accent color.")
    values = {"recruit": "<@" + "9" * 20 + ">", "recruiter": "<@" + "8" * 20 + ">", "family_codes": FAMILY_CODES_DISPLAY}
    rendered = [_replace(part, values) for part in sections]
    if any(len(part) > _MAX_BLOCK for part in rendered) or sum(map(len, rendered)) > _MAX_TOTAL_TEXT:
        raise ValueError("Question text exceeds Discord's display limit.")
    return {"variant": variant, "sections": list(sections), "footer_url": footer_url, "accent": accent}

def _row_id(guild_id: int, variant: str) -> str:
    if variant not in VARIANTS or isinstance(guild_id, bool) or not isinstance(guild_id, int) or guild_id <= 0:
        raise ValueError("Choose an active recruitment question in a server.")
    return f"recruit_question_template:{guild_id}:{variant}"

async def load_template(mongo, guild_id: int, variant: str) -> dict:
    row = await mongo.bot_config.find_one({"_id": _row_id(guild_id, variant)})
    if row is None:
        return default_template(variant)
    if row.get("schema_version") != _SCHEMA_VERSION or row.get("guild_id") != guild_id or row.get("variant") != variant:
        raise ValueError("Saved recruitment question configuration is invalid. No message was sent.")
    revision = row.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Saved recruitment question revision is invalid. No message was sent.")
    try:
        validated = validate_template(variant, row)
    except ValueError as exc:
        raise ValueError("Saved recruitment question configuration is invalid. No message was sent.") from exc
    return dict(validated, revision=revision)

async def save_template(mongo, guild_id: int, variant: str, template: dict,
                        expected_revision: int, updated_by: int) -> dict:
    key = _row_id(guild_id, variant)
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("Template revision is invalid.")
    validated = validate_template(variant, template)
    row = {**validated, "_id": key, "schema_version": _SCHEMA_VERSION,
           "guild_id": guild_id, "revision": expected_revision + 1, "updated_by": int(updated_by)}
    if expected_revision == 0:
        try:
            await mongo.bot_config.insert_one(row)
        except DuplicateKeyError as exc:
            raise TemplateConflict("This question changed. Reopen it before saving.") from exc
    else:
        result = await mongo.bot_config.update_one(
            {"_id": key, "revision": expected_revision},
            {"$set": {name: value for name, value in row.items() if name != "_id"}},
        )
        if result.matched_count != 1:
            raise TemplateConflict("This question changed. Reopen it before saving.")
    return dict(validated, revision=expected_revision + 1)

async def reset_template(mongo, guild_id: int, variant: str,
                         expected_revision: int, updated_by: int) -> dict:
    return await save_template(mongo, guild_id, variant, default_template(variant), expected_revision, updated_by)

def _primary_render_template(template: dict, *, user_id: int, recruiter_id: int, preview: bool = False) -> list:
    variant = template.get("variant")
    validated = validate_template(variant, template)
    values = {"recruit": f"<@{int(user_id)}>", "recruiter": f"<@{int(recruiter_id)}>", "family_codes": FAMILY_CODES_DISPLAY}
    sections = [_replace(part, values) for part in validated["sections"]]
    if any(len(part) > _MAX_BLOCK for part in sections) or sum(map(len, sections)) > _MAX_TOTAL_TEXT:
        raise ValueError("Rendered question exceeds Discord's display limit.")
    parts = [Text(content=sections[0]), Separator(divider=True), Text(content=sections[1])]
    if variant == "discord_basic_skills":
        parts.append(Separator(divider=True))
    else:
        parts.append(Media(items=[MediaItem(media=validated["footer_url"])]))
    parts.append(Text(content=sections[2]))
    components = [Container(accent_color=validated["accent"], components=parts)]
    if variant == "discord_basic_skills":
        components.append(ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY, emoji="🛡",
            custom_id=f"shield_basics:{int(user_id)}:{int(recruiter_id)}", is_disabled=preview,
        )]))
    return components

# The six primary records above remain schema-1 compatible. Additional sender
# groups use the same revisioned collection, with ordered text and image slots.
PRIMARY_VARIANTS = VARIANTS

GROUPS = {
    "primary": {
        "label": "Primary Questions",
        "variants": PRIMARY_VARIANTS,
    },
    "fwa": {
        "label": "FWA Questions",
        "variants": (
            "fwa_clan_chat", "get_war_weight", "heard_of_lazy_cwl",
            "lazy_cwl_explanation", "fwa_leaders_reviewing", "fwa_bases_upon_approval",
        ),
    },
    "explanations": {
        "label": "Explanations",
        "variants": ("what_is_fwa", "fwa_war_plans", "what_is_flexible_fun", "what_is_tactical"),
    },
    "keep_it_moving": {
        "label": "Keep It Moving",
        "variants": ("waiting_response", "circles", "today", "chop_chop"),
    },
}
VARIANTS = tuple(variant for group in GROUPS.values() for variant in group["variants"])
VARIANT_LABELS.update({
    "attack_strategies": "Attack Strategies",
    "discord_basic_skills": "Discord Basic Skills",
    "family_codes": "Family Codes",
    "leaders_checking_you_out": "Leaders Checking You Out",
    "fwa_clan_chat": "FWA Clan Chat",
    "get_war_weight": "Get War Weight",
    "heard_of_lazy_cwl": "Heard of Lazy CWL?",
    "lazy_cwl_explanation": "Lazy CWL Explanation",
    "fwa_leaders_reviewing": "FWA Leaders Reviewing",
    "fwa_bases_upon_approval": "FWA Bases (Upon Approval)",
    "what_is_fwa": "What is FWA",
    "fwa_war_plans": "FWA War Plans",
    "what_is_flexible_fun": "What is Flexible Fun",
    "what_is_tactical": "What is Tactical",
    "waiting_response": "Waiting for Response...",
    "circles": "Going in Circles...",
    "today": "Today Jr...",
    "chop_chop": "Chop Chop...",
})

from utils.recruit_question_native import native_components, native_base_result


def _walk(items):
    for item in items:
        yield item
        yield from _walk(getattr(item, "components", ()))


def _text_nodes(items):
    return [item for item in _walk(items) if item.type == hikari.ComponentType.TEXT_DISPLAY]


def _media_nodes(items):
    return [item for item in _walk(items) if item.type == hikari.ComponentType.MEDIA_GALLERY]


def _media_value(item) -> str:
    value = item.items[0].media
    return str(getattr(value, "url", value))


def _base_example():
    return native_base_result(
        recruit_mention="{recruit}", recruiter_mention="{recruiter}",
        friendly_name="{town_hall}", th_number="{th_number}", base_info="{base_info}",
        base_link="https://example.org/fwa-base",
        war_base_media="https://example.org/war-base.png",
        active_war_base_media="https://example.org/active-base.png",
    )


def _native_for(variant: str, *, action_id: str = "preview"):
    return native_components(
        variant, recruit_mention="{recruit}", recruiter_mention="{recruiter}",
        action_id=action_id,
    )


def _new_default(variant: str) -> dict:
    native = _native_for(variant)
    text = [node.content for node in _text_nodes(native)]
    media = {f"image_{index}": _media_value(node) for index, node in enumerate(_media_nodes(native))}
    if variant == "fwa_bases_upon_approval":
        text += [node.content for node in _text_nodes(_base_example())]
    containers = [node for node in _walk(native) if node.type == hikari.ComponentType.CONTAINER]
    return {
        "variant": variant, "sections": text, "media": media,
        "footer_url": None, "accent": int(containers[0].accent_color), "revision": 0,
    }


def _section_labels(variant: str) -> tuple[str, ...]:
    sections = _new_default(variant)["sections"]
    if variant == "fwa_bases_upon_approval":
        return (
            "Selector heading", "Selector instructions", "Selector request credit",
            "Public recruit mention", "Public town hall heading", "Public war base heading",
            "Public base instructions", "Public request credit",
        )
    return tuple(
        f"Text {index + 1}: {value.splitlines()[0].strip('# *-')[:28]}"[:45]
        for index, value in enumerate(sections)
    )


BLOCK_LABELS.update({variant: _section_labels(variant) for variant in VARIANTS if variant not in PRIMARY_VARIANTS})
MEDIA_LABELS = {
    variant: {slot: f"Image {index + 1}" for index, slot in enumerate(_new_default(variant)["media"])}
    for variant in VARIANTS if variant not in PRIMARY_VARIANTS
}


def default_template(variant: str) -> dict:
    if variant in PRIMARY_VARIANTS:
        return _primary_default_template(variant)
    if variant not in VARIANTS:
        raise ValueError("Choose an active recruitment question.")
    return _new_default(variant)


def _public_media_ok(value: str, original: str) -> bool:
    if value == original:
        return True
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if "." not in host or host.lower() == "localhost" or host.lower().endswith((".local", ".internal")):
            return False
        if not parsed.path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            return False
    except ValueError:
        return False
    return True


def _replace_extended(value: str, replacements: dict[str, str]) -> str:
    tokens = _TOKEN.findall(value)
    if any(token not in replacements for token in tokens):
        raise ValueError("Use only supported recruitment placeholders.")
    if "{" in _TOKEN.sub("", value) or "}" in _TOKEN.sub("", value):
        raise ValueError("Use only supported placeholders inside braces.")
    return _TOKEN.sub(lambda match: replacements[match.group(1)], value)


def validate_template(variant: str, template: dict) -> dict:
    if variant in PRIMARY_VARIANTS:
        return _primary_validate_template(variant, template)
    if variant not in VARIANTS or not isinstance(template, dict) or template.get("variant") != variant:
        raise ValueError("Choose an active recruitment question.")
    sections = template.get("sections")
    if not isinstance(sections, list) or len(sections) != len(BLOCK_LABELS[variant]):
        raise ValueError("This question has the wrong number of text blocks.")
    if any(not isinstance(value, str) or not value.strip() for value in sections):
        raise ValueError("Every question text block needs content.")
    original_media = _new_default(variant)["media"]
    media = template.get("media")
    if not isinstance(media, dict) or set(media) != set(original_media):
        raise ValueError("This question has the wrong number of image slots.")
    if any(not _public_media_ok(media[slot], original) for slot, original in original_media.items()):
        raise ValueError("Choose a public HTTPS image URL or the original artwork.")
    accent = template.get("accent")
    if isinstance(accent, bool) or not isinstance(accent, int) or not 0 <= accent <= 0xFFFFFF:
        raise ValueError("Choose a valid six-digit accent color.")
    if variant == "fwa_bases_upon_approval":
        required = {3: "{recruit}", 4: "{town_hall}", 5: "{th_number}",
                    6: "{base_info}", 7: "{recruiter}"}
        if any(sections[index].count(token) != 1 for index, token in required.items()):
            raise ValueError("Keep the dynamic FWA base placeholders in the public message.")
    example = {"recruit": "<@" + "9" * 20 + ">", "recruiter": "<@" + "8" * 20 + ">",
               "town_hall": "Town Hall 18", "th_number": "18", "base_info": "Example FWA base instructions"}
    rendered = [
        _replace_extended(
            value,
            example if variant == "fwa_bases_upon_approval" and index >= 3
            else {"recruit": example["recruit"], "recruiter": example["recruiter"]},
        )
        for index, value in enumerate(sections)
    ]
    groups = (rendered[:3], rendered[3:]) if variant == "fwa_bases_upon_approval" else (rendered,)
    if any(len(value) > _MAX_BLOCK for value in rendered) or any(sum(map(len, group)) > _MAX_TOTAL_TEXT for group in groups):
        raise ValueError("Question text exceeds Discord's display limit.")
    return {"variant": variant, "sections": list(sections), "media": dict(media),
            "footer_url": None, "accent": accent}


def _replace_native(items, sections: list[str], media: dict, accent: int,
                    replacements: dict[str, str], *, preview: bool) -> list:
    """Rebuild text/media nodes while leaving controls and link buttons intact."""
    from hikari.impl import SectionComponentBuilder as Section
    from hikari.impl import LinkButtonBuilder as Link
    import copy
    text_index = 0
    media_index = 0

    def transform(item):
        nonlocal text_index, media_index
        if isinstance(item, Text):
            value = _replace_extended(sections[text_index], replacements)
            text_index += 1
            return Text(content=value)
        if isinstance(item, Media):
            slot = f"image_{media_index}"
            media_index += 1
            return Media(items=[MediaItem(media=media[slot])])
        if isinstance(item, Container):
            return Container(accent_color=accent, components=[transform(child) for child in item.components])
        if isinstance(item, Section):
            return Section(components=[transform(child) for child in item.components], accessory=copy.deepcopy(item.accessory))
        if isinstance(item, ActionRow):
            children = [copy.deepcopy(child) for child in item.components]
            if preview:
                for child in children:
                    if isinstance(child, (TextSelectMenu, Link)):
                        child.set_is_disabled(True)
            return ActionRow(components=children)
        return copy.deepcopy(item)

    result = [transform(item) for item in items]
    if text_index != len(sections) or media_index != len(media):
        raise RuntimeError("Native recruitment layout changed; update editable slots.")
    return result


def render_template(template: dict, *, user_id: int, recruiter_id: int,
                    preview: bool = False, action_id: str = "preview",
                    stage: str = "selector", town_hall: str | None = None,
                    th_number: str | None = None, base_info: str | None = None,
                    base_link: str | None = None, war_base_media: str | None = None,
                    active_war_base_media: str | None = None) -> list:
    variant = template.get("variant")
    if variant in PRIMARY_VARIANTS:
        return _primary_render_template(template, user_id=user_id, recruiter_id=recruiter_id, preview=preview)
    validated = validate_template(variant, template)
    replacements = {"recruit": f"<@{int(user_id)}>", "recruiter": f"<@{int(recruiter_id)}>"}
    if variant == "fwa_bases_upon_approval" and stage == "result":
        if any(value is None for value in (town_hall, th_number, base_info, base_link, war_base_media, active_war_base_media)):
            raise ValueError("FWA base data is incomplete.")
        replacements.update(town_hall=town_hall, th_number=th_number, base_info=base_info)
        native = native_base_result(
            recruit_mention="{recruit}", recruiter_mention="{recruiter}",
            friendly_name="{town_hall}", th_number="{th_number}", base_info="{base_info}",
            base_link=base_link, war_base_media=war_base_media, active_war_base_media=active_war_base_media,
        )
        # The two live FWA images are managed by /manage FWA, not this editor.
        sections = validated["sections"][3:]
        media = {f"image_{index}": _media_value(node) for index, node in enumerate(_media_nodes(native))}
    elif stage == "selector":
        native = _native_for(variant, action_id=action_id)
        sections = validated["sections"][:3] if variant == "fwa_bases_upon_approval" else validated["sections"]
        media = validated["media"]
    else:
        raise ValueError("Choose a supported FWA base preview stage.")
    rendered = _replace_native(native, sections, media, validated["accent"], replacements, preview=preview)
    texts = [node.content for node in _text_nodes(rendered)]
    if any(len(text) > _MAX_BLOCK for text in texts) or sum(map(len, texts)) > _MAX_TOTAL_TEXT:
        raise ValueError("Rendered question exceeds Discord's display limit.")
    return rendered


def preview_template(template: dict, *, stage: str = "selector") -> list:
    sample = dict(user_id=111111111111111111, recruiter_id=222222222222222222, preview=True)
    if template.get("variant") != "fwa_bases_upon_approval" or stage == "selector":
        return render_template(template, **sample)
    if stage != "result":
        raise ValueError("Choose a supported FWA base preview stage.")
    return render_template(
        template, **sample, stage="result", town_hall="Town Hall 18", th_number="18",
        base_info="Example FWA base instructions from clan data.",
        base_link="https://example.org/fwa-base",
        war_base_media="assets/Blue_Footer.png",
        active_war_base_media="assets/Blue_Footer.png",
    )

"""Guild-scoped editable copy for the six active primary recruit questions."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

import hikari
from hikari.impl import (
    ContainerComponentBuilder as Container, InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow, MediaGalleryComponentBuilder as Media,
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

def default_template(variant: str) -> dict:
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

def validate_template(variant: str, template: dict) -> dict:
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

def render_template(template: dict, *, user_id: int, recruiter_id: int, preview: bool = False) -> list:
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

def preview_template(template: dict) -> list:
    return render_template(template, user_id=111111111111111111, recruiter_id=222222222222222222, preview=True)

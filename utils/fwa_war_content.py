"""Guild-scoped, revisioned text for FWA war-plan messages.

The native war-plan builders own the layout. This module replaces only their
text nodes, footer image, and accent so saved edits cannot alter the message
shape or the public send destination.
"""

from __future__ import annotations

import copy
import ipaddress
import re
from urllib.parse import urlparse

from pymongo.errors import DuplicateKeyError


VARIANTS = ("win", "lose", "mismatch", "blacklisted")
PLACEHOLDERS = frozenset({"opponent", "author", "clan_role", "fwa_rep_role"})
_TOKEN = re.compile(r"\{([a-z_]+)\}")
BLOCK_LABELS = {
    "win": ("Outcome heading", "Clan and opponent", "First attack", "Second attack options", "Star goal", "Declaration credit"),
    "lose": ("Outcome heading", "Clan and opponent", "First attack", "Second attack options", "Star goal", "Declaration credit"),
    "mismatch": ("Outcome heading", "Clan and opponent", "War guidance", "War base warning", "Declaration credit"),
    "blacklisted": (
        "Alert heading", "Clan and opponent", "Switch to war bases", "Enemy intel",
        "First attack heading", "First attack strategy", "Second attack heading",
        "Second attack strategy", "Target claim heading", "Target claim rules",
        "FWA points heading", "FWA points objective", "Help and representative", "Declaration credit",
    ),
}
_SCHEMA_VERSION = 1
_MAX_BLOCK = 2000
_MAX_TOTAL_TEXT = 4000
_MAX_COPY = 1800


class TemplateConflict(ValueError):
    """The saved template changed after this editor loaded it."""


def _native(variant: str, opponent: str, author: str, clan_role: str, fwa_rep_role: str):
    # Lazy import avoids a cycle through extensions.commands.fwa.__init__.
    from extensions.commands.fwa.message_templates import WarMessageTemplates
    if variant not in VARIANTS:
        raise ValueError("Choose a supported war result.")
    args = (opponent, author, clan_role)
    if variant == "blacklisted":
        args += (fwa_rep_role,)
    return getattr(WarMessageTemplates, f"{variant}_message")(*args)


def default_template(variant: str) -> dict:
    from hikari.impl import TextDisplayComponentBuilder as Text
    from extensions.commands.fwa.message_templates import FOOTER_IMAGES, WAR_COLORS, WarCopyTexts
    native = _native(variant, "{opponent}", "{author}", "{clan_role}", "{fwa_rep_role}")
    sections = [part.content for part in native[0].components if isinstance(part, Text)]
    if len(sections) != len(BLOCK_LABELS[variant]):
        raise RuntimeError(f"Native {variant} war layout changed; update editable block labels.")
    return {
        "variant": variant,
        "sections": sections,
        "copy_text": getattr(WarCopyTexts, f"{variant}_copy")("{opponent}"),
        "footer_url": FOOTER_IMAGES[variant],
        "accent": int(WAR_COLORS[variant]),
        "revision": 0,
    }


def _replace(text: str, values: dict[str, str]) -> str:
    tokens = _TOKEN.findall(text)
    if any(token not in PLACEHOLDERS for token in tokens):
        raise ValueError("Only opponent, author, clan_role, and fwa_rep_role placeholders are supported.")
    remainder = _TOKEN.sub("", text)
    if "{" in remainder or "}" in remainder:
        raise ValueError("Use only supported placeholders inside braces.")
    return _TOKEN.sub(lambda match: values[match.group(1)], text)


def _footer_ok(value: str, variant: str) -> bool:
    from extensions.commands.fwa.message_templates import FOOTER_IMAGES
    if value == FOOTER_IMAGES[variant]:
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


def validate_template(variant: str, template: dict) -> dict:
    if variant not in VARIANTS or not isinstance(template, dict):
        raise ValueError("Choose a supported war result.")
    sections = template.get("sections")
    if not isinstance(sections, list) or len(sections) != len(BLOCK_LABELS[variant]):
        raise ValueError("This war message has the wrong number of text blocks.")
    if any(not isinstance(value, str) or not value.strip() for value in sections):
        raise ValueError("Every war message text block needs content.")
    copy_text = template.get("copy_text")
    if not isinstance(copy_text, str) or not copy_text.strip():
        raise ValueError("Copy text cannot be empty.")
    footer_url = template.get("footer_url")
    if not _footer_ok(footer_url, variant):
        raise ValueError("Choose a public HTTPS image URL or the original footer image.")
    accent = template.get("accent")
    if isinstance(accent, bool) or not isinstance(accent, int) or not 0 <= accent <= 0xFFFFFF:
        raise ValueError("Choose a valid six-digit accent color.")

    values = {
        "opponent": "O" * 50,
        "author": "A" * 32,
        "clan_role": "9" * 20,
        "fwa_rep_role": "8" * 20,
    }
    rendered = [_replace(value, values) for value in sections]
    rendered_copy = _replace(copy_text, values)
    if any(len(value) > _MAX_BLOCK for value in rendered) or sum(map(len, rendered)) > _MAX_TOTAL_TEXT:
        raise ValueError("War message text exceeds Discord's display limit.")
    if len(rendered_copy) > _MAX_COPY:
        raise ValueError("Copy text is too long.")
    return {
        "variant": variant,
        "sections": list(sections),
        "copy_text": copy_text,
        "footer_url": footer_url,
        "accent": accent,
    }


def _row_id(guild_id: int, variant: str) -> str:
    if variant not in VARIANTS or not isinstance(guild_id, int) or guild_id <= 0:
        raise ValueError("Choose a supported war result in a server.")
    return f"fwa_war_template:{guild_id}:{variant}"


async def load_template(mongo, guild_id: int, variant: str) -> dict:
    row = await mongo.bot_config.find_one({"_id": _row_id(guild_id, variant)})
    if row is None:
        return default_template(variant)
    if row.get("schema_version") != _SCHEMA_VERSION or row.get("guild_id") != guild_id or row.get("variant") != variant:
        raise ValueError("Saved FWA war message configuration is invalid. No message was sent.")
    revision = row.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Saved FWA war message revision is invalid. No message was sent.")
    try:
        template = validate_template(variant, row)
    except ValueError as exc:
        raise ValueError("Saved FWA war message configuration is invalid. No message was sent.") from exc
    return dict(template, revision=revision)


async def save_template(mongo, guild_id: int, variant: str, template: dict,
                        expected_revision: int, updated_by: int) -> dict:
    key = _row_id(guild_id, variant)
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("Template revision is invalid.")
    validated = validate_template(variant, template)
    row = {
        **validated, "_id": key, "schema_version": _SCHEMA_VERSION,
        "guild_id": guild_id, "revision": expected_revision + 1,
        "updated_by": int(updated_by),
    }
    if expected_revision == 0:
        try:
            await mongo.bot_config.insert_one(row)
        except DuplicateKeyError as exc:
            raise TemplateConflict("This war message changed. Reopen it before saving.") from exc
    else:
        result = await mongo.bot_config.update_one(
            {"_id": key, "revision": expected_revision},
            {"$set": {name: value for name, value in row.items() if name != "_id"}},
        )
        if result.matched_count != 1:
            raise TemplateConflict("This war message changed. Reopen it before saving.")
    return dict(validated, revision=expected_revision + 1)


async def reset_template(mongo, guild_id: int, variant: str,
                         expected_revision: int, updated_by: int) -> dict:
    return await save_template(
        mongo, guild_id, variant, default_template(variant), expected_revision, updated_by,
    )


def render_template(template: dict, *, opponent: str, author: str,
                    clan_role_id: int | str, fwa_rep_role_id: int | str) -> tuple[list, str]:
    from hikari.impl import (
        ContainerComponentBuilder as Container,
        MediaGalleryComponentBuilder as Media,
        MediaGalleryItemBuilder as MediaItem,
        TextDisplayComponentBuilder as Text,
    )
    from extensions.commands.fwa.message_templates import sanitize_opponent_for_header
    variant = template.get("variant")
    validated = validate_template(variant, template)
    values = {
        "opponent": sanitize_opponent_for_header(opponent),
        "author": author,
        "clan_role": str(clan_role_id),
        "fwa_rep_role": str(fwa_rep_role_id),
    }
    copy_values = dict(values, opponent=opponent)
    native = _native(variant, opponent, author, str(clan_role_id), str(fwa_rep_role_id))
    text_index = 0
    parts = []
    for part in native[0].components:
        if isinstance(part, Text):
            parts.append(Text(content=_replace(validated["sections"][text_index], values)))
            text_index += 1
        elif isinstance(part, Media):
            parts.append(Media(items=[MediaItem(media=validated["footer_url"])]))
        else:
            parts.append(part)
    if text_index != len(validated["sections"]):
        raise RuntimeError("Native war message layout changed.")
    rendered_text = [part.content for part in parts if isinstance(part, Text)]
    rendered_copy = _replace(validated["copy_text"], copy_values)
    if any(len(value) > _MAX_BLOCK for value in rendered_text) or sum(map(len, rendered_text)) > _MAX_TOTAL_TEXT or len(rendered_copy) > _MAX_COPY:
        raise ValueError("Rendered war message exceeds Discord's display limit.")
    components = [Container(accent_color=validated["accent"], components=parts)]
    return components, rendered_copy


def preview_template(template: dict) -> tuple[list, str]:
    return render_template(
        template, opponent="Example Opponent", author="War Planner",
        clan_role_id=111111111111111111, fwa_rep_role_id=222222222222222222,
    )

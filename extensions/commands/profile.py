"""/profile: one Discord user's identity and every linked Clash account.

The same card is the staff "New Warrior" alert (``extensions/events/new_warrior_alert.py``).
Links come from ClashKing and ClashPerk and are mostly unverified; every forward
link is shown. Names are shown as the join/leave log shows them: a profile link,
never a mention, so Discord cannot render "Unknown user".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

import coc
import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SectionComponentBuilder as Section,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
    ThumbnailComponentBuilder as Thumbnail,
)

from extensions.commands import linked_accounts
from extensions.components import register_action
from utils import recruit_links
from utils.constants import WARRIORS_UNITED_GUILD_ID, WU_GOLD
from utils.member_events import safe_text

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)

MODE_PROFILE = "p"
MODE_ALERT = "a"
NEW_WARRIOR_PING_ROLE_ID = 1151305219079155802
NEW_WARRIOR_TITLE = "# ⛩️ New Warrior at the Gate"
USERNAME = re.compile(r"[a-z0-9_.]{2,32}")
MESSAGE_TEXT_LIMIT = 4000
TEXT_SAFETY_MARGIN = 100


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: int
    display_name: str
    username: str
    avatar_url: str | None = None
    created_at: datetime | None = None
    joined_at: datetime | None = None


def identity_from(user: hikari.User | hikari.Member) -> Identity:
    """Build the card header from a hikari user or member (no network)."""
    member = user if isinstance(user, hikari.Member) else None
    username = str(getattr(user, "username", "") or "")
    display_name = str(
        (getattr(member, "display_name", None) if member else None)
        or getattr(user, "global_name", None)
        or username
        or "Unknown member"
    )
    avatar = getattr(user, "display_avatar_url", None)
    return Identity(
        user_id=int(user.id),
        display_name=display_name,
        username=username,
        avatar_url=str(avatar) if avatar else None,
        created_at=getattr(user, "created_at", None),
        joined_at=getattr(member, "joined_at", None) if member else None,
    )


async def resolve_identity(
    app, user_id: int, guild_id: int | None, user: hikari.User | None = None,
) -> Identity:
    """Prefer a cached member, then the given user, then one REST user fetch."""
    guild_id = int(guild_id or WARRIORS_UNITED_GUILD_ID)
    cache = getattr(app, "cache", None)
    try:
        member = cache.get_member(guild_id, int(user_id)) if cache else None
    except Exception:
        member = None
    if member is not None:
        return identity_from(member)
    if user is not None:
        return identity_from(user)
    try:
        cached = cache.get_user(int(user_id)) if cache else None
    except Exception:
        cached = None
    if cached is not None:
        return identity_from(cached)
    try:
        return identity_from(await app.rest.fetch_user(int(user_id)))
    except Exception:
        _log.warning("profile user lookup failed user=%s", user_id)
        return Identity(int(user_id), "Unknown member", "")


async def load_profile_accounts(
    coc_client: coc.Client, discord_id: int, *, force: bool = False,
) -> linked_accounts.AccountsData:
    """Merged forward links (no ownership check), cached briefly for paging."""
    if not force and (cached := linked_accounts.cached_merged(discord_id)) is not None:
        return cached
    links = await recruit_links.resolve(int(discord_id), verify_owners=False)
    data = await linked_accounts.load_accounts(
        coc_client, int(discord_id), force=True, linked_result=links,
    )
    linked_accounts.remember_merged(discord_id, data)
    return data


def _stamp(value: datetime | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    return f"<t:{int(value.timestamp())}:D>"


def _header_text(identity: Identity) -> str:
    # Display names can hold characters that stop Discord rendering a masked
    # link, so the name is plain text and the link sits on the username
    # (Discord usernames are only a-z, 0-9, "_" and ".").
    # Disarm bare URLs too, as the join log does, so a name is never a link.
    name = re.sub(r"(?i)\b(https?)://", "\\1\u200b://", safe_text(identity.display_name))
    name = name if name.replace("\u200d", "").strip() else "Unknown member"
    username = identity.username if USERNAME.fullmatch(identity.username or "") else ""
    profile_url = f"https://discord.com/users/{int(identity.user_id)}"
    lines = [f"### {name}", f"[{safe_text(username) if username else 'Discord profile'}]({profile_url})"]
    if created := _stamp(identity.created_at):
        lines.append(f"**Account created:** {created}")
    if joined := _stamp(identity.joined_at):
        lines.append(f"**Joined server:** {joined}")
    return "\n".join(lines)


def _header(identity: Identity, content: str) -> Section | Text:
    text = Text(content=content)
    if not identity.avatar_url:
        return text
    return Section(
        components=[text],
        accessory=Thumbnail(media=identity.avatar_url, description="Avatar"),
    )


def _buttons(user_id: int, page: int, pages: int, mode: str) -> ActionRow:
    style = hikari.ButtonStyle.SECONDARY
    row: list = []
    if pages > 1:
        # Unclamped ids stay unique on the first and last page; the renderer
        # clamps hostile or out-of-range values when they arrive.
        row.extend([
            Button(style=style, custom_id=f"profile_page:{user_id}:{page - 1}:{mode}",
                   label="◀", is_disabled=page == 0),
            Button(style=style, custom_id=f"profile_page:{user_id}:{page}:{mode}",
                   label=f"Page {page + 1}/{pages}", is_disabled=True),
            Button(style=style, custom_id=f"profile_page:{user_id}:{page + 1}:{mode}",
                   label="▶", is_disabled=page >= pages - 1),
        ])
    row.append(Button(style=style, custom_id=f"profile_refresh:{user_id}:{page}:{mode}",
                      label="Refresh"))
    return ActionRow(components=row)


def render_profile(
    identity: Identity, data: linked_accounts.AccountsData, page: int = 0,
    *, mode: str = MODE_PROFILE,
) -> list[Container]:
    """One Components V2 card: identity, separator, linked accounts."""
    title = f"{NEW_WARRIOR_TITLE}\n<@&{NEW_WARRIOR_PING_ROLE_ID}>" if mode == MODE_ALERT else ""
    header = _header_text(identity)
    notes = "\n".join(linked_accounts.account_notes(data))
    if data.entries:
        heading = (
            f"## Linked Accounts\n{linked_accounts.summary_line(data)}\n"
            "-# ClashKing + ClashPerk links. Sorted by Town Hall."
        )
    elif data.unavailable_sources:
        heading = "## Linked Accounts"  # An outage is never presented as "no links".
    else:
        heading = "## Linked Accounts\nNo linked accounts\n-# Not linked in ClashKing or ClashPerk."
    # Discord limits the text of all Text Displays in one message together.
    budget = MESSAGE_TEXT_LIMIT - TEXT_SAFETY_MARGIN - sum(
        linked_accounts.text_units(part) for part in (title, header, notes, heading))
    page, pages, blocks = linked_accounts.page_window(data, page, budget=budget)

    body: list = [Text(content=title)] if title else []
    body.extend([_header(identity, header), Separator(divider=True), Text(content=heading)])
    body.extend(Text(content=block) for block in blocks)
    if notes:
        if data.entries:
            body.append(Separator(divider=True))
        body.append(Text(content=notes))
    body.append(_buttons(identity.user_id, page, pages, mode))
    body.append(Media(items=[MediaItem(media="assets/Gold_Footer.png")]))
    return [Container(accent_color=WU_GOLD, components=body)]


def parse_action(action_id: str) -> tuple[int, int, str] | None:
    """``<user_id>:<page>[:<mode>]``; old ``user_accounts_page`` ids have no mode."""
    parts = action_id.split(":")
    if len(parts) not in (2, 3):
        return None
    target, page = parts[0], parts[1]
    mode = parts[2] if len(parts) == 3 else MODE_PROFILE
    if (not target or len(target) > 20 or not target.isascii() or not target.isdigit()
            or mode not in (MODE_PROFILE, MODE_ALERT)):
        return None
    user_id = int(target)
    if not 0 < user_id < 2**64:
        return None
    try:
        page_number = int(page)
    except ValueError:
        page_number = 0
    return user_id, page_number, mode


async def _render_action(ctx, action_id: str, coc_client, *, force: bool):
    parsed = parse_action(action_id)
    if parsed is None:
        await ctx.respond("Run `/profile` again.", ephemeral=True)
        return None
    user_id, page, mode = parsed
    app = ctx.interaction.app
    guild_id = getattr(ctx.interaction, "guild_id", None)
    identity = await resolve_identity(app, user_id, guild_id)
    data = await load_profile_accounts(coc_client, user_id, force=force)
    cards = render_profile(identity, data, page, mode=mode)
    # This handler edits the message itself so every edit states that nobody
    # is pinged; the alert's role mention must notify only once, at posting.
    quiet = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
    try:
        await ctx.respond(components=cards, edit=True, **quiet)
    except hikari.NotFoundError:
        # The interaction token expired before the acknowledgement; the button
        # still sits on a real message, so edit that message directly.
        message = getattr(ctx.interaction, "message", None)
        if message is None:
            raise
        await ctx.interaction.app.rest.edit_message(
            message.channel_id, message.id, components=cards, **quiet,
        )
    return None


@register_action(
    "profile_page", preload_state=False, no_return=True, aliases=("user_accounts_page",),
)
@lightbulb.di.with_di
async def profile_page_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _render_action(ctx, action_id, coc_client, force=False)


@register_action("profile_refresh", preload_state=False, no_return=True)
@lightbulb.di.with_di
async def profile_refresh_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    **_kwargs,
):
    return await _render_action(ctx, action_id, coc_client, force=True)


@loader.command
class Profile(
    lightbulb.SlashCommand,
    name="profile",
    description="Show a Discord user and their linked Clash accounts",
):
    discord_user = lightbulb.user(
        "discord_user", "Discord user to show. Leave empty for yourself", default=None,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        coc_client: coc.Client = lightbulb.di.INJECTED,
    ) -> None:
        target = self.discord_user or ctx.user
        await ctx.defer(ephemeral=False)
        identity = await resolve_identity(ctx.interaction.app, int(target.id), ctx.guild_id, target)
        data = await load_profile_accounts(coc_client, int(target.id), force=True)
        await ctx.interaction.edit_initial_response(
            components=render_profile(identity, data),
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )

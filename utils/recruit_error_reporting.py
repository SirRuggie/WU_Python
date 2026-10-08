"""Report recruit-facing failures without turning reporting failures into outages."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys

import hikari

ALERT_CHANNEL_ID = 1547244294757425212
DEVELOPER_USER_ID = 505227988229554179
_log = logging.getLogger(__name__)


def _safe(value: object) -> str:
    text = str(value)
    for key, secret in os.environ.items():
        if any(part in key.upper() for part in ('TOKEN', 'SECRET', 'PASSWORD', 'MONGODB_URI')) and len(secret) >= 8:
            text = text.replace(secret, '[redacted]')
    text = re.sub(r'https://(?:[^/]+\.)?discord(?:app)?\.com/api/webhooks/\S+', '[redacted webhook]', text)
    return text.replace('`', "'")


async def notify(ctx, message: str, *, error: BaseException | None = None, rest=None) -> str:
    """Return user copy only after a bounded notification attempt.

    Helpers called inside an except block retain the actual exception, even
    when the public error intentionally hides internal details.
    """
    error = error if error is not None else sys.exception()
    try:
        interaction = ctx.interaction
        rest = rest if rest is not None else interaction.app.rest
        guild = getattr(ctx, 'guild_id', None) or getattr(interaction, 'guild_id', None)
        channel = getattr(ctx, 'channel_id', None) or getattr(interaction, 'channel_id', None)
        action = getattr(interaction, 'custom_id', 'unknown')
        detail = f'{type(error).__name__}: {error}' if error is not None else message
        safe_detail = _safe(detail)
        attachments = {}
        if len(safe_detail) > 950:
            attachments['attachment'] = hikari.Bytes(safe_detail.encode('utf-8'), 'recruit-error.txt')
        content = (
            f'<@{DEVELOPER_USER_ID}> **Recruit error**\n'
            f'Recruit: <@{ctx.user.id}> (`{ctx.user.id}`)\n'
            f'Step: `{_safe(action)[:200]}`\n'
            f'Location: https://discord.com/channels/{guild}/{channel}\n'
            f'Interaction: `{getattr(interaction, "id", "unknown")}`\n'
            f'User message: {_safe(message)[:600]}\n'
            f'Exact issue: {safe_detail[:950]}'
            + ('\nFull error details attached.' if attachments else '')
        )
        async with asyncio.timeout(5):
            await rest.create_message(
                ALERT_CHANNEL_ID, content=content[:2000],
                user_mentions=[DEVELOPER_USER_ID], role_mentions=False,
                mentions_everyone=False, **attachments,
            )
    except Exception:
        _log.exception('Could not send recruit error alert')
        return message + '\nI could not notify the Server Dev automatically. Please contact server staff.'
    return message + '\nThe Server Dev has been notified so they can look into this.'


async def edit_error(ctx, *, content: str, rest=None) -> None:
    await ctx.interaction.edit_initial_response(content=await notify(ctx, content, rest=rest))


def is_recruit_action(action) -> bool:
    """Use registry source metadata, including resolved aliases/group actions."""
    source = getattr(action, 'declared_at', '').replace('\\', '/')
    return any(path in source for path in (
        'commands/setup/recruit_', 'commands/recruit/questions.py',
        'commands/tickets/rite.py',
    )) or getattr(action, 'name', '') in {'ticket_v2_create', 'ticket_v2_my_ticket'}


async def respond_error(ctx, message: str, *, ephemeral=True) -> None:
    await ctx.respond(await notify(ctx, message), ephemeral=ephemeral)

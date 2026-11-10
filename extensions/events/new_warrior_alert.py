"""Staff "New Warrior" alert: the /profile card, posted once when someone joins WU.

One send attempt per join. A failed send is logged and dropped: Discord may
already have accepted it, and a retry could post twice. A link lookup failure
still posts the alert, with the incomplete-list note.
"""

from __future__ import annotations

import asyncio
import logging

import coc
import hikari
import lightbulb

from extensions.commands import linked_accounts
from extensions.commands.profile import (
    MODE_ALERT,
    NEW_WARRIOR_PING_ROLE_ID,
    identity_from,
    load_profile_accounts,
    render_profile,
)
from utils.constants import NEW_WARRIOR_ALERT_CHANNEL_ID, WARRIORS_UNITED_GUILD_ID

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)


async def _accounts(coc_client, user_id: int) -> linked_accounts.AccountsData:
    try:
        return await load_profile_accounts(coc_client, user_id, force=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        _log.exception("New warrior link lookup failed user=%s", user_id)
        return linked_accounts.AccountsData(
            unavailable_sources=("ClashKing", "ClashPerk"),
        )


async def post_alert(bot, member: hikari.Member, coc_client) -> bool:
    """Post the alert once. Returns True when Discord accepted the message."""
    if int(member.guild_id) != WARRIORS_UNITED_GUILD_ID or member.is_bot:
        return False
    data = await _accounts(coc_client, int(member.id))
    components = render_profile(identity_from(member), data, mode=MODE_ALERT)
    try:
        await bot.rest.create_message(
            NEW_WARRIOR_ALERT_CHANNEL_ID,
            components=components,
            user_mentions=False,
            role_mentions=[NEW_WARRIOR_PING_ROLE_ID],
            mentions_everyone=False,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        _log.exception("New warrior alert was not posted user=%s", member.id)
        return False
    return True


@loader.listener(hikari.MemberCreateEvent)
@lightbulb.di.with_di
async def new_warrior_joined(
    event: hikari.MemberCreateEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    coc_client: coc.Client = lightbulb.di.INJECTED,
) -> None:
    try:
        await post_alert(bot, event.member, coc_client)
    except asyncio.CancelledError:
        raise
    except Exception:
        _log.exception("New warrior alert failed")

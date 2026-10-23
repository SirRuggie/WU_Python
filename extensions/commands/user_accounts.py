"""Public, merged account inventory by Discord ID."""

import time

import coc
import lightbulb

from extensions.components import register_action
from extensions.commands.accounts import (
    AccountsData, RESULT_TTL, _page_number, load_accounts, render_accounts,
)
from utils import recruit_links

loader = lightbulb.Loader()
# Separate from /accounts: that inventory currently uses ClashKing alone.
_results: dict[int, tuple[float, AccountsData]] = {}


def parse_discord_id(value: str) -> int | None:
    value = value.strip()
    if not value or len(value) > 20 or not value.isascii() or not value.isdigit():
        return None
    parsed = int(value)
    return parsed if 0 < parsed < 2**64 else None


async def load_inventory(coc_client: coc.Client, discord_id: int, *, force=False) -> AccountsData:
    now = time.monotonic()
    for key, (expires, _) in list(_results.items()):
        if expires <= now:
            _results.pop(key, None)
    if not force and discord_id in _results:
        return _results[discord_id][1]
    # This is an inventory of forward links, not an ownership-verification flow.
    links = await recruit_links.resolve(discord_id, verify_owners=False)
    data = await load_accounts(coc_client, discord_id, linked_result=links)
    _results[discord_id] = (time.monotonic() + RESULT_TTL, data)
    return data


@register_action("user_accounts_page", preload_state=False)
@lightbulb.di.with_di
async def user_accounts_page_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    **_kwargs,
):
    target, separator, page = action_id.partition(":")
    discord_id = parse_discord_id(target)
    if discord_id is None or not separator:
        await ctx.respond("This panel is invalid. Run `/user-accounts` again.", ephemeral=True)
        return None
    data = await load_inventory(coc_client, discord_id)
    return render_accounts(data, _page_number(page), discord_id=discord_id)


@loader.command
class UserAccounts(
    lightbulb.SlashCommand,
    name="user-accounts",
    description="Publicly show merged ClashKing and ClashPerk accounts for a user",
):
    user = lightbulb.user(
        "user", "Search for the Discord user whose accounts you want to see",
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        coc_client: coc.Client = lightbulb.di.INJECTED,
    ) -> None:
        discord_id = int(self.user.id)
        await ctx.defer(ephemeral=False)
        data = await load_inventory(coc_client, discord_id, force=True)
        await ctx.interaction.edit_initial_response(
            components=render_accounts(data, discord_id=discord_id),
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )

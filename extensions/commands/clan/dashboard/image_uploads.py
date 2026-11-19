"""Retired upload controls link to the existing dashboard without saving data."""
from typing import Any
import lightbulb
from extensions.components import register_action
from utils.discord_file_upload import pop_file_upload
from utils.mongo import MongoClient
from .fwa_data import town_hall_base_card, FWA_REP_ROLE_ID
from .permissions import require_dashboard_role


async def _open(ctx: Any, action_id: str, mongo: MongoClient, kind: str) -> None:
    if kind == 'clan':
        from .read_only_clan import show_clan
        await show_clan(ctx,mongo,action_id)
        return
    if await require_dashboard_role(ctx,FWA_REP_ROLE_ID,'FWA Clan Rep'):
        await ctx.respond(components=town_hall_base_card(),ephemeral=True,
                          user_mentions=False,role_mentions=False,mentions_everyone=False)


@register_action('clan_image_upload', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def clan_image_upload(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    from .read_only_clan import show_clan
    await show_clan(ctx,mongo,action_id)


@register_action('fwa_image_upload', no_return=True, preload_state=False)
@lightbulb.di.with_di
async def fwa_image_upload(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _open(ctx,action_id,mongo,'fwa')


@register_action('dashboard_image_submit', is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def dashboard_image_submit(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    # Old opaque upload tokens carry no trusted destination. Consume the raw
    # gateway cache, then use the existing read-only clan fallback; never upload.
    interaction = ctx.interaction
    pop_file_upload(interaction.id, interaction.custom_id, 'image')
    from .read_only_clan import show_clan
    await show_clan(ctx, mongo, action_id)

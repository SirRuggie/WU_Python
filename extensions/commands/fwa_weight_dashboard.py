"""Town Hall administration moved to the revision-checked dashboard editor."""
import hikari
import lightbulb
from extensions.components import register_action
from utils.constants import WU_GOLD
from utils.dashboard_urls import DASHBOARD_ORIGIN

loader = lightbulb.Loader()
NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)


def admin(ctx):
    member = getattr(ctx.interaction, 'member', None)
    return bool(getattr(member, 'permissions', 0) & hikari.Permissions.ADMINISTRATOR)


def panel():
    row = hikari.impl.MessageActionRowBuilder()
    row.add_link_button(DASHBOARD_ORIGIN + '/manage/town-halls', label='Open Town Halls')
    return [hikari.impl.ContainerComponentBuilder(accent_color=WU_GOLD, components=[
        hikari.impl.TextDisplayComponentBuilder(content='## Town Halls\nTown Halls are managed on the dashboard.'), row])]


async def open_dashboard(ctx, mongo, *, manage_token, deferred=False):
    if not admin(ctx):
        await ctx.respond('You need Administrator permission.', ephemeral=True)
        return
    if not deferred:
        await ctx.defer(ephemeral=True)
    await ctx.interaction.edit_initial_response(components=panel(), **NO_MENTIONS)


# These legacy buttons acknowledge with a new private card. Suppress the
# dispatcher's default source-message edit; none of these controls opens a modal.
@register_action('weight_refresh', aliases=('weight_minimum', 'weight_add', 'weight_edit'),
                 opens_modal=True, no_return=True, preload_state=False)
async def refresh(ctx, action_id, **_):
    if not admin(ctx):
        await ctx.respond('You need Administrator permission.', ephemeral=True)
        return
    await ctx.respond(components=panel(), ephemeral=True, **NO_MENTIONS)


@register_action('weight_save', is_modal=True, no_return=True, preload_state=False)
async def save(ctx, action_id, **_):
    await refresh(ctx, action_id)

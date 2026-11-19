"""Read-only compatibility cards for retired Discord Town Hall base editors."""
import logging
import re
import hikari
import lightbulb
from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text, MessageActionRowBuilder as ActionRow, LinkButtonBuilder as LinkButton
from extensions.components import register_action
from extensions.commands.clan.dashboard.permissions import require_dashboard_role
from utils.constants import WU_GOLD, WARRIORS_UNITED_GUILD_ID as GUILD_ID
from utils.dashboard_urls import DASHBOARD_ORIGIN
from utils import town_halls

FWA_REP_ROLE_ID = 993015846442127420
LOG = logging.getLogger(__name__)


def get_th_emoji(th_level):
    match = re.fullmatch(r'th([1-9][0-9]?)(?:_new)?', str(th_level))
    markup = town_halls.town_hall_emoji(int(match[1])) if match else ''
    return hikari.Emoji.parse(markup) if markup else None


def town_hall_base_card():
    doc = town_halls.snapshot(GUILD_ID)
    levels = [level for level in town_halls.levels(doc) if level >= doc['lowest_fwa_town_hall']] if doc else []
    if len(levels) > 25:
        LOG.warning('Town Hall base management has more than25 levels; keeping the highest25.')
    components = [Text(content='## Town Halls\nTown Hall bases are managed on the dashboard.')]
    for offset in range(0, min(len(levels), 25), 5):
        components.append(ActionRow(components=[LinkButton(
            url=f'{DASHBOARD_ORIGIN}/manage/town-halls/{level}', label=f'Open Town Hall {level}',
        ) for level in levels[offset:offset+5]]))
    if not levels:
        components.append(ActionRow(components=[LinkButton(url=DASHBOARD_ORIGIN+'/manage/town-halls',label='Open Town Halls')]))
    return [Container(accent_color=WU_GOLD, components=components)]


async def build_fwa_management_screen(ctx, mongo, manage_token=None):
    return town_hall_base_card()


def build_th_edit_components(th_level, *_legacy_values, manage_token=None):
    """Old callers get the same link card, never a second base editor."""
    return town_hall_base_card()


@register_action('manage_fwa_data', group='clan_database', ephemeral=True, preload_state=False,
                 aliases=('fwa_back_to_main','fwa_th_select','fwa_update_link','fwa_update_images',
                          'fwa_image_urls','fwa_update_descriptions','fwa_th_select_return','fwa_upload_guide'))
@lightbulb.di.with_di
async def manage_fwa_data(ctx, **_kwargs):
    if not await require_dashboard_role(ctx,FWA_REP_ROLE_ID,'FWA Clan Rep'):
        return
    return town_hall_base_card()


@register_action('fwa_link_submit', is_modal=True, no_return=True, preload_state=False,
                 aliases=('fwa_images_submit','fwa_descriptions_submit'))
@lightbulb.di.with_di
async def retired_fwa_submit(ctx, **_kwargs):
    if not await require_dashboard_role(ctx,FWA_REP_ROLE_ID,'FWA Clan Rep'):
        return
    await ctx.respond(components=town_hall_base_card(),ephemeral=True,
                      user_mentions=False,role_mentions=False,mentions_everyone=False)


# Public callable names retained for old internal imports and fixtures.
fwa_back_to_main = fwa_th_select = fwa_update_link = fwa_update_images = manage_fwa_data
fwa_image_urls = fwa_update_descriptions = fwa_th_select_return = fwa_upload_guide = manage_fwa_data
fwa_link_submit = fwa_images_submit = fwa_descriptions_submit = retired_fwa_submit

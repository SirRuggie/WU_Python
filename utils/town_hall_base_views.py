"""Storage-free Discord adapters for the server's Town Hall base snapshot."""
import hikari
from hikari.impl import TextSelectMenuBuilder, SelectOptionBuilder
from utils import town_halls
from utils.media_urls import DETAIL, optimized
from utils.constants import WARRIORS_UNITED_GUILD_ID as GUILD_ID



def base_menu(custom_id, *, empty=False):
    doc = town_halls.snapshot(GUILD_ID)
    choices = town_halls.menu_options(doc) if doc else []
    if not choices:
        if not empty:
            return None
        return TextSelectMenuBuilder(custom_id=custom_id, max_values=1,
            placeholder='No base links are set.', is_disabled=True,
            options=[SelectOptionBuilder(label='No base links are set.', value='unavailable')])
    return TextSelectMenuBuilder(
        custom_id=custom_id, max_values=1, placeholder="Select a Base...",
        options=[SelectOptionBuilder(
            label=choice['label'], value=choice['value'],
            emoji=hikari.Emoji.parse(choice['emoji']) if choice.get('emoji') else hikari.UNDEFINED,
        ) for choice in choices],
    )


def base_choice(value):
    """Recheck old menu values against linked, currently visible variants."""
    try:
        level, variant = town_halls.parse_variant_value(value)
    except ValueError:
        return None
    doc = town_halls.snapshot(GUILD_ID)
    if doc is None:
        return None
    item = next((row for row in town_halls.base_variants(doc)
                 if row['level'] == level and row['variant'] == variant), None)
    if item is None:
        return None
    label = town_halls.variant_label(level, variant)
    return {
        **item, 'display_name': f'TH{level} {label}'.rstrip(),
        'friendly_name': f'Town Hall {level} {label}'.rstrip(),
        'war_image': optimized(item['war_image'], width=DETAIL) if item['war_image'] else '',
        'active_image': optimized(item['active_image'], width=DETAIL) if item['active_image'] else '',
    }

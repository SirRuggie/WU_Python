"""Read-only compatibility handlers for retired Discord clan editing."""
import lightbulb
from extensions.components import register_action
from utils.mongo import MongoClient
from .read_only_clan import show_clan, ROLE_ID as CLAN_MANAGEMENT_ROLE_ID
from . import update_clan_info_general  # Register compatibility controls.

@register_action('update_clan_information', no_return=True, ephemeral=True, preload_state=False, is_modal=False, group='clan_database')
@lightbulb.di.with_di
async def update_clan_information(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('add_clan_page', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def add_clan_page(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('add_clan', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def add_clan(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('add_clan_modal', no_return=True, ephemeral=True, preload_state=False, is_modal=True)
@lightbulb.di.with_di
async def add_clan_modal(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('remove_clan_select', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def remove_clan_select(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('clan_remove_menu', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def clan_remove_menu(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('remove_clan', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def on_remove_clan_field(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('choose_clan_select', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def choose_clan_select(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('clan_edit_menu', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def clan_edit_menu(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('edit_clan', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def on_edit_clan_field(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('edit_thread', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def on_edit_thread_field(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('update_logo', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def update_logo_button(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('logo_upload_guide', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def logo_upload_guide(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('logo_url_modal', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def logo_url_modal_handler(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('update_logo_modal', no_return=True, ephemeral=True, preload_state=False, is_modal=True)
@lightbulb.di.with_di
async def update_logo_modal(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('back_to_clan_edit', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def back_to_clan_edit(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('edit_roles', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def edit_roles(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('edit_channels', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def edit_channels(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('update_emoji', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def update_emoji_button(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('emoji_url_modal', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def emoji_url_modal_handler(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('emoji_from_logo', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def emoji_from_logo(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('update_emoji_modal', no_return=True, ephemeral=True, preload_state=False, is_modal=True)
@lightbulb.di.with_di
async def update_emoji_modal(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

"""Read-only compatibility handlers for retired Discord clan editing."""
import lightbulb
from extensions.components import register_action
from utils.mongo import MongoClient
from .read_only_clan import show_clan

@register_action('update_general_info', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def update_general_info_panel(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

@register_action('edit_general', no_return=True, ephemeral=True, preload_state=False, is_modal=False)
@lightbulb.di.with_di
async def on_edit_general(ctx, action_id: str = '', mongo: MongoClient = lightbulb.di.INJECTED, **kwargs):
    await show_clan(ctx, mongo, action_id)

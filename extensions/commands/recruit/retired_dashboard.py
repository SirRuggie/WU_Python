"""Harmless redirects for buttons on retired recruit dashboard messages.

No old session data is loaded and no Discord or MongoDB mutation is performed.
"""

import hikari
from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT

RETIRED_ACTIONS = (
    "add_all_clans",
    "add_clan_roles",
    "add_roles",
    "back_to_dashboard",
    "begin_walkthrough",
    "create_nickname",
    "execute_add_clans",
    "execute_add_roles",
    "execute_remove_roles",
    "execute_server_walkthrough",
    "execute_set_th",
    "manage_roles",
    "nickname_modal",
    "quick_setup",
    "refresh_dashboard",
    "remove_all_clans",
    "remove_all_th",
    "remove_roles",
    "remove_roles_next",
    "remove_roles_page",
    "remove_roles_prev",
    "server_walkthrough",
    "set_townhall",
)


async def retired(ctx, action_id, **kwargs):
    return [
        hikari.impl.ContainerComponentBuilder(
            accent_color=GOLDENROD_ACCENT,
            components=[
                hikari.impl.TextDisplayComponentBuilder(
                    content="## Recruit Dashboard Retired\nUse `/warrior setup discord-user:@Member` to set up this recruit. This old control no longer makes changes."
                )
            ],
        )
    ]


for name in RETIRED_ACTIONS:
    register_action(name, preload_state=False, is_modal=name == "nickname_modal")(
        retired
    )

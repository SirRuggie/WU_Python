from extensions.commands.clan import loader, clan
from .dashboard import dashboard_page
from . import fwa_data

# Registration-only imports: these modules hold @register_action handlers for
# the dashboard select. Nothing else imports them, and load_cogs skips the
# clan folder, so without this their actions never enter the registry.
from . import update_clan_info  # also pulls in update_clan_info_general
from . import view_clan_list

__all__ = ["dashboard_page"]

"""The retired clan slash commands and their old public buttons stay off."""

import importlib

from extensions import components
from extensions.commands import clan
from extensions.commands.help_catalog import command_paths
from utils import startup


RETIRED_ACTIONS = {
    "clan_select_menu",
    "show_competitive", "show_casual", "show_zen", "show_fwa", "show_trial",
    "what_is_zen_info", "what_is_fwa_info",
    "back_to_zen_clans", "back_to_fwa_clans",
}


def test_clan_group_and_legacy_extensions_are_not_loaded():
    paths = command_paths()
    assert "/clan info" not in paths and "/clan list" not in paths
    assert not clan.clan.subcommands
    assert not any(getattr(item, "_command", None) is clan.clan for item in clan.loader._loadables)
    discovered = startup.load_cogs(disallowed=set(), disallowed_folders=set())
    assert "extensions.commands.clan.list" not in discovered
    assert "extensions.commands.clan.info_hub.info" not in discovered
    assert "extensions.commands.clan.dashboard.dashboard" in discovered


def test_legacy_modules_cannot_register_old_buttons_even_if_imported():
    for module_name in (
        "extensions.commands.clan.list",
        "extensions.commands.clan.info_hub.info",
        "extensions.commands.clan.info_hub.handlers",
        "extensions.commands.clan.info_hub.explanations",
    ):
        importlib.import_module(module_name)
    assert RETIRED_ACTIONS.isdisjoint(components.registered_functions)
    # FWA management and the separate family-links clan information stay live.
    importlib.import_module("extensions.commands.family_links")
    assert "manage_fwa_data" in components.registered_functions
    assert "view_clan_info" in components.registered_functions

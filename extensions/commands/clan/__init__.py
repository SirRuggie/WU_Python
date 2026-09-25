# extensions/commands/clan/__init__.py
import lightbulb

loader = lightbulb.Loader()
clan = lightbulb.Group("clan", "All Clan-related commands")

# Keep the dashboard component handlers for /manage FWA. The old /clan
# command group has no public subcommands and is deliberately not loaded.
from . import dashboard  # noqa: E402,F401

__all__ = ["loader", "clan", "dashboard"]

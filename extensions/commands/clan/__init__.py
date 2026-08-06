# extensions/commands/clan/__init__.py
import lightbulb

loader = lightbulb.Loader()
clan = lightbulb.Group("clan", "All Clan-related commands")

# One package extension owns the shared loader. Import every clan command here
# so main.py does not have to load the same Loader once per child module.
from . import dashboard, info_hub, list, upload  # noqa: E402,F401,A004

__all__ = ["loader", "clan", "dashboard", "info_hub", "list", "upload"]

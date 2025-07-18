# extensions/commands/clan/__init__.py
import lightbulb

loader = lightbulb.Loader()
clan = lightbulb.Group("clan", "All Clan-related commands")

__all__ = ["loader", "clan"]

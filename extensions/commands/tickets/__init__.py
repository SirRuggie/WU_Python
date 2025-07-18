# extensions/commands/tickets/__init__.py
import lightbulb

loader = lightbulb.Loader()
tickets = lightbulb.Group("tickets", "Warriors United ticket system commands")

# Import all ticket modules
from . import setup
from . import config
from . import manage
from . import handlers
from . import close

# Register the tickets group with the loader
loader.command(tickets)

__all__ = ["loader", "tickets"]
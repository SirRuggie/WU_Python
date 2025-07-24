# extensions/commands/tickets/__init__.py
import lightbulb
from utils.mongo import MongoClient
import hikari

loader = lightbulb.Loader()
ticket = lightbulb.Group("ticket", "Warriors United ticket system commands")

# Store config globally for all ticket modules
ticket_config = None
_config_loaded = False  # Guard flag


# Single startup listener for ALL ticket modules
@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Load ticket configuration from database on startup - ONCE"""
    global ticket_config, _config_loaded

    # Guard against multiple loads
    if _config_loaded:
        return
    _config_loaded = True

    config = await mongo.ticket_setup.find_one({"_id": "config"})
    if config:
        ticket_config = config
        print(f"[Tickets] Loaded configuration from database")
        print(f"[Tickets] Main Role: {config.get('main_recruiter_role')}")
        print(f"[Tickets] FWA Role: {config.get('fwa_recruiter_role')}")
        print(f"[Tickets] Admin: {config.get('admin_to_notify')}")
        print(f"[Tickets] Categories: Main={config.get('main_category')}, FWA={config.get('fwa_category')}")
        print(
            f"[Tickets] Counters: Main={config.get('main_ticket_counter', 0)}, FWA={config.get('fwa_ticket_counter', 0)}")
    else:
        print(f"[Tickets] No configuration found in database, using defaults")


# Import all ticket modules
from . import setup
from . import config
from . import manage
from . import handlers
from . import close

# Register the ticket group with the loader
loader.command(ticket)

__all__ = ["loader", "ticket", "ticket_config"]
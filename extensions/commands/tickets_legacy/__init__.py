# extensions/commands/tickets_legacy/__init__.py
import lightbulb
from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler
import hikari

from . import resolution_delivery

loader = lightbulb.Loader()
ticket = lightbulb.Group("ticket", "Warriors United legacy channel ticket commands")

# Store config globally for all ticket modules
ticket_config = None
_config_loaded = False  # Guard flag
_resolution_delivery_discovery: StartupReconciler | None = None


async def recover_resolution_delivery_discovery(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
) -> None:
    result = await resolution_delivery.recover_pending_deliveries(
        bot=bot,
        mongo=mongo,
        limit=resolution_delivery.RECOVERY_LIMIT,
    )
    if (
        result["failed"]
        or result["pending"]
        or result["processed"] >= resolution_delivery.RECOVERY_LIMIT
    ):
        raise RuntimeError("legacy resolution delivery recovery remains pending")


def start_resolution_delivery_discovery(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
) -> StartupReconciler:
    global _resolution_delivery_discovery
    if _resolution_delivery_discovery is None:
        _resolution_delivery_discovery = StartupReconciler(
            "legacy-resolution-delivery",
            lambda: recover_resolution_delivery_discovery(bot, mongo),
        )
    _resolution_delivery_discovery.start()
    return _resolution_delivery_discovery


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

    await resolution_delivery.start_retries()
    resolution_delivery.start_online_recovery(bot=event.app, mongo=mongo)
    start_resolution_delivery_discovery(event.app, mongo)

    try:
        await handlers.ensure_creation_index(mongo)
    except Exception as error:
        # Intake also performs this check before any Discord side effect. Keep
        # startup available while failing closed on the affected workflow.
        print(
            "[Tickets:Legacy] Creation evidence index recovery failed: "
            f"{type(error).__name__}"
        )

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


@loader.listener(hikari.StoppingEvent)
async def on_stopping(_: hikari.StoppingEvent) -> None:
    """Fence recovery tasks before REST and Mongo dependencies stop."""
    global _config_loaded, _resolution_delivery_discovery
    _config_loaded = False
    try:
        if _resolution_delivery_discovery is not None:
            await _resolution_delivery_discovery.stop()
            _resolution_delivery_discovery = None
    finally:
        try:
            await resolution_delivery.stop_online_recovery()
        finally:
            await resolution_delivery.stop_retries()


# Import all ticket modules.
from . import setup
from . import config
from . import manage
from . import handlers
# resolve holds the shared side effects and the ticket_override action; close
# imports it too, but registering it explicitly keeps the action's origin obvious.
from . import resolve
from . import close
from . import claim

# Register the ticket group with the loader
loader.command(ticket)

__all__ = ["loader", "ticket", "ticket_config"]

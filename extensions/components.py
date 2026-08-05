import asyncio
import dataclasses
import datetime
import functools
import inspect
import logging
import os
import uuid
from typing import Any, Callable, get_type_hints

import hikari.events
import lightbulb
import pendulum as pend

from hikari.events.interaction_events import ComponentInteractionCreateEvent
from utils.constants import RED_ACCENT
from utils.mongo import MongoClient
from utils.component_state import get_state, prepare_storage

loader = lightbulb.Loader()

_log = logging.getLogger(__name__)

# The only copy a clicker ever sees from the dispatcher itself. It says what to
# DO, because "unknown action" is never actionable to the person who clicked.
MSG_STALE_PANEL = (
    "⚠️ This panel is out of date and can no longer be used.\n"
    "Please re-run the command to get a fresh one."
)

# The ref is the whole point: without it, "the button didn't work" cannot be
# matched to a traceback across the ~120 handlers in 40 files.
MSG_INTERNAL_ERROR = (
    "❌ Something went wrong handling that.\n"
    "It has been logged (ref `{ref}`). Please try again, or re-run the command."
)


@dataclasses.dataclass(frozen=True, slots=True)
class Action:
    """One registered component handler.

    Replaces the 7-tuple this registry used to hold. That tuple was unpacked by
    position in two places with hand-matched names, and had already drifted from
    its own type annotation, which declared five elements while seven were stored.
    """

    fn: Callable[..., Any]
    name: str
    user_only: bool  # stored, NOT enforced - see docs/component-dispatcher.md
    no_return: bool
    is_modal: bool
    ephemeral: bool
    opens_modal: bool
    requires_state: bool
    group: str | None
    declared_at: str  # "file:line" of the @register_action, for duplicate reporting


registered_functions: dict[str, Action] = {}

# Routing keys declared via register_action(group=...). Held separately from
# registered_functions so a group key can never be mistaken for an action name.
group_keys: set[str] = set()

# Retired action name -> current name.
#
# WHY THIS EXISTS: component custom_ids never expire. Discord does not garbage
# collect messages, and a button posted a year ago still fires an interaction
# carrying whatever action name it was built with. Renaming an action therefore
# breaks every message already in the guild, permanently, with no deprecation
# path - and a dashboard's panels are exactly the messages that linger.
#
# Declaring the old name as an alias keeps those messages working:
#
#     @register_action("ticket_console", aliases=("ticket_dashboard",))
#
# This is what makes an iterating dashboard project safe. Leave aliases in place
# indefinitely; they cost one dict entry and removing one re-breaks old panels.
action_aliases: dict[str, str] = {}


def _declaration_site(depth: int = 2) -> str:
    """`file:line` of the @register_action application.

    Read from the call frame, NOT from the decorated function. register_action is
    applied above @lightbulb.di.with_di, so the function it receives is already
    linkd's wrapper and reports `linkd.solver` as its module regardless of which
    file registered the action - which made the duplicate warning useless, since
    both sides of a collision printed the same name.
    """
    frame = inspect.currentframe()
    try:
        for _ in range(depth):
            if frame is None:
                return "<unknown>"
            frame = frame.f_back
        if frame is None:
            return "<unknown>"
        filename = frame.f_code.co_filename
        try:
            filename = os.path.relpath(filename)
        except (ValueError, OSError):
            # ValueError: different drive on Windows. OSError: relpath calls
            # getcwd(). Either way the absolute path is still useful, and this
            # runs at import for every action - it must not be able to raise.
            pass
        return f"{filename}:{frame.f_lineno}"
    finally:
        # Frames hold references to locals; drop ours rather than leaving a cycle.
        del frame


def register_action(
        name: str,
        user_only: bool = False,
        no_return: bool = False,
        is_modal: bool = False,
        ephemeral: bool = False,
        opens_modal: bool = False,
        group: str | None = None,
        aliases: tuple[str, ...] = (),
        requires_state: bool = False,
):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(func)
        hints = get_type_hints(func)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # bind the incoming args/kwargs to parameter names
            bound = sig.bind_partial(*args, **kwargs)

            # for each argument, if the hint is pendulum.DateTime
            # but the value is a stdlib datetime, convert it
            for param_name, value in bound.arguments.items():
                hint = hints.get(param_name)
                if hint is pend.DateTime \
                        and isinstance(value, datetime.datetime) \
                        and not isinstance(value, pend.DateTime):
                    bound.arguments[param_name] = pend.instance(value)

            # call the original, with converted values
            return await func(*bound.args, **bound.kwargs)

        if group:
            group_keys.add(group)

        # Warn, do not raise. A duplicate name means import order silently decides
        # which handler runs, which is a real bug - but raising here stops the bot
        # booting, and this dispatcher's whole premise is not disturbing the
        # running system. Resolve the duplicate first, then consider raising.
        declared_at = _declaration_site()

        existing = registered_functions.get(name)
        if existing is not None:
            _log.warning(
                "duplicate component action %r: %s replaces %s - "
                "import order is deciding which one runs",
                name, declared_at, existing.declared_at,
            )

        registered_functions[name] = Action(
            fn=wrapper,
            name=name,
            user_only=user_only,
            no_return=no_return,
            is_modal=is_modal,
            ephemeral=ephemeral,
            opens_modal=opens_modal,
            requires_state=requires_state,
            group=group,
            declared_at=declared_at,
        )

        for alias in aliases:
            action_aliases[alias] = name

        return wrapper

    return decorator


def _resolve(name: str) -> Action | None:
    """Follow retired aliases to the live action. Returns None if there isn't one."""
    seen: set[str] = set()
    while name in action_aliases and name not in seen:
        seen.add(name)
        name = action_aliases[name]
    return registered_functions.get(name)


async def _refuse(ctx, message: str) -> None:
    """Tell the clicker something, without touching the message they clicked.

    Safe both before and after defer: lightbulb sends an initial response when the
    interaction is unacknowledged and a followup when it is not. Ephemeral either
    way - a dashboard message can be visible to a whole channel, and an error
    belongs to the person who clicked, not to everyone watching.
    """
    try:
        await ctx.respond(message, ephemeral=True)
    except Exception:
        _log.exception("failed to deliver dispatcher message to user")


def build_ctx(interaction: hikari.ComponentInteraction | hikari.ModalInteraction, client: lightbulb.Client, is_modal = False):
    if not is_modal:
        return lightbulb.components.MenuContext(client, None, interaction, None, None, None, asyncio.Event())
    else:
        return lightbulb.components.ModalContext(client, None, interaction, asyncio.Event())


@lightbulb.di.with_di
async def component_handler(
        ctx: lightbulb.components.MenuContext | lightbulb.components.ModalContext,
        mongo: MongoClient = lightbulb.di.INJECTED,
):
    """Entry point. No exception may escape this function.

    Before this boundary existed, a raising handler produced the worst failure a
    component can have: `defer(edit=True)` sends DEFERRED_MESSAGE_UPDATE, which
    acknowledges silently and shows no loading state, so the button simply
    un-pressed and nothing happened - no error, no spinner, nothing. Discord had
    already been acknowledged, so it never showed "This interaction failed"
    either. Indistinguishable from a slow bot, which invites re-clicking.
    """
    try:
        await _dispatch(ctx, mongo)
    except Exception:
        ref = uuid.uuid4().hex[:8]
        _log.exception(
            "component dispatch failed ref=%s custom_id=%r user=%s",
            ref, getattr(ctx.interaction, "custom_id", "<unknown>"), ctx.user.id,
        )
        await _refuse(ctx, MSG_INTERNAL_ERROR.format(ref=ref))


async def _dispatch(
        ctx: lightbulb.components.MenuContext | lightbulb.components.ModalContext,
        mongo: MongoClient,
):
    raw = ctx.interaction.custom_id
    # partition never raises; split(":", 1) raised ValueError on a colon-less id
    command_name, _, action_id = raw.partition(":")

    # Route on whether the CUSTOM_ID names a group, not on whether the resolved
    # action happens to belong to one. The old check read the action's own group
    # field, so a button pointing straight at a grouped action took the select
    # branch, found no .values, and returned silently - which is why
    # fwa_data.py:773's "Back to Main Menu" button has never worked.
    if command_name in group_keys:
        # ModalInteraction has no .values at all, so getattr rather than access.
        values = getattr(ctx.interaction, "values", None)
        if not values:
            _log.warning("group %r routed with no selection (custom_id=%r)", command_name, raw)
            await _refuse(ctx, MSG_STALE_PANEL)
            return
        command_name = values[0]

    action = _resolve(command_name)
    if action is None:
        # Previously: .get() returned None and was tuple-unpacked immediately,
        # raising TypeError before any response, so the user got a 3-second hang
        # and "This interaction failed".
        _log.warning(
            "unknown component action %r (custom_id=%r, user=%s)",
            command_name, raw, ctx.user.id,
        )
        await _refuse(ctx, MSG_STALE_PANEL)
        return

    # Only defer if not a modal AND not opening a modal
    if not action.is_modal and not action.opens_modal:
        await ctx.defer(edit=True)

    kw = await get_state(mongo, action_id, {"_id": 0})
    if kw is None and action.requires_state:
        _log.info("expired component state action=%s id=%s", action.name, action_id)
        await _refuse(ctx, MSG_STALE_PANEL)
        return
    kw = kw or {}
    kw = kw | {"color" : RED_ACCENT, "action_id" : action_id, "ctx": ctx}
    if not kw:
        return
    components = await action.fn(**kw)

    if not action.no_return:
        if action.is_modal:
            # ModalContext inherits the plain response mixin, which has no edit=
            # parameter at all - passing one raises TypeError. Unreached so far
            # only because all 12 is_modal registrations also set no_return=True,
            # so the first modal handler written without it would have crashed.
            await ctx.respond(components=components)
        else:
            # `ephemeral` is a no-op alongside edit=True (an existing message's
            # ephemeral state cannot be changed) and is kept only so this commit
            # changes nothing on the success path. Remove it with the state work.
            await ctx.respond(components=components, edit=True, ephemeral=action.ephemeral)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def prepare_component_state(
    _: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Install expiry and migrate only audited legacy state after startup."""
    await prepare_storage(mongo)



@loader.listener(hikari.events.ComponentInteractionCreateEvent)
async def component_interaction(
        event: ComponentInteractionCreateEvent,
        client: lightbulb.Client = lightbulb.di.INJECTED,
):
    ctx = build_ctx(event.interaction, client)
    await component_handler(ctx=ctx)


@loader.listener(hikari.events.ModalInteractionCreateEvent)
async def modal_interaction(
        event: hikari.events.ModalInteractionCreateEvent,
        client: lightbulb.Client = lightbulb.di.INJECTED,
):
    ctx = build_ctx(event.interaction, client, True)
    await component_handler(ctx=ctx)

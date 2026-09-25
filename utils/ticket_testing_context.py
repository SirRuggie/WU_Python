"""Explicit dependency and component routing for isolated ticket interactions."""
from __future__ import annotations

import copy
from contextlib import asynccontextmanager

import hikari
import linkd

from utils.mongo import MongoClient

PREFIX = "tt|"


def prefix_components(components):
    if components is None or components is hikari.UNDEFINED:
        return components
    result = copy.deepcopy(components)
    def walk(component):
        custom_id = getattr(component, "custom_id", None)
        if (getattr(component, "type", None) in (2, 3, 5, 6, 7, 8)
                and isinstance(custom_id, str) and custom_id and not custom_id.startswith(PREFIX)):
            prefixed = PREFIX + custom_id
            if len(prefixed) > 100:
                raise ValueError("Test ticket control exceeds Discord's custom ID limit")
            component.set_custom_id(prefixed)
        for child in getattr(component, "components", ()) or ():
            walk(child)
        accessory = getattr(component, "accessory", None)
        if accessory is not None:
            walk(accessory)
    for component in result:
        walk(component)
    return result


def prefix_payload(kwargs):
    result = dict(kwargs)
    if "components" in result:
        result["components"] = prefix_components(result["components"])
    if "component" in result and result["component"] not in (None, hikari.UNDEFINED):
        result["component"] = prefix_components([result["component"]])[0]
    if isinstance(result.get("custom_id"), str) and not result["custom_id"].startswith(PREFIX):
        result["custom_id"] = PREFIX + result["custom_id"]
    # Sandbox conversations never notify live recruiter roles or everyone.
    for key in ("role_mentions", "mentions_everyone"):
        if key in result:
            result[key] = False
    return result


class PrefixRest:
    def __init__(self, rest):
        self._rest = rest

    def __getattr__(self, name):
        target = getattr(self._rest, name)
        if name in {"create_message", "edit_message", "create_interaction_response",
                    "edit_interaction_response", "execute_webhook", "edit_webhook_message"}:
            async def wrapped(*args, **kwargs):
                return await target(*args, **prefix_payload(kwargs))
            return wrapped
        return target


class PrefixBot:
    def __init__(self, bot):
        self._bot = bot
        self.rest = PrefixRest(bot.rest)

    def __getattr__(self, name):
        return getattr(self._bot, name)


class TestInteraction:
    def __init__(self, interaction, bot):
        self._interaction = interaction
        self.app = bot
        self.custom_id = getattr(interaction, "custom_id", "")
        if self.custom_id.startswith(PREFIX):
            self.custom_id = self.custom_id[len(PREFIX):]

    def __getattr__(self, name):
        target = getattr(self._interaction, name)
        if name in {"create_initial_response", "edit_initial_response", "execute", "edit_message", "create_modal_response"}:
            async def wrapped(*args, **kwargs):
                return await target(*args, **prefix_payload(kwargs))
            return wrapped
        return target


class TestContext:
    def __init__(self, ctx, bot):
        self._ctx = ctx
        self.interaction = TestInteraction(ctx.interaction, bot)
        self.app = bot

    def __getattr__(self, name):
        target = getattr(self._ctx, name)
        if name in {"respond", "respond_with_modal", "edit_response"}:
            async def wrapped(*args, **kwargs):
                return await target(*args, **prefix_payload(kwargs))
            return wrapped
        return target


@asynccontextmanager
async def test_dependencies(mongo, bot, ctx=None):
    """Nested calls resolve the isolated database and guarded REST client too."""
    from extensions.commands.tickets import testing_service
    scoped_bot = PrefixBot(testing_service.test_bot(bot, mongo))
    container = linkd.Container(linkd.Registry(), parent=linkd.DI_CONTAINER.get(None))
    container.add_value(MongoClient, mongo)
    container.add_value(hikari.GatewayBot, scoped_bot)
    token = linkd.DI_CONTAINER.set(container)
    try:
        async with container:
            yield (TestContext(ctx, scoped_bot) if ctx is not None else None), scoped_bot
    finally:
        linkd.DI_CONTAINER.reset(token)

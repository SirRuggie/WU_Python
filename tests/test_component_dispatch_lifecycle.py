"""The dispatcher's acknowledgement contract, pinned after a live timeout.

Live failure (2026-08-14): tapping **Save confirmed cards** produced
"WU Wizard didn't respond in time" and a production
`hikari.errors.NotFoundError: (10062) Unknown interaction` raised while the
initial response was being attempted. The 3-second acknowledgement window was
already gone when the defer arrived - a stalled event loop on a busy host is
enough - and a dead token used to kill the whole flow.

These tests pin two things at the real dispatch boundary:

1. the defer is the FIRST await - before state load and before the handler;
2. a dead token no longer loses the player's work - the handler still runs
   and the result is delivered by editing the originating message over REST.
"""

import asyncio
from types import SimpleNamespace

import hikari

from extensions import components
from extensions.commands import cards as cards_command


def _dead_token_error():
    # hikari's HTTP errors are attrs classes with required constructor data
    # the test does not have; an uninitialised instance raises fine and the
    # dispatcher never formats it.
    return hikari.NotFoundError.__new__(hikari.NotFoundError)


class _RecorderCtx:
    def __init__(self, custom_id, *, dead_token=False):
        self.events = []
        self.user = SimpleNamespace(id=123)
        self._dead = dead_token
        rest = SimpleNamespace(edit_message=self._edit_message)
        self.interaction = SimpleNamespace(
            custom_id=custom_id,
            message=SimpleNamespace(channel_id=555, id=42),
            app=SimpleNamespace(rest=rest),
        )

    async def defer(self, edit=False):
        self.events.append(("defer", edit))
        if self._dead:
            raise _dead_token_error()

    async def respond(self, components=None, edit=False, **kwargs):
        self.events.append(("respond", edit, components))

    async def _edit_message(self, channel_id, message_id, components=None):
        self.events.append(("rest_edit", channel_id, message_id, components))


def _register_probe(name, handler):
    components.register_action(name)(handler)
    return lambda: components.registered_functions.pop(name, None)


def _install_state(monkeypatch, state, recorder=None):
    async def fake_get_state(_mongo, _action_id, _projection):
        if recorder is not None:
            recorder.append("state")
        return dict(state)

    monkeypatch.setattr(components, "get_state", fake_get_state)


def test_the_defer_is_the_first_await_before_state_and_handler(monkeypatch):
    order = []

    async def probe(ctx=None, action_id=None, **_kwargs):
        order.append("handler")
        return ["VIEW"]

    cleanup = _register_probe("lifecycle_probe", probe)
    try:
        ctx = _RecorderCtx("lifecycle_probe:x")
        _install_state(monkeypatch, {}, recorder=order)
        order_events = ctx.events

        asyncio.run(components._dispatch(ctx, mongo=SimpleNamespace()))

        assert order_events[0] == ("defer", True), (
            "acknowledgement must come before any slow work"
        )
        assert order == ["state", "handler"], (
            "state load and handler run only after the defer"
        )
        assert order_events[-1] == ("respond", True, ["VIEW"])
    finally:
        cleanup()


def test_a_dead_token_still_delivers_by_editing_the_message(monkeypatch):
    ran = []

    async def probe(ctx=None, action_id=None, **_kwargs):
        ran.append(True)
        return ["VIEW"]

    cleanup = _register_probe("lifecycle_probe_dead", probe)
    try:
        ctx = _RecorderCtx("lifecycle_probe_dead:x", dead_token=True)
        _install_state(monkeypatch, {})

        asyncio.run(components._dispatch(ctx, mongo=SimpleNamespace()))

        assert ran == [True], "the player's work must not be dropped"
        assert ("rest_edit", 555, 42, ["VIEW"]) in ctx.events
        assert not any(e[0] == "respond" for e in ctx.events), (
            "a dead token cannot be responded to"
        )
    finally:
        cleanup()


def test_a_public_button_answers_privately_and_its_followup_stays_clickable(monkeypatch):
    """The public-surface pattern, pinned at the dispatch boundary.

    A button on a channel post must never let the dispatcher's normal reply
    run: that reply is an EDIT of the clicked message, which on a public post
    would replace it with the clicker's private panel for the whole channel.
    The escape is `no_return=True` plus an ephemeral followup - the sticky's
    "I am lost" button has run this exact shape in production since it
    shipped. What that button never carried is a control OF ITS OWN on the
    followup, so this test pins the second half: a click arriving from the
    followup message routes like any other component and edits the followup,
    leaving the public post untouched both times.
    """
    followup_sends = []

    async def public_probe(ctx=None, action_id=None, **_kwargs):
        # The handler answers through the interaction, not the dispatcher:
        # a followup is a NEW message, so the public post is never targeted.
        await ctx.interaction.execute(
            components=["PRIVATE-PANEL"],
            flags=(
                hikari.MessageFlag.IS_COMPONENTS_V2
                | hikari.MessageFlag.EPHEMERAL
            ),
        )

    async def followup_probe(ctx=None, action_id=None, **_kwargs):
        return ["NEXT-SCREEN"]

    components.register_action("pub_probe", no_return=True)(public_probe)
    components.register_action("pub_probe_next")(followup_probe)
    try:
        # Click 1: the button on the public channel post.
        public_ctx = _RecorderCtx("pub_probe:trade-1")
        public_ctx.interaction.execute = (
            lambda **kwargs: _record_execute(followup_sends, kwargs)
        )
        _install_state(monkeypatch, {})
        asyncio.run(components._dispatch(public_ctx, mongo=SimpleNamespace()))

        assert ("defer", True) in public_ctx.events, (
            "the public click is still acknowledged within the window"
        )
        assert not any(e[0] == "respond" for e in public_ctx.events), (
            "no_return means the dispatcher must never edit the public post"
        )
        assert len(followup_sends) == 1
        assert followup_sends[0]["components"] == ["PRIVATE-PANEL"]
        assert followup_sends[0]["flags"] & hikari.MessageFlag.EPHEMERAL, (
            "the reply belongs to the clicker, not the channel"
        )

        # Click 2: a button the followup itself carries. Discord delivers it
        # as an ordinary component interaction on the followup message with a
        # fresh token; the dispatcher neither knows nor cares that the message
        # was a followup, and its edit lands on that message.
        followup_ctx = _RecorderCtx("pub_probe_next:trade-1")
        asyncio.run(components._dispatch(followup_ctx, mongo=SimpleNamespace()))

        assert followup_ctx.events[0] == ("defer", True)
        assert followup_ctx.events[-1] == ("respond", True, ["NEXT-SCREEN"]), (
            "the followup's own button edits the followup, nothing else"
        )
    finally:
        components.registered_functions.pop("pub_probe", None)
        components.registered_functions.pop("pub_probe_next", None)


async def _record_execute(sink, kwargs):
    sink.append(kwargs)


def test_save_confirmed_cards_survives_a_dead_token(monkeypatch):
    """The exact live P0, end to end through the real registration."""
    sentinel = ["PARTIAL-SAVE-VIEW"]

    async def fake_save(ctx, action_id, **_kwargs):
        return sentinel

    monkeypatch.setattr(
        cards_command, "_save_partial_scan_draft", fake_save
    )
    _install_state(monkeypatch, {
        "scan_draft": {"card_states": {}},
        "user_id": 123,
        "guild_id": 1,
        "coc_client": SimpleNamespace(),
        "mongo": SimpleNamespace(),
    })
    ctx = _RecorderCtx("cards_scan_save_partial:draft-1", dead_token=True)

    asyncio.run(components._dispatch(ctx, mongo=SimpleNamespace()))

    assert ("rest_edit", 555, 42, sentinel) in ctx.events, (
        "Save confirmed cards must reach the player even when the "
        "interaction token expired before the defer"
    )

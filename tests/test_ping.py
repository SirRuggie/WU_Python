import asyncio
import math
from pathlib import Path
from types import SimpleNamespace

import hikari

from extensions.commands import ping


def _built_payload(component):
    payload = component.build()
    return payload[0] if isinstance(payload, tuple) else payload


def _walk_payload(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_payload(child)


def _view_text(view) -> str:
    payload = [_built_payload(component) for component in view]
    return "\n".join(
        node["content"]
        for node in _walk_payload(payload)
        if "content" in node
    )


class _Context:
    def __init__(self):
        self.responses = []

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


def test_ping_command_is_public_and_available_to_everyone():
    command = ping.PingCommand._command_data

    assert command.name == "ping"
    assert command.description == "Check whether the bot is online and responding"
    assert command.default_member_permissions is hikari.UNDEFINED


def test_ping_view_is_one_compact_green_status_container():
    view = ping.build_ping_view(
        latency_ms=42,
        session_started_at=1_788_200_000,
    )
    payload = _built_payload(view[0])
    text = _view_text(view)

    assert len(view) == 1
    assert payload["accent_color"] == int(ping.GREEN_ACCENT)
    assert len(payload["components"]) == 1
    assert "WU Wizard is online" in text
    assert "connected to Discord and responding to commands" in text
    assert "**Gateway latency:** `42 ms`" in text
    assert "**Session started:** <t:1788200000:R>" in text


def test_gateway_latency_handles_unavailable_and_invalid_values():
    assert ping.gateway_latency_ms(0.042) == 42
    assert ping.gateway_latency_ms(float("nan")) is None
    assert ping.gateway_latency_ms(math.inf) is None
    assert ping.gateway_latency_ms(-0.1) is None
    assert ping.gateway_latency_ms("unknown") is None

    text = _view_text(ping.build_ping_view(
        latency_ms=None,
        session_started_at=1_788_200_000,
    ))
    assert "**Gateway latency:** `Measuring…`" in text


def test_ping_invocation_responds_once_without_deferring_or_dependencies():
    ctx = _Context()
    bot = SimpleNamespace(heartbeat_latency=0.0376)

    asyncio.run(ping.PingCommand.invoke._func(
        SimpleNamespace(),
        ctx,
        bot=bot,
    ))

    assert len(ctx.responses) == 1
    args, kwargs = ctx.responses[0]
    assert args == ()
    assert "ephemeral" not in kwargs
    assert "**Gateway latency:** `38 ms`" in _view_text(kwargs["components"])


def test_ping_module_stays_independent_of_external_services():
    source = Path(ping.__file__).read_text(encoding="utf-8")

    assert "MongoClient" not in source
    assert "coc." not in source
    assert "aiohttp" not in source

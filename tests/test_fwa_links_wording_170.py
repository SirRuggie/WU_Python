import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from extensions.commands.fwa import links


def test_war_weight_links_keep_destination_and_exact_prompt(monkeypatch):
    monkeypatch.setattr(links, "Clan", lambda data: SimpleNamespace(tag=data["tag"], name=data["name"]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda query: SimpleNamespace(
        to_list=AsyncMock(return_value=[{"tag": "#ABC", "name": "Example"}])
    )))
    ctx = SimpleNamespace(respond=AsyncMock())

    asyncio.run(links.on_war_weights.__wrapped__._func("test", bot=None, mongo=mongo, ctx=ctx))

    sent = ctx.respond.await_args.kwargs
    assert sent["ephemeral"] is True
    container = sent["components"][0]
    assert container.components[2].content == "Select any clan to enter war weights:"
    button = container.components[4].components[0]
    assert button.label == "Example"
    assert button.url == "https://fwastats.com/Clan/ABC/Weight"

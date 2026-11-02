"""Validate the bot constructor's actual driver options without booting Discord."""

import ast
import asyncio
from pathlib import Path

from utils.mongo import MongoClient


def test_bot_driver_has_named_bounded_pool_and_separate_selection_operation_budgets():
    tree = ast.parse(Path("main.py").read_text())
    call = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "mongo_client"
            for target in node.targets
        )
    )
    assert (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "MongoClient"
    )

    # Evaluate only the constructor expression with a numeric loopback URI and
    # connect=False. No main-module lifecycle, credentials, DNS or Mongo command.
    def local_client(**kwargs):
        return MongoClient(**kwargs, connect=False)

    async def run():
        expression = ast.Expression(body=call)
        client = eval(
            compile(ast.fix_missing_locations(expression), "main.py", "eval"),
            {"MongoClient": local_client, "_mongodb_uri": "mongodb://127.0.0.1:27154"},
        )
        try:
            assert client.options.timeout == 30
            assert client.options.server_selection_timeout == 3
            assert client.options.pool_options.max_pool_size == 20
            assert client.options.pool_options.appname == "wu-bot"
        finally:
            await client.close()

    asyncio.run(run())

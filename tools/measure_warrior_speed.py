"""Offline synthetic read-phase benchmark; never construct a real Discord or Mongo client."""

import asyncio, json, sys, time, subprocess, types, argparse
from types import SimpleNamespace as S
from unittest.mock import AsyncMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extensions.warrior import core, nickname_setup as nick
from tests.test_warrior_setup import context, mongo

parser = argparse.ArgumentParser()
parser.add_argument("--baseline")
args = parser.parse_args()
if args.baseline:
    for name, file in [
        ("core", "extensions/warrior/core.py"),
        ("nick", "extensions/warrior/nickname_setup.py"),
    ]:
        module = types.ModuleType("extensions.warrior._baseline_" + name)
        module.__package__ = "extensions.warrior"
        with patch(
            "extensions.components.register_action", lambda *a, **k: lambda fn: fn
        ):
            exec(
                compile(
                    subprocess.check_output(
                        ["git", "show", args.baseline + ":" + file], text=True
                    ),
                    file,
                    "exec",
                ),
                module.__dict__,
            )
        globals()[name] = module


async def main():
    c = context()
    m = mongo()
    m.member_profiles = S()
    m.ticket_setup.find_one.return_value = {"main_recruiter_role": 40}
    timings = []

    async def delay(label, value):
        at = time.perf_counter()
        await asyncio.sleep(0.01 if label == "mongo" else 0.02)
        timings.append(
            {"call": label, "ms": round((time.perf_counter() - at) * 1000, 2)}
        )
        return value

    async def config(*_):
        return await delay("mongo", {"main_recruiter_role": 40})

    m.ticket_setup.find_one.side_effect = config

    class Rest:
        async def fetch_guild(self, *_):
            return await delay("guild", c["guild"])

        async def fetch_roles(self, *_):
            return await delay("roles", c["roles"])

        async def fetch_member(self, g, u):
            return await delay(
                "member:" + str(u),
                next(x for x in [c["actor"], c["member"], c["me"]] if x.id == u),
            )

    b = S(
        rest=Rest(),
        get_me=lambda: c["me"],
        cache=S(
            get_guild=lambda g: c["guild"],
            get_roles_view_for_guild=lambda g: {r.id: r for r in c["roles"]},
            get_member=lambda g, u: next(
                x for x in [c["actor"], c["member"], c["me"]] if x.id == u
            ),
        ),
    )
    result = {}
    for label in ["open_panel", "open_step"]:
        at = time.perf_counter()
        await core.context(
            b, m, 10, 20, 30, **({} if args.baseline else {"fresh": False})
        )
        result[label] = round((time.perf_counter() - at) * 1000, 2)
    for n in [1, 10, 47]:

        async def choices(*_):
            await asyncio.sleep(0.02 + n * 0.005)
            return {
                "accounts": [
                    {
                        "tag": "#PYY" + str(i),
                        "name": "Fixture " + str(i),
                        "townHallLevel": 18,
                    }
                    for i in range(n)
                ],
                "suggested": None,
                "unavailable": False,
            }

        with patch.object(nick, "GUILD_ID", 10), patch.object(
            nick.MemberProfiles, "get", AsyncMock(return_value=None)
        ), patch.object(nick, "name_choices", choices), patch.object(
            nick,
            "persist",
            AsyncMock(side_effect=lambda m, d, s: dict(s, nonce="fixture")),
        ), patch(
            "extensions.commands.warrior.show", AsyncMock()
        ), patch(
            "utils.component_state.get_state", AsyncMock(return_value=None)
        ):
            at = time.perf_counter()
            await nick.begin(S(), {"_id": "fixture"}, c, m, None)
            result["nickname_" + str(n)] = round((time.perf_counter() - at) * 1000, 2)
    if not args.baseline:
        await nick.stop()
    print(
        json.dumps(
            {
                "fixture": "REST20ms, Mongo10ms, linked lookup20ms+5ms/account; no network",
                "totals_ms": result,
                "calls": timings,
            },
            indent=2,
        )
    )


asyncio.run(main())

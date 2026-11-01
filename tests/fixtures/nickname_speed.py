"""Owned loopback Mongo plus fake Discord timing. Never connects to Discord."""

import sys, asyncio, time, json, logging, subprocess, types, runpy
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace as S
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "web/cwl/tests/fixtures/qa_network_guard.py"))
import hikari
from pymongo import AsyncMongoClient
from utils.member_profiles import MemberProfiles
from utils.member_profile_runs import ProfileRuns
from utils import (
    manage_web_worker as worker,
    dashboard_access,
    manage_operations_runtime,
    return_bulk,
)
from extensions.warrior import profile_dashboard

GUILD = worker.GUILD_ID
ACTOR = 234567890123456789
BOT = 345678901234567890


class Mongo:
    def __init__(self, db):
        self.db = db

    def __getattr__(self, name):
        return self.db[name]


class Rest:
    def __init__(self, count):
        self.calls = {}
        self.edits = []
        self.roles = [
            S(id=GUILD, permissions=hikari.Permissions.NONE, position=0),
            S(
                id=101,
                permissions=hikari.Permissions.MANAGE_NICKNAMES,
                position=10,
            ),
            S(
                id=102,
                permissions=hikari.Permissions.ADMINISTRATOR,
                position=20,
            ),
            S(id=103, permissions=hikari.Permissions.NONE, position=1),
        ]
        self.members = {
            ACTOR: S(
                id=ACTOR,
                guild_id=GUILD,
                role_ids=[102],
                display_name="Staff",
                nickname="Staff",
                is_bot=False,
            ),
            BOT: S(
                id=BOT,
                guild_id=GUILD,
                role_ids=[101],
                display_name="Bot",
                nickname="Bot",
                is_bot=True,
            ),
        }
        for i in range(count):
            uid = 123456789012340000 + i
            self.members[uid] = S(
                id=uid,
                guild_id=GUILD,
                role_ids=[103],
                display_name=f"Member {i}",
                nickname=f"Member {i} | EST 🇺🇸",
                is_bot=False,
            )

    async def fetch_member(self, guild, uid):
        key = (
            "target"
            if uid not in (ACTOR, BOT)
            else "actor" if uid == ACTOR else "bot"
        )
        self.calls[key] = self.calls.get(key, 0) + 1
        await asyncio.sleep(0.05)
        return deepcopy(self.members[uid])

    async def fetch_roles(self, guild):
        self.calls["roles"] = self.calls.get("roles", 0) + 1
        await asyncio.sleep(0.05)
        return deepcopy(self.roles)

    async def fetch_guild(self, guild):
        self.calls["guild"] = self.calls.get("guild", 0) + 1
        await asyncio.sleep(0.05)
        return S(id=GUILD, owner_id=ACTOR)

    async def edit_member(self, guild, uid, *, nickname, reason):
        await asyncio.sleep(0.05)
        self.edits.append({"id": uid, "at": time.perf_counter()})
        self.members[uid].nickname = nickname


def old_module(path, name, package=None):
    source = subprocess.check_output(
        ["git", "show", "aeef3fe:" + path], cwd=ROOT, text=True
    )
    module = types.ModuleType(name)
    module.__package__ = package
    exec(compile(source, path, "exec"), module.__dict__)
    return module


async def case(mode, count):
    client = AsyncMongoClient("mongodb://127.0.0.1:27155")
    db = client["wu_speed_fixture_" + uuid4().hex]
    mongo = Mongo(db)
    rest = Rest(count)
    bot = S(rest=rest, get_me=lambda: S(id=BOT))
    store = MemberProfiles(mongo)
    try:
        rows = []
        for i in range(count):
            uid = str(123456789012340000 + i)
            await store.write(
                uid,
                dict(zone_id="gmt-5", country="US"),
                expected_revision=0,
                updated_by=str(ACTOR),
                source="staff",
            )
            rows.append(
                dict(
                    discord_id=uid,
                    name=f"Member {i}",
                    old_nickname=f"Member {i} | EST 🇺🇸",
                    new_nickname=f"Member {i} | GMT-5 🇺🇸",
                    revision=1,
                )
            )
        if mode == "before":
            old_runs = old_module(
                "utils/member_profile_runs.py", "fixture_old_runs"
            )
            old_actions = old_module(
                "extensions/warrior/profile_dashboard.py",
                "fixture_old_actions",
                "extensions.warrior",
            )
            engine = old_module(
                "utils/manage_web_worker.py", "fixture_old_worker"
            )
            runs = old_runs.ProfileRuns(mongo)
        else:
            engine = worker
            runs = ProfileRuns(mongo)
        parent = await runs.create(
            actor_id=str(ACTOR),
            guild_id=GUILD,
            request_id=str(uuid4()),
            preview=rows,
            selected=[r["discord_id"] for r in rows],
        )
        started = time.perf_counter()
        print(f"START mode={mode} members={count}", flush=True)
        with patch.object(
            dashboard_access, "dashboard_allowed", AsyncMock(return_value=True)
        ), patch.object(
            manage_operations_runtime, "refresh_base_image_cache", AsyncMock()
        ), patch.object(
            manage_operations_runtime, "runtime_snapshot", lambda _: {}
        ), patch.object(
            return_bulk, "activate", AsyncMock()
        ):
            if mode == "before":
                import utils.member_profile_runs as run_module

                with patch.object(
                    run_module, "ProfileRuns", old_runs.ProfileRuns
                ), patch.object(profile_dashboard, "apply", old_actions.apply):
                    while True:
                        await asyncio.sleep(10)
                        await engine.poll(bot, mongo)
                        current = await mongo.bot_config.find_one(
                            {"_id": parent["_id"]}
                        )
                        if current["state"] == "done":
                            break
                        if time.perf_counter() - started > 90:
                            raise RuntimeError(
                                "Before timing fixture exceeded90s"
                            )
            else:
                async with asyncio.timeout(110):
                    await worker.fast_poll(bot, mongo)
        elapsed = time.perf_counter() - started
        current = await mongo.bot_config.find_one({"_id": parent["_id"]})
        assert current["state"] == "done" and len(rest.edits) == count
        assert len({r["id"] for r in rest.edits}) == count
        result = dict(
            mode=mode,
            members=count,
            elapsed_seconds=elapsed,
            first_edit_seconds=rest.edits[0]["at"] - started,
            read_calls=rest.calls,
            edit_gaps_seconds=[
                b["at"] - a["at"] for a, b in zip(rest.edits, rest.edits[1:])
            ],
            fake_transport=True,
            production_effects=False,
        )
        if mode == "after":
            assert elapsed < (10 if count == 2 else 100), result
        print(json.dumps(result), flush=True)
        return result
    finally:
        await client.drop_database(db.name)
        await client.close()


async def main():
    logging.basicConfig(level=logging.INFO)
    result = []
    cases = (
        [("after", 2), ("after", 25)]
        if "--after" in sys.argv
        else [("before", 2), ("after", 2), ("after", 25)]
    )
    for mode, count in cases:
        result.append(await case(mode, count))
    output = ROOT / ".local/p86-evidence/fixture-timings.json"
    if "--after" in sys.argv and output.exists():
        result = [
            r for r in json.loads(output.read_text()) if r["mode"] == "before"
        ] + result
    (ROOT / ".local/p86-evidence/fixture-timings.json").write_text(
        json.dumps(result, indent=2)
    )


if __name__ == "__main__":
    asyncio.run(main())

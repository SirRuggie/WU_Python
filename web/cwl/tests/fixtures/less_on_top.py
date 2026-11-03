"""Owned, disconnected density-layout samples; never contact a live provider."""
import asyncio
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

root = Path(os.environ["WU_FIXTURE_BACKEND"])
role, static = sys.argv[1:3]
assert role in {"staff", "member"}
source = Path(__file__).with_name("roster_readability.py" if role == "staff" else "staff_nav.py")
sys.argv = [str(source), static, "8900"]
spec = importlib.util.spec_from_file_location("density_fixture_" + role, source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from aiohttp import web  # noqa: E402: the imported fixture installs the socket guard.

app = module.app
assert app["dev_fixture"]
seed = None


@web.middleware
async def presentation(request, handler):
    response = await handler(request)
    if request.method == "GET" and request.path == "/api/cwl/config":
        # Only the development banner is excluded for production-shaped pixels.
        # Authentication, permissions, controls and styles are unchanged.
        return web.json_response({**json.loads(response.text), "dev_fixture": False})
    return response


app.middlewares.insert(0, presentation)


async def setup(request):
    if request.remote not in {"127.0.0.1", "::1"}:
        raise web.HTTPNotFound()
    if role == "member":
        sid = 2 if request.query.get("mode") == "closed" else 6
        with app["store"].tx() as db:
            db.execute("UPDATE member_season SET season_id=? WHERE id=1", (sid,))
            # No campaign is an internal synthetic scenario, not a member label.
            db.execute("UPDATE seasons SET label='November 2026 · local sample' WHERE id=6")
            db.execute("INSERT OR IGNORE INTO clans(tag,name) VALUES('#R222222Y','Fixture Family')")
            db.execute("UPDATE roster_entries SET assigned_clan_tag='#R222222Y' WHERE season_id=6")
        return web.json_response({"season": sid})
    count = int(request.query.get("count", "125"))
    assert count in {26, 65, 125} and seed is not None
    with sqlite3.connect(module.folder.name + "/isolated.sqlite") as db:
        seed.backup(db)
    with app["store"].tx() as db:
        rows = list(db.execute("SELECT tag FROM signups WHERE season_id=1 ORDER BY tag"))
        required = {module.players[5], module.players[10], module.players[11]}
        wanted = required | {rows[i * len(rows) // count]["tag"] for i in range(count)}
        for row in rows:
            if len(wanted) <= count:
                break
            if row["tag"] in wanted - required:
                wanted.remove(row["tag"])
        for row in rows:
            if row["tag"] not in wanted:
                db.execute("DELETE FROM roster_entries WHERE season_id=1 AND tag=?", (row["tag"],))
                db.execute("DELETE FROM signups WHERE season_id=1 AND tag=?", (row["tag"],))
        db.execute("UPDATE member_season SET season_id=1 WHERE id=1")
        db.execute("UPDATE lineup_rules SET capacity=15 WHERE season_id=1 AND capacity IS NULL")
        db.execute("INSERT OR IGNORE INTO signup_activity_reviews(audit_id,reviewed_by) SELECT id,'505227988229554179' FROM roster_audit WHERE season_id=1 AND action IN ('member_withdrawal','member_pool_change')")
    module.set_publication_state("published")
    module.baseline = module.state()
    assert module.baseline["account_count"] == count
    module.requests.clear()
    return web.json_response({"count": count})


app.router.add_get("/qa/less-on-top/setup", setup)
start = web.TCPSite.start


async def ephemeral(site):
    await start(site)
    module.PORT = site._server.sockets[0].getsockname()[1]
    assert module.PORT not in {8766, 8767}


web.TCPSite.start = ephemeral


async def main():
    global seed
    if role == "staff":
        module.PORT = 0
        task = asyncio.create_task(module.main())
        while module.baseline is None:
            if task.done():
                return await task
            await asyncio.sleep(0.01)
        seed = sqlite3.connect(":memory:")
        with sqlite3.connect(module.folder.name + "/isolated.sqlite") as db:
            db.backup(seed)
    else:
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        task = asyncio.create_task(asyncio.Event().wait())
    print(json.dumps({"less_on_top_ready": True, "role": role, "port": module.PORT}), flush=True)
    await task


asyncio.run(main())

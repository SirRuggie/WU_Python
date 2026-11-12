"""Four-month233 picker sample; same script/data for base and changed frontend."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import qa_network_guard  # noqa: F401: denies external/default/production sockets

for name in ("DISCORD_TOKEN", "MONGODB_URI", "MONGODB_ROUTES", "COC_API_TOKEN"):
    os.environ.pop(name, None)
from aiohttp import web, ClientSession, CookieJar
from cwl_web import create_app
from cwl_web.providers import FixtureProviders

STATIC = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2])
assert (
    PORT == 0 or 1024 <= PORT <= 65535 and PORT not in (8766, 8767, 27017, 27166)
), "Use an isolated fixture port"
OUT = Path(sys.argv[3]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
OWNER = "505227988229554179"
SID = 1


provider = FixtureProviders(OWNER)
provider.players = {}
CLANS = [
    ("#C2Y", "Amber Knights with a long hosting name"),
    ("#R2Y", "Bronze Hold"),
    ("#G2Y", "Cedar Guard"),
    ("#J2Y", "Crystal Keep"),
    ("#Q2Y", "Dawn Watch"),
    ("#L2Y", "Ember Hall"),
]
ALPHABET = "0289PYLQGRJCUV"
PLAYERS = []
for i in range(26):
    tag = "#P" + ALPHABET[i // 14] + ALPHABET[i % 14] + "Y"
    PLAYERS.append(tag)
    provider.players[tag] = dict(
        tag=tag,
        name=(
            ["Long fixture account name", "<script> @everyone", "=SUM(1,2)"][i]
            if i < 3
            else f"Fixture player {i+1:02}"
        ),
        town_hall=18 - i % 5,
        current_clan_tag="#C2Y",
        current_clan_name="Amber Knights",
    )


async def family():
    return dict(
        source="fixture",
        status="ok",
        checked_at=datetime.now(timezone.utc).isoformat(),
        clans=[dict(tag=t, name=n, type="CWL") for t, n in CLANS],
    )


provider.family_clans = family
TEMP = ROOT / ".local/season-pickers-233-tmp"
TEMP.mkdir(parents=True, exist_ok=True)
DATA = Path(tempfile.mkdtemp(prefix="season-pickers-", dir=TEMP))
app = create_app(
    db_path=str(DATA / "fixture.sqlite"),
    providers=provider,
    dev_fixture=True,
    dev_identity=dict(
        id=OWNER, username="Isolated export owner", avatar_url="/exports-avatar.svg"
    ),
    secure_cookies=False,
    static_dir=STATIC,
)
mode = dict(preview_error=0, download_error=0)
requests = []


@web.middleware
async def sample(request, handler):
    if request.path == "/_exports/mode" and request.method == "POST":
        body = await request.json()
        if any(
            k not in mode or type(v) is not int or v not in (0, 403, 500)
            for k, v in body.items()
        ):
            raise web.HTTPBadRequest(text="Choose an isolated failure mode")
        mode.update(body)
        return web.json_response(mode)
    if request.path.startswith("/_exports/scenario/"):
        scenario = request.path.rsplit("/", 1)[-1]
        if scenario not in ("normal", "denied", "retry"):
            raise web.HTTPNotFound()
        mode.update(
            preview_error={"normal": 0, "denied": 403, "retry": 500}[scenario],
            download_error=0,
        )
        raise web.HTTPFound("/cwl/exports?season=1")
    if request.path == "/_exports/state":
        with app["store"].tx() as db:
            rev = db.execute(
                "SELECT revision FROM roster_meta WHERE season_id=?", (SID,)
            ).fetchone()[0]
        return web.json_response(
            dict(
                requests=requests,
                mode=mode,
                roster_revision=rev,
                db=str(DATA / "fixture.sqlite"),
            )
        )
    if request.path == "/exports-avatar.svg":
        return web.Response(
            text='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#365573"/></svg>',
            content_type="image/svg+xml",
        )
    if request.path.startswith("/api/"):
        requests.append(dict(method=request.method, path=request.path_qs))
        error = (
            mode["download_error"]
            if request.path.endswith(".xlsx")
            else (
                mode["preview_error"] if request.path.endswith("/export-preview") else 0
            )
        )
        if error:
            return web.json_response(
                dict(error="Private fixture failure detail"),
                status=error,
                headers={"X-Read-Retries-Exhausted": "1"},
            )
    return await handler(request)


app.middlewares.insert(0, sample)
with app["store"].tx() as db:
    db.execute(
        "INSERT INTO seasons(id,label,status,signup_open) VALUES(1,'November 2026','draft',1),(2,'2026-08','archived',0),(3,'2026-09','archived',0),(4,'2026-10','archived',0)"
    )
    db.execute("UPDATE member_season SET season_id=1,revision=1 WHERE id=1")
    for clan_index, (t, n) in enumerate(CLANS):
        db.execute("INSERT INTO clans(tag,name) VALUES(?,?)", (t, n))
        db.execute("INSERT INTO lineup(season_id,tag) VALUES(1,?)", (t,))
        db.execute(
            "INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES(1,?,?,15)",
            (t, "main" if clan_index < 3 else "lazy"),
        )
    for i, t in enumerate(PLAYERS):
        p = provider.players[t]
        db.execute(
            "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(1,?,?,?,0,?,?)",
            (t, OWNER, "main" if i < 15 else "lazy", p["name"], p["town_hall"]),
        )
        db.execute(
            "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,manual_weight,kept) VALUES(1,?,?,171000,0)",
            (t, CLANS[min(i // 5, 5)][0]),
        )


async def main():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}/api/cwl"
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        assert (await session.post(base + "/dev/login")).status == 200
        me = await (await session.get(base + "/auth/me")).json()
        headers = {"X-CSRF-Token": me["csrf_token"]}

        async def call(method, path, body=None):
            response = await session.request(
                method, base + path, headers=headers, json=body
            )
            assert response.status in (200, 201), (
                path,
                response.status,
                await response.text(),
            )
            return await response.json()

        draft = await call("GET", "/seasons/1/publication")
        await call(
            "POST",
            "/seasons/1/publication",
            dict(
                revision=draft["draft_revision"],
                acknowledge_unassigned=True,
                joining_instructions="Fixture only",
            ),
        )
        # Version is fixture setup, not a production migration or publish claim.
        with app["store"].tx() as db:
            db.execute("UPDATE roster_publications SET version=6 WHERE season_id=1")
        await call(
            "POST",
            "/seasons/1/participation/sync-settings",
            dict(cycle="2026-11", enabled=False),
        )
        for i in range(2):
            await call(
                "PATCH",
                "/seasons/1/participation/%23" + PLAYERS[i][1:],
                dict(
                    revision=0,
                    publication_version=6,
                    notes="Fixed fixture result",
                ),
            )
        from utils.cwl_working_roster import account_token, working_accounts

        with app["store"].tx() as db:
            for tag in PLAYERS[:2]:
                db.execute(
                    "INSERT INTO participation_source_results(season_id,cycle,tag,attacks,stars,status,complete,checked_at,roster_token) VALUES (1,'2026-11',?,7,21,'complete',1,?,?)",
                    (
                        tag,
                        datetime.now(timezone.utc).isoformat(),
                        account_token(working_accounts(db, 1)[tag]),
                    ),
                )
        await call(
            "PATCH",
            "/seasons/1/bonuses/settings",
            dict(
                revision=0,
                policy=dict(min_attacks=None, min_stars=None, cooldown_months=None),
                clans=[dict(tag=tag, slots=1) for tag, _ in CLANS],
            ),
        )
        await call(
            "PATCH",
            "/seasons/1/bonuses/draft",
            dict(
                revision=1,
                selections=[
                    dict(tag=PLAYERS[1], reason="Fixture selection, not a game award")
                ],
            ),
        )
        preview = await call("GET", "/seasons/1/bonuses/preview")
        await call(
            "POST",
            "/seasons/1/bonuses/confirm",
            dict(
                revision=preview["revision"],
                fingerprint=preview["fingerprint"],
                acknowledge_warnings=True,
            ),
        )
        with app["store"].tx() as db:
            db.execute(
                "UPDATE roster_entries SET manual_weight=179000 WHERE season_id=1"
            )
            db.execute(
                "UPDATE roster_entries SET assigned_clan_tag='#J2Y' WHERE season_id=1 AND tag=?",
                (PLAYERS[0],),
            )
            db.execute("UPDATE roster_meta SET revision=revision+1 WHERE season_id=1")
        with app["store"].tx() as db:
            for sid, cycle in ((2, "2026-08"), (3, "2026-09"), (4, "2026-10")):
                db.execute("UPDATE seasons SET history_only=1 WHERE id=?", (sid,))
                db.execute(
                    "INSERT INTO participation_sync_settings(season_id,cycle,enabled,updated_by,updated_at) VALUES (?,?,0,'fixture','now')",
                    (sid, cycle),
                )
                db.execute("INSERT INTO lineup VALUES (?,'#J2Y')", (sid,))
                db.execute(
                    "INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES (?,'#J2Y','lazy',15)",
                    (sid,),
                )
                db.execute(
                    "INSERT INTO bonus_imported_winners VALUES (?,?,'lazy',?,'Imported history winner','#J2Y','Crystal Keep','import','fixture','now')",
                    (sid, cycle, PLAYERS[sid]),
                )
            db.execute(
                "INSERT INTO bonus_imported_winners VALUES (1,'2026-11','lazy',?,'Imported November winner','#J2Y','Crystal Keep','import','fixture','now')",
                (PLAYERS[4],),
            )
            for tag, league in [
                ("#C2Y", "Master League II"),
                ("#J2Y", "Crystal League I"),
            ]:
                db.execute(
                    "INSERT INTO bonus_allowance_leagues VALUES (1,'2026-11',?,?,'fixture')",
                    (tag, league),
                )
            counts = {
                table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in (
                    "signups",
                    "roster_entries",
                    "bonus_confirmations",
                    "bonus_imported_winners",
                    "roster_publications",
                )
            }
            counts["pools"] = [
                dict(row)
                for row in db.execute(
                    "SELECT season_id,pool,COUNT(*) signups,SUM(kept) locks FROM signups JOIN roster_entries USING(season_id,tag) GROUP BY season_id,pool"
                )
            ]
        (OUT / "before-counts.json").write_text(json.dumps(counts, indent=2))
        baseline = {}
        for name, path in [
            ("season-published.xlsx", "/seasons/1/export.xlsx?basis=published"),
            ("season-working.xlsx", "/seasons/1/export.xlsx?basis=current"),
            ("range.xlsx", "/exports/range.xlsx?from=2026-08&to=2026-11"),
            ("history-only.xlsx", "/seasons/3/export.xlsx"),
        ]:
            response = await session.get(base + path)
            assert response.status == 200, await response.text()
            raw = await response.read()
            (OUT / name).write_bytes(raw)
            baseline[name] = hashlib.sha256(raw).hexdigest()
        (OUT / "baseline-workbook-hashes.json").write_text(
            json.dumps(baseline, indent=2)
        )
    requests.clear()
    proof = dict(
        ready=True,
        port=port,
        pid=os.getpid(),
        db=str(DATA / "fixture.sqlite"),
        static=str(STATIC),
        fixture_clock="real server time",
        fixture_definition_sha256=hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        months=["2026-11", "2026-10", "2026-09", "2026-08"],
        season=1,
        empty_season=2,
        rows=26,
        published_version=6,
        external_network_blocked=True,
        production_writes=False,
    )
    (OUT / "ready.json").write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof), flush=True)
    await asyncio.Event().wait()


asyncio.run(main())

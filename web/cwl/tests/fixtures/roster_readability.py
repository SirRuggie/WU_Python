import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, os.environ["WU_FIXTURE_BACKEND"])
sys.path.insert(0, str(Path(__file__).resolve().parent))

import qa_network_guard
from aiohttp import web, ClientSession, CookieJar
from cwl_web import create_app
from cwl_web.providers import ProviderUnavailable

STATIC = Path(sys.argv[1])
PORT = int(sys.argv[2])
assert 8900 <= PORT <= 8999, "Only isolated preview ports allowed"
folder = tempfile.TemporaryDirectory(prefix="wu-roster-readability-fixture-")
app = create_app(
    db_path=folder.name + "/isolated.sqlite",
    dev_fixture=True,
    secure_cookies=False,
    static_dir=STATIC,
)
provider = app["providers"]
provider.players = {}
clans = ["#P2Y", "#Q2Y", "#G2Y", "#L2Y", "#R2Y", "#C2Y", "#J2Y", "#V2Y"]
names = [
    "Warriors Unite!",
    "Morning Woods!",
    "Amber Knights",
    "Crystal Keep",
    "Dragon Flight",
    "Emerald Watch",
    "W. U. Lazy .125",
    "W. U. Lazy .128",
]
counts = [16, 15, 16, 15, 16, 15, 16, 16]
players = []
oldtags = []


async def family():
    return {
        "source": "fixture",
        "status": "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "clans": [
            {"tag": tag, "name": name}
            for tag, name in zip(clans, names)
        ],
    }


provider.family_clans = family


async def clan(value):
    return {
        "tag": value,
        "name": names[clans.index(value)] if value in clans else "Outside Family",
        "cwl_league": "Crystal League I" if value == "#Q2Y" else "Master League II",
    }


provider.clan = clan


async def player(value):
    if value not in provider.players:
        raise ProviderUnavailable("Isolated fixture lookup failure")
    return provider.players[value].copy()


provider.player = player

with app["store"].tx() as db:
    db.execute("UPDATE seasons SET label='November 2026'")
    n = 0
    for ci, (ct, name, count) in enumerate(zip(clans, names, counts)):
        pool = "main" if ci < 6 else "lazy"
        db.execute("INSERT INTO clans(tag,name) VALUES (?,?)", (ct, name))
        db.execute("INSERT INTO lineup(season_id,tag) VALUES (1,?)", (ct,))
        db.execute(
            "INSERT INTO lineup_rules(season_id,tag,pool,capacity,min_weight,max_weight) "
            "VALUES (1,?,?,?,?,?)",
            (
                ct,
                pool,
                30 if ci == 3 else 15,
                150000 if ci % 3 != 1 else None,
                170000 if ci % 3 != 2 else None,
            ),
        )
        for j in range(count):
            tag = (
                "#QG02CY8LG"
                if n == 93
                else "#P"
                + "".join(
                    "0289PYLQGRJCUV"[int(x)]
                    for x in str(n).zfill(7 if n % 2 == 0 else 6)
                )
                + "Y"
            )
            players.append(tag)
            first_names = ["Aurora", "Blaze", "Cinder", "Delta", "Echo", "Falcon"]
            pname = "FifteenCharName" if n == 0 else f"{first_names[j % 6]} {n + 1:03}"
            weight = None if j == 5 else 179000 - j * 1500
            db.execute(
                "INSERT INTO signups("
                "season_id,tag,user_id,player_name,town_hall,pool,"
                "prefer_crystal_1_or_lower) "
                "VALUES (1,?,?,?,?,?,0)",
                (tag, str(505227988229554179 + n // 3), pname, 18 - j % 5, pool),
            )
            db.execute(
                "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept,manual_weight) "
                "VALUES (1,?,?,?,?)",
                (tag, ct, int(j == 0), weight),
            )
            loc = (
                ct
                if j % 6 in (0, 5)
                else clans[(ci + 1) % 8]
                if j % 6 == 1
                else "#Y2Y"
                if j % 6 == 2
                else None
            )
            locname = (
                names[clans.index(loc)]
                if loc in clans
                else "Outside Family"
                if loc
                else None
            )
            if j % 6 != 4:
                provider.players[tag] = {
                    "tag": tag,
                    "name": pname,
                    "town_hall": 18 - j % 5,
                    "current_clan_tag": loc,
                    "current_clan_name": locname,
                }
            if j == 6:
                oldtags.append(tag)
                provider.players.pop(tag, None)
                app.setdefault("roster_location_cache", {})[tag] = (
                    time.monotonic(),
                    {
                        "current_clan_tag": ct,
                        "current_clan_name": name,
                        "current_clan_checked_at": (
                            datetime.now(timezone.utc) - timedelta(minutes=12)
                        ).isoformat(),
                        "current_clan_status": "current",
                    },
                )
            n += 1

with app["store"].tx() as db:
    db.execute("UPDATE lineup_rules SET capacity=15,lower_league=1 WHERE tag='#P2Y'")
    db.execute("UPDATE lineup_rules SET lower_league=0 WHERE tag='#G2Y'")
    db.execute("UPDATE lineup_rules SET min_weight=NULL,max_weight=NULL WHERE tag='#C2Y'")
    for ct, name, pool in [
        ("#U2Y", "Funnies", "main"),
        ("#Y2Y", "FifteenCharClan", "main"),
    ]:
        db.execute("INSERT INTO clans(tag,name) VALUES (?,?)", (ct, name))
        db.execute("INSERT INTO lineup(season_id,tag) VALUES (1,?)", (ct,))
        db.execute(
            "INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES (1,?,?,?)",
            (ct, pool, None if ct == "#U2Y" else 15),
        )
    # Funnies intentionally has an assigned account with no weight, so its
    # clan-card total exercises the explicit "no weights yet" state.
    db.execute(
        "UPDATE roster_entries SET assigned_clan_tag=?,kept=0 WHERE tag=?",
        ("#U2Y", players[5]),
    )
    db.execute(
        "INSERT INTO seasons(id,label,status,signup_open) "
        "VALUES (2,'October 2026','archived',0)"
    )
    db.execute("INSERT INTO lineup(season_id,tag) SELECT 2,tag FROM lineup WHERE season_id=1")
    db.execute(
        "INSERT INTO lineup_rules(season_id,tag,pool,capacity,min_weight,max_weight) "
        "SELECT 2,tag,pool,capacity,min_weight,max_weight "
        "FROM lineup_rules WHERE season_id=1"
    )


def set_publication_state(state_name):
    """Fixture-only status setup. Never called by a dashboard control."""
    if state_name not in {"draft", "hidden", "published"}:
        raise ValueError("Unsupported fixture publication state")
    if state_name == "draft":
        with app["store"].tx() as db:
            ids = [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM roster_publications WHERE season_id=1"
                )
            ]
            if ids:
                marks = ",".join("?" for _ in ids)
                db.execute(
                    "DELETE FROM publication_accounts "
                    f"WHERE publication_id IN ({marks})",
                    ids,
                )
                db.execute("DELETE FROM roster_publications WHERE season_id=1")
        return

    from cwl_web.app import _revision, _roster_rows, _rule_rows

    published_at = (
        "2026-10-15T19:58:00+00:00"
        if state_name == "hidden"
        else "2026-10-28T16:00:00+00:00"
    )
    version = 1 if state_name == "hidden" else 3
    with app["store"].tx() as db:
        accounts = _roster_rows(db, 1)
        clans = _rule_rows(db, 1)
        clan_names = {item["tag"]: item["name"] for item in clans}
        assigned_count = sum(bool(item["assigned_clan_tag"]) for item in accounts)
        db.execute(
            "DELETE FROM publication_accounts WHERE publication_id IN "
            "(SELECT id FROM roster_publications WHERE season_id=1)"
        )
        db.execute("DELETE FROM roster_publications WHERE season_id=1")
        cursor = db.execute(
            "INSERT INTO roster_publications("
            "season_id,version,revision,published_by,published_at,joining_instructions,"
            "assigned_count,unassigned_count,clans_json,withdrawn_at) "
            "VALUES (1,?,?,?,?,?,?,?,?,?)",
            (
                version,
                _revision(db, 1),
                "505227988229554179",
                published_at,
                "Fixture-only publication status.",
                assigned_count,
                len(accounts) - assigned_count,
                json.dumps(clans, sort_keys=True),
                "2026-10-15T20:15:00+00:00" if state_name == "hidden" else None,
            ),
        )
        publication_id = cursor.lastrowid
        for item in accounts:
            db.execute(
                "INSERT INTO publication_accounts("
                "publication_id,tag,user_id,player_name,town_hall,pool,"
                "prefer_crystal_1_or_lower,signup_clan_tag,signup_clan_name,"
                "assigned_clan_tag,assigned_clan_name,source_weight,source_status,"
                "source_name,source_checked_at,source_modified_at,manual_weight,"
                "effective_weight,kept) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    publication_id,
                    item["tag"],
                    item["user_id"],
                    item["player_name"],
                    item["town_hall"],
                    item["pool"],
                    int(item["prefer_crystal_1_or_lower"]),
                    item.get("signup_clan_tag"),
                    item.get("signup_clan_name"),
                    item.get("assigned_clan_tag"),
                    clan_names.get(item.get("assigned_clan_tag")),
                    item.get("source_weight"),
                    item.get("source_status"),
                    item.get("source_name"),
                    item.get("source_checked_at"),
                    item.get("source_modified_at"),
                    item.get("manual_weight"),
                    item.get("effective_weight"),
                    int(bool(item.get("kept"))),
                ),
            )
        if state_name == "hidden":
            db.execute(
                "UPDATE roster_publications SET withdrawn_at=? WHERE id=?",
                ("2026-10-15T20:15:00+00:00", publication_id),
            )


requests = []
mode = {
    "fail": False,
    "no_clan_permission": False,
    "no_publish_permission": False,
    "save_failure": False,
}
baseline = None


@web.middleware
async def qa(request, handler):
    if request.path.startswith("/api/"):
        requests.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "method": request.method,
                "path": request.path_qs,
            }
        )
    if request.path.endswith("/arrival-check") and mode["fail"]:
        return web.json_response({"error": "Isolated lookup failure"}, status=503)
    if request.path.endswith("/staff-signup-members"):
        uid = request.query.get("id", "505227988229554179")
        return web.json_response(
            {
                "options": [
                    {
                        "id": uid,
                        "display_name": "Fixture staff member",
                        "username": "fixture-staff",
                        "avatar_url": None,
                    }
                ]
            }
        )
    if (
        mode["save_failure"]
        and request.method == "PATCH"
        and "/roster/" in request.path
    ):
        return web.json_response({"error": "Isolated save failure"}, status=409)
    response = await handler(request)
    if (
        request.path.endswith("/auth/me")
        and (mode["no_clan_permission"] or mode["no_publish_permission"])
        and response.status == 200
    ):
        payload = json.loads(response.text)
        payload["is_owner"] = False
        permission = "cwl_publish" if mode["no_publish_permission"] else "clan_weights"
        payload["dashboard_permissions"] = [
            item
            for item in payload.get("dashboard_permissions", [])
            if item != permission
        ]
        response = web.json_response(payload)
    return response

app.middlewares.insert(0, qa)


def state():
    with app["store"].tx() as db:
        counts = [
            dict(row)
            for row in db.execute(
                "SELECT s.pool,COUNT(*) signups,"
                "SUM(r.assigned_clan_tag IS NOT NULL) assigned,"
                "SUM(COALESCE(r.kept,0)) locks "
                "FROM signups s LEFT JOIN roster_entries r "
                "ON s.season_id=r.season_id AND s.tag=r.tag "
                "WHERE s.season_id=1 GROUP BY s.pool"
            )
        ]
        version = db.execute(
            "SELECT MAX(version) FROM roster_publications WHERE season_id=1"
        ).fetchone()[0]
        unreviewed = db.execute(
            "SELECT COUNT(*) FROM roster_audit a "
            "LEFT JOIN signup_activity_reviews r ON r.audit_id=a.id "
            "WHERE a.season_id=1 "
            "AND a.action IN ('member_withdrawal','member_pool_change') "
            "AND r.audit_id IS NULL"
        ).fetchone()[0]
        account_count = db.execute(
            "SELECT COUNT(*) FROM signups WHERE season_id=1"
        ).fetchone()[0]

    store = app["store"]
    reviews = [
        dict(row)
        for row in store.rows(
            "SELECT * FROM signup_activity_reviews ORDER BY audit_id"
        )
    ]
    season_counts = [
        dict(row)
        for row in store.rows(
            "SELECT x.id season_id,p.pool,COUNT(s.tag) signups,"
            "SUM(CASE WHEN r.assigned_clan_tag IS NOT NULL THEN 1 ELSE 0 END) assigned,"
            "SUM(COALESCE(r.kept,0)) locks "
            "FROM seasons x "
            "CROSS JOIN (SELECT 'main' pool UNION ALL SELECT 'lazy') p "
            "LEFT JOIN signups s ON s.season_id=x.id AND s.pool=p.pool "
            "LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag "
            "GROUP BY x.id,p.pool"
        )
    ]
    publications = [
        dict(row)
        for row in store.rows(
            "SELECT season_id,version,withdrawn_at "
            "FROM roster_publications ORDER BY season_id,version"
        )
    ]
    manual_weights = [
        dict(row)
        for row in store.rows(
            "SELECT season_id,tag,manual_weight FROM roster_entries "
            "ORDER BY season_id,tag"
        )
    ]
    saved_weights = [
        dict(row)
        for row in store.rows("SELECT tag,weight FROM player_weights ORDER BY tag")
    ]
    rules = [
        dict(row)
        for row in store.rows("SELECT * FROM lineup_rules ORDER BY season_id,tag")
    ]
    return {
        "account_count": account_count,
        "unreviewed_changes": unreviewed,
        "reviews": reviews,
        "counts": counts,
        "season_counts": season_counts,
        "publication": version,
        "publications": publications,
        "manual_weights": manual_weights,
        "saved_weights": saved_weights,
        "rules": rules,
    }

async def qa_state(request):
    return web.json_response(
        {
            "current": state(),
            "baseline": baseline,
            "requests": requests,
            "db": folder.name + "/isolated.sqlite",
            "oldtags": oldtags,
        }
    )

async def qa_mode(request):
    mode.update(await request.json())
    return web.json_response(mode)


app.router.add_get("/qa/state", qa_state)
app.router.add_post("/qa/mode", qa_mode)

async def qa_publication_state(request):
    payload = await request.json()
    if set(payload) != {"state"} or payload["state"] not in {
        "draft",
        "hidden",
        "published",
    }:
        return web.json_response(
            {"error": "Expected isolated state: draft, hidden, or published"},
            status=400,
        )
    set_publication_state(payload["state"])
    return web.json_response({"state": payload["state"], "current": state()})


app.router.add_post("/qa/publication-state", qa_publication_state)

async def main():
    global baseline
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        base = f"http://127.0.0.1:{PORT}/api/cwl"
        response = await session.post(base + "/dev/login")
        assert response.status == 200
        me = await (await session.get(base + "/auth/me")).json()
        roster = await (await session.get(base + "/seasons/1/roster")).json()
        response = await session.post(
            base + "/seasons/1/publication",
            headers={"X-CSRF-Token": me["csrf_token"]},
            json={
                "revision": roster["revision"],
                "acknowledge_unassigned": True,
                "joining_instructions": "Isolated review only",
            },
        )
        assert response.status in (200, 201), await response.text()
    with app["store"].tx() as db:
        db.execute(
            "UPDATE roster_entries SET manual_weight=151500 WHERE tag=?",
            (players[1],),
        )
        db.execute("UPDATE signups SET pool='lazy' WHERE tag=?", (players[2],))
        db.execute(
            "UPDATE roster_entries SET assigned_clan_tag=?,kept=0 WHERE tag=?",
            (clans[6], players[2]),
        )
        db.execute("DELETE FROM roster_entries WHERE tag=?", (players[-1],))
        db.execute("DELETE FROM signups WHERE tag=?", (players[-1],))
        db.execute(
            "INSERT INTO signups(season_id,tag,user_id,player_name,town_hall,pool,"
            "prefer_crystal_1_or_lower) "
            "VALUES(1,'#QQQY0P02Y','505227988229554179','New Signup',18,'main',0)"
        )
        db.execute(
            "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept,manual_weight) "
            "VALUES(1,'#QQQY0P02Y',?,0,NULL)",
            (clans[0],),
        )
        db.execute(
            "INSERT INTO roster_meta(season_id,revision) VALUES(1,1) "
            "ON CONFLICT(season_id) DO UPDATE SET revision=revision+1"
        )
    provider.players["#QQQY0P02Y"] = {
        "tag": "#QQQY0P02Y",
        "name": "New Signup",
        "town_hall": 18,
        "current_clan_tag": "#Y2Y",
        "current_clan_name": "Outside Family",
    }
    with app["store"].tx() as db:
        db.execute(
            "UPDATE roster_entries SET assigned_clan_tag=NULL,kept=0 "
            "WHERE tag IN (?,?)",
            (players[10], players[11]),
        )
        db.execute(
            "INSERT INTO seasons(id,label,status,signup_open) "
            "VALUES (3,'September 2026','draft',0)"
        )
        db.execute(
            "INSERT INTO signups(season_id,tag,user_id,player_name,town_hall,pool,"
            "prefer_crystal_1_or_lower) "
            "VALUES(3,'#QQQY0P02Y','505227988229554179','Old member',18,'main',0)"
        )
        db.execute(
            "INSERT INTO roster_entries(season_id,tag,manual_weight) "
            "VALUES(3,'#QQQY0P02Y',150000)"
        )
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        await session.post(base + "/dev/login")
        me = await (await session.get(base + "/auth/me")).json()
        draft = await (await session.get(base + "/seasons/3/publication")).json()
        response = await session.post(
            base + "/seasons/3/publication",
            headers={"X-CSRF-Token": me["csrf_token"]},
            json={
                "revision": draft["draft_revision"],
                "acknowledge_unassigned": True,
                "joining_instructions": (
                    "Join after your current war.\nAsk staff if you need help."
                ),
            },
        )
        assert response.status == 201, await response.text()
        draft = await (await session.get(base + "/seasons/3/publication")).json()
        response = await session.post(
            base + "/seasons/3/publication/withdraw",
            headers={"X-CSRF-Token": me["csrf_token"]},
            json={"revision": draft["draft_revision"], "version": 1},
        )
        assert response.status == 200, await response.text()
    with app["store"].tx() as db:
        for index, suffix in [
            (16, "01 In clan"),
            (17, "02 Elsewhere"),
            (20, "03 Not checked"),
            (21, "04 No weight"),
            (10, "05 Unassigned"),
            (11, "06 Clanless"),
        ]:
            db.execute(
                "UPDATE signups SET player_name=? WHERE season_id=1 AND tag=?",
                (suffix, players[index]),
            )
    with app["store"].tx() as db:
        db.execute(
            "INSERT INTO seasons(id,label,status,signup_open) "
            "VALUES (4,'December 2026','draft',1)"
        )
        for sid in (3, 4):
            for table in ('lineup', 'lineup_rules', 'signups', 'roster_entries'):
                columns = [
                    row["name"]
                    for row in db.execute(f"PRAGMA table_info({table})")
                ]
                # Fixture-only copies; every copied row belongs to this temporary DB.
                selection = ",".join(
                    "?" if column == "season_id" else column
                    for column in columns
                )
                db.execute(
                    f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) "
                    f"SELECT {selection} FROM {table} WHERE season_id=1",
                    (sid,),
                )
        events = [
            (1, "member_withdrawal", "#G2RGRRGPY", "Ayooo", "#P2Y", "main", None)
        ]
        for sid, number in ((3, 2), (4, 4)):
            for index in range(number):
                switch = index % 2 == 1
                tag = (
                    players[3 + index]
                    if switch
                    else "#G2RGRRGP" + "YLCV"[index]
                )
                events.append(
                    (
                        sid,
                        "member_pool_change" if switch else "member_withdrawal",
                        tag,
                        "Ayooo" if index == 0 else "Blaze " + str(index),
                        "#J2Y",
                        "lazy",
                        "main" if switch else None,
                    )
                )
                if switch:
                    db.execute(
                        "UPDATE roster_entries SET assigned_clan_tag=NULL,kept=0 "
                        "WHERE season_id=? AND tag=?",
                        (sid, tag),
                    )
        for sid, action, tag, name, oldclan, source, dest in events:
            before = {
                "player_name": name,
                "pool": source,
                "assigned_clan_tag": oldclan,
                "assigned_clan_name": names[clans.index(oldclan)],
            }
            db.execute(
                "INSERT INTO roster_audit(season_id,tag,actor_id,action,before_json,"
                "after_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    sid,
                    tag,
                    "505227988229554179",
                    action,
                    json.dumps(before),
                    json.dumps({"pool": dest}),
                    "2026-10-28 08:44:00",
                ),
            )
    set_publication_state('hidden')
    baseline = state()
    assert baseline["account_count"] == 125
    assert baseline["unreviewed_changes"] == 1
    assert any(
        row["tag"] == "#U2Y" and row["pool"] == "main" and row["capacity"] is None
        for row in baseline["rules"]
    )
    assert any(
        row["tag"] == players[5] and row["manual_weight"] is None
        for row in baseline["manual_weights"]
    )
    assert any(
        row["tag"] == "#P2Y" and row["capacity"] == 15
        for row in baseline["rules"]
    )
    requests.clear()
    print(
        json.dumps(
            {
                "ready": True,
                "db": folder.name + "/isolated.sqlite",
                "counts": baseline,
            }
        ),
        flush=True,
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

"""Isolated UI sample transport. No Mongo, Discord or production writes."""

import os
import sys
from pathlib import Path
from copy import deepcopy
from aiohttp import web

sys.path.insert(0, str(Path(__file__).parent))
import player_cards as fixture
from utils.member_timezones import COUNTRY_CHOICES, ZONE_CHOICES, SINGLE_ZONE, flag

BASE = "/api/cwl/manage/member-timezones"
profiles = [
    dict(
        zone_id="gmt-5",
        gmt_label="GMT-5",
        utc_offset_minutes=-300,
        country="US",
        flag="🇺🇸",
        name_source_tag=None,
        source="staff",
        revision=3,
    ),
    None,
    None,
    None,
]
labels = ["Saved", "From nickname", "Unknown", "Missing"]
members = [
    dict(
        discord_id=str(123456789012345670 + i),
        name=name,
        nickname=nick,
        bot=False,
        status=labels[i],
        profile=profiles[i],
        parsed=parsed,
        skip_reason=None,
    )
    for i, (name, nick, parsed) in enumerate(
        [
            (
                "Ada Champion",
                "Ada Champion | EST 🇺🇸",
                dict(label="EST", offsetMinutes=-300),
            ),
            ("Birch", "Birch | NZT 🇳🇿", dict(label="NZT", offsetMinutes=720)),
            (
                "Cedar <script> @everyone",
                "Cedar | MOON",
                dict(label="MOON", offsetMinutes=None),
            ),
            ("Dawn", None, None),
        ]
    )
]
members.append(
    dict(
        discord_id="123456789012345679",
        name="Server owner with a deliberately long display name",
        nickname="Owner",
        bot=False,
        status="Missing",
        profile=None,
        parsed=None,
        skip_reason="The server owner cannot be changed by this tool.",
    )
)
state = dict(denied=False, conflict=False, request=None, preview=None, run=None)


@web.middleware
async def sample(request, handler):
    if request.path == "/qa/member-timezones":
        body = await request.json()
        state.update({k: v for k, v in body.items() if k in ("denied", "conflict")})
        return web.json_response({"ok": True})
    if not request.path.startswith(BASE) and not request.path.startswith(
        "/api/cwl/manage/requests/profile-fixture"
    ):
        return await handler(request)
    fixture.requests.append(dict(method=request.method, path=request.path))
    if state["denied"]:
        return web.json_response({"error": "Access revoked in fixture"}, status=403)
    if request.path == BASE:
        return web.json_response(
            dict(
                members=members,
                countries=[
                    dict(code=c, label=n, flag=flag(c), zone_id=SINGLE_ZONE.get(c))
                    for c, n in COUNTRY_CHOICES
                ],
                zones=[
                    dict(id=z, label=z.upper() + " · " + n) for z, _, n in ZONE_CHOICES
                ],
                permission="member_roles",
            )
        )
    if request.path.endswith("/choices"):
        return web.json_response(
            dict(
                accounts=[
                    dict(tag="#PYY", name="Main Hero", townHallLevel=18),
                    dict(tag="#PQQ", name="Second Main", townHallLevel=18),
                ],
                suggested=None,
                complete=True,
            )
        )
    if request.path.endswith("/save"):
        if state["conflict"]:
            return web.json_response(
                {"error": "Member profile changed; review it again."}, status=409
            )
        body = await request.json()
        state["request"] = body
        return web.json_response(
            dict(
                request_id="profile-fixture",
                status="pending",
                status_url="/manage/requests/profile-fixture",
                message="Waiting for fixture bot",
            )
        )
    if request.path.startswith("/api/cwl/manage/requests/profile-fixture"):
        return web.json_response(
            dict(status="done", message="Profile saved. Nickname unchanged.", result={})
        )
    if request.path.endswith("/preview"):
        rows = [
            dict(
                discord_id=m["discord_id"],
                name=m["name"],
                old_nickname=m["nickname"],
                new_nickname=(m["nickname"] or m["name"]).split(" | ")[0]
                + " | GMT-5 🇺🇸",
                revision=3,
                skip_reason=m["skip_reason"],
            )
            for m in members
        ]
        state["preview"] = rows
        return web.json_response(dict(token="fixture-token", rows=rows))
    if request.path == BASE + "/runs":
        return web.json_response(
            dict(
                runs=[dict(run_id="fixture-run", state="done")] if state["run"] else []
            )
        )
    if request.path.endswith("/confirm"):
        body = await request.json()
        selected = set(body["selected"])
        state["run"] = [
            dict(
                row,
                status="uncertain" if index == 0 else "done",
                message="Check Discord before repeating" if index == 0 else "Saved",
            )
            for index, row in enumerate(state["preview"])
            if row["discord_id"] in selected
        ]
        return web.json_response(dict(run_id="fixture-run", state="done"))
    if request.path == BASE + "/runs/fixture-run":
        return web.json_response(
            dict(run_id="fixture-run", state="done", rows=state["run"] or [])
        )
    return web.json_response(
        {"error": "Unsupported isolated fixture action"}, status=400
    )


fixture.app.middlewares.insert(0, sample)
if __name__ == "__main__":
    import asyncio

    asyncio.run(fixture.main())

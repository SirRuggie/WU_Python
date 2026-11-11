"""World clocks dashboard API: access, validation, receipts and conflicts."""
import asyncio
import json
from datetime import timedelta
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiohttp import web

from cwl_web import server_management, world_clocks as api
from tests.world_clock_fakes import memory_db
from utils import world_clocks as rules
from utils.world_clock_store import WorldClockStore

GUILD = str(rules.GUILD_ID)
CATEGORY = {"id": "900000000000000001", "type": 4, "name": "⏳ ⇒ Live World Times", "guild_id": GUILD,
            "permission_overwrites": [{"id": GUILD, "type": 0, "allow": "0", "deny": "1049600"}]}
VOICE = {"id": "900000000000000002", "type": 2, "name": "EST : 9:21pm", "guild_id": GUILD,
         "parent_id": CATEGORY["id"], "position": 1}
VOICE2 = {"id": "900000000000000003", "type": 2, "name": "PHT", "guild_id": GUILD,
          "parent_id": CATEGORY["id"], "position": 2}
TEXT = {"id": "900000000000000004", "type": 0, "name": "general", "guild_id": GUILD}


class FakeDiscord:
    def __init__(self):
        self.channels = [CATEGORY, VOICE, VOICE2, TEXT]
        self.posts = []
        self.fail_post = None
        self.fail_delete = None
        self.deletes = []
        self.down = False
        self.next_id = 900000000000000100

    async def __call__(self, request, method, path, **kwargs):
        if self.down:
            raise web.HTTPServiceUnavailable(text="Discord is unavailable.")
        if method == "GET" and path == f"/guilds/{GUILD}/channels":
            return list(self.channels)
        if method == "GET" and path.startswith("/channels/"):
            found = next((c for c in self.channels if c["id"] == path.split("/")[2]), None)
            if not found:
                raise web.HTTPNotFound(text="gone")
            return found
        if method == "DELETE" and path.startswith("/channels/"):
            cid = path.split("/")[2]
            self.deletes.append((cid, kwargs))
            if self.fail_delete:
                raise self.fail_delete
            found = next((c for c in self.channels if c["id"] == cid), None)
            if not found:
                raise server_management.DiscordItemNotFound(10003)
            self.channels.remove(found)
            return found
        if method == "POST" and path == f"/guilds/{GUILD}/channels":
            self.posts.append(kwargs)
            if self.fail_post:
                raise self.fail_post
            self.next_id += 1
            row = {"id": str(self.next_id), "type": 2, "guild_id": GUILD, **kwargs["json"]}
            self.channels.append(row)
            return row
        raise AssertionError((method, path))


@pytest.fixture
def env(monkeypatch):
    db = memory_db()
    fake = FakeDiscord()

    @asynccontextmanager
    async def mongo(request):
        yield db

    monkeypatch.setattr(api, "mongo", mongo)
    monkeypatch.setattr(api, "discord", fake)
    access = AsyncMock(return_value={"user_id": "123456789012345678"})
    monkeypatch.setattr(api, "require_manage", access)
    return NS(db=db, discord=fake, access=access, store=WorldClockStore(db))


def request(body=None, **match):
    return NS(json=AsyncMock(return_value=body if body is not None else {}), match_info=match)


def payload(response):
    return json.loads(response.text)


def run(coro):
    return asyncio.run(coro)


def add_body(mode="create", **extra):
    return {"request_id": str(uuid4()), "zone": "America/New_York", "flag": "🇺🇸", "code": None,
            "mode": mode, "category_id": CATEGORY["id"], **extra}


def test_section_maps_to_server_tools():
    from utils.dashboard_access import SECTION_SCOPE
    assert SECTION_SCOPE["world_clocks"] == "server_tools"


def test_every_route_checks_access_before_reading_body(env):
    env.access.side_effect = web.HTTPForbidden()
    for handler, match in ((api.add, {}), (api.toggle, {"clock_id": "a" * 32}), (api.edit, {"clock_id": "a" * 32}),
                           (api.remove, {"clock_id": "a" * 32}), (api.save_settings, {}), (api.preview, {}),
                           (api.read, {}), (api.zones, {})):
        req = request(add_body(), **match)
        with pytest.raises(web.HTTPForbidden):
            run(handler(req))
        req.json.assert_not_awaited()
    assert env.discord.posts == []
    writes = [call.kwargs.get("write") for call in env.access.await_args_list]
    assert writes.count(True) == 5


def test_create_channel_copies_category_permissions_and_names_it(env):
    response = run(api.add(request(add_body())))
    assert response.status == 201
    sent = env.discord.posts[0]["json"]
    assert sent["type"] == 2 and sent["parent_id"] == CATEGORY["id"]
    assert sent["permission_overwrites"] == CATEGORY["permission_overwrites"]
    assert sent["name"].startswith("🇺🇸 E") and " · " in sent["name"]
    assert env.discord.posts[0]["roster_delivery"] is True
    clock = run(env.store.list_clocks())[0]
    assert clock["status"] == "ok" and clock["last_name"] == sent["name"]


def test_double_tap_creates_one_channel(env):
    body = add_body()
    first = payload(run(api.add(request(body))))
    second = payload(run(api.add(request(body))))
    assert len(env.discord.posts) == 1 and first["id"] == second["id"]
    assert len(run(env.store.list_clocks())) == 1


def test_uncertain_create_is_never_retried(env):
    env.discord.fail_post = server_management.DiscordDeliveryUncertain("timeout")
    body = add_body()
    with pytest.raises(web.HTTPServiceUnavailable) as error:
        run(api.add(request(body)))
    assert "Check the category" in error.value.text
    with pytest.raises(web.HTTPConflict):
        run(api.add(request(body)))
    assert len(env.discord.posts) == 1 and run(env.store.list_clocks()) == []


def test_refused_create_is_recorded_as_failed(env):
    env.discord.fail_post = web.HTTPForbidden(text="Discord does not allow this action.")
    body = add_body()
    with pytest.raises(web.HTTPBadRequest) as error:  # Never a 403: that means "dashboard access lost".
        run(api.add(request(body)))
    assert "permissions" in error.value.text and "bot" not in error.value.text
    receipt = env.db.collections["world_clock_requests"].rows[0]
    assert receipt["status"] == "failed"


def test_failed_create_can_retry_with_the_same_id(env):
    env.discord.fail_post = web.HTTPTooManyRequests(text="slow down")
    body = add_body()
    with pytest.raises(web.HTTPServiceUnavailable):
        run(api.add(request(body)))
    env.discord.fail_post = None
    response = run(api.add(request(body)))
    assert response.status == 201 and len(env.discord.posts) == 2
    assert len(run(env.store.list_clocks())) == 1


def test_uncertain_create_blocks_new_ids_in_that_category(env):
    env.discord.fail_post = server_management.DiscordDeliveryUncertain("timeout")
    with pytest.raises(web.HTTPServiceUnavailable):
        run(api.add(request(add_body())))
    env.discord.fail_post = None
    with pytest.raises(web.HTTPConflict) as error:  # A new id after reopening the sheet.
        run(api.add(request(add_body())))
    assert "Use an existing voice channel" in error.value.text
    assert len(env.discord.posts) == 1
    # Existing channels can still be added while the create is unconfirmed.
    assert run(api.add(request(add_body("existing", channel_id=VOICE["id"])))).status == 201


def test_old_uncertain_create_stops_blocking(env):
    env.discord.fail_post = server_management.DiscordDeliveryUncertain("timeout")
    with pytest.raises(web.HTTPServiceUnavailable):
        run(api.add(request(add_body())))
    receipt = env.db.collections["world_clock_requests"].rows[0]
    receipt["created_at"] = receipt["created_at"] - timedelta(minutes=api.OPEN_TRY_MINUTES + 1)
    env.discord.fail_post = None
    assert run(api.add(request(add_body()))).status == 201


def test_create_stuck_after_a_restart_is_treated_as_uncertain(env):
    body = add_body()
    run(env.store.claim_request(body["request_id"], "123456789012345678", {"category_id": CATEGORY["id"]}))
    with pytest.raises(web.HTTPConflict) as error:
        run(api.add(request(body)))
    assert "Still creating" in error.value.text
    receipt = env.db.collections["world_clock_requests"].rows[0]
    receipt["created_at"] = receipt["created_at"] - timedelta(minutes=api.OPEN_TRY_MINUTES + 1)
    with pytest.raises(web.HTTPConflict) as error:
        run(api.add(request(body)))
    assert "Use an existing voice channel" in error.value.text and env.discord.posts == []


def test_repeated_successful_press_at_the_clock_limit_returns_the_clock(env, monkeypatch):
    body = add_body()
    first = payload(run(api.add(request(body))))
    monkeypatch.setattr(rules, "MAX_CLOCKS", 1)
    second = run(api.add(request(body)))
    assert second.status == 200 and payload(second)["id"] == first["id"]


def test_channel_created_but_clock_not_saved_finishes_on_retry(env):
    body = add_body()
    clocks = env.db.collections["world_clocks"]
    clocks.fail_next = RuntimeError("mongo down")
    with pytest.raises(RuntimeError):
        run(api.add(request(body)))
    assert env.db.collections["world_clock_requests"].rows[0]["status"] == "channel_created"
    response = run(api.add(request(body)))
    assert response.status == 201 and len(env.discord.posts) == 1
    assert len(run(env.store.list_clocks())) == 1


def test_create_needs_a_category(env):
    body = add_body(category_id=None)
    with pytest.raises(web.HTTPBadRequest, match=None) as error:
        run(api.add(request(body)))
    assert "category" in error.value.text and env.discord.posts == []


def test_create_refuses_a_full_category(env):
    env.discord.channels += [{"id": str(800000000000000000 + i), "type": 2, "parent_id": CATEGORY["id"]} for i in range(50)]
    with pytest.raises(web.HTTPBadRequest) as error:
        run(api.add(request(add_body())))
    assert "full" in error.value.text and env.discord.posts == []


def test_create_when_discord_is_down_changes_nothing(env):
    env.discord.down = True
    with pytest.raises(web.HTTPServiceUnavailable):
        run(api.add(request(add_body())))
    assert env.db.collections["world_clock_requests"].rows == []


def test_existing_channel_must_be_voice_and_unused(env):
    assert run(api.add(request(add_body("existing", channel_id=VOICE["id"])))).status == 201
    with pytest.raises(web.HTTPConflict):
        run(api.add(request(add_body("existing", channel_id=VOICE["id"], zone="Europe/London"))))
    with pytest.raises(web.HTTPBadRequest):
        run(api.add(request(add_body("existing", channel_id=TEXT["id"]))))
    with pytest.raises(web.HTTPBadRequest):
        run(api.add(request(add_body("existing", channel_id="12"))))
    assert env.discord.posts == []


def test_bad_inputs_are_rejected(env):
    for body in (add_body(zone="Nowhere/City"), add_body(code="1A"), add_body(flag="@everyone"),
                 add_body(mode="move"), add_body(request_id="nope"), add_body(zone="Asia/Dubai")):
        with pytest.raises(web.HTTPBadRequest):
            run(api.add(request(body)))
    assert env.discord.posts == []


def test_clock_limit(env, monkeypatch):
    monkeypatch.setattr(rules, "MAX_CLOCKS", 1)
    run(api.add(request(add_body("existing", channel_id=VOICE["id"]))))
    with pytest.raises(web.HTTPBadRequest):
        run(api.add(request(add_body())))


def test_toggle_saves_at_once_and_rejects_stale_revision(env):
    row = run(env.store.add_clock({"zone": "America/New_York", "flag": "", "code": None, "channel_id": VOICE["id"]}, "1"))
    with pytest.raises(web.HTTPConflict):
        run(api.toggle(request({"revision": "99", "enabled": False}, clock_id=row["_id"])))
    result = payload(run(api.toggle(request({"revision": str(row["version"]), "enabled": False}, clock_id=row["_id"]))))
    assert result["clock"]["enabled"] is False and result["clock"]["revision"] == str(row["version"] + 1)
    with pytest.raises(web.HTTPBadRequest):
        run(api.toggle(request({"revision": "2", "enabled": "no"}, clock_id=row["_id"])))
    with pytest.raises(web.HTTPNotFound):
        run(api.toggle(request({"revision": "2", "enabled": True}, clock_id="../x")))


def test_edit_changes_zone_and_channel(env):
    row = run(env.store.add_clock({"zone": "America/New_York", "flag": "", "code": None, "channel_id": VOICE["id"]}, "1"))
    body = {"revision": "1", "zone": "Asia/Manila", "flag": "🇵🇭", "code": None, "channel_id": VOICE2["id"]}
    result = payload(run(api.edit(request(body, clock_id=row["_id"]))))
    assert result["clock"]["zone"] == "Asia/Manila" and result["clock"]["channel_id"] == VOICE2["id"]
    assert result["clock"]["status"] == "waiting" and result["clock"]["code_auto"] == "PHT"
    with pytest.raises(web.HTTPConflict):  # Old revision.
        run(api.edit(request(body, clock_id=row["_id"])))


def test_edit_to_a_used_channel_conflicts(env):
    run(env.store.add_clock({"zone": "America/New_York", "flag": "", "code": None, "channel_id": VOICE["id"]}, "1"))
    other = run(env.store.add_clock({"zone": "Europe/London", "flag": "", "code": None, "channel_id": VOICE2["id"]}, "1"))
    body = {"revision": "1", "zone": "Europe/London", "flag": "", "code": None, "channel_id": VOICE["id"]}
    with pytest.raises(web.HTTPConflict):
        run(api.edit(request(body, clock_id=other["_id"])))


def clock_on(env, channel_id):
    return run(env.store.add_clock({"zone": "America/New_York", "flag": "", "code": None, "channel_id": channel_id}, "1"))


def test_remove_deletes_the_clock_voice_channel_then_the_clock(env):
    row = clock_on(env, VOICE["id"])
    with pytest.raises(web.HTTPConflict):  # Stale revision: nothing deleted.
        run(api.remove(request({"revision": "7"}, clock_id=row["_id"])))
    assert env.discord.deletes == [] and VOICE in env.discord.channels
    result = payload(run(api.remove(request({"revision": "1"}, clock_id=row["_id"]))))
    assert result["channel"] == "deleted"
    assert [cid for cid, _ in env.discord.deletes] == [VOICE["id"]]
    assert env.discord.deletes[0][1].get("roster_delivery") is True
    assert run(env.store.list_clocks()) == [] and VOICE not in env.discord.channels


def test_remove_when_channel_is_already_gone_still_removes_the_clock(env):
    row = clock_on(env, "900000000000000777")
    assert payload(run(api.remove(request({"revision": "1"}, clock_id=row["_id"]))))["channel"] == "gone"
    assert run(env.store.list_clocks()) == [] and env.discord.deletes == []


def test_remove_never_deletes_a_channel_that_is_not_a_voice_channel(env):
    row = clock_on(env, TEXT["id"])  # Should never happen; the guard still holds.
    assert payload(run(api.remove(request({"revision": "1"}, clock_id=row["_id"]))))["channel"] == "kept"
    assert env.discord.deletes == [] and TEXT in env.discord.channels
    assert run(env.store.list_clocks()) == []


@pytest.mark.parametrize("error, status, text", [
    (server_management.DiscordDeliveryUncertain("timeout"), web.HTTPServiceUnavailable, "did not confirm"),
    (web.HTTPForbidden(text="no"), web.HTTPBadRequest, "permissions"),
    (web.HTTPTooManyRequests(text="slow"), web.HTTPServiceUnavailable, "Try again"),
])
def test_remove_keeps_the_clock_when_discord_does_not_delete(env, error, status, text):
    row = clock_on(env, VOICE["id"])
    env.discord.fail_delete = error
    with pytest.raises(status) as raised:
        run(api.remove(request({"revision": "1"}, clock_id=row["_id"])))
    assert text in raised.value.text and "not removed" in raised.value.text and "bot" not in raised.value.text
    assert len(run(env.store.list_clocks())) == 1


def test_remove_with_discord_down_removes_nothing(env):
    row = clock_on(env, VOICE["id"])
    env.discord.down = True
    with pytest.raises(web.HTTPServiceUnavailable):
        run(api.remove(request({"revision": "1"}, clock_id=row["_id"])))
    assert len(run(env.store.list_clocks())) == 1


def test_remove_without_a_channel_just_removes_the_clock(env):
    row = clock_on(env, None)
    assert payload(run(api.remove(request({"revision": "1"}, clock_id=row["_id"]))))["channel"] == "none"
    assert env.discord.deletes == []


def test_settings_validation_and_save(env):
    with pytest.raises(web.HTTPBadRequest):
        run(api.save_settings(request({"revision": "0", "time_format": "12h", "interval_minutes": 5, "category_id": None})))
    with pytest.raises(web.HTTPBadRequest):
        run(api.save_settings(request({"revision": "0", "time_format": "12h", "interval_minutes": 6, "category_id": VOICE["id"]})))
    for bad in (6.0, True, "6"):
        with pytest.raises(web.HTTPBadRequest):
            run(api.save_settings(request({"revision": "0", "time_format": "12h", "interval_minutes": bad,
                                           "category_id": None})))
    saved = payload(run(api.save_settings(request(
        {"revision": "0", "time_format": "24h", "interval_minutes": 10, "category_id": CATEGORY["id"]}))))
    assert saved["settings"] == {"category_id": CATEGORY["id"], "time_format": "24h", "interval_minutes": 10, "revision": "1"}
    with pytest.raises(web.HTTPConflict):
        run(api.save_settings(request({"revision": "0", "time_format": "12h", "interval_minutes": 6, "category_id": None})))


def test_read_sorts_clocks_and_marks_missing_channels(env):
    run(env.store.add_clock({"zone": "Australia/Sydney", "flag": "", "code": None, "channel_id": VOICE["id"]}, "1"))
    run(env.store.add_clock({"zone": "America/New_York", "flag": "", "code": None, "channel_id": "900000000000000999"}, "1"))
    data = payload(run(api.read(request())))
    assert [c["zone"] for c in data["clocks"]] == ["America/New_York", "Australia/Sydney"]
    assert data["clocks"][0]["channel_missing"] is True and data["clocks"][1]["channel_name"] == VOICE["name"]
    assert data["channels_available"] is True
    assert [c["id"] for c in data["voice_channels"]] == [VOICE["id"], VOICE2["id"]]
    assert data["voice_channels"][0]["used"] is True and data["categories"][0]["id"] == CATEGORY["id"]
    assert len(data["chips"]) == 12


def test_read_with_discord_down_still_shows_clocks(env):
    run(env.store.add_clock({"zone": "America/New_York", "flag": "", "code": None, "channel_id": VOICE["id"]}, "1"))
    env.discord.down = True
    data = payload(run(api.read(request())))
    assert data["channels_available"] is False and data["clocks"][0]["channel_missing"] is False


def test_preview_and_zones(env):
    data = payload(run(api.preview(request({"zone": "Asia/Dubai", "flag": "🇦🇪", "code": ""}))))
    assert data["needs_code"] is True and data["name_now"] is None
    data = payload(run(api.preview(request({"zone": "Asia/Dubai", "flag": "🇦🇪", "code": "gst"}))))
    assert data["name_now"].startswith("🇦🇪 GST GMT+4 · ")
    with pytest.raises(web.HTTPBadRequest):
        run(api.preview(request({"zone": "Bad/Zone"})))
    zones = payload(run(api.zones(request())))["zones"]
    assert any(row["zone"] == "Asia/Manila" for row in zones)
    assert not any(row["zone"].startswith("Etc/") for row in zones)
    by_zone = {row["zone"]: row for row in zones}
    assert set(by_zone["America/Chicago"]["codes"]) == {"CST", "CDT"}
    assert by_zone["Asia/Manila"]["codes"] == ["PHT"]
    assert by_zone["Asia/Dubai"]["codes"] == ["GST"]  # Search only; naming still needs a typed code.


def test_unchanged_category_is_not_checked_with_discord_again(env):
    run(api.save_settings(request({"revision": "0", "time_format": "12h", "interval_minutes": 6,
                                   "category_id": CATEGORY["id"]})))
    env.discord.down = True
    saved = payload(run(api.save_settings(request({"revision": "1", "time_format": "24h", "interval_minutes": 6,
                                                   "category_id": CATEGORY["id"]}))))
    assert saved["settings"]["time_format"] == "24h"


def test_remove_keeps_a_voice_channel_from_another_server(env):
    other = {"id": "900000000000000888", "type": 2, "name": "x", "guild_id": "111111111111111111"}
    env.discord.channels.append(other)
    row = clock_on(env, other["id"])
    assert payload(run(api.remove(request({"revision": "1"}, clock_id=row["_id"]))))["channel"] == "kept"
    assert env.discord.deletes == [] and other in env.discord.channels


def test_remove_when_channel_cannot_be_read_removes_nothing(env, monkeypatch):
    row = clock_on(env, VOICE["id"])
    fake = env.discord

    async def hidden(request_, method, path, **kwargs):
        if method == "GET" and path.startswith("/channels/"):
            raise web.HTTPForbidden(text="Discord does not allow this action. Check bot permissions.")
        return await fake(request_, method, path, **kwargs)
    monkeypatch.setattr(api, "discord", hidden)
    with pytest.raises(web.HTTPBadRequest) as raised:  # Never 403: that means "dashboard access lost".
        run(api.remove(request({"revision": "1"}, clock_id=row["_id"])))
    assert "not removed" in raised.value.text and "bot" not in raised.value.text
    assert fake.deletes == [] and len(run(env.store.list_clocks())) == 1


def test_remove_when_channel_vanishes_between_read_and_delete(env):
    row = clock_on(env, VOICE["id"])
    env.discord.fail_delete = server_management.DiscordItemNotFound(10003)
    assert payload(run(api.remove(request({"revision": "1"}, clock_id=row["_id"]))))["channel"] == "gone"
    assert run(env.store.list_clocks()) == []

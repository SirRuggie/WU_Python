import asyncio
import warnings
from datetime import datetime, timezone
from types import SimpleNamespace

import hikari

from extensions.tasks import band_sync_panel as panel
from extensions.tasks import band_sync_schema as schema
from tests.test_band_sync_ical_delivery import FakeMongo, FakeRest


class FakeInteraction:
    def __init__(self, guild_id=None, values=None):
        self.guild_id = guild_id
        self.values = values or []
        self.executed = []

    async def execute(self, content=None, flags=None):
        self.executed.append(content)


class FakeCtx:
    def __init__(self, user_id, guild_id=None, values=None):
        self.user = SimpleNamespace(id=user_id)
        self.interaction = FakeInteraction(guild_id=guild_id, values=values)
        self.responses = []

    async def respond(self, *, embed=None, components=None, edit=False):
        self.responses.append({"embed": embed, "components": components, "edit": edit})


def _event_row(uid="sync-1", start=None, panel_channel_id=None, panel_message_id=None):
    start = start or datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    row = schema.new_event_doc(
        {"uid": uid, "start": start, "calendar": "Sync3", "summary": "FWA high sync"},
        panel_channel_id=panel_channel_id, panel_message_id=panel_message_id,
    )
    return row


# ---- panel_embed: lists by status ----
def test_panel_embed_lists_users_by_status():
    event = _event_row()
    responses = [
        schema.normalize_response({"user_id": 1, "status": "in"}),
        schema.normalize_response({"user_id": 2, "status": "in"}),
        schema.normalize_response({"user_id": 3, "status": "maybe"}),
        schema.normalize_response({"user_id": 4, "status": "no"}),
    ]
    embed = panel.panel_embed(event, responses)
    fields = {f.name: f.value for f in embed.fields}
    assert fields["✅ Going"] == "<@1>, <@2>"
    assert fields["❔ Maybe"] == "<@3>"
    assert fields["❌ Not going"] == "<@4>"


def test_panel_embed_empty_group_says_nobody_yet():
    event = _event_row()
    embed = panel.panel_embed(event, [])
    fields = {f.name: f.value for f in embed.fields}
    assert fields["✅ Going"] == "nobody yet"
    assert fields["❔ Maybe"] == "nobody yet"
    assert fields["❌ Not going"] == "nobody yet"


# ---- status handler: upserts and clears reminders on leaving "in" ----
def test_opting_in_then_leaving_clears_reminders():
    mongo = FakeMongo(events=[_event_row(panel_channel_id=None, panel_message_id=None)])
    ctx = FakeCtx(user_id=42, guild_id=555)

    asyncio.run(panel.fwa_sync_in(ctx, "sync-1", bot=None, mongo=mongo))
    stored = mongo.fwa_sync_responses.documents[schema.response_id("sync-1", 42)]
    assert stored["status"] == "in"

    # give them a reminder, then have them opt out - reminders must be cleared
    asyncio.run(panel.upsert_response(
        mongo, "sync-1", mongo.fwa_sync_events.documents[schema.event_id("sync-1")],
        42, "in", [60],
    ))
    asyncio.run(panel.fwa_sync_no(ctx, "sync-1", bot=None, mongo=mongo))
    stored = mongo.fwa_sync_responses.documents[schema.response_id("sync-1", 42)]
    assert stored["status"] == "no"
    assert stored["reminders"] == []


# ---- reminder select: rejected unless "in" ----
def test_reminders_rejected_unless_opted_in():
    mongo = FakeMongo(events=[_event_row()])
    ctx = FakeCtx(user_id=42, guild_id=555, values=["60"])

    asyncio.run(panel.fwa_sync_reminders(ctx, "sync-1", bot=None, mongo=mongo))

    assert schema.response_id("sync-1", 42) not in mongo.fwa_sync_responses.documents
    assert ctx.interaction.executed == [panel.MSG_OPT_IN_FIRST]


def test_reminders_accepted_once_opted_in():
    event = _event_row()
    response = schema.new_response_doc(
        "sync-1", 42, event["start_at"], event["event_version"], "in",
    )
    mongo = FakeMongo(events=[event], responses=[response])
    ctx = FakeCtx(user_id=42, guild_id=555, values=["10"])

    asyncio.run(panel.fwa_sync_reminders(ctx, "sync-1", bot=None, mongo=mongo))

    stored = mongo.fwa_sync_responses.documents[schema.response_id("sync-1", 42)]
    assert stored["reminders"] == [10]


# ---- "All" -> [60, 10, 0] ----
def test_reminders_all_selects_every_offset():
    event = _event_row()
    response = schema.new_response_doc(
        "sync-1", 42, event["start_at"], event["event_version"], "in",
    )
    mongo = FakeMongo(events=[event], responses=[response])
    ctx = FakeCtx(user_id=42, guild_id=555, values=["all"])

    asyncio.run(panel.fwa_sync_reminders(ctx, "sync-1", bot=None, mongo=mongo))

    stored = mongo.fwa_sync_responses.documents[schema.response_id("sync-1", 42)]
    assert stored["reminders"] == [60, 10, 0]


# ---- DM replace deletes previous id ----
def test_send_dm_deletes_previous_message_before_sending():
    rest = FakeRest()
    bot = SimpleNamespace(rest=rest)
    mongo = FakeMongo()
    event = {"uid": "sync-1", "start": datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc),
             "summary": "FWA high sync", "calendar": "Sync3"}
    response = schema.new_response_doc(
        "sync-1", 42, event["start"], "v1", "in",
        dm_channel_id=111, dm_message_id=222,
    )
    mongo.fwa_sync_responses.documents[response["_id"]] = response

    result = asyncio.run(panel.send_dm(mongo, bot, event, response, "https://band.us", "once"))

    assert result.sent is True
    assert (111, 222) in rest.deleted_messages
    stored = mongo.fwa_sync_responses.documents[response["_id"]]
    assert stored["dm_channel_id"] == 42       # FakeRest.create_dm_channel(user_id) returns user_id
    assert stored["dm_message_id"] != 222


# ---- unknown uid message ----
def test_unknown_uid_gets_passed_message():
    mongo = FakeMongo()
    ctx = FakeCtx(user_id=42, guild_id=555)

    asyncio.run(panel.fwa_sync_in(ctx, "no-such-uid", bot=None, mongo=mongo))

    assert ctx.interaction.executed == [panel.MSG_PASSED]
    assert ctx.responses == []


# ---- panel replacement deletes previous panel id ----
def test_post_or_replace_panel_deletes_previous_events_panel():
    rest = FakeRest()
    bot = SimpleNamespace(rest=rest)
    old_event = _event_row(uid="old-sync", panel_channel_id=777, panel_message_id=888)
    new_event = _event_row(uid="new-sync")
    mongo = FakeMongo(events=[old_event, new_event])
    # current_panel (not the old event row) is the source of truth for what to delete -
    # see DECISIONS.md D013.
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(
        panel_channel_id=777,
        current_panel={"uid": "old-sync", "channel_id": 777, "message_id": 888},
    )

    asyncio.run(panel.post_or_replace_panel(mongo, bot, new_event))

    assert (777, 888) in rest.deleted_messages
    stored = mongo.fwa_sync_events.documents[schema.event_id("new-sync")]
    assert stored["panel_channel_id"] == 777
    assert stored["panel_message_id"] is not None


# ---- NotFound repost once ----
def test_refresh_panel_reposts_once_on_not_found():
    class NotFoundOnEditRest(FakeRest):
        async def edit_message(self, channel_id, message_id, embed=None, components=None):
            raise hikari.NotFoundError("https://discord.test", {}, {}, "unknown message")

    rest = NotFoundOnEditRest()
    bot = SimpleNamespace(rest=rest)
    event = _event_row(panel_channel_id=777, panel_message_id=888)
    mongo = FakeMongo(events=[event])

    asyncio.run(panel.refresh_panel_message(mongo, bot, event, [], "https://band.us"))

    assert rest.attempts == [777]  # one repost create_message call
    stored = mongo.fwa_sync_events.documents[schema.event_id(event["uid"])]
    assert stored["panel_message_id"] != 888


# ---- repost-on-NotFound must update config.current_panel too (refuter-04 must-fix) ----
def test_refresh_panel_repost_updates_config_current_panel_and_old_message_is_deleted_later():
    class NotFoundOnEditRest(FakeRest):
        async def edit_message(self, channel_id, message_id, embed=None, components=None):
            raise hikari.NotFoundError("https://discord.test", {}, {}, "unknown message")

    rest = NotFoundOnEditRest()
    bot = SimpleNamespace(rest=rest)
    event_a = _event_row(uid="sync-A")
    mongo = FakeMongo(events=[event_a])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=777)

    # post m1
    asyncio.run(panel.post_or_replace_panel(mongo, bot, event_a))
    stored_a = mongo.fwa_sync_events.documents[schema.event_id("sync-A")]
    m1 = stored_a["panel_message_id"]
    assert mongo.fwa_sync_config.documents["config"]["current_panel"]["message_id"] == m1

    # hand-delete + click: refresh_panel_message's edit fails NotFound, reposts m2
    asyncio.run(panel.refresh_panel_message(mongo, bot, stored_a, [], "https://band.us"))
    stored_a = mongo.fwa_sync_events.documents[schema.event_id("sync-A")]
    m2 = stored_a["panel_message_id"]
    assert m2 != m1
    assert mongo.fwa_sync_config.documents["config"]["current_panel"]["message_id"] == m2

    # purge (deletes the event row, D003/D013) then discover event B - m2 must be
    # deleted, not orphaned, because config.current_panel now points at it.
    del mongo.fwa_sync_events.documents[schema.event_id("sync-A")]
    event_b = _event_row(uid="sync-B", start=datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc))
    mongo.fwa_sync_events.documents[schema.event_id("sync-B")] = event_b

    asyncio.run(panel.post_or_replace_panel(mongo, bot, event_b))

    assert (777, m2) in rest.deleted_messages
    assert mongo.fwa_sync_config.documents["config"]["current_panel"]["uid"] == "sync-B"


# ---- panel id lives on the config singleton, so it survives purge (refuter-03 must-fix 1) ----
def test_panel_survives_purge_and_old_panel_is_deleted_on_next_discovery():
    rest = FakeRest()
    bot = SimpleNamespace(rest=rest)
    old_event = _event_row(uid="old-sync", panel_channel_id=777, panel_message_id=888)
    mongo = FakeMongo(events=[old_event])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(
        panel_channel_id=777,
        current_panel={"uid": "old-sync", "channel_id": 777, "message_id": 888},
    )

    # purge_finished_events() deletes the old event row but never touches config
    # (DECISIONS.md D003) - simulate that here rather than importing band_sync_ical.
    del mongo.fwa_sync_events.documents[schema.event_id("old-sync")]

    new_event = _event_row(uid="new-sync", start=datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc))
    mongo.fwa_sync_events.documents[schema.event_id("new-sync")] = new_event

    asyncio.run(panel.post_or_replace_panel(mongo, bot, new_event))

    assert (777, 888) in rest.deleted_messages
    stored_config = mongo.fwa_sync_config.documents["config"]
    assert stored_config["current_panel"]["uid"] == "new-sync"
    stored_event = mongo.fwa_sync_events.documents[schema.event_id("new-sync")]
    assert stored_event["panel_message_id"] is not None


# ---- times normalize through Mongo round trip (refuter-03 must-fix 2) ----
def test_panel_embed_times_agree_after_mongo_round_trip():
    aware_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    event = _event_row(start=aware_start)
    event["start_at"] = event["start_at"].replace(tzinfo=None)  # mimic a Mongo read

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # HikariWarning on a naive Embed timestamp must raise
        embed = panel.panel_embed(event, [])

    assert embed.timestamp == aware_start
    sync_field = next(f for f in embed.fields if f.name == "Sync Time")
    assert panel.discord_timestamp(aware_start, "F") in sync_field.value
    assert panel.discord_timestamp(aware_start, "R") in sync_field.value


# ---- DM-once never sets a status (refuter-03 must-fix 3) ----
def test_dm_once_for_fresh_user_sets_no_status_and_is_unlisted():
    rest = FakeRest()
    bot = SimpleNamespace(rest=rest)
    event = _event_row()
    mongo = FakeMongo(events=[event])
    ctx = FakeCtx(user_id=42, guild_id=555)

    asyncio.run(panel.fwa_sync_dm_once(ctx, "sync-1", bot=bot, mongo=mongo))

    stored = mongo.fwa_sync_responses.documents[schema.response_id("sync-1", 42)]
    assert stored["status"] is None

    embed = panel.panel_embed(event, [schema.normalize_response(stored)])
    fields = {f.name: f.value for f in embed.fields}
    assert "<@42>" not in fields["✅ Going"]
    assert "<@42>" not in fields["❔ Maybe"]
    assert "<@42>" not in fields["❌ Not going"]


# ---- _mentions caps at 1024 chars (noted, non-blocking) ----
def test_mentions_caps_at_1024_chars_with_more_suffix():
    user_ids = [100000000000000000 + i for i in range(60)]
    result = panel._mentions(user_ids)

    assert len(result) <= 1024
    assert result.endswith("more")
    assert result.count("<@") < 60


# ---- real BAND uid shape driven through a handler and its custom_id (noted) ----
def test_real_band_uid_shape_survives_custom_id_and_handler():
    uid = "4/71428305/1006326105/19700101@band.us"
    mongo = FakeMongo(events=[_event_row(uid=uid)])
    ctx = FakeCtx(user_id=42, guild_id=555)

    # extensions/components.py:_dispatch does raw.partition(":") - exercise the same
    # split so a uid shape with no colon is proven to survive it.
    custom_id = f"fwa_sync_in:{uid}"
    command_name, _, action_id = custom_id.partition(":")
    assert command_name == "fwa_sync_in"
    assert action_id == uid

    asyncio.run(panel.fwa_sync_in(ctx, action_id, bot=None, mongo=mongo))

    stored = mongo.fwa_sync_responses.documents[schema.response_id(uid, 42)]
    assert stored["status"] == "in"


# ---- _render_after_change's DM branch (noted) ----
def test_apply_status_from_dm_edits_dm_and_refreshes_channel_panel():
    rest = FakeRest()
    bot = SimpleNamespace(rest=rest)
    event = _event_row(panel_channel_id=777, panel_message_id=888)
    mongo = FakeMongo(events=[event])
    ctx = FakeCtx(user_id=42, guild_id=None)  # clicked from the DM, not the channel

    asyncio.run(panel.fwa_sync_in(ctx, "sync-1", bot=bot, mongo=mongo))

    assert len(ctx.responses) == 1
    assert ctx.responses[0]["edit"] is True  # the DM message itself was edited
    assert (777, 888) in rest.edits  # and the channel panel was refreshed too

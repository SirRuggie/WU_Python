import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import hikari

from extensions.tasks import band_monitor
from extensions.tasks import band_sync_panel as panel
from extensions.tasks import band_sync_schema as schema
from tests.test_band_sync_ical_delivery import FakeMongo, FakeRest
from utils.constants import RED_ACCENT
from utils.emoji import emojis


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


def _texts(container):
    """Text.content of every direct child of a Container that has one, in order -
    what "exact Text contents and order" (brief) means to check against."""
    return [child.content for child in container.components if hasattr(child, "content")]


def _url_for(event):
    return panel.band_url(event, schema.new_config_doc())


# ---- panel_container: exact layout, DECISIONS.md D001 mockup, zero responses ----
def test_panel_container_exact_layout_zero_responses():
    event = _event_row()
    url = _url_for(event)
    components = panel.panel_container(event, url, [])

    assert len(components) == 1
    container = components[0]
    assert container.accent_color == RED_ACCENT

    start = panel._start_of(event)
    assert _texts(container) == [
        "## ⚔️ War Sync Event has been posted.",
        f"<@&{band_monitor.ALLOWED_ROLE_ID}> - A new FWA War Sync has been scheduled!",
        f"**Sync Time:** {panel.discord_timestamp(start, 'F')} · {panel.discord_timestamp(start, 'R')}",
        "Please review the **FWA Sync Time** and confirm your availability by selecting the "
        "corresponding button below:",
        f"{str(emojis.yes)} - If you are available to start.",
        f"{str(emojis.maybe)} - If you may be available to start.",
        f"{str(emojis.no)} - If you are unavailable to start.",
        "*Please note that if your availability changes, you can update your response by "
        "selecting the appropriate button.*",
        "## Rep Availability",
        "*No responses yet...*",
    ]
    assert len(container.components) <= 40


# ---- panel_container: exact layout with 3 responses, in -> maybe -> no order ----
def test_panel_container_exact_layout_three_responses():
    event = _event_row()
    url = _url_for(event)
    responses = [
        schema.normalize_response({"user_id": 1, "status": "in"}),
        schema.normalize_response({"user_id": 2, "status": "maybe"}),
        schema.normalize_response({"user_id": 3, "status": "no"}),
    ]
    components = panel.panel_container(event, url, responses)
    texts = _texts(components[0])

    assert texts[-1] == (
        f"{str(emojis.yes)} **Available** - <@1>\n"
        f"{str(emojis.maybe)} **Maybe** - <@2>\n"
        f"{str(emojis.no)} **Unavailable** - <@3>"
    )
    assert texts[-2] == "## Rep Availability"
    assert len(components[0].components) <= 40


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


# ---- role ping must notify: create_message needs role_mentions/user_mentions
# (refuter-01 must-fix 1) ----
def test_post_or_replace_panel_pings_the_allowed_role():
    rest = FakeRest()
    bot = SimpleNamespace(rest=rest)
    event = _event_row()
    mongo = FakeMongo(events=[event])
    mongo.fwa_sync_config.documents["config"] = schema.new_config_doc(panel_channel_id=777)

    asyncio.run(panel.post_or_replace_panel(mongo, bot, event))

    channel, role_mentions, user_mentions = rest.create_calls[-1]
    assert channel == 777
    assert role_mentions == [band_monitor.ALLOWED_ROLE_ID]
    assert user_mentions is True


def test_refresh_panel_repost_on_not_found_also_pings_the_allowed_role():
    class NotFoundOnEditRest(FakeRest):
        async def edit_message(self, channel_id, message_id, embed=None, components=None):
            raise hikari.NotFoundError("https://discord.test", {}, {}, "unknown message")

    rest = NotFoundOnEditRest()
    bot = SimpleNamespace(rest=rest)
    event = _event_row(panel_channel_id=777, panel_message_id=888)
    mongo = FakeMongo(events=[event])

    asyncio.run(panel.refresh_panel_message(mongo, bot, event, [], "https://band.us"))

    channel, role_mentions, user_mentions = rest.create_calls[-1]
    assert channel == 777
    assert role_mentions == [band_monitor.ALLOWED_ROLE_ID]
    assert user_mentions is True


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
def test_panel_container_times_agree_after_mongo_round_trip():
    aware_start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    event = _event_row(start=aware_start)
    event["start_at"] = event["start_at"].replace(tzinfo=None)  # mimic a Mongo read
    url = _url_for(event)

    components = panel.panel_container(event, url, [])

    sync_line = next(t for t in _texts(components[0]) if t.startswith("**Sync Time:**"))
    assert panel.discord_timestamp(aware_start, "F") in sync_line
    assert panel.discord_timestamp(aware_start, "R") in sync_line


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

    lines = panel._availability_lines([schema.normalize_response(stored)])
    assert "<@42>" not in lines


# ---- _availability_lines caps at 4000 chars (Text component hard cap) ----
def test_availability_lines_caps_at_4000_chars_with_more_suffix():
    responses = [
        schema.normalize_response({"user_id": 100000000000000000 + i, "status": "in"})
        for i in range(200)
    ]
    result = panel._availability_lines(responses)

    assert len(result) <= 4000
    assert result.rstrip().split("\n")[-1].endswith("more*")


# ---- whole container stays under Discord's 4000-char-per-message-of-Text ceiling with
# a big roster, not just the availability Text on its own (refuter-01 must-fix 2) ----
def test_panel_container_total_text_chars_stay_under_4000_with_200_responders():
    event = _event_row()
    url = _url_for(event)
    responses = [
        schema.normalize_response({"user_id": 100000000000000000 + i, "status": "in"})
        for i in range(200)
    ]

    components = panel.panel_container(event, url, responses)
    texts = _texts(components[0])
    total_chars = sum(len(t) for t in texts)

    assert total_chars <= 4000
    assert texts[-1].rstrip().split("\n")[-1].endswith("more*")


# ---- a button click must never crash when an edit is rejected as too large
# (refuter-01 must-fix 2) ----
def test_apply_status_from_channel_survives_badrequest_on_edit():
    class RaisingCtx(FakeCtx):
        async def respond(self, *, embed=None, components=None, edit=False):
            raise hikari.BadRequestError("https://discord.test", {}, {}, "too long")

    event = _event_row()
    mongo = FakeMongo(events=[event])
    ctx = RaisingCtx(user_id=42, guild_id=555)

    asyncio.run(panel.fwa_sync_in(ctx, "sync-1", bot=None, mongo=mongo))

    stored = mongo.fwa_sync_responses.documents[schema.response_id("sync-1", 42)]
    assert stored["status"] == "in"  # the RSVP itself still landed


def test_refresh_panel_message_survives_badrequest_on_edit():
    class BadRequestOnEditRest(FakeRest):
        async def edit_message(self, channel_id, message_id, embed=None, components=None):
            raise hikari.BadRequestError("https://discord.test", {}, {}, "too long")

    rest = BadRequestOnEditRest()
    bot = SimpleNamespace(rest=rest)
    event = _event_row(panel_channel_id=777, panel_message_id=888)
    mongo = FakeMongo(events=[event])

    asyncio.run(panel.refresh_panel_message(mongo, bot, event, [], "https://band.us"))
    # no exception -> handler completed


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


# ---- status_rows: exact button styles/custom_ids/labels/emoji, select present ----
def test_status_rows_buttons_and_select():
    row1, row2 = panel.status_rows("sync-1")

    buttons = row1.components
    assert [b.custom_id for b in buttons] == [
        "fwa_sync_in:sync-1", "fwa_sync_maybe:sync-1",
        "fwa_sync_no:sync-1", "fwa_sync_dm_once:sync-1",
    ]
    assert [b.label for b in buttons] == ["Yes", "Maybe", "No", "DM me the time"]
    assert [b.style for b in buttons] == [
        hikari.ButtonStyle.SUCCESS, hikari.ButtonStyle.SECONDARY,
        hikari.ButtonStyle.DANGER, hikari.ButtonStyle.SECONDARY,
    ]
    assert buttons[0].emoji == emojis.yes.partial_emoji
    assert buttons[1].emoji == emojis.maybe.partial_emoji
    assert buttons[2].emoji == emojis.no.partial_emoji
    assert buttons[3].emoji == "📩"

    select = row2.components[0]
    assert select.custom_id == "fwa_sync_reminders:sync-1"
    assert select.placeholder == "Reminders (opt in first)…"
    assert [option.value for option in select.options] == ["60", "10", "0", "all"]


# ---- dm_container: role ping and Rep Availability list are gone; status line instead ----
def test_dm_container_has_no_role_ping_or_availability_list():
    event = _event_row()
    url = _url_for(event)
    components = panel.dm_container(event, url, None)
    texts = _texts(components[0])

    assert not any(str(band_monitor.ALLOWED_ROLE_ID) in t for t in texts)
    assert "## Rep Availability" not in texts
    assert texts[0] == "## ⚔️ War Sync Event has been posted."
    assert texts[-1].startswith("**Your response:**")


# ---- dm_container: "Your response" line for every status and unanswered ----
def test_dm_container_status_line_per_status():
    event = _event_row()
    url = _url_for(event)
    cases = [
        (None, "*not answered yet*"),
        ("in", str(emojis.yes)),
        ("maybe", str(emojis.maybe)),
        ("no", str(emojis.no)),
    ]
    for status, expect_fragment in cases:
        response = None if status is None else schema.normalize_response({"status": status})
        components = panel.dm_container(event, url, response)
        line = next(t for t in _texts(components[0]) if t.startswith("**Your response:**"))
        assert expect_fragment in line


# ---- dm_container: change alert carries a "Was" line under Sync Time ----
def test_dm_container_change_alert_adds_was_line():
    event = _event_row()
    url = _url_for(event)
    old_start = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)

    components = panel.dm_container(event, url, None, old_start=old_start)
    texts = _texts(components[0])

    was_line = next(t for t in texts if t.startswith("**Was:**"))
    assert panel.discord_timestamp(old_start, "F") in was_line
    sync_index = texts.index(next(t for t in texts if t.startswith("**Sync Time:**")))
    assert texts[sync_index + 1] == was_line  # directly under Sync Time
    assert len(components[0].components) <= 40


# ---- dm_container: change-alert DM title, DECISIONS.md D003 (restores old dm_embed
# behaviour, refuter-01 noted) ----
def test_dm_container_change_alert_title():
    event = _event_row()
    url = _url_for(event)
    old_start = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)

    changed = panel.dm_container(event, url, None, old_start=old_start)
    posted = panel.dm_container(event, url, None)

    assert _texts(changed[0])[0] == "## ⏰ FWA Sync Time CHANGED"
    assert _texts(posted[0])[0] == "## ⚔️ War Sync Event has been posted."


# ---- band_monitor no longer posts a panel of its own (band-sync-panel-restyle) ----
def test_band_monitor_posts_nothing_when_a_sync_post_is_seen():
    rest = FakeRest()
    bot = SimpleNamespace(rest=rest)
    # send_war_sync_to_discord reads the module-global bot_instance directly rather than
    # taking one as a parameter, so patch that global for the call.
    original_bot = band_monitor.bot_instance
    band_monitor.bot_instance = bot
    try:
        delivered = asyncio.run(band_monitor.send_war_sync_to_discord(
            {"post_key": "sync", "content": band_monitor.WAR_SYNC_MARKER}
        ))
    finally:
        band_monitor.bot_instance = original_bot

    assert delivered is True
    assert rest.attempts == []

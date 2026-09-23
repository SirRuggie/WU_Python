import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pendulum

from extensions.commands import cwl_dashboard as dashboard
from utils import cwl_campaign, cwl_sequence


def run(coroutine):
    return asyncio.run(coroutine)


def context(*, guild_id=22, user_id=11):
    interaction = SimpleNamespace(
        guild_id=guild_id,
        member=SimpleNamespace(permissions=hikari.Permissions.MANAGE_GUILD),
        edit_initial_response=AsyncMock(),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id), interaction=interaction,
        respond=AsyncMock(),
    )


def draft(*, guild_id=22, cycle="2026-10"):
    return {
        "_id": f"cwl:draft:{guild_id}:" + "f" * 32,
        "token": "f" * 32,
        "user_id": 11,
        "guild_id": guild_id,
        "cycle": cycle,
        "base_revision": 0,
        "campaign": cwl_campaign.default_campaign(),
    }


def text_content(components):
    output = []

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("content"), str):
                output.append(value["content"])
            for child in value.get("components", ()):
                walk(child)

    for component in components:
        walk(component.build()[0])
    return output


def test_overview_shows_edited_signup_time_without_competing_send_times(monkeypatch):
    item = draft()
    draft_time = pendulum.now("America/New_York").add(days=2).isoformat()
    live_time = pendulum.now("America/New_York").add(days=1).isoformat()
    monkeypatch.setattr(
        dashboard.cwl_campaign,
        "resolve_schedule",
        lambda *_args, **_kwargs: [{
            "id": "2026-10|signup|main",
            "message_id": "signup",
            "variant": "main",
            "run_at": draft_time,
        }],
    )
    monkeypatch.setattr(
        dashboard.cwl_campaign,
        "load_campaign",
        AsyncMock(return_value={
            "schedule": [{
                "id": "2026-10|signup|main",
                "message_id": "signup",
                "variant": "main",
                "run_at": live_time,
            }],
            "deliveries": [],
            "skipped": [],
        }),
    )

    content = "\n".join(text_content(run(dashboard.panel(item, "overview", mongo=object()))))
    assert dashboard._discord_time(draft_time) in content
    assert dashboard._discord_time(live_time) not in content
    assert "Some edits are not in use yet" in content
    assert "Next message" not in content
    assert "CWL announcements" in content
    assert "delivery" not in content.lower()


def test_default_dashboard_open_does_not_resume_a_draft_from_an_old_cycle(monkeypatch):
    stale = draft(cycle="2026-08")
    current = draft(cycle="2026-09")

    async def find(_mongo, _guild, _user, cycle=None):
        return stale if cycle is None else current

    monkeypatch.setattr(dashboard.cwl_campaign, "find_draft", find)
    monkeypatch.setattr(
        dashboard.cwl_campaign, "load_campaign",
        AsyncMock(return_value={"cycle": "2026-09"}),
    )
    monkeypatch.setattr(dashboard, "panel", AsyncMock(return_value=[]))

    opened = run(dashboard.open_dashboard(context(), object()))
    assert opened["cycle"] == "2026-09"


def test_overview_shows_one_next_message_only_for_settings_already_in_use(monkeypatch):
    item = draft()
    when = pendulum.now("UTC").add(days=2).isoformat()
    saved = {
        "campaign": deepcopy(item["campaign"]),
        "schedule": [{"id": "2026-10|signup|main", "message_id": "signup", "run_at": when}],
        "deliveries": [], "skipped": [],
    }
    monkeypatch.setattr(dashboard.cwl_campaign, "load_campaign", AsyncMock(return_value=saved))
    content = "\n".join(text_content(run(dashboard.panel(item, "overview", mongo=object()))))
    assert "These settings are saved." in content
    assert content.count("### Next message") == 1
    assert dashboard._discord_time(when) in content
    assert "delivery" not in content.lower()
    saved["campaign"]["paused"] = True
    item["campaign"]["paused"] = True
    content = "\n".join(text_content(run(dashboard.panel(item, "overview", mongo=object()))))
    assert "Automatic messages are paused." in content
    assert dashboard._discord_time(when) not in content


def test_schedule_upcoming_list_excludes_past_occurrences(monkeypatch):
    item = draft(cycle="2026-09")
    now = pendulum.now("UTC")
    monkeypatch.setattr(
        dashboard.cwl_campaign,
        "resolve_schedule",
        lambda *_args, **_kwargs: [
            {
                "id": "2026-09|signup|main", "message_id": "signup",
                "variant": "main", "run_at": now.subtract(days=1).isoformat(),
            },
            {
                "id": "2026-09|reminder:1|main", "message_id": "reminder:1",
                "variant": "main", "run_at": now.add(days=1).isoformat(),
            },
        ],
    )

    content = text_content(run(dashboard.panel(item, "schedule")))
    upcoming = next(value for value in content if value.startswith("### Message times"))
    assert "Signups open" not in upcoming
    assert "Reminder 1" in upcoming


def test_first_defaults_review_compares_against_effective_legacy_defaults(monkeypatch):
    guild_id = cwl_campaign.LEGACY_WU_GUILD_ID
    item = draft(guild_id=guild_id)
    legacy = {
        "_id": "schedule", "enabled": True,
        "day": 29, "hour": 18, "minute": 45,
        "followups": [],
    }
    mongo = SimpleNamespace(
        bot_config=SimpleNamespace(find_one=AsyncMock(return_value=None)),
        cwl_reminder=SimpleNamespace(find_one=AsyncMock(return_value=legacy)),
    )
    monkeypatch.setattr(
        dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=item)
    )
    captured = {}

    def summary(before, after, cycle):
        captured.update(before=deepcopy(before), after=deepcopy(after), cycle=cycle)
        return "Changes"

    monkeypatch.setattr(dashboard.cwl_review, "change_summary", summary)
    monkeypatch.setattr(dashboard, "insert_state", AsyncMock())

    run(dashboard.review_apply(
        context(guild_id=guild_id), item["token"] + "|defaults", mongo=mongo
    ))
    signup = captured["before"]["messages"]["signup"]["schedule"]
    assert signup["day"] == 29
    assert signup["hour"] == 18
    assert signup["minute"] == 45


def test_defaults_review_resolves_dates_for_first_affected_cycle(monkeypatch):
    current = pendulum.now("America/New_York").format("YYYY-MM")
    following = pendulum.now("America/New_York").add(months=1).format("YYYY-MM")
    item = draft(cycle=current)
    mongo = SimpleNamespace(
        bot_config=SimpleNamespace(find_one=AsyncMock(return_value=None)),
        cwl_reminder=SimpleNamespace(find_one=AsyncMock(return_value=None)),
    )
    monkeypatch.setattr(
        dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=item)
    )
    captured = {}

    def summary(before, after, cycle):
        captured["cycle"] = cycle
        return "Changes"

    monkeypatch.setattr(dashboard.cwl_review, "change_summary", summary)
    monkeypatch.setattr(dashboard, "insert_state", AsyncMock())

    output = run(dashboard.review_apply(
        context(), item["token"] + "|defaults", mongo=mongo
    ))
    assert captured["cycle"] == following
    assert following in "\n".join(text_content(output))


def test_turning_off_sequence_does_not_restore_old_automatic_reminder_times(monkeypatch):
    item = draft()
    campaign = item["campaign"]
    campaign["reminder_sequence"] = {
        "enabled": True,
        "mode": "evenly",
        "count": 4,
        "interval_hours": 48,
        "final_hours": 3,
        "min_gap_hours": 3,
    }
    assert campaign["messages"]["reminder:1"]["schedule"]["mode"] == "legacy_chain"
    monkeypatch.setattr(
        dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=item)
    )
    saved = {}

    async def patch(_mongo, _token, update):
        saved.update(deepcopy(update["campaign"]))
        result = deepcopy(item)
        result["campaign"] = deepcopy(update["campaign"])
        return result

    async def autosave(_ctx, _mongo, _draft, updated_campaign):
        result = await patch(_mongo, _draft["token"], {"campaign": updated_campaign})
        return result, "Scheduled."

    monkeypatch.setattr(dashboard, "_save_timing", autosave)
    monkeypatch.setattr(dashboard, "panel", AsyncMock(return_value=[]))

    run(dashboard.disable_sequence(context(), item["token"], mongo=object()))
    assert saved["reminder_sequence"]["enabled"] is False
    for message_id, message in saved["messages"].items():
        if message_id.startswith("reminder:"):
            assert message["schedule"] == {"mode": "manual"}
    assert all(
        occurrence.get("run_at") is None
        for occurrence in cwl_campaign.resolve_schedule(saved, item["cycle"])
        if occurrence["message_id"].startswith("reminder:")
    )


def test_review_routes_temporarily_invalid_sequence_back_to_timing_steps(monkeypatch):
    item = draft()
    campaign = cwl_sequence.configure(
        item["campaign"], "evenly", count=4,
        final_hours=3, min_gap_hours=3,
    )
    campaign["messages"]["signup"]["schedule"] = {
        "mode": "specific", "at": "2026-10-30T17:00:00",
    }
    campaign["signup_deadline"] = {
        "at": "2026-10-29T17:00:00",
    }
    item["campaign"] = campaign
    monkeypatch.setattr(
        dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=item)
    )
    monkeypatch.setattr(
        dashboard.cwl_campaign, "load_campaign",
        AsyncMock(return_value={"campaign": cwl_campaign.default_campaign()}),
    )
    insert = AsyncMock()
    monkeypatch.setattr(dashboard, "insert_state", insert)

    output = run(dashboard.review_apply(
        context(), item["token"] + "|cycle", mongo=object()
    ))
    content = "\n".join(text_content(output))
    assert "review is not ready" in content.lower()
    assert "signups" in content.lower()
    assert "previous sending schedule stays unchanged" in content.lower()
    insert.assert_not_awaited()


def test_defaults_scoped_draft_header_and_timeline_use_next_active_cycle():
    current = pendulum.now("America/New_York").format("YYYY-MM")
    following = pendulum.now("America/New_York").add(months=1).format("YYYY-MM")
    item = draft(cycle=current)
    # A failed defaults Apply can persist this scope while the draft's own
    # cycle remains current. Every visible date must still describe the first
    # month the defaults can affect.
    item["scope"] = "defaults"
    opening = next(
        row["run_at"]
        for row in cwl_campaign.resolve_schedule(item["campaign"], following)
        if row["message_id"] == "signup" and row["variant"] == "main"
    )
    opening_timestamp = int(pendulum.parse(opening).timestamp())

    content = "\n".join(text_content(run(dashboard.panel(item, "schedule"))))
    assert "For future months, starting" in content
    assert f"<t:{opening_timestamp}:F>" in content
    assert "Cycle →" not in content

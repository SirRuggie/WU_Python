import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import cwl_dashboard as dashboard
from utils import cwl_campaign


def _draft():
    return {
        "_id": "cwl:draft:2:" + "a" * 32, "token": "a" * 32,
        "user_id": 1, "guild_id": 2, "cycle": "2026-10", "base_revision": 0,
        "campaign": cwl_campaign.default_campaign(),
    }


def _ctx(values=None):
    values = values or {}
    return SimpleNamespace(
        user=SimpleNamespace(id=1),
        interaction=SimpleNamespace(
            guild_id=2, member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR),
            message=None, components=[[SimpleNamespace(custom_id=key, value=value)] for key, value in values.items()],
            edit_initial_response=AsyncMock(),
        ),
        defer=AsyncMock(), respond_with_modal=AsyncMock(),
    )


def _component_text(components):
    return str(components[0].build()[0])


def _schema_stats(components):
    """Return every nested component and custom id from Components V2 builders."""
    roots = [builder.build()[0] for builder in components]
    nodes = []
    custom_ids = []

    def walk(node):
        nodes.append(node)
        if "custom_id" in node:
            custom_ids.append(node["custom_id"])
        for child in node.get("components", ()):
            walk(child)

    for root in roots:
        walk(root)
    return roots, nodes, custom_ids


def test_schedule_panel_offers_recommended_sequence_choices_without_changing_legacy_timing(monkeypatch):
    draft = _draft()
    text = _component_text(asyncio.run(dashboard.panel(draft, "schedule")))
    assert "Edit reminders" in text
    assert "Evenly spread reminders" not in text
    choices = _component_text(dashboard.sequence_panel(draft))
    assert "Evenly spread reminders" in choices
    assert "Every X hours" in choices
    assert draft["campaign"]["reminder_sequence"]["enabled"] is False


def test_sequence_submit_configures_numbered_slots_and_validates_resolved_plan(monkeypatch):
    draft = _draft()
    context = _ctx({"count": "4", "final_hours": "3", "min_gap_hours": "3"})
    context.interaction.edit_initial_response = AsyncMock()

    async def load(_mongo, _token):
        return draft

    saved = []
    async def autosave(_ctx, _mongo, _draft, campaign):
        saved.append(campaign)
        return draft | {"campaign": campaign}, "Scheduled."

    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", load)
    monkeypatch.setattr(dashboard, "_save_timing", autosave)
    asyncio.run(dashboard.submit_sequence(context, "a" * 32 + "|evenly", mongo=object()))
    campaign = saved[0]
    assert campaign["reminder_sequence"] == {
        "enabled": True, "mode": "evenly", "count": 4, "interval_hours": 48,
        "final_hours": 3, "min_gap_hours": 3,
    }
    assert all(f"reminder:{number}" in campaign["messages"] for number in range(1, 11))
    assert context.defer.await_count == 1


def test_interval_modal_uses_only_interval_lead_and_gap_and_keeps_internal_count(monkeypatch):
    draft = _draft()
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    modal_context = _ctx()
    asyncio.run(dashboard.sequence_interval(modal_context, "a" * 32, mongo=object()))
    fields = modal_context.respond_with_modal.call_args.kwargs["components"]
    assert [row.build()[0]["components"][0]["custom_id"] for row in fields] == [
        "interval_hours", "final_hours", "min_gap_hours",
    ]

    saved = []

    async def autosave(_ctx, _mongo, _draft, campaign):
        saved.append(campaign)
        return draft | {"campaign": campaign}, "Scheduled."

    monkeypatch.setattr(dashboard, "_save_timing", autosave)
    submit_context = _ctx({"interval_hours": "48", "final_hours": "1", "min_gap_hours": "3"})
    asyncio.run(dashboard.submit_sequence(submit_context, "a" * 32 + "|interval", mongo=object()))
    assert saved[0]["reminder_sequence"] == {
        "enabled": True, "mode": "interval", "count": 4, "interval_hours": 48,
        "final_hours": 1, "min_gap_hours": 3,
    }


def test_intermediate_invalid_deadline_saves_so_sequence_can_be_repaired(monkeypatch):
    from utils import cwl_sequence

    draft = _draft() | {
        "campaign": cwl_sequence.configure(
            cwl_campaign.default_campaign(), "evenly", count=4, final_hours=3, min_gap_hours=3,
        ),
    }
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    saved = []
    async def autosave(_ctx, _mongo, _draft, campaign):
        saved.append(campaign)
        return draft | {"campaign": campaign}, "NOT SCHEDULED: Signup deadline must be after signups open. Your previous sending schedule is unchanged."
    monkeypatch.setattr(dashboard, "_save_timing", autosave)
    context = _ctx({"date": "2026-10-20", "time": "17:30", "timezone": "America/New_York"})

    asyncio.run(dashboard.submit_settings(context, "a" * 32 + "|specific", mongo=object()))

    assert len(saved) == 1
    rendered = _component_text(context.interaction.edit_initial_response.call_args.kwargs["components"])
    assert "NOT SCHEDULED:" in rendered
    assert "previous sending schedule is unchanged" in rendered


def test_stale_numbered_schedule_submit_redirects_without_saving(monkeypatch):
    from utils import cwl_sequence

    draft = _draft() | {
        "campaign": cwl_sequence.configure(cwl_campaign.default_campaign(), "evenly", count=4),
    }
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    save = AsyncMock()
    monkeypatch.setattr(dashboard.cwl_campaign, "patch_draft", save)
    context = _ctx({"amount": "3", "unit": "hours"})

    asyncio.run(dashboard.submit_schedule(context, "a" * 32 + "|reminder:1|before_close", mongo=object()))

    save.assert_not_awaited()
    assert "Numbered reminders are timed by the reminder sequence" in _component_text(
        context.interaction.edit_initial_response.call_args.kwargs["components"]
    )


def test_manual_signup_opening_saves_intermediate_sequence_repair(monkeypatch):
    from utils import cwl_sequence

    draft = _draft() | {
        "campaign": cwl_sequence.configure(cwl_campaign.default_campaign(), "evenly", count=4),
    }
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    saved = []
    async def autosave(_ctx, _mongo, _draft, campaign):
        saved.append(campaign)
        return draft | {"campaign": campaign}, "NOT SCHEDULED: Choose a signup opening time before automatic reminders. Your previous sending schedule is unchanged."
    monkeypatch.setattr(dashboard, "_save_timing", autosave)
    context = _ctx()
    context.interaction.values = ("manual",)

    asyncio.run(dashboard.edit_schedule(context, "a" * 32 + "|signup", mongo=object()))

    assert len(saved) == 1
    assert "NOT SCHEDULED:" in _component_text(
        context.interaction.edit_initial_response.call_args.kwargs["components"]
    )


def test_sequence_schedule_redirects_numbered_reminders_and_lists_each_time_once(monkeypatch):
    campaign = cwl_campaign.default_campaign()
    from utils import cwl_sequence
    campaign = cwl_sequence.configure(campaign, "evenly", count=4, final_hours=3, min_gap_hours=3)
    draft = _draft() | {"campaign": campaign}
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    context = _ctx()
    context.interaction.values = ("reminder:1",)
    redirected = asyncio.run(dashboard.choose_schedule(context, "a" * 32, mongo=object()))
    assert "Numbered reminders are timed by the reminder sequence" in _component_text(redirected)

    listed = asyncio.run(dashboard.sequence_times(context, "a" * 32, mongo=object()))
    text = _component_text(listed)
    assert text.count("Reminder 1") == 1
    assert text.count("Reminder 4") == 1


def test_sequence_panels_are_well_nested_bounded_and_have_unique_component_ids(monkeypatch):
    from utils import cwl_sequence

    draft = _draft() | {
        "campaign": cwl_sequence.configure(cwl_campaign.default_campaign(), "evenly", count=4),
    }
    monkeypatch.setattr(dashboard.cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    context = _ctx()
    panels = [
        asyncio.run(dashboard.panel(draft, "schedule")),
        dashboard.sequence_panel(draft),
        asyncio.run(dashboard.sequence_times(context, "a" * 32, mongo=object())),
    ]
    for rendered in panels:
        roots, nodes, custom_ids = _schema_stats(rendered)
        assert roots and roots[0]["type"] == hikari.ComponentType.CONTAINER
        assert len(nodes) <= 40
        assert len(custom_ids) == len(set(custom_ids))
        assert all(len(custom_id) <= 100 for custom_id in custom_ids)

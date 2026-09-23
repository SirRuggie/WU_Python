import asyncio
from unittest.mock import AsyncMock

from extensions.commands import cwl_dashboard as ui
from extensions.components import registered_functions
from tests.test_cwl_dashboard_integration import MemoryMongo, modal_context
from utils import cwl_campaign, cwl_sequence


def nodes(components):
    def walk(node):
        yield node
        for child in node.get("components", ()):
            yield from walk(child)
    return [node for component in components for node in walk(component.build()[0])]


async def click_back(components, ctx, mongo):
    buttons = [node for node in nodes(components) if str(node.get("label", "")).startswith("Back")]
    assert len(buttons) == 1
    assert not buttons[0].get("disabled")
    name, action_id = buttons[0]["custom_id"].split(":", 1)
    return await registered_functions[name].fn(ctx, action_id, mongo=mongo)


def test_submenu_back_buttons_invoke_working_handlers_without_duplicate_tabs(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        campaign = cwl_sequence.configure(draft["campaign"], "evenly", count=4)
        draft = await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        ctx = modal_context()
        token = draft["token"]
        schedule_submenus = [
            ui.closing_editor(draft), ui.monthly_editor(draft, "signup"),
            ui.schedule_editor(draft, "roster"), ui.sequence_panel(draft),
            await ui.sequence_times(ctx, token, mongo=mongo),
            await ui.advanced(ctx, token, mongo=mongo),
        ]
        for submenu in schedule_submenus:
            labels = [node.get("label") for node in nodes(submenu)]
            assert "Overview" not in labels and "Settings" not in labels
            result = await click_back(submenu, ctx, mongo)
            assert result
            assert "Edit reminders" in str(result[0].build()[0])
        for submenu in [ui.message_editor(draft, "signup", "main"), ui.links_editor(draft, "signup", "main"), await ui.preview(ctx, token + "|signup|main", mongo=mongo)]:
            result = await click_back(submenu, ctx, mongo)
            assert result
            assert "out of date" not in str(result[0].build()[0])
        for origin in ("overview", "schedule"):
            result = await ui.save_options(ctx, token + "|" + origin, mongo=mongo)
            assert any(node.get("custom_id") == f"cwl_tab:{token}|overview" for node in nodes(result))
            assert "Use these settings for" not in str(result[0].build()[0])
    asyncio.run(scenario())


def test_schedule_has_four_controls_and_legacy_settings_links_still_work():
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        components = await ui.panel(draft, "schedule")
        buttons = [node for node in nodes(components) if node.get("type") == 2]
        assert len(buttons) == 7  # Three tabs, four task controls.
        assert all(not node.get("disabled") for node in buttons)
        assert all(node.get("label") != "Settings" for node in buttons)
        legacy = await ui.tab(modal_context(), draft["token"] + "|settings", mongo=mongo)
        assert "Edit reminders" in str(legacy[0].build()[0])
    asyncio.run(scenario())

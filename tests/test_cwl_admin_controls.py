import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import cwl_dashboard as ui
from extensions.components import registered_functions
from tests.test_cwl_dashboard_integration import MemoryMongo, modal_context
from utils import cwl_campaign


def test_manage_server_cannot_queue_or_schedule_posts(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        ctx = modal_context(values={"day": "24", "time": "17:00"})
        ctx.interaction.member.permissions = hikari.Permissions.MANAGE_GUILD
        queue = AsyncMock()
        save = AsyncMock()
        monkeypatch.setattr(cwl_campaign, "queue_manual_occurrence", queue)
        monkeypatch.setattr(cwl_campaign, "apply_draft", save)
        result = await ui.queue_manual(ctx, draft["token"] + "|roster|main", mongo=mongo)
        assert "Only administrators" in str(result[0].build()[0])
        await ui.submit_schedule(ctx, draft["token"] + "|signup|day", mongo=mongo)
        queue.assert_not_awaited()
        save.assert_not_awaited()
        assert not ui.can_edit(ctx)
        ctx.interaction.member.permissions = hikari.Permissions.ADMINISTRATOR
        assert ui.can_edit(ctx)
    asyncio.run(scenario())


def test_removed_history_controls_cannot_mutate_state():
    async def scenario():
        for action in ("cwl_retry", "cwl_restore", "cwl_update_start", "cwl_update_confirm"):
            result = await registered_functions[action].fn(SimpleNamespace(), "old-control")
            assert "control was removed" in str(result[0].build()[0])
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        for tab in ("overview", "messages", "schedule", "history"):
            rendered = str((await ui.panel(draft, tab))[0].build()[0])
            assert "History" not in rendered
            assert "cwl_restore:" not in rendered
            assert "cwl_update_start:" not in rendered
    asyncio.run(scenario())

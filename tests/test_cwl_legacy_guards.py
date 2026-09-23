import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.tasks import cwl_reminder as runtime


@pytest.mark.parametrize("command", [
    runtime.Schedule, runtime.Status, runtime.Test, runtime.Cancel,
    runtime.AddFollowup, runtime.RemoveFollowup, runtime.List, runtime.TestAll, runtime.SendNow,
])
def test_adopted_campaign_redirects_every_legacy_command_before_mutation(monkeypatch, command):
    async def run():
        collection = SimpleNamespace(find_one=AsyncMock(return_value={"campaign_managed": True}), update_one=AsyncMock())
        pending = SimpleNamespace(delete_many=AsyncMock())
        mongo = SimpleNamespace(cwl_reminder=collection, cwl_pending_reminders=pending)
        monkeypatch.setattr(runtime, "mongo_client", mongo)
        send, schedule = AsyncMock(), AsyncMock()
        monkeypatch.setattr(runtime, "send_cwl_reminder", send)
        monkeypatch.setattr(runtime, "schedule_cwl_reminder", schedule)
        ctx = SimpleNamespace(
            interaction=SimpleNamespace(guild_id=runtime.cwl_campaign.LEGACY_WU_GUILD_ID,
                                        member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)),
            defer=AsyncMock(), respond=AsyncMock(),
        )
        kwargs = {} if command in {runtime.Schedule, runtime.Test} else {"mongo": mongo}
        await command.invoke(SimpleNamespace(), ctx, **kwargs)
        assert "/cwl dashboard" in ctx.respond.call_args.args[0]
        collection.update_one.assert_not_awaited()
        pending.delete_many.assert_not_awaited()
        send.assert_not_awaited()
        schedule.assert_not_awaited()
    asyncio.run(run())


def test_legacy_controls_fail_closed_outside_original_guild():
    async def run():
        mongo = SimpleNamespace(cwl_reminder=SimpleNamespace(find_one=AsyncMock()))
        ctx = SimpleNamespace(interaction=SimpleNamespace(
            guild_id=42, member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)), respond=AsyncMock())
        assert await runtime._legacy_campaign_guard(ctx, mongo)
        mongo.cwl_reminder.find_one.assert_not_awaited()
    asyncio.run(run())

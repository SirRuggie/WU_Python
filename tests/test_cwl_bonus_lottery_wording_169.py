"""Verify the authorized dashboard entry point copy and mention scope."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from extensions.commands import cwl_bonus_lottery


def test_authorized_bonus_entry_uses_approved_dashboard_instructions():
    ctx = SimpleNamespace(member=SimpleNamespace(role_ids=[1430950420926300200]), respond=AsyncMock())
    asyncio.run(cwl_bonus_lottery.LazyBonusLottery.invoke(SimpleNamespace(), ctx))
    ctx.respond.assert_awaited_once_with(
        'Open **Bonus medals** and select Lazy CWL. Check who can win. Draw the winners and approve them. Then post the announcement.\n'
        f'{cwl_bonus_lottery.DASHBOARD_ORIGIN}/cwl/bonuses\n'
        'Sign in with your staff account. If Home opens after you sign in, go to CWL → Bonus medals.',
        ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False,
    )


def test_bonus_entry_still_rejects_members_without_staff_role():
    ctx = SimpleNamespace(member=SimpleNamespace(role_ids=[]), respond=AsyncMock())
    asyncio.run(cwl_bonus_lottery.LazyBonusLottery.invoke(SimpleNamespace(), ctx))
    ctx.respond.assert_awaited_once_with('You do not have permission to use this command.', ephemeral=True)

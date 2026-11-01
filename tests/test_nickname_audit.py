import asyncio
import logging
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import hikari
import pytest
from extensions.warrior.nickname_audit import edit_nickname


@pytest.mark.parametrize("outcome", ["confirmed", "refused", "unconfirmed"])
def test_every_one_shot_nickname_attempt_has_attributable_outcome(caplog, outcome):
    async def run():
        error = (
            None
            if outcome == "confirmed"
            else (
                hikari.ForbiddenError(
                    url="https://discord.com/api",
                    headers={},
                    raw_body="",
                    message="Missing Permissions",
                )
                if outcome == "refused"
                else TimeoutError()
            )
        )
        rest = S(edit_member=AsyncMock(side_effect=error))
        caplog.set_level(logging.INFO, logger="extensions.warrior.nickname_audit")
        action = edit_nickname(
            rest,
            10,
            30,
            nickname="New | GMT",
            reason="Fixture",
            actor_id=20,
            old_nickname="Old\nname",
            source="warrior",
        )
        if error:
            with pytest.raises(type(error)):
                await action
        else:
            await action
        rest.edit_member.assert_awaited_once()
        text = caplog.text
        assert (
            "Nickname edit attempted source=warrior guild=10 actor=20 target=30" in text
        )
        assert f"Nickname edit {outcome}" in text
        assert "old='Old\\nname' new='New | GMT'" in text

    asyncio.run(run())

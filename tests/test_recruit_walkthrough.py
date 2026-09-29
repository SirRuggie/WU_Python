"""Retired dashboard controls cannot mutate a member, even with forged state."""

import asyncio
from pathlib import Path
from extensions import components
from extensions.commands.recruit import recruit, retired_dashboard


def test_legacy_dashboard_is_removed():
    assert "dashboard" not in recruit.subcommands
    assert "questions" in recruit.subcommands
    assert not list(Path("extensions/commands/recruit/dashboard").glob("*.py"))


def test_every_old_control_only_returns_retirement_notice():
    for name in retired_dashboard.RETIRED_ACTIONS:
        action = components.registered_functions[name]
        assert not action.preload_state
        assert not action.opens_modal
        result = asyncio.run(
            action.fn(
                object(),
                "forged-session:#CLAN",
                mongo=object(),
                bot=object(),
                user_id=1,
            )
        )
        text = repr(result[0].build()[0])
        assert "/warrior setup" in text
        assert "no longer makes changes" in text

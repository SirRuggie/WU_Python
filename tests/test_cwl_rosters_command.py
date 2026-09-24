"""Public command routing and retirement guards for CWL rosters."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import cwl_dashboard, fwa, lazycwl_dashboard
from extensions.commands.help_catalog import command_paths


def test_roster_editor_remains_importable_without_old_cwl_group():
    assert lazycwl_dashboard.CWLRosters._command_data.name == "rosters"
    assert not cwl_dashboard.cwl.subcommands
    assert not any(getattr(item, "_command", None) for item in lazycwl_dashboard.loader._loadables)
    assert not any(name.startswith("lazycwl-") for name in fwa.fwa.subcommands)
    assert "/manage" in command_paths()
    assert "/cwl rosters" not in command_paths()
    assert "/lazycwl" not in command_paths()


def test_roster_entry_still_rejects_non_admins():
    ctx = SimpleNamespace(member=SimpleNamespace(permissions=hikari.Permissions.NONE), respond=AsyncMock())
    asyncio.run(lazycwl_dashboard.open_dashboard(ctx, object()))
    assert ctx.respond.await_args.kwargs["ephemeral"] is True
    assert "administrators" in ctx.respond.await_args.args[0]


def test_expired_roster_panel_points_to_the_new_command():
    ctx = SimpleNamespace(member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR), respond=AsyncMock())
    assert asyncio.run(lazycwl_dashboard._allow(ctx, "nonexistent-session")) is False
    assert "/manage" in ctx.respond.await_args.args[0]

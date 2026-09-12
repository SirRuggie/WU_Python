import asyncio
import re
import subprocess
import sys
from pathlib import Path

import hikari

from extensions.commands import lazycwl_dashboard as dashboard
from extensions.commands.fwa import fwa, lazy_cwl
from tests.lazycwl_wording import BANNED_WORDS
from tests.test_lazycwl_dashboard import _FakeMongo, _texts

REPO_ROOT = Path(__file__).resolve().parent.parent

ALIAS_NAMES = {
    "lazycwl-snapshot",
    "lazycwl-ping",
    "lazycwl-status",
    "lazycwl-roster",
    "lazycwl-reset",
    "lazycwl-autopings-start",
    "lazycwl-autopings-stop",
    "lazycwl-autopings-status",
    "lazycwl-remove-player",
}


def test_importing_dashboard_first_does_not_break_lazy_cwl(monkeypatch=None):
    """extensions.commands.lazycwl_dashboard -> fwa.lazy_cwl_service ->
    extensions.commands.fwa/__init__ -> extensions.commands.fwa.lazy_cwl. A
    module-level `from extensions.commands.lazycwl_dashboard import
    build_home` in lazy_cwl.py completes that cycle (refuter-14 MUST-FIX 1)."""
    result = subprocess.run(
        [sys.executable, "-c", "import extensions.commands.lazycwl_dashboard"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_importing_lazy_cwl_first_still_works():
    result = subprocess.run(
        [sys.executable, "-c", "import extensions.commands.fwa.lazy_cwl"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_nine_alias_commands_registered_under_fwa_group():
    assert ALIAS_NAMES <= set(fwa.subcommands.keys())


def test_every_alias_defaults_to_administrator_only():
    for name in ALIAS_NAMES:
        command = fwa.subcommands[name]
        assert command._command_data.default_member_permissions == hikari.Permissions.ADMINISTRATOR, name


def test_notice_string_passes_banned_word_rule():
    lowered = lazy_cwl.MOVED_NOTICE.lower()
    for word in BANNED_WORDS:
        assert not re.search(rf"\b{re.escape(word)}\b", lowered), (word, lazy_cwl.MOVED_NOTICE)


class _FakeMember:
    def __init__(self, permissions):
        self.permissions = permissions


class _FakeInteraction:
    def __init__(self):
        self.edited = None

    async def edit_initial_response(self, components):
        self.edited = components


class _FakeCtx:
    def __init__(self, member):
        self.member = member
        self.interaction = _FakeInteraction()
        self.responded = []
        self.deferred = False

    async def respond(self, message, ephemeral=False):
        self.responded.append((message, ephemeral))

    async def defer(self, ephemeral=False):
        self.deferred = True


def test_redirect_denies_non_admins():
    ctx = _FakeCtx(_FakeMember(hikari.Permissions.NONE))

    asyncio.run(lazy_cwl._redirect(ctx, mongo=None))

    assert ctx.deferred is False
    assert ctx.responded == [("Only server admins can use this.", True)]
    assert ctx.interaction.edited is None


def test_redirect_renders_dashboard_home_with_moved_notice(monkeypatch):
    ctx = _FakeCtx(_FakeMember(hikari.Permissions.ADMINISTRATOR))
    calls = []

    async def fake_build_home(mongo, selected_tag, note=None):
        calls.append((mongo, selected_tag, note))
        return ["rendered-home"]

    monkeypatch.setattr(lazy_cwl, "build_home", fake_build_home)

    asyncio.run(lazy_cwl._redirect(ctx, mongo="fake-mongo"))

    assert ctx.deferred is True
    assert calls == [("fake-mongo", None, lazy_cwl.MOVED_NOTICE)]
    assert ctx.interaction.edited == ["rendered-home"]


def test_redirect_end_to_end_through_the_real_build_home(monkeypatch):
    """refuter-15 NOTED 1: `lazy_cwl.build_home is None` (the lazy-import
    branch, the ONLY branch production ever takes) is exercised by no other
    test - every other happy-path test here monkeypatches `build_home`
    itself. Drive the real `_redirect` -> the real, un-monkeypatched
    `dashboard.build_home` -> real `render_home`, and assert MOVED_NOTICE
    actually lands in the rendered components. Only `service.away_players`
    is monkeypatched (build_home's one real I/O side-effect beyond Mongo)."""
    async def fake_away_players(doc):
        return []

    monkeypatch.setattr(dashboard.service, "away_players", fake_away_players)

    mongo = _FakeMongo(
        clan_docs=[{"tag": "#ABC", "name": "Alpha", "type": "FWA"}],
        list_docs=[],
    )
    ctx = _FakeCtx(_FakeMember(hikari.Permissions.ADMINISTRATOR))

    asyncio.run(lazy_cwl._redirect(ctx, mongo))

    assert ctx.deferred is True
    rendered = ctx.interaction.edited
    assert rendered is not None
    assert lazy_cwl.MOVED_NOTICE in _texts(rendered)

"""Startup helpers shared by the bot entry point and its tests."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterable
from pathlib import Path

import coc


COMMANDS_ROOT = Path("extensions/commands")


def _binds_loader(module_path: Path) -> bool:
    """Return whether a module exposes a top-level name named ``loader``.

    Lightbulb treats every Python file passed to ``load_extensions`` as an
    extension candidate.  The command tree also contains renderers, parsers,
    and other helpers, so walking every ``.py`` file produces warning noise and
    imports modules that were never intended to be entry points.

    All extension entry points in this repository either create ``loader`` or
    import a shared package loader.  Inspecting the syntax avoids importing a
    helper merely to discover that it has no loader.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "loader" for target in targets):
                return True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name.rsplit(".", 1)[-1]) == "loader":
                    return True
    return False


def load_cogs(disallowed: set[str], disallowed_folders: set[str] | None = None) -> list[str]:
    """Discover command extension entry points, in deterministic order."""
    disallowed_folders = disallowed_folders or set()
    file_list: list[str] = []

    for full_path in sorted(COMMANDS_ROOT.rglob("*.py")):
        relative = full_path.relative_to(COMMANDS_ROOT)
        if full_path.name.startswith("__"):
            continue
        if any(part in disallowed_folders for part in relative.parts[:-1]):
            continue
        if full_path.stem in disallowed:
            continue
        if not _binds_loader(full_path):
            continue

        module_parts = (*COMMANDS_ROOT.parts, *relative.with_suffix("").parts)
        file_list.append(".".join(module_parts))

    return file_list


def unique_extensions(*groups: Iterable[str]) -> list[str]:
    """Merge extension groups without changing first-load order."""
    return list(dict.fromkeys(extension for group in groups for extension in group))


def create_clash_client(*, loop: asyncio.AbstractEventLoop | None = None) -> coc.Client:
    """Create coc.py on the active bot loop.

    coc.py 3.10 still falls back to ``asyncio.get_event_loop()`` in its
    constructor.  Python 3.12 warns when that happens before ``bot.run()`` has
    installed a loop, and a future Python release will make it an error.
    """
    active_loop = loop or asyncio.get_running_loop()
    return coc.Client(
        loop=active_loop,
        base_url="https://proxy.clashk.ing/v1",
        key_count=10,
        load_game_data=coc.LoadGameData(default=False),
        raw_attribute=True,
    )

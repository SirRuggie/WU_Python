"""Python user-facing copy; the frontend companion runs in Vitest with TypeScript."""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

from utils.user_copy import needs_permissions

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"\bthe bot\b|\bbot['’]s\b", re.I)
# (repository-relative file, exact literal): reason for code-only text.
ALLOWLIST: dict[tuple[str, str], str] = {}


def python_literals(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    skipped.add(id(value))
        if isinstance(node, ast.Call):
            function = node.func
            root = function
            while isinstance(root, ast.Attribute):
                root = root.value
            name = root.id if isinstance(root, ast.Name) else ""
            if name in {"logger", "logging", "log_failure", "print"}:
                for argument in [*node.args, *(item.value for item in node.keywords)]:
                    skipped.update(id(child) for child in ast.walk(argument))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skipped
    ]



def wording_violations(
    relative: str,
    literals: list[tuple[int, str]],
    allowlist: dict[tuple[str, str], str],
) -> tuple[list[str], set[tuple[str, str]]]:
    failures = []
    used = set()
    for line, text in literals:
        if not FORBIDDEN.search(text):
            continue
        key = (relative, text)
        if key in allowlist:
            assert allowlist[key].strip(), "Every code-only exception needs a reason."
            used.add(key)
        else:
            failures.append(f"{relative}:{line}: {text!r}")
    return failures, used



def test_python_user_facing_wording() -> None:
    failures = []
    used = set()
    for directory in ("cwl_web", "utils"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            found, exceptions = wording_violations(
                relative, python_literals(path.read_text(encoding="utf-8")), ALLOWLIST
            )
            failures.extend(found)
            used.update(exceptions)
    assert not failures, "\n".join(failures)
    expected = {key for key in ALLOWLIST if key[0].startswith(("cwl_web/", "utils/"))}
    assert used == expected, "Remove unused Python wording exceptions."



def test_python_guard_skips_only_docstrings_and_diagnostic_arguments() -> None:
    source = '''"""the bot module"""
class Example:
    """the bot class"""
    def run(self):
        """the bot function"""
        logger.error("the bot", extra={"detail": f"the bot {1}"})
        logging.warning("the bot")
        log_failure("the bot")
        print("the bot")
        return f"the bot {1}", "bot's role"
'''
    violations = [(line, text) for line, text in python_literals(source) if FORBIDDEN.search(text)]
    assert sorted(violations) == [(10, "bot's role"), (10, "the bot ")]



@pytest.mark.parametrize(
    ("names", "where", "expected"),
    [
        (("View Channel",), "", "WU Wizard needs View Channel."),
        (("View Channel", "Send Messages"), "here", "WU Wizard needs View Channel and Send Messages here."),
        (("View Channel", "Send Messages", "Attach Files"), "in this channel", "WU Wizard needs View Channel, Send Messages, and Attach Files in this channel."),
    ],
)
def test_permission_copy(names: tuple[str, ...], where: str, expected: str) -> None:
    assert needs_permissions(*names, where=where) == expected


def test_permission_copy_requires_a_permission() -> None:
    with pytest.raises(ValueError, match="at least one"):
        needs_permissions()



def test_python_allowlist_matches_exact_file_and_literal_only() -> None:
    path = "utils/internal.py"
    source = 'a = "the bot code"; b = "the bot code extra"'
    allowlist = {(path, "the bot code"): "A diagnostic protocol fixture."}
    failures, used = wording_violations(path, python_literals(source), allowlist)
    assert used == {(path, "the bot code")}
    assert len(failures) == 1 and "the bot code extra" in failures[0]
    failures, used = wording_violations("utils/other.py", python_literals(source), allowlist)
    assert len(failures) == 2 and not used
    with pytest.raises(AssertionError, match="needs a reason"):
        wording_violations(path, python_literals(source), {(path, "the bot code"): ""})


def test_allowlist_entries_have_reasons_and_supported_source_paths() -> None:
    for (path, text), reason in ALLOWLIST.items():
        assert path.startswith(("cwl_web/", "utils/"))
        assert FORBIDDEN.search(text) and reason.strip()

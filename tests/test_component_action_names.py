import ast
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _registered_action_sites():
    sites = defaultdict(list)
    for path in (ROOT / "extensions").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "register_action"
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.args[0].value, str)
                ):
                    continue
                relative = path.relative_to(ROOT).as_posix()
                sites[decorator.args[0].value].append(
                    f"{relative}:{node.lineno} ({node.name})"
                )
    return sites


def test_component_action_names_are_unique_across_extensions():
    sites = _registered_action_sites()
    duplicates = {
        name: declarations
        for name, declarations in sites.items()
        if len(declarations) > 1
    }
    assert duplicates == {}


def test_back_to_clan_edit_keeps_the_production_handler():
    sites = _registered_action_sites()
    declarations = sites["back_to_clan_edit"]
    assert len(declarations) == 1
    assert declarations[0].startswith(
        "extensions/commands/clan/dashboard/update_clan_info.py:"
    )
    assert declarations[0].endswith("(back_to_clan_edit)")

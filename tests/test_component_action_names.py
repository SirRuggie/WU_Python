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


def _registered_action_keywords():
    """name -> the constant keyword flags at its @register_action site."""
    flags = {}
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
                flags[decorator.args[0].value] = {
                    keyword.arg: keyword.value.value
                    for keyword in decorator.keywords
                    if keyword.arg is not None
                    and isinstance(keyword.value, ast.Constant)
                }
    return flags


def test_every_public_cards_action_is_no_return():
    """One missed no_return replaces a public channel post with somebody's
    private panel for the whole channel - the dispatcher's normal reply is
    an edit of the clicked message. Every cards_pub_* action must therefore
    answer through the ephemeral followup instead.
    """
    flags = _registered_action_keywords()
    public = {
        name: keywords
        for name, keywords in flags.items()
        if name.startswith("cards_pub_")
    }
    assert set(public) == {
        "cards_pub_accept", "cards_pub_decline", "cards_pub_cancel",
        "cards_pub_claim", "cards_pub_claim_as", "cards_pub_take",
        "cards_pub_gem_yes", "cards_pub_gem_no",
    }
    for name, keywords in public.items():
        assert keywords.get("no_return") is True, name


def test_dm_trade_actions_are_still_registered():
    """DMs already sent carry these ids forever, and they need the normal
    edit reply (no_return=False) - an alias cannot hold both flags, so the
    DM pair and the public pair stay separate registrations for good.
    """
    flags = _registered_action_keywords()
    for name in ("cards_dm_accept", "cards_dm_decline"):
        assert name in flags, name
        assert flags[name].get("no_return") is not True, name


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

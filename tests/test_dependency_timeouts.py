"""Safe startup-budget and generated runtime-lock contracts, without main startup."""
import ast
import asyncio
import copy

import pymongo
import pytest
from pymongo import _csot
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from utils.mongo import MongoClient


ROOT = Path(__file__).resolve().parents[1]


def _bot_mongo_options():
    # main.py owns a live gateway entry point. Execute only its actual client
    # constructor expression, replacing the constructor with a recording stub.
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "mongo_client" for target in node.targets)
    )
    expression = ast.Expression(assignment.value)
    ast.fix_missing_locations(expression)
    return eval(compile(expression, "main.py:MongoClient", "eval"), {
        "MongoClient": lambda **kwargs: kwargs,
        "_mongodb_uri": "mongodb://fixture.invalid/wubot_test",
    })


def test_bot_client_has_ten_second_total_budget_without_starting_main(monkeypatch):
    monkeypatch.delenv("MONGODB_ROUTES", raising=False)
    options = _bot_mongo_options()
    assert options == {
        "uri": "mongodb://fixture.invalid/wubot_test",
        "timeoutMS": 10000,
        "serverSelectionTimeoutMS": 3000,
        "maxPoolSize": 20,
        "appName": "wu-bot",
    }

    async def scenario():
        # Use the real driver option parser; connect=False and no operation
        # prevent topology/network startup. Never use an ambient URI.
        client = MongoClient(**options, connect=False)
        try:
            assert client.options.timeout == 10
            assert client.options.server_selection_timeout == 3
            assert client.options.pool_options.max_pool_size == 20
        finally:
            await client.close()

    asyncio.run(scenario())


def _locked_requirements():
    entries = {}
    current = None
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith(" "):
            if "--hash=" in line:
                assert current is not None
                value = line.strip().rstrip(" \\")
                assert value.startswith("--hash=sha256:")
                digest = value.removeprefix("--hash=sha256:")
                assert len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
                entries[current]["hashes"].append(digest)
            continue
        assert not line.startswith("--"), "runtime lock must not override package indexes"
        requirement = Requirement(line.rstrip(" \\").strip())
        specs = list(requirement.specifier)
        assert len(specs) == 1 and specs[0].operator == "=="
        assert not requirement.url
        name = canonicalize_name(requirement.name)
        assert name not in entries
        entries[name] = {"requirement": requirement, "version": specs[0].version, "hashes": []}
        current = name
    assert entries and all(row["hashes"] for row in entries.values())
    return entries


def test_hashed_lock_satisfies_every_direct_runtime_input_for_target_python():
    locked = _locked_requirements()
    environment = {
        **default_environment(),
        "python_version": "3.12", "python_full_version": "3.12.3",
        "implementation_name": "cpython", "platform_system": "Linux",
        "sys_platform": "linux", "platform_machine": "x86_64",
    }
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate(environment):
            continue
        name = canonicalize_name(requirement.name)
        assert name in locked
        assert locked[name]["version"] in requirement.specifier
    assert {"pytest", "pip-tools", "ruff"}.isdisjoint(locked)


def test_extras_bearing_transitives_are_included_in_lock_inventory():
    # A bare name==version regex misses extras and previously hid a transitive
    # update-checker version change during this batch's inventory self-audit.
    locked = _locked_requirements()
    assert "update-checker" in locked
    assert locked["update-checker"]["requirement"].extras == {"async"}
    assert locked["update-checker"]["version"] == "1.0.0"


def test_runtime_constraints_reject_unapproved_major_driver_scheduler_changes():
    inputs = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            requirement = Requirement(line)
            inputs[canonicalize_name(requirement.name)] = requirement
    for name, accepted, rejected in (
        ("pymongo", "4.17.0", "4.18.0"),
        ("apscheduler", "3.11.3", "4.0.0"),
        ("aiohttp", "3.14.3", "4.0.0"),
    ):
        assert accepted in inputs[name].specifier
        assert rejected not in inputs[name].specifier


# Approved single-unit adapters, including the now-merged AF/N/K/M/G owners.
ADAPTER_PATHS = (
    'extensions/commands/recruit/questions.py',
    'extensions/commands/ticket_runtime.py',
    'extensions/commands/tickets/console.py',
    'extensions/commands/tickets/flag_store.py',
    'extensions/commands/tickets/legacy_bulk.py',
    'extensions/commands/tickets/legacy_migration.py',
    'extensions/commands/tickets/migrate.py',
    'extensions/commands/tickets/store.py',
    'extensions/commands/tickets/thread_service.py',
    'extensions/commands/tickets_legacy/migrate.py',
    'extensions/tasks/band_monitor.py',
    'extensions/tasks/band_sync_ical.py',
    'extensions/tasks/recruit_role_cleanup.py',
    'extensions/warrior/walkthrough.py',
    'utils/component_state.py',
    'utils/cwl_post_update_store.py',
    'utils/fwa_war_plan_store.py',
    'utils/member_profile_runs.py',
    'utils/member_profiles.py',
    'utils/poll_store.py',
    'utils/recruit_goblin_challenges.py',
    'utils/strike_store.py',
    'utils/strike_tracking.py',
    'utils/todo_sessions.py',
    'extensions/commands/cards.py',
    'extensions/commands/tickets/testing_service.py',
    'extensions/commands/tickets_legacy/handlers.py',
    'extensions/tasks/gauntlet_help.py',
    'utils/clan_history.py',
    'utils/lazy_cwl_store.py',
    'utils/member_events.py',
    'utils/member_invites.py',
    'utils/mongo.py',
    'utils/player_activity_store.py',
    'utils/recruit_message_delivery.py',
    'utils/recruit_panel_refresh.py',
    'utils/war_reminder_store.py',
    'utils/world_clock_store.py',
)


def _maintenance_contexts():
    contexts = []
    for path in ADAPTER_PATHS:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.With) or len(node.items) != 1:
                continue
            call = node.items[0].context_expr
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "pymongo" and call.func.attr == "timeout"):
                contexts.append((path, node))
    return contexts


CONTEXTS = _maintenance_contexts()


def test_maintenance_scopes_contain_one_mongo_unit_and_no_workflow_or_task():
    assert len(CONTEXTS) == 111
    for path, context in CONTEXTS:
        assert len(context.items[0].context_expr.args) == 1
        assert context.items[0].context_expr.args[0].value == 30
        assert len(context.body) == 1
        nodes = list(ast.walk(context.body[0]))
        assert not any(isinstance(node, (ast.For, ast.AsyncFor, ast.While)) for node in nodes)
        awaits = [node for node in nodes if isinstance(node, ast.Await)]
        assert len(awaits) == 1
        operation = awaits[0].value.func
        if isinstance(operation, ast.Name):
            assert path == "extensions/tasks/band_sync_ical.py" and operation.id == "factory"
        else:
            assert isinstance(operation, ast.Attribute)
            assert operation.attr in {"create_index", "delete_many", "to_list"}
        assert not any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"create_task", "add_job", "sleep", "create_message", "delete_message"}
            for node in nodes
        )


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("path,context", CONTEXTS, ids=[f"{path}:{node.lineno}" for path, node in CONTEXTS])
def test_real_driver_budget_overrides_default_then_restores_without_task_leak(path, context, cancel):
    # Execute each actual source context with a probe at its one I/O boundary.
    # The real driver's operation decorator applies the client's default10s
    # only when no explicit context is active; an enclosing10s deadline would
    # wrongly constrain a nested30s context, so do not simulate it that way.
    observations = []

    class OperationProbe:
        _timeout = 10

        @_csot.apply
        async def operation(self, *, phase, cancelled=False):
            observations.append((phase, _csot.get_timeout(), _csot.remaining()))
            if cancelled:
                raise asyncio.CancelledError

    probe = OperationProbe()

    async def maintenance():
        await probe.operation(phase="maintenance", cancelled=cancel)

    block = copy.deepcopy(context)
    block.body = [ast.Expr(value=ast.Await(value=ast.Call(
        func=ast.Name(id="maintenance", ctx=ast.Load()), args=[], keywords=[],
    )))]
    function = ast.AsyncFunctionDef(
        name="exercise", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=[block], decorator_list=[], type_params=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {"pymongo": pymongo, "maintenance": maintenance}
    exec(compile(module, f"{path}:bounded-context", "exec"), namespace)

    async def scenario():
        assert _csot.get_timeout() is None
        await probe.operation(phase="before")
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await namespace["exercise"]()
        else:
            await namespace["exercise"]()
        assert _csot.get_timeout() is None
        # A task created AFTER the source context must receive the normal
        # default rather than an inherited maintenance deadline.
        await asyncio.create_task(probe.operation(phase="next-task"))
        assert _csot.get_timeout() is None

    asyncio.run(scenario())
    assert [value[1] for value in observations] == [10, 30, 10]
    assert observations[1][2] > 10


@pytest.mark.parametrize("failing_index", [None, 2])
def test_flag_index_list_keeps_order_results_and_failure_boundary(failing_index):
    from types import SimpleNamespace
    from extensions.commands.tickets import flag_store

    calls = []

    class Collection:
        async def create_index(self, keys, **kwargs):
            calls.append((kwargs["name"], _csot.get_timeout()))
            if len(calls) == failing_index:
                raise RuntimeError("fixture index failure")
            return kwargs["name"]

    async def scenario():
        mongo = SimpleNamespace(ticket_flags=Collection())
        if failing_index is None:
            assert await flag_store.ensure_indexes(mongo) == [
                "flag_kind_active_checked", "active_flag_discord_unique", "active_flag_player_tag_unique",
            ]
        else:
            with pytest.raises(RuntimeError, match="fixture index failure"):
                await flag_store.ensure_indexes(mongo)
        assert _csot.get_timeout() is None

    asyncio.run(scenario())
    expected = ["flag_kind_active_checked", "active_flag_discord_unique", "active_flag_player_tag_unique"]
    if failing_index is not None:
        expected = expected[:failing_index]
    assert calls == [(name, 30) for name in expected]


def test_canonical_index_list_and_recovery_indexes_keep_results_and_default_boundary(monkeypatch):
    from types import SimpleNamespace
    from extensions.commands.tickets import store

    calls = []

    class Collection:
        async def create_index(self, keys, **kwargs):
            calls.append((kwargs["name"], _csot.get_timeout()))
            return kwargs["name"]

    async def conflict_check(collection):
        assert _csot.get_timeout() is None
        return []

    monkeypatch.setattr(store, "index_conflicts", conflict_check)

    async def scenario():
        names = await store._install_indexes(SimpleNamespace(tickets=Collection()))
        assert names == [name for name, _ in calls]
        assert len(names) == 12 + len(store.ACCOUNT_RECOVERY_BOOLEAN_FIELDS)
        assert _csot.get_timeout() is None

    asyncio.run(scenario())
    assert calls[0][0] == "thread_v2_ticket_location_unique"
    assert calls[1][0] == "thread_v2_ticket_staff_location_unique"
    assert calls[-1][0] == "thread_v2_account_recovery_last_attempt"
    assert all(timeout == 30 for _, timeout in calls)


def test_now_merged_owner_DDL_sites_all_use_one_local_budget():
    merged_paths = {
        "extensions/commands/cards.py", "extensions/commands/tickets/testing_service.py",
        "extensions/commands/tickets_legacy/handlers.py", "extensions/tasks/gauntlet_help.py",
        "utils/clan_history.py", "utils/lazy_cwl_store.py", "utils/member_events.py",
        "utils/member_invites.py", "utils/mongo.py", "utils/player_activity_store.py",
        "utils/recruit_message_delivery.py", "utils/recruit_panel_refresh.py",
        "utils/war_reminder_store.py", "utils/world_clock_store.py",
    }
    seen = []
    for path in merged_paths:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_index":
                await_node = parents[node]
                assert isinstance(await_node, ast.Await)
                context = parents[parents[await_node]]
                assert isinstance(context, ast.With)
                assert ast.unparse(context.items[0].context_expr) == "pymongo.timeout(30)"
                seen.append((path, node))
    assert len(seen) == 33
    assert sum(path == "extensions/tasks/gauntlet_help.py" for path, _ in seen) == 4


@pytest.mark.parametrize("cancel", [False, True])
def test_maintenance_task_deadline_does_not_leak_to_concurrent_caller_or_next_task(cancel):
    observations = []

    class Probe:
        _timeout = 10

        @_csot.apply
        async def operation(self, phase, entered=None, release=None):
            observations.append((phase, _csot.get_timeout(), _csot.remaining()))
            if entered is not None:
                entered.set()
                await release.wait()

    probe = Probe()

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def maintenance():
            with pymongo.timeout(30):
                await probe.operation("maintenance", entered, release)
            assert _csot.get_timeout() is None

        task = asyncio.create_task(maintenance())
        await entered.wait()
        assert _csot.get_timeout() is None
        await probe.operation("concurrent-normal")
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            await task
        assert _csot.get_timeout() is None
        await asyncio.create_task(probe.operation("next-normal-task"))
        assert _csot.get_timeout() is None

    asyncio.run(scenario())
    assert [value[1] for value in observations] == [30, 10, 10]
    assert observations[0][2] > 10


def test_merged_caller_loops_and_tasks_remain_outside_maintenance_contexts():
    for path in ("utils/player_activity_polling.py", "extensions/tasks/cwl_reminder.py"):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.With)
            and any(isinstance(item.context_expr, ast.Call)
                    and ast.unparse(item.context_expr.func) == "pymongo.timeout"
                    for item in node.items)
            for node in ast.walk(tree)
        )

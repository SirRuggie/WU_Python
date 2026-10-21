"""Enforce the feature boundaries documented in AGENTS.md and the runbook."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imports(path):
    tree = ast.parse((ROOT/path).read_text())
    return [name for node in ast.walk(tree)
            for name in ([node.module or ''] if isinstance(node, ast.ImportFrom)
                         else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])]


def test_worker_and_shared_services_do_not_depend_on_dashboard():
    for path in ['extensions/tasks/war_reminders.py', 'utils/account_links.py',
                 'utils/war_reminders.py', 'utils/war_reminder_store.py']:
        assert not any(name.startswith('cwl_web') for name in imports(path)), path


def test_renderer_is_independent_of_database_and_http():
    assert not any(name.startswith(('pymongo', 'aiohttp', 'cwl_web')) for name in imports('utils/war_reminders.py'))


def test_reminder_adapters_use_storage_and_public_provider_interfaces():
    for path in ['extensions/tasks/war_reminders.py', 'cwl_web/war_reminders.py', 'cwl_web/war_reminder_samples.py']:
        tree = ast.parse((ROOT/path).read_text())
        forbidden = {'_coc', '_combined_links', 'get_collection', 'insert_one', 'update_one', 'find_one'}
        assert not [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in forbidden], path

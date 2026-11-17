"""Publishing sync context managers cannot quietly return to async functions."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).parents[1]


def test_no_sync_transactions_in_async_functions():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--',
                                     'cwl_web/*.py', 'utils/*.py', 'extensions/**/*.py'], cwd=ROOT, text=True).split('\0')
    violations = []
    for name in filter(None, names):
        tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            if not any(isinstance(item.context_expr, ast.Call)
                       and isinstance(item.context_expr.func, ast.Attribute)
                       and item.context_expr.func.attr in {'tx', 'role_tx'} for item in node.items):
                continue
            enclosing = parents.get(node)
            while enclosing is not None and not isinstance(enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing = parents.get(enclosing)
            if isinstance(enclosing, ast.AsyncFunctionDef):
                violations.append(f'{name}:{node.lineno}')
    assert violations == []  # No deferred allowlist; future exceptions require approval.


def tracked_product_sources():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--',
                                     'cwl_web/*.py', 'utils/*.py', 'extensions/**/*.py'],
                                    cwd=ROOT, text=True).split('\0')
    return {name[:-3].replace('/', '.'): (ROOT / name).read_text(encoding='utf-8')
            for name in names if name}


def test_known_publishers_resolve_by_source_provenance_and_are_offloaded():
    from dashboard_transaction_analysis import PublisherAudit
    audit = PublisherAudit(tracked_product_sources())
    assert audit.violations() == []
    # A constructed receiver used to evade the literal-receiver guard. Require
    # the actual handler to appear in the resolved inventory now.
    rows = [row for row in audit.inventory()
            if row['module'] == 'cwl_web.announcement_settings']
    assert len(rows) == 1
    assert rows[0]['publishers'] == [
        'utils.cwl_roster_image_store.RosterImageStore.configure_test_channel']
    assert rows[0]['offloaded'] is True


def test_known_member_store_and_prank_publishers_are_wrapped():
    cases = {
        'cwl_web/app.py': {'_store(request).set_member_season', 'member_withdraw'},
        'cwl_web/signup_activity.py': {'_store(request).review_signup_activity'},
        'cwl_web/discord_member.py': {'member.withdraw'},
        'cwl_web/owner_prank.py': {'apply'},
    }
    for name, publishers in cases.items():
        tree = ast.parse((ROOT / name).read_text())
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or ast.unparse(node.func) not in publishers:
                continue
            found.add(ast.unparse(node.func))
            enclosing = parents[node]
            while not isinstance(enclosing, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing = parents[enclosing]
            assert isinstance(enclosing, ast.Lambda), f'{name}:{node.lineno}'
            wrapper = parents[enclosing]
            assert isinstance(wrapper, ast.Call) and isinstance(wrapper.func, ast.Attribute) and wrapper.func.attr == 'run_writer'
        assert found == publishers

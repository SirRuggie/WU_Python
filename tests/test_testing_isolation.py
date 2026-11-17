"""Exercise isolation in a separate pytest process with fake credentials only."""
import asyncio
import ast
import re
import os
from pathlib import Path
import subprocess
import sys

import pytest

import conftest
from tests import mongo_test_support
from utils import gold_loot


ROOT = Path(__file__).resolve().parents[1]

# Deliberately independent of conftest: omissions in that inventory must fail.
EXPECTED_ISOLATED_NAMES = (
    "MONGODB_URI", "COC_API_TOKEN", "TICKET_TEST_MONGODB_URI",
    "DISCORD_TOKEN", "CWL_DISCORD_CLIENT_SECRET", "CWL_DISCORD_BRIDGE_SECRET",
    "CWL_PUSH_VAPID_PRIVATE_KEY", "CLASHPERK_PASSKEY", "CLASHKING_API_TOKEN",
    "CLASHKING_BOT_TOKEN", "BAND_ACCESS_TOKEN", "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY", "LAZYCWL_TEST_MONGODB_URI",
    "WU_ACTIVITY_TEST_MONGO_URI", "WU_STARTUP_TEST_MONGO_URI",
    "WU_CAMPAIGN_READ_MONGO_URI", "WU_CURSOR_TEST_MONGO_URI",
    "WU_DECLARATION_TEST_MONGO_URI", "WU_WEIGHTS_GUARD_MONGO_URI",
    "WU_ACTIVITY_RESTORE_MONGO_URI", "WU159_OWNED_SNAPSHOT",
    "WU159_OWNED_SNAPSHOT_RECEIPT", "WU_CATCHUP_144_MONGO",
    "CWL_RECOVERY_MONGOD", "BAND_ICAL_SYNC1", "BAND_ICAL_SYNC2",
    "BAND_ICAL_SYNC3", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN", "RESTIC_PASSWORD", "RESTIC_PASSWORD_FILE",
    "RESTIC_FROM_PASSWORD", "RESTIC_FROM_PASSWORD_FILE",
    "CWL_BACKUP_HEALTHCHECK_URL",
)
OMITTED_URI_NAMES = (
    "WU_DECLARATION_TEST_MONGO_URI",
    "WU_WEIGHTS_GUARD_MONGO_URI",
    "WU_ACTIVITY_RESTORE_MONGO_URI",
)


def test_full_module_cannot_capture_inherited_credentials(tmp_path):
    (tmp_path / "conftest.py").write_text(
        (ROOT / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "test_probe.py").write_text('''
import os
EXPECTED_NAMES = __EXPECTED_NAMES__
captured = {name for name in EXPECTED_NAMES if name in os.environ}
def test_at_collection():
    assert captured == set()
def test_at_execution():
    assert not any(name in os.environ for name in EXPECTED_NAMES)
'''.replace("__EXPECTED_NAMES__", repr(EXPECTED_ISOLATED_NAMES)), encoding="utf-8")
    env = os.environ.copy()
    env.pop("WU_REAL_MONGO_TESTS", None)
    env.update({name: "fake-isolation-only" for name in EXPECTED_ISOLATED_NAMES})
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(tmp_path)],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


@pytest.mark.parametrize("flag", [None, "0", "true", "yes", " 1"])
def test_real_mongo_gate_requires_exact_explicit_opt_in(monkeypatch, flag):
    monkeypatch.setenv("TICKET_TEST_MONGODB_URI", "mongodb://example.invalid/wubot_test")
    if flag is None:
        monkeypatch.delenv("WU_REAL_MONGO_TESTS", raising=False)
    else:
        monkeypatch.setenv("WU_REAL_MONGO_TESTS", flag)
    assert mongo_test_support.test_mongodb_uri() is None


def test_library_does_not_load_dotenv_or_create_clients_without_credentials(tmp_path, monkeypatch):
    # A fake on-disk .env must never be read by library calls.
    (tmp_path / ".env").write_text(
        "MONGODB_URI=mongodb://example.invalid/wubot_test\nCOC_API_TOKEN=fake\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gold_loot, "ROOT", tmp_path)
    # Exercise the library boundary itself, independently of the outer runner.
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    for name in conftest.LIVE_CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("credentials must be checked before creating clients")

    from utils import mongo
    monkeypatch.setattr(mongo, "MongoClient", forbidden)
    monkeypatch.setattr(gold_loot.aiohttp, "ClientSession", forbidden)
    db = gold_loot.connect(tmp_path / "fixture.sqlite3")
    try:
        with pytest.raises(ValueError, match="must be configured"):
            asyncio.run(gold_loot.expand_family(db))
        with pytest.raises(ValueError, match="not configured"):
            asyncio.run(gold_loot.collect(db, "start"))
        assert asyncio.run(gold_loot.load_town_halls(["#FIXTURE"])) == {}
        assert attempts == []
        assert not any(name in os.environ for name in conftest.LIVE_CREDENTIAL_NAMES)
        assert db.execute("SELECT count(*) FROM players").fetchone()[0] == 0
    finally:
        db.close()


def test_importing_cli_does_not_load_environment(monkeypatch):
    import importlib
    import dotenv
    from tools import gold_loot as cli

    def forbidden(*args, **kwargs):
        raise AssertionError("importing a CLI must not load .env")

    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    importlib.reload(cli)


@pytest.mark.parametrize("entrypoint", ["tools/gold_loot.py", "utils/gold_loot.py"])
def test_executing_gold_loot_entrypoint_loads_environment_once(monkeypatch, entrypoint):
    import dotenv
    import runpy

    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda path: calls.append(path))
    monkeypatch.setattr(sys, "argv", [entrypoint, "--help"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(ROOT / entrypoint), run_name="__main__")
    assert stopped.value.code == 0
    assert calls == [ROOT / ".env"]


def test_tracked_mongo_uri_names_have_an_isolation_policy():
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.py"], cwd=ROOT
    )
    found = set()
    for raw in tracked.split(b"\0"):
        if not raw:
            continue
        tree = ast.parse((ROOT / os.fsdecode(raw)).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[A-Z][A-Z0-9_]*MONGO(?:DB)?[A-Z0-9_]*URI", node.value) or node.value == "MONGODB_URI":
                    found.add(node.value)
    assert set(OMITTED_URI_NAMES) <= found
    assert found <= set(conftest.LIVE_CREDENTIAL_NAMES)


def test_exact_opt_in_preserves_independent_inventory(monkeypatch):
    monkeypatch.setenv("WU_REAL_MONGO_TESTS", "1")
    for name in EXPECTED_ISOLATED_NAMES:
        monkeypatch.setenv(name, "fake-opt-in-only")
    conftest._remove_live_credentials()
    assert all(os.environ.get(name) == "fake-opt-in-only" for name in EXPECTED_ISOLATED_NAMES)
    # URI/database and role checks remain separate gates, exercised in
    # test_mongo_test_support; this test must never construct a Mongo client.


def _collection_probe(tmp_path, *, simulate_omitted_names=False, first_diagnostic=None):
    source = (ROOT / "conftest.py").read_text(encoding="utf-8")
    if simulate_omitted_names:
        source += "\nLIVE_CREDENTIAL_NAMES = tuple(name for name in LIVE_CREDENTIAL_NAMES if name not in " + repr(OMITTED_URI_NAMES) + ")\n"
    (tmp_path / "conftest.py").write_text(source, encoding="utf-8")
    # Collect actual optional-test sources in the isolated fixture directory,
    # so the copied guard is the sole pytest configuration under evaluation.
    files = (
        "test_declaration_ping_store_mongo.py",
        "test_declaration_ping_http.py",
        "test_weights_release_migration_mongo.py",
        "test_player_activity_mongo.py",
    )
    for name in files:
        (tmp_path / name).write_text((ROOT / "tests" / name).read_text(encoding="utf-8"), encoding="utf-8")
    code = '''
import sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[1] + '/tests')
import pymongo
import pytest
attempts = 0
def forbidden(*args, **kwargs):
    global attempts
    attempts += 1
    raise AssertionError('Mongo construction forbidden in collection probe')
pymongo.MongoClient.__init__ = forbidden
pymongo.AsyncMongoClient.__init__ = forbidden
class Probe:
    def pytest_collection_modifyitems(self, items):
        modules = {item.module for item in items}
        assert len(modules) == 4
        if sys.argv[3]:
            # Force each legitimate first rejection without relying on set/hash order.
            modules = sorted(modules, key=lambda module: hasattr(module, 'RESTORE_URI'),
                             reverse=sys.argv[3] == 'restore')
        for module in modules:
            assert module.URI is None, 'ambient URI survived module collection'
            if hasattr(module, 'RESTORE_URI'):
                assert module.RESTORE_URI is None, 'ambient restore URI survived module collection'
        print('COLLECTED_URI_MODULES_CLEARED=4')
    def pytest_sessionfinish(self, session, exitstatus):
        print('MONGO_CONSTRUCTOR_ATTEMPTS=' + str(attempts))
        if attempts:
            session.exitstatus = 1
raise SystemExit(pytest.main(['-q', sys.argv[2]], plugins=[Probe()]))
'''
    env = os.environ.copy()
    env.pop("WU_REAL_MONGO_TESTS", None)
    for name in EXPECTED_ISOLATED_NAMES:
        env.pop(name, None)
    env.update({
        "WU_DECLARATION_TEST_MONGO_URI": "mongodb://fake-declaration.invalid/wubot_test",
        "WU_WEIGHTS_GUARD_MONGO_URI": "mongodb://fake-weights.invalid/wubot_test",
        "WU_ACTIVITY_RESTORE_MONGO_URI": "mongodb://fake-restore.invalid/wubot_test",
        "WU_ACTIVITY_TEST_MONGO_URI": "mongodb://fake-activity.invalid/wubot_test",
        "PYTHON_DOTENV_DISABLED": "1",
    })
    return subprocess.run(
        [sys.executable, "-c", code, str(ROOT), str(tmp_path), first_diagnostic or ""],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )


def test_independent_omitted_uris_are_cleared_before_real_module_collection(tmp_path):
    result = _collection_probe(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COLLECTED_URI_MODULES_CLEARED=4" in result.stdout
    assert "MONGO_CONSTRUCTOR_ATTEMPTS=0" in result.stdout
    assert "skipped" in result.stdout
    assert "passed" not in result.stdout


@pytest.mark.parametrize("first_diagnostic", [None, "uri", "restore"])
def test_collection_probe_rejects_the_previously_omitted_inventory(tmp_path, first_diagnostic):
    # Negative control: reproduces the exact missing-three-name policy. It
    # must fail at collection, before any optional test body or Mongo call.
    result = _collection_probe(
        tmp_path, simulate_omitted_names=True, first_diagnostic=first_diagnostic,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    diagnostics = {
        "uri": "ambient URI survived module collection",
        "restore": "ambient restore URI survived module collection",
    }
    assert any(diagnostic in output for diagnostic in diagnostics.values())
    if first_diagnostic is not None:
        assert diagnostics[first_diagnostic] in output
    assert "MONGO_CONSTRUCTOR_ATTEMPTS=0" in result.stdout

"""pytest configuration.

Ensures the repository root is importable so tests can `import utils...`
regardless of where pytest is invoked from.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


import pytest


# Explicit inventory of live credentials and optional real-service activators.
# Names only: never inspect or log values here. Keep the independent tests and
# docs/testing-isolation.md inventory in sync when adding an environment input.
LIVE_CREDENTIAL_NAMES = (
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


def _remove_live_credentials():
    if os.environ.get("WU_REAL_MONGO_TESTS") != "1":
        for name in LIVE_CREDENTIAL_NAMES:
            os.environ.pop(name, None)


def pytest_configure(config):
    # Session fixtures run after collection: strip credentials before test
    # module imports can capture them as module-level configuration too.
    _remove_live_credentials()


@pytest.fixture(scope="session", autouse=True)
def isolated_credentials():
    """Default every suite to fixture credentials, including direct pytest use."""
    _remove_live_credentials()

"""Run optional real-Mongo ticket regressions using only the test URI in .env."""

from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
TEST_URI_VARIABLE = "TICKET_TEST_MONGODB_URI"
TEST_FILES = (
    "tests/test_ticket_runtime.py::test_reconcile_terminal_delete_preserves_reused_live_slot_on_mongodb7",
    "tests/test_ticket_opening_chocolate.py::test_real_mongo_slow_page_takeover_fences_remaining_rest_writes",
)


def main() -> int:
    values = dotenv_values(ROOT / ".env")
    test_uri = values.get(TEST_URI_VARIABLE)
    if not test_uri:
        raise RuntimeError(f"{TEST_URI_VARIABLE} must be set in the local .env file")

    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TEST_FILES],
        cwd=ROOT,
        env={TEST_URI_VARIABLE: test_uri},
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())

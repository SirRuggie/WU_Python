"""Start the dashboard, restoring its Mongo-authoritative working copy first."""

import os
import logging
from contextlib import nullcontext
from pathlib import Path
import sqlite3

from aiohttp import web

from .app import create_app
from utils.cwl_dashboard_state import MongoDashboardState, database_lock


def main():
    logging.basicConfig(level=logging.INFO)
    fixture = os.getenv("CWL_WEB_DEV_FIXTURE") == "1"
    host = os.getenv("CWL_WEB_HOST", "127.0.0.1")
    if fixture and host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit("Fixture mode must bind to loopback")
    db_path = os.getenv("CWL_WEB_DB_PATH", "")
    if not db_path:
        raise SystemExit("CWL_WEB_DB_PATH is required")
    static_dir = os.getenv("CWL_WEB_STATIC_DIR", "")
    # Production cannot silently create an empty SQLite database on a new host.
    with database_lock(db_path) if not fixture else nullcontext():
        durability = None
        try:
            if not fixture:
                durability = MongoDashboardState.open(os.getenv('MONGODB_URI', ''))
                durability.restore(db_path)
                logging.info('Dashboard restored from Mongo revision %s', durability.revision)
            app = create_app(
                db_path=db_path,
                durability=durability,
                static_dir=Path(static_dir) if static_dir else None,
                secure_cookies=not fixture,
                dev_fixture=fixture,
            )
            if durability:
                # Include idempotent schema upgrades before any workers start.
                with sqlite3.connect(db_path) as db:
                    durability.publish(db)
            web.run_app(app, host=host, port=int(os.getenv("CWL_WEB_PORT", "8767")), access_log=None)
        finally:
            if durability:
                durability.close()


if __name__ == "__main__":
    main()

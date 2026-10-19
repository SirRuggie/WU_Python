"""Start the isolated web foundation with an optional same-origin frontend build."""

import os
import logging
from pathlib import Path

from aiohttp import web

from .app import create_app


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
    app = create_app(
        db_path=db_path,
        static_dir=Path(static_dir) if static_dir else None,
        secure_cookies=not fixture,
        dev_fixture=fixture,
    )
    web.run_app(app, host=host, port=int(os.getenv("CWL_WEB_PORT", "8767")), access_log=None)


if __name__ == "__main__":
    main()

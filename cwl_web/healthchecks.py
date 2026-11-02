"""Optional in-backend self-checks; no Mongo, Clash or Discord reads."""

import asyncio
from contextlib import suppress
import ipaddress
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

import aiohttp

from utils.external_heartbeat import ExternalHeartbeat

PERIOD_SECONDS = 5 * 60
DASHBOARD_ENV = "CWL_DASHBOARD_HEALTHCHECK_URL"
CAPTURE_ENV = "CWL_CAPTURE_HEALTHCHECK_URL"


def _sqlite_read(path):
    # Do not use Store.tx(): this is a read-only SQLite proof, not a commit or
    # a request for the durability owner's existing Mongo heartbeat.
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=2) as db:
        db.execute("SELECT id FROM seasons LIMIT 1").fetchone()
    return True


def _self_url():
    host = os.getenv("CWL_WEB_HOST", "127.0.0.1")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1", "localhost": "127.0.0.1"}.get(
        host, host
    )
    address = ipaddress.ip_address(host)
    if not address.is_loopback:
        raise ValueError("Dashboard self-check must stay on loopback")
    port = int(os.getenv("CWL_WEB_PORT", "8767"))
    if not 1 <= port <= 65535:
        raise ValueError("Dashboard self-check port is invalid")
    host = "[" + host + "]" if address.version == 6 else host
    return f"http://{host}:{port}/api/cwl/config"


async def self_check(app, *, url=None):
    try:
        target = _self_url() if url is None else str(url)
        parsed = urlsplit(target)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or not ipaddress.ip_address(parsed.hostname).is_loopback
            or not parsed.port
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/api/cwl/config"
        ):
            return False
        owner = app["store"].durability
        if owner is not None:
            owner.check()  # Existing in-memory fence only; never a new Mongo call.
        await asyncio.to_thread(_sqlite_read, app["store"].path)
        # No cookies, authentication or external request: config is a public
        # handler whose access middleware skips Mongo and Discord entirely.
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5), trust_env=False
        ) as client:
            async with client.get(target, allow_redirects=False) as response:
                if response.status != 200:
                    return False
                value = await response.json()
                return (
                    isinstance(value, dict) and type(value.get("dev_fixture")) is bool
                )
    except asyncio.CancelledError:
        raise
    except Exception:
        return False


async def _dashboard_worker(app, sender):
    ready_once = False
    while True:
        await asyncio.sleep(PERIOD_SECONDS)
        healthy = await self_check(app)
        if healthy:
            ready_once = True
        # Initial bind/recovery uses the outside grace, not immediate /fail.
        if ready_once:
            sender.submit(healthy)


async def lifecycle(app):
    sender = ExternalHeartbeat(os.getenv(DASHBOARD_ENV, ""), "dashboard")
    if not sender.enabled:
        yield
        return
    task = asyncio.create_task(
        _dashboard_worker(app, sender), name="dashboard-external-health"
    )
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await sender.close()


class CapturePass:
    """One ordinary pass across enabled draft seasons; no persistent state."""

    def __init__(self):
        self.progress = False
        self.crashed = False

    def record(self, useful):
        self.progress = self.progress or bool(useful)

    def healthy(self, *, no_seasons=False):
        return not self.crashed and (no_seasons or self.progress)


def record_capture(observer, *, force, clans, groups, wars, waiting):
    if observer is not None and not force:
        try:
            observer(bool(not clans or groups or wars or waiting))
        except Exception:
            pass

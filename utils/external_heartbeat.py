"""Private, payload-free Healthchecks pings; async callers never wait for delivery."""

import asyncio
from contextlib import suppress
import logging
import time
from urllib.parse import urlsplit
from uuid import UUID

import requests

LOG = logging.getLogger(__name__)


def _endpoint(url, healthy):
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        raise RuntimeError("External heartbeat URL is invalid") from None
    if (
        parsed.scheme != "https"
        or parsed.netloc != "hc-ping.com"
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("External heartbeat must be an HTTPS hc-ping.com UUID URL")
    try:
        check_id = str(UUID(parsed.path.strip("/")))
    except (TypeError, ValueError, AttributeError):
        raise RuntimeError("External heartbeat URL has an invalid check ID") from None
    return "https://hc-ping.com/" + check_id + ("" if healthy else "/fail")


class _PrivatePingFilter(logging.Filter):
    """Requests can log the path at DEBUG before our error handler runs."""

    def __init__(self, check_id):
        super().__init__()
        self.check_id = check_id

    def filter(self, record):
        message = record.getMessage()
        if self.check_id in message:
            record.msg = message.replace(self.check_id, "<private-check>")
            record.args = ()
        return True


def ping_external(url, healthy, get=requests.get):
    """Use the managed dead-man switch without transmitting logs or data."""
    if not url:
        return False
    endpoint = _endpoint(url, healthy)
    redactor = _PrivatePingFilter(endpoint.split("/")[3])
    http_loggers = tuple(
        logging.getLogger(name)
        for name in (
            "urllib3.connectionpool",
            "requests.packages.urllib3.connectionpool",
        )
    )
    for logger in http_loggers:
        logger.addFilter(redactor)
    try:
        response = get(endpoint, timeout=(5, 10), allow_redirects=False)
    except requests.RequestException:
        # Requests errors include the private Ping URL. Never propagate it.
        raise RuntimeError("External heartbeat delivery failed") from None
    finally:
        for logger in http_loggers:
            logger.removeFilter(redactor)
    if response.status_code != 200:
        raise RuntimeError(f"External heartbeat rejected (HTTP {response.status_code})")
    return True


class ExternalHeartbeat:
    """At most one off-loop delivery, bounded cadence, no automatic retries."""

    def __init__(self, url, check, *, send=None, clock=time.monotonic, min_interval=60):
        self._url = str(url or "").strip()
        self.check = check if check in {"bot", "dashboard", "capture"} else "service"
        self._send = send or ping_external
        self._clock = clock
        self._min_interval = min_interval
        self._last_attempt = float("-inf")
        self._task = None
        self._closed = False
        self.enabled = bool(self._url)
        if self.enabled:
            try:
                _endpoint(self._url, True)
            except RuntimeError:
                self.enabled = False
                self._warning("invalid configuration")

    def _warning(self, reason):
        try:
            LOG.warning("External heartbeat %s check=%s", reason, self.check)
        except Exception:
            pass

    def submit(self, healthy):
        """Queue one attempt only; service/capture callers do not await HTTP."""
        if not self.enabled or self._closed or self._task and not self._task.done():
            return False
        try:
            now = self._clock()
            if now - self._last_attempt < self._min_interval:
                return False
            loop = asyncio.get_running_loop()
            self._last_attempt = now
            self._task = loop.create_task(
                self._deliver(bool(healthy)), name="external-heartbeat:" + self.check
            )
            return True
        except Exception:
            self._warning("could not queue delivery")
            return False

    async def _deliver(self, healthy):
        try:
            await asyncio.to_thread(self._send, self._url, healthy)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Neither exception text nor traceback may expose the private URL.
            self._warning("delivery failed")

    async def close(self):
        self._closed = True
        task = self._task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

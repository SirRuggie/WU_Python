"""Private, payload-free Healthchecks pings; async callers never wait for delivery."""

import asyncio
from contextlib import suppress
from concurrent.futures import Future
import logging
import socket
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID

import requests
import aiohttp

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


TOTAL_DEADLINE_SECONDS = 15


_DNS_PENDING = {}
_DNS_LOCK = threading.Lock()


class _ServiceResolver(aiohttp.abc.AbstractResolver):
    """A stuck OS DNS call cannot hold service exit or multiply on retries."""

    async def resolve(self, host, port=0, family=socket.AF_INET):
        key = (host, port, family)
        with _DNS_LOCK:
            result = _DNS_PENDING.get(key)
            fresh = result is None or result.done()
            if fresh:
                result = Future()
                _DNS_PENDING[key] = result
        if fresh:

            def lookup():
                try:
                    addresses = socket.getaddrinfo(
                        host, port, family=family, type=socket.SOCK_STREAM
                    )
                    result.set_result(
                        [
                            dict(
                                hostname=host,
                                host=address[0],
                                port=address[1],
                                family=af,
                                proto=proto,
                                flags=socket.AI_NUMERICHOST,
                            )
                            for af, _, proto, _, address in addresses
                        ]
                    )
                except Exception as error:
                    result.set_exception(error)
                finally:
                    with _DNS_LOCK:
                        if _DNS_PENDING.get(key) is result:
                            _DNS_PENDING.pop(key, None)

            try:
                threading.Thread(
                    target=lookup, name="external-heartbeat-dns", daemon=True
                ).start()
            except Exception:
                with _DNS_LOCK:
                    if _DNS_PENDING.get(key) is result:
                        _DNS_PENDING.pop(key, None)
                raise
        # Shield the shared concurrent future from one attempt's cancellation.
        return await asyncio.shield(asyncio.wrap_future(result))

    async def close(self):
        pass  # No executor/resource to join; in-flight DNS remains single-flight.


async def ping_external_async(url, healthy):
    """Service transport: total deadline, no response body, no executor thread."""
    endpoint = _endpoint(url, healthy)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=TOTAL_DEADLINE_SECONDS, connect=5, sock_read=10
            ),
            trust_env=False,
            connector=aiohttp.TCPConnector(resolver=_ServiceResolver()),
        ) as client:
            async with client.get(endpoint, allow_redirects=False) as response:
                if response.status != 200:
                    raise RuntimeError("External heartbeat rejected")
    except asyncio.CancelledError:
        raise
    except Exception:
        raise RuntimeError("External heartbeat delivery failed") from None
    return True


class ExternalHeartbeat:
    """At most one off-loop delivery, bounded cadence, no automatic retries."""

    def __init__(self, url, check, *, send=None, clock=time.monotonic, min_interval=60):
        self._url = str(url or "").strip()
        self.check = check if check in {"bot", "dashboard", "capture"} else "service"
        self._send = send or ping_external_async
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
            async with asyncio.timeout(TOTAL_DEADLINE_SECONDS):
                await self._send(self._url, healthy)
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

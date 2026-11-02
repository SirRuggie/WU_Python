"""Shared URL restrictions, privacy, and nonblocking bounded delivery."""

import asyncio
import threading
from types import SimpleNamespace as S

import pytest
import requests

from utils import external_heartbeat as health

URL = "https://hc-ping.com/12345678-1234-1234-1234-123456789abc"


def test_shared_transport_sends_only_canonical_status_url_and_no_payload():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return S(status_code=200)

    assert health.ping_external(URL, True, get)
    assert health.ping_external(URL, False, get)
    assert calls == [
        (URL, {"timeout": (5, 10), "allow_redirects": False}),
        (URL + "/fail", {"timeout": (5, 10), "allow_redirects": False}),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://hc-ping.com/12345678-1234-1234-1234-123456789abc",
        "https://example.com/12345678-1234-1234-1234-123456789abc",
        URL + "?secret=yes",
        URL + "#secret",
        URL + "/fail",
        "https://user:secret@hc-ping.com/12345678-1234-1234-1234-123456789abc",
        "https://hc-ping.com:443/12345678-1234-1234-1234-123456789abc",
        "https://hc-ping.com/not-a-check",
        "https://[invalid/secret",
    ],
)
def test_invalid_destinations_fail_closed_without_exposing_url(url):
    def never(*a, **kw):
        raise AssertionError("Network must not run")

    with pytest.raises(RuntimeError) as error:
        health.ping_external(url, True, never)
    assert url not in str(error.value)
    assert "secret" not in str(error.value)


def test_delivery_error_hides_private_url_and_redirect_is_not_success():
    def fail(*a, **kw):
        raise requests.Timeout("private endpoint " + URL)

    with pytest.raises(RuntimeError) as error:
        health.ping_external(URL, True, fail)
    assert URL not in str(error.value) and error.value.__suppress_context__
    with pytest.raises(RuntimeError, match="302"):
        health.ping_external(URL, True, lambda *a, **kw: S(status_code=302))


def test_unset_is_silent_and_never_schedules_or_calls(caplog):
    async def run():
        sender = health.ExternalHeartbeat("", "bot", send=lambda *a: pytest.fail())
        assert not sender.enabled and not sender.submit(True)
        assert sender._task is None
        await sender.close()

    asyncio.run(run())
    assert not caplog.records
    assert health.ping_external("", True, lambda *a: pytest.fail()) is False


def test_async_outage_is_harmless_and_logs_no_url(caplog):
    async def run():
        calls = []

        def fail(url, healthy):
            calls.append(healthy)
            raise RuntimeError("private endpoint " + url)

        sender = health.ExternalHeartbeat(URL, "capture", send=fail)
        assert sender.submit(False)
        await sender._task
        assert calls == [False]
        assert not sender.submit(False)  # No immediate retry on failure.
        await sender.close()

    asyncio.run(run())
    assert "delivery failed" in caplog.text
    assert URL not in caplog.text and "12345678" not in caplog.text


def test_single_inflight_off_loop_attempt_and_normal_cadence():
    async def run():
        entered, release = threading.Event(), threading.Event()
        calls, clock = [], [0.0]

        def send(url, healthy):
            calls.append(healthy)
            entered.set()
            assert release.wait(2)

        sender = health.ExternalHeartbeat(
            URL, "dashboard", send=send, clock=lambda: clock[0]
        )
        try:
            assert sender.submit(True)
            assert await asyncio.to_thread(entered.wait, 1)
            assert not sender.submit(False)
            # The service loop still runs while the HTTP worker is blocked.
            alive = []
            await asyncio.sleep(0)
            alive.append(True)
            assert alive == [True]
            release.set()
            await sender._task
            clock[0] = 59
            assert not sender.submit(True)
            clock[0] = 60
            assert sender.submit(True)
            await sender._task
            assert calls == [True, True]
        finally:
            release.set()
            await sender.close()
        clock[0] = 1000
        assert not sender.submit(True)

    asyncio.run(run())


def test_invalid_configuration_does_not_fail_service_or_log_secret(caplog):
    sender = health.ExternalHeartbeat(URL + "?secret=yes", "bot")
    assert not sender.enabled and not sender.submit(True)
    assert "invalid configuration" in caplog.text
    assert URL not in caplog.text and "secret" not in caplog.text


def test_requests_debug_logging_redacts_private_ping_path_and_restores_filter(caplog):
    import logging

    private = "https://hc-ping.com/12345678-1234-5678-1234-567812345678"
    logger = logging.getLogger("urllib3.connectionpool")
    prior = list(logger.filters)

    def get(url, **kwargs):
        logger.debug("HTTPS hc-ping.com GET %s", url)
        raise requests.ConnectionError(private)

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        with pytest.raises(RuntimeError, match="delivery failed"):
            health.ping_external(private, True, get=get)
    assert "<private-check>" in caplog.text
    assert "12345678-1234-5678-1234-567812345678" not in caplog.text
    assert logger.filters == prior

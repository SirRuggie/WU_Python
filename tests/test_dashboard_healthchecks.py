"""The configured backend proves local HTTP and SQLite, not just a timer."""

import asyncio
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from cwl_web import healthchecks as health, app as routes, access_settings
from cwl_web.store import Store


async def served_app(tmp_path, *, status=200):
    app = web.Application(middlewares=[access_settings.access_context])
    app.update(
        store=Store(str(tmp_path / "health.sqlite")),
        dev_fixture=False,
        live_access=True,
    )
    if status == 200:
        app.router.add_get("/api/cwl/config", routes.config)
    else:

        async def fail(request):
            return web.json_response({"error": "fixture"}, status=status)

        app.router.add_get("/api/cwl/config", fail)
    server = TestServer(app)
    await server.start_server()
    return app, server


def test_actual_public_config_and_sqlite_pass_without_mongo_or_discord(
    tmp_path, monkeypatch
):
    def never(*a, **kw):
        raise AssertionError("No Mongo authorization read")

    monkeypatch.setattr(access_settings, "repository", never)

    async def run():
        app, server = await served_app(tmp_path)
        try:
            assert await health.self_check(app, url=server.make_url("/api/cwl/config"))
        finally:
            await server.close()

    asyncio.run(run())


@pytest.mark.parametrize("status", [302, 401, 500])
def test_failed_or_redirecting_http_is_not_healthy(tmp_path, status):
    async def run():
        app, server = await served_app(tmp_path, status=status)
        try:
            assert not await health.self_check(
                app, url=server.make_url("/api/cwl/config")
            )
        finally:
            await server.close()

    asyncio.run(run())


def test_sqlite_failure_or_existing_durability_fence_is_not_healthy(
    tmp_path, monkeypatch
):
    async def run():
        app, server = await served_app(tmp_path)
        try:
            url = server.make_url("/api/cwl/config")
            app["store"].durability = S(
                check=lambda: (_ for _ in ()).throw(RuntimeError("fenced"))
            )
            assert not await health.self_check(app, url=url)
            app["store"].durability = None
            Path(app["store"].path).write_text("not sqlite")
            assert not await health.self_check(app, url=url)
        finally:
            await server.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/cwl/config",
        "http://example.com/api/cwl/config",
        "http://127.0.0.1:1234/private",
        "http://127.0.0.1:1234/api/cwl/config?secret=yes",
    ],
)
def test_self_check_cannot_reach_external_or_other_paths(url):
    async def run():
        assert not await health.self_check({}, url=url)

    asyncio.run(run())


def test_self_address_uses_existing_loopback_bind_configuration(monkeypatch):
    monkeypatch.setenv("CWL_WEB_HOST", "0.0.0.0")
    monkeypatch.setenv("CWL_WEB_PORT", "39177")
    assert health._self_url() == "http://127.0.0.1:39177/api/cwl/config"
    monkeypatch.setenv("CWL_WEB_HOST", "::")
    assert health._self_url() == "http://[::1]:39177/api/cwl/config"
    monkeypatch.setenv("CWL_WEB_HOST", "example.com")
    with pytest.raises(ValueError):
        health._self_url()


def test_unset_starts_no_dashboard_task_or_periodic_io(monkeypatch, caplog):
    async def run():
        monkeypatch.delenv(health.DASHBOARD_ENV, raising=False)
        with patch.object(
            health, "_dashboard_worker", side_effect=AssertionError("No task")
        ):
            context = health.lifecycle({})
            await anext(context)
            await context.aclose()

    asyncio.run(run())
    assert not caplog.records


def test_dashboard_worker_uses_real_self_check_result_not_timer(monkeypatch):
    async def run():
        calls, count = [], 0

        async def sleep(seconds):
            nonlocal count
            assert seconds == health.PERIOD_SECONDS
            count += 1
            if count == 4:
                raise asyncio.CancelledError()

        async def check(app):
            return count == 2

        sender = S(submit=calls.append)
        with patch.object(health, "asyncio", S(sleep=sleep)), patch.object(
            health, "self_check", check
        ):
            with pytest.raises(asyncio.CancelledError):
                await health._dashboard_worker({}, sender)
        assert calls == [True]

    asyncio.run(run())


def test_real_app_wires_optional_dashboard_lifecycle(tmp_path):
    app = routes.create_app(db_path=str(tmp_path / "app.sqlite"), dev_fixture=True)
    assert health.lifecycle in app.cleanup_ctx


def test_real_listener_shutdown_after_success_never_sends_failure(
    tmp_path, monkeypatch
):
    async def run():
        app, server = await served_app(tmp_path)
        url = str(server.make_url("/api/cwl/config"))
        monkeypatch.setattr(health, "_self_url", lambda: url)
        monkeypatch.setattr(health, "PERIOD_SECONDS", 0.01)
        calls = []
        task = asyncio.create_task(
            health._dashboard_worker(app, S(submit=calls.append))
        )
        try:
            async with asyncio.timeout(2):
                while len(calls) < 4:
                    await asyncio.sleep(0.005)
            await server.close()  # The listener stops before worker cleanup.
            await asyncio.sleep(0.08)
            assert len(calls) >= 4 and all(value is True for value in calls)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await server.close()

    asyncio.run(run())


def test_self_check_warning_is_rate_limited_numeric_free_and_private(
    monkeypatch, caplog
):
    async def run():
        steps, calls = [0], []

        async def sleep(seconds):
            steps[0] += 1
            if steps[0] == 4:
                raise asyncio.CancelledError()

        async def failed(app):
            return False

        monkeypatch.setattr(health, "time", S(monotonic=lambda: steps[0]))
        monkeypatch.setattr(health, "asyncio", S(sleep=sleep))
        monkeypatch.setattr(health, "self_check", failed)
        with pytest.raises(asyncio.CancelledError):
            await health._dashboard_worker({}, S(submit=calls.append))
        assert calls == []

    asyncio.run(run())
    lines = [r.getMessage() for r in caplog.records]
    assert lines == ["Dashboard self-check unavailable"]
    assert not any(char.isdigit() for char in lines[0]) and "http" not in lines[0]


def test_real_sqlite_writer_lock_past_timeout_never_sends_failure(
    tmp_path, monkeypatch
):
    import sqlite3

    async def run():
        app, server = await served_app(tmp_path)
        monkeypatch.setattr(
            health, "_self_url", lambda: str(server.make_url("/api/cwl/config"))
        )
        lock = sqlite3.connect(app["store"].path, isolation_level=None)
        lock.execute("PRAGMA journal_mode=DELETE")
        calls = []
        steps = 0

        async def sleep(seconds):
            nonlocal steps
            steps += 1
            if steps == 2:
                lock.execute("BEGIN EXCLUSIVE")
            if steps == 3:
                raise asyncio.CancelledError()

        monkeypatch.setattr(
            health,
            "asyncio",
            S(
                sleep=sleep,
                to_thread=asyncio.to_thread,
                CancelledError=asyncio.CancelledError,
            ),
        )
        try:
            with pytest.raises(asyncio.CancelledError):
                await health._dashboard_worker(app, S(submit=calls.append))
            assert calls == [True]
        finally:
            lock.rollback()
            lock.close()
            await server.close()

    asyncio.run(run())

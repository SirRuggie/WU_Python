"""Storage availability is distinct from an ordinary provider failure."""

import asyncio
import json
from aiohttp.test_utils import make_mocked_request
from cwl_web.app import errors
from cwl_web.providers import ProviderUnavailable
from utils.cwl_dashboard_state import DashboardDurabilityError


def test_only_storage_errors_mark_staff_status_without_changing_error_body():
    async def run():
        for error, marked in [
            (DashboardDurabilityError("Storage is recovering"), True),
            (ProviderUnavailable("Game data unavailable"), False),
        ]:

            async def handler(request):
                raise error

            response = await errors(
                make_mocked_request("GET", "/api/cwl/auth/me"), handler
            )
            assert response.status == 503
            assert json.loads(response.text) == {"error": str(error)}
            assert (
                response.headers.get("X-Dashboard-Storage-Degraded") == "1"
            ) is marked

    asyncio.run(run())


def test_authenticated_healthy_header_rechecks_owner_after_visitor_await(monkeypatch):
    from types import SimpleNamespace
    from cwl_web import app, visitors
    from utils.cwl_dashboard_state import DashboardDurabilityAttention

    session = {
        "user_id": "1",
        "username": "fixture",
        "display_name": "fixture",
        "avatar_url": None,
        "csrf": "fixture",
    }
    fenced = False

    def check():
        if fenced:
            raise DashboardDurabilityAttention("needs attention")

    request = SimpleNamespace(
        app={"store": SimpleNamespace(durability=SimpleNamespace(check=check))},
        get=lambda key: None,
    )
    monkeypatch.setattr(app, "_require", lambda request: session)
    monkeypatch.setattr(app, "_owner", lambda session: True)
    monkeypatch.setattr(app, "_editor", lambda request, session: True)

    async def run():
        async def healthy_record(*args):
            pass

        monkeypatch.setattr(visitors, "record", healthy_record)
        response = await app.me(request)
        assert response.headers["X-Dashboard-Storage-State"] == "healthy"

        async def fence_during_record(*args):
            nonlocal fenced
            fenced = True

        monkeypatch.setattr(visitors, "record", fence_during_record)
        import pytest

        with pytest.raises(DashboardDurabilityAttention):
            await app.me(request)

    asyncio.run(run())

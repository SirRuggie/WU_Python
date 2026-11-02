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

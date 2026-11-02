"""Discord link destinations survive an entirely mocked OAuth round trip."""

import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import test_cwl_web_foundation as foundation
from utils.dashboard_urls import SIGNUP_URL, ASSIGNMENTS_URL, TASKS_URL, WARS_URL


class DashboardMessageLoginTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = foundation.WebFoundationTests.asyncSetUp
    asyncTearDown = foundation.WebFoundationTests.asyncTearDown
    auth = foundation.WebFoundationTests.auth
    call = foundation.WebFoundationTests.call

    async def test_member_links_return_after_signin_even_without_linked_accounts(self):
        self.app["oauth"] = {
            "client_id": "fixture",
            "client_secret": "fixture",
            "redirect_uri": "https://example.test/callback",
        }

        class Response:
            status = 200

            def __init__(self, data):
                self.data = data

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def json(self):
                return self.data

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return Response({"access_token": "fixture"})

            def get(self, url, **kwargs):
                return Response(
                    {"id": "555", "username": "No linked accounts"}
                    if url.endswith("/users/@me")
                    else [{"id": "644963518025826315", "owner": False}]
                )

        for url, view in [
            (SIGNUP_URL, "signup"),
            (ASSIGNMENTS_URL, "assignments"),
            (TASKS_URL, "todo"),
            (WARS_URL, "wars"),
        ]:
            expected = urlparse(url).path
            started = await self.call(
                "GET", "/auth/discord?view=" + view, allow_redirects=False
            )
            self.assertEqual(started.status, 302)
            self.assertEqual(started.cookies["wu_login_page"].value, expected)
            state = parse_qs(urlparse(started.headers["Location"]).query)["state"][0]
            cookies = (
                "cwl_oauth_state="
                + started.cookies["cwl_oauth_state"].value
                + "; wu_login_page="
                + expected
            )
            with patch("cwl_web.app.aiohttp.ClientSession", return_value=Session()):
                response = await self.call(
                    "GET",
                    "/auth/callback?state=" + state + "&code=fixture",
                    {"Cookie": cookies},
                    allow_redirects=False,
                )
            self.assertEqual(response.status, 302, await response.text())
            self.assertEqual(response.headers["Location"], expected)
            self.assertIn("cwl_session", response.cookies)
        self.assertEqual(self.providers.links.get("555", {}), {})

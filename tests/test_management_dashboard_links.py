"""Management dashboard routes and OAuth return destinations stay on known pages."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from cwl_web.app import MANAGEMENT_PAGE_PATHS, create_app, login_destination, saved_login_destination


class ManagementDashboardLinksTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_page_refresh_and_trailing_slash_serves_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("<html>Management dashboard</html>")
            app = create_app(
                db_path=str(root / "test.sqlite"),
                static_dir=root,
                dev_fixture=True,
                secure_cookies=False,
            )
            async with TestClient(TestServer(app)) as client:
                for path in MANAGEMENT_PAGE_PATHS.values():
                    for suffix in ("", "/"):
                        with self.subTest(path=path + suffix):
                            response = await client.get(path + suffix)
                            self.assertEqual(response.status, 200)
                            self.assertIn("Management dashboard", await response.text())
                self.assertEqual((await client.get("/settings/not-a-page")).status, 404)
                self.assertEqual((await client.get("/api/cwl/seasons/1/signups")).status, 401)

    async def test_auth_start_saves_only_allowlisted_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                db_path=str(root / "test.sqlite"),
                dev_fixture=True,
                secure_cookies=False,
                oauth={"client_id": "id", "client_secret": "secret", "redirect_uri": "https://app.example/api/cwl/auth/callback"},
            )
            async with TestClient(TestServer(app)) as client:
                response = await client.get("/api/cwl/auth/discord?view=access&next=https://evil.test", allow_redirects=False)
                self.assertEqual(response.status, 302)
                self.assertTrue(response.headers["Location"].startswith("https://discord.com/oauth2/authorize?"))
                self.assertEqual(response.cookies["wu_login_page"].value, "/settings/access")
                response = await client.get("/api/cwl/auth/discord?view=//evil.test", allow_redirects=False)
                self.assertEqual(response.status, 302)
                self.assertEqual(response.cookies["wu_login_page"].value, "")

    def test_legacy_manage_signups_login_resolves_to_roster(self):
        self.assertEqual(login_destination({"view": "manage-signups", "season": "12"}), "/cwl/roster?season=12")
        self.assertEqual(login_destination({"view": "manage-signups", "season": "bad"}), "/cwl/roster")
        self.assertEqual(saved_login_destination(SimpleNamespace(
            cookies={"wu_login_page": "/cwl/signups?season=12&next=https://evil.test"}
        )), "/cwl/roster?season=12")
        self.assertEqual(saved_login_destination(SimpleNamespace(
            cookies={"wu_login_page": "/?view=manage-signups&season=12"}
        )), "/cwl/roster?season=12")

    def test_management_destinations_are_canonical_and_strict(self):
        for view, path in MANAGEMENT_PAGE_PATHS.items():
            with self.subTest(view=view):
                self.assertEqual(login_destination({"view": view, "season": "12", "next": "https://evil.test"}), path)
                request = SimpleNamespace(cookies={"wu_login_page": path + "?view=//evil.test&next=https://evil.test"})
                self.assertEqual(saved_login_destination(request), path)
        for value in (
            "https://evil.test",
            "//evil.test/settings/access",
            "/settings/access/../../evil",
            "/settings/access%0d%0aLocation:evil",
            "/settings/not-a-page",
            "/?view=//evil.test",
            "/?view=access&next=https://evil.test" + "x" * 150,
        ):
            with self.subTest(value=value):
                self.assertEqual(saved_login_destination(SimpleNamespace(cookies={"wu_login_page": value})), "")

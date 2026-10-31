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
                for path in ("/clans/strikes", "/clans/replacements", "/clans/reminders", "/clans/history", "/clans/%23P0LYQ", "/clans/%23P0LYQ/roles", "/clans/%23P0LYQ/war-reminders/"):
                    response = await client.get(path)
                    self.assertEqual(response.status, 200)
                    self.assertIn("Management dashboard", await response.text())
                self.assertEqual((await client.get("/clans/not-a-tag")).status, 404)
                self.assertEqual((await client.get("/clans/%23P0LYQ/not-a-section")).status, 404)
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

    async def test_failed_oauth_preserves_staff_season_and_step(self):
        with tempfile.TemporaryDirectory() as directory:
            app=create_app(db_path=str(Path(directory)/'test.sqlite'),dev_fixture=True,secure_cookies=False)
            async with TestClient(TestServer(app)) as client:
                for destination,expected in [
                    ('/cwl/publish?season=12&step=announce','/cwl/publish?season=12&step=announce&signin_error=discord'),
                    ('/cwl/roster?season=12','/cwl/roster?season=12&signin_error=discord'),
                    ('/settings/access','/settings/access?signin_error=discord'),
                    ('https://evil.test','/?signin_error=discord'),
                ]:
                    response=await client.get('/api/cwl/auth/callback?error=access_denied',headers={'Accept':'text/html','Cookie':'wu_login_page='+destination},allow_redirects=False)
                    self.assertEqual(response.headers['Location'],expected)
                    self.assertEqual(response.cookies['wu_login_page'].value,'')
                    self.assertEqual(response.cookies['cwl_oauth_state'].value,'')


def test_activity_signin_preserves_bounded_filters_and_legacy_alias():
    from urllib.parse import urlsplit, parse_qs
    destination=login_destination({'view':'replacements','clans':'#PYY,https://evil.test',
                                   'marked':'1','sort':'quiet','q':'<Name>','tag':'#PQQ','next':'https://evil.test'})
    assert urlsplit(destination).path=='/replacements'
    params=parse_qs(urlsplit(destination).query)
    assert params=={'clans':['#PYY'],'marked':['1'],'sort':['quiet'],'q':['<Name>'],'tag':['#PQQ']}
    assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page':'/clans/replacements?clan=%23PYY&marked=1'}))=='/replacements?clan=%23PYY&marked=1'
    assert login_destination({'view':'strikes','q':'x'*1000}).count('x')==80

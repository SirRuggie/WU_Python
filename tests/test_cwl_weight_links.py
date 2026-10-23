import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from cwl_web.app import create_app, login_destination, saved_login_destination
from types import SimpleNamespace


class WeightLinksTests(unittest.IsolatedAsyncioTestCase):
    async def test_weight_paths_serve_dashboard_and_api_stays_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'index.html').write_text('<html>Dashboard fixture</html>')
            app=create_app(db_path=str(root/'test.sqlite'),static_dir=root,dev_fixture=True,secure_cookies=False)
            async with TestClient(TestServer(app)) as client:
                for path in ['/clan-weights','/weights','/weight','/weight-trial','/?view=weight-trial','/signup','/tasks']:
                    response=await client.get(path)
                    self.assertEqual(response.status,200)
                    self.assertIn('Dashboard fixture',await response.text())
                self.assertEqual((await client.get('/api/cwl/weight-trial/clans')).status,401)

    def test_login_destination_is_allowlisted(self):
        self.assertEqual(login_destination({'view':'weight-trial'}),'/clan-weights')
        self.assertEqual(saved_login_destination(SimpleNamespace(cookies={'wu_login_page':'/clan-weights'})),'/clan-weights')
        self.assertEqual(login_destination({'view':'//evil.test'}),'')
        self.assertEqual(saved_login_destination(SimpleNamespace(cookies={'wu_login_page':'https://evil.test'})),'')

    async def test_all_member_routes_and_trailing_slashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'index.html').write_text('<html>Member dashboard</html>')
            app=create_app(db_path=str(root/'test.sqlite'),static_dir=root,dev_fixture=True,secure_cookies=False)
            async with TestClient(TestServer(app)) as client:
                for path in ['signup','my-signups','assignments','tasks','wars','events','search']:
                    for suffix in ['', '/']:
                        response=await client.get('/'+path+suffix)
                        self.assertEqual(response.status,200)
                        self.assertIn('Member dashboard',await response.text())
                self.assertEqual((await client.get('/api/cwl/seasons/1/signups')).status,401)
        self.assertEqual(login_destination({'view':'my-signups','season':'999'}),'/my-signups')
        self.assertEqual(saved_login_destination(SimpleNamespace(cookies={'wu_login_page':'/my-signups'})),'/my-signups')

    async def test_cwl_routes_and_restricted_api(self):
        from cwl_web.app import CWL_PAGE_PATHS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text('<html>CWL dashboard</html>')
            app = create_app(db_path=str(root/'test.sqlite'), static_dir=root, dev_fixture=True, secure_cookies=False)
            async with TestClient(TestServer(app)) as client:
                for view, path in CWL_PAGE_PATHS.items():
                    for suffix in ['', '/']:
                        response = await client.get(path + suffix + '?season=12')
                        self.assertEqual(response.status, 200)
                        self.assertIn('CWL dashboard', await response.text())
                    expected = '/cwl/roster' if view == 'manage-signups' else path
                    self.assertEqual(login_destination({'view':view, 'season':'12'}), expected+'?season=12')
                    self.assertEqual(saved_login_destination(SimpleNamespace(cookies={'wu_login_page':path+'?season=12&view=access&redirect=https://evil.test'})), expected+'?season=12')
                self.assertEqual((await client.get('/api/cwl/seasons/1/signups?all=1')).status, 401)
                self.assertEqual((await client.get('/cwl/not-a-page')).status, 404)
        self.assertEqual(login_destination({'view':'publication','season':'bad','step':'announce'}), '/cwl/publish?step=announce')
        for value in ['//evil.test/cwl/roster','/cwl/roster/../../access','/cwl/roster%0d%0aLocation:evil','/cwl/roster?'+('x'*151)]:
            self.assertEqual(saved_login_destination(SimpleNamespace(cookies={'wu_login_page':value})), '')

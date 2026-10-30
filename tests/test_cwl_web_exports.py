"""CSV export authorization, spreadsheet safety and historical accuracy."""
import csv
import io
import unittest
import test_cwl_web_bonuses as fixtures
from cwl_web.exports import csv_cell


class ExportTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.BonusTests.asyncSetUp
    asyncTearDown = fixtures.BonusTests.asyncTearDown
    auth = fixtures.BonusTests.auth
    call = fixtures.BonusTests.call
    revision = fixtures.BonusTests.revision
    signup = fixtures.BonusTests.signup
    setup_published = fixtures.BonusTests.setup_published
    settings = fixtures.BonusTests.settings
    select = fixtures.BonusTests.select
    preview = fixtures.BonusTests.preview
    base = fixtures.BonusTests.base

    async def download(self, query=''):
        response = await self.call('GET', f'/seasons/{self.sid}/export.csv' + query, self.owner)
        self.assertEqual(response.status, 200, await response.text())
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        return list(csv.DictReader(io.StringIO((await response.read()).decode('utf-8-sig'))))

    async def test_access_empty_and_invalid_exports(self):
        url = f'/seasons/{self.sid}/export.csv'
        self.assertEqual((await self.call('GET', url)).status, 401)
        self.assertEqual((await self.call('GET', url, self.member)).status, 403)
        self.assertEqual((await self.call('GET', url + '?kind=nope', self.owner)).status, 400)
        self.assertEqual((await self.call('GET', url + '?basis=published', self.owner)).status, 409)
        self.assertEqual(await self.download(), [])
        self.assertEqual((await self.call('GET', '/seasons/9999/export.csv', self.owner)).status, 404)

    async def test_current_published_and_archived_exports_preserve_values(self):
        await self.setup_published()
        with self.app['store'].tx() as db:
            db.execute("UPDATE signups SET player_name=?,signup_clan_name=? WHERE season_id=?", ('=SUM(1,2)', 'Clan, "é"\nsecond line', self.sid))
            db.execute('UPDATE roster_entries SET manual_weight=174000,source_weight=176000,assigned_clan_tag=NULL WHERE season_id=?', (self.sid,))
        rows = await self.download()
        self.assertEqual(rows[0]['player_name'], "'=SUM(1,2)")
        self.assertEqual(rows[0]['signup_clan_name'], 'Clan, "é"\nsecond line')
        self.assertEqual(rows[0]['effective_weight'], '174000')
        self.assertEqual(rows[0]['legacy_manual_weight'], '174000')
        self.assertNotIn('manual_weight', rows[0])
        self.assertEqual(rows[0]['source_weight'], '176000')
        self.assertEqual(rows[0]['participation_attacks'], '')
        self.assertEqual(rows[0]['assigned_clan_tag'], '')
        published = await self.download('?basis=published')
        self.assertEqual(published[0]['assigned_clan_tag'], '#C2Y')
        self.assertEqual(published[0]['player_name'], 'Main')
        self.assertIn('manual_weight', published[0])
        self.assertNotIn('legacy_manual_weight', published[0])
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        revision = await self.revision()
        archived = await self.download()
        self.assertEqual(archived[0]['season_status'], 'archived')
        self.assertEqual(await self.revision(), revision)

    async def test_preview_is_staff_only_read_only_and_matches_csv_columns(self):
        await self.setup_published()
        revision = await self.revision()
        url = f'/seasons/{self.sid}/export-preview?kind=accounts&basis=published'
        self.assertEqual((await self.call('GET', url)).status, 401)
        self.assertEqual((await self.call('GET', url, self.member)).status, 403)
        response = await self.call('GET', url + '&unused=1', self.owner)
        self.assertEqual(response.status, 200, await response.text())
        self.assertIn('no-store', response.headers['Cache-Control'])
        preview = await response.json()
        self.assertEqual((preview['kind'], preview['basis']), ('accounts', 'published'))
        self.assertEqual(preview['summary']['published_available'], True)
        self.assertEqual(preview['summary']['roster_basis'], 'published')
        self.assertEqual(preview['counts']['rows'], len(preview['rows']))
        self.assertTrue(preview['rows'])
        csv_response = await self.call('GET', f'/seasons/{self.sid}/export.csv?kind=accounts&basis=published', self.owner)
        reader = csv.reader(io.StringIO((await csv_response.read()).decode('utf-8-sig')))
        self.assertEqual(next(reader), preview['columns'])
        self.assertEqual(len(list(reader)), preview['counts']['rows'])
        self.assertEqual(await self.revision(), revision)

    async def test_published_preview_excludes_current_draft_bonus_selection_and_new_signups(self):
        await self.setup_published()
        await self.signup('main', '#G2Y')
        self.assertEqual((await self.settings(0)).status, 200)
        response = await self.select(1)
        self.assertEqual(response.status, 200, await response.text())
        current = await self.call('GET', f'/seasons/{self.sid}/export-preview?kind=accounts&basis=current', self.owner)
        published = await self.call('GET', f'/seasons/{self.sid}/export-preview?kind=accounts&basis=published', self.owner)
        self.assertEqual(current.status, 200, await current.text())
        self.assertEqual(published.status, 200, await published.text())
        current_rows = (await current.json())['rows']
        published_data = await published.json()
        published_rows = published_data['rows']
        self.assertEqual(len(current_rows), len(published_rows) + 1)
        self.assertNotIn('#G2Y', {row['tag'] for row in published_rows})
        self.assertTrue(any(row['bonus_draft_selected'] for row in current_rows))
        self.assertFalse(any(row['bonus_draft_selected'] for row in published_rows))
        self.assertEqual(published_data['summary']['published_available'], True)

    async def test_mismatched_saved_results_are_separated_from_current_and_published_rosters(self):
        await self.setup_published()
        response = await self.call(
            'PATCH', f'/seasons/{self.sid}/participation/%23P2Y', self.owner,
            json={'revision': 0, 'publication_version': 1, 'attacks': 2, 'stars': 5, 'notes': 'Old host result'},
        )
        self.assertEqual(response.status, 200, await response.text())
        response = await self.call('POST', '/clans', self.owner, json={'tag': '#J2Y'})
        self.assertEqual(response.status, 201)
        response = await self.call(
            'PATCH', f'/seasons/{self.sid}/roster/%23P2Y', self.owner,
            json={'revision': await self.revision(), 'assigned_clan_tag': '#J2Y', 'kept': True},
        )
        self.assertEqual(response.status, 200, await response.text())
        response = await self.call(
            'POST', f'/seasons/{self.sid}/publication', self.owner,
            json={'revision': await self.revision(), 'acknowledge_unassigned': True, 'joining_instructions': ''},
        )
        self.assertEqual(response.status, 201, await response.text())

        for basis in ('current', 'published'):
            response = await self.call(
                'GET', f'/seasons/{self.sid}/export-preview?kind=accounts&basis={basis}', self.owner,
            )
            self.assertEqual(response.status, 200, await response.text())
            row = next(row for row in (await response.json())['rows'] if row['tag'] == '#P2Y')
            self.assertFalse(row['participation_matches_roster'])
            self.assertIsNone(row['participation_attacks'])
            self.assertEqual(row['participation_recorded_clan_tag'], '#C2Y')

        published_participation = await self.call(
            'GET', f'/seasons/{self.sid}/export-preview?kind=participation&basis=published', self.owner,
        )
        self.assertEqual(published_participation.status, 200, await published_participation.text())
        published_row = (await published_participation.json())['rows'][0]
        self.assertEqual(published_row['assigned_clan_tag'], '#J2Y')
        self.assertFalse(published_row['matches_roster'])
        self.assertIsNone(published_row['attacks'])
        self.assertEqual(published_row['recorded_clan_tag'], '#C2Y')

        history = await self.call(
            'GET', f'/seasons/{self.sid}/export-preview?kind=participation-history', self.owner,
        )
        self.assertEqual(history.status, 200, await history.text())
        historical_row = (await history.json())['rows'][0]
        self.assertEqual(historical_row['attacks'], 2)
        self.assertEqual(historical_row['assigned_clan_tag'], '#C2Y')

    async def test_preview_missing_published_roster_and_invalid_kind(self):
        base = f'/seasons/{self.sid}/export-preview'
        self.assertEqual((await self.call('GET', base + '?kind=accounts&basis=published', self.owner)).status, 409)
        self.assertEqual((await self.call('GET', base + '?kind=bad', self.owner)).status, 400)
        self.assertEqual((await self.call('GET', base + '?kind=accounts&basis=bad', self.owner)).status, 400)

    async def test_bonus_history_retains_void_and_participation(self):
        await self.setup_published()
        response = await self.call('PATCH', f'/seasons/{self.sid}/participation/%23P2Y', self.owner,
            json={'revision': 0, 'publication_version': 1, 'attacks': 0, 'stars': 0, 'notes': 'Reviewed'})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await self.settings(0)).status, 200)
        self.assertEqual((await self.select(1)).status, 200)
        preview = await self.preview()
        response = await self.call('POST', self.base + '/confirm', self.owner, json={'revision': 2, 'fingerprint': preview['fingerprint'], 'acknowledge_warnings': True})
        self.assertIn(response.status, (200, 201), await response.text())
        history = await self.download('?kind=bonus-history')
        self.assertEqual(history[0]['record_type'], 'dashboard_selection_not_game_award')
        self.assertEqual(history[0]['attacks'], '0')
        response = await self.call('POST', self.base + '/' + history[0]['id'] + '/void', self.owner, json={'revision': 3, 'reason': 'Correction'})
        self.assertEqual(response.status, 200, await response.text())
        history = await self.download('?kind=bonus-history')
        self.assertEqual(history[0]['void_reason'], 'Correction')
        self.assertTrue(history[0]['voided_at'])
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM publication_accounts WHERE tag=?', ('#P2Y',))
        participation = await self.download('?kind=participation')
        self.assertEqual(participation[0]['attacks'], '0')
        self.assertEqual(participation[0]['in_latest_publication'], 'No')
        self.assertEqual(participation[0]['notes'], 'Reviewed')

    def test_formula_cells_are_escaped(self):
        for value in ('=1+1', '+CMD', '-1+2', '@SUM(A1)', '  =1', '\tbad', '\rbad'):
            self.assertTrue(csv_cell(value).startswith("'"))
        self.assertEqual(csv_cell(None), '')
        self.assertEqual(csv_cell(0), '0')

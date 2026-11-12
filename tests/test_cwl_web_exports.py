"""Preview authorization, spreadsheet safety and historical accuracy."""
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
    seed_complete_source = fixtures.BonusTests.seed_complete_source
    legacy_override = fixtures.BonusTests.legacy_override
    settings = fixtures.BonusTests.settings
    select = fixtures.BonusTests.select
    preview = fixtures.BonusTests.preview
    base = fixtures.BonusTests.base

    async def snapshot_rows(self, query=''):
        # Preserve the existing scalar-domain assertions against the retained
        # preview contract. Actual Excel encoding is tested separately.
        response = await self.call('GET', f'/seasons/{self.sid}/export-preview' + query, self.owner)
        self.assertEqual(response.status, 200, await response.text())
        self.assertIn('no-store', response.headers['Cache-Control'])
        payload = await response.json()
        return [{key: csv_cell(row.get(key)) for key in payload['columns']} for row in payload['rows']]

    async def test_access_empty_and_invalid_exports(self):
        url = f'/seasons/{self.sid}/export-preview'
        self.assertEqual((await self.call('GET', url)).status, 401)
        self.assertEqual((await self.call('GET', url, self.member)).status, 403)
        self.assertEqual((await self.call('GET', url + '?kind=nope', self.owner)).status, 400)
        self.assertEqual((await self.call('GET', url + '?basis=published', self.owner)).status, 409)
        self.assertEqual(await self.snapshot_rows(), [])
        self.assertEqual((await self.call('GET', '/seasons/9999/export-preview', self.owner)).status, 404)

    async def test_current_published_and_archived_exports_preserve_values(self):
        await self.setup_published()
        with self.app['store'].tx() as db:
            db.execute("UPDATE signups SET player_name=?,signup_clan_name=? WHERE season_id=?", ('=SUM(1,2)', 'Clan, "é"\nsecond line', self.sid))
            db.execute('UPDATE roster_entries SET manual_weight=174000,source_weight=176000,assigned_clan_tag=NULL WHERE season_id=?', (self.sid,))
        rows = await self.snapshot_rows()
        self.assertEqual(rows[0]['player_name'], "'=SUM(1,2)")
        self.assertEqual(rows[0]['signup_clan_name'], 'Clan, "é"\nsecond line')
        self.assertEqual(rows[0]['effective_weight'], '174000')
        self.assertEqual(rows[0]['legacy_manual_weight'], '174000')
        self.assertNotIn('manual_weight', rows[0])
        self.assertEqual(rows[0]['source_weight'], '176000')
        self.assertEqual(rows[0]['participation_attacks'], '')
        self.assertEqual(rows[0]['assigned_clan_tag'], '')
        published = await self.snapshot_rows('?basis=published')
        self.assertEqual(published[0]['assigned_clan_tag'], '#C2Y')
        self.assertEqual(published[0]['player_name'], 'Main')
        self.assertIn('manual_weight', published[0])
        self.assertNotIn('legacy_manual_weight', published[0])
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        revision = await self.revision()
        archived = await self.snapshot_rows()
        self.assertEqual(archived[0]['season_status'], 'archived')
        self.assertEqual(await self.revision(), revision)

    async def test_preview_is_staff_only_read_only_and_has_declared_columns(self):
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
        self.assertTrue(all(set(preview['columns']).issubset(row) for row in preview['rows']))
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
        await self.legacy_override(attacks=2, stars=5, notes='Old host result')
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
        await self.seed_complete_source()
        await self.legacy_override(attacks=0, stars=0, notes='Reviewed')
        self.assertEqual((await self.settings(0)).status, 200)
        self.assertEqual((await self.select(1)).status, 200)
        preview = await self.preview()
        response = await self.call('POST', self.base + '/confirm', self.owner, json={'revision': 2, 'fingerprint': preview['fingerprint'], 'acknowledge_warnings': True})
        self.assertIn(response.status, (200, 201), await response.text())
        history = await self.snapshot_rows('?kind=bonus-history')
        self.assertEqual(history[0]['record_type'], 'dashboard_selection_not_game_award')
        self.assertEqual(history[0]['attacks'], '0')
        response = await self.call('POST', self.base + '/' + history[0]['id'] + '/void', self.owner, json={'revision': 3, 'reason': 'Correction'})
        self.assertEqual(response.status, 200, await response.text())
        history = await self.snapshot_rows('?kind=bonus-history')
        self.assertEqual(history[0]['void_reason'], 'Correction')
        self.assertTrue(history[0]['voided_at'])
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM publication_accounts WHERE tag=?', ('#P2Y',))
        participation = await self.snapshot_rows('?kind=participation')
        self.assertEqual(participation[0]['attacks'], '0')
        self.assertEqual(participation[0]['in_latest_publication'], 'No')
        self.assertEqual(participation[0]['notes'], 'Reviewed')

    def test_formula_cells_are_escaped(self):
        for value in ('=1+1', '+CMD', '-1+2', '@SUM(A1)', '  =1', '\tbad', '\rbad'):
            self.assertTrue(csv_cell(value).startswith("'"))
        self.assertEqual(csv_cell(None), '')
        self.assertEqual(csv_cell(0), '0')

    async def test_accounts_preview_keeps_weight_status_separate_from_waiting_participation(self):
        from cwl_web.exports import _export_snapshot
        from utils.cwl_working_roster import working_accounts, account_token
        await self.setup_published()
        query = '?kind=accounts&basis=published'
        before = await self.snapshot_rows(query)
        with self.app['store'].tx() as db:
            token = account_token(working_accounts(db, self.sid)['#P2Y'])
            db.execute(
                'INSERT INTO participation_source_results('
                'season_id,cycle,tag,attacks,stars,status,complete,checked_at,warning,roster_token) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (self.sid,'2026-10','#P2Y',None,None,'waiting',0,
                 '2026-10-01T00:00:00+00:00','October CWL has not started in Clash yet',token),
            )
            raw = _export_snapshot(db,self.sid,'accounts','published','test')
            changes = db.total_changes
            dump = list(db.iterdump())
        rows = await self.snapshot_rows(query)
        self.assertEqual(len(rows),len(before))
        self.assertEqual(rows[0]['source_status'],before[0]['source_status'])
        self.assertEqual(rows[0]['source_status'],raw['rows'][0]['source_status'])
        self.assertEqual(rows[0]['source_weight'],before[0]['source_weight'])
        self.assertEqual(rows[0]['effective_weight'],before[0]['effective_weight'])
        self.assertEqual(rows[0]['participation_source_status'],'waiting')
        self.assertEqual(rows[0]['participation_source_warning'],'October CWL has not started in Clash yet')
        self.assertEqual(rows[0]['participation_attacks'],'')
        self.assertEqual(rows[0]['participation_stars'],'')
        with self.app['store'].tx() as db:
            self.assertEqual(list(db.iterdump()),dump)

    async def test_failed_capture_agrees_at_get_and_both_preview_boundaries(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        clock = patch('cwl_web.exports.datetime', wraps=datetime)
        export_clock = clock.start()
        self.addCleanup(clock.stop)
        export_clock.now.return_value = datetime.now(timezone.utc)
        await self.setup_published()
        await self.seed_complete_source(attacks=2, stars=5)
        before = (await self.snapshot_rows('?kind=accounts&basis=published'))[0]
        for attacks, stars, override, label, code in (
            (2, 5, None, 'Last saved results', 'stale'),
            (0, 0, None, 'Last saved results', 'stale'),
            (None, None, None, 'Results unavailable', 'unavailable'),
            (None, None, (2, 5), 'Results unavailable', 'unavailable'),
            (2, 5, (None, None), 'Last saved results', 'stale'),
        ):
            with self.subTest(attacks=attacks, stars=stars, override=override):
                stamp = datetime.now(timezone.utc).isoformat()
                with self.app['store'].tx() as db:
                    db.execute('UPDATE participation_source_results SET attacks=?,stars=?,status=?,complete=0,checked_at=?,warning=? WHERE season_id=?',
                               (attacks, stars, 'stale' if attacks is not None else 'unavailable', stamp, 'CWL data unavailable', self.sid))
                    db.execute('UPDATE participation_sync_settings SET status=?,warning=?,last_checked_at=? WHERE season_id=?',
                               ('unavailable', 'Some Clash CWL data could not be refreshed; cached results are marked stale', stamp, self.sid))
                if override is not None:
                    await self.legacy_override(attacks=override[0], stars=override[1])
                    response = await self.call('GET', f'/seasons/{self.sid}/participation', self.owner)
                    self.assertEqual(response.status, 200, await response.text())
                    edited = (await response.json())['accounts'][0]
                    self.assertTrue(edited['attacks_override'])
                    self.assertTrue(edited['stars_override'])
                effective_attacks, effective_stars = override if override is not None else (attacks, stars)
                with self.app['store'].tx() as db:
                    dump = list(db.iterdump())
                response = await self.call('GET', f'/seasons/{self.sid}/participation', self.owner)
                self.assertEqual(response.status, 200, await response.text())
                account = next(row for row in (await response.json())['accounts'] if row['tag'] == '#P2Y')
                expected = account['display_status']
                self.assertEqual((expected['code'], expected['label'], expected['failed_clan']), (code, label, True))
                self.assertEqual((account['source_attacks'], account['source_stars']), (attacks, stars))
                for kind, prefix in (('accounts', 'participation_'), ('participation', '')):
                    query = f'?kind={kind}&basis=published'
                    scalar_row = next(row for row in await self.snapshot_rows(query) if row['tag'] == '#P2Y')
                    self.assertEqual(scalar_row[prefix + 'source_status'], code)
                    self.assertEqual(scalar_row[prefix + 'source_warning'], 'CWL data unavailable')
                    self.assertEqual(scalar_row[prefix + 'attacks'], '' if effective_attacks is None else str(effective_attacks))
                    self.assertEqual(scalar_row[prefix + 'stars'], '' if effective_stars is None else str(effective_stars))
                    response = await self.call('GET', f'/seasons/{self.sid}/export-preview' + query, self.owner)
                    self.assertEqual(response.status, 200, await response.text())
                    preview_row = next(row for row in (await response.json())['rows'] if row['tag'] == '#P2Y')
                    self.assertEqual(preview_row[prefix + 'display_status'], expected)
                    self.assertEqual(preview_row[prefix + 'attacks'], effective_attacks)
                    self.assertEqual(preview_row[prefix + 'stars'], effective_stars)
                    self.assertNotIn('_participation_display_source', preview_row)
                    if kind == 'accounts':
                        self.assertNotIn('participation_source_attacks', preview_row)
                        self.assertNotIn('participation_source_stars', preview_row)
                    if kind == 'accounts':
                        self.assertEqual({key: value for key, value in scalar_row.items() if not key.startswith('participation_')},
                                         {key: value for key, value in before.items() if not key.startswith('participation_')})
                with self.app['store'].tx() as db:
                    self.assertEqual(list(db.iterdump()), dump)

    async def test_unavailable_export_keeps_stored_warning_when_display_has_none(self):
        await self.setup_published()
        await self.seed_complete_source()
        with self.app['store'].tx() as db:
            db.execute("UPDATE participation_source_results SET attacks=NULL,stars=NULL,status='unavailable',complete=0,warning='CWL data unavailable' WHERE season_id=?", (self.sid,))
            dump = list(db.iterdump())
        for kind, prefix in (('accounts', 'participation_'), ('participation', '')):
            row = (await self.snapshot_rows(f'?kind={kind}&basis=published'))[0]
            self.assertEqual(row[prefix + 'source_status'], 'unavailable')
            self.assertEqual(row[prefix + 'source_warning'], 'CWL data unavailable')
        with self.app['store'].tx() as db:
            self.assertEqual(list(db.iterdump()), dump)

    async def test_old_failed_get_retains_scoped_failure_fact_without_fresh_failure_claim(self):
        from datetime import datetime, timedelta, timezone
        await self.setup_published()
        await self.seed_complete_source(attacks=2, stars=5)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        failure = 'Some Clash CWL data could not be refreshed; cached results are marked stale'
        with self.app['store'].tx() as db:
            db.execute('UPDATE participation_sync_settings SET status=?,warning=?,last_checked_at=? WHERE season_id=?',
                       ('unavailable', failure, old, self.sid))
            dump = list(db.iterdump())
        response = await self.call('GET', f'/seasons/{self.sid}/participation', self.owner)
        self.assertEqual(response.status, 200, await response.text())
        payload = await response.json()
        self.assertEqual(payload['sync']['warning'], failure)
        status = payload['accounts'][0]['display_status']
        self.assertEqual(status['code'], 'not_recent')
        self.assertFalse(status['failed_clan'])
        self.assertTrue(status['last_check_failed'])
        with self.app['store'].tx() as db:
            self.assertEqual(list(db.iterdump()), dump)

    async def test_bonus_history_includes_owned_import_source_without_writes(self):
        await self.setup_published()
        with self.app['store'].tx() as db:
            other = db.execute("INSERT INTO seasons(label,status,signup_open,history_only) VALUES ('2026-08','archived',0,1)").lastrowid
            for sid, tag in ((self.sid, '#Q2Y'), (other, '#G2Y')):
                db.execute("INSERT INTO bonus_imported_winners VALUES (?,'2026-08','lazy',?,'Official <name>','#C2Y','Import clan','import','fixture','now')", (sid, tag))
            before = list(db.iterdump())
        response = await self.call('GET', f'/seasons/{self.sid}/export-preview?kind=bonus-history&basis=current', self.owner)
        self.assertEqual(response.status, 200, await response.text())
        rows = (await response.json())['rows']
        self.assertEqual([(row['tag'], row['source'], row['record_type']) for row in rows], [('#Q2Y', 'import', 'imported_winner')])
        self.assertEqual(rows[0]['player_name'], 'Official <name>')
        with self.app['store'].tx() as db:
            self.assertEqual(list(db.iterdump()), before)


    async def test_bonus_history_permission_matrix_and_other_kinds_unchanged(self):
        import json
        await self.setup_published()
        staff = self.auth('200')
        for grant, expected in (('cwl_results', 403), ('cwl_bonuses', 200), ('cwl_send', 200)):
            with self.app['store'].tx() as db:
                db.execute('INSERT INTO grants(user_id,granted_by,permissions) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET permissions=excluded.permissions', ('200','fixture',json.dumps([grant])))
            for suffix in ('export-preview',):
                url = f'/seasons/{self.sid}/{suffix}?kind=bonus-history&basis=current'
                response = await self.call('GET',url,staff)
                self.assertEqual(response.status, expected, (grant,suffix,await response.text()))
                response = await self.call('GET',url,self.owner)
                self.assertEqual(response.status,200,await response.text())
                if grant == 'cwl_results':
                    response = await self.call('GET',f'/seasons/{self.sid}/{suffix}?kind=accounts&basis=current',staff)
                    self.assertEqual(response.status,200,await response.text())

    async def test_seasons_resolves_bound_months_once_and_is_read_only(self):
        from unittest.mock import patch
        from cwl_web import participation_sync
        await self.setup_published()
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET label='September staff history' WHERE id=?", (self.sid,))
            db.execute("UPDATE participation_sync_settings SET cycle='2026-09' WHERE season_id=?", (self.sid,))
            db.execute("INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES (?,'2026-08')", (self.sid,))
            other = db.execute("INSERT INTO seasons(label) VALUES ('2026-07')").lastrowid
            db.execute("INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES (?,'2026-06')", (other,))
            free = db.execute("INSERT INTO seasons(label) VALUES ('Unbound notes')").lastrowid
            before = list(db.iterdump())
        response = await self.call('GET','/seasons',self.owner)
        self.assertEqual(response.status,200,await response.text())
        by_id = {row['id']:row for row in (await response.json())['seasons']}
        self.assertEqual(by_id[self.sid]['cwl_month'],'2026-09')
        self.assertEqual(by_id[other]['cwl_month'],'2026-06')
        self.assertIsNone(by_id[free]['cwl_month'])
        original = participation_sync.resolved_cwl_months
        queries = []
        def counted(db, ids):
            trace=[]
            db.set_trace_callback(trace.append)
            result=original(db,ids)
            db.set_trace_callback(None)
            queries.extend(line for line in trace if line.lstrip().upper().startswith('SELECT'))
            return result
        with patch.object(participation_sync,'resolved_cwl_months',side_effect=counted) as resolver:
            response = await self.call('GET','/seasons',self.owner)
            self.assertEqual(response.status,200,await response.text())
            self.assertEqual(resolver.call_count,1)
            self.assertEqual(len(queries),1)
        with self.app['store'].tx() as db:
            self.assertEqual(list(db.iterdump()),before)

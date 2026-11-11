"""HTTP safeguards for Lazy bonus eligibility and manual candidates."""
import unittest
from unittest.mock import patch
from aiohttp import web
from test_cwl_bonus_raffle import RaffleTests
from utils.cwl_working_roster import account_token, working_accounts

ROLE = '769130325460254740'
USER = '111111111111111111'


class LazyBonusApiTests(RaffleTests):
    async def ready_lazy(self):
        await self.ready()
        self.discord_down = False
        self.rep = True
        async def discord(method, path, **kwargs):
            if self.discord_down:
                raise web.HTTPServiceUnavailable(text='Simulated Discord failure')
            if path.endswith('/roles'):
                return [{'id': ROLE, 'name': 'FWA Rep'}]
            if path.endswith('/members'):
                return [{'user': {'id': USER}, 'roles': [ROLE] if self.rep else []}]
            raise AssertionError(path)
        self.app['server_management_discord'] = discord
        async def linked_owner(tag):
            return USER
        self.providers.linked_owner = linked_owner
        with self.app['store'].tx() as db:
            db.execute("UPDATE signups SET pool='lazy',user_id=? WHERE season_id=?", (USER, self.sid))
            db.execute("UPDATE clans SET pool='lazy' WHERE tag='#C2Y'")
            db.execute("UPDATE participation_source_results SET attacks=3,stars=8,roster_token=? WHERE season_id=?", (account_token(working_accounts(db, self.sid)['#P2Y']), self.sid))
        return await self.get_state()

    async def review_preview(self):
        response = await self.call('POST', self.base + '/preview', self.owner,
                                   json={'pool': 'lazy', 'clan_tag': '#C2Y', 'slots': 2})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    def set_host_pools(self, season_pool, directory_pool, *, archived=0):
        with self.app['store'].tx() as db:
            db.execute('UPDATE clans SET pool=?,archived=? WHERE tag=?', (directory_pool, archived, '#C2Y'))
            db.execute('DELETE FROM lineup_rules WHERE season_id=? AND tag=?', (self.sid, '#C2Y'))
            if season_pool is not None:
                db.execute('INSERT INTO lineup_rules(season_id,tag,pool) VALUES (?,?,?)', (self.sid, '#C2Y', season_pool))

    async def host_state(self):
        state = await self.get_state()
        valid = next(a for a in state['accounts'] if a['tag'] == '#P2Y')['host_valid']
        return valid, [h['tag'] for h in state['lazy_hosts']], state

    async def test_host_check_uses_the_season_pool_with_directory_fallback(self):
        await self.ready_lazy()
        cases = [
            ('lazy', None, True), ('lazy', 'main', True), ('main', 'lazy', False),
            (None, 'lazy', True), (None, 'main', False),
        ]
        for season_pool, directory_pool, expected in cases:
            self.set_host_pools(season_pool, directory_pool)
            valid, hosts, _ = await self.host_state()
            self.assertEqual(valid, expected, (season_pool, directory_pool))
            self.assertEqual(hosts, ['#C2Y'] if expected else [], (season_pool, directory_pool))

    async def test_host_archived_after_the_season_counts_only_with_assigned_accounts(self):
        await self.ready_lazy()
        self.set_host_pools('lazy', None, archived=1)
        valid, hosts, state = await self.host_state()
        self.assertTrue(valid)
        self.assertEqual(hosts, ['#C2Y'])
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM roster_entries WHERE season_id=?', (self.sid,))
        valid, hosts, _ = await self.host_state()
        self.assertEqual(hosts, [])

    async def test_host_outside_the_season_lineup_is_invalid(self):
        await self.ready_lazy()
        self.set_host_pools('lazy', 'lazy')
        with self.app['store'].tx() as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute('DELETE FROM lineup_rules WHERE season_id=? AND tag=?', (self.sid, '#C2Y'))
            db.execute('DELETE FROM lineup WHERE season_id=? AND tag=?', (self.sid, '#C2Y'))
        valid, hosts, _ = await self.host_state()
        self.assertFalse(valid)
        self.assertEqual(hosts, [])

    async def test_manual_candidate_host_uses_season_pool_and_rejects_archived_clans(self):
        state = await self.ready_lazy()
        body = {'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Fill remaining bonus slot', 'revision': state['revision']}
        self.set_host_pools('main', 'lazy')
        self.assertEqual((await self.call('POST', self.base + '/manual-candidates', self.owner, json=body)).status, 400)
        self.set_host_pools('lazy', None, archived=1)
        self.assertEqual((await self.call('POST', self.base + '/manual-candidates', self.owner, json=body)).status, 400)
        self.set_host_pools('lazy', None)
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        # An existing manual candidate whose host stops being Lazy for the season is reported, not dropped.
        self.set_host_pools('main', 'lazy')
        state = await self.get_state()
        self.assertEqual(state['manual_candidate_conflicts'][0]['tag'], '#Q2Y')
        self.assertNotIn('#C2Y', [h['tag'] for h in state['lazy_hosts']])

    @property
    def status_url(self):
        return f'/seasons/{self.sid}/bonus-status'

    async def status(self):
        response = await self.call('GET', self.status_url, self.owner)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_bonus_status_auth_and_archived_season(self):
        await self.ready_lazy()
        self.assertEqual((await self.call('GET', self.status_url)).status, 401)
        self.assertEqual((await self.call('GET', self.status_url, self.member)).status, 403)
        self.assertEqual((await self.call('GET', f'/seasons/{self.sid + 99}/bonus-status', self.owner)).status, 404)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        status = await self.status()
        self.assertTrue(status['archived'])

    async def test_bonus_status_makes_no_discord_lookup_and_no_write(self):
        await self.ready_lazy()
        counts = lambda: [self.app['store'].one(f'SELECT COUNT(*) AS n FROM {t}')['n'] for t in (
            'signups', 'roster_entries', 'bonus_raffle_draws', 'bonus_confirmations', 'participation_source_results')]
        rows = counts()
        with patch('cwl_web.manage_roles.searchable_members') as members:
            await self.status()
        members.assert_not_called()
        self.assertEqual(counts(), rows)

    async def test_bonus_status_counts_match_the_full_bonus_read(self):
        state = await self.ready_lazy()
        body = {'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Fill remaining bonus slot', 'revision': state['revision']}
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        full = await self.get_state()
        status = await self.status()
        self.assertEqual(status['season_id'], self.sid)
        self.assertEqual(status['cycle'], full['cycle'])
        self.assertFalse(status['archived'])
        self.assertEqual(status['main_minimum'], full['policies']['main'])
        self.assertEqual(status['pools']['main'], [])
        (clan,) = status['pools']['lazy']
        accounts = [a for a in full['accounts'] if a['pool'] == 'lazy' and a['assigned_clan_tag'] == '#C2Y']
        self.assertEqual(clan['tag'], '#C2Y')
        self.assertEqual(clan['name'], full['clans'][0]['name'])
        self.assertTrue(clan['active'])
        self.assertEqual(clan['candidates'], len(accounts))
        self.assertEqual(clan['meets_rule'], sum(1 for a in accounts if not a['exclusion']))
        self.assertEqual(clan['results_state'], 'partial')
        self.assertEqual(clan['allowance_ready'], full['allowances']['#C2Y']['status'] == 'ready')
        self.assertEqual(clan['draw_state'], 'none')
        self.set_host_pools('main', 'main')
        (clan,) = (await self.status())['pools']['lazy']
        self.assertFalse(clan['active'])

    async def test_bonus_status_main_pool_minimum_and_draw_states(self):
        await self.ready()
        status = await self.status()
        (clan,) = status['pools']['main']
        self.assertEqual((status['main_minimum'], clan['meets_rule'], clan['candidates']), (5, 1, 1))
        self.assertEqual((clan['results_state'], clan['draw_state'], clan['active']), ('captured', 'none', True))
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM bonus_raffle_policy WHERE season_id=?', (self.sid,))
        self.assertIsNone((await self.status())['pools']['main'][0]['meets_rule'])
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO bonus_raffle_policy VALUES (?,'main',5)", (self.sid,))
        self.allowance_evidence()
        self.assertTrue((await self.status())['pools']['main'][0]['allowance_ready'])
        draw = await self.draw()
        self.assertEqual((await self.status())['pools']['main'][0]['draw_state'], 'saved')
        draw = await self.approve(draw)
        self.assertEqual((await self.status())['pools']['main'][0]['draw_state'], 'approved')
        await self.send(draw)
        self.assertEqual((await self.status())['pools']['main'][0]['draw_state'], 'sent')

    async def test_bonus_status_cancelled_draw_and_missing_results(self):
        await self.ready()
        self.allowance_evidence()
        draw = await self.draw()
        response = await self.call('POST', self.base + f"/{draw['id']}/cancel", self.owner, json={'reason': 'Wrong count'})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual((await self.status())['pools']['main'][0]['draw_state'], 'cancelled')
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM participation_source_results WHERE season_id=?', (self.sid,))
        self.assertEqual((await self.status())['pools']['main'][0]['results_state'], 'not_checked')

    async def test_flags_override_role_weight_and_stale_approval(self):
        state = await self.ready_lazy()
        body = {'tag': '#P2Y', 'flags': ['lingering'], 'override_reason': '', 'revision': state['revision']}
        response = await self.call('PATCH', self.base + '/account-review', self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        preview = await self.review_preview()
        self.assertEqual(len(preview['excluded']), 1)
        response = await self.call('PATCH', self.base + '/account-review', self.owner,
                                   json={**body, 'revision': state['revision'], 'override_reason': 'Staff approved exception'})
        self.assertEqual(response.status, 200, await response.text())
        preview = await self.review_preview()
        self.assertFalse(preview['blocking_reasons'])
        self.assertEqual(preview['eligible'][0]['multiplier'], 2)
        response = await self.call('POST', self.base + '/draw', self.owner,
            json={'pool': 'lazy', 'clan_tag': '#C2Y', 'slots': 2, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 200, await response.text())
        draw = (await response.json())['draws'][0]
        self.assertEqual(len(draw['snapshot']['winners']), 1)
        self.rep = False
        self.app['member_search_directory']['loaded_at'] = -1000
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409, await response.text())
        self.assertIsNone((await self.get_state())['draws'][0]['approved_at'])

    async def test_role_failure_does_not_silently_remove_double_chance(self):
        await self.ready_lazy()
        self.discord_down = True
        self.app['member_search_directory']['loaded_at'] = -1000
        preview = await self.review_preview()
        self.assertTrue(preview['blocking_reasons'])
        response = await self.call('POST', self.base + '/draw', self.owner,
            json={'pool': 'lazy', 'clan_tag': '#C2Y', 'slots': 2, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 409)

    async def test_manual_candidate_verified_no_signup_mutation_and_removal(self):
        state = await self.ready_lazy()
        body = {'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Fill remaining bonus slot', 'revision': state['revision']}
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        self.assertTrue(any(a['tag'] == '#Q2Y' and a.get('manual_candidate') for a in state['accounts']))
        self.assertIsNone(self.app['store'].one('SELECT tag FROM signups WHERE season_id=? AND tag=?', (self.sid, '#Q2Y')))
        preview = await self.review_preview()
        # Results for the manual candidate were never captured ("Not checked"),
        # so its logged staff reason covers them (2026-11-11 decision).
        self.assertEqual(len(preview['eligible']), 2)
        self.assertFalse(any(a['tag'] == '#Q2Y' for a in preview['excluded']))
        candidate = next(a for a in state['accounts'] if a['tag'] == '#Q2Y')
        with self.app['store'].tx() as db:
            db.execute(
                'INSERT INTO participation_source_results('
                'season_id,cycle,tag,attacks,stars,status,complete,checked_at,warning,roster_token) '
                'VALUES (?,?,?,?,?,?,?,?,?,?)',
                (self.sid,state['cycle'],'#Q2Y',4,12,'stale',1,
                 '2026-10-14T16:00:00+00:00',None,account_token(candidate)),
            )
        preview = await self.review_preview()
        self.assertEqual(len(preview['eligible']), 2)
        self.assertFalse(preview['blocking_reasons'])
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json=body)
        self.assertEqual(response.status, 409)
        response = await self.call('DELETE', self.base + '/manual-candidates', self.owner,
                                   json={'tag': '#Q2Y', 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        removed = await response.json()
        self.assertFalse(any(a['tag'] == '#Q2Y' for a in removed['accounts']))
        self.assertEqual(removed['bonus_reviews']['#Q2Y']['override_reason'], '')

    async def test_manual_candidate_override_can_be_cleared(self):
        state = await self.ready_lazy()
        body = {'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Staff exception', 'revision': state['revision']}
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        candidate = next(a for a in state['accounts'] if a['tag'] == '#Q2Y')
        self.assertEqual(candidate['bonus_review']['override_reason'], 'Staff exception')
        response = await self.call('PATCH', self.base + '/account-review', self.owner, json={
            'tag': '#Q2Y', 'flags': ['left_family'], 'override_reason': '', 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        preview = await self.review_preview()
        excluded = next(a for a in preview['excluded'] if a['tag'] == '#Q2Y')
        self.assertIn('Left the family', excluded['exclusion'])
        self.assertIn('unavailable', excluded['exclusion'])

    async def test_lazy_confirmation_uses_weighted_rule_wording(self):
        await self.ready_lazy()
        preview = await self.review_preview()
        self.assertEqual(preview['rules_version'], 2)
        self.assertIn('4+ attacks OR 3+ attacks and 8+ stars', preview['qualification_rule'])
        response = await self.call('POST', self.base + '/draw', self.owner,
            json={'pool': 'lazy', 'clan_tag': '#C2Y', 'slots': 2, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 200, await response.text())
        draw = (await response.json())['draws'][0]
        self.assertIn('Rule: 4+ attacks OR 3+ attacks and 8+ stars', draw['messages'][0])
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 200, await response.text())
        row = self.app['store'].one('SELECT reason FROM bonus_confirmations WHERE season_id=? AND cycle=?',
                                    (self.sid, '2026-10'))
        self.assertEqual(row['reason'], 'Representative-weighted Lazy CWL raffle')

    async def test_lazy_reviews_candidates_and_settings_survive_store_reopen(self):
        from cwl_web.bonuses import _view
        from cwl_web.store import Store
        from utils.cwl_bonus_raffle_store import RaffleStore
        state = await self.ready_lazy()
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json={
            'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Verified missing sync', 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        response = await self.call('PATCH', self.base + '/lazy-settings', self.owner, json={
            'representative_role_id': ROLE, 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        reopened = Store(self.app['store'].path)
        with reopened.tx() as db:
            view = _view(db, self.sid, current_roster=True)
            restored = RaffleStore(db, self.sid).enrich_view(view)
        candidate = next(account for account in restored['accounts'] if account['tag'] == '#Q2Y')
        self.assertTrue(candidate['manual_candidate'])
        self.assertEqual(candidate['bonus_review']['override_reason'], 'Verified missing sync')
        self.assertEqual(restored['lazy_settings']['representative_role_id'], ROLE)
        self.assertEqual(restored['manual_candidates'][0]['reason'], 'Verified missing sync')

    async def test_three_consecutive_prior_cycles_are_a_reasoned_lazy_exclusion(self):
        await self.ready_lazy()
        with self.app['store'].tx() as db:
            for index, cycle in enumerate(('2026-07', '2026-08', '2026-09')):
                batch = db.execute('INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?)',
                    (self.sid, cycle, index, f'prior-{cycle}', '{}', '505227988229554179', cycle)).lastrowid
                db.execute('INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (batch, self.sid, cycle, 1, '#P2Y', 'Player', 'lazy', '#C2Y', 'Lazy Host', 3, 8,
                     'Prior award', '[]', '505227988229554179', cycle))
        preview = await self.review_preview()
        excluded = next(a for a in preview['excluded'] if a['tag'] == '#P2Y')
        self.assertIn('Received a Lazy bonus in one of the previous three CWL months', excluded['exclusion'])
        state = await self.get_state()
        response = await self.call('PATCH', self.base + '/account-review', self.owner, json={
            'tag': '#P2Y', 'flags': [], 'override_reason': 'Staff approved cooldown exception',
            'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        preview = await self.review_preview()
        self.assertIn('#P2Y', {a['tag'] for a in preview['eligible']})

    def add_prior_bonus(self, db, cycle, *, voided=False, pool='lazy'):
        batch = db.execute('INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?)',
            (self.sid, cycle, 0, f'prior-{cycle}', '{}', '505227988229554179', cycle)).lastrowid
        db.execute('INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at,voided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (batch, self.sid, cycle, 1, '#P2Y', 'Player', pool, '#C2Y', 'Lazy Host', 3, 8,
             'Prior award', '[]', '505227988229554179', cycle, cycle if voided else None))

    def sit_out(self, cycle):
        from utils.cwl_bonus_raffle_store import RaffleStore
        with self.app['store'].tx() as db:
            return RaffleStore(db, self.sid)._has_three_cycle_cooldown('#P2Y', cycle)

    async def test_one_bonus_blocks_the_next_three_cycles_only(self):
        await self.ready_lazy()
        with self.app['store'].tx() as db:
            self.add_prior_bonus(db, '2026-01')
        for cycle in ('2026-02', '2026-03', '2026-04'):
            self.assertTrue(self.sit_out(cycle), cycle)
        self.assertFalse(self.sit_out('2026-05'))
        self.assertFalse(self.sit_out('2026-01'))

    async def test_sit_out_wraps_the_year(self):
        await self.ready_lazy()
        with self.app['store'].tx() as db:
            self.add_prior_bonus(db, '2025-12')
        self.assertTrue(self.sit_out('2026-03'))
        self.assertFalse(self.sit_out('2026-04'))

    async def test_main_bonus_does_not_sit_out_a_lazy_draw(self):
        await self.ready_lazy()
        with self.app['store'].tx() as db:
            self.add_prior_bonus(db, '2026-01', pool='main')
        self.assertFalse(self.sit_out('2026-02'))
        with self.app['store'].tx() as db:
            self.add_prior_bonus(db, '2025-12', pool='lazy')
        self.assertTrue(self.sit_out('2026-02'))

    async def test_voided_bonus_does_not_sit_out(self):
        await self.ready_lazy()
        with self.app['store'].tx() as db:
            self.add_prior_bonus(db, '2026-01', voided=True)
        self.assertFalse(self.sit_out('2026-02'))

    async def test_settings_scope_validation_and_archived_protection(self):
        state = await self.ready_lazy()
        body = {'representative_role_id': ROLE, 'revision': state['revision']}
        self.assertEqual((await self.call('PATCH', self.base + '/lazy-settings', self.member, json=body)).status, 403)
        self.assertEqual((await self.call('PATCH', self.base + '/lazy-settings', self.owner,
            json={**body, 'representative_role_id': '999999999999999999'})).status, 400)
        self.assertEqual((await self.call('PATCH', self.base + '/lazy-settings', self.owner, json=body)).status, 200)
        state = await self.get_state()
        self.assertEqual(state['lazy_settings']['representative_role_id'], ROLE)
        self.assertEqual((await self.call('PATCH', self.base + '/policy', self.owner,
            json={'pool': 'lazy', 'minimum': 0, 'revision': state['revision']})).status, 400)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        self.assertEqual((await self.call('POST', self.base + '/manual-candidates', self.owner,
            json={'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Extra', 'revision': state['revision']})).status, 423)

    async def test_malformed_flags_and_missing_override_reason_are_rejected(self):
        state = await self.ready_lazy()
        for flags in ([{}], ['made_up'], ['lingering', 'lingering']):
            response = await self.call('PATCH', self.base + '/account-review', self.owner,
                json={'tag': '#P2Y', 'flags': flags, 'override_reason': '', 'revision': state['revision']})
            self.assertEqual(response.status, 400)
        response = await self.call('POST', self.base + '/manual-candidates', self.owner,
            json={'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': '  ', 'revision': state['revision']})
        self.assertEqual(response.status, 400)

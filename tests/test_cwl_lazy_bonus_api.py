"""HTTP safeguards for Lazy bonus eligibility, manual candidates and FWA Rep accounts."""
import unittest
import unittest.mock
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
        self.discord_calls = 0
        async def discord(method, path, **kwargs):
            self.discord_calls += 1
            if self.discord_down:
                raise web.HTTPServiceUnavailable(text='Simulated Discord failure')
            if path.endswith('/roles'):
                return [{'id': ROLE, 'name': 'FWA Rep'}]
            if path.endswith('/members'):
                return [{'user': {'id': USER}, 'roles': [ROLE]}]
            raise AssertionError(path)
        self.app['server_management_discord'] = discord
        async def linked_owner(tag):
            return USER
        self.providers.linked_owner = linked_owner
        with self.app['store'].tx() as db:
            db.execute("UPDATE signups SET pool='lazy',user_id=? WHERE season_id=?", (USER, self.sid))
            db.execute("UPDATE clans SET pool='lazy' WHERE tag='#C2Y'")
            db.execute("UPDATE participation_source_results SET attacks=3,stars=8,roster_token=? WHERE season_id=?", (account_token(working_accounts(db, self.sid)['#P2Y']), self.sid))
        state = await self.get_state()
        return await self.add_rep('#P2Y', 'REP for Edrag Rush/420', state['revision'])

    async def add_rep(self, tag, note, revision, user=None, status=200):
        response = await self.call('POST', self.base + '/rep-accounts', user or self.owner,
                                   json={'tag': tag, 'note': note, 'revision': revision})
        self.assertEqual(response.status, status, await response.text())
        return await response.json() if status == 200 else None

    @staticmethod
    def rep(state, tag):
        return next((row for row in state['rep_accounts'] if row['tag'] == tag), None)

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
        state = await self.get_state()
        response = await self.call('DELETE', self.base + '/rep-accounts', self.owner, json={
            'tag': '#P2Y', 'rep_revision': self.rep(state, '#P2Y')['revision'], 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409, await response.text())
        self.assertIsNone((await self.get_state())['draws'][0]['approved_at'])

    async def test_odds_come_from_the_rep_list_without_discord(self):
        state = await self.ready_lazy()
        self.discord_down = True
        self.discord_calls = 0
        preview = await self.review_preview()
        self.assertFalse(preview['blocking_reasons'])
        self.assertEqual(preview['eligible'][0]['multiplier'], 2)
        self.assertEqual(preview['eligible'][0]['representative_status'], 'listed')
        self.assertEqual(self.discord_calls, 0)
        state = await self.get_state()
        response = await self.call('DELETE', self.base + '/rep-accounts', self.owner, json={
            'tag': '#P2Y', 'rep_revision': self.rep(state, '#P2Y')['revision'], 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        preview = await self.review_preview()
        self.assertEqual(preview['eligible'][0]['multiplier'], 1)
        self.assertEqual(preview['eligible'][0]['representative_status'], 'not_listed')
        self.assertEqual(self.discord_calls, 0)

    async def test_a_note_edit_keeps_a_saved_draw_approvable(self):
        await self.ready_lazy()
        preview = await self.review_preview()
        response = await self.call('POST', self.base + '/draw', self.owner,
            json={'pool': 'lazy', 'clan_tag': '#C2Y', 'slots': 2, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        draw = state['draws'][0]
        response = await self.call('PATCH', self.base + '/rep-accounts', self.owner, json={
            'tag': '#P2Y', 'note': 'REP for Edrag Rush', 'rep_revision': self.rep(state, '#P2Y')['revision'],
            'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.rep(await response.json(), '#P2Y')['note'], 'REP for Edrag Rush')
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 200, await response.text())

    async def test_older_role_rule_draw_must_be_redrawn(self):
        await self.ready_lazy()
        preview = await self.review_preview()
        response = await self.call('POST', self.base + '/draw', self.owner,
            json={'pool': 'lazy', 'clan_tag': '#C2Y', 'slots': 2, 'fingerprint': preview['fingerprint']})
        draw = (await response.json())['draws'][0]
        import json
        with self.app['store'].tx() as db:
            snapshot = json.loads(db.execute('SELECT snapshot_json FROM bonus_raffle_draws WHERE id=?', (draw['id'],)).fetchone()[0])
            snapshot['rules_version'] = 2
            db.execute('UPDATE bonus_raffle_draws SET snapshot_json=? WHERE id=?', (json.dumps(snapshot), draw['id']))
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409)
        self.assertIn('older rule set', await response.text())

    def test_clan_rep_role_matches_the_fwa_war_plans_role(self):
        from extensions.commands.fwa.war_plans import FWA_WAR_PLANS_CONFIG
        from utils.cwl_bonus_raffle_store import CLAN_REP_ROLE_ID
        self.assertEqual(CLAN_REP_ROLE_ID, str(FWA_WAR_PLANS_CONFIG['fwa_clan_rep_role_id']))

    async def test_clan_rep_members_lists_only_the_role_and_writes_nothing(self):
        await self.ready_lazy()
        OTHER = '222222222222222222'
        async def discord(method, path, **kwargs):
            assert method == 'GET' and path.endswith('/members'), (method, path)
            return [{'user': {'id': USER, 'username': 'rep'}, 'nick': 'Rep One', 'roles': [ROLE]},
                    {'user': {'id': OTHER, 'username': 'plain'}, 'roles': ['1']},
                    {'user': {'id': '333333333333333333', 'username': 'robot', 'bot': True}, 'roles': [ROLE]}]
        self.app['server_management_discord'] = discord
        self.app['member_search_directory']['loaded_at'] = -1000
        before = (await self.get_state())['revision']
        response = await self.call('GET', self.base + '/clan-rep-members', self.owner)
        self.assertEqual(response.status, 200, await response.text())
        members = (await response.json())['members']
        self.assertEqual([(m['id'], m['display_name']) for m in members], [(USER, 'Rep One')])
        self.assertEqual((await self.get_state())['revision'], before)
        self.assertEqual((await self.call('GET', self.base + '/clan-rep-members', self.member)).status, 403)
        async def down(method, path, **kwargs):
            raise web.HTTPServiceUnavailable(text='Simulated Discord failure')
        self.app['server_management_discord'] = down
        self.app['member_search_directory']['loaded_at'] = -1000
        self.assertEqual((await self.call('GET', self.base + '/clan-rep-members', self.owner)).status, 503)

    async def test_rep_list_is_family_wide_and_audited(self):
        from utils.cwl_bonus_raffle_store import RaffleStore
        state = await self.ready_lazy()
        rep = self.rep(state, '#P2Y')
        self.assertEqual((rep['user_id'], rep['note'], rep['revision']), (USER, 'REP for Edrag Rush/420', 1))
        with self.app['store'].tx() as db:
            # Not saved per season: any season reads the same list.
            self.assertEqual(RaffleStore(db, self.sid + 1000).rep_tags(), {'#P2Y'})
            audit = [dict(r) for r in db.execute('SELECT tag,action,actor_id FROM bonus_raffle_rep_account_audit')]
        self.assertEqual(audit, [{'tag': '#P2Y', 'action': 'add', 'actor_id': '505227988229554179'}])

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
        self.assertEqual(preview['rules_version'], 4)
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
        self.assertEqual(row['reason'], 'FWA Rep-weighted Lazy CWL raffle')

    async def test_lazy_reviews_candidates_and_settings_survive_store_reopen(self):
        from cwl_web.bonuses import _view
        from cwl_web.store import Store
        from utils.cwl_bonus_raffle_store import RaffleStore
        state = await self.ready_lazy()
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json={
            'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Verified missing sync', 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        state = await response.json()
        response = await self.call('PATCH', self.base + '/rep-accounts', self.owner, json={
            'tag': '#P2Y', 'note': 'Edrag Rush', 'rep_revision': 1, 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        reopened = Store(self.app['store'].path)
        with reopened.tx() as db:
            view = _view(db, self.sid, current_roster=True)
            restored = RaffleStore(db, self.sid).enrich_view(view)
        candidate = next(account for account in restored['accounts'] if account['tag'] == '#Q2Y')
        self.assertTrue(candidate['manual_candidate'])
        self.assertEqual(candidate['bonus_review']['override_reason'], 'Verified missing sync')
        self.assertEqual([(r['tag'], r['note']) for r in restored['rep_accounts']], [('#P2Y', 'Edrag Rush')])
        self.assertEqual(next(a for a in restored['accounts'] if a['tag'] == '#P2Y')['multiplier'], 2)
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
        self.assertIn('Prior winner (Sep 2026)', excluded['exclusion'])
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
        url = self.base + '/rep-accounts'
        await self.add_rep('#Q2Y', '', state['revision'], user=self.member, status=403)
        await self.add_rep('#Q2Y', 'x' * 41, state['revision'], status=400)
        await self.add_rep('not a tag!', '', state['revision'], status=400)
        await self.add_rep('#P2Y', '', state['revision'], status=409)
        await self.add_rep('#Q2Y', '', state['revision'] - 1, status=409)
        edit = {'tag': '#P2Y', 'note': 'New', 'rep_revision': 1, 'revision': state['revision']}
        self.assertEqual((await self.call('PATCH', url, self.member, json=edit)).status, 403)
        self.assertEqual((await self.call('PATCH', url, self.owner, json={**edit, 'rep_revision': 9})).status, 409)
        self.assertEqual((await self.call('PATCH', url, self.owner, json={**edit, 'extra': 1})).status, 400)
        self.assertEqual((await self.call('DELETE', url, self.member, json={'tag': '#P2Y', 'rep_revision': 1, 'revision': state['revision']})).status, 403)
        self.assertEqual((await self.call('DELETE', url, self.owner, json={'tag': '#R2Y', 'rep_revision': 1, 'revision': state['revision']})).status, 409)
        self.assertEqual([r['tag'] for r in (await self.get_state())['rep_accounts']], ['#P2Y'])
        self.providers.player = unittest.mock.AsyncMock(side_effect=TimeoutError)
        await self.add_rep('#Q2Y', '', state['revision'], status=503)
        self.assertEqual([r['tag'] for r in (await self.get_state())['rep_accounts']], ['#P2Y'])
        self.assertEqual((await self.call('PATCH', self.base + '/policy', self.owner,
            json={'pool': 'lazy', 'minimum': 0, 'revision': state['revision']})).status, 400)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        self.assertEqual((await self.call('POST', self.base + '/manual-candidates', self.owner,
            json={'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Extra', 'revision': state['revision']})).status, 423)
        await self.add_rep('#Q2Y', '', state['revision'], status=423)

    async def test_malformed_flags_and_missing_override_reason_are_rejected(self):
        state = await self.ready_lazy()
        for flags in ([{}], ['made_up'], ['lingering', 'lingering']):
            response = await self.call('PATCH', self.base + '/account-review', self.owner,
                json={'tag': '#P2Y', 'flags': flags, 'override_reason': '', 'revision': state['revision']})
            self.assertEqual(response.status, 400)
        response = await self.call('POST', self.base + '/manual-candidates', self.owner,
            json={'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': '  ', 'revision': state['revision']})
        self.assertEqual(response.status, 400)


class PriorWinnerSettingsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = RaffleTests.asyncSetUp
    asyncTearDown = RaffleTests.asyncTearDown
    auth = RaffleTests.auth
    call = RaffleTests.call
    revision = RaffleTests.revision
    signup = RaffleTests.signup
    setup_published = RaffleTests.setup_published
    ready = RaffleTests.ready
    get_state = RaffleTests.get_state
    base = RaffleTests.base
    ready_lazy = LazyBonusApiTests.ready_lazy
    add_rep = LazyBonusApiTests.add_rep
    review_preview = LazyBonusApiTests.review_preview
    status = LazyBonusApiTests.status
    status_url = LazyBonusApiTests.status_url

    async def save_length(self, months, revision=None, user=None):
        state = await self.get_state()
        return await self.call('PATCH', self.base + '/policy', user or self.owner, json={
            'clan_tag': '#C2Y', 'sit_out_months': months,
            'revision': state['revision'] if revision is None else revision})

    async def test_sit_out_setting_revision_archive_grant_audit_and_copy(self):
        state = await self.ready_lazy()
        self.assertEqual(state['sit_out_settings'], [{'tag': '#C2Y', 'name': 'Host #C2Y', 'months': 3}])
        response = await self.save_length(2)
        self.assertEqual(response.status, 200, await response.text())
        revision = (await response.json())['revision']
        response = await self.save_length(6, revision - 1)
        self.assertEqual(response.status, 409)
        self.assertEqual((await self.save_length(6, user=self.member)).status, 403)
        for bad in (True, -1, 7, '2'):
            self.assertEqual((await self.save_length(bad)).status, 400)
        with self.app['store'].tx() as db:
            row = db.execute("SELECT * FROM bonus_audit WHERE action='sit_out'").fetchone()
            import json
            self.assertEqual(json.loads(row['before_json'])['months'], 3)
            self.assertEqual(json.loads(row['after_json'])['months'], 2)
            self.assertEqual(row['actor_id'], '505227988229554179')
        response = await self.call('POST', '/seasons', self.owner, json={'label': 'Next fixture month', 'signup_open': False})
        self.assertEqual(response.status, 201, await response.text())
        next_sid = (await response.json())['id']
        self.assertEqual(self.app['store'].one('SELECT sit_out_months FROM lineup_rules WHERE season_id=?', (next_sid,))['sit_out_months'], 2)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        self.assertEqual((await self.save_length(6)).status, 423)

    async def test_imported_win_draw_host_length_main_ignored_status_and_override(self):
        await self.ready_lazy()
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO bonus_imported_winners VALUES (?,'2026-09','lazy','#P2Y','Official','#OLD','Old host','import','staff','now')", (self.sid,))
        response = await self.save_length(1)
        self.assertEqual(response.status, 200)
        state = await self.get_state()
        account = next(a for a in state['accounts'] if a['tag'] == '#P2Y')
        self.assertEqual(account['prior_winner_label'], 'Sep 2026')
        self.assertEqual(account['eligible_again'], '2026-11')
        self.assertEqual(account['exclusion'], 'Prior winner (Sep 2026)')
        self.assertEqual((await self.status())['pools']['lazy'][0]['meets_rule'], 0)
        participation = await self.call('GET', f'/seasons/{self.sid}/participation', self.owner)
        self.assertTrue((await participation.json())['accounts'][0]['sit_out_excluded'])
        response = await self.call('PATCH', self.base + '/account-review', self.owner, json={
            'tag': '#P2Y', 'flags': [], 'override_reason': 'Staff approves', 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        self.assertFalse((await response.json())['accounts'][0]['sit_out_excluded'])
        self.assertEqual((await self.status())['pools']['lazy'][0]['meets_rule'], 1)
        await self.save_length(0)
        self.assertIsNone((await self.get_state())['accounts'][0]['exclusion'])

    async def saved_lazy_draw(self):
        preview = await self.review_preview()
        response = await self.call('POST', self.base + '/draw', self.owner, json={
            'pool': 'lazy', 'clan_tag': '#C2Y', 'slots': 2, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 200, await response.text())
        return (await response.json())['draws'][0]

    async def test_length_or_new_import_blocks_v4_approval_without_reroll(self):
        await self.ready_lazy()
        draw = await self.saved_lazy_draw()
        self.assertEqual(draw['snapshot']['rules_version'], 4)
        self.assertEqual(draw['snapshot']['sit_out_months'], 3)
        await self.save_length(2)
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409)
        self.assertIn('Rules changed · draw again', (await response.json())['error'])
        self.assertEqual((await self.get_state())['draws'][0]['snapshot'], draw['snapshot'])
        await self.save_length(3)
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO bonus_imported_winners VALUES (?,'2026-09','lazy','#P2Y','Official','#OLD','Old host','import','staff','now')", (self.sid,))
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409)
        self.assertIn('Rules changed · draw again', (await response.json())['error'])

    async def test_v3_pending_draw_retains_confirmation_only_three_month_rule(self):
        import json
        await self.ready_lazy()
        draw = await self.saved_lazy_draw()
        snapshot = draw['snapshot']
        snapshot['rules_version'] = 3
        snapshot.pop('sit_out_months')
        for account in snapshot['eligible'] + snapshot['excluded']:
            for key in ('prior_winner_cycle', 'prior_winner_label', 'sit_out_months', 'eligible_again', 'sit_out_excluded'):
                account.pop(key, None)
        with self.app['store'].tx() as db:
            db.execute('UPDATE bonus_raffle_draws SET snapshot_json=? WHERE id=?', (json.dumps(snapshot), draw['id']))
            db.execute("INSERT INTO bonus_imported_winners VALUES (?,'2026-09','lazy','#P2Y','Official','#OLD','Old host','import','staff','now')", (self.sid,))
        await self.save_length(6)
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 200, await response.text())

    async def test_imported_history_does_not_replace_normal_season_copy_source(self):
        from pathlib import Path
        from tools.import_prior_lazy_winners import read_rows, check_rows, apply_checked
        from test_cwl_prior_winners import Players
        await self.ready_lazy()
        await self.save_length(2)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET label='November fixture' WHERE id=?", (self.sid,))
            db.execute("UPDATE participation_sync_settings SET cycle='2026-11' WHERE season_id=?", (self.sid,))
            db.execute("UPDATE lineup_rules SET pool='lazy',capacity=30,min_weight=150000,max_weight=180000 WHERE season_id=?", (self.sid,))
            rows = read_rows(Path(__file__).parent / 'fixtures/prior_lazy_winners_230.tsv')
        import sqlite3
        with sqlite3.connect(Path(self.app['store'].path).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None) as db:
            db.row_factory = sqlite3.Row
            checked_rows = await check_rows(db, rows, Players(rows))
        apply_checked(self.app['store'], checked_rows, 'fixture')
        response = await self.call('POST', '/seasons', self.owner, json={'label': 'December fixture', 'signup_open': False})
        self.assertEqual(response.status, 201, await response.text())
        sid = (await response.json())['id']
        with self.app['store'].tx() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT tag FROM lineup WHERE season_id=?', (sid,))], ['#C2Y'])
            self.assertEqual(dict(db.execute('SELECT pool,capacity,min_weight,max_weight,sit_out_months FROM lineup_rules WHERE season_id=?', (sid,)).fetchone()),
                             {'pool': 'lazy', 'capacity': 30, 'min_weight': 150000, 'max_weight': 180000, 'sit_out_months': 2})
            self.assertEqual(db.execute('SELECT history_only FROM seasons WHERE id=?', (sid,)).fetchone()[0], 0)

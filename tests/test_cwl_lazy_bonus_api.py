"""HTTP safeguards for Lazy bonus eligibility and manual candidates."""
import unittest
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
        self.assertIn('previous three CWL months', excluded['exclusion'])
        state = await self.get_state()
        response = await self.call('PATCH', self.base + '/account-review', self.owner, json={
            'tag': '#P2Y', 'flags': [], 'override_reason': 'Staff approved cooldown exception',
            'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())
        preview = await self.review_preview()
        self.assertIn('#P2Y', {a['tag'] for a in preview['eligible']})

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

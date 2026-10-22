"""Staff raffle workflow, integrity and durable send failure regressions."""
import asyncio
import unittest
from utils.cwl_working_roster import account_token, working_accounts
from datetime import datetime, timezone
from unittest.mock import patch

import test_cwl_web_bonuses as bonus_fixtures
from test_cwl_web_announcements import Transport, MAIN_CHANNEL, FOREIGN_CHANNEL
from extensions.cwl_discord_transport import AnnouncementUncertain, AnnouncementRejected
from utils.cwl_bonus_raffle import draw_accounts, announcement_pages, lazy_eligibility


class RaffleTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = bonus_fixtures.BonusTests.asyncSetUp
    asyncTearDown = bonus_fixtures.BonusTests.asyncTearDown
    auth = bonus_fixtures.BonusTests.auth
    call = bonus_fixtures.BonusTests.call
    revision = bonus_fixtures.BonusTests.revision
    signup = bonus_fixtures.BonusTests.signup
    setup_published = bonus_fixtures.BonusTests.setup_published

    @property
    def base(self):
        return f'/seasons/{self.sid}/bonus-raffle'

    async def ready(self):
        await self.setup_published()
        self.transport = Transport()
        self.app['announcement_transport'] = self.transport
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO participation_source_results(season_id,cycle,tag,attacks,stars,status,complete,checked_at,warning) VALUES (?,?,'#P2Y',5,12,'complete',1,?,NULL)", (self.sid, '2026-10', datetime.now(timezone.utc).isoformat()))
            db.execute('UPDATE participation_source_results SET roster_token=? WHERE season_id=?', (account_token(working_accounts(db, self.sid)['#P2Y']), self.sid))
        result = await self.call('PATCH', self.base + '/policy', self.owner, json={'pool': 'main', 'minimum': 5, 'revision': 0})
        self.assertEqual(result.status, 200, await result.text())

    async def get_state(self):
        result = await self.call('GET', self.base, self.owner)
        self.assertEqual(result.status, 200, await result.text())
        return await result.json()

    async def draw(self):
        body = {'pool': 'main', 'clan_tag': '#C2Y', 'slots': 2}
        preview = await self.call('POST', self.base + '/preview', self.owner, json=body)
        self.assertEqual(preview.status, 200, await preview.text())
        review = await preview.json()
        self.assertEqual(review['blocking_reasons'], [])
        self.body = {**body, 'fingerprint': review['fingerprint']}
        response = await self.call('POST', self.base + '/draw', self.owner, json=self.body)
        self.assertEqual(response.status, 200, await response.text())
        return (await response.json())['draws'][0]

    async def approve(self, draw):
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 200, await response.text())
        return (await response.json())['draws'][0]

    async def send(self, draw, channel=MAIN_CHANNEL, retry=False):
        response = await self.call('POST', self.base + f"/{draw['id']}/send", self.owner, json={'channel_id': channel, 'retry': retry})
        self.assertEqual(response.status, 200, await response.text())
        return (await response.json())['draws'][0]

    def allowance_evidence(self):
        import json
        from utils.cwl_bonus_allowance import AllowanceStore
        from test_cwl_bonus_allowance import war
        with self.app['store'].tx() as db:
            owner = AllowanceStore(db, self.sid, '2026-10')
            tags = ['#Y2Y', '#Y2P', '#Y2L', '#Y2Q', '#Y2G', '#Y2R', '#Y2J']
            db.execute('INSERT INTO participation_group_observations VALUES (?,?,?,?,?,?,?,?)',
                       (self.sid, '2026-10', '#C2Y', '2026-10', 'ENDED', json.dumps([[t] for t in tags]), '[]', 'now'))
            owner.capture_league('#C2Y', 'Crystal League I', 'now')
            for tag in tags:
                owner.capture_war(tag, war())

    async def test_automatic_preview_draw_and_changed_allowance_blocks_approval(self):
        from utils.cwl_bonus_allowance import AllowanceStore
        from test_cwl_bonus_allowance import war
        await self.ready()
        self.allowance_evidence()
        body = {'pool': 'main', 'clan_tag': '#C2Y', 'slots': None}
        response = await self.call('POST', self.base + '/preview', self.owner, json=body)
        preview = await response.json()
        self.assertEqual(preview['slots'], 11)
        self.assertEqual(preview['allowance_source'], 'automatic')
        self.assertEqual(preview['blocking_reasons'], [])
        response = await self.call('POST', self.base + '/draw', self.owner, json={**body, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 200, await response.text())
        draw = (await response.json())['draws'][0]
        with self.app['store'].tx() as db:
            AllowanceStore(db, self.sid, '2026-10').capture_war('#Y2Y', war(stars=20))
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409)
        self.assertEqual((await self.get_state())['draws'][0]['snapshot'], draw['snapshot'])

    async def test_automatic_missing_data_blocks_draw_and_override_remains_explicit(self):
        await self.ready()
        body = {'pool': 'main', 'clan_tag': '#C2Y', 'slots': None}
        response = await self.call('POST', self.base + '/preview', self.owner, json=body)
        preview = await response.json()
        self.assertTrue(preview['blocking_reasons'])
        response = await self.call('POST', self.base + '/draw', self.owner, json={**body, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 409)
        draw = await self.draw()
        self.assertEqual(draw['snapshot']['allowance_source'], 'staff')
        self.assertIsNone(draw['snapshot']['allowance'])

    async def test_allowance_change_invalidates_preview(self):
        from utils.cwl_bonus_allowance import AllowanceStore
        from test_cwl_bonus_allowance import war
        await self.ready()
        self.allowance_evidence()
        body = {'pool': 'main', 'clan_tag': '#C2Y', 'slots': None}
        preview = await (await self.call('POST', self.base + '/preview', self.owner, json=body)).json()
        with self.app['store'].tx() as db:
            AllowanceStore(db, self.sid, '2026-10').capture_war('#Y2Y', war(stars=20))
        response = await self.call('POST', self.base + '/draw', self.owner, json={**body, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 409)

    async def test_saved_draw_review_send_and_replays(self):
        await self.ready()
        draw = await self.draw()
        self.assertIsNone(draw['approved_at'])
        self.assertEqual(len(draw['snapshot']['winners']), 1)
        response = await self.call('POST', self.base + f"/{draw['id']}/send", self.owner, json={'channel_id': MAIN_CHANNEL})
        self.assertEqual(response.status, 409)
        replay = await self.call('POST', self.base + '/draw', self.owner, json=self.body)
        self.assertEqual((await replay.json())['draws'][0]['snapshot'], draw['snapshot'])
        await self.approve(draw)
        await self.approve(draw)
        self.assertEqual(len((await self.get_state())['history']), 1)
        await self.send(draw)
        again = await self.send(draw)
        self.assertEqual(again['delivery']['status'], 'sent')
        self.assertEqual(len(self.transport.calls), 1)

    async def test_unknown_results_below_threshold_and_stale_preview(self):
        await self.ready()
        body = {'pool': 'main', 'clan_tag': '#C2Y', 'slots': 1}
        old = await (await self.call('POST', self.base + '/preview', self.owner, json=body)).json()
        with self.app['store'].tx() as db:
            db.execute('UPDATE participation_source_results SET attacks=4,stars=9 WHERE season_id=?', (self.sid,))
        changed = await self.call('POST', self.base + '/draw', self.owner, json={**body, 'fingerprint': old['fingerprint']})
        self.assertEqual(changed.status, 409)
        below = await (await self.call('POST', self.base + '/preview', self.owner, json=body)).json()
        self.assertEqual(len(below['eligible']), 0)
        with self.app['store'].tx() as db:
            db.execute("UPDATE participation_source_results SET complete=0,status='partial' WHERE season_id=?", (self.sid,))
        partial = await (await self.call('POST', self.base + '/preview', self.owner, json=body)).json()
        self.assertIn('Resolve incomplete or changed account results before drawing', partial['blocking_reasons'])

    async def test_legacy_main_draw_without_lazy_review_fields_still_approves(self):
        import json
        await self.ready()
        draw = await self.draw()
        legacy = draw['snapshot']
        for group in ('eligible', 'excluded'):
            for account in legacy[group]:
                for field in ('bonus_review', 'three_cycle_cooldown', 'host_valid'):
                    account.pop(field, None)
        with self.app['store'].tx() as db:
            db.execute('UPDATE bonus_raffle_draws SET snapshot_json=? WHERE id=?',
                       (json.dumps(legacy), draw['id']))
        approved = await self.approve(draw)
        self.assertTrue(approved['approved_at'])

    async def test_changed_results_block_approval_without_reroll(self):
        await self.ready()
        draw = await self.draw()
        with self.app['store'].tx() as db:
            db.execute('UPDATE participation_source_results SET attacks=6 WHERE season_id=?', (self.sid,))
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409)
        self.assertEqual((await self.get_state())['draws'][0]['snapshot'], draw['snapshot'])

    async def test_uncertain_send_never_replayed_even_new_channel(self):
        await self.ready()
        draw = await self.approve(await self.draw())
        self.transport.failure = AnnouncementUncertain('timeout')
        sent = await self.send(draw)
        self.assertEqual(sent['delivery']['status'], 'uncertain')
        self.transport.failure = None
        await self.send(draw, retry=True)
        self.assertEqual(len(self.transport.calls), 1)

    async def test_known_rejection_requires_explicit_retry(self):
        await self.ready()
        draw = await self.approve(await self.draw())
        self.transport.failure = AnnouncementRejected('no permission')
        self.assertEqual((await self.send(draw))['delivery']['status'], 'failed')
        self.transport.failure = None
        await self.send(draw)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual((await self.send(draw, retry=True))['delivery']['status'], 'sent')
        self.assertEqual(len(self.transport.calls), 2)

    async def test_auth_validation_foreign_channel_and_pool_rules(self):
        await self.ready()
        self.assertEqual((await self.call('GET', self.base, self.member)).status, 403)
        self.assertEqual((await self.call('GET', self.base)).status, 401)
        no_csrf = {k: v for k, v in self.owner.items() if k != 'X-CSRF-Token'}
        self.assertEqual((await self.call('POST', self.base + '/draw', no_csrf, json={})).status, 403)
        self.assertEqual((await self.get_state())['policies'], {'main': 5, 'lazy': None})
        for slots in [True, -1, 51, '2']:
            self.assertEqual((await self.call('POST', self.base + '/preview', self.owner, json={'pool': 'main', 'clan_tag': '#C2Y', 'slots': slots})).status, 400)
        draw = await self.approve(await self.draw())
        self.assertEqual((await self.call('POST', self.base + f"/{draw['id']}/send", self.owner, json={'channel_id': FOREIGN_CHANNEL})).status, 503)
        self.assertEqual(self.transport.calls, [])

    async def test_concurrent_draw_and_delivery(self):
        await self.ready()
        draw = await self.draw()
        results = await asyncio.gather(*[self.call('POST', self.base + '/draw', self.owner, json=self.body) for _ in range(2)])
        self.assertTrue(all(r.status == 200 for r in results))
        self.assertEqual(len((await self.get_state())['draws']), 1)
        await self.approve(draw)
        responses = await asyncio.gather(*[self.call('POST', self.base + f"/{draw['id']}/send", self.owner, json={'channel_id': MAIN_CHANNEL}) for _ in range(2)])
        self.assertTrue(all(r.status in (200, 409) for r in responses))
        self.assertEqual(len(self.transport.calls), 1)

    async def test_cancel_retains_history_invalidates_preview_and_allows_corrected_draw(self):
        await self.ready()
        draw = await self.draw()
        response = await self.call('POST', self.base + f"/{draw['id']}/cancel", self.owner, json={'reason': 'Wrong bonus count'})
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())['draws'][0]['cancelled_at'])
        response = await self.call('POST', self.base + '/draw', self.owner, json=self.body)
        self.assertEqual(response.status, 409)
        replacement = await self.draw()
        self.assertNotEqual(replacement['id'], draw['id'])
        await self.approve(replacement)
        response = await self.call('POST', self.base + f"/{replacement['id']}/cancel", self.owner, json={'reason': 'No'})
        self.assertEqual(response.status, 409)

    async def test_partial_send_retry_skips_confirmed_pages(self):
        await self.ready()
        draw = await self.approve(await self.draw())
        calls = []
        async def send(channel, content, nonce):
            calls.append(content)
            if content == 'second' and len(calls) == 2:
                raise AnnouncementRejected('permission changed')
            return '999999999999999999'
        self.transport.send = send
        with patch('utils.cwl_bonus_raffle_store.announcement_pages', return_value=['first', 'second']):
            first = await self.send(draw)
            self.assertEqual(first['delivery']['status'], 'failed')
            self.assertEqual(first['delivery']['pages'][0]['status'], 'sent')
            await self.send(draw, retry=True)
        self.assertEqual(calls, ['first', 'second', 'second'])

    async def test_archived_and_other_season_are_protected(self):
        await self.ready()
        draw = await self.draw()
        response = await self.call('POST', '/seasons', self.owner, json={'label': 'Another season', 'signup_open': True})
        other = (await response.json())['id']
        response = await self.call('POST', f"/seasons/{other}/bonus-raffle/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 409)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        response = await self.call('POST', self.base + f"/{draw['id']}/approve", self.owner, json={})
        self.assertEqual(response.status, 423)

    async def test_current_signups_replace_stale_published_accounts(self):
        await self.ready()
        await self.signup('main', '#Q2Y')
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,'#Q2Y','#C2Y')", (self.sid,))
            db.execute("DELETE FROM signups WHERE season_id=? AND tag='#P2Y'", (self.sid,))
        result = await self.get_state()
        self.assertEqual(result['roster_source'], 'current_signups')
        self.assertEqual([a['tag'] for a in result['accounts']], ['#Q2Y'])
        self.assertEqual(result['historical_accounts_count'], 1)

    async def test_no_publication_required_for_bonus_review(self):
        await self.ready()
        with self.app['store'].tx() as db:
            db.execute('DELETE FROM publication_accounts WHERE publication_id IN (SELECT id FROM roster_publications WHERE season_id=?)', (self.sid,))
            db.execute('DELETE FROM roster_publications WHERE season_id=?', (self.sid,))
        draw = await self.draw()
        self.assertEqual(draw['snapshot']['publication_version'], 0)
        await self.approve(draw)


class RaffleDomainTests(unittest.TestCase):
    def test_one_equal_ticket_per_account(self):
        accounts = [{'tag': str(i), 'user_id': 'same-owner'} for i in range(50)]
        with patch('utils.cwl_bonus_raffle.secrets.SystemRandom') as rng:
            rng.return_value.sample.return_value = accounts[:3]
            self.assertEqual(draw_accounts(accounts, 3), accounts[:3])
            rng.return_value.sample.assert_called_once_with(accounts, 3)
        with self.assertRaises(ValueError):
            draw_accounts(accounts + accounts[:1], 3)
        winners = draw_accounts(accounts, 60)
        self.assertEqual(len({a['tag'] for a in winners}), 50)

    def test_lazy_rule_thresholds_overrides_and_hard_exclusions(self):
        base = {'tag': '#ABC', 'pool': 'lazy', 'assigned_clan_tag': '#HOST',
                'in_current_roster': True, 'source_complete': True,
                'attacks': 4, 'stars': 0}
        self.assertIsNone(lazy_eligibility(base))
        self.assertIsNone(lazy_eligibility({**base, 'attacks': 3, 'stars': 8}))
        self.assertIn('participation rule', lazy_eligibility({**base, 'attacks': 3, 'stars': 7}))
        self.assertIn('Missed CWL sync', lazy_eligibility({**base, 'bonus_review': {'flags': ['missed_sync']}}))
        exception = {'flags': ['missed_sync'], 'override_reason': 'Staff reviewed'}
        self.assertIsNone(lazy_eligibility({**base, 'attacks': 1, 'stars': 0,
                                            'three_cycle_cooldown': True,
                                            'bonus_review': exception}))
        self.assertIn('active Lazy clan', lazy_eligibility({**base, 'manual_candidate': True,
                            'manual_host_valid': False, 'bonus_review': exception}))
        self.assertIn('Already selected', lazy_eligibility({**base,
                            'already_confirmed_this_cycle': True, 'bonus_review': exception}))
        self.assertIn('invalid', lazy_eligibility({**base, 'attacks': 8,
                            'bonus_review': exception}))

    def test_weighted_draw_is_unique_and_multiplier_must_be_valid(self):
        ordinary = {'tag': '#ONE', 'multiplier': 1}
        representative = {'tag': '#REP', 'multiplier': 2}
        other = {'tag': '#TWO', 'multiplier': 1}
        with patch('utils.cwl_bonus_raffle.secrets.SystemRandom') as rng:
            rng.return_value.choice.side_effect = [representative, ordinary]
            winners = draw_accounts([ordinary, representative, other], 2)
            self.assertEqual(winners, [representative, ordinary])
            first_tickets, second_tickets = [call.args[0] for call in rng.return_value.choice.call_args_list]
            self.assertEqual(sum(item['tag'] == '#REP' for item in first_tickets), 2)
            self.assertFalse(any(item['tag'] == '#REP' for item in second_tickets))
        with self.assertRaises(ValueError):
            draw_accounts([{'tag': '#BAD', 'multiplier': 3}], 1)
        with self.assertRaises(ValueError):
            draw_accounts([{'tag': '#BAD', 'multiplier': 3}, {'tag': '#OK'}], 2)

    def test_unicode_long_names_split_and_no_mentions(self):
        snapshot = {'pool': 'lazy', 'clan_name': '@everyone **Clan**', 'cycle': '2026-10', 'minimum': 5,
                    'winners': [{'tag': '#P'+str(i), 'player_name': '<@123456789012345678>\n' + '😀'*80, 'attacks': None, 'stars': None} for i in range(50)]}
        pages = announcement_pages(snapshot)
        self.assertGreater(len(pages), 1)
        self.assertIn('Rule: 4+ attacks OR 3+ attacks and 8+ stars', pages[0])
        self.assertNotIn('Minimum None attacks', pages[0])
        self.assertIn('Participation unavailable', pages[0])
        self.assertTrue(all(len(p.encode('utf-16-le')) // 2 <= 2000 for p in pages))
        self.assertTrue(all('@everyone' not in p and '<@123' not in p for p in pages))
        for i in range(50):
            self.assertEqual(sum(('\\#P'+str(i)+' ·') in p for p in pages), 1)

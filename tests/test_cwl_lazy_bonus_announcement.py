"""Combined Lazy CWL bonus announcement: preview, scope, gates, mentions and durable send."""
import json
import unittest
from types import SimpleNamespace

from extensions.cwl_discord_transport import AnnouncementRejected, AnnouncementUncertain
import test_cwl_lazy_bonus_api as lazy_api
from test_cwl_web_announcements import MAIN_CHANNEL, FOREIGN_CHANNEL
from utils import cwl_bonus_announcement as render

ROLE = render.LAZY_CWL_ROLE_ID


def components_sender(transport):
    async def send_components(channel_id, payload, nonce, files=()):
        transport.calls.append((channel_id, payload, nonce, list(files)))
        if transport.failure:
            raise transport.failure
        return str(900000000000000000 + len(transport.calls))
    transport.send_components = send_components


USER = lazy_api.USER


Base = lazy_api.PriorWinnerSettingsTests


class LazyAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp, asyncTearDown, auth, call = Base.asyncSetUp, Base.asyncTearDown, Base.auth, Base.call
    revision, signup, setup_published, ready = Base.revision, Base.signup, Base.setup_published, Base.ready
    get_state, base, ready_lazy, add_rep = Base.get_state, Base.base, Base.ready_lazy, Base.add_rep
    review_preview, saved_lazy_draw = Base.review_preview, Base.saved_lazy_draw
    approve = lazy_api.RaffleTests.approve
    @property
    def url(self):
        return self.base + '/lazy-announcement'

    async def approved_lazy(self):
        await self.ready_lazy()
        components_sender(self.transport)
        draw = await self.saved_lazy_draw()
        return await self.approve(draw)

    async def preview(self, scope='one', clan='#C2Y', ping=False, user=None, status=200):
        query = f'?scope={scope}&ping={"1" if ping else "0"}' + (f'&clan_tag=%23{clan[1:]}' if clan else '')
        response = await self.call('GET', self.url + query, user or self.owner)
        self.assertEqual(response.status, status, await response.text())
        return await response.json() if status == 200 else None

    async def send_now(self, preview, request_id='a' * 24, channel=MAIN_CHANNEL, status=200):
        response = await self.call('POST', self.url, self.owner, json={
            'scope': preview['scope'], 'clan_tag': preview['clan_tag'], 'ping': preview['ping'],
            'channel_id': channel, 'request_id': request_id, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, status, await response.text())
        return await response.json()

    def audit(self):
        with self.app['store'].tx() as db:
            return [json.loads(r['after_json']) for r in db.execute(
                "SELECT after_json FROM bonus_audit WHERE action='lazy_bonus_announcement' ORDER BY id")]

    async def test_unapproved_clan_blocks_and_preview_shows_no_raw_ids(self):
        await self.ready_lazy()
        components_sender(self.transport)
        await self.saved_lazy_draw()
        preview = await self.preview()
        self.assertIn('approve the winners first', preview['blockers'][0])
        self.assertEqual(preview['pages'], [])
        await self.send_now(preview, status=409)
        self.assertEqual(self.transport.calls, [])

    async def test_one_clan_send_uses_components_v2_gold_and_no_player_pings(self):
        await self.approved_lazy()
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO bonus_imported_winners VALUES (?,'2026-09','lazy','#Q2Y','Older <@1>','#OLD','Old host','import','staff','now')", (self.sid,))
        preview = await self.preview()
        self.assertEqual(preview['blockers'], [])
        self.assertEqual(preview['last_month_label'], 'Sep 2026')
        text = json.dumps(preview['pages'])
        self.assertNotIn(USER, text)
        self.assertIn('Lazy CWL Bonus Medals', text)
        self.assertIn('last 3 seasons', text)
        result = await self.send_now(preview)
        self.assertEqual(result['status'], 'sent')
        self.assertEqual(len(result['urls']), 1)
        channel, payload, nonce, files = self.transport.calls[0]
        self.assertEqual(channel, MAIN_CHANNEL)
        self.assertEqual(payload['flags'], 1 << 15)
        self.assertEqual(payload['allowed_mentions'], {'parse': [], 'users': [], 'roles': []})
        containers = [c for c in payload['components'] if c['type'] == 17]
        self.assertTrue(all(c['accent_color'] == 0xF2B62A for c in containers))
        self.assertEqual(containers[-1]['components'][-1]['type'], 12)
        self.assertEqual(files[0][0], 'Gold_Footer.png')
        body = json.dumps(payload)
        self.assertIn(f'<@{USER}>', body)
        self.assertIn('<:CWL:1399013745598009375>', body)
        self.assertNotIn(f'<@&{ROLE}>', body)
        # External names cannot inject mentions.
        self.assertNotIn('<@1>', body)
        self.assertEqual(len(nonce), 24)
        self.assertEqual(self.audit()[-1]['status'], 'sent')

    async def test_role_ping_only_when_selected(self):
        await self.approved_lazy()
        preview = await self.preview(ping=True)
        await self.send_now(preview)
        payload = self.transport.calls[0][1]
        self.assertEqual(payload['allowed_mentions']['roles'], [ROLE])
        self.assertEqual(payload['allowed_mentions']['users'], [])
        self.assertEqual(payload['components'][0], {'type': 10, 'content': f'<@&{ROLE}>'})

    async def test_duplicate_request_and_stale_preview_never_send_twice(self):
        await self.approved_lazy()
        preview = await self.preview()
        first = await self.send_now(preview)
        again = await self.send_now(preview)
        self.assertEqual(again['urls'], first['urls'])
        self.assertEqual(len(self.transport.calls), 1)
        stale = {**preview, 'fingerprint': 'b' * 64}
        await self.send_now(stale, request_id='c' * 24, status=409)
        self.assertEqual(len(self.transport.calls), 1)

    async def test_foreign_channel_and_failures_are_recorded_without_retry(self):
        await self.approved_lazy()
        preview = await self.preview()
        await self.send_now(preview, channel=FOREIGN_CHANNEL, status=503)
        self.assertEqual(self.audit(), [])
        self.transport.failure = AnnouncementUncertain('timeout')
        result = await self.send_now(preview, request_id='d' * 24)
        self.assertEqual(result['status'], 'uncertain')
        self.assertIn('Check Discord', result['failure'])
        self.transport.failure = AnnouncementRejected('denied')
        result = await self.send_now(preview, request_id='e' * 24)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(self.transport.calls), 2)
        replay = await self.send_now(preview, request_id='e' * 24)
        self.assertEqual(replay['status'], 'failed')
        self.assertEqual(len(self.transport.calls), 2)

    async def test_permissions_input_and_archive(self):
        await self.approved_lazy()
        await self.preview(user=self.member, status=403)
        response = await self.call('GET', self.url + '?scope=some', self.owner)
        self.assertEqual(response.status, 400)
        response = await self.call('GET', self.url + '?scope=one&clan_tag=bad', self.owner)
        self.assertEqual(response.status, 400)
        preview = await self.preview()
        response = await self.call('POST', self.url, self.owner, json={'scope': 'all'})
        self.assertEqual(response.status, 400)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        await self.send_now(preview, status=423)
        self.assertEqual(self.transport.calls, [])
        from cwl_web.bonus_announcement import send
        from cwl_web.cwl_permissions import mutation_permission
        request = SimpleNamespace(match_info=SimpleNamespace(handler=send))
        self.assertEqual(mutation_permission(request), 'cwl_send')

    async def test_all_scope_lists_unready_clan(self):
        await self.approved_lazy()
        preview = await self.preview(scope='all', clan=None)
        self.assertEqual([c['tag'] for c in preview['clans']], ['#C2Y'])
        self.assertEqual(preview['blockers'], [])
        await self.preview(scope='one', clan='#Q2Y')


del Base


class LazyAnnouncementRenderTests(unittest.TestCase):
    def data(self, clans=1, winners=3, last=27, months=(3,)):
        return {'cycle': '2026-10', 'last_month_label': 'Sep 2026',
                'last_month': [{'tag': f'#P{i:04d}Y', 'player_name': f'Player {i}', 'user_id': str(10**17 + i)} for i in range(last)],
                'clans': [{'tag': f'#C{c:03d}Y', 'name': f'Clan {c}', 'bonus_count': 6,
                           'sit_out_months': months[c % len(months)],
                           'winners': [{'tag': f'#W{c:02d}{w:02d}Y', 'player_name': 'W' * 15, 'user_id': str(10**17 + w)}
                                       for w in range(winners)]} for c in range(clans)]}

    def test_large_family_splits_within_limits_and_footer_once(self):
        pages = render.messages(self.data(clans=14, winners=10, last=90), ping=True)
        self.assertGreater(len(pages), 1)
        for payload in pages:
            self.assertLessEqual(sum(map(render._units, payload['components'])), 40)
            self.assertLessEqual(sum(map(render._text_total, payload['components'])), 4000)
        footers = sum(1 for p in pages for c in p['components'] if c['type'] == 17 for x in c['components'] if x['type'] == 12)
        self.assertEqual(footers, 1)
        self.assertEqual(pages[0]['components'][0]['content'], f'<@&{ROLE}>')
        self.assertEqual(pages[0]['allowed_mentions']['roles'], [ROLE])
        self.assertTrue(all(p['allowed_mentions']['roles'] == [] for p in pages[1:]))
        self.assertEqual(sum(json.dumps(p).count(f'<@&{ROLE}>') for p in pages), 1)

    def test_sit_out_wording(self):
        self.assertEqual(render.sit_out_rule([3, 3])[0], 'Not get a bonus in the last 3 seasons.')
        self.assertEqual(render.sit_out_rule([1])[0], 'Not get a bonus in the last season.')
        self.assertIsNone(render.sit_out_rule([0])[0])
        self.assertIn("clan's sit-out", render.sit_out_rule([2, 3])[0])
        text = json.dumps(render.messages(self.data(clans=2, months=(2, 3))))
        self.assertIn('Sit-out: 2 months', text)

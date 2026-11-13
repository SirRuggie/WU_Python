"""Combined Lazy CWL bonus announcement: preview, scope, gates, mentions and durable send."""
import json
import unittest
from types import SimpleNamespace

from extensions.cwl_discord_transport import AnnouncementRejected, AnnouncementUncertain
import test_cwl_lazy_bonus_api as lazy_api
from test_cwl_web_announcements import MAIN_CHANNEL, FOREIGN_CHANNEL
from utils import cwl_bonus_announcement as render
from utils import cwl_bonus_history_image as history_image

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
        self.assertEqual(preview['history'][-1], {'label': 'September 2026', 'count': 1})
        text = json.dumps(preview['pages'])
        self.assertNotIn(USER, text)
        self.assertIn('Lazy CWL Bonus Medals', text)
        self.assertIn('last 3 seasons', text)
        # Past winners are in the image, not in the text.
        self.assertNotIn('Older', text)
        self.assertIn('/lazy-announcement/history.png?v=' + preview['fingerprint'][:16], text)
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
        self.assertEqual([name for name, _ in files], ['Lazy_Bonus_History.png', 'Gold_Footer.png'])
        self.assertTrue(files[0][1].startswith(b'\x89PNG'))
        self.assertEqual(render.attachments(payload), ['Lazy_Bonus_History.png', 'Gold_Footer.png'])
        body = json.dumps(payload)
        self.assertIn(f'<@{USER}>', body)
        self.assertIn('<:CWL:1399013745598009375>', body)
        self.assertNotIn('<@&', body)
        # External names cannot inject mentions.
        self.assertNotIn('<@1>', body)
        self.assertEqual(len(nonce), 24)
        self.assertEqual(self.audit()[-1]['status'], 'sent')

    async def test_history_shows_three_seasons_before_this_one(self):
        await self.approved_lazy()
        cycle = (await self.preview())['cycle']
        from utils.cwl_bonus_raffle_store import RaffleStore
        with self.app['store'].tx() as db:
            for back, tag in ((4, '#FOURY'), (3, '#THREEY'), (2, '#TWOY'), (1, '#ONEY'), (0, '#NOWY')):
                db.execute("INSERT INTO bonus_imported_winners VALUES (?,?,'lazy',?,'Player','#OLD','Old host','import','staff','now')",
                           (self.sid, RaffleStore.shift_cycle(cycle, -back), tag))
        preview = await self.preview()
        self.assertEqual([h['count'] for h in preview['history']], [1, 1, 1])
        from cwl_web.bonus_announcement import collect
        with self.app['store'].tx() as db:
            _, _, data = collect(db, self.sid, 'one', '#C2Y')
        self.assertEqual([[w['tag'] for w in h['winners']] for h in data['history']], [['#THREEY'], ['#TWOY'], ['#ONEY']])
        self.assertEqual([h['cycle'] for h in data['history']], [RaffleStore.shift_cycle(cycle, -n) for n in (3, 2, 1)])
        # The preview fingerprint changes when the history changes.
        with self.app['store'].tx() as db:
            db.execute("DELETE FROM bonus_imported_winners WHERE player_tag='#TWOY'")
        self.assertNotEqual((await self.preview())['fingerprint'], preview['fingerprint'])

    async def test_history_image_route_is_staff_read_only_png(self):
        await self.approved_lazy()
        response = await self.call('GET', self.url + '/history.png', self.owner)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, 'image/png')
        self.assertTrue((await response.read()).startswith(b'\x89PNG'))
        response = await self.call('GET', self.url + '/history.png', self.member)
        self.assertEqual(response.status, 403)
        response = await self.call('POST', self.url + '/history.png', self.owner)
        self.assertEqual(response.status, 405)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.audit(), [])

    async def test_ping_notifies_this_months_winners_and_no_role(self):
        await self.approved_lazy()
        preview = await self.preview(ping=True)
        self.assertEqual(preview['ping_count'], 1)
        await self.send_now(preview)
        payload = self.transport.calls[0][1]
        self.assertEqual(payload['allowed_mentions'], {'parse': [], 'users': [USER], 'roles': []})
        self.assertEqual(payload['components'][0]['type'], 17)
        self.assertNotIn('<@&', json.dumps(payload))
        self.assertEqual((await self.preview())['ping_count'], 0)

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
        return {'cycle': '2026-10',
                'history': [{'cycle': f'2026-0{m}', 'label': label,
                             'winners': [{'tag': f'#P{m}{i:03d}Y', 'player_name': f'Player {i}'} for i in range(last)]}
                            for m, label in ((7, 'July'), (8, 'August'), (9, 'September'))],
                'clans': [{'tag': f'#C{c:03d}Y', 'name': f'Clan {c}', 'bonus_count': 6,
                           'sit_out_months': months[c % len(months)],
                           'winners': [{'tag': f'#W{c:02d}{w:02d}Y', 'player_name': 'W' * 15, 'user_id': str(10**17 + w)}
                                       for w in range(winners)]} for c in range(clans)]}

    def test_large_family_splits_within_limits_and_footer_once(self):
        data = self.data(clans=14, winners=10, last=90)
        pages = render.messages(data, ping=True)
        self.assertGreater(len(pages), 1)
        for payload in pages:
            self.assertLessEqual(sum(map(render._units, payload['components'])), 40)
            self.assertLessEqual(sum(map(render._text_total, payload['components'])), 4000)
        files = [name for p in pages for name in render.attachments(p)]
        self.assertEqual(sorted(files), ['Gold_Footer.png', 'Lazy_Bonus_History.png'])
        self.assertEqual(render.attachments(pages[-1])[-1], 'Gold_Footer.png')
        self.assertTrue(all(p['allowed_mentions']['roles'] == [] and p['allowed_mentions']['parse'] == [] for p in pages))
        self.assertFalse(any('<@&' in json.dumps(p) for p in pages))
        # Every winner is pinged in a message that mentions them, and only there.
        pinged = set().union(*(p['allowed_mentions']['users'] for p in pages))
        self.assertEqual(pinged, render.ping_users(data))
        for payload in pages:
            for user in payload['allowed_mentions']['users']:
                self.assertIn(f'<@{user}>', json.dumps(payload))

    def test_history_is_one_image_in_the_rules_container(self):
        data = self.data(clans=1, winners=2, last=27)
        [payload] = render.messages(data, ping=True)
        first = payload['components'][0]['components']
        media = [c for c in first if c['type'] == 12]
        self.assertEqual(media[0]['items'][0]['media']['url'], 'attachment://Lazy_Bonus_History.png')
        self.assertEqual(media[0]['items'][0]['description'],
                         'Lazy CWL bonus winners by season. July: 27, August: 27, September: 27.')
        # 3 x 27 past winners add no text and never ping.
        self.assertNotIn('Player 1', json.dumps(payload))
        self.assertIn('-# These players got a bonus in the last 3 seasons."', json.dumps(payload))
        self.assertEqual(payload['allowed_mentions']['users'], sorted([str(10**17), str(10**17 + 1)]))
        [quiet] = render.messages(data, ping=False)
        self.assertEqual(quiet['allowed_mentions'], {'parse': [], 'users': [], 'roles': []})
        parts = render.preview_parts(payload, '/api/cwl/seasons/1/bonus-raffle/lazy-announcement/history.png?v=' + '0' * 16)
        items = [i for part in parts for c in part['children'] if c['type'] == 'media' for i in c['items']]
        self.assertTrue(items[0]['url'].endswith('history.png?v=' + '0' * 16))
        self.assertEqual(items[-1], {'url': None, 'description': 'Gold footer image'})

    def test_typical_month_fits_one_message(self):
        # About 27 winners per season and 4 Lazy clans x 7 winners (2026-11-13 estimate).
        self.assertEqual(len(render.messages(self.data(clans=4, winners=7, last=27))), 1)

    def test_history_image_names_use_font_fallback(self):
        # Names seen in Clash; DejaVu alone draws every one of these as an empty box.
        names = ['꧁Dragon꧂', '亗Legend亗', 'ツ Ninja', '김철수', 'محمد', 'สมชาย', '༒Warrior',
                 '🔥Fire', '⚔️Blade', '𓆩Royal𓆪', '୨୧ cute', '♛Queen']
        fonts = history_image._chain(True, 30)
        for name in names:
            for char in name:
                if not history_image._joins(char):
                    self.assertTrue(any(history_image._has(font, char) for font in fonts), (name, hex(ord(char))))
        self.assertFalse(history_image._has(fonts[0], '亗'))
        # Same-font characters stay in one run, so scripts such as Arabic keep their shaping.
        self.assertEqual([part for part, _ in history_image.runs('محمد', fonts)], ['محمد'])
        self.assertEqual(len(history_image.runs('亗Star亗', fonts)), 3)
        history = [{'label': 'Aug', 'winners': [{'tag': f'#N{i:03d}Y', 'player_name': n} for i, n in enumerate(names)]}]
        self.assertTrue(history_image.render(history).startswith(b'\x89PNG'))

    def test_history_image_is_deterministic_and_handles_edge_rows(self):
        history = [{'label': 'July', 'winners': []},
                   {'label': 'August', 'winners': [{'tag': '#AAAY', 'player_name': 'W' * 15}, {'tag': '#BBBY', 'player_name': ''}]},
                   {'label': 'September', 'winners': [{'tag': f'#S{i:03d}Y', 'player_name': f'ＦＵＬＬ{i}'} for i in range(60)]}]
        first = history_image.render(history)
        self.assertEqual(first, history_image.render(history))
        from io import BytesIO
        from PIL import Image
        image = Image.open(BytesIO(first))
        self.assertEqual(image.size, (1200, 205 + 60 * 64 + 40))
        self.assertEqual(history_image.alt_text(history), 'Lazy CWL bonus winners by season. July: 0, August: 2, September: 60.')

    def test_more_than_100_pinged_users_split_messages(self):
        data = self.data(clans=6, winners=30, last=0)
        for c, clan in enumerate(data['clans']):
            for w, winner in enumerate(clan['winners']):
                winner['user_id'] = str(4 * 10**17 + c * 100 + w)
        pages = render.messages(data, ping=True)
        self.assertTrue(all(len(p['allowed_mentions']['users']) <= 100 for p in pages))
        self.assertEqual(sum(len(p['allowed_mentions']['users']) for p in pages), 180)

    def test_sit_out_wording(self):
        self.assertEqual(render.sit_out_rule([3, 3])[0], 'Not get a bonus in the last 3 seasons.')
        self.assertEqual(render.sit_out_rule([1])[0], 'Not get a bonus in the last season.')
        self.assertIsNone(render.sit_out_rule([0])[0])
        self.assertIn("clan's sit-out", render.sit_out_rule([2, 3])[0])
        text = json.dumps(render.messages(self.data(clans=2, months=(2, 3))))
        self.assertIn('Sit-out: 2 months', text)

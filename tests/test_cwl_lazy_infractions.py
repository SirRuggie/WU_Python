"""Lazy CWL infractions: list rules, red post format, split, no pings, durable send."""
import json
import unittest
from types import SimpleNamespace

from extensions.cwl_discord_transport import AnnouncementRejected, AnnouncementUncertain
import test_cwl_lazy_bonus_api as lazy_api
from test_cwl_lazy_bonus_announcement import components_sender
from test_cwl_web_announcements import MAIN_CHANNEL, FOREIGN_CHANNEL
from utils import cwl_lazy_infractions as render

Base = lazy_api.PriorWinnerSettingsTests


def account(tag, name='Player', clan='#C2Y', flags=(), reason='', no_show=False, pool='lazy'):
    return {'tag': tag, 'player_name': name, 'pool': pool, 'assigned_clan_tag': clan,
            'source_no_show': no_show, 'bonus_review': {'flags': list(flags), 'override_reason': reason}}


class BuildTests(unittest.TestCase):
    def test_flags_and_did_not_join_count_staff_reason_moves_to_exceptions(self):
        data = render.build([
            account('#A', 'zed', flags=['lingering', 'missed_sync']),
            account('#B', 'Amy', no_show=True),
            account('#C', 'Clean'),
            account('#D', 'Excused', flags=['left_family'], reason='  Staff approved  '),
            account('#E', 'Main', flags=['lingering'], pool='main'),
            account('#F', 'NoHost', flags=['lingering'], clan=None),
            account('#G', 'Other', clan='#Z2Y', flags=['left_family'], no_show=True),
        ], {'#C2Y': 'B clan', '#Z2Y': 'a clan'}, '2026-11')
        self.assertEqual(data['label'], 'November 2026')
        self.assertEqual([c['name'] for c in data['clans']], ['a clan', 'B clan'])
        self.assertEqual(data['clans'][0]['players'][0]['infractions'], ['Left family', 'Did not join'])
        self.assertEqual([p['player_name'] for p in data['clans'][1]['players']], ['Amy', 'zed'])
        # Fixed label order, whatever order the flags were saved in.
        self.assertEqual(data['clans'][1]['players'][1]['infractions'], ['Missed sync', 'Lingering'])
        self.assertEqual(data['exceptions'], [{'tag': '#D', 'player_name': 'Excused', 'town_hall': None,
                                               'infractions': ['Left family'],
                                               'clan_name': 'B clan', 'reason': 'Staff approved'}])

    def test_post_is_red_with_footer_and_never_mentions(self):
        data = render.build([account('#P2Y', '<@123> **bold**', flags=['missed_sync'])], {'#C2Y': 'Lazy 1'}, '2026-11')
        pages = render.messages(data)
        self.assertEqual(len(pages), 1)
        payload = pages[0]
        self.assertEqual(payload['flags'], 1 << 15)
        self.assertEqual(payload['allowed_mentions'], {'parse': [], 'users': [], 'roles': []})
        container = payload['components'][0]
        self.assertEqual(container['accent_color'], 0xE00010)
        self.assertEqual(container['components'][-1]['items'][0]['media']['url'], 'attachment://Red_Footer.png')
        body = json.dumps(payload)
        self.assertIn('November 2026 Infractions', body)
        self.assertIn('<:CWL:1399013745598009375>', body)
        self.assertIn('`#P2Y`', body)
        self.assertIn('Missed sync', body)
        self.assertNotIn('<@123>', body)
        parts = render.preview_parts(payload)
        self.assertEqual(parts[0]['accent'], '#E00010')
        self.assertEqual(parts[0]['children'][-1]['items'][0]['description'], 'Red footer image')

    def test_a_clan_that_does_not_fit_starts_the_next_message(self):
        players = [account(f'#A{i:03d}Y'.replace('0', '2'), 'N' * 15, clan='#A2Y', flags=['missed_sync'])
                   for i in range(82)]
        players += [account('#B2Y', 'Last', clan='#B2Y', flags=['lingering'])]
        pages = render.messages(render.build(players, {'#A2Y': 'Alpha', '#B2Y': 'Beta'}, '2026-11'))
        texts = [[c.get('content', '') for c in p['components'][0]['components']] for p in pages]
        everything = '\n'.join('\n'.join(t) for t in texts)
        # Beta does not fit after Alpha's 82 rows, so it starts message 2 with its own heading.
        self.assertEqual(len(pages), 2)
        self.assertTrue(texts[1][0].startswith('### Beta'))
        self.assertEqual(everything.count('### Beta'), 1)
        self.assertEqual(sum(1 for line in everything.splitlines() if line[:1].isdigit()), 83)
        for page in texts:
            # No page ends with a clan heading that has no rows under it.
            self.assertFalse(page[-1].startswith('###'))

    def test_many_players_split_with_repeated_heading_and_footer_last(self):
        players = [account(f'#P{i:04d}Y'.replace('0', '2'), 'N' * 15, flags=['missed_sync', 'lingering', 'left_family'],
                           no_show=True) for i in range(160)]
        data = render.build(players, {'#C2Y': 'Lazy 1'}, '2026-11')
        pages = render.messages(data)
        self.assertGreater(len(pages), 1)
        for index, payload in enumerate(pages):
            container = payload['components'][0]
            units = 1 + len(container['components']) + sum(len(c.get('items', ())) for c in container['components'])
            self.assertLessEqual(units, 40)
            text = sum(len(c.get('content', '').encode('utf-16-le')) // 2 for c in container['components'])
            self.assertLessEqual(text, 4000)
            has_footer = container['components'][-1]['type'] == 12
            self.assertEqual(has_footer, index == len(pages) - 1)
        self.assertIn('(continued)', pages[1]['components'][0]['components'][0]['content'])
        lines = '\n'.join(c.get('content', '') for p in pages for c in p['components'][0]['components'])
        self.assertEqual(sum(1 for line in lines.splitlines() if 'Did not join' in line), 160)


class LazyInfractionsApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp, asyncTearDown, auth, call = Base.asyncSetUp, Base.asyncTearDown, Base.auth, Base.call
    revision, signup, setup_published, ready = Base.revision, Base.signup, Base.setup_published, Base.ready
    get_state, base, ready_lazy, add_rep = Base.get_state, Base.base, Base.ready_lazy, Base.add_rep

    @property
    def url(self):
        return self.base + '/lazy-infractions'

    async def flag(self, tag, flags, reason=''):
        state = await self.get_state()
        response = await self.call('PATCH', self.base + '/account-review', self.owner, json={
            'tag': tag, 'flags': flags, 'override_reason': reason, 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())

    async def preview(self, user=None, status=200):
        response = await self.call('GET', self.url, user or self.owner)
        self.assertEqual(response.status, status, await response.text())
        return await response.json() if status == 200 else None

    async def send_now(self, preview, request_id='a' * 24, channel=MAIN_CHANNEL, status=200):
        response = await self.call('POST', self.url, self.owner, json={
            'channel_id': channel, 'request_id': request_id, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, status, await response.text())
        return await response.json()

    def audit(self):
        with self.app['store'].tx() as db:
            return [json.loads(r['after_json']) for r in db.execute(
                "SELECT after_json FROM bonus_audit WHERE action='lazy_infractions_announcement' ORDER BY id")]

    async def asyncSetUpLazy(self):
        await self.ready_lazy()
        components_sender(self.transport)

    async def test_no_infractions_blocks_send(self):
        await self.asyncSetUpLazy()
        preview = await self.preview()
        self.assertEqual(preview['clans'], [])
        self.assertEqual(preview['pages'], [])
        self.assertIn('No players have infractions', preview['blockers'][0])
        await self.send_now(preview, status=409)
        self.assertEqual(self.transport.calls, [])

    async def add_manual_q2y(self):
        state = await self.get_state()
        response = await self.call('POST', self.base + '/manual-candidates', self.owner, json={
            'tag': '#Q2Y', 'clan_tag': '#C2Y', 'reason': 'Fill remaining bonus slot', 'revision': state['revision']})
        self.assertEqual(response.status, 200, await response.text())

    async def test_list_send_and_staff_exception(self):
        await self.asyncSetUpLazy()
        await self.add_manual_q2y()
        await self.flag('#P2Y', ['lingering'])
        await self.flag('#Q2Y', ['left_family'], reason='Moved for family war')
        preview = await self.preview()
        self.assertEqual(preview['blockers'], [])
        self.assertEqual(preview['player_count'], 1)
        self.assertEqual(preview['clans'][0]['players'][0]['tag'], '#P2Y')
        self.assertEqual(preview['clans'][0]['players'][0]['infractions'], ['Lingering'])
        self.assertEqual([e['tag'] for e in preview['exceptions']], ['#Q2Y'])
        self.assertNotIn(lazy_api.USER, json.dumps(preview))
        result = await self.send_now(preview)
        self.assertEqual(result['status'], 'sent')
        channel, payload, nonce, files = self.transport.calls[0]
        self.assertEqual(channel, MAIN_CHANNEL)
        self.assertEqual(payload['allowed_mentions'], {'parse': [], 'users': [], 'roles': []})
        self.assertEqual(payload['components'][0]['accent_color'], 0xE00010)
        self.assertEqual([name for name, _ in files], ['Red_Footer.png'])
        self.assertTrue(files[0][1].startswith(b'\x89PNG'))
        body = json.dumps(payload)
        self.assertNotIn('<@', body.replace('<:CWL:', ''))
        self.assertNotIn('#Q2Y', body)
        self.assertEqual([row['status'] for row in self.audit()], ['sending', 'sent'])
        self.assertEqual(self.audit()[-1]['players'], ['#P2Y'])

    async def test_duplicate_and_stale_preview_never_send_twice(self):
        await self.asyncSetUpLazy()
        await self.flag('#P2Y', ['missed_sync'])
        preview = await self.preview()
        first = await self.send_now(preview)
        again = await self.send_now(preview)
        self.assertEqual(again['urls'], first['urls'])
        self.assertEqual(len(self.transport.calls), 1)
        await self.flag('#P2Y', ['missed_sync', 'lingering'])
        await self.send_now(preview, request_id='c' * 24, status=409)
        self.assertEqual(len(self.transport.calls), 1)

    async def test_foreign_channel_and_failures_are_recorded_without_retry(self):
        await self.asyncSetUpLazy()
        await self.flag('#P2Y', ['missed_sync'])
        preview = await self.preview()
        await self.send_now(preview, channel=FOREIGN_CHANNEL, status=503)
        self.assertEqual(self.audit(), [])
        self.transport.failure = AnnouncementUncertain('timeout')
        result = await self.send_now(preview, request_id='d' * 24)
        self.assertEqual(result['status'], 'uncertain')
        self.transport.failure = AnnouncementRejected('denied')
        result = await self.send_now(preview, request_id='e' * 24)
        self.assertEqual(result['status'], 'failed')
        replay = await self.send_now(preview, request_id='e' * 24)
        self.assertEqual(replay['status'], 'failed')
        self.assertEqual(len(self.transport.calls), 2)

    async def test_permissions_input_and_archive(self):
        await self.asyncSetUpLazy()
        await self.flag('#P2Y', ['missed_sync'])
        await self.preview(user=self.member, status=403)
        preview = await self.preview()
        response = await self.call('POST', self.url, self.owner, json={'channel_id': MAIN_CHANNEL})
        self.assertEqual(response.status, 400)
        response = await self.call('POST', self.url, self.owner, json={
            'channel_id': 'x', 'request_id': 'a' * 24, 'fingerprint': preview['fingerprint']})
        self.assertEqual(response.status, 400)
        with self.app['store'].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        await self.send_now(preview, status=423)
        self.assertEqual(self.transport.calls, [])
        # The send is a mutation and needs Send CWL announcements.
        from cwl_web.lazy_infractions import send
        from cwl_web.cwl_permissions import mutation_permission
        self.assertEqual(mutation_permission(SimpleNamespace(match_info=SimpleNamespace(handler=send))), 'cwl_send')


# Base is only a source of helpers; keep pytest from collecting its tests twice.
del Base


if __name__ == '__main__':
    unittest.main()

"""Durable announcement gate tests; local SQLite only, no Discord calls."""
import json
import tempfile
import unittest

from cwl_web.store import Store
from utils.cwl_roster_image_store import ImageConflict, RosterImageStore


class SequenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = self.temp.name + '/roster.db'
        self.store = Store(self.path)
        self.images = RosterImageStore(self.store)
        with self.store.tx() as db:
            db.execute("INSERT INTO seasons(id,label) VALUES(1,'November')")
            db.execute("INSERT INTO roster_publications(season_id,version,revision,published_by,"
                       "published_at,joining_instructions,assigned_count,unassigned_count,clans_json) "
                       "VALUES(1,1,1,'staff','2026-10-30T00:00:00Z','',0,0,'[]')")
        self.args = dict(sequence_id='a' * 24, sid=1, pool='lazy', cycle='2026-11',
                         version=1, generation='2:3', channel='123456789012345678',
                         actor='123456789012345679',
                         plan={'clans': [{'tag': '#ABC', 'name': 'Frozen name', 'league': 'Gold'}]})
        self.bridge = dict(sequence_id='a' * 24, cycle='2026-11', pool='lazy',
                           publication_version=1, generation='2:3',
                           channel_id=123456789012345678, requested_by=123456789012345679,
                           status='sent', receipt={'status': 'sent',
                           'occurrence_id': '2026-11|roster|lazy',
                           'channel_id': 123456789012345678, 'message_id': 987})

    def test_review_survives_restart_and_replay_cannot_change_frozen_inputs(self):
        first = self.images.prepare_sequence(**self.args)
        self.assertEqual(first['status'], 'awaiting_announcement')
        reopened = RosterImageStore(Store(self.path))
        self.assertEqual(reopened.sequence(first['sequence_id']), first)
        self.assertEqual(reopened.prepare_sequence(**self.args), first)
        for field, value in [('channel', '999999999999999999'), ('generation', '2:4'),
                             ('plan', {'clans': []}), ('actor', 'other'), ('version', 2)]:
            with self.subTest(field=field), self.assertRaises(ImageConflict):
                reopened.prepare_sequence(**(self.args | {field: value}))
        self.args['plan']['clans'][0]['name'] = 'Later metadata'
        self.assertEqual(json.loads(reopened.sequence(first['sequence_id'])['plan_json'])
                         ['clans'][0]['name'], 'Frozen name')

    def test_conflicting_review_and_stale_publication_do_not_create_job(self):
        with self.assertRaises(ImageConflict):
            self.images.prepare_sequence(**(self.args | {'version': 2}))
        self.assertIsNone(self.images.sequence('a' * 24))
        self.images.prepare_sequence(**self.args)
        with self.assertRaises(ImageConflict):
            self.images.prepare_sequence(**(self.args | {'sequence_id': 'b' * 24}))
        self.assertIsNone(self.images.sequence('b' * 24))

    def test_no_unlock_from_pending_uncertain_old_or_mismatched_announcement(self):
        self.images.prepare_sequence(**self.args)
        for field, value in [('sequence_id', None), ('status', 'pending'), ('status', 'uncertain'),
                             ('generation', 'old'), ('cycle', '2026-10'), ('pool', 'main'),
                             ('publication_version', 2), ('channel_id', 987), ('requested_by', 99)]:
            with self.subTest(field=field, value=value), self.assertRaises(ImageConflict):
                self.images.confirm_sequence_announcement('a' * 24, self.bridge | {field: value})
        for field, value in [('status', 'uncertain'), ('message_id', None),
                             ('channel_id', 99), ('occurrence_id', '2026-10|roster|lazy')]:
            with self.subTest(receipt_field=field), self.assertRaises(ImageConflict):
                self.images.confirm_sequence_announcement('a' * 24, self.bridge | {
                    'receipt': self.bridge['receipt'] | {field: value}})
        self.assertEqual(self.images.sequence('a' * 24)['status'], 'awaiting_announcement')

    def test_confirmation_is_idempotent_after_restart_but_cannot_change_message(self):
        self.images.prepare_sequence(**self.args)
        confirmed = self.images.confirm_sequence_announcement('a' * 24, self.bridge)
        self.assertEqual(confirmed['status'], 'ready')
        self.assertEqual(confirmed['announcement_message_id'], '987')
        reopened = RosterImageStore(Store(self.path))
        self.assertEqual(reopened.confirm_sequence_announcement('a' * 24, self.bridge), confirmed)
        with self.assertRaises(ImageConflict):
            reopened.confirm_sequence_announcement('a' * 24, self.bridge | {
                'receipt': self.bridge['receipt'] | {'message_id': 988}})
        # Confirmation replay must not resume a stopped sequence.
        with self.store.tx() as db:
            db.execute("UPDATE roster_image_sequences SET status='stopped'")
        self.assertEqual(reopened.confirm_sequence_announcement('a' * 24, self.bridge)['status'], 'stopped')

    def test_no_png_bytes_are_persisted(self):
        with self.assertRaises(TypeError):
            self.images.prepare_sequence(**(self.args | {'plan': {'png': b'PNG'}}))
        self.assertIsNone(self.images.sequence('a' * 24))

    def image_plan(self):
        frozen = {'payload': {'content': '**Clan**', 'allowed_mentions': {'parse': []}},
                  'name': 'Clan', 'league': 'Gold', 'season_label': 'November'}
        self.args['plan'] = {'clans': [
            {'tag': '#AAA', 'request_id': 'b' * 24, 'frozen': frozen},
            {'tag': '#BBB', 'request_id': 'c' * 24, 'frozen': frozen},
        ]}
        self.images.prepare_sequence(**self.args)
        return frozen

    def claim_image(self, tag, request_id, frozen):
        return self.images.claim(1, 'lazy', tag, 1, request_id, 'post',
                                 self.args['channel'], None, frozen, self.args['actor'],
                                 sequence_id='a' * 24)

    def test_image_claim_requires_announcement_and_every_earlier_clan_confirmed(self):
        frozen = self.image_plan()
        with self.assertRaises(ImageConflict):
            self.claim_image('#AAA', 'b' * 24, frozen)
        self.images.confirm_sequence_announcement('a' * 24, self.bridge)
        with self.assertRaises(ImageConflict):
            self.claim_image('#BBB', 'c' * 24, frozen)
        first, acquired = self.claim_image('#AAA', 'b' * 24, frozen)
        self.assertTrue(acquired)
        # Concurrent claim/restart returns the same in-flight receipt, never permission to send twice.
        self.images = RosterImageStore(Store(self.path))
        self.assertFalse(self.claim_image('#AAA', 'b' * 24, frozen)[1])
        for status in ('failed', 'uncertain'):
            self.images.finish(first, status, error='Fixture failure')
            with self.subTest(status=status), self.assertRaises(ImageConflict):
                self.claim_image('#BBB', 'c' * 24, frozen)
        self.images.finish(first, 'posted', '123456789012345680')
        second, acquired = self.claim_image('#BBB', 'c' * 24, frozen)
        self.assertTrue(acquired)
        self.assertEqual(second['channel_id'], self.args['channel'])
        self.assertEqual(self.images.channels(), [])  # No separate image-channel setting required.

    def test_image_claim_rejects_changed_frozen_payload_and_unreviewed_clan(self):
        frozen = self.image_plan()
        self.images.confirm_sequence_announcement('a' * 24, self.bridge)
        for tag, request_id, payload in [('#AAA', 'd' * 24, frozen),
                                         ('#AAA', 'b' * 24, frozen | {'name': 'Changed'}),
                                         ('#CCC', 'd' * 24, frozen)]:
            with self.subTest(tag=tag, request_id=request_id), self.assertRaises(ImageConflict):
                self.claim_image(tag, request_id, payload)
        self.assertIsNone(self.images.receipt('b' * 24))

    def test_closing_waits_for_last_clan_and_restart_never_claims_it_twice(self):
        from utils.cwl_roster_messages import closing_message
        frozen = {'name': 'Clan', 'payload': {'allowed_mentions': {'parse': []}}}
        self.args['plan'] = {'clans': [
            {'tag': '#AAA', 'request_id': 'b' * 24, 'frozen': frozen}],
            'closing': {'request_id': 'd' * 24, 'payload': closing_message()}}
        self.images.prepare_sequence(**self.args)
        with self.assertRaises(ImageConflict):
            self.images.claim_sequence_closing('a' * 24)
        self.images.confirm_sequence_announcement('a' * 24, self.bridge)
        with self.assertRaises(ImageConflict):
            self.images.claim_sequence_closing('a' * 24)
        image, _ = self.claim_image('#AAA', 'b' * 24, frozen)
        self.images.finish(image, 'posted', '123456789012345680')
        closing, acquired = self.images.claim_sequence_closing('a' * 24)
        self.assertTrue(acquired)
        self.assertEqual(json.loads(closing['payload_json'])['allowed_mentions'], {'parse': []})
        reopened = RosterImageStore(Store(self.path))
        self.assertFalse(reopened.claim_sequence_closing('a' * 24)[1])
        result = reopened.finish_sequence_closing('a' * 24, status='posted', message='123456789012345681')
        self.assertEqual(reopened.sequence('a' * 24)['status'], 'complete')
        self.assertEqual(reopened.finish_sequence_closing('a' * 24, status='failed', error='stale worker'), result)
        self.assertFalse(reopened.claim_sequence_closing('a' * 24)[1])

    def test_even_frozen_image_plan_cannot_enable_mentions(self):
        frozen = {'payload': {'allowed_mentions': {'parse': ['roles']}}}
        self.args['plan'] = {'clans': [{'tag': '#AAA', 'request_id': 'b' * 24, 'frozen': frozen}]}
        self.images.prepare_sequence(**self.args)
        self.images.confirm_sequence_announcement('a' * 24, self.bridge)
        with self.assertRaises(ImageConflict):
            self.claim_image('#AAA', 'b' * 24, frozen)

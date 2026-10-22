"""Allowance rules, incomplete evidence, persistence, and raffle boundaries."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cwl_web.store import Store
from utils.cwl_bonus_allowance import AllowanceStore, base_allowance, final_war


def war(stars=40, enemy=35, destruction=90, other=85, size=30):
    return {'state': 'ENDED', 'team_size': size,
            'clan': {'tag': '#C2Y', 'stars': stars, 'destruction': destruction},
            'opponent': {'tag': '#J2Y', 'stars': enemy, 'destruction': other}}


class AllowanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.store = Store(self.path)
        with self.store.tx() as db:
            db.execute("INSERT INTO seasons(id,label,status) VALUES (1,'October','draft')")

    def tearDown(self):
        self.temp.cleanup()

    def populate(self, db, state='ENDED'):
        owner = AllowanceStore(db, 1, '2026-10')
        tags = ['#Y2Y', '#Y2P', '#Y2L', '#Y2Q', '#Y2G', '#Y2R', '#Y2J']
        db.execute('INSERT INTO participation_group_observations VALUES (?,?,?,?,?,?,?,?)',
                   (1, '2026-10', '#C2Y', '2026-10', state, json.dumps([[t] for t in tags]), '[]', 'now'))
        owner.capture_league('#C2Y', 'Crystal League I', 'now')
        for tag in tags:
            owner.capture_war(tag, war())
        return owner, tags

    def test_table_format_and_history_boundaries(self):
        for league, base in [('Bronze', 1), ('Silver', 1), ('Gold', 2), ('Crystal', 2), ('Master', 3), ('Champion', 4), ('Titan', 5)]:
            for rank in ['I', 'II', 'III']:
                name = f'{league} League {rank}'
                self.assertEqual(base_allowance(name, 15, '2026-10'), base)
                self.assertEqual(base_allowance(name, 30, '2026-10'), base * 2 if base <= 3 else None)
        self.assertEqual(base_allowance('Legend League', 15, '2026-10'), 6)
        for league, size, cycle in [('Unranked', 15, '2026-10'), ('Crystal League I', 5, '2026-10'), ('Crystal League I', 30, '2026-02')]:
            self.assertIsNone(base_allowance(league, size, cycle))

    def test_final_results_league_retention_restart_and_cycle_isolation(self):
        with self.store.tx() as db:
            owner, _ = self.populate(db)
            owner.capture_league('#C2Y', 'Master League III', 'later')
            self.assertEqual(owner.view('#C2Y')['total'], 11)
            self.assertEqual(owner.view('#C2Y')['league'], 'Crystal League I')
            self.assertIsNone(AllowanceStore(db, 1, '2026-11').view('#C2Y')['total'])
        with Store(self.path).tx() as db:
            self.assertEqual(AllowanceStore(db, 1, '2026-10').view('#C2Y')['total'], 11)

    def test_ties_losses_and_opponent_orientation(self):
        with self.store.tx() as db:
            owner, tags = self.populate(db)
            owner.capture_war(tags[0], war(stars=40, enemy=40, destruction=90, other=90))
            owner.capture_war(tags[1], war(stars=40, enemy=40, destruction=89, other=90))
            reverse = war()
            reverse['clan'], reverse['opponent'] = reverse['opponent'], reverse['clan']
            owner.capture_war(tags[2], reverse)
            self.assertEqual(owner.view('#C2Y')['wins'], 5)
            self.assertEqual(owner.view('#C2Y')['total'], 9)

    def test_missing_duplicate_in_progress_and_inconsistent_size_fail_closed(self):
        with self.store.tx() as db:
            owner, tags = self.populate(db, 'INWAR')
            self.assertIsNone(owner.view('#C2Y')['total'])
            db.execute("UPDATE participation_group_observations SET state='ENDED'")
            db.execute('DELETE FROM bonus_allowance_wars WHERE war_tag=?', (tags[0],))
            self.assertIsNone(owner.view('#C2Y')['total'])
            owner.capture_war(tags[0], war(size=15))
            self.assertIsNone(owner.view('#C2Y')['total'])
            owner.capture_war(tags[0], war())
            db.execute('UPDATE participation_group_observations SET war_tags_json=?', (json.dumps([[tags[0]]] * 7),))
            self.assertIsNone(owner.view('#C2Y')['total'])

    def test_short_regular_group_and_zero_wins(self):
        with self.store.tx() as db:
            owner, tags = self.populate(db)
            db.execute('UPDATE participation_group_observations SET war_tags_json=?', (json.dumps([[tag] for tag in tags[:5]]),))
            for tag in tags:
                owner.capture_war(tag, war(stars=0, enemy=20))
            self.assertEqual(owner.view('#C2Y')['total'], 4)
            self.assertEqual(owner.view('#C2Y')['wins'], 0)
        self.assertIsNone(base_allowance({}, 15, '2026-10'))

    def test_malformed_results_do_not_replace_final_evidence(self):
        for key, value in [('stars', True), ('stars', -1), ('stars', 91), ('destruction', float('nan')), ('destruction', float('inf')), ('destruction', 101), ('destruction', '90')]:
            raw = war(); raw['clan'][key] = value
            self.assertIsNone(final_war(raw))
        with self.store.tx() as db:
            owner, tags = self.populate(db)
            raw = war(); raw['state'] = 'WAR'
            owner.capture_war(tags[0], raw)
            self.assertEqual(owner.view('#C2Y')['total'], 11)

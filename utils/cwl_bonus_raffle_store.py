"""SQLite owner for saved draws, review decisions and announcement receipts.

Uses the dashboard's existing transaction boundary; no network work occurs inside
a transaction. A draw is unique for a CWL month, pool and hosting clan, even when
staff create another dashboard season for the same month.
"""

import hashlib
import json
from datetime import datetime, timezone

from utils.cwl_bonus_raffle import announcement_pages, draw_accounts, eligibility

SCHEMA = """
CREATE TABLE IF NOT EXISTS bonus_raffle_policy (
 season_id INTEGER NOT NULL REFERENCES seasons(id), pool TEXT NOT NULL,
 minimum INTEGER NOT NULL CHECK(minimum BETWEEN 0 AND 7),
 PRIMARY KEY(season_id,pool)
);
CREATE TABLE IF NOT EXISTS bonus_raffle_draws (
 id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
 cycle TEXT NOT NULL, pool TEXT NOT NULL, clan_tag TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 approved_by TEXT, approved_at TEXT,
 cancelled_at TEXT, cancelled_by TEXT, cancel_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS bonus_raffle_active
 ON bonus_raffle_draws(cycle,pool,clan_tag) WHERE cancelled_at IS NULL;
CREATE TABLE IF NOT EXISTS bonus_raffle_deliveries (
 draw_id INTEGER PRIMARY KEY REFERENCES bonus_raffle_draws(id),
 channel_id TEXT NOT NULL, requested_by TEXT NOT NULL, requested_at TEXT NOT NULL,
 status TEXT NOT NULL, failure TEXT
);
CREATE TABLE IF NOT EXISTS bonus_raffle_pages (
 draw_id INTEGER NOT NULL REFERENCES bonus_raffle_draws(id), page INTEGER NOT NULL,
 status TEXT NOT NULL, message_id TEXT,
 PRIMARY KEY(draw_id,page)
);
"""


class RaffleConflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class RaffleStore:
    def __init__(self, db, season_id):
        self.db, self.sid = db, season_id

    def policies(self):
        rows = self.db.execute('SELECT pool,minimum FROM bonus_raffle_policy WHERE season_id=?', (self.sid,))
        return {'main': None, 'lazy': None, **{r['pool']: r['minimum'] for r in rows}}

    def save_policy(self, pool, minimum):
        self.db.execute('INSERT INTO bonus_raffle_policy VALUES (?,?,?) ON CONFLICT(season_id,pool) DO UPDATE SET minimum=excluded.minimum', (self.sid, pool, minimum))

    def draws(self):
        return [self.get(row['id']) for row in self.db.execute('SELECT id FROM bonus_raffle_draws WHERE season_id=? ORDER BY id DESC', (self.sid,)).fetchall()]

    def get(self, draw_id):
        row = self.db.execute('SELECT * FROM bonus_raffle_draws WHERE id=? AND season_id=?', (draw_id, self.sid)).fetchone()
        if not row:
            raise RaffleConflict('Saved draw not found for this season')
        delivery = self.db.execute('SELECT * FROM bonus_raffle_deliveries WHERE draw_id=?', (draw_id,)).fetchone()
        pages = [dict(r) for r in self.db.execute('SELECT page,status,message_id FROM bonus_raffle_pages WHERE draw_id=? ORDER BY page', (draw_id,))]
        snapshot = json.loads(row['snapshot_json'])
        metadata = {key: row[key] for key in row.keys() if key != 'snapshot_json'}
        return {**metadata, 'snapshot': snapshot, 'messages': announcement_pages(snapshot),
                'delivery': {**dict(delivery), 'pages': pages} if delivery else None}

    def preview(self, view, pool, clan_tag, slots):
        minimum = self.policies()[pool]
        accounts = [a for a in view['accounts'] if a['pool'] == pool and a['assigned_clan_tag'] == clan_tag]
        eligible, excluded, blocks = [], [], []
        if not view['cycle']:
            blocks.append('Select the CWL month in Results first')
        if view['active_other_cycles']:
            blocks.append('This season contains bonus decisions for a different CWL month')
        if minimum is None:
            blocks.append('Save the minimum attacks for this CWL pool')
        if not accounts:
            blocks.append('No current signups assigned to this clan and CWL pool')
        for account in accounts:
            reason = eligibility(account, minimum)
            if reason:
                excluded.append({**account, 'exclusion': reason})
                if reason in ('Roster changed; reconcile results before drawing', 'Results are not complete', 'Attack total is not available'):
                    blocks.append('Resolve incomplete or changed account results before drawing')
            else:
                eligible.append(account)
        if not eligible:
            blocks.append('No accounts qualify for this draw')
        confirmed = sum(r['clan_tag'] == clan_tag for r in view['cycle_confirmed'])
        reserved = 0
        if view['cycle']:
            for row in self.db.execute('SELECT snapshot_json FROM bonus_raffle_draws WHERE cycle=? AND clan_tag=? AND approved_at IS NULL AND cancelled_at IS NULL', (view['cycle'], clan_tag)):
                reserved += len(json.loads(row['snapshot_json'])['winners'])
        available = max(0, slots - confirmed - reserved)
        if not available:
            blocks.append('No bonus slots remain after saved selections')
        clan = next((c for c in view['clans'] if c['tag'] == clan_tag), {})
        result = {'cycle': view['cycle'], 'pool': pool, 'clan_tag': clan_tag,
                  'clan_name': clan.get('name', clan_tag), 'minimum': minimum,
                  'slots': slots, 'available': available, 'confirmed': confirmed,
                  'eligible': eligible, 'excluded': excluded,
                  'publication_version': view['publication_version'],
                  'blocking_reasons': sorted(set(blocks))}
        result['draw_history'] = [dict(r) for r in self.db.execute('SELECT id,cancelled_at FROM bonus_raffle_draws WHERE cycle=? AND pool=? AND clan_tag=? ORDER BY id', (view['cycle'], pool, clan_tag))]
        result['fingerprint'] = fingerprint(result)
        return result

    def draw(self, view, pool, clan_tag, slots, expected, actor):
        prior = self.db.execute('SELECT id,season_id FROM bonus_raffle_draws WHERE cycle=? AND pool=? AND clan_tag=? AND cancelled_at IS NULL', (view['cycle'], pool, clan_tag)).fetchone()
        if prior:
            if prior['season_id'] != self.sid:
                raise RaffleConflict('This clan already has a saved draw in another dashboard season for this CWL month')
            return self.get(prior['id'])
        preview = self.preview(view, pool, clan_tag, slots)
        if preview['fingerprint'] != expected:
            raise RaffleConflict('Results or rules changed. Review the qualifying accounts again')
        if preview['blocking_reasons']:
            raise RaffleConflict('; '.join(preview['blocking_reasons']))
        snapshot = {**preview, 'winners': draw_accounts(preview['eligible'], preview['available'])}
        cursor = self.db.execute('INSERT INTO bonus_raffle_draws(season_id,cycle,pool,clan_tag,snapshot_json,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
                                 (self.sid, view['cycle'], pool, clan_tag, json.dumps(snapshot), actor, now()))
        return self.get(cursor.lastrowid)

    def approve(self, draw_id, view, actor):
        draw = self.get(draw_id)
        if draw['cancelled_at']:
            raise RaffleConflict('This draw was cancelled. Use the current saved draw')
        if draw['approved_at']:
            return draw
        snapshot = draw['snapshot']
        if snapshot['cycle'] != view['cycle']:
            raise RaffleConflict('The CWL month changed. Restore the original month before approving')
        # Revalidate relevant results/identity without rerolling saved winners.
        current = {a['tag']: a for a in view['accounts']}
        original = snapshot['eligible'] + snapshot['excluded']
        relevant = [a for a in view['accounts'] if a['pool'] == snapshot['pool'] and a['assigned_clan_tag'] == snapshot['clan_tag']]
        if {a['tag'] for a in original} != {a['tag'] for a in relevant}:
            raise RaffleConflict('The participating accounts changed after the draw. Reconcile results before approval')
        for old in original:
            account = current.get(old['tag'])
            if not account or any(account.get(k) != old.get(k) for k in ('pool', 'assigned_clan_tag', 'attacks')) or eligibility(account, snapshot['minimum']) != eligibility(old, snapshot['minimum']):
                raise RaffleConflict('Results or roster changed since the draw. Resolve the discrepancy before approval; winners have not been rerolled')
        confirmed = sum(r['clan_tag'] == snapshot['clan_tag'] for r in view['cycle_confirmed'])
        if confirmed + len(snapshot['winners']) > snapshot['slots']:
            raise RaffleConflict('Other bonus selections now use these slots. Review the existing selections')
        batch = self.db.execute('INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?)',
                               (self.sid, snapshot['cycle'], view['revision'], fingerprint(snapshot), json.dumps(snapshot), actor, now())).lastrowid
        for account in snapshot['winners']:
            self.db.execute('INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (batch, self.sid, snapshot['cycle'], snapshot['publication_version'], account['tag'], account['player_name'], snapshot['pool'], snapshot['clan_tag'], snapshot['clan_name'], account['attacks'], account['stars'], 'Equal-chance account raffle', '[]', actor, now()))
        self.db.execute('UPDATE bonus_raffle_draws SET approved_by=?,approved_at=? WHERE id=?', (actor, now(), draw_id))
        return self.get(draw_id)

    def cancel(self, draw_id, actor, reason):
        draw = self.get(draw_id)
        if draw['approved_at'] or draw['delivery']:
            raise RaffleConflict('An approved or announced draw cannot be cancelled')
        if not draw['cancelled_at']:
            self.db.execute('UPDATE bonus_raffle_draws SET cancelled_at=?,cancelled_by=?,cancel_reason=? WHERE id=?', (now(), actor, reason, draw_id))

    def reserve_delivery(self, draw_id, channel_id, actor, *, retry=False):
        draw = self.get(draw_id)
        if not draw['approved_at']:
            raise RaffleConflict('Approve the winners before sending')
        if draw['delivery'] and not (retry and draw['delivery']['status'] == 'failed' and draw['delivery']['channel_id'] == channel_id):
            raise RaffleConflict('This announcement already has a delivery record. Refresh its status; do not send it again')
        # A legacy void invalidates approval for sending rather than advertising a voided winner.
        for account in draw['snapshot']['winners']:
            if not self.db.execute('SELECT 1 FROM bonus_confirmations WHERE season_id=? AND cycle=? AND tag=? AND voided_at IS NULL', (self.sid, draw['cycle'], account['tag'])).fetchone():
                raise RaffleConflict('A winner selection was voided. This announcement cannot be sent')
        if draw['delivery']:
            self.db.execute("UPDATE bonus_raffle_deliveries SET status='sending',failure=NULL WHERE draw_id=? AND status='failed'", (draw_id,))
            sent = {p['page'] for p in draw['delivery']['pages'] if p['status'] == 'sent'}
            return [(i, message) for i, message in enumerate(draw['messages']) if i not in sent]
        self.db.execute("INSERT INTO bonus_raffle_deliveries VALUES (?,?,?,?,'sending',NULL)", (draw_id, channel_id, actor, now()))
        self.db.executemany("INSERT INTO bonus_raffle_pages VALUES (?,?,'pending',NULL)", [(draw_id, i) for i in range(len(draw['messages']))])
        return list(enumerate(draw['messages']))

    def page_sent(self, draw_id, page, message_id):
        self.db.execute("UPDATE bonus_raffle_pages SET status='sent',message_id=? WHERE draw_id=? AND page=?", (message_id, draw_id, page))

    def finish_delivery(self, draw_id, status, failure=None):
        self.db.execute('UPDATE bonus_raffle_deliveries SET status=?,failure=? WHERE draw_id=?', (status, failure, draw_id))

"""Storage owner for global image destinations and per-clan delivery receipts."""
import json
import re

SCHEMA = """
CREATE TABLE IF NOT EXISTS roster_image_channels (
 pool TEXT PRIMARY KEY CHECK(pool IN ('main','lazy')),
 channel_id TEXT NOT NULL, channel_name TEXT NOT NULL,
 configured_by TEXT NOT NULL, configured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS roster_image_posts (
 id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
 pool TEXT NOT NULL CHECK(pool IN ('main','lazy')), clan_tag TEXT NOT NULL,
 channel_id TEXT NOT NULL, message_id TEXT, posted_version INTEGER,
 status TEXT NOT NULL CHECK(status IN ('sending','posted','failed','uncertain','dropped','dismissed')),
 request_id TEXT NOT NULL, error TEXT, posted_by TEXT NOT NULL,
 posted_at TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(season_id,pool,clan_tag)
);
CREATE TABLE IF NOT EXISTS roster_image_requests (
 request_id TEXT PRIMARY KEY, operation TEXT NOT NULL CHECK(operation IN ('post','update','drop')),
 season_id INTEGER NOT NULL REFERENCES seasons(id), pool TEXT NOT NULL CHECK(pool IN ('main','lazy')),
 clan_tag TEXT NOT NULL, target_version INTEGER NOT NULL, channel_id TEXT NOT NULL, message_id TEXT,
 payload_json TEXT NOT NULL, status TEXT NOT NULL, error TEXT, retry_after REAL, actor_id TEXT NOT NULL,
 replacement_request_id TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS roster_image_test_sequences (
 request_id TEXT PRIMARY KEY,
 season_id INTEGER NOT NULL REFERENCES seasons(id), pool TEXT NOT NULL,
 target_version INTEGER NOT NULL, channel_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 plan_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ready','sending','failed','uncertain','complete')),
 next_step INTEGER NOT NULL DEFAULT 0, error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS roster_image_test_receipts (
 request_id TEXT NOT NULL REFERENCES roster_image_test_sequences(request_id),
 step INTEGER NOT NULL, nonce TEXT NOT NULL UNIQUE, message_id TEXT,
 status TEXT NOT NULL CHECK(status IN ('sending','posted','failed','uncertain')),
 error TEXT, PRIMARY KEY(request_id,step)
);

CREATE TABLE IF NOT EXISTS roster_image_sequences (
 sequence_id TEXT PRIMARY KEY,
 season_id INTEGER NOT NULL REFERENCES seasons(id),
 pool TEXT NOT NULL CHECK(pool IN ('main','lazy')),
 cycle TEXT NOT NULL, target_version INTEGER NOT NULL,
 generation TEXT NOT NULL, channel_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 plan_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'awaiting_announcement'
   CHECK(status IN ('awaiting_announcement','ready','stopped','complete')),
 announcement_message_id TEXT, error TEXT, resume_requested INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(season_id,pool), UNIQUE(cycle,pool)
);

CREATE TABLE IF NOT EXISTS roster_image_sequence_closing (
 sequence_id TEXT PRIMARY KEY REFERENCES roster_image_sequences(sequence_id),
 request_id TEXT NOT NULL UNIQUE, channel_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, message_id TEXT,
 status TEXT NOT NULL CHECK(status IN ('sending','posted','failed','uncertain')),
 error TEXT, retry_after REAL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roster_image_sequence_archives (
 season_id INTEGER NOT NULL, pool TEXT NOT NULL, deleted_message_id TEXT NOT NULL,
 sequence_json TEXT, closing_json TEXT, posts_json TEXT NOT NULL,
 actor_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(season_id,pool,deleted_message_id)
);

CREATE TABLE IF NOT EXISTS roster_image_sequence_closing_history (
 request_id TEXT PRIMARY KEY, sequence_id TEXT NOT NULL,
 receipt_json TEXT NOT NULL
);

"""


def migrate(db):
    """Extend the existing CHECK constraint without changing saved delivery data."""
    if 'replacement_request_id' not in {row[1] for row in db.execute('PRAGMA table_info(roster_image_requests)')}:
        db.execute('ALTER TABLE roster_image_requests ADD COLUMN replacement_request_id TEXT')
    if 'resume_requested' not in {row[1] for row in db.execute('PRAGMA table_info(roster_image_sequences)')}:
        db.execute('ALTER TABLE roster_image_sequences ADD COLUMN resume_requested INTEGER NOT NULL DEFAULT 0')
    if 'error' not in {row[1] for row in db.execute('PRAGMA table_info(roster_image_sequences)')}:
        db.execute('ALTER TABLE roster_image_sequences ADD COLUMN error TEXT')
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='roster_image_posts'").fetchone()['sql']
    if "'dismissed'" in sql:
        return
    with db:
        db.execute('SAVEPOINT image_status_migration')
        try:
            db.execute(sql.replace('roster_image_posts', 'roster_image_posts_migrate', 1)
                       .replace("'dropped'", "'dropped','dismissed'"))
            db.execute('INSERT INTO roster_image_posts_migrate SELECT * FROM roster_image_posts')
            db.execute('DROP TABLE roster_image_posts')
            db.execute('ALTER TABLE roster_image_posts_migrate RENAME TO roster_image_posts')
            db.execute('RELEASE image_status_migration')
        except Exception:
            db.execute('ROLLBACK TO image_status_migration')
            db.execute('RELEASE image_status_migration')
            raise


def has_active_image_message(row):
    """A new post must never replace a known, non-dropped message."""
    return bool(row and row['message_id'] and row['status'] != 'dropped')


class RosterImageStore:
    def __init__(self, store):
        self.store = store

    def prepare_test_sequence(self, *, request_id, sid, pool, version, channel, actor, plan):
        """Freeze a test independently of production occurrence/post records."""
        if (not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{24}', request_id)
                or pool not in ('main', 'lazy') or type(version) is not int or version < 1
                or not isinstance(channel, str) or not re.fullmatch(r'\d{15,22}', channel)
                or not isinstance(actor, str) or not actor
                or not isinstance(plan, list) or len(plan) < 2):
            raise ImageConflict('Invalid full-test review')
        if any(not isinstance(step, dict) or step.get('payload', {}).get('allowed_mentions') != {'parse': []}
               for step in plan):
            raise ImageConflict('Every test message must disable mentions')
        frozen = json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False)
        values = (sid, pool, version, channel, actor, frozen)
        with self.store.tx() as db:
            prior = db.execute('SELECT * FROM roster_image_test_sequences WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if tuple(prior[k] for k in ('season_id','pool','target_version','channel_id','actor_id','plan_json')) != values:
                    raise ImageConflict('Test request belongs to a different review')
                return dict(prior)
            publication = db.execute('SELECT version FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,)).fetchone()
            if not publication or publication['version'] != version:
                raise ImageConflict('Published roster changed; review the test again')
            db.execute("INSERT INTO roster_image_test_sequences(request_id,season_id,pool,target_version,channel_id,actor_id,plan_json,status) VALUES(?,?,?,?,?,?,?,'ready')", (request_id, *values))
        return self.test_sequence(request_id)

    def pending_test_sequences(self):
        with self.store.tx() as db:
            return [dict(row) for row in db.execute("SELECT * FROM roster_image_test_sequences WHERE status='ready' ORDER BY created_at")]

    def stop_test_sequence(self, request_id, error):
        with self.store.tx() as db:
            db.execute("UPDATE roster_image_test_sequences SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND status='ready'", (error, request_id))

    def test_sequence(self, request_id):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_test_sequences WHERE request_id=?', (request_id,)).fetchone()
            return dict(row) if row else None

    def claim_test_step(self, request_id):
        """Never replay an in-flight test after a crash or uncertain response."""
        import hashlib
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_test_sequences WHERE request_id=?', (request_id,)).fetchone()
            if not row or row['status'] != 'ready':
                raise ImageConflict('Test is not ready; check its delivery before retrying')
            step = row['next_step']
            plan = json.loads(row['plan_json'])
            if step >= len(plan):
                raise ImageConflict('Test already completed')
            nonce = hashlib.sha256(f'{request_id}:{step}'.encode()).hexdigest()[:24]
            db.execute("INSERT INTO roster_image_test_receipts(request_id,step,nonce,status) VALUES(?,?,?,'sending')", (request_id, step, nonce))
            db.execute("UPDATE roster_image_test_sequences SET status='sending',updated_at=CURRENT_TIMESTAMP WHERE request_id=?", (request_id,))
            return {'step': step, 'nonce': nonce, 'item': plan[step]}

    def finish_test_step(self, request_id, step, *, status, message_id=None, error=None):
        if status not in ('posted', 'failed', 'uncertain'):
            raise ImageConflict('Invalid test delivery result')
        if status == 'posted' and (not isinstance(message_id, str) or not re.fullmatch(r'\d{15,22}', message_id)):
            raise ImageConflict('A confirmed test message is required')
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_test_sequences WHERE request_id=?', (request_id,)).fetchone()
            if not row or row['status'] != 'sending' or row['next_step'] != step:
                raise ImageConflict('Test result no longer matches the active step')
            db.execute("UPDATE roster_image_test_receipts SET status=?,message_id=?,error=? WHERE request_id=? AND step=? AND status='sending'", (status, message_id, error, request_id, step))
            next_step = step + 1 if status == 'posted' else step
            next_status = ('complete' if next_step == len(json.loads(row['plan_json'])) else 'ready') if status == 'posted' else status
            db.execute('UPDATE roster_image_test_sequences SET status=?,next_step=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE request_id=?', (next_status, next_step, error, request_id))
        return self.test_sequence(request_id)

    def prepare_sequence(self, *, sequence_id, sid, pool, cycle, version,
                         generation, channel, actor, plan):
        """Freeze reviewed text/render inputs before queuing the announcement.

        The native bridge will carry sequence_id so an older announcement cannot
        unlock a newly created sequence. This method makes no external calls.
        PNGs are regenerated from the immutable publication, never stored here.
        """
        if (not isinstance(sequence_id, str)
                or not re.fullmatch(r'[a-f0-9]{24}', sequence_id)
                or pool not in ('main', 'lazy')
                or not re.fullmatch(r'20\d\d-(?:0[1-9]|1[0-2])', cycle)
                or not re.fullmatch(r'\d{15,22}', channel)
                or type(version) is not int or version < 1
                or not isinstance(generation, str) or not generation
                or not isinstance(actor, str) or not actor):
            raise ImageConflict('Invalid reviewed sequence')
        # JSON serialization rejects bytes, including accidental PNG payloads.
        frozen = json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False)
        expected = (sid, pool, cycle, version, generation, channel, actor, frozen)
        with self.store.tx() as db:
            prior = db.execute(
                'SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                (sequence_id,),
            ).fetchone()
            if prior:
                actual = tuple(prior[k] for k in (
                    'season_id', 'pool', 'cycle', 'target_version', 'generation',
                    'channel_id', 'actor_id', 'plan_json',
                ))
                if actual != expected:
                    raise ImageConflict('Sequence ID belongs to a different review')
                return dict(prior)
            existing = db.execute(
                'SELECT sequence_id FROM roster_image_sequences '
                'WHERE (season_id=? AND pool=?) OR (cycle=? AND pool=?)',
                (sid, pool, cycle, pool),
            ).fetchone()
            if existing:
                raise ImageConflict('This pool already has a sequence; refresh its status')
            season = db.execute('SELECT status FROM seasons WHERE id=?', (sid,)).fetchone()
            latest = db.execute(
                'SELECT version FROM roster_publications WHERE season_id=? '
                'AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,),
            ).fetchone()
            if not season or season['status'] != 'draft' or not latest or latest['version'] != version:
                raise ImageConflict('Published roster changed; refresh and review')
            db.execute(
                'INSERT INTO roster_image_sequences(sequence_id,season_id,pool,cycle,'
                'target_version,generation,channel_id,actor_id,plan_json) '
                'VALUES(?,?,?,?,?,?,?,?,?)', (sequence_id, *expected),
            )
            return dict(db.execute(
                'SELECT * FROM roster_image_sequences WHERE sequence_id=?', (sequence_id,),
            ).fetchone())

    def pool_sequence(self, sid, pool):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_sequences WHERE season_id=? AND pool=?',
                             (sid, pool)).fetchone()
            return dict(row) if row else None

    def revise_unsent_sequence(self, sequence_id, *, version, generation, channel, actor, plan):
        """Refresh a known-unsent review; callers must first check the native queue.

        Once the announcement is confirmed, its plan and destination never change.
        """
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                             (sequence_id,)).fetchone()
            if not row or row['announcement_message_id'] or row['status'] != 'stopped':
                raise ImageConflict('This sequence has already started; refresh its status')
            latest = db.execute('SELECT version FROM roster_publications WHERE season_id=? '
                                'AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1',
                                (row['season_id'],)).fetchone()
            if not latest or latest['version'] != version:
                raise ImageConflict('Published roster changed; refresh and review')
            db.execute("UPDATE roster_image_sequences SET target_version=?,generation=?,channel_id=?,"
                       "actor_id=?,plan_json=?,status='awaiting_announcement',error=NULL,"
                       'updated_at=CURRENT_TIMESTAMP WHERE sequence_id=?',
                       (version, generation, channel, actor,
                        json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False), sequence_id))
            return dict(db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                                   (sequence_id,)).fetchone())

    def pending_sequences(self):
        with self.store.tx() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM roster_image_sequences WHERE status IN ('awaiting_announcement','ready') "
                'ORDER BY created_at,sequence_id')]

    def stop_sequence(self, sequence_id, error):
        with self.store.tx() as db:
            db.execute("UPDATE roster_image_sequences SET status='stopped',resume_requested=0,error=?,"
                       "updated_at=CURRENT_TIMESTAMP WHERE sequence_id=? AND status!='complete'",
                       (error, sequence_id))

    def sequence(self, sequence_id):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                             (sequence_id,)).fetchone()
            return dict(row) if row else None

    def confirm_sequence_announcement(self, sequence_id, bridge):
        """Unlock only from this job's matching, confirmed native receipt.

        The caller supplies a server-read bridge row, never browser evidence.
        A bare sent-occurrence marker without a destination/message is insufficient.
        """
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                             (sequence_id,)).fetchone()
            if not row:
                raise ImageConflict('Sequence not found')
            receipt = bridge.get('receipt') or {}
            matches = (
                bridge.get('sequence_id') == sequence_id
                and bridge.get('status') == 'sent'
                and bridge.get('cycle') == row['cycle']
                and bridge.get('pool') == row['pool']
                and bridge.get('generation') == row['generation']
                and bridge.get('publication_version') == row['target_version']
                and str(bridge.get('channel_id')) == row['channel_id']
                and str(bridge.get('requested_by')) == row['actor_id']
                and receipt.get('status') == 'sent'
                and receipt.get('occurrence_id') == f"{row['cycle']}|roster|{row['pool']}"
                and str(receipt.get('channel_id')) == row['channel_id']
                and bool(receipt.get('message_id'))
            )
            if not matches:
                raise ImageConflict('Announcement is not confirmed for this sequence')
            message = str(receipt['message_id'])
            if row['announcement_message_id'] and row['announcement_message_id'] != message:
                raise ImageConflict('Announcement receipt changed; check before continuing')
            db.execute(
                "UPDATE roster_image_sequences SET status='ready',announcement_message_id=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE sequence_id=? AND status='awaiting_announcement'",
                (message, sequence_id),
            )
            return dict(db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                                   (sequence_id,)).fetchone())

    def channels(self):
        with self.store.tx() as db:
            return [dict(r) for r in db.execute('SELECT * FROM roster_image_channels ORDER BY pool')]

    def configure(self, pool, channel, name, actor):
        with self.store.tx() as db:
            old = db.execute('SELECT * FROM roster_image_channels WHERE pool=?', (pool,)).fetchone()
            db.execute('INSERT INTO roster_image_channels(pool,channel_id,channel_name,configured_by) VALUES(?,?,?,?) '
                       'ON CONFLICT(pool) DO UPDATE SET channel_id=excluded.channel_id,channel_name=excluded.channel_name,'
                       'configured_by=excluded.configured_by,configured_at=CURRENT_TIMESTAMP', (pool, channel, name, actor))
            new = dict(db.execute('SELECT * FROM roster_image_channels WHERE pool=?', (pool,)).fetchone())
            db.execute('INSERT INTO roster_audit(season_id,actor_id,action,before_json,after_json) VALUES(?,?,?,?,?)',
                       (0, actor, 'roster_image_channel', json.dumps(dict(old)) if old else None, json.dumps(new)))
            return new

    def posts(self, sid):
        with self.store.tx() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM roster_image_posts WHERE season_id=? ORDER BY pool,clan_tag', (sid,))]
            last = db.execute('SELECT version,published_at,withdrawn_at FROM roster_publications WHERE season_id=? ORDER BY version DESC LIMIT 1', (sid,)).fetchone()
            published = db.execute('SELECT version,published_at FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,)).fetchone()
            for row in rows:
                receipt = db.execute('SELECT operation,target_version,payload_json FROM roster_image_requests WHERE request_id=?', (row['request_id'],)).fetchone()
                row['operation'] = receipt['operation'] if receipt else 'post'
                row['target_version'] = receipt['target_version'] if receipt else row['posted_version']
                row['clan_name'] = json.loads(receipt['payload_json']).get('name', row['clan_tag']) if receipt else row['clan_tag']
            return {'posts': rows, 'published': dict(published) if published else None, 'last_publication': dict(last) if last else None}

    def publication(self, sid, version=None):
        """Read immutable publication rows; no draft roster is used for images."""
        with self.store.tx() as db:
            season = db.execute('SELECT * FROM seasons WHERE id=?', (sid,)).fetchone()
            if version is None:
                pub = db.execute('SELECT * FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,)).fetchone()
            else:
                pub = db.execute('SELECT * FROM roster_publications WHERE season_id=? AND version=?', (sid, version)).fetchone()
            if not season or not pub:
                return None
            accounts = [dict(r) for r in db.execute('SELECT * FROM publication_accounts WHERE publication_id=? ORDER BY town_hall DESC,player_name,tag', (pub['id'],))]
            return dict(season), dict(pub), accounts

    def receipt(self, request_id):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_requests WHERE request_id=?', (request_id,)).fetchone()
            return dict(row) if row else None

    def current(self, sid, pool, clan):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_posts WHERE season_id=? AND pool=? AND clan_tag=?', (sid, pool, clan)).fetchone()
            return dict(row) if row else None

    def dismiss(self, sid, pool, clan, version, actor):
        """Acknowledge a removed clan's unknown new post; never call Discord."""
        with self.store.tx() as db:
            latest = db.execute('SELECT * FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,)).fetchone()
            if not latest or latest['version'] != version:
                raise ImageConflict('A newer roster is published. Refresh before checking images.')
            clans = {c['tag']: c for c in json.loads(latest['clans_json'])}
            accounts = db.execute('SELECT pool FROM publication_accounts WHERE publication_id=? AND assigned_clan_tag=?', (latest['id'], clan)).fetchall()
            if any((clans.get(clan, {}).get('pool') or a['pool']) == pool for a in accounts):
                raise ImageConflict('This clan is still in the published pool.')
            row = db.execute('SELECT * FROM roster_image_posts WHERE season_id=? AND pool=? AND clan_tag=?', (sid, pool, clan)).fetchone()
            if row and row['status'] == 'dismissed' and not row['message_id']:
                return dict(row)
            receipt = db.execute('SELECT operation FROM roster_image_requests WHERE request_id=?', (row['request_id'],)).fetchone() if row else None
            if not row or row['status'] != 'uncertain' or row['message_id'] or not receipt or receipt['operation'] != 'post':
                raise ImageConflict('Only an uncertain new post for a removed clan can be marked checked.')
            db.execute("UPDATE roster_image_posts SET status='dismissed',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['id'],))
            updated = dict(db.execute('SELECT * FROM roster_image_posts WHERE id=?', (row['id'],)).fetchone())
            db.execute('INSERT INTO roster_audit(season_id,tag,actor_id,action,before_json,after_json) VALUES(?,?,?,?,?,?)',
                       (sid, clan, actor, 'roster_image_dismiss', json.dumps(dict(row)), json.dumps(updated)))
            return updated

    def retry_sequence_image(self, sequence_id, request_id):
        """Reclaim only a known rejection, preserving the frozen body and nonce."""
        with self.store.tx() as db:
            receipt = db.execute('SELECT * FROM roster_image_requests WHERE request_id=?',
                                 (request_id,)).fetchone()
            if not receipt or receipt['status'] != 'failed':
                raise ImageConflict('Only a confirmed rejection can be retried automatically')
            payload = json.loads(receipt['payload_json'])
            self._check_sequence_image(db, sequence_id, receipt['season_id'], receipt['pool'],
                                       receipt['clan_tag'], receipt['target_version'], request_id,
                                       receipt['channel_id'], payload)
            current = db.execute('SELECT request_id FROM roster_image_posts WHERE season_id=? '
                                 'AND pool=? AND clan_tag=?',
                                 (receipt['season_id'], receipt['pool'], receipt['clan_tag'])).fetchone()
            if not current or current['request_id'] != request_id:
                raise ImageConflict('A newer image action replaced this receipt')
            db.execute("UPDATE roster_image_requests SET status='sending',error=NULL,retry_after=NULL,"
                       'updated_at=CURRENT_TIMESTAMP WHERE request_id=?', (request_id,))
            db.execute("UPDATE roster_image_posts SET status='sending',error=NULL,"
                       'updated_at=CURRENT_TIMESTAMP WHERE request_id=?', (request_id,))
            return dict(db.execute('SELECT * FROM roster_image_requests WHERE request_id=?',
                                   (request_id,)).fetchone())

    def recover_sequence_message(self, sequence_id, request_id, new_request_id, actor):
        """Explicit duplicate-warning confirmation; never called by the worker."""
        if not re.fullmatch(r'[a-f0-9]{24}', new_request_id) or new_request_id == request_id:
            raise ImageConflict('A fresh recovery request is required')
        with self.store.tx() as db:
            job = db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                             (sequence_id,)).fetchone()
            if not job or job['status'] != 'stopped' or not job['announcement_message_id']:
                raise ImageConflict('Sequence changed; refresh before recovering')
            plan = json.loads(job['plan_json'])
            if plan['closing']['request_id'] == request_id:
                receipt = db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?',
                                     (sequence_id,)).fetchone()
                if not receipt or receipt['request_id'] != request_id or receipt['status'] not in ('sending', 'uncertain'):
                    raise ImageConflict('Closing receipt changed; refresh before recovering')
                db.execute('INSERT INTO roster_image_sequence_closing_history VALUES(?,?,?)',
                           (request_id, sequence_id, json.dumps(dict(receipt))))
                db.execute('DELETE FROM roster_image_sequence_closing WHERE sequence_id=?', (sequence_id,))
                plan['closing']['request_id'] = new_request_id
            else:
                item = next((item for item in plan['clans'] if item['request_id'] == request_id), None)
                receipt = db.execute('SELECT * FROM roster_image_requests WHERE request_id=?',
                                     (request_id,)).fetchone()
                current = db.execute('SELECT request_id FROM roster_image_posts WHERE season_id=? '
                                     'AND pool=? AND clan_tag=?',
                                     (job['season_id'], job['pool'], item['tag'] if item else '')).fetchone()
                if (not item or not receipt or receipt['status'] not in ('sending', 'uncertain')
                        or not current or current['request_id'] != request_id or receipt['message_id']):
                    raise ImageConflict('Image receipt changed; refresh before recovering')
                db.execute("UPDATE roster_image_requests SET status='uncertain',updated_at=CURRENT_TIMESTAMP "
                           'WHERE request_id=?', (request_id,))
                db.execute("UPDATE roster_image_posts SET status='uncertain',updated_at=CURRENT_TIMESTAMP "
                           'WHERE request_id=?', (request_id,))
                item['request_id'] = new_request_id
                item['confirm_duplicate'] = True
            db.execute("UPDATE roster_image_sequences SET plan_json=?,actor_id=?,status='ready',"
                       'resume_requested=1,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE sequence_id=?',
                       (json.dumps(plan, sort_keys=True, separators=(',', ':')), actor, sequence_id))
            db.execute('INSERT INTO roster_audit(season_id,actor_id,action,after_json) VALUES(?,?,?,?)',
                       (job['season_id'], actor, 'roster_sequence_duplicate_confirmed',
                        json.dumps({'sequence_id': sequence_id, 'previous_request_id': request_id,
                                    'request_id': new_request_id})))

    def request_sequence_resume(self, sequence_id, actor):
        with self.store.tx() as db:
            changed = db.execute("UPDATE roster_image_sequences SET status='ready',resume_requested=1,"
                                 "actor_id=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE sequence_id=? "
                                 "AND status='stopped' AND announcement_message_id IS NOT NULL",
                                 (actor, sequence_id))
            if not changed.rowcount:
                raise ImageConflict('Sequence changed; refresh before resuming')

    def closing_receipt(self, sequence_id):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?',
                             (sequence_id,)).fetchone()
            return dict(row) if row else None

    def resume_sequence(self, sequence_id):
        with self.store.tx() as db:
            db.execute("UPDATE roster_image_sequences SET status='ready',error=NULL,updated_at=CURRENT_TIMESTAMP "
                       "WHERE sequence_id=? AND status='stopped' AND announcement_message_id IS NOT NULL",
                       (sequence_id,))

    def repost_deleted_closing(self, sequence_id, message_id, actor):
        """After a confirmed 10008, queue one fresh frozen closing message."""
        import hashlib
        with self.store.tx() as db:
            job = db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?', (sequence_id,)).fetchone()
            receipt = db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?', (sequence_id,)).fetchone()
            if (not job or job['status'] != 'complete' or not receipt
                    or receipt['status'] != 'posted' or receipt['message_id'] != message_id):
                raise ImageConflict('Closing message changed; refresh before updating')
            old = dict(receipt)
            old['status'] = 'deleted_confirmed'
            db.execute('INSERT INTO roster_image_sequence_closing_history VALUES(?,?,?)',
                       (receipt['request_id'], sequence_id, json.dumps(old)))
            plan = json.loads(job['plan_json'])
            plan['closing']['request_id'] = hashlib.sha256((receipt['request_id'] + ':deleted-repost').encode()).hexdigest()[:24]
            db.execute('DELETE FROM roster_image_sequence_closing WHERE sequence_id=?', (sequence_id,))
            db.execute("UPDATE roster_image_sequences SET status='ready',plan_json=?,actor_id=?,error=NULL,resume_requested=1,updated_at=CURRENT_TIMESTAMP WHERE sequence_id=?",
                       (json.dumps(plan, sort_keys=True), str(actor), sequence_id))
            return dict(db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?', (sequence_id,)).fetchone())

    def claim_sequence_closing(self, sequence_id, *, retry_failed=False):
        """Claim the final note only after all images are durably confirmed."""
        with self.store.tx() as db:
            prior = db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?',
                               (sequence_id,)).fetchone()
            if prior:
                if retry_failed and prior['status'] == 'failed':
                    db.execute("UPDATE roster_image_sequence_closing SET status='sending',error=NULL,"
                               'retry_after=NULL,updated_at=CURRENT_TIMESTAMP WHERE sequence_id=?',
                               (sequence_id,))
                    return dict(db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?',
                                           (sequence_id,)).fetchone()), True
                return dict(prior), False
            sequence = db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                                  (sequence_id,)).fetchone()
            if (not sequence or sequence['status'] != 'ready'
                    or not sequence['announcement_message_id']):
                raise ImageConflict('Announcement sequence is not ready for the closing note')
            plan = json.loads(sequence['plan_json'])
            for item in plan.get('clans', []):
                receipt = db.execute('SELECT * FROM roster_image_requests WHERE request_id=?',
                                     (item.get('request_id'),)).fetchone()
                if (not receipt or receipt['status'] != 'posted' or not receipt['message_id']
                        or (receipt['season_id'], receipt['pool'], receipt['clan_tag'],
                            receipt['target_version'], receipt['channel_id'])
                        != (sequence['season_id'], sequence['pool'], item.get('tag'),
                            sequence['target_version'], sequence['channel_id'])):
                    raise ImageConflict('A clan image is not confirmed; stop before the closing note')
            closing = plan.get('closing') or {}
            if (not re.fullmatch(r'[a-f0-9]{24}', closing.get('request_id', ''))
                    or not isinstance(closing.get('payload'), dict)
                    or closing['payload'].get('allowed_mentions') != {'parse': []}):
                raise ImageConflict('Closing note is missing from the reviewed sequence')
            db.execute(
                'INSERT INTO roster_image_sequence_closing(sequence_id,request_id,channel_id,'
                "payload_json,status) VALUES(?,?,?,?,'sending')",
                (sequence_id, closing['request_id'], sequence['channel_id'],
                 json.dumps(closing['payload'], sort_keys=True)),
            )
            return dict(db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?',
                                   (sequence_id,)).fetchone()), True

    def finish_sequence_closing(self, sequence_id, *, status, message=None, error=None, retry_after=None, expected_request_id=None):
        if status not in ('posted', 'failed', 'uncertain'):
            raise ImageConflict('Invalid closing-note result')
        if status == 'posted' and not re.fullmatch(r'\d{15,22}', str(message or '')):
            raise ImageConflict('A confirmed closing message ID is required')
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?',
                             (sequence_id,)).fetchone()
            if expected_request_id is not None and (not row or row['request_id'] != expected_request_id):
                archived = db.execute('SELECT receipt_json FROM roster_image_sequence_closing_history '
                                      'WHERE request_id=? AND sequence_id=?',
                                      (expected_request_id, sequence_id)).fetchone()
                if archived:
                    return json.loads(archived['receipt_json'])
                raise ImageConflict('Closing attempt changed; do not overwrite its receipt')
            if not row:
                raise ImageConflict('Closing note has not been claimed')
            if row['status'] != 'sending':
                return dict(row)
            if status == 'posted' and any(
                json.loads(item['receipt_json']).get('status') == 'deleted_confirmed'
                for item in db.execute('SELECT receipt_json FROM roster_image_sequence_closing_history WHERE sequence_id=?', (sequence_id,))
            ):
                error = 'Reposted (old message was deleted)'
            db.execute('UPDATE roster_image_sequence_closing SET status=?,message_id=?,error=?,'
                       'retry_after=?,updated_at=CURRENT_TIMESTAMP WHERE sequence_id=?',
                       (status, str(message) if message else None, error, retry_after, sequence_id))
            retry = status == 'failed' and retry_after is not None
            db.execute('UPDATE roster_image_sequences SET status=?,resume_requested=?,'
                       'updated_at=CURRENT_TIMESTAMP WHERE sequence_id=?',
                       ('complete' if status == 'posted' else 'ready' if retry else 'stopped',
                        int(retry), sequence_id))
            return dict(db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?',
                                   (sequence_id,)).fetchone())

    def _check_sequence_image(self, db, sequence_id, sid, pool, clan, version,
                              request_id, channel, payload):
        """Check ordering and destination inside the image-receipt transaction."""
        sequence = db.execute('SELECT * FROM roster_image_sequences WHERE sequence_id=?',
                              (sequence_id,)).fetchone()
        if (not sequence or sequence['status'] != 'ready'
                or not sequence['announcement_message_id']
                or (sequence['season_id'], sequence['pool'], sequence['target_version'],
                    sequence['channel_id']) != (sid, pool, version, channel)):
            raise ImageConflict('Announcement sequence is not ready for image delivery')
        if payload.get('payload', {}).get('allowed_mentions') != {'parse': []}:
            raise ImageConflict('Sequence image messages must not allow mentions')
        items = json.loads(sequence['plan_json']).get('clans', [])
        for item in items:
            if item.get('tag') == clan:
                if item.get('request_id') != request_id or item.get('frozen') != payload:
                    raise ImageConflict('Image does not match the frozen sequence review')
                return
            receipt = db.execute('SELECT * FROM roster_image_requests WHERE request_id=?',
                                 (item.get('request_id'),)).fetchone()
            if (not receipt or receipt['status'] != 'posted' or not receipt['message_id']
                    or (receipt['season_id'], receipt['pool'], receipt['clan_tag'],
                        receipt['target_version'], receipt['channel_id'])
                    != (sid, pool, item.get('tag'), version, channel)):
                raise ImageConflict('Previous clan is not confirmed; stop and check its status')
        raise ImageConflict('Clan is not part of the reviewed sequence')

    def claim(self, sid, pool, clan, version, request_id, operation, channel, message, payload, actor, *, confirm_duplicate=False, sequence_id=None, announcement_channel=None):
        """Atomic durable intent; no external call is made with the transaction held."""
        with self.store.tx() as db:
            prior = db.execute('SELECT * FROM roster_image_requests WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if (prior['season_id'], prior['pool'], prior['clan_tag'], prior['target_version'], prior['operation']) != (sid, pool, clan, version, operation):
                    raise ImageConflict('Request ID belongs to a different action')
                return dict(prior), False
            latest = db.execute('SELECT version FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,)).fetchone()
            if not latest:
                raise ImageConflict('Publish the roster before posting images')
            if latest['version'] != version and sequence_id is None:
                raise ImageConflict('A newer roster is published. Refresh before posting images.')
            old = db.execute('SELECT * FROM roster_image_posts WHERE season_id=? AND pool=? AND clan_tag=?', (sid, pool, clan)).fetchone()
            if old and old['status'] == 'sending':
                # A crashed worker must never cause an automatic duplicate delivery.
                active = db.execute("SELECT status FROM roster_image_requests WHERE request_id=? AND updated_at > datetime('now','-60 seconds')", (old['request_id'],)).fetchone()
                if active:
                    raise ImageConflict('Another post for this clan is in progress')
                db.execute("UPDATE roster_image_posts SET status='uncertain',error='Delivery interrupted; check Discord',updated_at=CURRENT_TIMESTAMP WHERE id=?", (old['id'],))
                db.execute("UPDATE roster_image_requests SET status='uncertain',error='Delivery interrupted; check Discord',updated_at=CURRENT_TIMESTAMP WHERE request_id=?", (old['request_id'],))
                return {'status': 'uncertain', 'error': 'Delivery interrupted; check Discord'}, False
            if operation == 'post' and has_active_image_message(old):
                raise ImageConflict('This clan already has a message · use Update')
            if operation == 'post' and old and old['status'] == 'uncertain' and not confirm_duplicate:
                raise ImageConflict('This clan may already have posted · confirm Post again anyway')
            if old and old['status'] in ('posted', 'dropped') and old['posted_version'] == version:
                if (operation == 'drop') == (old['status'] == 'dropped'):
                    return dict(old), False
            # Recheck the saved destination after asynchronous render/validation.
            if operation == 'post' and sequence_id is not None:
                self._check_sequence_image(db, sequence_id, sid, pool, clan, version,
                                           request_id, channel, payload)
            elif operation == 'post' and announcement_channel is not None:
                if announcement_channel != channel:
                    raise ImageConflict('The announcement destination changed; review again')
                sequence = db.execute('SELECT status FROM roster_image_sequences WHERE season_id=? AND pool=?', (sid, pool)).fetchone()
                if sequence and sequence['status'] != 'complete':
                    raise ImageConflict('Finish the announcement image sequence first')
            elif operation == 'post':
                selected = db.execute('SELECT channel_id FROM roster_image_channels WHERE pool=?', (pool,)).fetchone()
                if not selected or selected['channel_id'] != channel:
                    raise ImageConflict('The image channel changed. Review the destination again.')
            elif not old or old['message_id'] != message or old['channel_id'] != channel:
                raise ImageConflict('The posted message changed. Refresh before editing.')
            db.execute('INSERT INTO roster_image_requests(request_id,operation,season_id,pool,clan_tag,target_version,channel_id,message_id,payload_json,status,actor_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (request_id, operation, sid, pool, clan, version, channel, message, json.dumps(payload), 'sending', actor))
            db.execute('INSERT INTO roster_image_posts(season_id,pool,clan_tag,channel_id,message_id,status,request_id,posted_by) VALUES(?,?,?,?,?,?,?,?) '
                       'ON CONFLICT(season_id,pool,clan_tag) DO UPDATE SET channel_id=excluded.channel_id,message_id=excluded.message_id,status=excluded.status,request_id=excluded.request_id,error=NULL,posted_by=excluded.posted_by,updated_at=CURRENT_TIMESTAMP',
                       (sid, pool, clan, channel, message, 'sending', request_id, actor))
            return dict(db.execute('SELECT * FROM roster_image_requests WHERE request_id=?', (request_id,)).fetchone()), True

    def archive_deleted_sequence(self, sid, pool, deleted_message_id, actor):
        """Retain the old sequence/mappings before an explicit fresh resend.

        No Discord messages or individual delivery receipts are deleted. Replay
        of the same confirmed announcement deletion cannot erase its replacement.
        """
        if pool not in ('main', 'lazy') or not re.fullmatch(r'\d{15,22}', str(deleted_message_id)):
            raise ImageConflict('A confirmed deleted announcement receipt is required')
        with self.store.tx() as db:
            previous = db.execute(
                'SELECT 1 FROM roster_image_sequence_archives WHERE season_id=? AND pool=? AND deleted_message_id=?',
                (sid, pool, str(deleted_message_id)),
            ).fetchone()
            if previous:
                return False
            sequence = db.execute('SELECT * FROM roster_image_sequences WHERE season_id=? AND pool=?', (sid, pool)).fetchone()
            posts = db.execute('SELECT * FROM roster_image_posts WHERE season_id=? AND pool=?', (sid, pool)).fetchall()
            if any(post['status'] in ('sending', 'uncertain') for post in posts):
                raise ImageConflict('Check unfinished image deliveries before resending the announcement')
            closing = None
            if sequence:
                if (sequence['announcement_message_id'] != str(deleted_message_id)
                        or sequence['status'] not in ('complete', 'stopped')):
                    raise ImageConflict('The previous image sequence must finish or stop before resending')
                closing = db.execute('SELECT * FROM roster_image_sequence_closing WHERE sequence_id=?', (sequence['sequence_id'],)).fetchone()
                if closing and closing['status'] in ('sending', 'uncertain'):
                    raise ImageConflict('Check the unfinished closing message before resending')
            db.execute('INSERT INTO roster_image_sequence_archives(season_id,pool,deleted_message_id,sequence_json,closing_json,posts_json,actor_id) VALUES(?,?,?,?,?,?,?)',
                       (sid, pool, str(deleted_message_id), json.dumps(dict(sequence)) if sequence else None,
                        json.dumps(dict(closing)) if closing else None, json.dumps([dict(post) for post in posts]), str(actor)))
            if sequence:
                db.execute('DELETE FROM roster_image_sequence_closing WHERE sequence_id=?', (sequence['sequence_id'],))
                db.execute('DELETE FROM roster_image_sequences WHERE sequence_id=?', (sequence['sequence_id'],))
            db.execute('DELETE FROM roster_image_posts WHERE season_id=? AND pool=?', (sid, pool))
            return True

    def repost_deleted(self, receipt):
        """Convert a confirmed-deleted edit into a distinct durable NEW attempt."""
        import hashlib
        replacement = hashlib.sha256((receipt['request_id'] + ':deleted-repost').encode()).hexdigest()[:24]
        with self.store.tx() as db:
            current = db.execute('SELECT * FROM roster_image_requests WHERE request_id=?', (receipt['request_id'],)).fetchone()
            post = db.execute('SELECT * FROM roster_image_posts WHERE request_id=?', (receipt['request_id'],)).fetchone()
            if not current or not post or current['status'] != 'sending' or current['operation'] != 'update' or not current['message_id']:
                raise ImageConflict('The edited message changed; refresh before reposting')
            db.execute("UPDATE roster_image_requests SET status='deleted_confirmed',replacement_request_id=?,updated_at=CURRENT_TIMESTAMP WHERE request_id=?", (replacement, receipt['request_id']))
            db.execute("INSERT INTO roster_image_requests(request_id,operation,season_id,pool,clan_tag,target_version,channel_id,payload_json,status,actor_id) VALUES(?,'post',?,?,?,?,?,?,'sending',?)",
                       (replacement, current['season_id'], current['pool'], current['clan_tag'], current['target_version'], current['channel_id'], current['payload_json'], current['actor_id']))
            db.execute("UPDATE roster_image_posts SET request_id=?,message_id=NULL,status='sending',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE request_id=?", (replacement, receipt['request_id']))
            db.execute('INSERT INTO roster_audit(season_id,tag,actor_id,action,after_json) VALUES(?,?,?,?,?)',
                       (current['season_id'], current['clan_tag'], current['actor_id'], 'roster_image_deleted', json.dumps({'message_id': current['message_id'], 'request_id': receipt['request_id'], 'replacement_request_id': replacement})))
            return dict(db.execute('SELECT * FROM roster_image_requests WHERE request_id=?', (replacement,)).fetchone())

    def finish(self, receipt, status, message=None, error=None, retry_after=None, *, clear_message=False, sequence_id=None):
        with self.store.tx() as db:
            db.execute('UPDATE roster_image_requests SET status=?,message_id=COALESCE(?,message_id),error=?,retry_after=?,updated_at=CURRENT_TIMESTAMP WHERE request_id=?',
                       (status, message, error, retry_after, receipt['request_id']))
            if sequence_id is not None and status in ('failed', 'uncertain'):
                retry = status == 'failed' and retry_after is not None
                db.execute('UPDATE roster_image_sequences SET status=?,resume_requested=?,error=?,'
                           'updated_at=CURRENT_TIMESTAMP WHERE sequence_id=?',
                           ('ready' if retry else 'stopped', int(retry), error, sequence_id))
            successful = status in ('posted', 'dropped')
            db.execute('UPDATE roster_image_posts SET status=?,message_id=CASE WHEN ? THEN NULL ELSE COALESCE(?,message_id) END,error=?,posted_version=CASE WHEN ? THEN ? ELSE posted_version END,posted_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE posted_at END,updated_at=CURRENT_TIMESTAMP WHERE request_id=?',
                       (status, clear_message, message, error, successful, receipt['target_version'], successful, receipt['request_id']))
            details = {k: receipt[k] for k in ('pool', 'clan_tag', 'target_version', 'request_id')}
            details.update(status=status, message_id=message or receipt['message_id'], error=error)
            db.execute('INSERT INTO roster_audit(season_id,tag,actor_id,action,after_json) VALUES(?,?,?,?,?)',
                       (receipt['season_id'], receipt['clan_tag'], receipt['actor_id'], 'roster_image_' + receipt['operation'], json.dumps(details)))
            return dict(db.execute('SELECT * FROM roster_image_posts WHERE request_id=?', (receipt['request_id'],)).fetchone())


class ImageConflict(Exception):
    """Durable concurrency or publication conflict; no Discord request permitted."""

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
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
 announcement_message_id TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(season_id,pool), UNIQUE(cycle,pool)
);

"""


def migrate(db):
    """Extend the existing CHECK constraint without changing saved delivery data."""
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

    def claim(self, sid, pool, clan, version, request_id, operation, channel, message, payload, actor, *, confirm_duplicate=False):
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
            if latest['version'] != version:
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
            if operation == 'post':
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

    def finish(self, receipt, status, message=None, error=None, retry_after=None, *, clear_message=False):
        with self.store.tx() as db:
            db.execute('UPDATE roster_image_requests SET status=?,message_id=COALESCE(?,message_id),error=?,retry_after=?,updated_at=CURRENT_TIMESTAMP WHERE request_id=?',
                       (status, message, error, retry_after, receipt['request_id']))
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

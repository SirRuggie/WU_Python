"""SQLite owner for saved draws, review decisions and announcement receipts.

Uses the dashboard's existing transaction boundary; no network work occurs inside
a transaction. A draw is unique for a CWL month, pool and hosting clan, even when
staff create another dashboard season for the same month.
"""

import hashlib
import json
from datetime import datetime, timezone

from utils.cwl_bonus_raffle import announcement_pages, draw_accounts, eligibility, lazy_eligibility, LAZY_REVIEW_FLAGS

DEFAULT_REPRESENTATIVE_ROLE_ID = "769130325460254740"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bonus_raffle_policy (
 season_id INTEGER NOT NULL REFERENCES seasons(id), pool TEXT NOT NULL,
 minimum INTEGER NOT NULL CHECK(minimum BETWEEN 0 AND 7),
 PRIMARY KEY(season_id,pool)
);
CREATE TABLE IF NOT EXISTS bonus_raffle_settings (
 season_id INTEGER PRIMARY KEY REFERENCES seasons(id),
 representative_role_id TEXT NOT NULL,
 updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bonus_raffle_settings_audit (
 id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
 actor_id TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bonus_raffle_account_reviews (
 season_id INTEGER NOT NULL REFERENCES seasons(id), tag TEXT NOT NULL,
 flags_json TEXT NOT NULL DEFAULT '[]', override_reason TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(season_id,tag)
);
CREATE TABLE IF NOT EXISTS bonus_raffle_review_audit (
 id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
 tag TEXT NOT NULL, actor_id TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bonus_raffle_review_audit_season ON bonus_raffle_review_audit(season_id,id);
CREATE TABLE IF NOT EXISTS bonus_raffle_candidate_review_links (
 season_id INTEGER NOT NULL REFERENCES seasons(id), tag TEXT NOT NULL,
 override_reason TEXT NOT NULL, PRIMARY KEY(season_id,tag)
);
CREATE TABLE IF NOT EXISTS bonus_raffle_manual_candidates (
 season_id INTEGER NOT NULL REFERENCES seasons(id), tag TEXT NOT NULL,
 player_name TEXT NOT NULL, town_hall INTEGER NOT NULL, user_id TEXT,
 clan_tag TEXT NOT NULL, clan_name TEXT NOT NULL, reason TEXT NOT NULL,
 created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_by TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(season_id,tag)
);
CREATE TABLE IF NOT EXISTS bonus_raffle_manual_candidate_audit (
 id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
 tag TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL,
 before_json TEXT, after_json TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bonus_raffle_candidate_audit_season ON bonus_raffle_manual_candidate_audit(season_id,id);
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

    def settings(self):
        row = self.db.execute('SELECT representative_role_id,updated_by,updated_at FROM bonus_raffle_settings WHERE season_id=?', (self.sid,)).fetchone()
        return {'representative_role_id': row['representative_role_id'] if row else DEFAULT_REPRESENTATIVE_ROLE_ID,
                'updated_by': row['updated_by'] if row else None, 'updated_at': row['updated_at'] if row else None}

    def save_settings(self, role_id, actor):
        if not isinstance(role_id, str) or not role_id.isdigit() or not 15 <= len(role_id) <= 22:
            raise RaffleConflict('Choose a valid Discord role ID')
        before = self.settings()
        after = {'representative_role_id': role_id}
        if before['representative_role_id'] == role_id:
            return before
        stamp = now()
        self.db.execute('INSERT INTO bonus_raffle_settings(season_id,representative_role_id,updated_by,updated_at) VALUES (?,?,?,?) '
                        'ON CONFLICT(season_id) DO UPDATE SET representative_role_id=excluded.representative_role_id,updated_by=excluded.updated_by,updated_at=excluded.updated_at',
                        (self.sid, role_id, actor, stamp))
        self.db.execute('INSERT INTO bonus_raffle_settings_audit(season_id,actor_id,before_json,after_json,created_at) VALUES (?,?,?,?,?)',
                        (self.sid, actor, json.dumps({'representative_role_id': before['representative_role_id']}), json.dumps(after), stamp))
        return {**after, 'updated_by': actor, 'updated_at': stamp}

    def account_reviews(self):
        result = {}
        for row in self.db.execute('SELECT * FROM bonus_raffle_account_reviews WHERE season_id=?', (self.sid,)):
            result[row['tag']] = self._review_view(row)
        return result

    @staticmethod
    def _review_view(row=None):
        return {'flags': json.loads(row['flags_json']) if row else [],
                'override_reason': row['override_reason'] if row else '',
                'revision': row['revision'] if row else 0,
                'updated_by': row['updated_by'] if row else None,
                'updated_at': row['updated_at'] if row else None}

    def save_account_review(self, tag, flags, override_reason, actor, expected_revision=None):
        if not isinstance(tag, str) or not tag.startswith('#') or not 3 <= len(tag) <= 16:
            raise RaffleConflict('Choose a verified player tag')
        if not isinstance(flags, (list, tuple, set)) or any(flag not in LAZY_REVIEW_FLAGS for flag in flags):
            raise RaffleConflict('Choose valid Lazy eligibility flags')
        flags = sorted(set(flags))
        if not isinstance(override_reason, str) or len(override_reason.strip()) > 500:
            raise RaffleConflict('Override reason must be 500 characters or fewer')
        override_reason = override_reason.strip()
        prior = self.db.execute('SELECT * FROM bonus_raffle_account_reviews WHERE season_id=? AND tag=?', (self.sid, tag)).fetchone()
        old = self._review_view(prior)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != old['revision']):
            raise RaffleConflict('Eligibility review changed. Refresh and try again')
        if old['flags'] == flags and old['override_reason'] == override_reason:
            return old
        stamp = now()
        revision = old['revision'] + 1
        self.db.execute('INSERT INTO bonus_raffle_account_reviews(season_id,tag,flags_json,override_reason,revision,updated_by,updated_at) VALUES (?,?,?,?,?,?,?) '
                        'ON CONFLICT(season_id,tag) DO UPDATE SET flags_json=excluded.flags_json,override_reason=excluded.override_reason,revision=excluded.revision,updated_by=excluded.updated_by,updated_at=excluded.updated_at',
                        (self.sid, tag, json.dumps(flags), override_reason, revision, actor, stamp))
        after = {'flags': flags, 'override_reason': override_reason}
        self.db.execute('INSERT INTO bonus_raffle_review_audit(season_id,tag,actor_id,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)',
                        (self.sid, tag, actor, json.dumps({'flags': old['flags'], 'override_reason': old['override_reason']}), json.dumps(after), stamp))
        # An explicit account-review edit takes ownership of its override.
        self.db.execute('DELETE FROM bonus_raffle_candidate_review_links WHERE season_id=? AND tag=?', (self.sid, tag))
        return {**after, 'revision': revision, 'updated_by': actor, 'updated_at': stamp}

    def add_manual_candidate(self, identity, clan_tag, reason, actor):
        """Add a verified non-signup Lazy account without changing its assignment."""
        if not isinstance(identity, dict):
            raise RaffleConflict('Choose a verified player identity')
        tag, name, th = identity.get('tag'), identity.get('player_name'), identity.get('town_hall')
        user_id = identity.get('user_id')
        if not isinstance(tag, str) or not tag.startswith('#') or not 3 <= len(tag) <= 16:
            raise RaffleConflict('Choose a verified player tag')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise RaffleConflict('Choose a verified in-game name')
        if type(th) is not int or not 1 <= th <= 18:
            raise RaffleConflict('Choose a verified Town Hall level')
        if user_id is not None and (not isinstance(user_id, str) or not user_id.isdigit() or not 15 <= len(user_id) <= 22):
            raise RaffleConflict('Linked Discord identity is invalid')
        if not isinstance(clan_tag, str) or not clan_tag.startswith('#') or not 3 <= len(clan_tag) <= 16:
            raise RaffleConflict('Choose an active Lazy hosting clan')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
            raise RaffleConflict('Explain why this account is being added (up to 500 characters)')
        reason = reason.strip()
        host = self.db.execute('SELECT c.name FROM clans c JOIN lineup l ON l.tag=c.tag WHERE l.season_id=? AND c.tag=? AND c.archived=0 AND c.pool=?', (self.sid, clan_tag, 'lazy')).fetchone()
        if not host:
            raise RaffleConflict('Choose an active Lazy hosting clan in this season')
        signup = self.db.execute('SELECT s.pool,r.assigned_clan_tag FROM signups s LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag WHERE s.season_id=? AND s.tag=?', (self.sid, tag)).fetchone()
        if signup:
            if signup['pool'] != 'lazy' or signup['assigned_clan_tag'] != clan_tag:
                raise RaffleConflict('This signup is assigned elsewhere. Reconcile its roster assignment before adding it')
            raise RaffleConflict('This account is already signed up and assigned to this clan')
        old_row = self.db.execute('SELECT * FROM bonus_raffle_manual_candidates WHERE season_id=? AND tag=?', (self.sid, tag)).fetchone()
        if old_row and old_row['clan_tag'] != clan_tag:
            raise RaffleConflict('This manual account is already assigned to another hosting clan')
        stamp = now()
        if old_row:
            before = {key: old_row[key] for key in ('tag','player_name','town_hall','user_id','clan_tag','clan_name','reason')}
            after = {**before, 'player_name': name.strip(), 'town_hall': th, 'user_id': user_id,
                     'clan_name': host['name'], 'reason': reason}
            if before == after:
                return {'tag': tag, 'revision': old_row['revision'], 'created_by': old_row['created_by'], 'created_at': old_row['created_at']}
            self.db.execute('UPDATE bonus_raffle_manual_candidates SET player_name=?,town_hall=?,user_id=?,clan_name=?,reason=?,updated_by=?,updated_at=?,revision=revision+1 WHERE season_id=? AND tag=?',
                            (after['player_name'], th, user_id, host['name'], reason, actor, stamp, self.sid, tag))
            action = 'updated'
            created_by, created_at, revision = old_row['created_by'], old_row['created_at'], old_row['revision'] + 1
        else:
            before = None
            after = {'tag': tag, 'player_name': name.strip(), 'town_hall': th, 'user_id': user_id,
                     'clan_tag': clan_tag, 'clan_name': host['name'], 'reason': reason}
            self.db.execute('INSERT INTO bonus_raffle_manual_candidates(season_id,tag,player_name,town_hall,user_id,clan_tag,clan_name,reason,created_by,created_at,updated_by,updated_at,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)',
                            (self.sid, tag, after['player_name'], th, user_id, clan_tag, host['name'], reason, actor, stamp, actor, stamp))
            action, created_by, created_at, revision = 'added', actor, stamp, 1
        self.db.execute('INSERT INTO bonus_raffle_manual_candidate_audit(season_id,tag,actor_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?,?)',
                        (self.sid, tag, actor, action, json.dumps(before, sort_keys=True) if before else None, json.dumps(after, sort_keys=True), stamp))
        saved_review = self.account_reviews().get(tag, self._review_view())
        linked = self.db.execute('SELECT override_reason FROM bonus_raffle_candidate_review_links WHERE season_id=? AND tag=?', (self.sid, tag)).fetchone()
        generated_review = bool(linked and saved_review['override_reason'] == linked['override_reason'])
        if not saved_review['override_reason'] or (generated_review and saved_review['override_reason'] != reason):
            created_review = self.save_account_review(tag, saved_review['flags'], reason, actor, saved_review['revision'])
            self.db.execute('INSERT INTO bonus_raffle_candidate_review_links(season_id,tag,override_reason) VALUES (?,?,?) ON CONFLICT(season_id,tag) DO UPDATE SET override_reason=excluded.override_reason',
                            (self.sid, tag, created_review['override_reason']))
        return {'tag': tag, 'revision': revision, 'created_by': created_by, 'created_at': created_at,
                'updated_by': actor, 'updated_at': stamp, 'clan_tag': clan_tag, 'reason': reason}

    def remove_manual_candidate(self, tag, actor):
        row = self.db.execute('SELECT * FROM bonus_raffle_manual_candidates WHERE season_id=? AND tag=?', (self.sid, tag)).fetchone()
        if not row:
            raise RaffleConflict('Manual candidate not found')
        before = {key: row[key] for key in ('tag','player_name','town_hall','user_id','clan_tag','clan_name','reason')}
        linked_review = self.db.execute('SELECT override_reason FROM bonus_raffle_candidate_review_links WHERE season_id=? AND tag=?', (self.sid, tag)).fetchone()
        if linked_review:
            review = self.account_reviews().get(tag, self._review_view())
            if review['override_reason'] == linked_review['override_reason']:
                self.save_account_review(tag, review['flags'], '', actor, review['revision'])
            self.db.execute('DELETE FROM bonus_raffle_candidate_review_links WHERE season_id=? AND tag=?', (self.sid, tag))
        stamp = now()
        self.db.execute('DELETE FROM bonus_raffle_manual_candidates WHERE season_id=? AND tag=?', (self.sid, tag))
        self.db.execute('INSERT INTO bonus_raffle_manual_candidate_audit(season_id,tag,actor_id,action,before_json,after_json,created_at) VALUES (?,?,?, ?,?,NULL,?)',
                        (self.sid, tag, actor, 'removed', json.dumps(before, sort_keys=True), stamp))
        return {'tag': tag, 'removed_by': actor, 'removed_at': stamp}

    @staticmethod
    def _prior_cycles(cycle):
        try:
            current = datetime.strptime(cycle, '%Y-%m')
        except (TypeError, ValueError):
            return []
        result = []
        year, month = current.year, current.month
        for _ in range(3):
            month -= 1
            if month == 0:
                month, year = 12, year - 1
            result.append(f'{year:04d}-{month:02d}')
        return result

    def _has_three_cycle_cooldown(self, tag, cycle):
        prior = self._prior_cycles(cycle)
        if len(prior) != 3:
            return False
        placeholders = ','.join('?' for _ in prior)
        rows = self.db.execute(
            f'SELECT DISTINCT cycle FROM bonus_confirmations WHERE tag=? AND cycle IN ({placeholders}) AND voided_at IS NULL',
            (tag, *prior),
        )
        return {row['cycle'] for row in rows} == set(prior)

    def enrich_view(self, view):
        """Attach Lazy review state and persisted manual candidates to the preview view."""
        accounts = list(view.get('accounts') or [])
        by_tag = {account['tag']: account for account in accounts}
        reviews = self.account_reviews()
        cycle = view.get('cycle')
        active_hosts = {row['tag'] for row in self.db.execute(
            "SELECT c.tag FROM clans c JOIN lineup l ON l.tag=c.tag WHERE l.season_id=? AND c.archived=0 AND c.pool='lazy'",
            (self.sid,),
        )}
        for account in accounts:
            account['three_cycle_cooldown'] = self._has_three_cycle_cooldown(account['tag'], cycle)
            account['host_valid'] = account.get('assigned_clan_tag') in active_hosts
        for account in accounts:
            # Preserve role evidence and candidate-scoped override annotations if
            # the parent already enriched this view before calling preview.
            account['bonus_review'] = {**self._review_view(), **(account.get('bonus_review') or {}), **reviews.get(account['tag'], {})}
        for row in self.db.execute('SELECT * FROM bonus_raffle_manual_candidates WHERE season_id=?', (self.sid,)):
            tag = row['tag']
            current = by_tag.get(tag)
            if current:
                if current.get('pool') != 'lazy' or current.get('assigned_clan_tag') != row['clan_tag']:
                    conflicts = view.setdefault('manual_candidate_conflicts', [])
                    conflict = {'tag': tag, 'clan_tag': row['clan_tag'], 'reason': 'Signup is now assigned to a different pool or clan'}
                    if conflict not in conflicts:
                        conflicts.append(conflict)
                continue
            host_valid = row['clan_tag'] in active_hosts
            if not host_valid:
                conflicts = view.setdefault('manual_candidate_conflicts', [])
                conflict = {'tag': tag, 'clan_tag': row['clan_tag'], 'reason': 'Manual hosting clan is no longer an active Lazy clan in this season'}
                if conflict not in conflicts:
                    conflicts.append(conflict)
            source = self.db.execute('SELECT attacks,stars,status,complete,checked_at,warning,roster_token FROM participation_source_results WHERE season_id=? AND cycle=? AND tag=?', (self.sid, cycle, tag)).fetchone() if cycle else None
            identity = {'tag': tag, 'user_id': row['user_id'], 'pool': 'lazy', 'assigned_clan_tag': row['clan_tag']}
            from utils.cwl_working_roster import account_token
            if source and source['roster_token'] == account_token(identity):
                attacks, stars, status, complete, checked_at, warning = source['attacks'], source['stars'], source['status'], bool(source['complete']), source['checked_at'], source['warning']
            else:
                attacks = stars = checked_at = warning = None
                status, complete = 'unavailable', False
            manual = {
                'tag': tag, 'user_id': row['user_id'], 'player_name': row['player_name'], 'town_hall': row['town_hall'],
                'pool': 'lazy', 'assigned_clan_tag': row['clan_tag'], 'assigned_clan_name': row['clan_name'],
                'attacks': attacks, 'stars': stars, 'source_status': status, 'source_complete': complete,
                'checked_at': checked_at, 'warning': warning, 'roster_changed': False,
                'in_current_roster': False, 'manual_candidate': True, 'manual_candidate_reason': row['reason'],
                'tag_valid': True, 'source': 'manual', 'candidate_source': 'manual', 'already_confirmed_this_cycle': any(c.get('tag') == tag for c in view.get('cycle_confirmed', [])),
                'season_rounds': None, 'three_cycle_cooldown': self._has_three_cycle_cooldown(tag, cycle),
                'manual_host_valid': host_valid, 'host_valid': host_valid, 'is_representative': False, 'representative_status': 'unlinked', 'multiplier': 1,
                'bonus_review': reviews.get(tag, self._review_view()),
            }
            accounts.append(manual)
            by_tag[tag] = manual
        view['accounts'] = accounts
        view['bonus_reviews'] = reviews
        view['lazy_hosts'] = [dict(row) for row in self.db.execute('SELECT c.tag,c.name FROM clans c JOIN lineup l ON l.tag=c.tag WHERE l.season_id=? AND c.archived=0 AND c.pool=? ORDER BY c.name COLLATE NOCASE,c.tag', (self.sid, 'lazy'))]
        current_clans = {row.get('tag') for row in view.get('clans', [])}
        for candidate in self.db.execute(
            "SELECT DISTINCT c.tag,c.name FROM bonus_raffle_manual_candidates m JOIN clans c ON c.tag=m.clan_tag JOIN lineup l ON l.tag=c.tag AND l.season_id=m.season_id WHERE m.season_id=? AND c.archived=0 AND c.pool='lazy'",
            (self.sid,),
        ):
            if candidate['tag'] not in current_clans:
                view.setdefault('clans', []).append({'tag': candidate['tag'], 'name': candidate['name']})
                current_clans.add(candidate['tag'])
        view['manual_candidates'] = [dict(row) for row in self.db.execute('SELECT tag,player_name,town_hall,user_id,clan_tag,clan_name,reason,created_by,created_at,updated_by,updated_at,revision FROM bonus_raffle_manual_candidates WHERE season_id=? ORDER BY created_at,tag', (self.sid,))]
        view['lazy_settings'] = self.settings()
        return view

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
        view = self.enrich_view(view)
        minimum = self.policies()[pool]
        automatic = slots is None
        allowance = view.get('allowances', {}).get(clan_tag, {})
        if automatic:
            slots = allowance.get('total') if allowance.get('status') == 'ready' else 0
        accounts = [a for a in view['accounts'] if a['pool'] == pool and a['assigned_clan_tag'] == clan_tag]
        eligible, excluded, blocks = [], [], []
        if automatic and allowance.get('status') != 'ready':
            blocks.append(allowance.get('reason') or 'Automatic allowance is not available. Confirm the in-game count.')
        if not view['cycle']:
            blocks.append('Select the CWL month in Results first')
        if view['active_other_cycles']:
            blocks.append('This season contains bonus decisions for a different CWL month')
        if pool == 'main' and minimum is None:
            blocks.append('Save the minimum attacks for this CWL pool')
        if not accounts:
            blocks.append('No current signups assigned to this clan and CWL pool')
        conflicts = [row for row in view.get('manual_candidate_conflicts', []) if row['clan_tag'] == clan_tag]
        if conflicts:
            blocks.append('A saved manual candidate is now signed up in a different pool or clan; reconcile the account first')
        for account in accounts:
            reason = lazy_eligibility(account) if pool == 'lazy' else eligibility(account, minimum)
            if reason:
                excluded.append({**account, 'exclusion': reason})
                if pool == 'main' and reason in ('Roster changed; reconcile results before drawing', 'Results are not complete', 'Attack total is not available'):
                    blocks.append('Resolve incomplete or changed account results before drawing')
            else:
                if pool == 'lazy':
                    role_status = account.get('representative_status')
                    is_rep = account.get('is_representative')
                    multiplier = account.get('multiplier')
                    if role_status == 'unavailable':
                        blocks.append('Discord representative roles could not be verified for every eligible Lazy account')
                    elif role_status == 'unlinked':
                        if is_rep is not False or multiplier != 1:
                            blocks.append('Unlinked Lazy accounts must use the 1x ticket weight')
                    elif role_status == 'verified':
                        if type(is_rep) is not bool or multiplier != (2 if is_rep else 1):
                            blocks.append('Lazy representative role evidence is inconsistent')
                    else:
                        blocks.append('Lazy representative role status is unavailable')
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
                  'clan_name': clan.get('name', clan_tag), 'minimum': minimum if pool == 'main' else None,
                  'rules_version': 2 if pool == 'lazy' else 1,
                  'qualification_rule': '4+ attacks OR 3+ attacks and 8+ stars' if pool == 'lazy' else None,
                  'slots': slots, 'available': available, 'confirmed': confirmed,
                  'allowance_source': 'automatic' if automatic else 'staff',
                  'allowance': allowance if automatic else None,
                  'lazy_settings': self.settings() if pool == 'lazy' else None,
                  'eligible': eligible, 'excluded': excluded,
                  'manual_candidate_conflicts': conflicts,
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
        view = self.enrich_view(view)
        draw = self.get(draw_id)
        if draw['cancelled_at']:
            raise RaffleConflict('This draw was cancelled. Use the current saved draw')
        if draw['approved_at']:
            return draw
        snapshot = draw['snapshot']
        if snapshot['pool'] == 'lazy' and snapshot.get('rules_version') != 2:
            raise RaffleConflict('This saved Lazy draw uses an older rule set. Cancel and review it again before approval')
        if snapshot['cycle'] != view['cycle']:
            raise RaffleConflict('The CWL month changed. Restore the original month before approving')
        if snapshot.get('allowance_source') == 'automatic':
            allowance = view.get('allowances', {}).get(snapshot['clan_tag'])
            if allowance != snapshot.get('allowance'):
                raise RaffleConflict('The calculated allowance changed. Review the draw before approval; winners have not been rerolled')
        # Revalidate relevant results/identity without rerolling saved winners.
        current = {a['tag']: a for a in view['accounts']}
        original = snapshot['eligible'] + snapshot['excluded']
        relevant = [a for a in view['accounts'] if a['pool'] == snapshot['pool'] and a['assigned_clan_tag'] == snapshot['clan_tag']]
        if {a['tag'] for a in original} != {a['tag'] for a in relevant}:
            raise RaffleConflict('The participating accounts changed after the draw. Reconcile results before approval')
        if snapshot['pool'] == 'lazy' and snapshot.get('lazy_settings') != self.settings():
            raise RaffleConflict('The representative role changed since the draw. Review and draw again')
        if snapshot['pool'] == 'lazy':
            compare_fields = ('pool', 'assigned_clan_tag', 'assigned_clan_name', 'attacks', 'stars',
                              'source_complete', 'source_status', 'roster_changed', 'in_current_roster',
                              'manual_candidate', 'manual_candidate_reason', 'manual_host_valid', 'host_valid',
                              'player_name', 'town_hall', 'user_id', 'tag_valid', 'three_cycle_cooldown',
                              'already_confirmed_this_cycle', 'bonus_review', 'representative_status',
                              'is_representative', 'multiplier')
        else:
            # Keep pre-Lazy-rule Main draws approvable: these snapshots predate
            # review, cooldown, and role-evidence fields.
            compare_fields = ('pool', 'assigned_clan_tag', 'attacks')
        for old in original:
            account = current.get(old['tag'])
            old_reason = lazy_eligibility(old) if snapshot['pool'] == 'lazy' else eligibility(old, snapshot['minimum'])
            current_reason = lazy_eligibility(account) if account and snapshot['pool'] == 'lazy' else (eligibility(account, snapshot['minimum']) if account else None)
            if (not account or any(account.get(k) != old.get(k) for k in compare_fields)
                    or current_reason != old_reason):
                raise RaffleConflict('Results, eligibility review, representative status, or roster changed since the draw. Review again; winners have not been rerolled')
            if snapshot['pool'] == 'lazy' and old.get('tag') in {row.get('tag') for row in view.get('cycle_confirmed', [])}:
                raise RaffleConflict('This account is already confirmed for this CWL month')
        confirmed = sum(r['clan_tag'] == snapshot['clan_tag'] for r in view['cycle_confirmed'])
        if confirmed + len(snapshot['winners']) > snapshot['slots']:
            raise RaffleConflict('Other bonus selections now use these slots. Review the existing selections')
        batch = self.db.execute('INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?)',
                               (self.sid, snapshot['cycle'], view['revision'], fingerprint(snapshot), json.dumps(snapshot), actor, now())).lastrowid
        for account in snapshot['winners']:
            self.db.execute('INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (batch, self.sid, snapshot['cycle'], snapshot['publication_version'], account['tag'], account['player_name'], snapshot['pool'], snapshot['clan_tag'], snapshot['clan_name'], account['attacks'], account['stars'], ('Representative-weighted Lazy CWL raffle' if snapshot['pool'] == 'lazy' else 'Equal-chance account raffle'), '[]', actor, now()))
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

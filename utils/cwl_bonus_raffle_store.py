"""SQLite owner for saved draws, review decisions and announcement receipts.

Uses the dashboard's existing transaction boundary; no network work occurs inside
a transaction. A draw is unique for a CWL month, pool and hosting clan, even when
staff create another dashboard season for the same month.
"""

import hashlib
import json
from datetime import datetime, timezone

from utils.cwl_participation_status import ended_group_clans
from utils.cwl_bonus_raffle import announcement_pages, draw_accounts, eligibility, lazy_eligibility, LAZY_REVIEW_FLAGS

REP_NOTE_MAX = 40
# The FWA Clan Rep Discord role (same ID as FWA_WAR_PLANS_CONFIG
# "fwa_clan_rep_role_id"). Used only to help staff find rep accounts; the
# saved account list alone decides draw odds.
CLAN_REP_ROLE_ID = "769130325460254740"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bonus_imported_winners (
 season_id INTEGER NOT NULL REFERENCES seasons(id), cycle TEXT NOT NULL,
 pool TEXT NOT NULL CHECK(pool='lazy'), player_tag TEXT NOT NULL, player_name TEXT NOT NULL,
 clan_tag TEXT NOT NULL, clan_name TEXT NOT NULL, source TEXT NOT NULL CHECK(source='import'),
 imported_by TEXT NOT NULL, imported_at TEXT NOT NULL,
 PRIMARY KEY(cycle,player_tag)
);
CREATE INDEX IF NOT EXISTS bonus_imported_winners_player ON bonus_imported_winners(player_tag,cycle);
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
CREATE TABLE IF NOT EXISTS bonus_raffle_rep_accounts (
 tag TEXT PRIMARY KEY, player_name TEXT NOT NULL, town_hall INTEGER, user_id TEXT,
 note TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1,
 created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_by TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bonus_raffle_rep_account_audit (
 id INTEGER PRIMARY KEY, tag TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL,
 before_json TEXT, after_json TEXT, created_at TEXT NOT NULL
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


# A hosting clan is Lazy for a season by its season pool (Build roster), falling back to the
# directory pool. A clan archived after the season still counts when it has assigned accounts.
SEASON_POOL_JOIN = 'LEFT JOIN lineup_rules r ON r.season_id=l.season_id AND r.tag=c.tag'
LAZY_SEASON_POOL = "COALESCE(r.pool,c.pool)='lazy'"
ACTIVE_IN_SEASON = '(c.archived=0 OR EXISTS (SELECT 1 FROM roster_entries e WHERE e.season_id=l.season_id AND e.assigned_clan_tag=c.tag))'


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

    # FWA Rep accounts are one family-wide list, not saved per season. Listed
    # accounts get two Lazy draw tickets. The per-season role tables above are
    # kept only to preserve earlier data; nothing reads them.
    def rep_accounts(self):
        return [dict(row) for row in self.db.execute(
            'SELECT tag,player_name,town_hall,user_id,note,revision,created_by,created_at,updated_by,updated_at '
            'FROM bonus_raffle_rep_accounts ORDER BY player_name COLLATE NOCASE,tag')]

    def rep_tags(self):
        return {row['tag'] for row in self.db.execute('SELECT tag FROM bonus_raffle_rep_accounts')}

    def _rep_row(self, tag):
        row = self.db.execute('SELECT * FROM bonus_raffle_rep_accounts WHERE tag=?', (tag,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _rep_note(note):
        if not isinstance(note, str) or len(note.strip()) > REP_NOTE_MAX:
            raise RaffleConflict(f'Enter a note of up to {REP_NOTE_MAX} characters')
        return note.strip()

    def _rep_audit(self, tag, actor, action, before, after, stamp):
        public = lambda row: None if row is None else {k: row[k] for k in ('player_name', 'town_hall', 'user_id', 'note')}
        self.db.execute('INSERT INTO bonus_raffle_rep_account_audit(tag,actor_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)',
                        (tag, actor, action, json.dumps(public(before)) if before else None,
                         json.dumps(public(after)) if after else None, stamp))

    def add_rep_account(self, identity, note, actor):
        note = self._rep_note(note)
        if self._rep_row(identity['tag']):
            raise RaffleConflict('This account is already an FWA Rep account')
        stamp = now()
        self.db.execute('INSERT INTO bonus_raffle_rep_accounts(tag,player_name,town_hall,user_id,note,created_by,created_at,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                        (identity['tag'], identity['player_name'], identity.get('town_hall'), identity.get('user_id'), note, actor, stamp, actor, stamp))
        self._rep_audit(identity['tag'], actor, 'add', None, self._rep_row(identity['tag']), stamp)

    def _current_rep(self, tag, expected_revision):
        row = self._rep_row(tag)
        if not row:
            raise RaffleConflict('This account is no longer an FWA Rep account. Refresh the list')
        if row['revision'] != expected_revision:
            raise RaffleConflict('This FWA Rep account changed. Refresh the list')
        return row

    def update_rep_note(self, tag, note, expected_revision, actor):
        note = self._rep_note(note)
        before = self._current_rep(tag, expected_revision)
        if before['note'] == note:
            return
        stamp = now()
        self.db.execute('UPDATE bonus_raffle_rep_accounts SET note=?,revision=revision+1,updated_by=?,updated_at=? WHERE tag=?',
                        (note, actor, stamp, tag))
        self._rep_audit(tag, actor, 'note', before, self._rep_row(tag), stamp)

    def remove_rep_account(self, tag, expected_revision, actor):
        before = self._current_rep(tag, expected_revision)
        stamp = now()
        self.db.execute('DELETE FROM bonus_raffle_rep_accounts WHERE tag=?', (tag,))
        self._rep_audit(tag, actor, 'remove', before, None, stamp)

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
        host = self.db.execute(f'SELECT c.name FROM clans c JOIN lineup l ON l.tag=c.tag {SEASON_POOL_JOIN} WHERE l.season_id=? AND c.tag=? AND c.archived=0 AND {LAZY_SEASON_POOL}', (self.sid, clan_tag)).fetchone()
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

    def sit_out_settings(self):
        """Season hosting clans only; Main has no sit-out policy."""
        return [dict(row) for row in self.db.execute(
            f"SELECT c.tag,c.name,COALESCE(r.sit_out_months,3) AS months FROM clans c "
            f"JOIN lineup l ON l.tag=c.tag {SEASON_POOL_JOIN} "
            f"WHERE l.season_id=? AND {LAZY_SEASON_POOL} ORDER BY c.name COLLATE NOCASE,c.tag",
            (self.sid,))]

    def save_sit_out(self, clan_tag, months, actor):
        if type(months) is not int or not 0 <= months <= 6:
            raise RaffleConflict('Select a sit-out length of 0–6 months')
        before = next((row for row in self.sit_out_settings() if row['tag'] == clan_tag), None)
        if not before:
            raise RaffleConflict('Select a Lazy hosting clan in this season')
        if before['months'] == months:
            return
        self.db.execute('INSERT INTO lineup_rules(season_id,tag,sit_out_months) VALUES (?,?,?) '
                        'ON CONFLICT(season_id,tag) DO UPDATE SET sit_out_months=excluded.sit_out_months',
                        (self.sid, clan_tag, months))
        self.db.execute('INSERT INTO bonus_audit(season_id,actor_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)',
                        (self.sid, actor, 'sit_out', json.dumps(before),
                         json.dumps({**before, 'months': months}), now()))

    @staticmethod
    def shift_cycle(cycle, months):
        try:
            parsed = datetime.strptime(cycle, '%Y-%m')
        except (ValueError, TypeError):
            return None
        ordinal = parsed.year * 12 + parsed.month - 1 + months
        year, month = divmod(ordinal, 12)
        return f'{year:04d}-{month + 1:02d}'

    @staticmethod
    def month_label(cycle):
        return datetime.strptime(cycle, '%Y-%m').strftime('%b %Y') if cycle else None

    def latest_lazy_win(self, tag, cycle):
        if not self.shift_cycle(cycle, 0):
            return None
        row = self.db.execute(
            "SELECT MAX(cycle) AS cycle FROM (SELECT cycle FROM bonus_confirmations "
            "WHERE tag=? AND pool='lazy' AND voided_at IS NULL AND cycle<? "
            "UNION ALL SELECT cycle FROM bonus_imported_winners WHERE player_tag=? AND cycle<?)",
            (tag, cycle, tag, cycle)).fetchone()
        return row['cycle']

    def sit_out(self, tag, cycle, months):
        latest = self.latest_lazy_win(tag, cycle)
        eligible = self.shift_cycle(latest, months + 1) if latest else None
        return {'prior_winner_cycle': latest, 'prior_winner_label': self.month_label(latest),
                'sit_out_months': months, 'eligible_again': eligible,
                'three_cycle_cooldown': bool(months and eligible and cycle < eligible)}

    def enrich_prior_winners(self, accounts, cycle):
        lengths = {row['tag']: row['months'] for row in self.sit_out_settings()}
        reviews = self.account_reviews()
        for account in accounts:
            if account.get('pool') != 'lazy':
                continue
            account.update(self.sit_out(account['tag'], cycle, lengths.get(account.get('assigned_clan_tag'), 3)))
            account['sit_out_excluded'] = bool(account['three_cycle_cooldown'] and not
                str(reviews.get(account['tag'], {}).get('override_reason') or '').strip())
        return accounts

    def _has_three_cycle_cooldown(self, tag, cycle):
        # Compatibility for callers testing the former default rule.
        return self.sit_out(tag, cycle, 3)['three_cycle_cooldown']

    def imported_winner_history(self):
        """Read import records without inventing batches or confirmation receipts."""
        return [{**dict(row), 'tag': row['player_tag'], 'source': 'import',
                 'record_type': 'imported_winner'} for row in self.db.execute(
            'SELECT * FROM bonus_imported_winners WHERE season_id=? ORDER BY cycle DESC,clan_tag,player_tag',
            (self.sid,))]

    def import_pool_conflicts(self, rows, seasons):
        """Return every distinct NEW-row conflict; never reinterpret a saved staff rule."""
        conflicts = {}
        for row in rows:
            if self.db.execute('SELECT 1 FROM bonus_imported_winners WHERE cycle=? AND player_tag=?',
                               (row['cycle'], row['player_tag'])).fetchone():
                continue
            sid = seasons.get(row['cycle'])
            if sid is None:
                continue
            rule = self.db.execute(
                'SELECT r.pool,c.name FROM lineup_rules r JOIN clans c ON c.tag=r.tag '
                'WHERE r.season_id=? AND r.tag=?', (sid, row['clan_tag'])).fetchone()
            if rule is not None and rule['pool'] != 'lazy':
                key = (row['cycle'], row['clan_tag'])
                conflicts[key] = {'cycle': row['cycle'], 'clan_tag': row['clan_tag'],
                                  'clan_name': rule['name'], 'existing_pool': rule['pool']}
        return [conflicts[key] for key in sorted(conflicts)]

    def ensure_import_seasons(self, rows, existing_seasons=None):
        """Called in the import's single transaction, before binding CWL months."""
        seasons = {}
        for cycle in sorted({row['cycle'] for row in rows}):
            existing = (existing_seasons or {}).get(cycle)
            if existing:
                seasons[cycle] = existing
            else:
                seasons[cycle] = self.db.execute(
                    "INSERT INTO seasons(label,status,signup_open,history_only) VALUES (?,'archived',0,1)", (cycle,)).lastrowid
        for row in rows:
            sid = seasons[row['cycle']]
            self.db.execute('INSERT OR IGNORE INTO clans(tag,name,archived) VALUES (?,?,1)',
                            (row['clan_tag'], row['clan_name']))
            self.db.execute('INSERT OR IGNORE INTO lineup(season_id,tag) VALUES (?,?)', (sid, row['clan_tag']))
            # Only a TSV hosting clan is added; never copy another month's lineup.
            self.db.execute("INSERT OR IGNORE INTO lineup_rules(season_id,tag,pool) VALUES (?,?,'lazy')",
                            (sid, row['clan_tag']))
        return seasons

    def import_winners(self, rows, seasons, actor):
        added = 0
        stamp = now()
        for row in rows:
            added += self.db.execute(
                "INSERT OR IGNORE INTO bonus_imported_winners(season_id,cycle,pool,player_tag,player_name,"
                "clan_tag,clan_name,source,imported_by,imported_at) VALUES (?,?,'lazy',?,?,?,?,'import',?,?)",
                (seasons[row['cycle']], row['cycle'], row['player_tag'], row['player_name'],
                 row['clan_tag'], row['clan_name'], actor, stamp)).rowcount
        return added

    def enrich_view(self, view):
        """Attach Lazy review state and persisted manual candidates to the preview view."""
        accounts = list(view.get('accounts') or [])
        by_tag = {account['tag']: account for account in accounts}
        reviews = self.account_reviews()
        cycle = view.get('cycle')
        active_hosts = {row['tag'] for row in self.db.execute(
            f"SELECT c.tag FROM clans c JOIN lineup l ON l.tag=c.tag {SEASON_POOL_JOIN} WHERE l.season_id=? AND {ACTIVE_IN_SEASON} AND {LAZY_SEASON_POOL}",
            (self.sid,),
        )}
        for account in accounts:
            account['host_valid'] = account.get('assigned_clan_tag') in active_hosts
        for account in accounts:
            # Preserve candidate-scoped override annotations if
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
                'source_no_show': status == 'no_data' and row['clan_tag'] in ended_group_clans(self.db, self.sid, cycle),
                'checked_at': checked_at, 'warning': warning, 'roster_changed': False,
                'in_current_roster': False, 'manual_candidate': True, 'manual_candidate_reason': row['reason'],
                'tag_valid': True, 'source': 'manual', 'candidate_source': 'manual', 'already_confirmed_this_cycle': any(c.get('tag') == tag for c in view.get('cycle_confirmed', [])),
                'season_rounds': None,
                'manual_host_valid': host_valid, 'host_valid': host_valid,
                'bonus_review': reviews.get(tag, self._review_view()),
            }
            accounts.append(manual)
            by_tag[tag] = manual
        view['accounts'] = accounts
        view['bonus_reviews'] = reviews
        view['lazy_hosts'] = [dict(row) for row in self.db.execute(f'SELECT c.tag,c.name FROM clans c JOIN lineup l ON l.tag=c.tag {SEASON_POOL_JOIN} WHERE l.season_id=? AND {ACTIVE_IN_SEASON} AND {LAZY_SEASON_POOL} ORDER BY c.name COLLATE NOCASE,c.tag', (self.sid,))]
        current_clans = {row.get('tag') for row in view.get('clans', [])}
        for candidate in self.db.execute(
            f"SELECT DISTINCT c.tag,c.name FROM bonus_raffle_manual_candidates m JOIN clans c ON c.tag=m.clan_tag JOIN lineup l ON l.tag=c.tag AND l.season_id=m.season_id {SEASON_POOL_JOIN} WHERE m.season_id=? AND {ACTIVE_IN_SEASON} AND {LAZY_SEASON_POOL}",
            (self.sid,),
        ):
            if candidate['tag'] not in current_clans:
                view.setdefault('clans', []).append({'tag': candidate['tag'], 'name': candidate['name']})
                current_clans.add(candidate['tag'])
        view['manual_candidates'] = [dict(row) for row in self.db.execute('SELECT tag,player_name,town_hall,user_id,clan_tag,clan_name,reason,created_by,created_at,updated_by,updated_at,revision FROM bonus_raffle_manual_candidates WHERE season_id=? ORDER BY created_at,tag', (self.sid,))]
        self.enrich_prior_winners(accounts, cycle)
        reps = self.rep_tags()
        for account in accounts:
            if account.get('pool') == 'lazy':
                listed = account['tag'] in reps
                account.update(is_representative=listed, representative_status='listed' if listed else 'not_listed',
                               multiplier=2 if listed else 1)
        view['rep_accounts'] = self.rep_accounts()
        view['sit_out_settings'] = self.sit_out_settings()
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
                    is_rep = account.get('is_representative')
                    if type(is_rep) is not bool or account.get('multiplier') != (2 if is_rep else 1):
                        blocks.append('Lazy FWA Rep odds are inconsistent')
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
                  'rules_version': 4 if pool == 'lazy' else 1,
                  'sit_out_months': next((r['months'] for r in self.sit_out_settings() if r['tag'] == clan_tag), 3) if pool == 'lazy' else None,
                  'qualification_rule': '4+ attacks OR 3+ attacks and 8+ stars' if pool == 'lazy' else None,
                  'slots': slots, 'available': available, 'confirmed': confirmed,
                  'allowance_source': 'automatic' if automatic else 'staff',
                  'allowance': allowance if automatic else None,
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
        if snapshot['pool'] == 'lazy' and snapshot.get('rules_version') not in (3, 4):
            raise RaffleConflict('This saved Lazy draw uses an older rule set. Cancel and review it again before approval')
        if snapshot['pool'] == 'lazy' and snapshot.get('rules_version') == 4:
            length = next((r['months'] for r in self.sit_out_settings() if r['tag'] == snapshot['clan_tag']), 3)
            if snapshot.get('sit_out_months') != length:
                raise RaffleConflict('Rules changed · draw again')
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
            if snapshot['pool'] == 'lazy' and snapshot.get('rules_version') == 3 and account:
                # Pending v3 draws keep the former three-month confirmation-only rule.
                prior = [self.shift_cycle(view['cycle'], -n) for n in (1, 2, 3)]
                legacy = self.db.execute(
                    "SELECT 1 FROM bonus_confirmations WHERE tag=? AND pool='lazy' AND voided_at IS NULL AND cycle IN (?,?,?)",
                    (old['tag'], *prior)).fetchone()
                account = {**account, 'three_cycle_cooldown': bool(legacy), 'prior_winner_label': old.get('prior_winner_label')}
            if snapshot['pool'] == 'lazy' and snapshot.get('rules_version') == 4 and account and account.get('three_cycle_cooldown') != old.get('three_cycle_cooldown'):
                raise RaffleConflict('Rules changed · draw again')
            old_reason = lazy_eligibility(old) if snapshot['pool'] == 'lazy' else eligibility(old, snapshot['minimum'])
            current_reason = lazy_eligibility(account) if account and snapshot['pool'] == 'lazy' else (eligibility(account, snapshot['minimum']) if account else None)
            if (not account or any(account.get(k) != old.get(k) for k in compare_fields)
                    or current_reason != old_reason):
                raise RaffleConflict('Results, eligibility review, FWA Rep accounts, or roster changed since the draw. Review again; winners have not been rerolled')
            if snapshot['pool'] == 'lazy' and old.get('tag') in {row.get('tag') for row in view.get('cycle_confirmed', [])}:
                raise RaffleConflict('This account is already confirmed for this CWL month')
        confirmed = sum(r['clan_tag'] == snapshot['clan_tag'] for r in view['cycle_confirmed'])
        if confirmed + len(snapshot['winners']) > snapshot['slots']:
            raise RaffleConflict('Other bonus selections now use these slots. Review the existing selections')
        batch = self.db.execute('INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?)',
                               (self.sid, snapshot['cycle'], view['revision'], fingerprint(snapshot), json.dumps(snapshot), actor, now())).lastrowid
        for account in snapshot['winners']:
            self.db.execute('INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (batch, self.sid, snapshot['cycle'], snapshot['publication_version'], account['tag'], account['player_name'], snapshot['pool'], snapshot['clan_tag'], snapshot['clan_name'], account['attacks'], account['stars'], ('FWA Rep-weighted Lazy CWL raffle' if snapshot['pool'] == 'lazy' else 'Equal-chance account raffle'), '[]', actor, now()))
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

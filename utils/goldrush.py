"""Durable opt-in events over the existing gold-loot battle ledger."""
from datetime import datetime, timedelta, timezone
import json
import uuid

from utils.gold_loot import backup_database, connect, DEFAULT_DB


def utcnow():
    return datetime.now(timezone.utc)


def event_tables(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS goldrush_events (
            id TEXT PRIMARY KEY, guild_id TEXT NOT NULL,
            created_at TEXT NOT NULL, starts_at TEXT, ends_at TEXT,
            duration_hours INTEGER NOT NULL, account_mode TEXT NOT NULL,
            allow_late_join INTEGER NOT NULL, prize TEXT NOT NULL,
            final_results TEXT
        );
        CREATE TABLE IF NOT EXISTS goldrush_entries (
            event_id TEXT NOT NULL, user_id TEXT NOT NULL, player_tag TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY(event_id, player_tag),
            FOREIGN KEY(event_id) REFERENCES goldrush_events(id)
        );
        CREATE TABLE IF NOT EXISTS goldrush_changes (
            id TEXT PRIMARY KEY, event_id TEXT NOT NULL, user_id TEXT NOT NULL,
            starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
            previous_starts TEXT, previous_ends TEXT, expires_at TEXT NOT NULL,
            applied_at TEXT
        );
        CREATE TABLE IF NOT EXISTS goldrush_messages (
            event_id TEXT NOT NULL, channel_id TEXT NOT NULL, message_id TEXT PRIMARY KEY
        );
    ''')


def create_event(db, *, guild_id, account_mode, allow_late_join, duration_hours=24,
                 prize='1 Gold Pass', at=None):
    if account_mode not in ('single', 'combined'):
        raise ValueError('Choose single or combined account scoring.')
    if not 1 <= duration_hours <= 168:
        raise ValueError('Event duration must be between 1 and 168 hours.')
    at = at or utcnow()
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM goldrush_events WHERE guild_id=? AND final_results IS NULL',
                      (str(guild_id),)).fetchone():
            raise ValueError('Finish the existing Gold Rush before creating another.')
        event_id = uuid.uuid4().hex[:16]
        db.execute('INSERT INTO goldrush_events VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, NULL)',
                   (event_id, str(guild_id), at.isoformat(), duration_hours, account_mode,
                    int(allow_late_join), prize))
    backup_database(db)
    return get_event(db, event_id)


def get_event(db, event_id):
    row = db.execute('SELECT * FROM goldrush_events WHERE id=?', (event_id,)).fetchone()
    if row is None:
        raise ValueError('This Gold Rush could not be found.')
    return dict(row)


def current_event(db, guild_id):
    row = db.execute('SELECT * FROM goldrush_events WHERE guild_id=? ORDER BY created_at DESC LIMIT 1',
                     (str(guild_id),)).fetchone()
    return dict(row) if row else None


def start_event(db, event_id, *, at=None):
    at = at or utcnow()
    with db:
        db.execute('BEGIN IMMEDIATE')
        event = get_event(db, event_id)
        if event['starts_at'] or event['final_results'] is not None:
            raise ValueError('This Gold Rush has already started.')
        db.execute('UPDATE goldrush_events SET starts_at=?, ends_at=? WHERE id=?',
                   (at.isoformat(), (at + timedelta(hours=event['duration_hours'])).isoformat(), event_id))
    backup_database(db)
    return get_event(db, event_id)


def join_event(db, event_id, user_id, player_tags, *, at=None):
    """Caller verifies fresh CK/CP ownership before entering this transaction."""
    at = at or utcnow()
    tags = sorted(set(player_tags))
    with db:
        db.execute('BEGIN IMMEDIATE')
        event = get_event(db, event_id)
        if event['final_results'] is not None or (event['ends_at'] and at >= datetime.fromisoformat(event['ends_at'])):
            raise ValueError('Gold Rush signup is closed.')
        if event['starts_at'] and not event['allow_late_join']:
            raise ValueError('Signup closed when Gold Rush started.')
        if not tags or (event['account_mode'] == 'single' and len(tags) != 1):
            raise ValueError('Select one eligible account.' if event['account_mode'] == 'single' else 'No eligible accounts found.')
        existing = [row[0] for row in db.execute(
            'SELECT player_tag FROM goldrush_entries WHERE event_id=? AND user_id=? ORDER BY player_tag',
            (event_id, str(user_id)))]
        if existing:
            if existing == tags:
                return False
            raise ValueError('You have already joined. Your selected accounts are locked for this event.')
        for tag in tags:
            if not db.execute('SELECT 1 FROM players WHERE tag=?', (tag,)).fetchone():
                raise ValueError('Only accounts in the tracked Warriors United family roster can join.')
            if db.execute('SELECT 1 FROM goldrush_entries WHERE event_id=? AND player_tag=?', (event_id, tag)).fetchone():
                raise ValueError('That account is already entered in this Gold Rush.')
        db.executemany('INSERT INTO goldrush_entries VALUES (?, ?, ?, ?)',
                       [(event_id, str(user_id), tag, at.isoformat()) for tag in tags])
    backup_database(db)
    return True


def standings(db, event_id):
    event = get_event(db, event_id)
    if event['final_results'] is not None:
        return json.loads(event['final_results'])
    entries = db.execute('''SELECT e.user_id, e.player_tag, e.joined_at, p.name, c.clan_name
        FROM goldrush_entries e JOIN players p ON p.tag=e.player_tag
        LEFT JOIN player_clans c ON c.tag=e.player_tag
        WHERE e.event_id=? ORDER BY e.user_id, e.player_tag''', (event_id,)).fetchall()
    rows = {}
    for entry in entries:
        row = rows.setdefault(entry['user_id'], dict(user_id=entry['user_id'], gold=0,
            reached_at=None, joined_at=entry['joined_at'], accounts=[]))
        row['accounts'].append(dict(tag=entry['player_tag'], name=entry['name'], clan_name=entry['clan_name']))
        if event['starts_at']:
            score = db.execute('''SELECT COALESCE(SUM(gold),0), MAX(CASE WHEN gold>0 THEN battle_time END)
                FROM loot_events WHERE tag=? AND julianday(battle_time)>=julianday(?)
                AND julianday(battle_time)<julianday(?)''',
                (entry['player_tag'], event['starts_at'], event['ends_at'])).fetchone()
            row['gold'] += score[0]
            if score[1] and (row['reached_at'] is None or score[1] > row['reached_at']):
                row['reached_at'] = score[1]
    return sorted(rows.values(), key=lambda row: (-row['gold'], row['reached_at'] or '9999', row['joined_at'], row['user_id']))


def finalize_event(db, event_id, *, at=None):
    """Staff finalizes after checking refresh coverage; never automatically award."""
    at = at or utcnow()
    with db:
        db.execute('BEGIN IMMEDIATE')
        event = get_event(db, event_id)
        if not event['ends_at'] or at < datetime.fromisoformat(event['ends_at']):
            raise ValueError('Gold Rush has not ended yet.')
        if event['final_results'] is None:
            result = standings(db, event_id)
            db.execute('UPDATE goldrush_events SET final_results=? WHERE id=?', (json.dumps(result), event_id))
    backup_database(db)
    return get_event(db, event_id)


def open_store(path=DEFAULT_DB):
    if not path.is_file():
        raise ValueError('The gold tracker is not available on this bot host.')
    db = connect(path)
    event_tables(db)
    return db


def ensure_current(db, guild_id):
    event = current_event(db, guild_id)
    if event:
        return event
    session = db.execute('SELECT started FROM session').fetchone()
    if session is None:
        raise ValueError('Start the gold tracker first.')
    event = create_event(db, guild_id=guild_id, account_mode='combined', allow_late_join=True)
    return start_event(db, event['id'], at=datetime.fromisoformat(session['started']))


def propose_schedule(db, event_id, user_id, starts_at, duration_hours, *, at=None):
    at = at or utcnow()
    if starts_at.tzinfo is None:
        raise ValueError('Include a timezone offset, for example 2026-10-09T18:00:00-04:00.')
    starts_at = starts_at.astimezone(timezone.utc)
    if not 1 <= duration_hours <= 168:
        raise ValueError('Choose a duration from 1 to 168 hours.')
    earliest = datetime.fromisoformat(db.execute('SELECT started FROM session').fetchone()[0])
    if starts_at < earliest:
        raise ValueError('The start cannot be earlier than the original tracking start.')
    ends_at = starts_at + timedelta(hours=duration_hours)
    if ends_at <= at:
        raise ValueError('The new event must end in the future.')
    event = get_event(db, event_id)
    if event['final_results'] is not None:
        raise ValueError('This event has finalized results and cannot be rescheduled.')
    proposal = uuid.uuid4().hex[:16]
    with db:
        db.execute('INSERT INTO goldrush_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)',
            (proposal, event_id, str(user_id), starts_at.isoformat(), ends_at.isoformat(),
             event['starts_at'], event['ends_at'], (at + timedelta(minutes=10)).isoformat()))
    backup_database(db)
    return dict(db.execute('SELECT * FROM goldrush_changes WHERE id=?', (proposal,)).fetchone())


def confirm_schedule(db, proposal_id, user_id, guild_id, *, at=None):
    at = at or utcnow()
    with db:
        db.execute('BEGIN IMMEDIATE')
        proposal = db.execute('SELECT * FROM goldrush_changes WHERE id=?', (proposal_id,)).fetchone()
        if not proposal or proposal['user_id'] != str(user_id):
            raise ValueError('Only the administrator who requested this change can confirm it.')
        event = get_event(db, proposal['event_id'])
        if event['guild_id'] != str(guild_id):
            raise ValueError('This configuration belongs to another server.')
        if proposal['applied_at'] or at >= datetime.fromisoformat(proposal['expires_at']):
            raise ValueError('This confirmation expired or was already used. Run configure again.')
        if (event['starts_at'],event['ends_at']) != (proposal['previous_starts'],proposal['previous_ends']):
            raise ValueError('The event changed. Run configure again to review its current settings.')
        if event['final_results'] is not None:
            raise ValueError('This event has finalized results.')
        if datetime.fromisoformat(proposal['ends_at']) <= at:
            raise ValueError('The proposed event has already ended.')
        db.execute('UPDATE goldrush_events SET starts_at=?, ends_at=?, duration_hours=? WHERE id=?',
            (proposal['starts_at'],proposal['ends_at'],
             int((datetime.fromisoformat(proposal['ends_at'])-datetime.fromisoformat(proposal['starts_at'])).total_seconds()/3600),
             event['id']))
        db.execute('UPDATE goldrush_changes SET applied_at=? WHERE id=?', (at.isoformat(),proposal_id))
    backup_database(db)
    return get_event(db, event['id'])


def snapshot(db, event_id):
    event = get_event(db, event_id)
    rows = standings(db,event_id)
    count = db.execute('SELECT count(DISTINCT user_id), count(*) FROM goldrush_entries WHERE event_id=?', (event_id,)).fetchone()
    refreshed = db.execute('SELECT min(p.updated) FROM players p JOIN goldrush_entries e ON e.player_tag=p.tag WHERE e.event_id=?', (event_id,)).fetchone()[0]
    return dict(event=event, rows=rows[:10], entrants=count[0], accounts=count[1], refreshed=refreshed)


def register_message(db,event_id,channel_id,message_id):
    with db:
        db.execute('INSERT OR REPLACE INTO goldrush_messages VALUES (?, ?, ?)',(event_id,str(channel_id),str(message_id)))
    backup_database(db)

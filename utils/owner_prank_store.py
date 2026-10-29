"""Durable, isolated progress and notification claims for the owner prank."""

import json


SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_prank_state (
 user_id TEXT PRIMARY KEY,
 card INTEGER NOT NULL DEFAULT 1 CHECK(card BETWEEN 1 AND 15),
 branch TEXT CHECK(branch IN ('yes', 'no')),
 completed_at TEXT,
 notified TEXT NOT NULL DEFAULT '[]',
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 run INTEGER NOT NULL DEFAULT 1 CHECK(run >= 1)
);
"""


class InvalidEvent(ValueError):
    pass


class StaleRun(ValueError):
    pass


MILESTONE_CARDS = {
    'prank_opened': 1,
    'prank_bait_yes': 1,
    'prank_bait_no': 1,
    'prank_jumpscare_seen': 3,
    'prank_rickroll_seen': 10,
    'prank_encore_1': 11,
    'prank_encore_2': 12,
    'prank_encore_3': 13,
    'prank_encore_4': 14,
    'prank_completed': 15,
}


def read(store, user_id):
    row = store.one('SELECT * FROM owner_prank_state WHERE user_id=?', (user_id,))
    return row or {'user_id': user_id, 'card': 1, 'branch': None,
                   'completed_at': None, 'notified': '[]', 'run': 1}


def signup_count(store):
    row = store.one('SELECT COUNT(*) AS count FROM signups WHERE season_id='
                    '(SELECT season_id FROM member_season WHERE id=1)')
    return int(row['count']) if row else 0


def apply(store, user_id, event, card, run, branch=None, *, can_replay=False):
    """Return (state, newly claimed notification), committing before a send."""
    if type(card) is not int or not 1 <= card <= 15 or type(run) is not int or run < 1:
        raise InvalidEvent('Invalid card or run.')
    if type(event) is not str or event not in {*MILESTONE_CARDS, 'prank_card_seen', 'prank_closed_early', 'prank_replay'}:
        raise InvalidEvent('Unsupported prank event.')
    if event in MILESTONE_CARDS and card != MILESTONE_CARDS[event]:
        raise InvalidEvent('Card does not match prank event.')
    if branch is not None and (event not in {'prank_bait_yes', 'prank_bait_no'} or
                               branch != event.removeprefix('prank_bait_')):
        raise InvalidEvent('Invalid branch.')
    with store.tx() as db:
        row = db.execute('SELECT * FROM owner_prank_state WHERE user_id=?', (user_id,)).fetchone()
        state = dict(row) if row else {'user_id': user_id, 'card': 1, 'branch': None,
                                       'completed_at': None, 'notified': '[]', 'run': 1}
        if run != state['run']:
            raise StaleRun('Prank run changed. Reload before continuing.')
        if event in MILESTONE_CARDS or event == 'prank_closed_early':
            key = f'{run}:{event}' + (f':{card}' if event == 'prank_closed_early' else '')
            if key in json.loads(state['notified']):
                if event in ('prank_bait_yes', 'prank_bait_no') and state['branch'] != event.removeprefix('prank_bait_'):
                    raise InvalidEvent('Bait choice changed. Reload before continuing.')
                return state, None
        if event == 'prank_replay':
            if not can_replay or not state['completed_at'] or card != 15:
                raise InvalidEvent('Replay is unavailable.')
            state.update(card=1, branch=None, completed_at=None, run=run + 1)
        elif state['completed_at']:
            raise InvalidEvent('This prank run is complete.')
        elif event == 'prank_card_seen':
            if (card < state['card'] or card > state['card'] + 1 or
                    card in (2, 3) and not state['branch']):
                raise InvalidEvent('Card sequence changed. Reload before continuing.')
            state['card'] = card
        elif event in ('prank_bait_yes', 'prank_bait_no'):
            selected = event.removeprefix('prank_bait_')
            if card != 1 or state['card'] != 1 or (state['branch'] and state['branch'] != selected):
                raise InvalidEvent('Bait choice changed. Reload before continuing.')
            state['branch'] = selected
        elif event == 'prank_closed_early':
            if card != state['card']:
                raise InvalidEvent('Card sequence changed. Reload before continuing.')
        else:
            expected = MILESTONE_CARDS[event]
            if card != expected or card != state['card']:
                raise InvalidEvent('Card sequence changed. Reload before continuing.')
            if event == 'prank_completed':
                state['completed_at'] = _timestamp(db)

        claimed = None
        if event in MILESTONE_CARDS or event == 'prank_closed_early':
            key = f'{run}:{event}' + (f':{card}' if event == 'prank_closed_early' else '')
            notified = json.loads(state['notified'])
            if key not in notified:
                notified.append(key)
                state['notified'] = json.dumps(notified)
                claimed = event
        if row is None:
            db.execute('INSERT INTO owner_prank_state(user_id,card,branch,completed_at,notified,run) '
                       'VALUES (?,?,?,?,?,?)', (user_id, state['card'], state['branch'],
                       state['completed_at'], state['notified'], state['run']))
        else:
            db.execute('UPDATE owner_prank_state SET card=?,branch=?,completed_at=?,notified=?,run=?, '
                       'updated_at=CURRENT_TIMESTAMP WHERE user_id=?',
                       (state['card'], state['branch'], state['completed_at'], state['notified'],
                        state['run'], user_id))
    return state, claimed


def _timestamp(db):
    return db.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]

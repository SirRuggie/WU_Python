"""One-event, restart-safe Gold Rush winner announcement for an operator timer."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import requests
from utils import goldrush as store
from utils.gold_loot import ROOT, refresh_board


def winner_content(rows):
    positive = [row for row in rows if row['gold'] > 0]
    if not positive:
        return '🏁 Gold Rush has ended, but no entered account recorded gold. There is no winner this time.'
    first = positive[0]
    tied = [r for r in positive if (r['gold'], r['reached_at']) == (first['gold'], first['reached_at'])]
    if len(tied) > 1:
        return '🏁 Gold Rush has ended in an exact tie! Staff will review the tied accounts before announcing a winner.'
    return (f"🏆 <@{first['user_id']}> is the Gold Rush winner with **{first['gold']:,} gold**!\n\n"
            'He has proven to have no life and got all the gold... Go touch some grasss ffs 😂🌱')


def run(event_id, channel_id, message_id, *, check=False):
    load_dotenv(ROOT / '.env')
    session = requests.Session()
    session.headers['Authorization'] = 'Bot ' + os.environ['DISCORD_TOKEN']
    base = 'https://discord.com/api/v10'
    def api(method, route, **kwargs):
        response = session.request(method, base + route, timeout=45, **kwargs)
        response.raise_for_status()
        return response.json()
    with closing(store.open_store()) as db:
        event = store.get_event(db, event_id)
        if not db.execute('SELECT 1 FROM goldrush_messages WHERE event_id=? AND channel_id=? AND message_id=?',
                          (event_id, str(channel_id), str(message_id))).fetchone():
            raise ValueError('Target is not a registered post for this event.')
        channel = api('GET', f'/channels/{channel_id}')
        if str(channel['guild_id']) != event['guild_id']:
            raise ValueError('Target channel belongs to another guild.')
        post = api('GET', f'/channels/{channel_id}/messages/{message_id}')
        if check:
            print(json.dumps(dict(event=event_id, channel=channel['name'], ends_at=event['ends_at'],
                                 preview=winner_content(store.standings(db, event_id)))))
            return
        if not event['ends_at'] or store.utcnow() < datetime.fromisoformat(event['ends_at']) + timedelta(seconds=60):
            raise ValueError('Wait until one minute after the event ends.')
        receipt = ROOT / '.local' / f'goldrush-announced-{event_id}-{channel_id}.json'
        with receipt.with_suffix('.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if receipt.exists():
                print('Announcement already delivered.')
                return
            if event['final_results'] is None:
                board = refresh_board()
                if board['warning']:
                    raise RuntimeError(board['warning'])
                store.finalize_event(db, event_id)
            content = winner_content(store.standings(db, event_id))
            # Reconcile a prior successful send if the process stopped before saving its receipt.
            recent = api('GET', f'/channels/{channel_id}/messages', params={'limit':100})
            sent = next((m for m in recent if m['author']['id'] == post['author']['id']
                         and m.get('message_reference', {}).get('message_id') == str(message_id)
                         and m.get('content') == content), None)
            if sent is None:
                sent = api('POST', f'/channels/{channel_id}/messages', json={
                    'content': content,
                    'allowed_mentions': {'parse': ['users'], 'replied_user': False},
                    'message_reference': {'message_id': str(message_id), 'fail_if_not_exists': True},
                    'nonce': str(message_id), 'enforce_nonce': True,
                })
            temporary = receipt.with_suffix('.tmp')
            temporary.write_text(json.dumps({'message_id':sent['id'], 'channel_id':str(channel_id)}))
            temporary.replace(receipt)
            print('Winner announcement delivered: ' + sent['id'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('event_id')
    parser.add_argument('channel_id', type=int)
    parser.add_argument('message_id', type=int)
    parser.add_argument('--check', action='store_true', help='Validate destination and preview without sending or finalizing.')
    parser.add_argument('--scheduled', action='store_true')
    args = parser.parse_args()
    marker = f'# goldrush-announce-{args.event_id}'
    if args.scheduled:
        with closing(store.open_store()) as db:
            event = store.get_event(db, args.event_id)
            if not event['ends_at'] or store.utcnow() < datetime.fromisoformat(event['ends_at']) + timedelta(seconds=60):
                sys.exit(0)
    run(args.event_id, args.channel_id, args.message_id, check=args.check)
    if args.scheduled and not args.check:
        # Remove only this event's timer after successful delivery, preserving all other jobs.
        jobs = subprocess.run(['crontab', '-l'], check=True, capture_output=True, text=True).stdout
        remaining = ''.join(line for line in jobs.splitlines(keepends=True) if marker not in line)
        subprocess.run(['crontab', '-'], input=remaining, text=True, check=True)

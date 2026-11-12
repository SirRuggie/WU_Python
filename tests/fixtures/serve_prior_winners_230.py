"""Loopback-only native-browser fixture for prompt230. Never loads credentials.

Run from the repository root with the project Python:
  python tests/fixtures/serve_prior_winners_230.py --database /tmp/wu-230-preview.db
Build web/cwl first. Open http://127.0.0.1:8793, select Development login,
then Results & bonuses, season November fixture 2026, Lazy.
All identities and results below are explicitly synthetic. No external calls.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# Defend against inherited service credentials before importing the application.
for key in list(os.environ):
    if any(part in key for part in ('TOKEN', 'SECRET', 'MONGODB', 'DISCORD', 'COC_API')):
        os.environ.pop(key, None)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
from aiohttp import web
from cwl_web.app import create_app
from cwl_web.providers import FixtureProviders
from utils.cwl_working_roster import account_token, working_accounts
from utils.cwl_bonus_raffle_store import RaffleStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--port', type=int, default=8793)
    args = parser.parse_args()
    path = Path(args.database).resolve()
    if path.exists():
        raise SystemExit('Use a new fixture database path; refusing to overwrite an existing file')
    providers = FixtureProviders('505227988229554179')
    app = create_app(db_path=path, providers=providers, dev_fixture=True,
                     secure_cookies=False, static_dir=ROOT / 'web/cwl/dist')
    stamp = datetime.now(timezone.utc).isoformat()
    with app['store'].tx() as db:
        sid = db.execute("INSERT INTO seasons(label,signup_open) VALUES ('November fixture 2026',0)").lastrowid
        db.execute('UPDATE member_season SET season_id=?', (sid,))
        db.execute("INSERT INTO participation_sync_settings(season_id,cycle,enabled,status,last_checked_at,last_success_at,updated_by,updated_at) VALUES (?,'2026-11',0,'complete',?,?,'fixture',?)", (sid, stamp, stamp, stamp))
        for tag, name, pool in [('#C2Y', 'Lazy Phoenix', 'lazy'), ('#C2Q', 'Lazy Harbour', 'lazy'), ('#C2G', 'Main fixture', 'main')]:
            db.execute('INSERT INTO clans(tag,name) VALUES (?,?)', (tag,name))
            db.execute('INSERT INTO lineup(season_id,tag) VALUES (?,?)', (sid,tag))
            db.execute('INSERT INTO lineup_rules(season_id,tag,pool) VALUES (?,?,?)', (sid,tag,pool))
        owner = RaffleStore(db, sid)
        owner.save_sit_out('#C2Q', 2, 'fixture')
        alphabet = '0289PYLQGRJCUV'
        for i in range(26):
            tag = '#P' + alphabet[i // len(alphabet)] + alphabet[i % len(alphabet)] + 'Y'
            clan, pool = ('#C2Y','lazy') if i < 13 else ('#C2Q','lazy') if i < 23 else ('#C2G','main')
            name = ['October winner', 'Eligible player', 'Staff exception'][i] if i < 3 else f'Fixture player {i+1:02d}'
            db.execute('INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,?,?,?,0,?,16)', (sid,tag,'fixture-user',pool,name))
            db.execute('INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?,?,?,0)', (sid,tag,clan))
            identity = working_accounts(db,sid)[tag]
            attacks, stars = (2, 5) if i == 4 else (4, 10)
            db.execute("INSERT INTO participation_source_results(season_id,cycle,tag,attacks,stars,status,complete,checked_at,roster_token) VALUES (?,'2026-11',?,?,?,'complete',1,?,?)", (sid,tag,attacks,stars,stamp,account_token(identity)))
            if i in (0,2,13):
                db.execute("INSERT INTO bonus_imported_winners VALUES (?,'2026-10','lazy',?,?,'#OLD','Old fixture host','import','fixture',?)", (sid,tag,name,stamp))
            if i == 2:
                owner.save_account_review(tag, [], 'Fixture staff exception', 'fixture')
        # Manual allowance is set only on explicit staff entry; no fake live evidence.
        owner.save_policy('main', 4)
        counts = {table: db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                  for table in ('signups','roster_entries','bonus_raffle_draws','bonus_confirmations','bonus_raffle_account_reviews','bonus_imported_winners')}
        counts['by_pool'] = [dict(row) for row in db.execute('SELECT pool,COUNT(*) signups,SUM(kept) locks FROM signups JOIN roster_entries USING(season_id,tag) GROUP BY pool')]
    path.with_suffix('.counts.json').write_text(json.dumps(counts,indent=2))
    print(json.dumps({'url':f'http://127.0.0.1:{args.port}', 'database':str(path), 'counts':counts}),flush=True)
    web.run_app(app, host='127.0.0.1', port=args.port, access_log=None)


if __name__ == '__main__':
    main()

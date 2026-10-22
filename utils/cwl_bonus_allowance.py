"""CWL allowance rules and durable evidence owner. See docs/cwl-bonus-allowance.md."""
import json
import math
import re

RULES_VERSION = '2026-05-v1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS bonus_allowance_leagues (
 season_id INTEGER NOT NULL REFERENCES seasons(id), cycle TEXT NOT NULL,
 clan_tag TEXT NOT NULL, league TEXT NOT NULL, captured_at TEXT NOT NULL,
 PRIMARY KEY(season_id,cycle,clan_tag)
);
CREATE TABLE IF NOT EXISTS bonus_allowance_wars (
 season_id INTEGER NOT NULL REFERENCES seasons(id), cycle TEXT NOT NULL,
 war_tag TEXT NOT NULL, evidence_json TEXT NOT NULL,
 PRIMARY KEY(season_id,cycle,war_tag)
);
'''


def base_allowance(league, size, cycle):
    # Older seasons used different formats/rewards. Never apply today's table to them.
    if not isinstance(cycle, str) or not re.fullmatch(r'20\d\d-(?:0[1-9]|1[0-2])', cycle) or cycle < '2026-05':
        return None
    if not isinstance(league, str):
        return None
    match = re.fullmatch(r'(Bronze|Silver|Gold|Crystal|Master|Champion|Titan) League (I|II|III)', league or '')
    tier = match[1] if match else 'Legend' if league == 'Legend League' else None
    base = {'Bronze': 1, 'Silver': 1, 'Gold': 2, 'Crystal': 2, 'Master': 3,
            'Champion': 4, 'Titan': 5, 'Legend': 6}.get(tier)
    if base is None or type(size) is not int or size not in (15, 30):
        return None
    if size == 30:
        return base * 2 if base <= 3 else None
    return base


def final_war(war):
    """Retain only validated final clan scores; player attack sums are not war scores."""
    if not isinstance(war, dict) or war.get('state') not in ('ENDED', 'warEnded'):
        return None
    size = war.get('team_size')
    if type(size) is not int or size not in (15, 30):
        return None
    sides = []
    for key in ('clan', 'opponent'):
        side = war.get(key, {})
        if not isinstance(side, dict):
            return None
        tag, stars, destruction = side.get('tag'), side.get('stars'), side.get('destruction')
        if not isinstance(tag, str) or not re.fullmatch(r'#[0289PYLQGRJCUV]+', tag):
            return None
        if type(stars) is not int or not 0 <= stars <= 3 * size:
            return None
        if type(destruction) not in (int, float) or not math.isfinite(destruction) or not 0 <= destruction <= 100:
            return None
        sides.append({'tag': tag, 'stars': stars, 'destruction': destruction})
    if sides[0]['tag'] == sides[1]['tag']:
        return None
    return {'team_size': size, 'sides': sides}


class AllowanceStore:
    def __init__(self, db, sid, cycle):
        self.db, self.sid, self.cycle = db, sid, cycle

    def capture_league(self, clan_tag, league, stamp):
        if base_allowance(league, 15, self.cycle) is not None:
            self.db.execute('INSERT OR IGNORE INTO bonus_allowance_leagues VALUES (?,?,?,?,?)',
                            (self.sid, self.cycle, clan_tag, league, stamp))

    def capture_war(self, war_tag, war):
        evidence = final_war(war)
        if evidence is not None:
            self.db.execute('INSERT INTO bonus_allowance_wars VALUES (?,?,?,?) '
                            'ON CONFLICT(season_id,cycle,war_tag) DO UPDATE SET evidence_json=excluded.evidence_json',
                            (self.sid, self.cycle, war_tag, json.dumps(evidence, sort_keys=True)))

    def captured_wars(self):
        return {r['war_tag'] for r in self.db.execute(
            'SELECT war_tag FROM bonus_allowance_wars WHERE season_id=? AND cycle=?', (self.sid, self.cycle))}

    def view(self, clan_tag):
        result = {'status': 'unavailable', 'total': None, 'base': None, 'wins': 0,
                  'completed_wars': 0, 'rounds': None, 'league': None, 'team_size': None,
                  'rules_version': RULES_VERSION, 'reason': ''}
        league = self.db.execute('SELECT league FROM bonus_allowance_leagues WHERE season_id=? AND cycle=? AND clan_tag=?',
                                 (self.sid, self.cycle, clan_tag)).fetchone()
        if league:
            result['league'] = league['league']
        group = self.db.execute('SELECT * FROM participation_group_observations WHERE season_id=? AND cycle=? AND clan_tag=?',
                                (self.sid, self.cycle, clan_tag)).fetchone()
        if not group:
            result['reason'] = 'Refresh Clash results to check the allowance.'
            return result
        rounds = json.loads(group['war_tags_json'])
        result['rounds'] = len(rounds)
        evidence = {r['war_tag']: json.loads(r['evidence_json']) for r in self.db.execute(
            'SELECT war_tag,evidence_json FROM bonus_allowance_wars WHERE season_id=? AND cycle=?', (self.sid, self.cycle))}
        seen, sizes = set(), set()
        for tags in rounds:
            matches = [(tag, evidence[tag]) for tag in tags if tag in evidence and any(s['tag'] == clan_tag for s in evidence[tag]['sides'])]
            if len(matches) != 1 or matches[0][0] in seen:
                continue
            tag, war = matches[0]
            seen.add(tag)
            sizes.add(war['team_size'])
            ours = next(s for s in war['sides'] if s['tag'] == clan_tag)
            other = next(s for s in war['sides'] if s['tag'] != clan_tag)
            result['wins'] += int((ours['stars'], ours['destruction']) > (other['stars'], other['destruction']))
        result['completed_wars'] = len(seen)
        if len(sizes) == 1:
            result['team_size'] = next(iter(sizes))
        result['base'] = base_allowance(result['league'], result['team_size'], self.cycle)
        if result['base'] is None:
            result['reason'] = 'Season league or supported war format was not captured. Confirm the total shown in Clash.'
        elif len(rounds) not in (5, 7) or len(seen) != len(rounds) or str(group['state']).upper().replace('_', '') != 'ENDED':
            result['status'] = 'pending'
            result['reason'] = 'Waiting for complete final CWL results. The bonus total is not final yet.'
        else:
            result.update(status='ready', total=result['base'] + result['wins'], reason='Calculated from the saved season league and final war results.')
        return result

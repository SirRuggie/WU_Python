"""Pure official-player activity comparisons and bounded state reduction.

Storage and polling are deliberately separate from this domain reducer. Missing
fields never become zeroes: a partial upstream response cannot invent activity.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# ClashPerk players.service.ts didAchievementChange(..., forLastSeen=True).
ACHIEVEMENTS = frozenset({
    'Aggressive Capitalism', 'Most Valuable Clanmate', 'Games Champion',
    'Heroic Heist', 'Gold Grab', 'Elixir Escapade', 'Well Seasoned',
    'Union Buster', 'Wall Buster', 'Nice and Tidy', 'Superb Work',
    'Monolith Masher', 'Get those Goblins!', 'Anti-Artillery',
    'Shattered and Scattered', 'Counterspell', 'X-Bow Exterminator',
    'Mortar Mauler', 'Multi-Archer Tower Terminator', 'Ricochet Cannon Crusher',
    'Firespitter Finisher', 'Multi-Gear Tower Trampler', 'Firefighter',
})
COUNTERS = ('attackWins', 'donations', 'expLevel', 'townHallLevel')
CHANGES = ('name', 'warPreference', 'builderBaseTrophies')


def baseline(player: dict) -> dict:
    result = {key: player[key] for key in (*COUNTERS, *CHANGES, 'trophies')
              if key in player and player[key] is not None}
    for field in ('heroes', 'heroEquipment', 'troops', 'spells'):
        for unit in player.get(field) or []:
            if isinstance(unit, dict) and unit.get('name') and isinstance(unit.get('level'), int):
                result[f"{field}:{unit.get('village', 'home')}:{unit['name']}"] = unit['level']
    for row in player.get('achievements') or []:
        if (isinstance(row, dict) and row.get('name') in ACHIEVEMENTS
                and isinstance(row.get('value'), int)):
            result[f"achievement:{row['name']}"] = row['value']
    return result


def activity_changed(previous: dict | None, current: dict) -> bool:
    if not previous:
        return False
    for key, value in current.items():
        if key not in previous:
            continue
        old = previous[key]
        if key in CHANGES:
            if value != old:
                return True
        elif (isinstance(value, (int, float)) and not isinstance(value, bool)
              and isinstance(old, (int, float)) and not isinstance(old, bool)
              and value > old):
            if key != 'trophies' or old >= 5000:
                return True
    return False


def observe(previous: dict | None, player: dict, *, now: datetime) -> dict:
    """Reduce a successful read. Callers must never pass failed responses here."""
    if now.tzinfo is None:
        raise ValueError('Activity observations require an aware UTC timestamp')
    now = now.astimezone(timezone.utc)
    state = dict(previous or {})
    current = baseline(player)
    changed = activity_changed(state.get('baseline'), current)
    # Preserve omitted counters so partial reads do not erase the last baseline.
    state['baseline'] = {**state.get('baseline', {}), **current}
    state['name'] = player.get('name', state.get('name', ''))
    state['updated_at'] = now
    state.setdefault('tracking_started_at', now)
    if changed:
        state.update(last_seen_at=now, last_seen_source='clash_api')
    cutoff = (now - timedelta(days=29)).date().isoformat()
    days = {day for day in state.get('active_days', []) if cutoff <= day <= now.date().isoformat()}
    if changed:
        days.add(now.date().isoformat())
    state['active_days'] = sorted(days)[-30:]
    state['raid_weekends'] = list(state.get('raid_weekends', []))[-8:]
    return state

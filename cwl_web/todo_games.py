"""Adapt provider scores to the authenticated personal Tasks view."""
import asyncio
from datetime import datetime, timezone

import aiohttp
from utils.clan_games import fetch_clan_scores, valid_tag

SOURCE_NOTE = 'ClashPerk · Tracked scores can lag behind the game.'
FETCH_CONCURRENCY = 5


def event_window(now):
    now = now.astimezone(timezone.utc)
    start = now.replace(day=22, hour=8, minute=0, second=0, microsecond=0)
    return start, start.replace(day=28)


def _base_row(account, start, end):
    return {
        'tag': account.tag, 'name': account.name, 'town_hall': account.town_hall,
        'clan_tag': account.clan_tag, 'clan_name': account.clan_name,
        'badge_url': account.clan_badge, 'used': None, 'total': None, 'remaining': None,
        'state': 'unknown', 'detail': 'No score reported for this account. Check in game.',
        'starts_at': start.timestamp(), 'ends_at': end.timestamp(),
    }


async def build_games_view(accounts, *, now=None):
    now = now or datetime.now(timezone.utc)
    start, end = event_window(now)
    season = start.strftime('%Y-%m')
    rows = [_base_row(account, start, end) for account in accounts
            if isinstance(account.town_hall, int) and account.town_hall >= 6]
    view = {'ok': True, 'note': SOURCE_NOTE, 'notes': [], 'unavailable': '',
            'incomplete': '', 'rows': rows, 'season': season, 'source': 'ClashPerk',
            'checked_at': now.isoformat(), 'event_start': start.timestamp(), 'event_end': end.timestamp()}
    if now < start:
        for row in rows:
            row.update(state='upcoming', detail='Points will appear after Clan Games starts.')
        return view
    clans = sorted({row['clan_tag'].upper() for row in rows if valid_tag(row['clan_tag'])})
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
        results = await asyncio.gather(*(fetch_clan_scores(session, clan, season, semaphore)
                                         for clan in clans), return_exceptions=True)
    by_clan = dict(zip(clans, results))
    failures = missing = 0
    for row in rows:
        clan = row['clan_tag'].upper() if valid_tag(row['clan_tag']) else None
        result = by_clan.get(clan)
        if isinstance(result, BaseException):
            failures += 1
            row['detail'] = 'ClashPerk could not be reached. Try checking again.'
            continue
        if result is None:
            missing += 1
            row['detail'] = 'No current clan available to look up this account’s score.'
            continue
        points = result.get(row['tag'].upper()) if valid_tag(row['tag']) else None
        if points is None:
            missing += 1
            continue
        row.update(used=points, state='reported', detail=None)
    view['ok'] = not rows or failures < len(rows)
    if failures:
        view['incomplete'] = f'Scores could not be checked for {failures} account(s).'
    if missing:
        view['notes'].append(f'{missing} account(s) have no reported score. Missing scores are not treated as zero.')
    if not view['ok']:
        view['unavailable'] = 'Clan Games scores are temporarily unavailable.'
    return view

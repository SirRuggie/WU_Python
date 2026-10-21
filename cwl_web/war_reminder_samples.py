"""Authenticated sample-account loading; never supplies scheduled war data."""
import asyncio
import time

from aiohttp import web

from utils import war_reminders as reminders
from .providers import ProviderUnavailable

CACHE_SECONDS = 300
CACHE_LIMIT = 100
SAMPLE_ACCOUNT_LIMIT = 5


class SampleAccounts:
    """Bounded per-app cache with single-flight refreshes for repeated previews."""
    def __init__(self):
        self.cache = {}
        self.lock = asyncio.Lock()

    async def get(self, providers, user_id, clan_tag):
        key = (user_id, clan_tag)
        async with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            try:
                tags = await providers.linked_tags(user_id)
                if not tags:
                    raise web.HTTPBadRequest(text='No linked accounts found for your Discord account. Use sample players or link an account first.')
                roster = (await providers.clan_roster(clan_tag))['members']
            except ProviderUnavailable:
                raise web.HTTPServiceUnavailable(text='Could not load your linked accounts. Try again shortly or use sample players.') from None
            profiles = [p for p in roster if p['tag'] in tags][:SAMPLE_ACCOUNT_LIMIT]
            if not profiles:
                raise web.HTTPBadRequest(text='None of your linked accounts are currently in this clan. Choose a clan containing your accounts or use sample players.')
            if len(self.cache) >= CACHE_LIMIT:
                self.cache.clear()
            self.cache[key] = (time.monotonic()+CACHE_SECONDS, profiles)
            return profiles


async def test_messages(request, clan, config, event, body, actor):
    """Resolve only the authenticated actor, never a user ID supplied by a form."""
    for key in ('use_my_accounts', 'mention_me'):
        if type(body.get(key, False)) is not bool:
            raise web.HTTPBadRequest(text='Check the test options.')
    sample = reminders.sample(clan, event)
    own_accounts = body.get('use_my_accounts', False)
    if own_accounts:
        cache = request.app.setdefault('war_reminder_test_accounts', SampleAccounts())
        profiles = await cache.get(request.app['providers'], str(actor['user_id']), clan['tag'])
        unlinked = {**sample['members'][-1], 'name': 'Unlinked example'}
        sample['members'] = [
            dict(tag=p['tag'], name=p['name'], th=p['town_hall'], position=i+1, used=i % 2)
            for i, p in enumerate(profiles)
        ] + [unlinked]
    return reminders.messages(
        sample, config, event, test=True,
        tester=str(actor['user_id']) if body.get('mention_me') else None,
        sample_label='Your accounts in this clan + unlinked example' if own_accounts else 'Sample players',
        sample_group='Your accounts' if own_accounts else 'Sample accounts',
    )

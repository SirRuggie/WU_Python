"""Progressive, user-scoped account reads. Never used to authorize signup writes."""
import asyncio
import logging
import time
from datetime import datetime, timezone

from utils.clan_weights import source_weights, overlay_accounts
from .providers import ProviderUnavailable

LINK_INSTRUCTION = 'Link your accounts with ClashKing or ClashPerk in Discord, then refresh.'


async def snapshot(request, user_id):
    app = request.app
    states = app['account_display_states']
    jobs = app['account_display_jobs']
    now = time.monotonic()
    for key, state in list(states.items()):
        if key not in jobs and state['expires'] <= now:
            states.pop(key, None)
    force = request.query.get('refresh') == '1'
    state = states.get(user_id)
    if user_id not in jobs and (state is None or force):
        # Never serve accounts from a previous link set while rechecking ownership.
        state = {'accounts': {}, 'updating': True, 'total': None, 'error': None,
                 'expires': now + 120, 'checked_at': None}
        states[user_id] = state
        jobs[user_id] = asyncio.create_task(_load(app, user_id, state))
    while len(states) > 1024:
        removable = next((key for key in states if key not in jobs and key != user_id), None)
        if removable is None:
            break
        states.pop(removable, None)
    data = {'accounts': [dict(row) for row in state['accounts'].values()],
            'updating': state['updating'], 'total': state['total'],
            'status': 'loading' if state['updating'] else 'partial' if state['error'] else 'ok',
            'error': state['error'], 'checked_at': state['checked_at'],
            'link_url': None, 'link_instruction': LINK_INSTRUCTION}
    return overlay_accounts(app['store'], data)


async def _load(app, user_id, state):
    provider = app['providers']
    async def build():
        links = await asyncio.wait_for(provider.linked_tags(user_id), 35)
        state['total'] = len(links)
        directory = None
        failures = []
        user_gate = asyncio.Semaphore(5)

        async def family():
            nonlocal directory
            try:
                result = await asyncio.wait_for(provider.family_clans(), 15)
                directory = {clan['tag']: clan for clan in result['clans']}
            except (ProviderUnavailable, TimeoutError):
                pass

        def annotate(player, key):
            tag = player.get('current_clan_tag')
            return {**player, 'verified': bool(links[key]),
                    'family_clan_status': 'unknown' if directory is None else 'approved' if tag in directory else 'outside',
                    'current_clan_type': (directory or {}).get(tag, {}).get('type'),
                    'lazy_eligible': True, 'lazy_ineligible_reason': None}

        async def player(key):
            try:
                async with user_gate, app['account_display_gate']:
                    result = await asyncio.wait_for(provider.player(key), 35)
                if result.get('tag') != key:
                    raise ProviderUnavailable('Player response did not match request')
                state['accounts'][key] = annotate(result, key)
            except (ProviderUnavailable, TimeoutError):
                failures.append(key)

        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(family())
            for key in links:
                tasks.create_task(player(key))
        for key, account in state['accounts'].items():
            state['accounts'][key] = annotate(account, key)
        if failures:
            state['error'] = 'Some account details could not load. Refresh accounts to try again.'
        try:
            weights = await asyncio.wait_for(source_weights(app['store'], provider, list(state['accounts'])), 5) if state['accounts'] else {}
        except (ProviderUnavailable, TimeoutError):
            weights = {}
        for key, account in state['accounts'].items():
            account['war_weight'] = weights.get(key, {}).get('weight')

    try:
        async with asyncio.timeout(120):
            await build()
    except (ProviderUnavailable, TimeoutError):
        state['error'] = 'Account details could not finish loading. Refresh accounts to try again.'
    except Exception:
        logging.getLogger(__name__).exception('Dashboard account display refresh failed')
        state['error'] = 'Account details could not finish loading. Refresh accounts to try again.'
    finally:
        if state['error']:
            logging.getLogger(__name__).warning('Account display refresh incomplete: loaded=%s expected=%s', len(state['accounts']), state['total'])
        state['updating'] = False
        state['checked_at'] = datetime.now(timezone.utc).isoformat()
        state['expires'] = time.monotonic() + (5 if state['error'] else 30)
        app['account_display_jobs'].pop(user_id, None)


async def lifecycle(app):
    app['account_display_states'] = {}
    app['account_display_jobs'] = {}
    app['account_display_gate'] = asyncio.Semaphore(10)
    yield
    tasks = list(app['account_display_jobs'].values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    app['account_display_states'].clear()

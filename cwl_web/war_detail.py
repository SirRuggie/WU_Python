"""On-demand, scope-checked current-war roster and attack log."""
import asyncio
import re
from datetime import datetime, timezone

from aiohttp import web

from utils import todo_data
from utils.clan_activity import war_detail as project_detail, war_summary
from .providers import ProviderUnavailable
from .todo import get_clash_client, load_recent_clans

TAG = re.compile(r"^#[0289PYLQGRJCUV]{3,15}$")
WAR_ID = re.compile(r"^[0-9a-f]{24}$")


async def detail(request):
    from .app import _require

    scope = request.query.get('scope', 'mine')
    kind = request.query.get('kind', '')
    clan_tag = request.query.get('clan_tag', '').upper()
    expected = request.query.get('war_id', '')
    if (scope not in ('mine', 'family') or kind not in ('regular', 'cwl')
            or not TAG.fullmatch(clan_tag) or not WAR_ID.fullmatch(expected)
            or len(request.query) != len({'scope': scope, 'kind': kind,
                                          'clan_tag': clan_tag, 'war_id': expected})
            or set(request.query) != {'scope', 'kind', 'clan_tag', 'war_id'}):
        raise web.HTTPBadRequest(text='Invalid war detail request')
    session = _require(request, 'editor' if scope == 'family' else 'member')
    user_id = session['user_id']
    app = request.app

    # Independently prove the requested clan belongs to this scope on every read.
    # Mine allows current linked-account clans or a recent CWL host only when
    # the selected active league war actually includes a linked account.
    try:
        links = await asyncio.wait_for(app['providers'].linked_tags(user_id), 10)
        linked_tags = list(links)[:100]
    except Exception as exc:
        if scope == 'mine':
            raise ProviderUnavailable('Linked accounts could not be checked') from exc
        linked_tags = None
    war = None
    status = None
    if scope == 'family':
        try:
            directory = await asyncio.wait_for(app['providers'].family_clans(), 10)
        except Exception as exc:
            raise ProviderUnavailable('Family clans could not be checked') from exc
        if clan_tag not in {clan['tag'] for clan in directory['clans'][:100]}:
            raise web.HTTPForbidden(text='Clan is not in your available war activity')
    else:
        if not linked_tags:
            raise web.HTTPForbidden(text='Clan is not in your available war activity')
        client = await get_clash_client(app)
        try:
            accounts, _errors = await asyncio.wait_for(
                todo_data.fetch_accounts(
                    client, linked_tags, lookup_timeout=8, max_cache_age=60), 20)
        except Exception as exc:
            raise ProviderUnavailable('Linked accounts could not be checked') from exc
        if not accounts:
            raise ProviderUnavailable('Linked accounts could not be checked')
        current = {account.clan_tag for account in accounts if account.clan_tag}
        if clan_tag not in current:
            if kind != 'cwl':
                raise web.HTTPForbidden(text='Clan is not in your available war activity')
            candidates, note = await load_recent_clans(app, linked_tags)
            if note:
                raise ProviderUnavailable('Recent CWL clans could not be checked')
            eligible = any(candidate.check_cwl and candidate.clan_tag == clan_tag
                           for account in accounts
                           for candidate in candidates.get(account.tag.upper(), []))
            if not eligible:
                raise web.HTTPForbidden(text='Clan is not in your available war activity')
            status, war = await todo_data.fetch_current_war(client, clan_tag, kind)
            league = war_summary(status, war, clan_tag, accounts=accounts)
            if (league.get('state') not in ('preparation', 'inWar', 'awaitingResult')
                    or not league.get('my_accounts')):
                if league.get('state') in ('private', 'error'):
                    raise ProviderUnavailable('Recent CWL membership could not be verified')
                raise web.HTTPForbidden(text='Clan is not in your available war activity')
    if war is None:
        client = await get_clash_client(app)
        status, war = await todo_data.fetch_current_war(client, clan_tag, kind)
    if status == 'error':
        raise ProviderUnavailable('War detail is unavailable. Please retry.')
    if status != 'war' or war is None:
        raise web.HTTPConflict(text='War changed or is unavailable. Refresh the activity card.')
    result = project_detail(status, war, clan_tag, linked_tags=linked_tags, league=kind == 'cwl')
    if result.get('war_id') != expected or result.get('state') in ('error', 'private', 'none'):
        raise web.HTTPConflict(text='War changed. Refresh the activity card.')
    result.update({'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': scope,
                   'kind': kind, 'clan_tag': clan_tag})
    if linked_tags is None:
        result['warnings'] = ['Linked accounts could not be checked; highlights are unavailable.']
    return web.json_response(result)


def setup(app):
    app.router.add_get('/api/cwl/war-detail', detail)

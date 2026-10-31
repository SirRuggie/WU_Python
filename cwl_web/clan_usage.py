"""Read-only links to the actual consumers of a registered family clan."""
from urllib.parse import urlencode

from aiohttp import web

from .manage_clans import tag
from .server_management import API, require_manage, mongo


async def usage(request):
    await require_manage(request, 'clans')
    clan_tag = tag(request)
    async with mongo(request) as db:
        row = await db.clans.find_one({'tag': clan_tag})
    if not row:
        raise web.HTTPNotFound(text='Clan removed. Refresh the list.')
    # StrikeTracking receives every registered clan; only FWA-specific rules and
    # the weight editor restrict their directory to the exact stored FWA type.
    links = [{'label': 'Strikes tracking', 'href': '/clans/strikes'}]
    if row.get('type') == 'FWA':
        links.append({'label': 'Clan weights (FWA)',
                      'href': '/clan-weights?' + urlencode({'clan': clan_tag})})
    hosting = request.app['store'].rows(
        'SELECT s.id,s.label,COALESCE(r.pool,c.pool) AS pool '
        'FROM lineup l JOIN seasons s ON s.id=l.season_id '
        'JOIN clans c ON c.tag=l.tag '
        'LEFT JOIN lineup_rules r ON r.season_id=l.season_id AND r.tag=l.tag '
        "WHERE l.tag=? AND c.archived=0 AND s.status!='archived' ORDER BY s.id DESC",
        (clan_tag,),
    )
    for entry in hosting:
        pool = {'main': 'Main', 'lazy': 'Lazy'}.get(entry['pool'], 'Pool not set')
        links.append({'label': f"CWL hosting ({pool} · {entry['label']})",
                      'href': '/cwl/roster?' + urlencode({'season': entry['id']})})
    return web.json_response({'links': links})


routes = [web.get(API + '/clans/{tag}/usage', usage)]

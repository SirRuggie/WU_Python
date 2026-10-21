"""Staff-only trial editor using live clan membership and isolated saved weights."""
from datetime import datetime, timezone
from io import BytesIO
from aiohttp import web
from .providers import tag, ProviderUnavailable
from utils.clan_weight_trial_store import WeightConflict


def authorize(request):
    from .app import _require, _owner, _store, _fail
    from .access_control import scopes
    actor = _require(request)
    if not _owner(actor) and 'clans' not in scopes(_store(request), actor['user_id']):
        _fail(403, 'Clan management access required')
    return actor


async def family(request):
    result = await request.app['providers'].family_clans()
    return result['clans']


async def current(request):
    from .app import _fail
    try:
        value = tag(request.match_info['tag'])
    except ValueError:
        _fail(400, 'Invalid clan tag')
    clans = await family(request)
    if value not in {row['tag'] for row in clans}:
        _fail(404, 'This clan is no longer in the family. Refresh the clan list.')
    roster = await request.app['providers'].clan_roster(value)
    return roster


def response(roster, saved):
    return {'clan': {'tag':roster['tag'],'name':roster['name']},
            'checked_at':datetime.now(timezone.utc).isoformat(),
            'members':[{**member,'weight':saved.get(member['tag'],{}).get('weight'),
                        'storages':saved.get(member['tag'],{}).get('storages') or (5 if (member.get('town_hall') or 18) > 8 else 4),
                        'revision':saved.get(member['tag'],{}).get('revision',0)} for member in roster['members']]}


async def directory(request):
    authorize(request)
    return web.json_response({'clans':await family(request)})


async def members(request):
    authorize(request)
    roster = await current(request)
    saved = request.app['clan_weight_trial'].for_members([row['tag'] for row in roster['members']])
    result = response(roster,saved)
    try:
        order = await request.app['providers'].weight_war_order(roster['tag'])
        result['war_order'] = order
    except (ProviderUnavailable, ValueError, TypeError):
        result['war_order'] = None
    return web.json_response(result)


async def save(request):
    from .app import _json, _fail
    actor = authorize(request)
    body = await _json(request)
    changes = body.get('changes')
    if not isinstance(changes,list) or not 1 <= len(changes) <= 50:
        _fail(400, 'Choose between 1 and 50 weights to save.')
    seen = set()
    for item in changes:
        if not isinstance(item,dict) or set(item) not in ({'tag','weight','revision'}, {'tag','weight','revision','storages'}):
            _fail(400, 'Invalid weight row')
        try:
            item['tag'] = tag(item['tag'])
        except (ValueError,TypeError):
            _fail(400, 'Invalid player tag')
        if item['tag'] in seen or type(item['revision']) is not int or not 0 <= item['revision'] < 2**63:
            _fail(400, 'Duplicate player or invalid weight revision')
        seen.add(item['tag'])
        weight = item['weight']
        storages = item.get('storages')
        if 'storages' in item and (type(storages) is not int or not 1 <= storages <= 5):
            _fail(400, 'Storages must be a whole number from 1 to 5.')
        if weight is not None and (type(weight) is not int or not 1 <= weight <= 999999 or
                                   (storages is None and (weight < 1000 or weight % 1000)) or
                                   (storages is not None and weight % storages)):

            _fail(400, 'Enter a whole full weight divisible by the storage count. Leave blank for Not Available.')
    roster = await current(request)  # Recheck membership before any write.
    if not seen <= {row['tag'] for row in roster['members']}:
        _fail(409, 'A selected member has left this clan. Refresh members; their previously saved weight is retained.')
    try:
        saved = request.app['clan_weight_trial'].save(roster,changes,actor['user_id'])
    except WeightConflict as error:
        _fail(409,str(error))
    return web.json_response(response(roster,saved))


def workbook(rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    book = Workbook()
    sheet = book.active
    sheet.title = 'Saved test weights'
    headers = ['Player tag','Player name','Town Hall','Weight (k)','Weight','Clan at last save','Clan tag at last save','Saved at','Storages','Loot']
    sheet.append(headers)
    for row in rows:
        values = [row['tag'],row['player_name'],row['town_hall'],row['weight']/1000 if row['weight'] else None,
                  row['weight'],row['last_clan_name'],row['last_clan_tag'],row['updated_at'], row.get('storages'), row['weight'] // row['storages'] if row['weight'] is not None and row.get('storages') else None]
        values = [ILLEGAL_CHARACTERS_RE.sub('', value) if isinstance(value,str) else value for value in values]
        sheet.append(values)
        # Never interpret external names as spreadsheet formulas.
        for cell,value in zip(sheet[sheet.max_row],values):
            if isinstance(value,str): cell.data_type = 's'
    sheet.freeze_panes='A2'
    sheet.auto_filter.ref=sheet.dimensions
    for cell in sheet[1]:
        cell.font=Font(bold=True,color='FFFFFF')
        cell.fill=PatternFill('solid',fgColor='292929')
    for letter,width in zip('ABCDEFGHIJ',[18,30,12,14,16,28,24,30,12,14]):
        sheet.column_dimensions[letter].width=width
    data=BytesIO(); book.save(data)
    return data.getvalue()


async def export(request):
    authorize(request)
    data = workbook(request.app['clan_weight_trial'].all())
    return web.Response(body=data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':'attachment; filename="clan-weights-test.xlsx"'})


routes = [web.get('/api/cwl/weight-trial/clans',directory),
          web.get('/api/cwl/weight-trial/export.xlsx',export),
          web.get('/api/cwl/weight-trial/clans/{tag}',members),
          web.put('/api/cwl/weight-trial/clans/{tag}',save)]

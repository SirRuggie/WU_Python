"""Allowlisted local OAuth return query for the merged strike page."""
import re

TAG = re.compile(r'#[0289PYLQGRJCUV]{3,15}')


def activity_query(query):
    result = {}
    for key in ('tag', 'clan'):
        value = str(query.get(key, ''))
        if TAG.fullmatch(value):
            result[key] = value
    for key, allowed in (('clans', None), ('status', {'risk', 'watch', 'active'}), ('th', None)):
        values = str(query.get(key, '')).split(',')[:50]
        if key == 'clans':
            valid = [value for value in values if TAG.fullmatch(value)]
        elif key == 'th':
            valid = [value for value in values if value.isascii() and value.isdigit() and 1 <= int(value) <= 99]
        else:
            valid = [value for value in values if value in allowed]
        if valid:
            result[key] = ','.join(dict.fromkeys(valid))
    for key in ('marked', 'low', 'strikes'):
        if query.get(key) in ('0', '1'):
            result[key] = query[key]
    for key, allowed in (('sort', {'status','quiet','strikes','weight','th','missed','name','priority'}),
                         ('left', {'all','current','left'})):
        if query.get(key) in allowed:
            result[key] = query[key]
    page = str(query.get('page', ''))
    if page.isascii() and page.isdigit() and 0 <= int(page) <= 999:
        result['page'] = page
    if query.get('q'):
        result['q'] = str(query['q'])[:80]
    return result

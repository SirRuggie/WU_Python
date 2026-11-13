"""Components V2 rendering for the Lazy CWL bonus announcement.

One rules container (with last month's winners) and one container per Lazy
clan. Pure functions: callers supply stored data; nothing here reads Discord.
"""
import hashlib
import json
import re

from utils.cwl_bonus_raffle import safe_text

CWL_EMOJI = '<:CWL:1399013745598009375>'
LAZY_CWL_ROLE_ID = '1080521665584308286'
WU_GOLD = 0xF2B62A
FOOTER_FILE = 'Gold_Footer.png'
COMPONENTS_V2 = 1 << 15
# Discord limits: 40 components and 4,000 text characters per message.
# Keep a margin so a small count difference never rejects a send.
MAX_COMPONENTS = 38
MAX_TEXT = 3800
TEXT_CHUNK = 1800

INTRO = ('Each clan gets a set number of bonus medals. Each war win adds 1 more medal. '
         'We plan to lose all wars, so performance does not decide who gets them. '
         'The WU_Wizard bonus lottery selects recipients at random from the eligible players.')
RULE_ATTACKS = 'Do 4 or more attacks, OR do 3 attacks and get 8 or more stars.'

_TAG = re.compile(r'#[0-9A-Z]{3,12}')
_USER = re.compile(r'[0-9]{15,22}')


def _length(text):
    # Discord counts UTF-16 units; this is never lower than the real count.
    return len(text.encode('utf-16-le')) // 2


def _tag(value):
    value = str(value or '').upper()
    return f'`{value}`' if _TAG.fullmatch(value) else safe_text(value)


def _mention(user_id, names, preview):
    user_id = str(user_id or '')
    if not _USER.fullmatch(user_id):
        return None
    if preview:
        name = names.get(user_id)
        return f'**@{safe_text(name)}**' if name else '**@Discord member**'
    return f'<@{user_id}>'


def _seasons(months):
    return 'last season' if months == 1 else f'last {months} seasons'


def sit_out_rule(lengths):
    """Return (rule line or None, winners note) for the included clans' sit-out lengths."""
    values = sorted(set(lengths))
    if not values or values == [0]:
        return None, 'The players below got a bonus last month.'
    if len(values) == 1:
        rule = f'Not get a bonus in the {_seasons(values[0])}.'
        return rule, (f'The players below got a bonus last month. '
                      f'Players with a bonus in the {_seasons(values[0])} are not eligible.')
    return ("Not get a bonus during your clan's sit-out. Each clan below shows its sit-out.",
            "The players below got a bonus last month. Players in their clan's sit-out are not eligible.")


def _text(content):
    return {'type': 10, 'content': content}


def _separator():
    return {'type': 14, 'divider': True, 'spacing': 1}


def _chunks(heading, lines):
    """Split lines into text blocks of at most TEXT_CHUNK characters; heading starts the first."""
    blocks, current = [], heading
    for line in lines:
        candidate = f'{current}\n{line}' if current else line
        if current and _length(candidate) > TEXT_CHUNK:
            blocks.append(current)
            current = line
        else:
            current = candidate
    if current:
        blocks.append(current)
    return blocks


def _winner_line(row, names, preview, *, with_name):
    parts = [safe_text(row['player_name'])] if with_name and row.get('player_name') else []
    parts.append(_tag(row['tag']))
    mention = _mention(row.get('user_id'), names, preview)
    if mention:
        parts.append(mention)
    return ' · '.join(parts)


def sections(data, names=None, preview=False):
    """Build the ordered containers. Each container is a list of child components."""
    names = names or {}
    rule3, note = sit_out_rule([clan['sit_out_months'] for clan in data['clans']])
    rules = [f'1. Obey the Lazy CWL rules.', f'2. {RULE_ATTACKS}']
    if rule3:
        rules.append(f'3. {rule3}')
    header = [_text(f'## {CWL_EMOJI} Lazy CWL Bonus Medals'), _text(INTRO), _separator(),
              _text('**To be eligible, you must:**\n' + '\n'.join(rules)), _separator()]
    label = data.get('last_month_label') or 'last month'
    winners = sorted(data['last_month'], key=lambda row: (str(row.get('player_name') or '').casefold(), row['tag']))
    lines = [_winner_line(row, names, preview, with_name=False) for row in winners] or ['No bonus winners recorded.']
    blocks = _chunks(f'**Last month\'s bonus winners · {safe_text(label)}**\n-# {note}', lines)
    header.extend(_text(block) for block in blocks)
    result = [('Lazy CWL Bonus Medals', header)]
    mixed = len({clan['sit_out_months'] for clan in data['clans']}) > 1
    for clan in data['clans']:
        count = clan['bonus_count']
        info = f"**{count} bonus medal{'s' if count != 1 else ''}**"
        if mixed:
            months = clan['sit_out_months']
            info += ' · Sit-out: ' + ('none' if not months else f"{months} month{'s' if months != 1 else ''}")
        children = [_text(f"### {safe_text(clan['name'])} · {_tag(clan['tag'])}\n{info}"), _separator()]
        clan_lines = [f'{i}. ' + _winner_line(row, names, preview, with_name=True)
                      for i, row in enumerate(clan['winners'], 1)] or ['No winners.']
        children.extend(_text(block) for block in _chunks('**Winners**', clan_lines))
        result.append((clan['name'], children))
    return result


def _units(component):
    return 1 + sum(_units(child) for child in component.get('components', ())) + len(component.get('items', ()))


def _text_total(component):
    return (_length(component.get('content', '')) if component.get('type') == 10 else 0) + sum(
        _text_total(child) for child in component.get('components', ()))


def _footer():
    return {'type': 12, 'items': [{'media': {'url': f'attachment://{FOOTER_FILE}'}}]}


def _container(children):
    return {'type': 17, 'accent_color': WU_GOLD, 'components': children}


def messages(data, names=None, preview=False, ping=False):
    """Pack the containers into as few Components V2 messages as the limits allow."""
    role = _text(f'<@&{LAZY_CWL_ROLE_ID}>') if ping else None
    reserve_units = _units(_footer()) + (_units(role) if role else 0)
    reserve_text = _text_total(role) if role else 0
    containers = []
    for _, children in sections(data, names, preview):
        # A container larger than one message is split at text blocks.
        part = []
        for child in children:
            trial = _container(part + [child])
            if part and (_units(trial) + reserve_units > MAX_COMPONENTS or _text_total(trial) + reserve_text > MAX_TEXT):
                containers.append(_container(part))
                part = []
            part.append(child)
        containers.append(_container(part))
    pages, current = [], []
    for container in containers:
        trial = current + [container]
        if current and (sum(map(_units, trial)) + reserve_units > MAX_COMPONENTS
                        or sum(map(_text_total, trial)) + reserve_text > MAX_TEXT):
            pages.append(current)
            current = []
        current.append(container)
    pages.append(current)
    pages[-1][-1]['components'].append(_footer())
    if role:
        pages[-1].append(role)
    result = []
    for components in pages:
        payload = {'flags': COMPONENTS_V2, 'components': components,
                   # Only the Lazy CWL role may ping; player mentions never notify anyone.
                   'allowed_mentions': {'parse': [], 'users': [], 'roles': [LAZY_CWL_ROLE_ID] if ping else []}}
        result.append(payload)
    for payload in result:
        if sum(map(_units, payload['components'])) > 40 or sum(map(_text_total, payload['components'])) > 4000:
            raise ValueError('Announcement section is too large for one Discord message')
    return result


def preview_parts(payload):
    """Map one Components V2 payload to the dashboard DiscordPreview parts."""
    def convert(component):
        kind = component['type']
        if kind == 17:
            return {'type': 'container', 'accent': f"#{component['accent_color']:06x}".upper(),
                    'children': [convert(child) for child in component['components']]}
        if kind == 14:
            return {'type': 'separator', 'divider': component.get('divider', True), 'spacing': component.get('spacing', 1)}
        if kind == 12:
            # The footer file is attached at send time; the preview shows a labeled placeholder.
            return {'type': 'media', 'items': [{'url': None, 'description': 'Gold footer image'}
                                               for _ in component['items']]}
        return {'type': 'text', 'text': component.get('content', '')}
    return [convert(component) for component in payload['components']]


def fingerprint(data, ping):
    return hashlib.sha256(json.dumps({'data': data, 'ping': bool(ping)}, sort_keys=True, default=str).encode()).hexdigest()

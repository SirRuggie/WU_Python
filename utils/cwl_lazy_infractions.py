"""Lazy CWL infractions: the staff list and its Components V2 post.

Pure functions: callers supply stored accounts; nothing here reads Discord.
Decisions (Ruggie, 2026-11-13): saved review flags and "Did not join" are
infractions; a player with a saved staff reason is left out of the post; the
post pings nobody.
"""
import hashlib
import json
from datetime import datetime

from utils import cwl_bonus_announcement as base
from utils.cwl_bonus_raffle import safe_text

WU_RED = 0xE00010
FOOTER_FILE = 'Red_Footer.png'
FLAG_LABELS = {'missed_sync': 'Missed sync', 'lingering': 'Lingering', 'left_family': 'Left family'}
DID_NOT_JOIN = 'Did not join'
INTRO = 'These accounts broke a Lazy CWL rule this season.'


def infractions(account):
    """Labels in a fixed order: saved flags, then Did not join."""
    flags = set((account.get('bonus_review') or {}).get('flags') or ())
    labels = [label for flag, label in FLAG_LABELS.items() if flag in flags]
    if account.get('source_no_show') and account.get('assigned_clan_tag'):
        labels.append(DID_NOT_JOIN)
    return labels


def month_label(cycle):
    try:
        return datetime.strptime(cycle, '%Y-%m').strftime('%B %Y')
    except (TypeError, ValueError):
        return ''


def build(accounts, clan_names, cycle):
    """Group Lazy accounts with infractions by hosting clan.

    accounts: enriched bonus view accounts. Only Lazy accounts with a hosting clan count.
    """
    clans, exceptions = {}, []
    for account in accounts:
        clan_tag = account.get('assigned_clan_tag')
        if account.get('pool') != 'lazy' or not clan_tag:
            continue
        labels = infractions(account)
        if not labels:
            continue
        clan_name = clan_names.get(clan_tag) or account.get('assigned_clan_name') or clan_tag
        row = {'tag': account['tag'], 'player_name': account.get('player_name') or '',
               'town_hall': account.get('town_hall'), 'infractions': labels}
        reason = str((account.get('bonus_review') or {}).get('override_reason') or '').strip()
        if reason:
            exceptions.append({**row, 'clan_name': clan_name, 'reason': reason})
            continue
        clans.setdefault(clan_tag, {'tag': clan_tag, 'name': clan_name, 'players': []})['players'].append(row)
    ordered = sorted(clans.values(), key=lambda c: (c['name'].lower(), c['tag']))
    for clan in ordered:
        clan['players'].sort(key=lambda p: (p['player_name'].lower(), p['tag']))
    exceptions.sort(key=lambda p: (p['player_name'].lower(), p['tag']))
    return {'cycle': cycle, 'label': month_label(cycle), 'clans': ordered, 'exceptions': exceptions}


def _line(index, player):
    name = safe_text(player['player_name']) if player['player_name'] else 'Unknown player'
    return f"{index}. {name} · {base._tag(player['tag'])} · {', '.join(player['infractions'])}"


def _heading(clan, continued=False):
    return base._text(f"### {safe_text(clan['name'])} · {base._tag(clan['tag'])}" + (' (continued)' if continued else ''))


def _footer():
    return {'type': 12, 'items': [{'media': {'url': f'attachment://{FOOTER_FILE}'}}]}


def _container(children):
    return {'type': 17, 'accent_color': WU_RED, 'components': children}


def messages(data):
    """Pack the post into as few messages as the Discord limits allow.

    A clan that does not fit continues in the next message under its repeated heading.
    The red footer goes on the last message. No mentions are allowed.
    """
    reserve = base._units(_footer())

    def fits(children):
        container = _container(children)
        return (base._units(container) + reserve <= base.MAX_COMPONENTS
                and base._text_total(container) <= base.MAX_TEXT)

    title = f"## {base.CWL_EMOJI} {data['label'] or 'Lazy CWL'} Infractions"
    pages, current = [], [base._text(title), base._text(INTRO)]
    for clan in data['clans']:
        lines = [_line(i, p) for i, p in enumerate(clan['players'], 1)]
        blocks = base._chunks('', lines)
        if not fits(current + [base._separator(), _heading(clan), base._text(blocks[0])]):
            pages.append(current)
            current = []
        if current:
            current.append(base._separator())
        current.append(_heading(clan))
        for block in blocks:
            if not fits(current + [base._text(block)]):
                pages.append(current)
                current = [_heading(clan, continued=True)]
            current.append(base._text(block))
    current.append(_footer())
    pages.append(current)
    result = []
    for children in pages:
        container = _container(children)
        if base._units(container) > 40 or base._text_total(container) > 4000:
            raise ValueError('Infractions section is too large for one Discord message')
        result.append({'flags': base.COMPONENTS_V2, 'components': [container],
                       'allowed_mentions': {'parse': [], 'users': [], 'roles': []}})
    return result


def preview_parts(payload):
    return base.preview_parts(payload, footer_label='Red footer image')


def fingerprint(data):
    post = {'cycle': data['cycle'], 'clans': data['clans']}
    return hashlib.sha256(json.dumps(post, sort_keys=True, default=str).encode()).hexdigest()

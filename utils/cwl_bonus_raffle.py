"""Equal-account CWL draws and safe, bounded announcement rendering."""

import re
import secrets


def eligibility(account, minimum):
    if not account.get('in_current_roster') or account.get('roster_changed'):
        return 'Roster changed; reconcile results before drawing'
    if not account.get('source_complete') or account.get('source_status') not in ('complete', 'stale', 'historical'):
        return 'Results are not complete'
    attacks = account.get('attacks')
    if type(attacks) is not int or attacks < 0:
        return 'Attack total is not available'
    if account.get('already_confirmed_this_cycle'):
        return 'Already selected for a bonus this season'
    if minimum is None:
        return 'Set the minimum attacks'
    if attacks < minimum:
        return 'Below the minimum attacks'
    return None


def draw_accounts(accounts, count):
    """One ticket per unique player tag, sampled without replacement."""
    by_tag = {a['tag']: a for a in accounts}
    if len(by_tag) != len(accounts):
        raise ValueError('Duplicate accounts in raffle')
    if type(count) is not int or count < 1 or not accounts:
        raise ValueError('No eligible accounts or bonus slots')
    return secrets.SystemRandom().sample(list(by_tag.values()), min(count, len(by_tag)))


def safe_text(value):
    # External names cannot inject mentions, links, headings, or extra rows.
    text = re.sub(r'[\r\n\t\x00-\x1f]', ' ', str(value))[:100]
    text = text.replace('@', '@\u200b')
    return re.sub(r'([\\`*_~|<>\[\]#])', r'\\\1', text)


def announcement_pages(snapshot):
    label = 'Main CWL' if snapshot['pool'] == 'main' else 'Lazy CWL'
    header = f"**{safe_text(snapshot['clan_name'])} · {label} bonus winners**\n{snapshot['cycle']} · Minimum {snapshot['minimum']} attacks\n"
    footer = '\nCongratulations! Clan leadership will award the bonuses in-game.'
    pages, body = [], header
    for account in snapshot['winners']:
        line = f"\n• {safe_text(account['player_name'])} · {safe_text(account['tag'])} · {account['attacks']}{('/' + str(account['season_rounds'])) if account.get('season_rounds') else ''} attacks"
        # Discord uses UTF-16 lengths; use a conservative count for astral text.
        if len((body + line + footer).encode('utf-16-le')) // 2 > 1900:
            pages.append(body)
            body = header + '(continued)\n'
        body += line
    pages.append(body + footer)
    return pages

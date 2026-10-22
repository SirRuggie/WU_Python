"""Equal-account CWL draws and safe, bounded announcement rendering."""

import re
import secrets


LAZY_REVIEW_FLAGS = frozenset({'missed_sync', 'lingering', 'left_family'})


def _lazy_hard_exclusion(account):
    """Return exclusions that a staff reason must never bypass."""
    if account.get('already_confirmed_this_cycle'):
        return 'Already selected for a bonus this CWL month'
    if account.get('pool') != 'lazy':
        return 'Account is not in Lazy CWL'
    if not account.get('assigned_clan_tag'):
        return 'Account has no assigned hosting clan'
    if account.get('host_valid') is False:
        return 'Hosting clan is no longer an active Lazy clan in this season'
    if account.get('roster_changed'):
        return 'Roster changed; reconcile results before drawing'
    if not account.get('in_current_roster') and not account.get('manual_candidate'):
        return 'Account is not in the current signup roster'
    if account.get('tag_valid') is False:
        return 'Player tag could not be verified'
    if account.get('manual_host_valid') is False:
        return 'Manual hosting clan is no longer an active Lazy clan in this season'
    return None


def lazy_eligibility(account):
    """Lazy rule: 4+ attacks, or 3+ attacks and 8+ stars.

    Staff may override participation and review exclusions with a reason, but
    cannot override identity, assignment, reconciliation, or same-cycle rules.
    """
    hard = _lazy_hard_exclusion(account)
    if hard:
        return hard
    review = account.get('bonus_review') or {}
    flags = review.get('flags') or []
    reasons = {
        'missed_sync': 'Missed CWL sync',
        'lingering': 'Lingering in hosting clan',
        'left_family': 'Left the family',
    }
    flagged = [reasons[flag] for flag in flags if flag in reasons]
    attacks, stars = account.get('attacks'), account.get('stars')
    if attacks is not None and (type(attacks) is not int or not 0 <= attacks <= 7):
        return 'Attack result is invalid'
    if stars is not None and (type(stars) is not int or not 0 <= stars <= 21):
        return 'Star result is invalid'
    if attacks is not None and stars is not None and stars > attacks * 3:
        return 'Participation totals are inconsistent'
    if not account.get('source_complete') or attacks is None or stars is None:
        flagged.append('Complete participation results are unavailable')
    elif not (attacks >= 4 or (attacks >= 3 and stars >= 8)):
        flagged.append('Does not meet the Lazy CWL participation rule')
    if account.get('three_cycle_cooldown'):
        flagged.append('Received a bonus in each of the previous three CWL months')
    if flagged:
        if str(review.get('override_reason') or '').strip():
            return None
        return '; '.join(flagged)
    return None


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
    """Draw unique accounts; a 2x multiplier grants two tickets, not two wins."""
    by_tag = {a['tag']: a for a in accounts}
    if len(by_tag) != len(accounts):
        raise ValueError('Duplicate accounts in raffle')
    if type(count) is not int or count < 1 or not accounts:
        raise ValueError('No eligible accounts or bonus slots')
    winners_needed = min(count, len(by_tag))
    tickets = []
    multipliers = []
    for account in by_tag.values():
        multiplier = account.get('multiplier', 1)
        if type(multiplier) is not int or multiplier not in (1, 2):
            raise ValueError('Account multiplier must be 1 or 2')
        multipliers.append(multiplier)
        tickets.extend([account] * multiplier)
    if winners_needed == len(by_tag):
        return list(by_tag.values())
    rng = secrets.SystemRandom()
    if all(multiplier == 1 for multiplier in multipliers):
        return rng.sample(list(by_tag.values()), winners_needed)
    winners = []
    while len(winners) < winners_needed:
        chosen = rng.choice(tickets)
        winners.append(chosen)
        # Remove every ticket for a selected account, preventing repeat wins.
        tickets = [ticket for ticket in tickets if ticket['tag'] != chosen['tag']]
    return winners


def safe_text(value):
    # External names cannot inject mentions, links, headings, or extra rows.
    text = re.sub(r'[\r\n\t\x00-\x1f]', ' ', str(value))[:100]
    text = text.replace('@', '@\u200b')
    return re.sub(r'([\\`*_~|<>\[\]#])', r'\\\1', text)


def announcement_pages(snapshot):
    label = 'Main CWL' if snapshot['pool'] == 'main' else 'Lazy CWL'
    if snapshot['pool'] == 'lazy':
        rule = snapshot.get('qualification_rule') or '4+ attacks OR 3+ attacks and 8+ stars'
        header = f"**{safe_text(snapshot['clan_name'])} · {label} bonus winners**\n{snapshot['cycle']} · Rule: {safe_text(rule)}\n"
    else:
        header = f"**{safe_text(snapshot['clan_name'])} · {label} bonus winners**\n{snapshot['cycle']} · Minimum {snapshot['minimum']} attacks\n"
    footer = '\nCongratulations! Clan leadership will award the bonuses in-game.'
    pages, body = [], header
    for account in snapshot['winners']:
        if snapshot['pool'] == 'lazy':
            attacks = account.get('attacks')
            stars = account.get('stars')
            participation = 'Participation unavailable' if attacks is None else f"{attacks} attacks" + (f", {stars} stars" if stars is not None else '')
            line = f"\n• {safe_text(account['player_name'])} · {safe_text(account['tag'])} · {participation}"
        else:
            line = f"\n• {safe_text(account['player_name'])} · {safe_text(account['tag'])} · {account['attacks']}{('/' + str(account['season_rounds'])) if account.get('season_rounds') else ''} attacks"
        # Discord uses UTF-16 lengths; use a conservative count for astral text.
        if len((body + line + footer).encode('utf-16-le')) // 2 > 1900:
            pages.append(body)
            body = header + '(continued)\n'
        body += line
    pages.append(body + footer)
    return pages

"""Deterministic, non-destructive balancing of selected working placements."""
from collections import Counter


def balance_accounts(accounts, clans, selected_tags, destination_tags, include_locked=False):
    selected = set(selected_tags)
    hosts = {c['tag']: c for c in clans if c['tag'] in destination_tags}
    counts = Counter(a['assigned_clan_tag'] for a in accounts)
    totals = Counter()
    bands = Counter()
    for a in accounts:
        if a['effective_weight'] is not None:
            totals[a['assigned_clan_tag']] += a['effective_weight']
            bands[(a['assigned_clan_tag'], a['effective_weight'])] += 1
    placements, skipped = [], []
    candidates = []
    for a in sorted((a for a in accounts if a['tag'] in selected),
                    key=lambda a: (-(a['effective_weight'] or 0), a['tag'])):
        weight = a['effective_weight']
        reason = ('filler_manual_only' if a.get('roster_filler') else
                  'locked' if a['kept'] and not include_locked else
                  'source_unavailable' if a['manual_weight'] is None and a['source_status'] == 'unavailable' else
                  'missing_weight' if weight is None else None)
        if reason:
            skipped.append({'tag': a['tag'], 'reason': reason})
        else:
            candidates.append(a)
    # Reserve failed accounts at their original locations and re-plan. Releasing
    # all eligible selections together allows swaps even between full clans.
    while candidates:
        trial_counts, trial_totals, trial_bands = counts.copy(), totals.copy(), bands.copy()
        for a in candidates:
            old, weight = a['assigned_clan_tag'], a['effective_weight']
            trial_counts[old] -= 1
            trial_totals[old] -= weight
            trial_bands[(old, weight)] -= 1
        placements, failed = [], []
        for a in candidates:
            weight = a['effective_weight']
            eligible = [c for c in hosts.values() if not c['archived'] and c['pool'] == a['pool']
                        and c['capacity'] in (15, 30)
                        and (c['min_weight'] is None or weight >= c['min_weight'])
                        and (c['max_weight'] is None or weight <= c['max_weight'])]
            available = [c for c in eligible if trial_counts[c['tag']] < c['capacity']]
            if not available:
                failed.append({'tag': a['tag'], 'reason': 'full' if eligible else 'no_eligible_rule'})
                continue
            chosen = min(available, key=lambda c: (trial_bands[(c['tag'], weight)], trial_totals[c['tag']], trial_counts[c['tag']], c['tag']))['tag']
            if chosen != a['assigned_clan_tag']:
                placements.append({'tag': a['tag'], 'assigned_clan_tag': chosen})
            trial_counts[chosen] += 1
            trial_totals[chosen] += weight
            trial_bands[(chosen, weight)] += 1
        if not failed:
            break
        skipped.extend(failed)
        failed_tags = {a['tag'] for a in failed}
        candidates = [a for a in candidates if a['tag'] not in failed_tags]
        placements = []
    return placements, skipped

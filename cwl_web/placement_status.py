"""Explain planner results without changing placement rules."""
def explain(account, clans, reason):
    fixed = {
        'ready': 'Ready for auto-placement. Preview and apply to assign.',
        'kept': 'Held unassigned. Release keep to allow auto-placement.',
        'missing_weight': 'No weight available. Add a weight or place manually.',
        'source_unavailable': 'Weight source unavailable. Refresh or confirm a manual weight.',
        'full': 'All matching clans are full. Choose another clan manually.',
    }
    if reason in fixed:
        return fixed[reason]
    pools = [c for c in clans if not c['archived'] and c['pool'] == account['pool']]
    if not pools:
        return 'No active hosting clan is configured for this signup pool.'
    sized = [c for c in pools if c['capacity'] in (15,30)]
    if not sized:
        return 'Hosting clans need a 15- or 30-player capacity in Clan settings.'
    weight = account['effective_weight']
    ranges = ', '.join(dict.fromkeys(f"{c['min_weight']/1000:g}k–{c['max_weight']/1000:g}k" for c in sized if c['min_weight'] is not None and c['max_weight'] is not None))
    return f"Weight {weight/1000:g}k is outside matching clan ranges" + (f' ({ranges}).' if ranges else '.')

"""Official clan-weight resolution over the existing durable weight ledger.

Explicit roster/manual overrides remain a caller's responsibility. A saved blank
is intentional Not Available, not permission to revive an older external value.
"""


def saved_sources(db, tags):
    if not tags:
        return {}
    rows = db.execute('SELECT tag,weight,updated_at FROM clan_weight_trial WHERE tag IN (' +
                      ','.join('?' for _ in tags) + ')', tuple(tags)).fetchall()
    return {row['tag']: {'weight': row['weight'], 'source_name': 'Clan weights',
                         'source_modified_at': row['updated_at'],
                         'source_checked_at': row['updated_at']} for row in rows}


async def source_weights(store, provider, tags):
    with store.tx() as db:
        saved = saved_sources(db, tags)
    missing = [tag for tag in tags if tag not in saved]
    external = await provider.weights(missing) if missing else {}
    # Retain external validation at the HTTP boundary, rather than sanitizing it.
    if not isinstance(external, dict):
        return external
    return {**external, **{tag: value for tag, value in saved.items() if value['weight'] is not None}}


def overlay_accounts(store, payload):
    """Apply current saved weights after cache/in-flight reads finish."""
    accounts = payload['accounts']
    with store.tx() as db:
        saved = saved_sources(db, [account['tag'] for account in accounts])
        manual = {row['tag']: row['weight'] for row in db.execute('SELECT tag,weight FROM player_weights WHERE weight IS NOT NULL')}
    return {**payload, 'accounts': [
        {**account, 'war_weight': manual.get(account['tag'], saved.get(account['tag'], {}).get('weight', account.get('war_weight')))}
        for account in accounts]}

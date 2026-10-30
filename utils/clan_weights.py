"""Official clan-weight resolution over the existing durable weight ledger.

The newest saved legacy or linked weight wins; equal instants favor linked rows. A saved blank
is intentional Not Available, not permission to revive an older external value.
"""


def saved_sources(db, tags):
    if not tags:
        return {}
    from .clan_weight_store import effective_weights
    rows = effective_weights(db, tags)
    return {row['tag']: {'weight': row['weight'], 'source_name': row.get('source', 'Clan weights'),
                         'source_modified_at': row['updated_at'],
                         'source_checked_at': row['updated_at'],
                         'weight_revision': row['revision'], 'weight_storages': row.get('storages'),
                         'clan_weight_clan_tag': row['last_clan_tag'],
                         'clan_weight_clan_name': row['last_clan_name'],
                         'clan_weight_saved_at': row['updated_at']} for row in rows.values()}



async def source_weights(store, provider, tags):
    with store.tx() as db:
        saved = saved_sources(db, tags)
    missing = [tag for tag in tags if tag not in saved]
    external = await provider.weights(missing) if missing else {}
    # Retain external validation at the HTTP boundary, rather than sanitizing it.
    if not isinstance(external, dict):
        return external
    return {**{tag: value for tag, value in external.items() if tag in missing}, **{tag: value for tag, value in saved.items() if value['weight'] is not None}}


def overlay_accounts(store, payload):
    """Apply current saved weights after cache/in-flight reads finish."""
    accounts = payload['accounts']
    with store.tx() as db:
        saved = saved_sources(db, [account['tag'] for account in accounts])
        manual = {row['tag']: row['weight'] for row in db.execute('SELECT tag,weight FROM player_weights WHERE weight IS NOT NULL')}
    return {**payload, 'accounts': [
        {**account, 'war_weight': saved[account['tag']]['weight'] if account['tag'] in saved else manual.get(account['tag'], account.get('war_weight'))}
        for account in accounts]}

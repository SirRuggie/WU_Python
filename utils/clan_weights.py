"""Official clan-weight resolution over the existing durable weight ledger.

The newest saved legacy or linked weight wins; equal instants favor linked rows. A saved blank
is intentional Not Available, not permission to revive an older external value.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3


def replacement_saved_weights(source, tags):
    """Targeted, read-only replacement inputs, never a weight-ledger write.

    The caller runs this on a worker thread. A source may be a dashboard Store
    or the bot's configured SQLite path; no dashboard dependency is required.
    An existing blank is an explicit clear; an absent row allows fallback.
    """
    tags = tuple(dict.fromkeys(tags))
    if not tags:
        return {}

    @contextmanager
    def connection():
        if hasattr(source, 'read'):
            with source.read() as db:
                yield db
        elif source:
            from pathlib import Path
            with sqlite3.connect(Path(source).absolute().as_uri() + '?mode=ro',
                                 uri=True, timeout=.2) as db:
                db.row_factory = sqlite3.Row
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                yield db
        else:
            yield None

    with connection() as db:
        if db is None:
            return {}
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        result = {}
        placeholders = ','.join('?' for _ in tags)
        # Lower-precedence manual rows first; official saved rows win even if
        # their timestamp is older. This is this view's accepted D5 order.
        for table in ('player_weights', 'clan_player_weights'):
            if table not in tables:
                continue
            for raw in db.execute(f'SELECT * FROM {table} WHERE tag IN ({placeholders})', tags):
                row = dict(raw)
                result[row['tag']] = {
                    'tag': row['tag'], 'name': row.get('player_name') or row['tag'],
                    'saved_weight': row['weight'], 'saved_at': row.get('updated_at'),
                }
        return result


def replacement_weights(profiles, saved, feed):
    """One precedence rule for HTTP and Discord, with genuine absent fallback."""
    result = {}
    for profile in profiles:
        player = profile['player_tag']
        external = feed.get(player)
        if isinstance(external, dict):
            external = external.get('weight')
        result[player] = (saved[player]['saved_weight'] if player in saved else
                          external if type(external) is int and external > 0 else
                          profile.get('weight'))
    return result


def recruit_weight_groups(tags, saved, *, weights=None, disputed=(), profiles=()):
    """Public metadata and stable group identity, shared by both transports."""
    from utils.replacement_filters import compact_weight
    profile_names = {row['player_tag']: row.get('player_name') for row in profiles}
    accounts = []
    for player in sorted(tags):
        row = saved.get(player, {})
        name = row.get('name')
        if not name or name == player:
            name = profile_names.get(player) or player
        accounts.append({'tag': player, 'name': name,
                         'saved_weight': row.get('saved_weight'),
                         'link_disputed': player in disputed})

    def saved_order(account):
        value = saved[account['tag']].get('saved_at')
        instant = datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
        if instant is not None and instant.tzinfo is None:
            raise ValueError('Saved weight timestamp has no timezone.')
        return (-(instant.astimezone(timezone.utc).timestamp()) if instant else 0,
                account['tag'])

    usable = sorted((account for account in accounts
                     if type(account['saved_weight']) is int and 0 < account['saved_weight'] <= 500000),
                    key=saved_order)
    groups = []
    if weights is None:
        for account in usable[:5]:
            groups.append({'weight': account['saved_weight'], 'source': 'saved',
                           'account_tag': account['tag'], 'link_disputed': account['link_disputed'],
                           'label': f"{account['name']} · {compact_weight(account['saved_weight'])}"})
    else:
        for weight in weights:
            account = next((row for row in usable if row['saved_weight'] == weight), None)
            groups.append({'weight': weight, 'source': 'typed', 'account_tag': None,
                           'link_disputed': bool(account and account['link_disputed']),
                           'label': f"{account['name']} · {compact_weight(weight)}" if account else compact_weight(weight)})
    notice = ('No linked accounts' if not accounts else
              f'Showing 5 of {len(usable)} accounts' if weights is None and len(usable) > 5 else '')
    return {'groups': groups, 'member_accounts': accounts,
            'member_account_total': len(usable),
            'member_accounts_shown': min(5, len(usable)) if weights is None else 0,
            'member_notice': notice}


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
    with store.read() as db:
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
    with store.read() as db:
        saved = saved_sources(db, [account['tag'] for account in accounts])
        manual = {row['tag']: row['weight'] for row in db.execute('SELECT tag,weight FROM player_weights WHERE weight IS NOT NULL')}
    return {**payload, 'accounts': [
        {**account, 'war_weight': saved[account['tag']]['weight'] if account['tag'] in saved else manual.get(account['tag'], account.get('war_weight'))}
        for account in accounts]}

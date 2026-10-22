"""HTTP-facing permission helpers; durable policy lives in utils."""
import json
from utils.dashboard_access import (
    PERMISSIONS, SECTION_SCOPE, CWL_PERMISSIONS, OWNER_IDS, expand_legacy,
    dashboard_allowed,
)


def scopes(store, user_id):
    row = store.one('SELECT permissions FROM grants WHERE user_id=?', (user_id,))
    if not row:
        return []
    try:
        values = json.loads(row['permissions'])
        return [value for value in values if value in PERMISSIONS or value == 'cwl'] if isinstance(values, list) else []
    except (ValueError, TypeError):
        return []


def request_scopes(request, user_id):
    values = scopes(request.app['store'], user_id)
    legacy = expand_legacy(values)
    if 'clans' in values:
        legacy.add('clan_weights')
    return set(request.get('dashboard_permissions', legacy)) if hasattr(request, 'get') else legacy

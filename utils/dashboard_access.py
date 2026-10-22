"""Dashboard access policy and single-document, revisioned Mongo storage.

Discord command authorization remains separate. Role IDs here are effective only
when explicitly granted, and must come from a fresh guild-member lookup.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

OWNER_IDS = frozenset({'505227988229554179', '644005027052126208'})
DOCUMENT_ID = 'dashboard-access-v2'
CWL_PERMISSIONS = {
    'cwl_signups': ('Manage signups', 'Add, change and remove member signups.'),
    'cwl_roster': ('Edit rosters', 'Place accounts, check arrivals and refresh placement weights.'),
    'cwl_publish': ('Publish rosters', 'Make reviewed rosters visible to members.'),
    'cwl_reminders': ('Manage CWL reminders', 'Configure signup and return reminders, including schedules.'),
    'cwl_results': ('Manage results', 'Track and correct attacks and participation.'),
    'cwl_bonuses': ('Manage bonuses', 'Set eligibility, draw winners and approve awards.'),
    'cwl_send': ('Send CWL announcements', 'Post roster and bonus announcements to configured channels.'),
    'cwl_settings': ('Manage CWL settings', 'Manage seasons, signup availability and CWL hosting clans.'),
}
PERMISSIONS = {
    **CWL_PERMISSIONS,
    'clans': ('Manage family clans', 'Edit family clan settings, roles, channels and artwork.'),
    'clan_weights': ('Edit clan weights', 'View, save and export weights for all FWA clans.'),
    'strikes': ('Strike settings and replacements', 'Manage leave, exemptions and replacement priorities.'),
    'strikes_add': ('Add strikes', 'Add strikes and import wars.'),
    'strikes_remove': ('Remove strikes', 'Remove strikes.'),
    'text_commands': ('Command triggers', 'Manage trigger replies and Image Gallery.'),
    'recruitment': ('Recruitment messages', 'Manage applications, questions and staff messages.'),
    'tickets': ('Tickets', 'Read conversations and manage ticket settings and testing.'),
    'member_roles': ('Members & roles', 'Manage ordinary Discord roles within the bot hierarchy.'),
    'fwa': ('FWA tools', 'Manage FWA messages, bases, points and sync reminders.'),
    'server_tools': ('Connections', 'Manage BAND connection and debug controls.'),
}
GROUPS = {
    'CWL management': list(CWL_PERMISSIONS),
    'Clan management': ['clans', 'clan_weights'],
    'Strikes & replacements': ['strikes', 'strikes_add', 'strikes_remove'],
    'Member administration & other tools': ['member_roles', 'recruitment', 'tickets', 'text_commands', 'fwa', 'server_tools'],
}


def expand_legacy(values):
    result = set(values) & set(PERMISSIONS)
    if 'cwl' in values:
        result.update(CWL_PERMISSIONS)
    # Old clan management included weights. Only migration expands that grant.
    return result


def effective(document, user_id, role_ids=()):
    if str(user_id) in OWNER_IDS:
        return set(PERMISSIONS)
    roles = set(map(str, role_ids))
    result = set()
    for grant in document.get('grants', []):
        if (grant['kind'] == 'user' and grant['id'] == str(user_id)) or (grant['kind'] == 'role' and grant['id'] in roles):
            result.update(set(grant['permissions']) & set(PERMISSIONS))
    return result


class AccessConflict(Exception):
    pass


class AccessRepository:
    """One atomic record owns grants, revision and the last 200 changes."""
    def __init__(self, collection):
        self.collection = collection

    async def read(self):
        row = await self.collection.find_one({'_id': DOCUMENT_ID})
        return row if isinstance(row, dict) and row.get('_id') == DOCUMENT_ID else None

    async def save(self, current, *, revision, actor_id, kind, subject_id, permissions, label):
        if actor_id not in OWNER_IDS:
            raise PermissionError('Only dashboard owners can change access.')
        if revision != current['revision']:
            raise AccessConflict('Access changed. Reload before saving.')
        key = (kind, subject_id)
        before = next((g for g in current['grants'] if (g['kind'], g['id']) == key), None)
        after = None if permissions is None else dict(kind=kind, id=subject_id, label=label, permissions=sorted(set(permissions)))
        updated = deepcopy(current)
        updated['grants'] = [g for g in current['grants'] if (g['kind'], g['id']) != key]
        if after:
            updated['grants'].append(after)
        if len(updated['grants']) > 500:
            raise ValueError('Maximum of 500 access entries reached.')
        updated['revision'] += 1
        updated['_id'] = DOCUMENT_ID
        updated.pop('legacy', None)
        updated['history'] = (current.get('history', []) + [dict(
            at=datetime.now(timezone.utc).isoformat(), actor_id=actor_id,
            kind=kind, subject_id=subject_id, before=before, after=after,
        )])[-200:]
        if current.get('legacy'):
            try:
                await self.collection.insert_one(updated)
            except DuplicateKeyError as exc:
                raise AccessConflict('Access changed. Reload before saving.') from exc
        else:
            result = await self.collection.replace_one({'_id': DOCUMENT_ID, 'revision': revision}, updated)
            if result.matched_count != 1:
                raise AccessConflict('Access changed. Reload before saving.')
        return updated


async def dashboard_allowed(actor, section, db):
    scope = SECTION_SCOPE.get(section)
    if not scope and section != 'strikes_read':
        return False
    if str(actor.get('user_id')) in OWNER_IDS:
        return True
    document = await AccessRepository(db.bot_config).read()
    if document is not None:
        permissions = effective(document, actor['user_id'], actor.get('role_ids', ()))
    else:
        grant = await db.bot_config.find_one({'_id': 'dashboard-access:' + actor['user_id']}) or {}
        permissions = expand_legacy(grant.get('permissions', []))
    if 'dashboard_scopes' in actor:
        permissions &= expand_legacy(actor['dashboard_scopes'])
    eligible = {'strikes', 'strikes_add', 'strikes_remove'} if section == 'strikes_read' else {scope}
    return bool(eligible & permissions)


SECTION_SCOPE = {
    'strikes': 'strikes', 'strikes_add': 'strikes_add', 'strikes_remove': 'strikes_remove',
    'clans': 'clans', 'text_commands': 'text_commands',
    **dict.fromkeys(('recruit', 'recruitment_questions', 'recruitment_staff_thread'), 'recruitment'),
    **dict.fromkeys(('ticket_settings', 'ticket_testing'), 'tickets'),
    'roles': 'member_roles', 'band_monitor': 'server_tools',
    **dict.fromkeys(('fwa_war_messages', 'fwa_blacklist', 'fwa_bases', 'fwa_points', 'fwa_sync', 'fwa_weight'), 'fwa'),
    'cwl': 'cwl_reminders', 'cwl_rosters': 'cwl_reminders',
}

"""Named dashboard grants, separate from native Discord command permissions."""
import json

PERMISSIONS = {
    'clans': ('Clan management', 'Add, remove and update family clans, roles, channels and artwork.'),
    'text_commands': ('Command triggers', 'Create trigger replies and manage Image Gallery.'),
    'cwl': ('CWL management', 'Seasons, clans, rosters, messages, reminders, results and exports.'),
    'recruitment': ('Recruitment messages', 'Application messages, questions and staff messages.'),
    'tickets': ('Tickets', 'Read ticket conversations; manage ticket channels, access and testing.'),
    'member_roles': ('Members & roles', 'Add or remove Discord roles within the role hierarchy.'),
    'fwa': ('FWA tools', 'War messages, bases, points, weights, blacklist and sync reminders.'),
    'server_tools': ('Connections', 'BAND connection status and debug controls.'),
}
SECTION_SCOPE = {
    'clans': 'clans',
    'text_commands': 'text_commands',
    **dict.fromkeys(('recruit', 'recruitment_questions', 'recruitment_staff_thread'), 'recruitment'),
    **dict.fromkeys(('ticket_settings', 'ticket_testing'), 'tickets'),
    'roles': 'member_roles', 'band_monitor': 'server_tools',
    **dict.fromkeys(('fwa_war_messages', 'fwa_blacklist', 'fwa_bases', 'fwa_points', 'fwa_sync', 'fwa_weight'), 'fwa'),
    'cwl': 'cwl', 'cwl_rosters': 'cwl',
}

def scopes(store, user_id):
    row = store.one('SELECT permissions FROM grants WHERE user_id=?', (user_id,))
    if not row:
        return []
    try:
        values = json.loads(row['permissions'])
        return [value for value in values if value in PERMISSIONS] if isinstance(values, list) else []
    except (ValueError, TypeError):
        return []

async def dashboard_allowed(actor, section, db):
    scope = SECTION_SCOPE.get(section)
    if not scope:
        return False
    if actor.get('guild_owner') or actor.get('user_id') == '505227988229554179':
        return True
    grant = await db.bot_config.find_one({'_id': 'dashboard-access:' + actor['user_id']}) or {}
    permissions = grant.get('permissions', [])
    # Web requests also check local grants; queued actions reread shared grants.
    return scope in permissions and ('dashboard_scopes' not in actor or scope in actor['dashboard_scopes'])

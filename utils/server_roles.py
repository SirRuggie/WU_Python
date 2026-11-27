"""Single guild-owned self-select server-role list in bot_config.

Discord transport/authorization belongs to the caller. This module owns list
validation, revision CAS and the insert-only seed boundary.
"""
from copy import deepcopy
from datetime import datetime, timezone
import re

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


CONFLICT_MESSAGE = 'These roles changed. Refresh and review your edit.'
_ID = re.compile(r'[1-9][0-9]{0,19}')


class ServerRolesConflict(ValueError):
    """The reviewed revision no longer owns the list."""


class ServerRoleOverlap(ValueError):
    def __init__(self, conflicts):
        super().__init__('This role is already used for a Town Hall.')
        self.conflicts = deepcopy(conflicts)


async def town_hall_conflicts(mongo, guild_id, entries):
    from utils.town_halls import load_roles, cross_role_conflicts
    roles = await load_roles(mongo, guild_id)
    return cross_role_conflicts(roles['roles'], entries)


async def panel_roles(mongo, guild_id):
    """Legacy overlaps are TH-owned and must never appear in this menu."""
    row = await load(mongo, guild_id)
    conflicts = await town_hall_conflicts(mongo, guild_id, row['roles'])
    hidden = {item['role_id'] for item in conflicts}
    return [entry for entry in row['roles'] if entry['role_id'] not in hidden]


def key(guild_id):
    value = str(guild_id)
    if isinstance(guild_id, bool) or not _ID.fullmatch(value) or int(value) > 2**64 - 1:
        raise ValueError('Use a valid server ID.')
    return 'server_roles:' + value


def validate(entries):
    if not isinstance(entries, list) or len(entries) > 25:
        raise ValueError('Select at most 25 server roles.')
    seen = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or set(item) != {'role_id', 'label', 'short_line', 'order'}:
            raise ValueError('Review every server role field.')
        role = item['role_id']
        if not isinstance(role, str) or not _ID.fullmatch(role) or int(role) > 2**64 - 1 or role in seen:
            raise ValueError('Select each valid Discord role only once.')
        seen.add(role)
        if type(item['order']) is not int or item['order'] != index:
            raise ValueError('Review the server role order.')
        for field, maximum, required in [('label', 40, True), ('short_line', 100, False)]:
            value = item[field]
            if (not isinstance(value, str) or len(value) > maximum or '\n' in value or '\r' in value
                    or (required and not value.strip())):
                raise ValueError(f'Keep {field.replace("_", " ")} within {maximum} characters.')
    return deepcopy(entries)


async def load(mongo, guild_id):
    row = await mongo.bot_config.find_one({'_id': key(guild_id)})
    if row is None:
        return {'revision': 0, 'roles': [], 'exists': False}
    if type(row.get('revision')) is not int or row['revision'] < 0:
        raise ValueError('The server roles revision is invalid.')
    return {'revision': row['revision'], 'roles': validate(row.get('roles')), 'exists': True}


async def save(mongo, guild_id, entries, user_id, expected_revision):
    from utils.town_halls import role_configuration_guard
    async with role_configuration_guard(guild_id):
        entries = validate(entries)
        if type(expected_revision) is not int or not 0 <= expected_revision < 2**63 - 1:
            raise ValueError('Use a valid server roles revision.')
        identifier = key(guild_id)
        current = await load(mongo, guild_id)
        if current['revision'] != expected_revision:
            raise ServerRolesConflict(CONFLICT_MESSAGE)
        conflicts = await town_hall_conflicts(mongo, guild_id, entries)
        if conflicts:
            raise ServerRoleOverlap(conflicts)
        fields = {'roles': entries, 'revision': expected_revision + 1,
                  'updated_by': int(user_id), 'updated_at': datetime.now(timezone.utc)}
        if not current['exists']:
            try:
                await mongo.bot_config.insert_one({'_id': identifier, **fields})
            except DuplicateKeyError:
                raise ServerRolesConflict(CONFLICT_MESSAGE) from None
            return {'revision': fields['revision'], 'roles': entries, 'exists': True}
        saved = await mongo.bot_config.find_one_and_update(
            {'_id': identifier, 'revision': expected_revision}, {'$set': fields},
            upsert=False, return_document=ReturnDocument.AFTER)
        if saved is None:
            raise ServerRolesConflict(CONFLICT_MESSAGE)
        return {'revision': saved['revision'], 'roles': validate(saved['roles']), 'exists': True}


async def seed(mongo, guild_id, entries, *, apply=False):
    from utils.town_halls import role_configuration_guard
    """Dry-run by default; seed once without replacing an existing list."""
    async with role_configuration_guard(guild_id):
        entries = validate(entries)
        before = await load(mongo, guild_id)
        proposed_entries = before['roles'] if before['exists'] else entries
        conflicts = await town_hall_conflicts(mongo, guild_id, proposed_entries)
        if conflicts:
            if apply:
                raise ServerRoleOverlap(conflicts)
            return {'status': 'conflict', 'applied': False, 'before': before, 'proposed': {'roles': proposed_entries}, 'conflicts': conflicts}
        if before['exists']:
            return {'status': 'already migrated', 'applied': False, 'before': before, 'proposed': before}
        proposed = {'revision': 1, 'roles': entries, 'exists': True}
        if not apply:
            return {'status': 'dry run', 'applied': False, 'before': before, 'proposed': proposed}
        try:
            await mongo.bot_config.insert_one({'_id': key(guild_id), 'revision': 1, 'roles': entries,
                                              'updated_at': datetime.now(timezone.utc)})
        except DuplicateKeyError:
            raise ServerRolesConflict(CONFLICT_MESSAGE) from None
        return {'status': 'migrated', 'applied': True, 'before': before, 'proposed': proposed}

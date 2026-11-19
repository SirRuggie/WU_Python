"""Mongo persistence for war reminders, shared by the worker and web API.

Collections follow bot_config's configured database. Settings and receipt IDs
are permanent: deleting receipts could replay notifications after a restart.
"""

from utils.mongo_routes import collection_from
from datetime import datetime, timezone

import pymongo
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern
from utils.war_reminder_health import timestamp, settings_identity, checked_settings


def _status_value(value):
    """Compare persisted/fresh dates in the representation BSON can retain."""
    if isinstance(value, datetime):
        value = timestamp(value)
        return value.replace(microsecond=value.microsecond // 1000 * 1000)
    return value


class SettingsConflict(Exception):
    """Another editor saved this clan after the caller read its settings."""


def collection(db, name='war_reminder_settings'):
    return collection_from(db.bot_config, name, write_concern=WriteConcern(w='majority'))


class WarReminderStore:
    def __init__(self, db):
        self.db = db
        self.settings = collection(db)
        self.status = collection(db, 'war_reminder_status')
        self.deliveries = collection(db, 'war_reminder_deliveries')

    async def ensure_indexes(self):
        with pymongo.timeout(30):
            await self.deliveries.create_index(
                [('clan_tag', 1), ('at', -1)], name='clan_delivery_history'
            )
        with pymongo.timeout(30):
            await self.settings.create_index('enabled', name='enabled_reminders')

    async def family_overview(self):
        clans = await self.db.clans.find({}).sort('name', 1).to_list(length=None)
        tags = [row['tag'] for row in clans]
        if not tags:
            return []
        configs = {row['_id']: row for row in await self.settings.find({'_id': {'$in': tags}}).to_list(length=None)}
        states = {row['_id']: row for row in await self.status.find({'_id': {'$in': tags}}).to_list(length=None)}
        # Tests must never make a scheduled reminder look healthy or broken.
        cursor = await self.deliveries.aggregate([
            {'$match': {'clan_tag': {'$in': tags}, 'test': False}},
            {'$sort': {'clan_tag': 1, 'at': -1}},
            {'$group': {'_id': '$clan_tag', 'latest': {'$first': '$$ROOT'}}},
            {'$project': {'latest.status': 1, 'latest.at': 1, 'latest.event': 1}},
        ], maxTimeMS=10000)
        latest = {row['_id']: row['latest'] for row in await cursor.to_list(length=None)}
        return [(row, configs.get(row['tag']), states.get(row['tag']), latest.get(row['tag'])) for row in clans]

    async def copy_targets(self):
        clans = await self.db.clans.find({}).sort('name', 1).to_list(length=None)
        tags = [clan['tag'] for clan in clans]
        configs = {row['_id']: row for row in await self.settings.find(
            {'_id': {'$in': tags}}).to_list(length=None)}
        return [(clan, configs.get(clan['tag'])) for clan in clans]

    async def clan(self, tag):
        return await self.db.clans.find_one({'tag': tag})

    async def clan_exists(self, tag):
        """Worker membership check; web editors still need the full clan row."""
        return await self.db.clans.find_one({'tag': tag}, {'_id': 1}) is not None

    async def get_settings(self, tag):
        return await self.settings.find_one({'_id': tag})

    async def enabled_settings(self):
        with pymongo.timeout(30):
            return await self.settings.find({'enabled': True}).to_list(length=None)

    async def save_settings(self, tag, before, values, actor, *, history_context=None, history_names=None):
        event_id = None
        if history_context is not None:
            from utils.clan_dashboard_history import audit
            from utils.war_reminders import settings
            clan, identity = history_context
            previous = settings(before)
            event_id = await audit(self.db, identity, 'reminders',
                                   {**clan, 'reminder_settings': previous})
        query = {'_id': tag, 'version': before.get('version') if before else {'$exists': False}}
        update = {'$set': {**values, 'updated_by': actor, 'updated_at': datetime.now(timezone.utc)}, '$inc': {'version': 1}}
        try:
            result = await self.settings.update_one(query, update, upsert=before is None)
            if not result.matched_count and not result.upserted_id:
                raise SettingsConflict
        except Exception as exc:
            if event_id:
                from utils.clan_dashboard_history import abandon_change
                await abandon_change(self.db, event_id)
            if isinstance(exc, DuplicateKeyError):
                raise SettingsConflict from exc
            raise
        if event_id:
            from utils.clan_dashboard_history import finish_change
            await finish_change(self.db, event_id,
                                {key: previous.get(key) for key in values}, values, names=history_names)

    async def recent_deliveries(self, tag, limit=15):
        return await self.deliveries.find({'clan_tag': tag}, {'_id': 0}).sort('at', -1).limit(limit).to_list(length=limit)

    async def latest_scheduled_delivery(self, tag):
        rows = await self.deliveries.find({'clan_tag': tag, 'test': False}, {'_id': 0}).sort('at', -1).limit(1).to_list(length=1)
        return rows[0] if rows else None

    async def get_status(self, tag):
        return await self.status.find_one({'_id': tag}, {'_id': 0})

    async def record_status(self, tag, *, settings_updated_at=None, settings_version=None, **values):
        """Persist the actual scanned identity; reject late older results atomically.

        Legacy rows gain identity on their first bound scan. Unbound callers
        cannot overwrite a bound result. Same-identity liveness refreshes every
        120 s; a new identity or a real status change writes immediately.
        """
        bound = settings_updated_at is not None or settings_version is not None
        identity = settings_identity(settings_updated_at, settings_version)
        config = {'updated_at': settings_updated_at, 'version': settings_version}
        while True:
            before = await self.status.find_one({'_id': tag})
            marked = before is not None and 'settings_updated_at' in before and 'settings_version' in before
            if marked:
                stored = settings_identity(before['settings_updated_at'], before['settings_version'])
                if not bound:
                    return False
                # Versions are monotonic even for edits within one BSON ms or
                # a backwards wall clock. Unknown versions cannot replace one.
                if stored[1] is not None:
                    if identity[1] is None or identity[1] < stored[1]:
                        return False
                if identity[1] == stored[1] and stored[0] is not None:
                    if identity[0] is None or identity[0] < stored[0]:
                        return False
            status = {key: value for key, value in values.items() if key != 'checked_at'}
            if values.get('error') == 'Maintenance':
                status['maintenance_since'] = (before or {}).get('maintenance_since') or values['checked_at']
            same_identity = checked_settings(config, before) if bound and before else not bound
            checked = values.get('checked_at')
            previous = before.get('checked_at') if before else None
            # The observed clock remains in the CAS below. After any race we
            # reread and reject an older result, even if its status differs.
            # BSON-ms ties retain the existing status-change behavior.
            if (same_identity and isinstance(checked, datetime) and isinstance(previous, datetime)
                    and _status_value(checked) < _status_value(previous)):
                return False
            if before is not None and same_identity and all(
                    _status_value(before.get(key)) == _status_value(value)
                    for key, value in status.items()):
                updated = identity[0]
                settings_checked = updated is None or (
                    isinstance(previous, datetime) and _status_value(previous) >= updated)
                if checked is None and settings_checked:
                    return False
                if settings_checked and isinstance(checked, datetime) and isinstance(previous, datetime):
                    if 0 <= (timestamp(checked) - timestamp(previous)).total_seconds() < 120:
                        return False
            saved = dict(values)
            if values.get('error') == 'Maintenance':
                saved['maintenance_since'] = status['maintenance_since']
            if bound:
                saved.update(settings_updated_at=identity[0], settings_version=identity[1])
            # Match the exact observation so a newer scan winning after our
            # read cannot be overwritten by this result. Retry against its row.
            query = {'_id': tag}
            for key in ('checked_at', 'settings_updated_at', 'settings_version', 'maintenance_since', 'war_start'):
                query[key] = before[key] if before and key in before else {'$exists': False}
            try:
                result = await self.status.update_one(query, {'$set': saved}, upsert=before is None)
            except DuplicateKeyError:
                if before is not None:
                    raise
                continue  # Another scan inserted this clan before our upsert.
            if result.matched_count or result.upserted_id is not None:
                return True

    async def current_maintenance_window(self, config, maintenance_since, war_start):
        """Fresh read boundary for clearing the original recovery window."""
        tag = config['_id']
        fresh = await self.get_settings(tag)
        if (not fresh or not fresh.get('enabled')
                or settings_identity(fresh.get('updated_at'), fresh.get('version'))
                != settings_identity(config.get('updated_at'), config.get('version'))
                or not await self.clan_exists(tag)):
            return False
        state = await self.get_status(tag) or {}
        since = timestamp(maintenance_since)
        return (since is not None and state.get('error') is None
                and checked_settings(fresh, state)
                and _status_value(state.get('maintenance_since')) == _status_value(since)
                and _status_value(state.get('war_start')) == _status_value(war_start))

    async def clear_maintenance(self, config, maintenance_since, war_start):
        """Clear ONLY the original paused window, not one observed during delivery."""
        if not await self.current_maintenance_window(config, maintenance_since, war_start):
            return False
        updated, version = settings_identity(config.get('updated_at'), config.get('version'))
        result = await self.status.update_one(
            {'_id': config['_id'], 'maintenance_since': timestamp(maintenance_since),
             'war_start': timestamp(war_start), 'settings_updated_at': updated,
             'settings_version': version, 'error': None},
            {'$set': {'maintenance_since': None}},
        )
        return bool(result.matched_count)

    async def delivered_or_claimed(self, key):
        return await self.deliveries.find_one({'_id': key}) is not None

    async def claim_delivery(self, key, **values):
        try:
            await self.deliveries.insert_one({'_id': key, **values})
        except DuplicateKeyError:
            return False
        return True

    async def finish_delivery(self, key, **values):
        await self.deliveries.update_one({'_id': key}, {'$set': values})


def occurrence_key(clan_tag, war_start, event):
    # End time can shift during maintenance; the original start identifies a war.
    return f'{clan_tag}:{int(war_start.timestamp())}:{event}'

"""Mongo persistence for war reminders, shared by the worker and web API.

Collections follow bot_config's configured database. Settings and receipt IDs
are permanent: deleting receipts could replay notifications after a restart.
"""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern


class SettingsConflict(Exception):
    """Another editor saved this clan after the caller read its settings."""


def collection(db, name='war_reminder_settings'):
    return db.bot_config.database.get_collection(
        name, write_concern=WriteConcern(w='majority', wtimeout=10000)
    )


class WarReminderStore:
    def __init__(self, db):
        self.db = db
        self.settings = collection(db)
        self.status = collection(db, 'war_reminder_status')
        self.deliveries = collection(db, 'war_reminder_deliveries')

    async def ensure_indexes(self):
        await self.deliveries.create_index(
            [('clan_tag', 1), ('at', -1)], name='clan_delivery_history'
        )
        await self.settings.create_index('enabled', name='enabled_reminders')

    async def clan(self, tag):
        return await self.db.clans.find_one({'tag': tag})

    async def get_settings(self, tag):
        return await self.settings.find_one({'_id': tag})

    async def enabled_settings(self):
        return await self.settings.find({'enabled': True}).to_list(length=None)

    async def save_settings(self, tag, before, values, actor):
        query = {'_id': tag, 'version': before.get('version') if before else {'$exists': False}}
        update = {'$set': {**values, 'updated_by': actor, 'updated_at': datetime.now(timezone.utc)}, '$inc': {'version': 1}}
        try:
            result = await self.settings.update_one(query, update, upsert=before is None)
        except DuplicateKeyError as exc:
            raise SettingsConflict from exc
        if not result.matched_count and not result.upserted_id:
            raise SettingsConflict

    async def recent_deliveries(self, tag, limit=15):
        return await self.deliveries.find({'clan_tag': tag}, {'_id': 0}).sort('at', -1).limit(limit).to_list(length=limit)

    async def get_status(self, tag):
        return await self.status.find_one({'_id': tag}, {'_id': 0})

    async def record_status(self, tag, **values):
        await self.status.update_one({'_id': tag}, {'$set': values}, upsert=True)

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

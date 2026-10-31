"""Single owner for bounded player_activity documents and optimistic writes."""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from utils.player_activity import observe
from utils.strike_store import tag, utc


class PlayerActivityStore:
    def __init__(self, mongo):
        self.collection = mongo.player_activity

    async def ensure_indexes(self):
        # TTL creation is reserved for the backup-verified retention migration.
        await self.collection.create_index('current_clan_tag', name='activity_family_clan')

    async def all_players(self):
        return await self.collection.find({}).to_list(length=None)

    async def mark_seed_attempt(self, player_tag, status, version):
        await self.collection.update_one(
            {'_id': tag(player_tag)},
            {'$set': {'seed_job_version': version, 'seed_status': status,
                      'seed_attempted_at': datetime.now(timezone.utc)}, '$inc': {'revision': 1}})

    async def get(self, player_tag):
        return await self.collection.find_one({'_id': tag(player_tag)})

    async def record(self, player: dict, clan_tag: str, *, now=None):
        now = utc(now or datetime.now(timezone.utc))
        key = tag(player['tag'])
        clan = tag(clan_tag)
        for _ in range(5):
            previous = await self.get(key)
            if previous and previous.get('updated_at') and utc(previous['updated_at']) >= now:
                return False  # Do not let a late API response roll the baseline back.
            state = observe(previous, player, now=now)
            state.update(_id=key, tag=key, current_clan_tag=clan, left_at=None,
                         revision=int((previous or {}).get('revision', 0)) + 1)
            if previous is None:
                try:
                    await self.collection.insert_one(state)
                    return True
                except DuplicateKeyError:
                    continue
            result = await self.collection.replace_one(
                {'_id': key, 'revision': previous['revision']}, state)
            if result.matched_count:
                return True
        raise RuntimeError('Player activity changed concurrently')

    async def seed(self, player_tag, seen_at, *, now=None):
        now = utc(now or datetime.now(timezone.utc))
        seen_at = utc(seen_at)
        if seen_at > now:
            return False
        # One-time, idempotent and conditional: never replace our own observation
        # or another successful seed, including a concurrent official update.
        result = await self.collection.update_one(
            {'_id': tag(player_tag), 'last_seen_at': {'$exists': False}},
            {'$set': {'last_seen_at': seen_at, 'last_seen_source': 'clashking_seed'}, '$inc': {'revision': 1}})
        return bool(result.modified_count)

    async def reconcile_membership(self, members: dict[str, str], *, now=None):
        """Only call after a complete successful family-roster sweep."""
        now = utc(now or datetime.now(timezone.utc))
        members = {tag(player): tag(clan) for player, clan in members.items()}
        for row in await self.collection.find({}).to_list(length=None):
            key = row['_id']
            fields = ({'current_clan_tag': members[key], 'left_at': None,
                       'previous_roster_at': row.get('last_roster_at'),
                       'last_roster_at': now,
                       'family_since': (row.get('family_since') or now) if not row.get('left_at') else now}
                      if key in members else
                      {'current_clan_tag': None, 'left_at': row.get('left_at') or now,
                       'previous_roster_at': None, 'last_roster_at': None})
            await self.collection.update_one({'_id': key, 'revision': row['revision']},
                                             {'$set': fields, '$inc': {'revision': 1}})

    async def record_weekend(self, player_tag, weekend_id: str, attacks: int, *, observed_member: bool):
        if not isinstance(attacks, int) or isinstance(attacks, bool) or attacks < 0:
            raise ValueError('Raid attacks must be a non-negative integer')
        # Historical logs prove attacks, never absence or membership.
        if not attacks and not observed_member:
            return False
        for _ in range(5):
            row = await self.get(player_tag)
            if row is None:
                return False
            weekends = {item['weekend_id']: item for item in row.get('raid_weekends', [])}
            existing = weekends.get(weekend_id, {})
            count = max(attacks, existing.get('attacks', 0))
            weekends[weekend_id] = {'weekend_id': weekend_id, 'attacked': count > 0, 'attacks': count}
            recent = [weekends[key] for key in sorted(weekends)[-8:]]
            result = await self.collection.update_one(
                {'_id': row['_id'], 'revision': row['revision']},
                {'$set': {'raid_weekends': recent}, '$inc': {'revision': 1}})
            if result.matched_count:
                return True
        raise RuntimeError('Raid activity changed concurrently')

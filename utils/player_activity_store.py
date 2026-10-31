"""Single owner for bounded player_activity documents and optimistic writes."""
from datetime import datetime, timedelta, timezone
import logging

log = logging.getLogger(__name__)

from pymongo.errors import DuplicateKeyError

from utils.player_activity import observe, baseline
from utils.player_activity_raids import latest_raid_end
from utils.strike_store import tag, utc


class PlayerActivityStore:
    def __init__(self, mongo):
        self.collection = mongo.player_activity
        self._roster_seen = {}

    async def ensure_indexes(self):
        # TTL creation is reserved for the backup-verified retention migration.
        await self.collection.create_index('current_clan_tag', name='activity_family_clan')

    async def all_players(self):
        return await self.collection.find({}).to_list(length=None)

    async def overview(self):
        """Read only page signals, never the large per-unit diff baseline."""
        fields = {key: 1 for key in ('tag', 'name', 'current_clan_tag', 'left_at',
                                    'last_seen_at', 'last_seen_source', 'tracking_started_at',
                                    'raid_weekends', 'updated_at', 'baseline.townHallLevel')}
        return await self.collection.find({}, fields).to_list(length=None)

    async def mark_seed_attempt(self, player_tag, status, version):
        await self.collection.update_one(
            {'_id': tag(player_tag)},
            {'$set': {'seed_job_version': version, 'seed_status': status,
                      'seed_attempted_at': datetime.now(timezone.utc)}, '$inc': {'revision': 1, 'seed_attempts': 1}})

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
            if (previous and previous.get('current_clan_tag') == clan and not previous.get('left_at')
                    and previous.get('updated_at') and utc(previous['updated_at']).date() == now.date()
                    and all(previous.get('baseline', {}).get(key) == value for key, value in baseline(player).items())):
                return False
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

    async def known_members(self, clan_tag):
        rows = await self.collection.find({'current_clan_tag': tag(clan_tag), 'left_at': None},
                                          {'tag': 1, 'current_clan_tag': 1}).to_list(length=None)
        return {row.get('tag', row['_id']): tag(clan_tag) for row in rows}

    async def reconcile_membership(self, members: dict[str, str], *, now=None):
        """A complete sweep; persist daily, on membership changes, or at raid boundaries."""
        now = utc(now or datetime.now(timezone.utc))
        members = {tag(player): tag(clan) for player, clan in members.items()}
        ended = latest_raid_end(now)
        upcoming = (ended+timedelta(days=7)).isoformat()
        seen = {}
        for row in await self.collection.find({}).to_list(length=None):
            key = row['_id']
            if key in members:
                previous = self._roster_seen.get(key)
                if previous is None and row.get('last_roster_at') and not row.get('left_at'):
                    previous = (utc(row['last_roster_at']), row.get('current_clan_tag'))
                since = (row.get('family_since') or now) if not row.get('left_at') else now
                evidence = set(row.get('raid_membership_ends', []))
                if (previous and previous[0] <= ended <= now and now-previous[0] <= timedelta(minutes=90)
                        and utc(since) <= ended and not row.get('left_at')):
                    evidence.add(ended.isoformat())
                histories = {item['weekend_id']: set(item['clan_tags']) for item in row.get('raid_clan_history', [])}
                histories.setdefault(upcoming, set()).add(members[key])
                # Include the last observed clan when a move brackets the end.
                if ended.isoformat() in evidence and previous and previous[1]:
                    histories.setdefault(ended.isoformat(), set()).update((previous[1], members[key]))
                history = [{'weekend_id': end, 'clan_tags': sorted(histories[end])} for end in sorted(histories)[-9:]]
                fields = {'current_clan_tag': members[key], 'left_at': None, 'family_since': since,
                          'raid_membership_ends': sorted(evidence)[-8:], 'raid_clan_history': history}
                daily = not row.get('last_roster_at') or utc(row['last_roster_at']).date() != now.date()
                changed = any(row.get(field) != value for field, value in fields.items())
                if daily or changed:
                    fields.update(previous_roster_at=previous[0] if previous else row.get('last_roster_at'), last_roster_at=now)
                seen[key] = (now, members[key])
            else:
                fields = {'current_clan_tag': None, 'left_at': row.get('left_at') or now,
                          'previous_roster_at': None, 'last_roster_at': None}
            if all(row.get(field) == value for field, value in fields.items()):
                continue
            result = await self.collection.update_one({'_id': key, 'revision': row['revision']},
                                                       {'$set': fields, '$inc': {'revision': 1}})
            if not result.matched_count:
                log.warning('Player activity membership CAS conflict: %s', key)
        self._roster_seen = seen

    async def record_weekend(self, player_tag, weekend_id, attacks, *, observed_member):
        return await self.merge_raid_observations(player_tag, {weekend_id: (attacks, observed_member)}, [])

    async def merge_raid_observations(self, player_tag, observations, checked, reviewed=()):
        for attacks, observed in observations.values():
            if type(attacks) is not int or attacks < 0:
                raise ValueError('Raid attacks must be a non-negative integer')
        for _ in range(5):
            row = await self.get(player_tag)
            if row is None:
                return False
            weekends = {item['weekend_id']: item for item in row.get('raid_weekends', [])}
            for weekend, (attacks, observed) in observations.items():
                if not attacks and not observed:
                    continue
                count = max(attacks, weekends.get(weekend, {}).get('attacks', 0))
                weekends[weekend] = {'weekend_id': weekend, 'attacked': count > 0, 'attacks': count}
            recent = [weekends[key] for key in sorted(weekends)[-8:]]
            checked_ids = sorted(set(row.get('raid_checked_weekends', [])) | set(checked))[-8:]
            reviewed_ids = sorted(set(row.get('raid_logs_reviewed', [])) | set(reviewed))[-8:]
            if (recent == row.get('raid_weekends', []) and checked_ids == row.get('raid_checked_weekends', [])
                    and reviewed_ids == row.get('raid_logs_reviewed', [])):
                return False
            result = await self.collection.update_one(
                {'_id': row['_id'], 'revision': row['revision']},
                {'$set': {'raid_weekends': recent, 'raid_checked_weekends': checked_ids, 'raid_logs_reviewed': reviewed_ids}, '$inc': {'revision': 1}})
            if result.matched_count:
                return True
        raise RuntimeError('Raid activity changed concurrently')

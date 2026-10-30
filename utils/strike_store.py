"""Durable account strike ledger. War inputs are normalized by strike_wars.

No TTL indexes: expiry affects active counts, never the audit record. Automatic
writes use a deterministic primary key, so concurrent scans cannot double count.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from utils import recruit_links

DEFAULT_EXEMPT_ROLE = 769130325460254740
STRIKE_LIMIT = 4
REPLACEMENT_GRACE = timedelta(hours=48)
STRIKE_DAYS = 60
IMPORT_DAYS = 60


class StrikeConflict(RuntimeError):
    """The edit was based on an older durable revision."""


def revision_match(revision: int) -> dict:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError('Use a non-negative revision.')
    return ({'$or': [{'revision': 0}, {'revision': {'$exists': False}}]}
            if revision == 0 else {'revision': revision})


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError('A valid war end time is required.')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def tag(value: str) -> str:
    cleaned = str(value or '').strip().upper().lstrip('#')
    if not 3 <= len(cleaned) <= 15 or any(char not in '0289PYLQGRJCUV' for char in cleaned):
        raise ValueError('Enter a valid Clash player or clan tag.')
    return '#' + cleaned


def stamp(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return utc(value)


def status_of(row: dict, now: datetime | None = None) -> str:
    if row.get('revoked_at'):
        return 'removed'
    if row.get('kind') == 'cwl':
        return 'recorded'
    if row.get('kind') == 'missed':
        return 'missed'
    if row.get('kind') == 'exempt':
        return 'exempt'
    if row.get('kind') == 'completed':
        return 'completed'
    if utc(row['expires_at']) <= utc(now or datetime.now(timezone.utc)):
        return 'expired'
    return 'active'


def war_key(war: dict) -> str:
    # Normalizer requires both tags and an actual end time. No array index,
    # state, or API response ordering enters the identity.
    clan = tag(war['clan_tag'])
    opponent = tag(war['opponent_tag'])
    ended = stamp(war['end_time']).isoformat()
    return f'{clan}:{opponent}:{ended}'


def validate_war(war: dict, *, now: datetime | None = None) -> None:
    if war.get('type') != 'regular' or war.get('state') != 'warEnded':
        raise ValueError('Only ended regular wars are eligible.')
    if war.get('attacks_per_member') != 2:
        raise ValueError('Only two-attack wars are eligible.')
    if war.get('complete') is not True:
        raise ValueError('War data is incomplete.')
    end = stamp(war['end_time'])
    if end > utc(now or datetime.now(timezone.utc)):
        raise ValueError('War has not ended.')
    war_key(war)
    members = war.get('members')
    if not isinstance(members, list) or not members:
        raise ValueError('War roster is incomplete.')
    tags = set()
    for member in members:
        player = tag(member['tag'])
        if player in tags:
            raise ValueError('War roster has duplicate accounts.')
        tags.add(player)
        attacks = member.get('attacks')
        if not isinstance(attacks, int) or not 0 <= attacks <= 2:
            raise ValueError('Attack count is incomplete.')


def validate_cwl_war(war: dict, *, now: datetime | None = None) -> None:
    """CWL history is a separate one-attack record, never a strike source."""
    if war.get('type') != 'cwl' or war.get('state') != 'warEnded':
        raise ValueError('Only ended CWL wars are eligible for CWL history.')
    if war.get('attacks_per_member') != 1 or war.get('complete') is not True:
        raise ValueError('Complete one-attack CWL data is required.')
    tag(war['clan_tag'])
    tag(war['opponent_tag'])
    tag(war['war_tag'])
    if stamp(war['end_time']) > utc(now or datetime.now(timezone.utc)):
        raise ValueError('CWL war has not ended.')
    members = war.get('members')
    if not isinstance(members, list) or not members:
        raise ValueError('CWL roster is incomplete.')
    seen = set()
    for member in members:
        player = tag(member['tag'])
        if player in seen:
            raise ValueError('CWL roster has duplicate accounts.')
        seen.add(player)
        attacks = member.get('attacks')
        if not isinstance(attacks, int) or isinstance(attacks, bool) or attacks not in (0, 1):
            raise ValueError('CWL attack count is incomplete.')


def cwl_war_key(war: dict) -> str:
    validate_cwl_war(war)
    return f"cwl:{tag(war['clan_tag'])}:{tag(war['war_tag'])}:{stamp(war['end_time']).isoformat()}"


class StrikeService:
    def __init__(self, mongo, *, link_resolver=None, role_resolver=None):
        self.mongo = mongo
        self.link_resolver = link_resolver or recruit_links.resolve_players
        # role_resolver(guild_id, member_id) -> iterable of role IDs or None.
        # Unknown roles defer automatic strikes rather than bypass exclusions.
        self.role_resolver = role_resolver

    async def ensure_indexes(self):
        await self.mongo.strike_records.create_index([('guild_id', 1), ('player_tag', 1), ('occurred_at', -1)])
        await self.mongo.strike_records.create_index([('guild_id', 1), ('member_id', 1), ('occurred_at', -1)])
        await self.mongo.strike_records.create_index([('guild_id', 1), ('clan_tag', 1), ('occurred_at', -1)])
        # Stable history pages and exact-war dedup probes used by Find war.
        await self.mongo.strike_records.create_index([('guild_id', 1), ('kind', 1), ('occurred_at', -1), ('_id', 1)])
        await self.mongo.strike_records.create_index([('guild_id', 1), ('war_key', 1)])
        await self.mongo.strike_profiles.create_index([('guild_id', 1), ('player_tag', 1)])
        await self.mongo.strike_profiles.create_index([('guild_id', 1), ('current_clan_tag', 1)])
        await self.mongo.strike_profiles.create_index([('guild_id', 1), ('departed_last_seen_at', 1)])
        await self.mongo.strike_imports.create_index('expires_at', expireAfterSeconds=0)
        await self.mongo.strike_leave_history.create_index(
            [('guild_id', 1), ('member_id', 1), ('starts_at', -1)])

    async def settings(self, guild_id: int) -> dict:
        saved = await self.mongo.strike_settings.find_one({'_id': str(int(guild_id))})
        return {'guild_id': int(guild_id), 'exempt_role_ids': [DEFAULT_EXEMPT_ROLE],
                'strike_limit': STRIKE_LIMIT, 'revision': 0,
                **(saved or {}), 'retention_days': STRIKE_DAYS}

    async def monitor_activation(self, guild_id: int) -> datetime:
        """Persist the live-monitor launch boundary before reading any wars."""
        key = str(int(guild_id))
        now = datetime.now(timezone.utc)
        await self.mongo.strike_settings.update_one({'_id': key},
            {'$setOnInsert': {'guild_id': int(guild_id),
                              'exempt_role_ids': [DEFAULT_EXEMPT_ROLE]}}, upsert=True)
        await self.mongo.strike_settings.update_one(
            {'_id': key, 'monitoring_started_at': {'$exists': False}},
            {'$set': {'monitoring_started_at': now}})
        row = await self.mongo.strike_settings.find_one({'_id': key}, {'monitoring_started_at': 1})
        return utc(row['monitoring_started_at'])

    async def _compare_write(self, collection, key, previous, changes, revision):
        """No upsert on an existing row: a legacy revision-zero race cannot win."""
        expected = previous.get('revision', 0) if previous else 0
        if revision is not None and revision != expected:
            raise StrikeConflict('Changed by someone else · Reload')
        match = revision_match(expected)
        changes = {**changes, 'revision': expected + 1}
        if previous is None:
            try:
                await collection.insert_one({'_id': key, **changes})
            except DuplicateKeyError as exc:
                raise StrikeConflict('Changed by someone else · Reload') from exc
        else:
            result = await collection.update_one({'_id': key, **match}, {'$set': changes})
            if not result.matched_count:
                raise StrikeConflict('Changed by someone else · Reload')
        return changes

    async def set_exempt_roles(self, guild_id: int, role_ids, actor_id: int,
                               *, expected_revision=None, strike_limit=None) -> dict:
        if expected_revision is not None:
            revision_match(expected_revision)
        roles = sorted({int(role) for role in role_ids})
        if any(role <= 0 for role in roles):
            raise ValueError('Role IDs must be positive.')
        if strike_limit is not None and (type(strike_limit) is not int or not 1 <= strike_limit <= 20):
            raise ValueError('Strike limit must be from 1 to 20.')
        key = str(int(guild_id))
        previous = await self.mongo.strike_settings.find_one({'_id': key})
        changes = {'guild_id': int(guild_id), 'exempt_role_ids': roles,
                   'updated_at': datetime.now(timezone.utc), 'updated_by': int(actor_id)}
        if strike_limit is not None:
            changes['strike_limit'] = strike_limit
        saved = await self._compare_write(self.mongo.strike_settings, key, previous,
                                          changes, expected_revision)
        # Return this successful write's receipt, not a later editor's revision.
        # Otherwise the caller could pair its old draft with that newer revision.
        return {'_id': key, 'guild_id': int(guild_id), 'exempt_role_ids': [DEFAULT_EXEMPT_ROLE],
                'strike_limit': STRIKE_LIMIT, **(previous or {}), **saved,
                'retention_days': STRIKE_DAYS}

    async def _finish_leave_history(self, key, row):
        """Finish the atomic leave transition's durable archive receipt, idempotently.

        Readers finish this before testing exemptions. A failed archive remains
        on the owner document, so a crash cannot silently erase an old interval.
        """
        pending = (row or {}).get('pending_history')
        if pending:
            await self.mongo.strike_leave_history.update_one(
                {'_id': pending['_id']}, {'$setOnInsert': pending}, upsert=True)
            await self.mongo.strike_leaves.update_one(
                {'_id': key, 'revision': row['revision']}, {'$unset': {'pending_history': ''}})
        return row

    async def _write_leave(self, guild_id, member_id, changes, expected_revision):
        if expected_revision is not None:
            revision_match(expected_revision)
        key = f'{int(guild_id)}:{int(member_id)}'
        previous = await self.mongo.strike_leaves.find_one({'_id': key})
        # Check the user's revision before doing even idempotent archive recovery.
        if expected_revision is not None and expected_revision != (previous or {}).get('revision', 0):
            raise StrikeConflict('Changed by someone else · Reload')
        await self._finish_leave_history(key, previous)
        now = changes['updated_at']
        if previous and not previous.get('cleared'):
            history = {field: value for field, value in previous.items()
                       if field not in ('_id', 'pending_history')}
            history['until'] = min(utc(previous['until']), now)
            history['starts_at'] = previous.get('starts_at', previous['updated_at'])
            history['_id'] = f'{key}:{utc(history["starts_at"]).isoformat()}'
            changes['pending_history'] = history
        saved = await self._compare_write(self.mongo.strike_leaves, key, previous,
                                           changes, expected_revision)
        await self._finish_leave_history(key, saved)
        return {key: value for key, value in saved.items() if key != 'pending_history'}

    async def set_leave(self, guild_id: int, member_id: int, until_date: date | str,
                        actor_id: int, *, account_tags=None, expected_revision=None) -> dict:
        # Resume at 00:00 UTC on the chosen date. None selects all linked accounts.
        if isinstance(until_date, str):
            until_date = date.fromisoformat(until_date)
        if not isinstance(until_date, date):
            raise ValueError('Use YYYY-MM-DD for the return date.')
        until = datetime.combine(until_date, time.min, timezone.utc)
        now = datetime.now(timezone.utc)
        if until <= now:
            raise ValueError('Return date must be in the future.')
        selected = None if account_tags is None else sorted({tag(item) for item in account_tags})
        row = {'guild_id': int(guild_id), 'member_id': int(member_id),
               'starts_at': now, 'until': until, 'cleared': False,
               'account_tags': selected, 'updated_by': int(actor_id), 'updated_at': now}
        return await self._write_leave(guild_id, member_id, row, expected_revision)

    async def clear_leave(self, guild_id: int, member_id: int, *, expected_revision=None):
        # Keep an empty interval and revision tombstone to prevent delete/recreate ABA.
        now = datetime.now(timezone.utc)
        row = {'guild_id': int(guild_id), 'member_id': int(member_id), 'starts_at': now,
               'until': now, 'updated_at': now, 'account_tags': [], 'cleared': True}
        return await self._write_leave(guild_id, member_id, row, expected_revision)

    async def set_filler(self, guild_id: int, player_tag: str, preferred: bool,
                         actor_id: int, *, clan_tag=None, weight=None) -> dict:
        player = tag(player_tag)
        changes = {'guild_id': int(guild_id), 'player_tag': player,
                   'filler': bool(preferred), 'updated_by': int(actor_id),
                   'updated_at': datetime.now(timezone.utc)}
        if preferred and clan_tag is None:
            current = await self.mongo.strike_profiles.find_one({'_id': f'{int(guild_id)}:{player}'})
            clan_tag = (current or {}).get('current_clan_tag')
            if not clan_tag:
                raise ValueError('Current clan is unknown; choose a clan for this filler.')
        if clan_tag is not None:
            changes['filler_clan_tag'] = tag(clan_tag)
        if weight is not None:
            if not isinstance(weight, int) or weight <= 0:
                raise ValueError('Weight must be a positive whole number.')
            changes['weight'] = weight
        await self.mongo.strike_profiles.update_one(
            {'_id': f'{int(guild_id)}:{player}'}, {'$set': changes}, upsert=True)
        return changes

    async def expire_departed_replacements(self, guild_id: int, *, now=None):
        """Clear old clan marks only after confirmed absence and a 48h grace.

        CAS the roster evidence and preference revision so a rejoin or staff edit
        racing this pass wins. The audit reason remains on the profile forever.
        """
        now = utc(now or datetime.now(timezone.utc))
        profiles = await self.mongo.strike_profiles.find(
            {'guild_id': int(guild_id), 'departed_last_seen_at': {'$lt': now - REPLACEMENT_GRACE}}
        ).to_list(length=None)
        for profile in profiles:
            clan = profile.get('departed_clan_tag')
            if not clan or profile.get('current_clan_tag') == clan:
                continue
            if not (profile.get('replacement_clan_tag') == clan or profile.get('filler_clan_tag') == clan):
                continue
            await self.mongo.strike_profiles.update_one(
                {'_id': profile['_id'], 'current_clan_tag': profile.get('current_clan_tag'),
                 'departed_clan_tag': clan, 'departed_last_seen_at': profile['departed_last_seen_at'],
                 'replacement_updated_at': profile.get('replacement_updated_at'),
                 'updated_at': profile.get('updated_at')},
                {'$unset': {'replacement_listed': '', 'replacement_priority': '',
                            'replacement_note': '', 'replacement_clan_tag': '', 'filler_clan_tag': ''},
                 '$set': {'filler': False, 'replacement_updated_by': 'system',
                          'replacement_updated_at': now, 'replacement_clear_reason': 'Left clan (48h)'}})

    async def sync_roster(self, guild_id: int, clan_tag: str, members: list[dict], *, observed_at=None):
        clan = tag(clan_tag)
        now = utc(observed_at or datetime.now(timezone.utc))
        current_tags = [tag(member['tag']) for member in members]
        missing = await self.mongo.strike_profiles.find(
            {'guild_id': int(guild_id), 'current_clan_tag': clan,
             'player_tag': {'$nin': current_tags}}).to_list(length=None)
        for profile in missing:
            if utc(profile.get('roster_observed_at') or profile.get('roster_seen_at') or now) > now:
                continue
            departed = profile.get('departed_clan_tag')
            preserve_departure = departed and departed in (
                profile.get('replacement_clan_tag'), profile.get('filler_clan_tag'))
            await self.mongo.strike_profiles.update_one(
                {'_id': profile['_id'], 'current_clan_tag': clan,
                 'roster_seen_at': profile.get('roster_seen_at'),
                 'roster_observed_at': profile.get('roster_observed_at')},
                {'$unset': {'current_clan_tag': ''},
                 '$set': {'departed_clan_tag': departed if preserve_departure else clan,
                          'roster_observed_at': now,
                          'departed_last_seen_at': (profile.get('departed_last_seen_at')
                              if preserve_departure else profile.get('roster_seen_at')) or now}})
        # Includes profiles that are returning now, before refreshing their clock.
        await self.expire_departed_replacements(guild_id, now=now)
        for member in members:
            player = tag(member['tag'])
            identity = f'{int(guild_id)}:{player}'
            prior = await self.mongo.strike_profiles.find_one({'_id': identity}) or {}
            if utc(prior.get('roster_observed_at') or prior.get('roster_seen_at') or now) > now:
                continue
            changes = {'guild_id': int(guild_id), 'player_tag': player,
                       'current_clan_tag': clan, 'player_name': member.get('name') or player,
                       'roster_seen_at': now, 'roster_observed_at': now}
            update = {'$set': changes}
            if prior.get('departed_clan_tag') == clan:
                update['$unset'] = {'departed_clan_tag': '', 'departed_last_seen_at': ''}
            elif (prior.get('current_clan_tag') and prior['current_clan_tag'] != clan
                  and (not prior.get('departed_clan_tag') or prior.get('departed_clan_tag') not in (
                      prior.get('replacement_clan_tag'), prior.get('filler_clan_tag')))):
                changes.update({'departed_clan_tag': prior['current_clan_tag'],
                                'departed_last_seen_at': prior.get('roster_seen_at') or now})
            if isinstance(member.get('weight'), int) and not isinstance(member['weight'], bool) and member['weight'] > 0:
                changes['weight'] = member['weight']
            th = member.get('town_hall', member.get('townHallLevel'))
            if isinstance(th, int) and not isinstance(th, bool) and 0 < th < 100:
                changes['town_hall'] = th
            if member.get('member_id'):
                changes['member_id'] = int(member['member_id'])
            try:
                await self.mongo.strike_profiles.update_one(
                    {'_id': identity, 'roster_observed_at': prior.get('roster_observed_at')},
                    update, upsert=True)
            except DuplicateKeyError:
                # A newer roster observation won while this response was in flight.
                continue
        await self.expire_departed_replacements(guild_id, now=now)


    async def add_manual(self, guild_id: int, player_tag: str, reason: str, actor_id: int,
                         *, member_id=None, clan_tag=None, player_name=None, request_id=None) -> dict:
        reason = str(reason or '').strip()
        if not 1 <= len(reason) <= 500:
            raise ValueError('Enter a reason under 500 characters.')
        player = tag(player_tag)
        now = datetime.now(timezone.utc)
        from uuid import uuid4
        import re
        if request_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', str(request_id)):
            raise ValueError('Invalid request ID.')
        identity = str(request_id) if request_id else uuid4().hex
        row = {'_id': f'manual:{int(guild_id)}:{int(actor_id)}:{identity}', 'guild_id': int(guild_id),
               'player_tag': player, 'member_id': int(member_id) if member_id else None,
               'player_name': player_name or player, 'clan_tag': tag(clan_tag) if clan_tag else None,
               'kind': 'strike', 'source': 'manual', 'reason': reason,
               'missed_attacks': None, 'occurred_at': now,
               'expires_at': now + timedelta(days=STRIKE_DAYS), 'created_by': int(actor_id)}
        try:
            await self.mongo.strike_records.insert_one(row)
        except DuplicateKeyError:
            previous = await self.mongo.strike_records.find_one({'_id': row['_id']})
            if (previous is None or previous['player_tag'] != player
                    or previous['reason'] != reason or previous.get('member_id') != row['member_id']):
                raise ValueError('Request ID was already used for a different strike.')
            return {**previous, 'status': status_of(previous)}
        return {**row, 'status': 'active'}

    async def revoke(self, guild_id: int, strike_id: str, actor_id: int, reason: str) -> dict:
        reason = str(reason or '').strip()
        if not reason:
            raise ValueError('Give a reason for removing the strike.')
        now = datetime.now(timezone.utc)
        result = await self.mongo.strike_records.find_one_and_update(
            {'_id': str(strike_id), 'guild_id': int(guild_id), 'kind': 'strike',
             'revoked_at': {'$exists': False}},
            {'$set': {'revoked_at': now, 'revoked_by': int(actor_id), 'revoke_reason': reason}},
            return_document=True)
        if result is None:
            raise ValueError('Strike not found or already removed.')
        return {**result, 'status': 'removed'}

    async def history(self, guild_id: int, *, player_tag=None, member_id=None,
                      clan_tag=None, status='strikes', limit=50, skip=0, now=None,
                      query=None, war_key=None) -> dict:
        search = str(query or '').strip()
        query: dict[str, Any] = {'guild_id': int(guild_id)}
        if player_tag:
            query['player_tag'] = tag(player_tag)
        if member_id:
            linked = await recruit_links.resolve(int(member_id))
            if linked.unavailable:
                raise RuntimeError('Account links unavailable; member history cannot be complete.')
            linked_tags = [tag(value) for value in linked.sources if value not in linked.conflicts]
            query['$or'] = [{'member_id': int(member_id)}, {'player_tag': {'$in': linked_tags}}]
        if clan_tag:
            query['clan_tag'] = tag(clan_tag)
        if war_key is not None:
            if not isinstance(war_key, str) or not 8 <= len(war_key) <= 160:
                raise ValueError('Choose a saved war.')
            query['war_key'] = war_key
        if search:
            import re
            expression = re.escape(search[:80])
            terms = [{'player_name': {'$regex': expression, '$options': 'i'}},
                     {'reason': {'$regex': expression, '$options': 'i'}}]
            if search.startswith('#'):
                try:
                    terms.append({'player_tag': tag(search)})
                except ValueError:
                    pass
            query.setdefault('$and', []).append({'$or': terms})
        unrevoked = {'revoked_at': {'$in': [None, False, 0, '']}}
        if status == 'strikes':
            query['kind'] = 'strike'
        elif status in (None, 'all'):
            query['kind'] = {'$ne': 'completed'}
        elif status == 'removed':
            query['revoked_at'] = {'$nin': [None, False, 0, '']}
        elif status in ('active', 'expired'):
            query.update(unrevoked)
            query.update(kind='strike', expires_at={
                '$gt' if status == 'active' else '$lte': utc(now or datetime.now(timezone.utc))})
        elif status in ('cwl', 'missed', 'exempt', 'completed'):
            query.update(unrevoked)
            query['kind'] = status
        else:
            raise ValueError('Unknown history status.')
        limit = max(1, min(100, int(limit)))
        skip = max(0, int(skip))
        total = await self.mongo.strike_records.count_documents(query)
        rows = await self.mongo.strike_records.find(query).sort(
            [('occurred_at', -1), ('_id', 1)]).skip(skip).limit(limit).to_list(length=limit)
        return {'items': [{**row, 'status': status_of(row, now)} for row in rows], 'total': total}

    async def known_targets(self, guild_id: int, query: str, *, limit=25):
        """Bounded suggestions from saved profiles and ledger names, never global names."""
        import re
        limit = max(1, min(25, int(limit)))
        query = str(query).strip()
        if not 2 <= len(query) <= 80:
            return []
        name_match = {'$regex': re.escape(query), '$options': 'i'}
        profiles = await self.mongo.strike_profiles.find({
            'guild_id': int(guild_id), 'player_name': name_match}).sort(
                [('player_name', 1), ('player_tag', 1)]).limit(limit).to_list(length=limit)
        cursor = await self.mongo.strike_records.aggregate([
            {'$match': {'guild_id': int(guild_id)}},
            {'$sort': {'occurred_at': -1, '_id': 1}},
            {'$group': {'_id': '$player_tag', 'player_name': {'$first': '$player_name'}}},
            {'$match': {'player_name': name_match}},
            {'$sort': {'player_name': 1, '_id': 1}}, {'$limit': limit},
        ])
        records = await cursor.to_list(length=limit)
        found = {row['_id']: {'player_tag': row['_id'], 'player_name': row.get('player_name')}
                 for row in records}
        found.update({row['player_tag']: row for row in profiles})
        return sorted(found.values(), key=lambda row: (
            str(row.get('player_name') or '').casefold(), row['player_tag']))[:limit]

    async def leave_revision(self, guild_id: int, member_id: int) -> int:
        row = await self.mongo.strike_leaves.find_one({'_id': f'{int(guild_id)}:{int(member_id)}'})
        return (row or {}).get('revision', 0)

    async def account_list(self, guild_id: int, *, query=None, clan_tag=None,
                           status='active', limit=25, skip=0, action='all') -> dict:
        """One row per account, with active and lifetime strike counts."""
        if status not in ('active', 'all'):
            raise ValueError('Choose active or all accounts.')
        if action not in ('all', 'over_limit', 'new_this_week'):
            raise ValueError('Choose an action filter.')
        config = await self.settings(guild_id)
        threshold = config['strike_limit']
        summary = {'over_limit': 0, 'new_this_week': 0}
        search = str(query or '').strip()
        if len(search) > 80:
            raise ValueError('Use a shorter account search.')
        match: dict[str, Any] = {'guild_id': int(guild_id),
            'kind': 'strike' if status == 'active' else {'$in': ['strike', 'missed', 'exempt', 'cwl']}}
        searched_member = None
        if search.startswith('#'):
            match['player_tag'] = tag(search)
        elif search.isascii() and search.isdigit():
            searched_member = int(search)
            linked = await recruit_links.resolve(searched_member)
            if linked.unavailable or linked.conflicts:
                raise RuntimeError('Account links unavailable; member history cannot be complete.')
            linked_tags = {tag(value) for value in linked.sources}
            saved_tags = await self.mongo.strike_records.distinct(
                'player_tag', {'guild_id': int(guild_id), 'member_id': searched_member})
            linked_tags.update(tag(value) for value in saved_tags)
            if not linked_tags:
                return {'items': [], 'total': 0, 'summary': summary, 'strike_limit': threshold}
            match['player_tag'] = {'$in': sorted(linked_tags)}
        now = datetime.now(timezone.utc)
        pipeline = [
            {'$match': match},
            {'$sort': {'occurred_at': -1, '_id': 1}},
            {'$group': {
                '_id': '$player_tag', 'player_name': {'$first': '$player_name'},
                'member_id': {'$first': '$member_id'},
                'link_status': {'$first': '$link_status'},
                'total_strikes': {'$sum': {'$cond': [
                    {'$eq': ['$kind', 'strike']}, 1, 0]}},
                'last_strike_at': {'$max': {'$cond': [
                    {'$eq': ['$kind', 'strike']}, '$occurred_at', None]}},
                'last_record_at': {'$first': '$occurred_at'},
                'new_this_week': {'$max': {'$cond': [{'$and': [
                    {'$eq': ['$kind', 'strike']}, {'$gt': ['$expires_at', now]},
                    {'$eq': [{'$ifNull': ['$revoked_at', None]}, None]},
                    {'$gte': ['$occurred_at', now - timedelta(days=7)]},
                    {'$lte': ['$occurred_at', now]},
                ]}, 1, 0]}},
                'active_strikes': {'$sum': {'$cond': [{'$and': [
                    {'$eq': ['$kind', 'strike']},
                    {'$gt': ['$expires_at', now]},
                    {'$eq': [{'$ifNull': ['$revoked_at', None]}, None]},
                ]}, 1, 0]}},
            }},
            {'$sort': {'active_strikes': -1, 'last_strike_at': -1,
                       'last_record_at': -1, '_id': 1}},
        ]
        grouped_cursor = await self.mongo.strike_records.aggregate(pipeline)
        # Configurable routes can place profiles in another database. Join bounded
        # batches in the storage owner; keep only the requested page in memory.
        limit = max(1, min(100, int(limit)))
        skip = max(0, int(skip))
        total = 0
        wanted_clan = tag(clan_tag) if clan_tag else None
        rows = []
        async def accept_batch(grouped):
            nonlocal total
            tags = [row['_id'] for row in grouped]
            profiles = await self.mongo.strike_profiles.find(
                {'guild_id': int(guild_id), 'player_tag': {'$in': tags}}).to_list(length=len(tags))
            profile_by_tag = {row['player_tag']: row for row in profiles}
            for row in grouped:
                if status == 'active' and row['active_strikes'] <= 0:
                    continue
                profile = profile_by_tag.get(row['_id']) or {}
                display_name = profile.get('player_name') or row.get('player_name') or row['_id']
                if search and not search.startswith('#') and searched_member is None:
                    if search.casefold() not in str(display_name).casefold():
                        continue
                seen = profile.get('roster_seen_at')
                fresh = isinstance(seen, datetime) and utc(seen) > now - timedelta(minutes=30)
                current_clan = profile.get('current_clan_tag')
                if wanted_clan and current_clan != wanted_clan:
                    continue
                over_limit = row['active_strikes'] >= threshold
                new_week = bool(row.get('new_this_week'))
                summary['over_limit'] += over_limit
                summary['new_this_week'] += new_week
                if action == 'over_limit' and not over_limit or action == 'new_this_week' and not new_week:
                    continue
                total += 1
                if not skip < total <= skip + limit:
                    continue
                display_owner = searched_member or profile.get('member_id') or row.get('member_id')
                rows.append({'player_tag': row['_id'],
                             'player_name': display_name, 'over_limit': over_limit, 'new_this_week': new_week,
                             'member_id': display_owner,
                             'link_status': 'linked' if display_owner else 'unlinked',
                             'current_clan_tag': current_clan,
                             'clan_seen_at': seen, 'clan_is_current': fresh,
                             'active_strikes': int(row['active_strikes']),
                             'total_strikes': int(row['total_strikes']),
                             'last_strike_at': row.get('last_strike_at'),
                             'last_record_at': row.get('last_record_at')})
        batch = []
        async for row in grouped_cursor:
            batch.append(row)
            if len(batch) == 200:
                await accept_batch(batch)
                batch = []
        if batch:
            await accept_batch(batch)
        return {'items': rows, 'total': total, 'summary': summary, 'strike_limit': threshold}

    async def _war_cursor(self, guild_id: int, *, clan_tag=None):
        """Group saved missed-attack incidents by exact war, without API rescans."""
        match = {'guild_id': int(guild_id), 'source': {'$in': ['war', 'cwl']},
                 'war_key': {'$exists': True},
                 'kind': {'$in': ['strike', 'missed', 'exempt', 'cwl']}}
        if clan_tag:
            match['clan_tag'] = tag(clan_tag)
        pipeline = [
            {'$match': match},
            {'$sort': {'occurred_at': -1, '_id': 1}},
            {'$group': {
                '_id': '$war_key',
                'clan_tag': {'$first': '$clan_tag'},
                'clan_name': {'$first': '$clan_name'},
                'opponent_tag': {'$first': '$opponent_tag'},
                'opponent_name': {'$first': '$opponent_name'},
                'war_end': {'$first': '$occurred_at'},
                'war_type': {'$first': '$war_type'},
                'capture_source': {'$first': '$capture_source'},
                'import_id': {'$first': '$import_id'},
                'missed_accounts': {'$sum': {'$cond': [{'$gt': ['$missed_attacks', 0]}, 1, 0]}},
                'strikes': {'$sum': {'$cond': [{'$eq': ['$kind', 'strike']}, 1, 0]}},
                'one_missed': {'$sum': {'$cond': [{'$and': [
                    {'$ne': ['$kind', 'cwl']}, {'$eq': ['$missed_attacks', 1]}]}, 1, 0]}},
                'cwl_missed': {'$sum': {'$cond': [{'$and': [
                    {'$eq': ['$kind', 'cwl']}, {'$eq': ['$missed_attacks', 1]}]}, 1, 0]}},
            }},
            {'$sort': {'war_end': -1, '_id': 1}},
        ]
        return await self.mongo.strike_records.aggregate(pipeline)

    @staticmethod
    def _war_entry(row):
        return {'war_key': row['_id'], **{key: value for key, value in row.items() if key != '_id'},
                'war_type': row.get('war_type') or 'regular',
                'source_label': ('Clash API' if row.get('capture_source') == 'clash_api' else
                                 'ClashKing (import)' if row.get('import_id') or
                                 row.get('capture_source') == 'clashking_import' else
                                 'ClashKing (legacy)')}

    async def war_list(self, guild_id: int, *, clan_tag=None, query=None, limit=1000) -> list[dict]:
        # Legacy internal callers retain the list contract. The HTTP path uses war_page.
        result = await self.war_page(guild_id, clan_tag=clan_tag, query=query,
                                     limit=limit, include_incomplete=False)
        return result['items']

    async def war_page(self, guild_id: int, *, clan_tag=None, query=None, limit=25,
                       skip=0, clan_names=None, include_incomplete=True, enrich_names=None) -> dict:
        """Filter the entire stored population, retaining only the requested prefix.

        An optional public name resolver enriches bounded batches before search.
        Storage remains independent of HTTP/provider adapters and Mongo routing.
        """
        import heapq
        search = str(query or '').strip().casefold()
        if len(search) > 80:
            raise ValueError('Use a shorter clan, opponent, or date.')
        limit, skip = max(1, min(100, int(limit))), max(0, int(skip))
        names = clan_names or {}
        retained, total = [], 0
        def accept(row):
            nonlocal total
            row['clan_name'] = names.get(row.get('clan_tag')) or row.get('clan_name') or row.get('clan_tag')
            if search and search not in ' '.join(str(value or '') for value in (
                    row.get('clan_tag'), row.get('clan_name'), row.get('opponent_tag'),
                    row.get('opponent_name'), utc(row['war_end']).date().isoformat())).casefold():
                return
            total += 1
            # Ascending tuple is newest first, with deterministic war-key ties.
            order = (-utc(row['war_end']).timestamp(), row['war_key'])
            retained.append((order, row))
            if len(retained) > 2 * (skip + limit):
                retained[:] = heapq.nsmallest(skip + limit, retained, key=lambda item: item[0])
        batch = []
        async def flush():
            if enrich_names and search:
                await enrich_names(batch)
            for row in batch:
                accept(row)
            batch.clear()
        cursor = await self._war_cursor(guild_id, clan_tag=clan_tag)
        async for row in cursor:
            batch.append(self._war_entry(row))
            if len(batch) == 100:
                await flush()
        if include_incomplete:
            match = {'guild_id': int(guild_id), 'status': 'incomplete'}
            if clan_tag:
                match['clan_tag'] = tag(clan_tag)
            async for snapshot in self.mongo.strike_war_snapshots.find(match):
                # A saved incident takes precedence over the diagnostic placeholder.
                saved = await self.mongo.strike_records.find_one({
                    'guild_id': int(guild_id), 'war_key': snapshot['war_key'],
                    'source': {'$in': ['war', 'cwl']},
                    'kind': {'$in': ['strike', 'missed', 'exempt', 'cwl']}}, {'_id': 1})
                if saved:
                    continue
                war = snapshot['war']
                batch.append({'war_key': snapshot['war_key'], 'clan_tag': snapshot['clan_tag'],
                        'clan_name': war.get('clan_name'), 'opponent_tag': war.get('opponent_tag'),
                        'opponent_name': war.get('opponent_name'), 'war_end': snapshot['end_time'],
                        'war_type': war.get('type'), 'missed_accounts': 0, 'strikes': 0,
                        'one_missed': 0, 'cwl_missed': 0, 'incomplete': True,
                        'review_message': snapshot.get('incomplete_reason') or
                            'War ended before final check: review in Find war',
                        'source_label': 'Clash API'})
                if len(batch) == 100:
                    await flush()
        await flush()
        ordered = heapq.nsmallest(skip + limit, retained, key=lambda item: item[0])
        return {'items': [item[1] for item in ordered[skip:]], 'total': total}

    async def set_replacement_preference(self, guild_id: int, player_tag: str,
                                         priority: str, note: str, actor_id: int,
                                         *, clan_tag: str, player_name=None, town_hall=None,
                                         only_if_unmarked=False) -> dict | None:
        """Mark one account for replacement in its verified current family clan."""
        player, clan = tag(player_tag), tag(clan_tag)
        if priority not in ('replace_first', 'high', 'normal'):
            raise ValueError('Choose a replacement priority.')
        if not isinstance(note, str) or len(note.strip()) > 500:
            raise ValueError('Keep the note under 500 characters.')
        if not await self.mongo.clans.find_one({'tag': clan}, {'_id': 1}):
            raise ValueError('This account is not in a registered family clan.')
        now = datetime.now(timezone.utc)
        changes = {'guild_id': int(guild_id), 'player_tag': player,
                   'current_clan_tag': clan, 'roster_seen_at': now,
                   'replacement_listed': True, 'replacement_priority': priority,
                   'replacement_note': note.strip(), 'replacement_clan_tag': clan,
                   'replacement_updated_by': int(actor_id), 'replacement_updated_at': now,
                   'filler': priority == 'replace_first', 'filler_clan_tag': clan}
        if player_name:
            changes['player_name'] = str(player_name)
        if isinstance(town_hall, int) and not isinstance(town_hall, bool) and 0 < town_hall < 100:
            changes['town_hall'] = town_hall
        query = {'_id': f'{int(guild_id)}:{player}'}
        if only_if_unmarked:
            # A mark in another clan is inactive and may be replaced after transfer.
            # A current-clan mark wins even when two staff members submit together.
            query['$nor'] = [
                {'replacement_listed': True, 'replacement_clan_tag': clan},
                {'filler': True, 'filler_clan_tag': clan},
            ]
        try:
            await self.mongo.strike_profiles.update_one(
                query, {'$set': changes}, upsert=True)
        except DuplicateKeyError:
            if only_if_unmarked:
                return None
            raise
        return changes

    async def clear_replacement_preference(self, guild_id: int, player_tag: str,
                                           actor_id: int) -> None:
        player = tag(player_tag)
        await self.mongo.strike_profiles.update_one(
            {'_id': f'{int(guild_id)}:{player}'},
            {'$unset': {'replacement_listed': '', 'replacement_priority': '',
                        'replacement_note': '', 'replacement_clan_tag': '',
                        'filler_clan_tag': ''},
             '$set': {'filler': False, 'replacement_updated_by': int(actor_id),
                      'replacement_updated_at': datetime.now(timezone.utc)}})

    async def replacement(self, guild_id: int, recruit_weight: int | None = None, *,
                          clan_tag=None, limit=100, weights=None, browse_all=False,
                          family_scope='fwa', town_hall=None) -> list[dict]:
        """Family list or weight matching across FWA/all registered clans."""
        matching = recruit_weight is not None
        if family_scope not in ('fwa', 'all'):
            raise ValueError('Choose FWA or all clans.')
        if town_hall is not None and (not isinstance(town_hall, int) or isinstance(town_hall, bool)
                                      or not 1 <= town_hall < 100):
            raise ValueError('Choose a valid Town Hall level.')
        if matching and (not isinstance(recruit_weight, int) or isinstance(recruit_weight, bool)
                         or not 0 < recruit_weight <= 500000):
            raise ValueError('Enter a positive recruit weight.')
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=30)
        query = {'guild_id': int(guild_id)}
        if town_hall is not None:
            query['town_hall'] = town_hall
        if matching:
            query['roster_seen_at'] = {'$gt': cutoff}
        if clan_tag:
            chosen = tag(clan_tag)
            clan = await self.mongo.clans.find_one({'tag': chosen}, {'_id': 1, 'type': 1})
            if not clan or (matching and family_scope == 'fwa' and clan.get('type') != 'FWA'):
                raise ValueError('Choose a registered FWA clan.' if matching else 'Choose a registered family clan.')
            query['current_clan_tag'] = chosen
        else:
            allowed = {'type': 'FWA'} if matching and family_scope == 'fwa' else {}
            clans = await self.mongo.clans.find(allowed, {'tag': 1}).to_list(length=None)
            query['current_clan_tag'] = {'$in': [tag(row['tag']) for row in clans]}
        if not matching:
            clan_filter = query.pop('current_clan_tag')
            query['$or'] = [
                {'current_clan_tag': clan_filter},
                {'departed_clan_tag': clan_filter,
                 'departed_last_seen_at': {'$gte': now - REPLACEMENT_GRACE}},
            ]
        profiles = await self.mongo.strike_profiles.find(query).to_list(length=None)
        rows = []
        player_tags = [profile['player_tag'] for profile in profiles]
        counts = {}
        if player_tags:
            cursor = await self.mongo.strike_records.aggregate([
                {'$match': {'guild_id': int(guild_id), 'player_tag': {'$in': player_tags},
                            'kind': 'strike', 'revoked_at': {'$exists': False},
                            'expires_at': {'$gt': now}}},
                {'$group': {'_id': '$player_tag', 'count': {'$sum': 1}}},
            ])
            counts = {row['_id']: row['count'] for row in await cursor.to_list(length=None)}
        for profile in profiles:
            old_clan = profile.get('departed_clan_tag')
            marked_departure = old_clan and old_clan in (
                profile.get('replacement_clan_tag'), profile.get('filler_clan_tag'))
            departed = bool(not matching and old_clan and
                            profile.get('current_clan_tag') != old_clan and
                            (marked_departure or not profile.get('current_clan_tag')))
            # Reads must not expose an overdue original-clan mark merely because
            # the current family clan matched. Durable cleanup remains sync-owned.
            if (departed and isinstance(profile.get('departed_last_seen_at'), datetime)
                    and utc(profile['departed_last_seen_at']) < now - REPLACEMENT_GRACE):
                continue
            current_clan = old_clan if departed else profile.get('current_clan_tag')
            if clan_tag and current_clan != chosen:
                continue
            marked_clan = profile.get('replacement_clan_tag')
            marked = bool(profile.get('replacement_listed') and marked_clan == current_clan)
            legacy_filler = bool(profile.get('filler') and profile.get('filler_clan_tag') == current_clan)
            priority = profile.get('replacement_priority') if marked else None
            if priority not in ('replace_first', 'high', 'normal'):
                priority = 'replace_first' if legacy_filler else 'normal'
            weight = (weights or {}).get(profile['player_tag'], profile.get('weight'))
            if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
                weight = None
            count = counts.get(profile['player_tag'], 0)
            if not matching and not browse_all and not (marked or legacy_filler or count):
                continue
            seen = profile.get('roster_seen_at')
            rows.append({**profile, 'weight': weight, 'clan_seen_at': seen,
                         'departed': departed, 'last_seen_clan_tag': current_clan,
                         'last_seen_at': profile.get('departed_last_seen_at') if departed else seen,
                         'clan_is_current': bool(not departed and isinstance(seen, datetime) and utc(seen) > cutoff),
                         'filler': priority == 'replace_first' and (marked or legacy_filler),
                         'replacement_listed': marked or legacy_filler, 'is_manual': marked or legacy_filler,
                         'replacement_priority': priority,
                         'replacement_note': profile.get('replacement_note', '') if marked else '',
                         'active_strikes': count,
                         'weight_difference': abs(weight - recruit_weight) if matching and weight is not None else None})
        priority_rank = {'replace_first': 2, 'high': 1, 'normal': 0}
        rows.sort(key=lambda row: (row['weight_difference'] is None if matching else False,
                                   -priority_rank[row['replacement_priority']],
                                   -row['active_strikes'],
                                   row['weight'] is None,
                                   row['weight_difference'] if matching and row['weight_difference'] is not None else 0,
                                   row['player_tag']))
        return rows[:max(1, min(5000, int(limit)))]

    async def _exemption(self, guild_id: int, player: str, member_id: int | None,
                         occurred_at: datetime, roles: set[int], *, leave_cache=None) -> str | None:
        if member_id is None:
            return None
        if roles:
            if self.role_resolver is None:
                return 'pending_role_check'
            try:
                found = await self.role_resolver(int(guild_id), int(member_id))
            except Exception:
                return 'pending_role_check'
            if found is None:
                return 'pending_role_check'
            if {int(item) for item in found} & roles:
                return 'role'
        if leave_cache is not None:
            if member_id not in leave_cache:
                current = await self.mongo.strike_leaves.find_one({'_id': f'{int(guild_id)}:{int(member_id)}'})
                await self._finish_leave_history(f'{int(guild_id)}:{int(member_id)}', current)
                history = await self.mongo.strike_leave_history.find({
                    'guild_id': int(guild_id), 'member_id': int(member_id)}).to_list(length=None)
                leave_cache[member_id] = ([current] if current else []) + history
            for leave in leave_cache[member_id]:
                selected = leave.get('account_tags')
                if (utc(leave.get('starts_at', leave['updated_at'])) <= occurred_at < utc(leave['until'])
                        and (selected is None or player in selected)):
                    return 'leave'
            return None
        leave = await self.mongo.strike_leaves.find_one({'_id': f'{int(guild_id)}:{int(member_id)}'})
        await self._finish_leave_history(f'{int(guild_id)}:{int(member_id)}', leave)
        if leave and utc(leave.get('starts_at', leave['updated_at'])) <= occurred_at < utc(leave['until']):
            selected = leave.get('account_tags')
            if selected is None or player in selected:
                return 'leave'
        prior = await self.mongo.strike_leave_history.find_one({
            'guild_id': int(guild_id), 'member_id': int(member_id),
            'starts_at': {'$lte': occurred_at}, 'until': {'$gt': occurred_at},
            '$or': [{'account_tags': None}, {'account_tags': player}]})
        if prior:
            return 'leave'
        return None

    async def _resolve_members(self, tags: list[str]) -> tuple[dict[str, int], set[str]]:
        found = await self.link_resolver(tags)
        owners = getattr(found, 'owners', None)
        if owners is None:
            raise RuntimeError('Account links unavailable; war scan deferred.')
        if getattr(found, 'unavailable', ()):
            # A partial link result may hide a role-exempt owner.
            raise RuntimeError('Account links unavailable; war scan deferred.')
        conflicts = set(getattr(found, 'conflicts', ()))
        return {tag(key): int(value) for key, value in owners.items()}, {tag(item) for item in conflicts}

    async def preview_import(self, guild_id: int, wars: list[dict], actor_id: int = 0,
                             *, cwl_wars=()) -> dict:
        from uuid import uuid4
        now = datetime.now(timezone.utc)
        report = {'wars': 0, 'strikes': 0, 'missed': 0, 'exempt': 0,
                  'cwl_wars': 0, 'cwl_records': 0, 'cwl_missed': 0,
                  'existing': 0, 'skipped': [], 'items': [], 'deferred_accounts': []}
        accepted, accepted_cwl = [], []
        seen_rows = set()
        owner_cache = {}
        leave_cache = {}
        for war in wars:
            try:
                validate_war(war, now=now)
                if stamp(war['end_time']) < now - timedelta(days=IMPORT_DAYS):
                    raise ValueError('Outside the 60-day import window.')
                rows = await self._war_rows(guild_id, war, owner_cache=owner_cache,
                                            leave_cache=leave_cache, deferred=report['deferred_accounts'])
                for row in rows:
                    row['capture_source'] = 'clashking_import'
            except (ValueError, RuntimeError, KeyError, TypeError) as error:
                report['skipped'].append({'war': str(war.get('clan_tag', '?')), 'reason': str(error)})
                continue
            report['wars'] += 1
            accepted.append(war)
            missed_rows = [row for row in rows if row['kind'] != 'completed']
            existing_ids = set()
            if missed_rows:
                existing = await self.mongo.strike_records.find(
                    {'_id': {'$in': [row['_id'] for row in missed_rows]}},
                    {'_id': 1},
                ).to_list(length=None)
                existing_ids = {row['_id'] for row in existing}
            for row in missed_rows:
                if row['_id'] in existing_ids or row['_id'] in seen_rows:
                    report['existing'] += 1
                    continue
                seen_rows.add(row['_id'])
                report['items'].append({**row, 'status': status_of(row)})
                if row['kind'] == 'strike':
                    report['strikes'] += 1
                elif row['kind'] == 'missed':
                    report['missed'] += 1
                elif row['kind'] == 'exempt':
                    report['exempt'] += 1
        cwl_owner_cache = {}
        for war in cwl_wars:
            try:
                validate_cwl_war(war, now=now)
                if stamp(war['end_time']) < now - timedelta(days=IMPORT_DAYS):
                    raise ValueError('Outside the 60-day import window.')
                rows = await self._cwl_rows(guild_id, war, owner_cache=cwl_owner_cache)
                for row in rows:
                    row['capture_source'] = 'clashking_import'
            except (ValueError, RuntimeError, KeyError, TypeError) as error:
                report['skipped'].append({'war': str(war.get('clan_tag', '?')),
                                          'reason': str(error), 'war_type': 'cwl'})
                continue
            report['cwl_wars'] += 1
            accepted_cwl.append(war)
            existing = await self.mongo.strike_records.find(
                {'_id': {'$in': [row['_id'] for row in rows]}}, {'_id': 1}).to_list(length=None)
            existing_ids = {row['_id'] for row in existing}
            for row in rows:
                if row['_id'] in existing_ids or row['_id'] in seen_rows:
                    report['existing'] += 1
                    continue
                seen_rows.add(row['_id'])
                report['items'].append({**row, 'status': 'recorded'})
                report['cwl_records'] += 1
                report['cwl_missed'] += row['missed_attacks']
        preview_id = uuid4().hex
        await self.mongo.strike_imports.insert_one({
            '_id': preview_id, 'guild_id': int(guild_id), 'actor_id': int(actor_id),
            'created_at': now, 'expires_at': now + timedelta(hours=24),
            'wars': accepted, 'cwl_wars': accepted_cwl,
            'approved_rows': {item['_id']: item['kind'] for item in report['items']},
            'deferred_rows': {item['row_id']: item['reason'] for item in report['deferred_accounts']},
        })
        return {**report, 'deferred_count': len(report['deferred_accounts']), 'preview_id': preview_id,
                'summary': {'strikes': report['strikes'],
                            'accounts': len({row['player_tag'] for row in report['items'] if row['kind'] == 'strike'}),
                            'history_only': len(report['items']) - report['strikes']}}

    async def _war_rows(self, guild_id: int, war: dict, *, owner_cache=None, leave_cache=None,
                        deferred=None, check_all=False) -> list[dict]:
        validate_war(war)
        clan = tag(war['clan_tag'])
        registered = await self.mongo.clans.find_one({'tag': clan}, {'_id': 1})
        if not registered:
            raise ValueError('Clan is not registered.')
        members = war['members']
        tags = [tag(member['tag']) for member in members]
        if owner_cache is None:
            owners, conflicts = await self._resolve_members(tags)
        else:
            missing = [player for player in tags if player not in owner_cache]
            if missing:
                resolved, disputed = await self._resolve_members(missing)
                for player in missing:
                    owner_cache[player] = (resolved.get(player), player in disputed)
            owners = {player: owner_cache[player][0] for player in tags if owner_cache[player][0] is not None}
            conflicts = {player for player in tags if owner_cache[player][1]}

        settings = await self.settings(guild_id)
        exempt_roles = {int(item) for item in settings['exempt_role_ids']}
        ended = stamp(war['end_time'])
        key = war_key(war)
        rows = []
        for member in members:
            player = tag(member['tag'])
            missed = 2 - member['attacks']
            row_id = f'war:{int(guild_id)}:{key}:{player}'
            reason = 'Account owner conflict' if player in conflicts and (missed or check_all) else None
            owner = owners.get(player)
            if player in conflicts and not missed and not check_all:
                continue
            exemption = None
            if (missed or check_all) and reason is None:
                exemption = await self._exemption(guild_id, player, owner, ended, exempt_roles, leave_cache=leave_cache)
                if exemption == 'pending_role_check':
                    reason = 'Discord roles unavailable'
            if reason is not None:
                if deferred is not None:
                    deferred.append({'row_id': row_id, 'player_tag': player,
                                     'player_name': member.get('name') or player,
                                     'clan_tag': clan, 'clan_name': war.get('clan_name'),
                                     'war_end': ended, 'missed_attacks': missed,
                                     'reason': reason})
                continue
            kind = 'exempt' if missed and exemption else ('strike' if missed == 2 else ('missed' if missed == 1 else 'completed'))
            rows.append({'_id': row_id,
                         'guild_id': int(guild_id), 'player_tag': player,
                         'member_id': owner, 'link_status': 'linked' if owner is not None else 'unlinked',
                         'player_name': member.get('name') or player,
                         'clan_tag': clan, 'clan_name': war.get('clan_name'),
                         'opponent_tag': tag(war['opponent_tag']),
                         'opponent_name': war.get('opponent_name'),
                         'war_key': key, 'kind': kind, 'source': 'war',
                         'capture_source': 'clash_api',
                         'reason': 'Both attacks missed' if missed == 2 else ('One attack missed' if missed else 'Both attacks used'),
                         'missed_attacks': missed, 'exemption': exemption,
                         'occurred_at': ended, 'expires_at': ended + timedelta(days=STRIKE_DAYS)})
        return rows

    async def _cwl_rows(self, guild_id: int, war: dict, *, owner_cache=None) -> list[dict]:
        validate_cwl_war(war)
        clan = tag(war['clan_tag'])
        if not await self.mongo.clans.find_one({'tag': clan}, {'_id': 1}):
            raise ValueError('Clan is not registered.')
        tags = [tag(member['tag']) for member in war['members']]
        resolved = {} if owner_cache is None else owner_cache
        missing = [player for player in tags if player not in resolved]
        if missing:
            try:
                found = await self.link_resolver(missing)
                owners = getattr(found, 'owners', None)
                unavailable = getattr(found, 'unavailable', ())
                conflicts = {tag(value) for value in getattr(found, 'conflicts', ())}
                if owners is None or unavailable:
                    raise RuntimeError('Account link providers unavailable.')
                for player in missing:
                    if player in conflicts:
                        resolved[player] = (None, 'unknown', 'owner_conflict')
                    elif player in owners:
                        resolved[player] = (int(owners[player]), 'linked', None)
                    else:
                        resolved[player] = (None, 'unlinked', None)
            except Exception:
                for player in missing:
                    resolved[player] = (None, 'unknown', 'link_unavailable')
        ended = stamp(war['end_time'])
        key = cwl_war_key(war)
        rows = []
        for member in war['members']:
            player = tag(member['tag'])
            owner, link_status, link_reason = resolved[player]
            used = member['attacks']
            rows.append({'_id': f'cwl:{int(guild_id)}:{key}:{player}',
                         'guild_id': int(guild_id), 'player_tag': player,
                         'member_id': owner, 'link_status': link_status,
                         'link_reason': link_reason,
                         'player_name': member.get('name') or player,
                         'clan_tag': clan, 'clan_name': war.get('clan_name'),
                         'opponent_tag': tag(war['opponent_tag']),
                         'opponent_name': war.get('opponent_name'),
                         'war_key': key, 'war_type': 'cwl', 'war_tag': tag(war['war_tag']),
                         'kind': 'cwl', 'source': 'cwl',
                         'capture_source': 'clash_api',
                         'reason': 'CWL attack missed' if used == 0 else 'CWL attack used',
                         'attacks_used': used, 'attacks_per_member': 1,
                         'missed_attacks': 1 - used, 'occurred_at': ended})
        return rows

    async def process_cwl_war(self, guild_id: int, war: dict, *, owner_cache=None) -> dict:
        """Record CWL participation only; these rows can never count as strikes."""
        rows = await self._cwl_rows(guild_id, war, owner_cache=owner_cache)
        added = existing = missed = 0
        for row in rows:
            try:
                await self.mongo.strike_records.insert_one(row)
                added += 1
                missed += row['missed_attacks']
            except DuplicateKeyError:
                existing += 1
        return {'records': added, 'existing': existing, 'cwl_missed': missed,
                'strikes': 0, 'war_key': cwl_war_key(war)}

    async def streak(self, guild_id: int, player_tag: str) -> dict:
        profile = await self.mongo.strike_profiles.find_one(
            {'_id': f'{int(guild_id)}:{tag(player_tag)}'}) or {}
        return {'count': int(profile.get('streak_count', 0)),
                'last_war_key': profile.get('streak_last_war_key')}

    async def _finish_streak_receipt(self, profile: dict):
        """Replay only frozen strike IDs. Concurrent helpers do the same writes."""
        receipt = profile['streak_pending']
        for strike_id in receipt['strike_ids']:
            await self.mongo.strike_records.update_one(
                {'_id': strike_id, 'guild_id': profile['guild_id'],
                 'player_tag': profile['player_tag'], 'kind': 'strike',
                 'revoked_at': {'$exists': False}},
                {'$set': {'revoked_at': receipt['applied_at'], 'revoked_by': 'system',
                          'revoke_reason': receipt['reason'],
                          'streak_receipt_id': receipt['row_id']}})
        await self.mongo.strike_records.update_one(
            {'_id': receipt['row_id']}, {'$set': {'streak_receipt': receipt}})
        await self.mongo.strike_profiles.update_one(
            {'_id': profile['_id'], 'streak_pending.row_id': receipt['row_id']},
            {'$set': {'streak_count': receipt['count'],
                      'streak_last_war_key': receipt['war_key'],
                      'streak_last_order': receipt['order']},
             '$unset': {'streak_pending': ''}, '$inc': {'streak_version': 1}})

    async def _count_streak(self, row: dict) -> bool:
        """Serialize per account with a durable CAS reservation, without leases.

        Older unresolved captured wars block newer account events. The reservation
        freezes both the next count and target strikes before any revoke; a crash
        or another worker may safely finish it. Completed event receipts stay on
        the permanent war ledger, and the account watermark rejects old replays.
        """
        guild_id, player = row['guild_id'], row['player_tag']
        profile_id = f'{guild_id}:{player}'
        order = utc(row['occurred_at']).isoformat() + ':' + row['war_key']
        snapshots = await self.mongo.strike_war_snapshots.find(
            {'guild_id': guild_id, 'status': 'observing', 'seen_active': True,
             'end_time': {'$lte': row['occurred_at']}}).to_list(length=None)
        for snapshot in snapshots:
            other = snapshot['war']
            other_order = utc(snapshot['end_time']).isoformat() + ':' + snapshot['war_key']
            if (other_order < order and other.get('type') == 'regular'
                    and any(tag(m['tag']) == player for m in other.get('members', []))):
                older = await self.mongo.strike_records.find_one(
                    {'_id': f'war:{guild_id}:{snapshot["war_key"]}:{player}'})
                if not older or not older.get('streak_receipt'):
                    return False
        await self.mongo.strike_profiles.update_one(
            {'_id': profile_id}, {'$setOnInsert': {'guild_id': guild_id,
                'player_tag': player}}, upsert=True)
        for _ in range(12):
            profile = await self.mongo.strike_profiles.find_one({'_id': profile_id})
            if profile.get('streak_pending'):
                await self._finish_streak_receipt(profile)
                continue
            if profile.get('streak_last_order', '') >= order:
                return True
            count = int(profile.get('streak_count', 0))
            reason = None
            if row['kind'] != 'exempt' and not row.get('exemption'):
                count = count + 1 if row['missed_attacks'] == 0 else 0
                if count == 6:
                    reason = 'Reset by streak (6 wars played)'
                    count = 0
                elif count in (2, 4):
                    reason = 'Cleared by streak (2 wars played)'
            now = datetime.now(timezone.utc)
            targets = []
            if reason:
                targets = await self.mongo.strike_records.find(
                    {'guild_id': guild_id, 'player_tag': player, 'kind': 'strike',
                     'revoked_at': {'$exists': False}, 'expires_at': {'$gt': now}}).to_list(length=None)
                targets.sort(key=lambda item: (utc(item['occurred_at']), item['_id']))
                if count:
                    targets = targets[:1]
            receipt = {'row_id': row['_id'], 'war_key': row['war_key'],
                       'order': order, 'count': count, 'applied_at': now,
                       'reason': reason, 'strike_ids': [item['_id'] for item in targets]}
            version = ({'$exists': False} if 'streak_version' not in profile
                       else profile['streak_version'])
            won = await self.mongo.strike_profiles.update_one(
                {'_id': profile_id, 'streak_version': version,
                 'streak_pending': {'$exists': False}},
                {'$set': {'streak_pending': receipt}})
            if won.matched_count:
                await self._finish_streak_receipt({**profile, 'streak_pending': receipt})
                return True
        return False

    async def process_war(self, guild_id: int, war: dict, *, official_capture=False) -> dict:
        deferred = []
        if official_capture:
            snapshot = await self.mongo.strike_war_snapshots.find_one(
                {'_id': f'{int(guild_id)}:{war_key(war)}'})
            if (not snapshot or not snapshot.get('seen_active')
                    or snapshot.get('status') != 'observing' or not war.get('complete')):
                return {'applied': 0, 'existing': 0, 'strikes': 0, 'deferred_count': 0}
        rows = await self._war_rows(guild_id, war, deferred=deferred, check_all=official_capture)
        applied = existing = strikes = 0
        for row in rows:
            if official_capture:
                row['streak_eligible'] = True
            try:
                await self.mongo.strike_records.insert_one(row)
                applied += 1
                strikes += row['kind'] == 'strike'
            except DuplicateKeyError:
                existing += 1
            if official_capture:
                saved = await self.mongo.strike_records.find_one({'_id': row['_id']})
                # Never convert an imported/legacy row into a new streak event.
                if saved.get('streak_eligible') is True and saved.get('capture_source') == 'clash_api' and not saved.get('import_id'):
                    if not await self._count_streak(saved):
                        deferred.append({'player_tag': row['player_tag'],
                                         'reason': 'Earlier captured war pending'})
        return {'applied': applied, 'existing': existing,
                'strikes': strikes, 'war_key': war_key(war),
                'deferred_accounts': deferred, 'deferred_count': len(deferred)}

    async def apply_import(self, guild_id: int, preview_id: str, actor_id: int,
                           excluded_keys=()) -> dict:
        now = datetime.now(timezone.utc)
        preview = await self.mongo.strike_imports.find_one({
            '_id': str(preview_id), 'guild_id': int(guild_id),
            'actor_id': int(actor_id), 'expires_at': {'$gt': now}})
        if preview is None:
            raise ValueError('Import preview expired or belongs to another staff member.')
        excluded = set(excluded_keys)
        approved = preview['approved_rows']
        if not excluded <= set(approved):
            raise ValueError('Excluded incident is not in this preview.')
        results = {'wars': 0, 'cwl_wars': 0, 'cwl_records': 0, 'cwl_missed': 0,
                   'applied': 0, 'existing': 0, 'strikes': 0,
                   'excluded': len(excluded), 'skipped': [], 'deferred_accounts': []}
        cutoff = now - timedelta(days=IMPORT_DAYS)
        attempted = set()
        owner_cache = {}
        leave_cache = {}
        for war in preview['wars']:
            try:
                validate_war(war, now=now)
                if stamp(war['end_time']) < cutoff:
                    raise ValueError('Outside the 60-day import window.')
                rows = await self._war_rows(guild_id, war, owner_cache=owner_cache,
                                            leave_cache=leave_cache, deferred=results['deferred_accounts'])
            except (ValueError, RuntimeError, KeyError, TypeError) as error:
                results['skipped'].append({'war': str(war.get('clan_tag', '?')), 'reason': str(error)})
                continue
            results['wars'] += 1
            for row in rows:
                original = approved.get(row['_id'])
                if original is None:
                    if row['_id'] in preview.get('deferred_rows', {}):
                        results['deferred_accounts'].append({
                            'row_id': row['_id'], 'player_tag': row['player_tag'],
                            'player_name': row['player_name'], 'clan_tag': row['clan_tag'],
                            'clan_name': row.get('clan_name'), 'war_end': row['occurred_at'],
                            'missed_attacks': row['missed_attacks'],
                            'reason': 'Not approved in this preview; create a new preview'})
                    continue
                if row['_id'] in excluded or row['_id'] in attempted:
                    continue
                attempted.add(row['_id'])
                # An exemption discovered since preview can lower a strike.
                # Clearing an exemption cannot promote an originally exempt row.
                if original != 'strike' and row['kind'] == 'strike':
                    row['kind'] = original
                    row['exemption'] = 'preview_exempt' if original == 'exempt' else None
                row['created_by'] = int(actor_id)
                row['import_id'] = str(preview_id)
                row['capture_source'] = 'clashking_import'
                try:
                    await self.mongo.strike_records.insert_one(row)
                    results['applied'] += 1
                    results['strikes'] += row['kind'] == 'strike'
                except DuplicateKeyError:
                    results['existing'] += 1
        cwl_owner_cache = {}
        for war in preview.get('cwl_wars', ()):
            try:
                validate_cwl_war(war, now=now)
                if stamp(war['end_time']) < cutoff:
                    raise ValueError('Outside the 60-day import window.')
                rows = await self._cwl_rows(guild_id, war, owner_cache=cwl_owner_cache)
            except (ValueError, RuntimeError, KeyError, TypeError) as error:
                results['skipped'].append({'war': str(war.get('clan_tag', '?')),
                                           'reason': str(error), 'war_type': 'cwl'})
                continue
            results['cwl_wars'] += 1
            for row in rows:
                if approved.get(row['_id']) != 'cwl' or row['_id'] in excluded or row['_id'] in attempted:
                    continue
                attempted.add(row['_id'])
                row['created_by'] = int(actor_id)
                row['import_id'] = str(preview_id)
                row['capture_source'] = 'clashking_import'
                try:
                    await self.mongo.strike_records.insert_one(row)
                    results['applied'] += 1
                    results['cwl_records'] += 1
                    results['cwl_missed'] += row['missed_attacks']
                except DuplicateKeyError:
                    results['existing'] += 1
        return {**results, 'deferred_count': len(results['deferred_accounts']),
                'added_strikes': results['strikes'], 'duplicates': results['existing'],
                'history_only': results['applied'] - results['strikes']}

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
STRIKE_DAYS = 90


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
        await self.mongo.strike_profiles.create_index([('guild_id', 1), ('current_clan_tag', 1)])
        await self.mongo.strike_imports.create_index('expires_at', expireAfterSeconds=0)
        await self.mongo.strike_leave_history.create_index(
            [('guild_id', 1), ('member_id', 1), ('starts_at', -1)])

    async def settings(self, guild_id: int) -> dict:
        saved = await self.mongo.strike_settings.find_one({'_id': str(int(guild_id))})
        return {'guild_id': int(guild_id), 'exempt_role_ids': [DEFAULT_EXEMPT_ROLE],
                'retention_days': STRIKE_DAYS, **(saved or {})}

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

    async def set_exempt_roles(self, guild_id: int, role_ids, actor_id: int) -> dict:
        roles = sorted({int(role) for role in role_ids})
        if any(role <= 0 for role in roles):
            raise ValueError('Role IDs must be positive.')
        await self.mongo.strike_settings.update_one(
            {'_id': str(int(guild_id))},
            {'$set': {'guild_id': int(guild_id), 'exempt_role_ids': roles,
                      'updated_at': datetime.now(timezone.utc), 'updated_by': int(actor_id)}},
            upsert=True)
        return await self.settings(guild_id)

    async def set_leave(self, guild_id: int, member_id: int, until_date: date | str,
                        actor_id: int, *, account_tags=None) -> dict:
        # Resume at 00:00 UTC on the chosen date. None selects all linked accounts.
        if isinstance(until_date, str):
            until_date = date.fromisoformat(until_date)
        if not isinstance(until_date, date):
            raise ValueError('Use YYYY-MM-DD for the return date.')
        until = datetime.combine(until_date, time.min, timezone.utc)
        if until <= datetime.now(timezone.utc):
            raise ValueError('Return date must be in the future.')
        selected = None if account_tags is None else sorted({tag(item) for item in account_tags})
        row = {'guild_id': int(guild_id), 'member_id': int(member_id),
               'starts_at': datetime.now(timezone.utc), 'until': until,
               'account_tags': selected, 'updated_by': int(actor_id),
               'updated_at': datetime.now(timezone.utc)}
        key = f'{int(guild_id)}:{int(member_id)}'
        previous = await self.mongo.strike_leaves.find_one({'_id': key})
        if previous:
            history = {field: value for field, value in previous.items() if field != '_id'}
            history['until'] = min(utc(previous['until']), datetime.now(timezone.utc))
            await self.mongo.strike_leave_history.update_one(
                {'_id': f'{key}:{utc(previous["starts_at"]).isoformat()}'},
                {'$setOnInsert': history}, upsert=True)
        await self.mongo.strike_leaves.update_one(
            {'_id': key}, {'$set': row}, upsert=True)
        return row

    async def clear_leave(self, guild_id: int, member_id: int):
        key = f'{int(guild_id)}:{int(member_id)}'
        previous = await self.mongo.strike_leaves.find_one({'_id': key})
        if previous:
            ended = min(utc(previous['until']), datetime.now(timezone.utc))
            history = {field: value for field, value in previous.items() if field != '_id'}
            history['until'] = ended
            await self.mongo.strike_leave_history.update_one(
                {'_id': f'{key}:{utc(previous["starts_at"]).isoformat()}'},
                {'$setOnInsert': history}, upsert=True)
            await self.mongo.strike_leaves.delete_one({'_id': key})

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

    async def sync_roster(self, guild_id: int, clan_tag: str, members: list[dict]):
        clan = tag(clan_tag)
        current_tags = [tag(member['tag']) for member in members]
        await self.mongo.strike_profiles.update_many(
            {'guild_id': int(guild_id), 'current_clan_tag': clan,
             'player_tag': {'$nin': current_tags}},
            {'$unset': {'current_clan_tag': ''}})
        for member in members:
            player = tag(member['tag'])
            changes = {'guild_id': int(guild_id), 'player_tag': player,
                       'current_clan_tag': clan, 'player_name': member.get('name') or player,
                       'roster_seen_at': datetime.now(timezone.utc)}
            if isinstance(member.get('weight'), int) and member['weight'] > 0:
                changes['weight'] = member['weight']
            if member.get('member_id'):
                changes['member_id'] = int(member['member_id'])
            await self.mongo.strike_profiles.update_one(
                {'_id': f'{int(guild_id)}:{player}'}, {'$set': changes}, upsert=True)

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
        if status == 'strikes':
            query['kind'] = 'strike'
        elif status in (None, 'all'):
            query['kind'] = {'$ne': 'completed'}
        if status == 'active':
            query.update(kind='strike', revoked_at={'$exists': False},
                         expires_at={'$gt': utc(now or datetime.now(timezone.utc))})
        elif status in ('strikes', 'all', None, 'expired', 'removed', 'missed', 'exempt', 'completed'):
            pass
        elif status is not None:
            raise ValueError('Unknown history status.')
        limit = max(1, min(100, int(limit)))
        skip = max(0, int(skip))
        # Post-filtered statuses are paged after classification to preserve counts.
        if status in ('expired', 'removed', 'missed', 'exempt', 'completed'):
            rows = await self.mongo.strike_records.find(query).sort('occurred_at', -1).to_list(length=None)
            classified = [{**row, 'status': status_of(row, now)} for row in rows]
            classified = [row for row in classified if row['status'] == status]
            return {'items': classified[skip:skip+limit], 'total': len(classified)}
        total = await self.mongo.strike_records.count_documents(query)
        rows = await self.mongo.strike_records.find(query).sort('occurred_at', -1).skip(skip).limit(limit).to_list(length=limit)
        return {'items': [{**row, 'status': status_of(row, now)} for row in rows], 'total': total}

    async def account_list(self, guild_id: int, *, query=None, clan_tag=None,
                           status='active', limit=25, skip=0) -> dict:
        """One row per account, with active and lifetime strike counts."""
        if status not in ('active', 'all'):
            raise ValueError('Choose active or all accounts.')
        search = str(query or '').strip()
        if len(search) > 80:
            raise ValueError('Use a shorter account search.')
        match: dict[str, Any] = {'guild_id': int(guild_id),
            'kind': 'strike' if status == 'active' else {'$in': ['strike', 'missed', 'exempt']}}
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
                return {'items': [], 'total': 0}
            match['player_tag'] = {'$in': sorted(linked_tags)}
        now = datetime.now(timezone.utc)
        pipeline = [
            {'$match': match},
            {'$sort': {'occurred_at': -1}},
            {'$group': {
                '_id': '$player_tag', 'player_name': {'$first': '$player_name'},
                'member_id': {'$first': '$member_id'},
                'total_strikes': {'$sum': {'$cond': [
                    {'$eq': ['$kind', 'strike']}, 1, 0]}},
                'last_strike_at': {'$max': {'$cond': [
                    {'$eq': ['$kind', 'strike']}, '$occurred_at', None]}},
                'last_record_at': {'$first': '$occurred_at'},
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
        grouped = await grouped_cursor.to_list(length=None)
        tags = [row['_id'] for row in grouped]
        profiles = await self.mongo.strike_profiles.find(
            {'guild_id': int(guild_id), 'player_tag': {'$in': tags}}).to_list(length=None)
        profile_by_tag = {row['player_tag']: row for row in profiles}
        wanted_clan = tag(clan_tag) if clan_tag else None
        rows = []
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
            rows.append({'player_tag': row['_id'],
                         'player_name': display_name,
                         'member_id': searched_member or profile.get('member_id') or row.get('member_id'),
                         'current_clan_tag': current_clan,
                         'clan_seen_at': seen, 'clan_is_current': fresh,
                         'active_strikes': int(row['active_strikes']),
                         'total_strikes': int(row['total_strikes']),
                         'last_strike_at': row.get('last_strike_at'),
                         'last_record_at': row.get('last_record_at')})
        limit = max(1, min(100, int(limit)))
        skip = max(0, int(skip))
        return {'items': rows[skip:skip+limit], 'total': len(rows)}

    async def war_list(self, guild_id: int, *, clan_tag=None, query=None, limit=1000) -> list[dict]:
        """Group saved missed-attack incidents by exact war, without API rescans."""
        match = {'guild_id': int(guild_id), 'source': 'war',
                 'war_key': {'$exists': True},
                 'kind': {'$in': ['strike', 'missed', 'exempt']}}
        if clan_tag:
            match['clan_tag'] = tag(clan_tag)
        pipeline = [
            {'$match': match},
            {'$sort': {'occurred_at': -1}},
            {'$group': {
                '_id': '$war_key',
                'clan_tag': {'$first': '$clan_tag'},
                'clan_name': {'$first': '$clan_name'},
                'opponent_tag': {'$first': '$opponent_tag'},
                'opponent_name': {'$first': '$opponent_name'},
                'war_end': {'$first': '$occurred_at'},
                'missed_accounts': {'$sum': 1},
                'strikes': {'$sum': {'$cond': [{'$eq': ['$kind', 'strike']}, 1, 0]}},
                'one_missed': {'$sum': {'$cond': [{'$eq': ['$missed_attacks', 1]}, 1, 0]}},
            }},
            {'$sort': {'war_end': -1}},
            {'$limit': max(1, min(2000, int(limit)))},
        ]
        cursor = await self.mongo.strike_records.aggregate(pipeline)
        rows = await cursor.to_list(length=None)
        search = str(query or '').strip().casefold()
        if search:
            rows = [row for row in rows if search in ' '.join(str(value or '') for value in (
                row.get('clan_tag'), row.get('clan_name'), row.get('opponent_tag'),
                row.get('opponent_name'), utc(row['war_end']).date().isoformat()
            )).casefold()]
        return [{'war_key': row['_id'], **{key: value for key, value in row.items() if key != '_id'}}
                for row in rows]

    async def set_replacement_preference(self, guild_id: int, player_tag: str,
                                         priority: str, note: str, actor_id: int,
                                         *, clan_tag: str, player_name=None) -> dict:
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
        await self.mongo.strike_profiles.update_one(
            {'_id': f'{int(guild_id)}:{player}'}, {'$set': changes}, upsert=True)
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
                          clan_tag=None, limit=100, weights=None) -> list[dict]:
        """Family replacement list, or FWA weight matching when weight is supplied."""
        matching = recruit_weight is not None
        if matching and (not isinstance(recruit_weight, int) or isinstance(recruit_weight, bool)
                         or recruit_weight <= 0):
            raise ValueError('Enter a positive recruit weight.')
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        query = {'guild_id': int(guild_id)}
        if matching:
            query['roster_seen_at'] = {'$gt': cutoff}
        if clan_tag:
            chosen = tag(clan_tag)
            clan = await self.mongo.clans.find_one({'tag': chosen}, {'_id': 1, 'type': 1})
            if not clan or (matching and clan.get('type') != 'FWA'):
                raise ValueError('Choose a registered FWA clan.' if matching else 'Choose a registered family clan.')
            query['current_clan_tag'] = chosen
        else:
            allowed = {'type': 'FWA'} if matching else {}
            clans = await self.mongo.clans.find(allowed, {'tag': 1}).to_list(length=None)
            query['current_clan_tag'] = {'$in': [tag(row['tag']) for row in clans]}
        profiles = await self.mongo.strike_profiles.find(query).to_list(length=None)
        now = datetime.now(timezone.utc)
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
            current_clan = profile.get('current_clan_tag')
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
            if not matching and not (marked or legacy_filler or count):
                continue
            seen = profile.get('roster_seen_at')
            rows.append({**profile, 'weight': weight, 'clan_seen_at': seen,
                         'clan_is_current': bool(isinstance(seen, datetime) and utc(seen) > cutoff),
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
            found = await self.role_resolver(int(guild_id), int(member_id))
            if found is None:
                return 'pending_role_check'
            if {int(item) for item in found} & roles:
                return 'role'
        if leave_cache is not None:
            if member_id not in leave_cache:
                current = await self.mongo.strike_leaves.find_one({'_id': f'{int(guild_id)}:{int(member_id)}'})
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

    async def preview_import(self, guild_id: int, wars: list[dict], actor_id: int = 0) -> dict:
        from uuid import uuid4
        now = datetime.now(timezone.utc)
        report = {'wars': 0, 'strikes': 0, 'missed': 0, 'exempt': 0,
                  'existing': 0, 'skipped': [], 'items': []}
        accepted = []
        owner_cache = {}
        leave_cache = {}
        for war in wars:
            try:
                validate_war(war, now=now)
                if stamp(war['end_time']) < now - timedelta(days=STRIKE_DAYS):
                    raise ValueError('Outside the 90-day import window.')
                rows = await self._war_rows(guild_id, war, owner_cache=owner_cache, leave_cache=leave_cache)
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
                if row['_id'] in existing_ids:
                    report['existing'] += 1
                    continue
                report['items'].append({**row, 'status': status_of(row)})
                if row['kind'] == 'strike':
                    report['strikes'] += 1
                elif row['kind'] == 'missed':
                    report['missed'] += 1
                elif row['kind'] == 'exempt':
                    report['exempt'] += 1
        preview_id = uuid4().hex
        await self.mongo.strike_imports.insert_one({
            '_id': preview_id, 'guild_id': int(guild_id), 'actor_id': int(actor_id),
            'created_at': now, 'expires_at': now + timedelta(hours=24),
            'wars': accepted, 'approved_rows': {item['_id']: item['kind'] for item in report['items']},
        })
        return {**report, 'preview_id': preview_id}

    async def _war_rows(self, guild_id: int, war: dict, *, owner_cache=None, leave_cache=None) -> list[dict]:
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
            if player in conflicts:
                raise RuntimeError('Account owner conflict; war scan deferred.')
            owner = owners.get(player)
            missed = 2 - member['attacks']
            exemption = await self._exemption(guild_id, player, owner, ended, exempt_roles, leave_cache=leave_cache) if missed else None
            if exemption == 'pending_role_check':
                raise RuntimeError('Member roles unavailable; war scan deferred.')
            kind = 'exempt' if missed and exemption else ('strike' if missed == 2 else ('missed' if missed == 1 else 'completed'))
            rows.append({'_id': f'war:{int(guild_id)}:{key}:{player}',
                         'guild_id': int(guild_id), 'player_tag': player,
                         'member_id': owner, 'player_name': member.get('name') or player,
                         'clan_tag': clan, 'clan_name': war.get('clan_name'),
                         'opponent_tag': tag(war['opponent_tag']),
                         'opponent_name': war.get('opponent_name'),
                         'war_key': key, 'kind': kind, 'source': 'war',
                         'reason': 'Both attacks missed' if missed == 2 else ('One attack missed' if missed else 'Both attacks used'),
                         'missed_attacks': missed, 'exemption': exemption,
                         'occurred_at': ended, 'expires_at': ended + timedelta(days=STRIKE_DAYS)})
        return rows

    async def process_war(self, guild_id: int, war: dict) -> dict:
        rows = await self._war_rows(guild_id, war)
        applied = existing = strikes = 0
        for row in rows:
            try:
                await self.mongo.strike_records.insert_one(row)
                applied += 1
                strikes += row['kind'] == 'strike'
            except DuplicateKeyError:
                existing += 1
        return {'applied': applied, 'existing': existing,
                'strikes': strikes, 'war_key': war_key(war)}

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
        results = {'wars': 0, 'applied': 0, 'existing': 0, 'strikes': 0,
                   'excluded': len(excluded), 'skipped': []}
        cutoff = now - timedelta(days=STRIKE_DAYS)
        owner_cache = {}
        leave_cache = {}
        for war in preview['wars']:
            try:
                validate_war(war, now=now)
                if stamp(war['end_time']) < cutoff:
                    raise ValueError('Outside the 90-day import window.')
                rows = await self._war_rows(guild_id, war, owner_cache=owner_cache, leave_cache=leave_cache)
            except (ValueError, RuntimeError, KeyError, TypeError) as error:
                results['skipped'].append({'war': str(war.get('clan_tag', '?')), 'reason': str(error)})
                continue
            results['wars'] += 1
            for row in rows:
                original = approved.get(row['_id'])
                if original is None or row['_id'] in excluded:
                    continue
                # An exemption discovered since preview can lower a strike.
                # Clearing an exemption cannot promote an originally exempt row.
                if original != 'strike' and row['kind'] == 'strike':
                    row['kind'] = original
                    row['exemption'] = 'preview_exempt' if original == 'exempt' else None
                row['created_by'] = int(actor_id)
                row['import_id'] = str(preview_id)
                try:
                    await self.mongo.strike_records.insert_one(row)
                    results['applied'] += 1
                    results['strikes'] += row['kind'] == 'strike'
                except DuplicateKeyError:
                    results['existing'] += 1
        return results

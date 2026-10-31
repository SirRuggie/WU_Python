"""Immutable receipts for confirmed staff war-plan posts; never sends messages."""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

OUTCOMES = frozenset({'win', 'lose', 'blacklisted', 'mismatch'})


def instant(value):
    """CoC timestamps and Mongo datetimes are UTC when their tzinfo is absent."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('Missing war timestamp')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def clan_tag(value):
    if not isinstance(value, str) or not value.strip('# '):
        raise ValueError('Missing clan identity')
    return '#' + value.strip().lstrip('#').upper()


async def capture_binding(client, clan, opponent_name):
    """Read before posting; an unreadable/unbound plan cannot suppress strikes."""
    result = {'clan_tag': clan_tag(clan), 'bound': False, 'binding_reason': 'War plan check failed'}
    try:
        war = await client.get_clan_war(result['clan_tag'])
        if war.state not in ('preparation', 'inWar'):
            return {**result, 'binding_reason': 'No active war at posting'}
        actual_clan = getattr(getattr(war, 'clan', None), 'tag', result['clan_tag'])
        if clan_tag(actual_clan) != result['clan_tag']:
            return {**result, 'binding_reason': 'War plan unclear'}
        result.update(opponent_tag=clan_tag(war.opponent.tag), opponent_name=war.opponent.name,
                      preparation_start=instant(war.preparation_start_time.time),
                      war_end=instant(war.end_time.time))
        # A rep can type the next opponent while the old war is still running.
        if str(war.opponent.name).strip().casefold() != opponent_name.strip().casefold():
            return {**result, 'binding_reason': 'War plan unclear'}
        if result['preparation_start'] >= result['war_end']:
            return {**result, 'binding_reason': 'War plan unclear'}
        return {**result, 'bound': True, 'binding_reason': None}
    except Exception:
        return result


class WarPlanStore:
    def __init__(self, mongo):
        self.collection = mongo.fwa_war_plans

    async def record(self, *, guild_id, message_id, channel_id, actor_id, outcome, binding, posted_at):
        if outcome not in OUTCOMES:
            raise ValueError('Unknown war outcome')
        row = {**binding, '_id': f'{int(guild_id)}:{int(message_id)}',
               'guild_id': int(guild_id), 'message_id': int(message_id),
               'channel_id': int(channel_id), 'actor_id': int(actor_id),
               'outcome': outcome, 'posted_at': instant(posted_at)}
        await self.collection.create_index([('guild_id', 1), ('clan_tag', 1), ('war_end', 1)])
        try:
            await self.collection.insert_one(row)
        except DuplicateKeyError:
            existing = await self.collection.find_one({'_id': row['_id']})
            if any((instant(existing.get(key)) != val if isinstance(val, datetime)
                    else existing.get(key) != val) for key, val in row.items()):
                raise ValueError('Confirmed message already has a different receipt')

    async def outcome(self, guild_id, war):
        """Exact tags/end match; ambiguity or late posts fail open to normal strikes."""
        try:
            ended = instant(war['end_time'])
            rows = await self.collection.find({'guild_id': int(guild_id),
                'clan_tag': clan_tag(war['clan_tag']), 'war_end': ended}).to_list(length=None)
            if not rows:
                return None, 'War plan not found'
            opponent = clan_tag(war['opponent_tag'])
            if any(not row.get('bound') or row.get('opponent_tag') != opponent for row in rows):
                return None, 'War plan unclear'
            if any(instant(row['posted_at']) > ended or row.get('outcome') not in OUTCOMES for row in rows):
                return None, 'War plan unclear'
            rows.sort(key=lambda row: instant(row['posted_at']), reverse=True)
            latest = rows[0]
            tied = [row for row in rows if instant(row['posted_at']) == instant(latest['posted_at'])]
            if len({row['outcome'] for row in tied}) > 1:
                return None, 'War plan unclear'
            reason = 'Latest confirmed war plan used' if len(rows) > 1 else 'Confirmed war plan used'
            return latest['outcome'], reason
        except Exception:
            return None, 'War plan check failed'

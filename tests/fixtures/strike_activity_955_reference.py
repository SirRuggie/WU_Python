"""Frozen955 read baseline for159 equality only; never imported by product code."""
from datetime import datetime, timedelta, timezone
from utils.strike_store import tag


async def activity_context_reference(self, guild_id, activity_tags):
    """Bounded family snapshot for the read-only activity overview."""
    from utils.player_activity_polling import active_clan
    clans = [row for row in await self.mongo.clans.find({}).to_list(length=None)
             if active_clan(row) and row.get('tag')]
    family = [row['tag'] for row in clans]
    players = [tag(value) for value in activity_tags]
    now = datetime.now(timezone.utc)
    profiles = await self.mongo.strike_profiles.find({
        'guild_id': int(guild_id), '$or': [{'current_clan_tag': {'$in': family}},
                                          {'player_tag': {'$in': players}},
                                          {'departed_clan_tag': {'$in': family},
                                           'departed_last_seen_at': {'$gte': now-timedelta(days=90)}}]}).to_list(length=None)
    players = list(set(players) | {row['player_tag'] for row in profiles})
    now = datetime.now(timezone.utc)
    records = await self.mongo.strike_records.find({
        'guild_id': int(guild_id), 'player_tag': {'$in': players},
        '$or': [{'occurred_at': {'$gte': now-timedelta(days=90)}},
                {'kind': 'strike', 'expires_at': {'$gt': now}}]},
        {'player_tag': 1, 'war_key': 1, 'kind': 1, 'source': 1, 'war_type': 1,
         'occurred_at': 1, 'missed_attacks': 1, 'expires_at': 1, 'revoked_at': 1,
         'capture_source': 1, 'import_id': 1, 'exemption': 1}).to_list(length=None)
    return {'profiles': profiles, 'records': records, 'clans': clans,
            'replacements': await self.replacement(guild_id, limit=None),
            'strike_limit': (await self.settings(guild_id))['strike_limit']}


async def overview_reference(self):
    """Read only page signals, never the large per-unit diff baseline."""
    fields = {
        key: 1
        for key in (
            "tag",
            "name",
            "current_clan_tag",
            "left_at",
            "last_seen_at",
            "last_seen_source",
            "tracking_started_at",
            "raid_weekends",
            "recent_wars",
            "updated_at",
            "baseline.townHallLevel",
        )
    }
    return await self.collection.find(
        {"kind": {"$ne": "history_clan"}}, fields
    ).to_list(length=None)

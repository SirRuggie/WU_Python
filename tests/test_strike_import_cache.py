"""Historical import checks existing incident IDs once per war, not once per player."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from utils.strike_store import StrikeService


class Records:
    def __init__(self, ids):
        self.ids = set(ids)
        self.find_calls = []

    def find(self, query, projection=None):
        self.find_calls.append((query, projection))
        wanted = query['_id']['$in']
        result = [{'_id': value} for value in wanted if value in self.ids]
        return SimpleNamespace(to_list=lambda length=None: ready(result))


async def ready(value):
    return value


class Imports:
    def __init__(self):
        self.rows = []

    async def insert_one(self, row):
        self.rows.append(row)


def war(end):
    return {'clan_tag': '#2UVGQU9', 'opponent_tag': '#8GG8',
            'end_time': end, 'type': 'regular', 'state': 'warEnded',
            'attacks_per_member': 2, 'complete': True,
            'members': [{'tag': '#PC9YGL0JL', 'attacks': 0}]}


def test_preview_batches_duplicate_lookup_once_for_each_war():
    async def run():
        now = datetime.now(timezone.utc)
        wars = [war(now - timedelta(days=1)), war(now - timedelta(days=2))]
        records = Records({'old-0-7', 'old-1-3'})
        imports = Imports()
        ledger = StrikeService(SimpleNamespace(strike_records=records, strike_imports=imports))

        async def rows(guild_id, current, **kwargs):
            index = wars.index(current)
            return [{'_id': f'old-{index}-{offset}', 'guild_id': guild_id,
                     'kind': 'completed' if offset == 0 else ('missed' if offset % 2 else 'strike'),
                     'occurred_at': current['end_time'],
                     'expires_at': current['end_time'] + timedelta(days=90)}
                    for offset in range(50)]

        ledger._war_rows = rows
        report = await ledger.preview_import(123, wars, actor_id=5)
        assert len(records.find_calls) == 2
        assert all(len(call[0]['_id']['$in']) == 49 for call in records.find_calls)
        assert all(call[1] == {'_id': 1} for call in records.find_calls)
        assert report['existing'] == 2
        assert len(report['items']) == 96
        assert len(imports.rows) == 1
        assert len(imports.rows[0]['approved_rows']) == 96
    asyncio.run(run())

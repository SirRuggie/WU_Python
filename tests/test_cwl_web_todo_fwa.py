import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from utils.todo_fwa import matching_outcome
from cwl_web.todo import _fwa_outcomes


def test_outcome_requires_matching_war_and_blacklist_takes_precedence():
    row = SimpleNamespace(clan_tag='#ABC', ends_at=1800000000)
    record = {'coc_war_end_time': datetime.fromtimestamp(row.ends_at, timezone.utc).isoformat(),
              'our_outcome': 'win', 'opponent_name': 'Opponent', 'opponent_blacklisted': True}
    assert matching_outcome(row, {'#ABC': record}) == {'status': 'blacklisted', 'opponent': 'Opponent'}
    row.ends_at += 61
    assert matching_outcome(row, {'#ABC': record}) is None
    record['coc_war_end_time'] = None
    assert matching_outcome(row, {'#ABC': record}) is None


def test_web_outcomes_fail_without_breaking_attack_rows():
    async def check():
        mongo = SimpleNamespace(close=AsyncMock())
        app = {'providers': SimpleNamespace(mongo_uri='fixture')}
        rows = [SimpleNamespace(clan_tag='#ABC', ends_at=1800000000)]
        with patch('cwl_web.mongo_client.MongoClient', return_value=mongo), patch('utils.todo_fwa.load_fwa_records', new=AsyncMock(side_effect=RuntimeError('unavailable'))):
            values, note = await _fwa_outcomes(app, rows)
        assert values == [None]
        assert 'could not be checked' in note
        mongo.close.assert_not_awaited()
    asyncio.run(check())


def test_web_outcomes_are_current_and_in_row_order():
    async def check():
        mongo = SimpleNamespace(close=AsyncMock())
        rows = [SimpleNamespace(clan_tag='#ABC', ends_at=1800000000), SimpleNamespace(clan_tag='#OTHER', ends_at=1800000000)]
        records = {'#ABC': {'coc_war_end_time': datetime.fromtimestamp(1800000000, timezone.utc).isoformat(), 'our_outcome': 'lose'}}
        with patch('cwl_web.mongo_client.MongoClient', return_value=mongo), patch('utils.todo_fwa.load_fwa_records', new=AsyncMock(return_value=records)) as load:
            values, note = await _fwa_outcomes({'providers': SimpleNamespace(mongo_uri='fixture')}, rows)
        assert values == [{'status': 'lose', 'opponent': ''}, None]
        assert not note
        load.assert_awaited_once_with(mongo, rows, strict=True)
    asyncio.run(check())

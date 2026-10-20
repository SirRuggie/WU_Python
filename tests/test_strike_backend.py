"""Strike war-source and write-idempotency regressions."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from utils.strike_store import StrikeService
from utils.strike_wars import fetch_history_report, normalize


NOW = datetime.now(timezone.utc)


def raw_war(end, *, attacks=None):
    member = {'tag': '#PC9YGL0JL', 'name': 'Warrior'}
    if attacks is not None:
        member['attacks'] = attacks
    return {'state': 'warEnded', 'teamSize': 1, 'attacksPerMember': 2,
            'endTime': end.strftime('%Y%m%dT%H%M%S.000Z'),
            'clan': {'tag': '#2UVGQU9', 'members': [member], 'attacks': len(attacks or [])},
            'opponent': {'tag': '#8GG8', 'members': [{'tag': '#8GG82'}]}}


def test_war_missing_attacks_means_zero_but_incomplete_roster_is_rejected():
    raw = raw_war(NOW - timedelta(hours=1))
    assert normalize(raw, '#2UVGQU9')['members'][0]['attacks'] == 0
    raw['opponent']['members'] = []
    with pytest.raises(ValueError, match='roster'):
        normalize(raw, '#2UVGQU9')


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def json(self):
        return self.payload


class Session:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        return Response(self.pages.pop(0))


def test_history_paginates_past_full_page_of_ineligible_wars():
    # A whole first page can be CWL or incomplete. The cursor must still use
    # raw end times to discover older two-attack wars.
    first = []
    for day in range(100):
        row = raw_war(NOW - timedelta(minutes=day + 1))
        del row['attacksPerMember']
        first.append(row)
    second = [raw_war(NOW - timedelta(hours=2))]
    session = Session([{'items': first}, {'items': second}])
    report = asyncio.run(fetch_history_report('#2UVGQU9', days=2, session=session))
    assert len(session.calls) == 2
    assert len(report['wars']) == 1
    assert len(report['skipped']) == 100
    assert report['source_count'] == 101
    assert session.calls[1][1]['time[before]'] < session.calls[0][1]['time[before]']


class Rows:
    def __init__(self):
        self.rows = {}

    async def insert_one(self, row):
        if row['_id'] in self.rows:
            raise DuplicateKeyError('duplicate')
        self.rows[row['_id']] = row

    async def find_one(self, query, projection=None):
        return self.rows.get(query.get('_id'))


def test_manual_request_retry_reuses_one_strike_and_rejects_changed_payload():
    async def run():
        ledger = StrikeService(SimpleNamespace(strike_records=Rows()))
        first = await ledger.add_manual(1, '#PC9YGL0JL', 'Reason', 5, request_id='abc12345')
        second = await ledger.add_manual(1, '#PC9YGL0JL', 'Reason', 5, request_id='abc12345')
        assert first['_id'] == second['_id']
        assert len(ledger.mongo.strike_records.rows) == 1
        with pytest.raises(ValueError, match='different strike'):
            await ledger.add_manual(1, '#PC9YGL0JL', 'Changed', 5, request_id='abc12345')
    asyncio.run(run())


def test_manual_strike_expires_at_60_days_and_history_window_is_60():
    from utils.strike_store import IMPORT_DAYS, status_of

    async def run():
        ledger = StrikeService(SimpleNamespace(strike_records=Rows()))
        row = await ledger.add_manual(1, '#PC9YGL0JL', 'Reason', 5)
        assert row['expires_at'] == row['occurred_at'] + timedelta(days=60)
        assert status_of(row, now=row['occurred_at'] + timedelta(days=60, microseconds=-1)) == 'active'
        assert status_of(row, now=row['occurred_at'] + timedelta(days=60)) == 'expired'
        assert IMPORT_DAYS == 60
    asyncio.run(run())

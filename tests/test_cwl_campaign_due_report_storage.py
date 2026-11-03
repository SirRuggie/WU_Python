"""Due-scoped skip reports retain occurrence-wide uncertainty and snapshot safety."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pendulum
import pytest
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign as campaign, cwl_campaign_catchup as policy

GUILD, CYCLE = 22, '2026-11'
DUE = pendulum.datetime(2026, 11, 20, 12, tz='America/New_York')
OID = campaign.occurrence_id(CYCLE, 'signup', 'main')


def entry(due=DUE, status='skipped'):
    return dict(occurrence_id=OID, message_key='signup', variant='main', status=status,
                original_due_at=due.isoformat(), reason='Skipped: settings changed')


async def check_atomic_due_reports(mongo):
    results = await asyncio.gather(*[
        campaign.record_catchup_decision(mongo, GUILD, CYCLE, entry(DUE.in_timezone('UTC') if i % 2 else DUE))
        for i in range(12)
    ])
    assert sum(results) == 1
    assert await campaign.record_catchup_decision(mongo, GUILD, CYCLE, entry(DUE.add(hours=1)))
    raw = await mongo.bot_config.find_one({'_id': campaign.cycle_id(GUILD, CYCLE)})
    assert len(raw['deliveries']) == 2
    assert len(raw['catchup_reported_occurrences']) == 2
    state = await campaign.catchup_state(mongo, GUILD, CYCLE)
    for due in (DUE, DUE.add(hours=1)):
        assert OID in policy.handled_occurrences({'deliveries': []}, state, due=due)
    assert OID not in policy.handled_occurrences(raw, state, due=DUE.add(hours=2))
    assert not raw.get('sent_occurrences')


def test_atomic_due_key_and_history_pruning_memory():
    asyncio.run(check_atomic_due_reports(MemoryMongo()))


@pytest.mark.parametrize('field', ['sent_occurrences', 'uncertain_occurrences', 'catchup_reported_occurrences'])
def test_legacy_or_unknown_occurrence_marker_still_blocks_every_due(field):
    async def run():
        mongo = MemoryMongo()
        mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] = {
            '_id': campaign.cycle_id(GUILD, CYCLE), field: [OID],
        }
        assert not await campaign.record_catchup_decision(mongo, GUILD, CYCLE, entry())
        raw = await mongo.bot_config.find_one({'_id': campaign.cycle_id(GUILD, CYCLE)})
        assert not raw.get('deliveries')
    asyncio.run(run())


@pytest.mark.parametrize('status', ['uncertain', 'failed', 'sent'])
def test_non_skip_receipts_remain_whole_occurrence(status):
    state = {'reported': [OID]}
    row = entry(status=status)
    assert OID in policy.handled_occurrences({'deliveries': [row]}, state, due=DUE.add(hours=1))


def test_old_unscoped_skip_receipt_remains_conservative():
    assert OID in policy.handled_occurrences({'deliveries': [entry()]}, {}, due=DUE.add(hours=1))


@pytest.mark.parametrize('replacement', ['same', 'generation', 'run_time', 'failure_count', 'job_kind', 'status'])
def test_retired_retry_snapshot_deletion_preserves_replacements(replacement):
    async def run():
        mongo = MemoryMongo()
        key = f'cwl_campaign:{GUILD}:{CYCLE}:signup:main'
        observed = dict(_id=key, kind='campaign', guild_id=GUILD, cycle=CYCLE,
                        message_id='signup', variants=['main'], generation='old',
                        job_kind='retry', failure_count=1, status='scheduled', run_time=DUE.isoformat())
        actual = deepcopy(observed)
        if replacement == 'generation': actual['generation'] = 'new'
        if replacement == 'run_time': actual['run_time'] = DUE.add(hours=1).isoformat()
        if replacement == 'failure_count': actual['failure_count'] = 2
        if replacement == 'job_kind': actual['job_kind'] = 'manual'
        if replacement == 'status': actual['status'] = 'ledger_pending'
        mongo.cwl_pending_reminders.documents[key] = actual
        await campaign.delete_catchup_job(mongo, observed, retired_retry=True)
        assert (key in mongo.cwl_pending_reminders.documents) is (replacement != 'same')
        if replacement != 'same': assert mongo.cwl_pending_reminders.documents[key] == actual
    asyncio.run(run())

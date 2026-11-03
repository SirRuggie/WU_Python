"""Stale due retirement shares existing claims; Discord is always fake."""
import asyncio
from copy import deepcopy

import pendulum
import pytest

from extensions.tasks import cwl_reminder as native
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge
from test_cwl_campaign_catchup import runtime, GUILD, CYCLE
from test_cwl_campaign_stale_due import CANDIDATE


@pytest.fixture(autouse=True)
def isolated_activity(monkeypatch):
    monkeypatch.setattr(native, '_campaign_send_activity', {})
    yield
    assert native._campaign_send_activity == {}, 'Completed owner leaked'


async def seed(runtime):
    due = pendulum.datetime(2026, 11, 20, 12, tz='America/New_York')
    runtime.clock[0] = due.subtract(seconds=5)
    template = deepcopy(runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]['campaign'])
    template['messages']['signup']['schedule'] = {'mode': 'monthly', 'day': 20, 'hour': 12, 'minute': 0}
    key = native._campaign_job_id(GUILD, CYCLE, 'signup', 'main')
    runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] = {
        '_id': campaign.cycle_id(GUILD, CYCLE), 'kind': 'cwl_campaign_cycle',
        'guild_id': GUILD, 'cycle': CYCLE, 'revision': 1,
        'campaign': template, 'activated': True,
    }
    await native.sync_campaign_schedule(GUILD, CYCLE)
    return due, key, runtime.scheduler.get_job(key)


async def save_roster(runtime):
    loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
    await campaign.save_updated_roster_variant(
        runtime.mongo, guild_id=GUILD, cycle=CYCLE, pool='main', user_id=200,
        candidate=CANDIDATE, expected_generation=bridge.campaign_generation(loaded),
        future_months=False,
    )


async def receipts(runtime):
    loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
    oid = campaign.occurrence_id(CYCLE, 'signup', 'main')
    return [r for r in loaded['deliveries'] if r.get('occurrence_id') == oid]


def test_tokens_survive_overlap_and_in_process_runtime_change(monkeypatch):
    row = {'guild_id': GUILD, 'cycle': CYCLE, 'message_id': 'signup', 'variants': ['main']}
    first = native._register_campaign_activity(GUILD, CYCLE, 'signup', ['main'])
    monkeypatch.setattr(native, '_campaign_runtime_id', 'new-local-runtime')
    assert native._campaign_row_active(row)
    second = native._register_campaign_activity(GUILD, CYCLE, 'signup', ['main'])
    native._release_campaign_activity(first)
    native._release_campaign_activity(first)
    assert native._campaign_row_active(row), 'Old finally removed another owner'
    native._release_campaign_activity(second)
    assert not native._campaign_row_active(row)


@pytest.mark.parametrize('failure', [False, True])
def test_wrapper_releases_its_token_on_return_or_error(monkeypatch, failure):
    async def run():
        async def deliver(*args, **kwargs):
            assert kwargs['manual'] and kwargs['staff_request_id'] == 'request-one'
            assert native._campaign_row_active({'guild_id': GUILD, 'cycle': CYCLE, 'message_id': 'signup', 'variants': ['main']})
            if failure:
                raise ValueError('owned failure')
            return True
        monkeypatch.setattr(native, '_deliver_campaign_message', deliver)
        if failure:
            with pytest.raises(ValueError, match='owned failure'):
                await native.send_campaign_message(GUILD, CYCLE, 'signup', ['main'], manual=True, staff_request_id='request-one')
        else:
            assert await native.send_campaign_message(GUILD, CYCLE, 'signup', ['main'], manual=True, staff_request_id='request-one')
    asyncio.run(run())


def test_duplicate_stale_callbacks_reconcile_and_restart_leave_one_skip(runtime):
    async def run():
        due, _, job = await seed(runtime)
        await save_roster(runtime)
        runtime.clock[0] = due.add(seconds=1)
        await asyncio.gather(job.function(*job.args), job.function(*job.args), native.sync_campaign_schedule(GUILD, CYCLE))
        await native._reconcile_cwl_startup()
        rows = await receipts(runtime)
        assert len(rows) == 1 and rows[0]['status'] == 'skipped'
        assert 'settings changed' in rows[0]['reason'].lower()
        assert runtime.rest.sent == []
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['ordinary', 'manual', 'old-runtime', 'current-generation'])
def test_active_post_is_deferred_then_only_sent_is_kept(runtime, monkeypatch, mode):
    async def run():
        due, key, job = await seed(runtime)
        runtime.clock[0] = due.add(seconds=1)
        entered, release = asyncio.Event(), asyncio.Event()
        original = runtime.rest.create_message
        async def post(**kwargs):
            entered.set()
            await release.wait()
            return await original(**kwargs)
        monkeypatch.setattr(runtime.rest, 'create_message', post)
        task = asyncio.create_task(native.send_campaign_message(*job.args, manual=mode == 'manual'))
        try:
            await entered.wait()
            if mode == 'old-runtime':
                monkeypatch.setattr(native, '_campaign_runtime_id', 'second-local-runtime')
            if mode != 'current-generation':
                await save_roster(runtime)
            await native.sync_campaign_schedule(GUILD, CYCLE)
            # Current-generation ordinary cleanup keeps its pre-existing path.
            if mode != 'current-generation':
                assert key in runtime.mongo.cwl_pending_reminders.documents
            assert await receipts(runtime) == []
        finally:
            release.set()
            await task
        await native.sync_campaign_schedule(GUILD, CYCLE)
        assert len(runtime.rest.sent) == 1
        assert [r['status'] for r in await receipts(runtime)] == ['sent']
    asyncio.run(run())


def test_manual_owner_entering_during_state_read_is_seen(runtime, monkeypatch):
    async def run():
        due, key, job = await seed(runtime)
        await save_roster(runtime)
        runtime.clock[0] = due.add(seconds=1)
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        entered, release = asyncio.Event(), asyncio.Event()
        original_post, original_state = runtime.rest.create_message, campaign.catchup_state
        owner = None
        async def post(**kwargs):
            entered.set()
            await release.wait()
            return await original_post(**kwargs)
        async def state(*args):
            nonlocal owner
            result = await original_state(*args)
            if owner is None:
                owner = asyncio.create_task(native.send_campaign_message(
                    GUILD, CYCLE, 'signup', ['main'], native._campaign_generation(loaded), manual=True,
                ))
                await entered.wait()
            return result
        monkeypatch.setattr(runtime.rest, 'create_message', post)
        monkeypatch.setattr(campaign, 'catchup_state', state)
        try:
            await job.function(*job.args)
            assert key in runtime.mongo.cwl_pending_reminders.documents
            assert await receipts(runtime) == []
        finally:
            release.set()
            if owner is not None:
                await owner
        await native.sync_campaign_schedule(GUILD, CYCLE)
        assert len(runtime.rest.sent) == 1
        assert [r['status'] for r in await receipts(runtime)] == ['sent']
    asyncio.run(run())


def test_cancelled_owner_releases_token_but_never_retries_unknown_claim(runtime, monkeypatch):
    async def run():
        due, _, job = await seed(runtime)
        runtime.clock[0] = due.add(seconds=1)
        entered = asyncio.Event()
        async def post(**kwargs):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(runtime.rest, 'create_message', post)
        task = asyncio.create_task(job.function(*job.args))
        await entered.wait()
        await save_roster(runtime)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await native.sync_campaign_schedule(GUILD, CYCLE)
        await native._reconcile_cwl_startup()
        assert runtime.rest.sent == []
        assert [r['status'] for r in await receipts(runtime)] == ['uncertain']
    asyncio.run(run())


@pytest.mark.parametrize('change', ['same-copy', 'future', 'disabled', 'paused', 'too-old'])
def test_changed_due_has_history_and_future_send_is_not_consumed(runtime, change):
    async def run():
        due, key, job = await seed(runtime)
        await save_roster(runtime)
        row = runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)]
        if change == 'future':
            row['campaign']['messages']['signup']['schedule']['hour'] = 13
        elif change == 'disabled':
            row['campaign']['messages']['signup']['enabled'] = False
        elif change == 'paused':
            row['campaign']['paused'] = True
        runtime.clock[0] = due.add(hours=7) if change == 'too-old' else due.add(seconds=1)
        await job.function(*job.args)
        rows = await receipts(runtime)
        assert len(rows) == 1 and rows[0]['status'] == 'skipped'
        assert runtime.rest.sent == []
        if change == 'future':
            future = runtime.scheduler.get_job(key)
            assert future is not None and future.args[-1] != job.args[-1]
            runtime.clock[0] = due.add(hours=1)
            await future.function(*future.args)
            assert len(runtime.rest.sent) == 1
            assert sorted(r['status'] for r in await receipts(runtime)) == ['sent', 'skipped']
    asyncio.run(run())


def test_stale_decision_cannot_delete_a_newer_persisted_or_scheduler_job(runtime, monkeypatch):
    async def run():
        due, key, job = await seed(runtime)
        await save_roster(runtime)
        runtime.clock[0] = due.add(seconds=1)
        original = native._finish_catchup_decision
        replaced = False
        replacement_generation = None
        async def replace_then_decide(row, original_due, status, reason):
            nonlocal replaced, replacement_generation
            if not replaced:
                replaced = True
                config = runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)]
                config['campaign']['messages']['signup']['schedule']['hour'] = 13
                config['revision'] += 1
                loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
                replacement_generation = native._campaign_generation(loaded)
                future = due.add(hours=1)
                await native._persist_campaign_job(key, future, GUILD, CYCLE, 'signup', ['main'], replacement_generation)
                native._add_campaign_job(key, future, GUILD, CYCLE, 'signup', ['main'], replacement_generation)
            return await original(row, original_due, status, reason)
        monkeypatch.setattr(native, '_finish_catchup_decision', replace_then_decide)
        await job.function(*job.args)
        assert runtime.mongo.cwl_pending_reminders.documents[key]['generation'] == replacement_generation
        replacement = runtime.scheduler.get_job(key)
        assert replacement.args[-1] == replacement_generation
        assert pendulum.instance(replacement.trigger.run_date) == due.add(hours=1)
        await native.sync_campaign_schedule(GUILD, CYCLE)
        runtime.clock[0] = due.add(hours=1)
        await runtime.scheduler.get_job(key).function(*runtime.scheduler.get_job(key).args)
        assert len(runtime.rest.sent) == 1
        assert sorted(r['status'] for r in await receipts(runtime)) == ['sent', 'skipped']
    asyncio.run(run())

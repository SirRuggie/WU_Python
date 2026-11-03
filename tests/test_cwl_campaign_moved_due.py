"""A skip for an old due time must not consume another due time."""
import asyncio
import pytest
from test_cwl_campaign_catchup import runtime, GUILD, CYCLE, run_current_due_jobs
from test_cwl_campaign_stale_due_concurrency import seed, receipts, save_roster
from extensions.tasks import cwl_reminder as native
from utils import cwl_campaign as campaign


def move(runtime, hour):
    row = runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)]
    row['campaign']['messages']['signup']['schedule']['hour'] = hour
    row['revision'] += 1


@pytest.mark.parametrize('mode', ['restart-later', 'second-save'])
def test_old_skip_does_not_consume_moved_reminder(runtime, mode):
    async def run():
        due, key, first = await seed(runtime)
        runtime.clock[0] = due.subtract(seconds=2)
        move(runtime, 13)
        runtime.clock[0] = due.add(seconds=1)
        await first.function(*first.args, **getattr(first, 'kwargs', {}))
        assert [r['status'] for r in await receipts(runtime)] == ['skipped']
        moved = runtime.scheduler.get_job(key)
        assert moved is not None
        if mode == 'restart-later':
            runtime.clock[0] = due.add(hours=1, minutes=5)
            runtime.scheduler.jobs.clear()
            await native._reconcile_cwl_startup()
            await run_current_due_jobs(runtime)
            assert len(runtime.rest.sent) == 1, await receipts(runtime)
            assert [r['status'] for r in await receipts(runtime)].count('sent') == 1
        else:
            runtime.clock[0] = due.add(hours=1).subtract(seconds=2)
            await save_roster(runtime)
            runtime.clock[0] = due.add(hours=1, seconds=1)
            await moved.function(*moved.args, **getattr(moved, 'kwargs', {}))
            rows = await receipts(runtime)
            assert len(rows) == 2, rows
            assert [r['status'] for r in rows] == ['skipped', 'skipped']
            assert runtime.rest.sent == []
    asyncio.run(run())


def test_move_back_to_original_due_reuses_that_skip_without_duplicate(runtime):
    async def run():
        due, key, first = await seed(runtime)
        move(runtime, 13)
        runtime.clock[0] = due.add(seconds=1)
        await first.function(*first.args)
        move(runtime, 12)
        # Restart with the old due snapshot as well as its already durable skip.
        await native.sync_campaign_schedule(GUILD, CYCLE)
        runtime.scheduler.jobs.clear()
        await native._reconcile_cwl_startup()
        await run_current_due_jobs(runtime)
        assert len(await receipts(runtime)) == 1
        assert runtime.rest.sent == []
    asyncio.run(run())


@pytest.mark.parametrize('future', [False, True])
def test_stale_retry_gets_visible_skip_without_send(runtime, future):
    async def run():
        due, key, first = await seed(runtime)
        pending = runtime.mongo.cwl_pending_reminders.documents[key]
        pending.update(failure_count=1, job_kind='retry')
        if future:
            pending['run_time'] = due.add(minutes=5).isoformat()
        move(runtime, 13)
        runtime.clock[0] = due.add(seconds=1)
        await native.sync_campaign_schedule(GUILD, CYCLE)
        rows = await receipts(runtime)
        assert len(rows) == 1 and rows[0]['reason'] == 'Skipped: settings changed'
        assert rows[0]['status'] == 'skipped'
        assert runtime.rest.sent == []
        assert runtime.scheduler.get_job(key).trigger.run_date.hour == 13
    asyncio.run(run())


def test_next_sync_repairs_moved_job_after_manual_post_failure(runtime, monkeypatch):
    async def run():
        due, key, first = await seed(runtime)
        entered, release = asyncio.Event(), asyncio.Event()
        async def post(**kwargs):
            entered.set()
            await release.wait()
            raise RuntimeError('Synthetic failed POST')
        monkeypatch.setattr(runtime.rest, 'create_message', post)
        runtime.clock[0] = due.add(seconds=1)
        task = asyncio.create_task(native.send_campaign_message(*first.args, manual=True))
        await entered.wait()
        try:
            move(runtime, 13)
            await native.sync_campaign_schedule(GUILD, CYCLE)
            assert runtime.scheduler.get_job(key).trigger.run_date.hour == 12
        finally:
            release.set()
            await task
        await native.sync_campaign_schedule(GUILD, CYCLE)
        assert runtime.scheduler.get_job(key).trigger.run_date.hour == 13
        assert runtime.mongo.cwl_pending_reminders.documents[key]['generation'] == native._campaign_generation(
            await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))
        assert runtime.rest.sent == []
    asyncio.run(run())


def test_due_key_survives_history_pruning_and_equivalent_timezone(runtime):
    from utils import cwl_campaign_catchup as policy
    async def run():
        due, key, first = await seed(runtime)
        move(runtime, 13)
        runtime.clock[0] = due.add(seconds=1)
        await first.function(*first.args)
        row = runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)]
        row['deliveries'] = []
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        state = await campaign.catchup_state(runtime.mongo, GUILD, CYCLE)
        oid = campaign.occurrence_id(CYCLE, 'signup', 'main')
        assert oid in policy.handled_occurrences(loaded, state, due=due.in_timezone('UTC'))
        assert oid not in policy.handled_occurrences(loaded, state, due=due.add(hours=1))
    asyncio.run(run())

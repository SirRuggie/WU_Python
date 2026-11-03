"""A revision save inside the scheduler reconcile window must leave one outcome."""
import asyncio
from copy import deepcopy

import pendulum
import pytest
from test_cwl_campaign_catchup import runtime, GUILD, CYCLE
from extensions.tasks import cwl_reminder as native
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge

CANDIDATE = {
    "title": "Only roster text changed",
    "body": "Synthetic reviewed roster copy",
    "buttons": [{"label": "My tasks", "url": "https://dash.warriorsunited.cc/tasks"}],
}



@pytest.mark.parametrize('mode', ['control', 'save-before-due', 'save-and-restart'])
def test_due_callback_has_exactly_one_send_or_visible_record(runtime, mode):
    async def run():
        due = pendulum.datetime(2026, 11, 20, 12, tz='America/New_York')
        runtime.clock[0] = due.subtract(seconds=5)
        template = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]['campaign']
        template['messages']['signup']['schedule'] = {'mode': 'monthly', 'day': 20, 'hour': 12, 'minute': 0}
        runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] = {
            '_id': campaign.cycle_id(GUILD, CYCLE), 'kind': 'cwl_campaign_cycle',
            'guild_id': GUILD, 'cycle': CYCLE, 'revision': 1,
            'campaign': deepcopy(template), 'activated': True,
            'updated_at': due.subtract(minutes=1).in_timezone('UTC').isoformat(),
        }
        await native.sync_campaign_schedule(GUILD, CYCLE)
        job_id = native._campaign_job_id(GUILD, CYCLE, 'signup', 'main')
        job = runtime.scheduler.get_job(job_id)
        assert job is not None and job_id in runtime.mongo.cwl_pending_reminders.documents
        before = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        original_generation = job.args[-1]
        if mode != 'control':
            runtime.clock[0] = due.subtract(seconds=2)
            await campaign.save_updated_roster_variant(
                runtime.mongo, guild_id=GUILD, cycle=CYCLE, pool='main', user_id=200,
                candidate=CANDIDATE, expected_generation=bridge.campaign_generation(before),
                future_months=False,
            )
        runtime.clock[0] = due.add(seconds=1)
        if mode == 'save-and-restart':
            runtime.scheduler.jobs.clear()
            await native._reconcile_cwl_startup()
        # A callback already handed to the scheduler may still arrive after restart/reconcile.
        await job.function(*job.args, **getattr(job, 'kwargs', {}))
        after = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        occurrence = campaign.occurrence_id(CYCLE, 'signup', 'main')
        records = [row for row in after['deliveries'] if row.get('occurrence_id') == occurrence]
        visible_non_send = [row for row in records if row.get('status') != 'sent']
        outcome = {
            'syncToCallbackSeconds': 6, 'saveToCallbackSeconds': 3 if mode != 'control' else None,
            'generationChanged': original_generation != native._campaign_generation(after),
            'fakeSends': len(runtime.rest.sent), 'historyRecords': len(records),
            'historyStatuses': [row.get('status') for row in records],
            'historyReasons': [row.get('reason') for row in records],
            'pendingRowPresent': job_id in runtime.mongo.cwl_pending_reminders.documents,
            'schedulerJobPresent': runtime.scheduler.get_job(job_id) is not None,
            'logicalOutcomes': len(runtime.rest.sent) + len(visible_non_send),
        }
        assert outcome['logicalOutcomes'] == 1, outcome
        assert len(runtime.rest.sent) <= 1
        assert len(records) == 1
    asyncio.run(run())

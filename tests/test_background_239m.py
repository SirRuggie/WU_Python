"""Synthetic job clocks and owned tasks; no network or production state."""
import asyncio
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from utils import background as bg


@pytest.fixture(autouse=True)
def isolated_job_state():
    bg._jobs.clear()
    bg._errors.clear()
    yield
    assert not any(job.running for job in bg._jobs.values())
    bg._jobs.clear()
    bg._errors.clear()


def test_success_failure_and_false_result_keep_last_success_honest(monkeypatch, caplog):
    async def run():
        clock = [100.0]
        monkeypatch.setattr(bg, 'time', NS(monotonic=lambda: clock[0]))
        await bg.run_periodic('fixture', AsyncMock(return_value=None), 10, once=True)
        first = bg.job_health()['fixture']['last_success']
        assert first.tzinfo is not None
        secret = 'synthetic-sensitive-value'
        async def failure():
            raise RuntimeError(secret)
        clock[0] = 110
        assert await bg.run_periodic('fixture', failure, 10, once=True) is False
        assert bg.job_health()['fixture']['last_success'] == first
        clock[0] = 120
        assert await bg.run_periodic('fixture', AsyncMock(return_value=False), 10, once=True) is False
        assert bg.job_health()['fixture']['last_success'] == first
        assert bg.job_health()['fixture']['last_error'] == 'Incomplete'
    asyncio.run(run())
    assert 'synthetic-sensitive-value' not in caplog.text
    assert any(record.exc_info and record.exc_info[2] is not None for record in caplog.records)


def test_three_intervals_warn_once_and_next_success_recovers_once(monkeypatch, caplog):
    async def run():
        clock = [0.0]
        monkeypatch.setattr(bg, 'time', NS(monotonic=lambda: clock[0]))
        caplog.set_level(logging.INFO)
        await bg.run_periodic('fixture', AsyncMock(), 10, once=True)
        old = bg.job_health()['fixture']['last_success']
        for stamp in (10,20,30,40,50):
            clock[0] = stamp
            await bg.run_periodic('fixture', AsyncMock(return_value=False), 10, once=True)
        assert bg.job_health()['fixture']['last_success'] == old
        assert bg.job_health()['fixture']['stale']
        clock[0] = 60
        await bg.run_periodic('fixture', AsyncMock(), 10, once=True)
        await bg.run_periodic('fixture', AsyncMock(), 10, once=True)
        assert not bg.job_health()['fixture']['stale']
    asyncio.run(run())
    assert sum('no success for three intervals' in r.message for r in caplog.records) == 1
    assert sum('Background job recovered' in r.message for r in caplog.records) == 1


def test_first_failure_window_is_not_immediately_stale_and_clock_regression_is_safe(monkeypatch):
    async def run():
        clock=[100.0]
        monkeypatch.setattr(bg,'time',NS(monotonic=lambda:clock[0]))
        await bg.run_periodic('fixture',AsyncMock(return_value=False),10,once=True)
        assert bg.job_health()['fixture']['last_success'] is None
        for stamp,want in ((99,False),(129.99,False),(130,True)):
            clock[0]=stamp
            assert bg.job_health()['fixture']['stale'] is want
    asyncio.run(run())


def test_error_signatures_are_safe_distinct_rate_limited_and_bounded(monkeypatch, caplog):
    now=[100.0]
    monkeypatch.setattr(bg,'time',NS(monotonic=lambda:now[0]))
    secret='synthetic-private-error'
    def fail(kind):
        try:
            raise kind(secret)
        except Exception as error:
            bg.log_failure(logging.getLogger('fixture'),'fixture-job',error)
    for _ in range(4):fail(ValueError)
    fail(RuntimeError)
    assert sum(r.exc_info is not None for r in caplog.records)==2
    assert sum('traceback rate-limited' in r.message for r in caplog.records)==1
    assert secret not in caplog.text
    now[0]=401
    fail(ValueError)
    assert sum(r.exc_info is not None for r in caplog.records)==3
    for n in range(bg._ERROR_LIMIT+1):
        bg.log_failure(Mock(), 'synthetic-'+str(n), ValueError(secret))
    assert len(bg._errors)==bg._ERROR_LIMIT


def test_traceback_does_not_include_original_exception_chain(caplog):
    secret='synthetic-secret-chain'
    try:
        try:
            raise ValueError(secret)
        except ValueError as cause:
            raise RuntimeError(secret) from cause
    except RuntimeError as error:
        bg.log_failure(logging.getLogger('fixture'),'fixture-job',error)
    assert secret not in caplog.text
    record=caplog.records[-1]
    assert str(record.exc_info[1])=='RuntimeError'
    assert record.exc_info[1].__cause__ is None


def test_periodic_cadence_is_immediate_then_interval_after_completion(monkeypatch):
    async def run():
        clock=[0.0];starts=[];sleeps=[]
        monkeypatch.setattr(bg,'time',NS(monotonic=lambda:clock[0]))
        async def job():
            starts.append(clock[0]);clock[0]+=3
        async def sleep(delay):
            if asyncio.current_task().get_name().startswith('health:'):
                await asyncio.Event().wait()
            sleeps.append(delay)
            if len(sleeps)==3:raise asyncio.CancelledError()
            clock[0]+=delay
        monkeypatch.setattr(bg,'asyncio',NS(create_task=asyncio.create_task,sleep=sleep,CancelledError=asyncio.CancelledError,gather=asyncio.gather,shield=asyncio.shield))
        with pytest.raises(asyncio.CancelledError):
            await bg.run_periodic('fixture',job,60)
        assert starts==[0,63,126] and sleeps==[60,60,60]
    asyncio.run(run())


@pytest.mark.parametrize('during_job',[True,False])
def test_cancellation_during_work_or_sleep_awaits_owned_monitor(during_job):
    async def run():
        entered=asyncio.Event()
        async def job():
            entered.set()
            if during_job:await asyncio.Event().wait()
        task=asyncio.create_task(bg.run_periodic('fixture',job,10))
        await entered.wait();await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert not bg.job_health()['fixture']['running']
        assert not any(t.get_name()=='health:fixture' for t in asyncio.all_tasks())
    asyncio.run(run())


def test_stuck_iteration_warns_while_waiting_and_is_never_reentered():
    async def run():
        entered=asyncio.Event();warned=asyncio.Event();calls=[]
        async def job():calls.append(1);entered.set();await asyncio.Event().wait()
        logger=Mock()
        logger.warning.side_effect=lambda *args:warned.set()
        task=asyncio.create_task(bg.run_periodic('fixture',job,.005,logger=logger))
        try:
            await entered.wait();await asyncio.wait_for(warned.wait(),1)
            assert calls==[1] and logger.warning.call_count==1
            assert bg.job_health()['fixture']['last_success'] is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())


def test_job_names_are_independent_and_duplicate_owner_is_rejected():
    async def run():
        entered=asyncio.Event();release=asyncio.Event()
        async def job():entered.set();await release.wait()
        a=asyncio.create_task(bg.run_periodic('a',job,10,once=True))
        await entered.wait()
        second=AsyncMock()
        with pytest.raises(RuntimeError,match='already has an owner'):
            await bg.run_periodic('a',second,10,once=True)
        second.assert_not_awaited()
        await bg.run_periodic('b',AsyncMock(),10,once=True)
        assert bg.job_health()['a']['last_success'] is None
        assert bg.job_health()['b']['last_success'] is not None
        release.set();await a
    asyncio.run(run())


@pytest.mark.parametrize('interval',[0,-1,True,float('nan'),float('inf')])
def test_invalid_interval_does_not_start_work(interval):
    async def run():
        job=AsyncMock()
        with pytest.raises(ValueError):await bg.run_periodic('fixture',job,interval)
        job.assert_not_awaited()
    asyncio.run(run())


def test_cwl_actual_iteration_not_admission_updates_success(monkeypatch):
    from extensions.tasks import cwl_reminder as bridge
    from utils import manage_web_worker as worker
    async def run():
        stopped=[]
        async def heartbeat(mongo):
            try:await asyncio.Event().wait()
            finally:stopped.append(True)
        async def polled():
            await asyncio.sleep(0)
            return poll.return_value
        poll=AsyncMock(side_effect=polled,return_value=False)
        monkeypatch.setattr(worker,'maintain_worker_heartbeat',heartbeat)
        monkeypatch.setattr(worker,'poll',AsyncMock(return_value=0))
        monkeypatch.setattr(bridge,'_poll_web_roster_bridge',poll)
        assert await bridge._drive_web_roster_requests() is False
        assert bg.job_health()['cwl-web-roster-bridge']['last_success'] is None
        poll.return_value=True
        assert await bridge._drive_web_roster_requests() is True
        assert bg.job_health()['cwl-web-roster-bridge']['last_success'] is not None
        assert not worker.queue_lock().locked()
        assert len(stopped)==2
    asyncio.run(run())


def test_war_scan_cancellation_drains_all_sibling_tasks(monkeypatch):
    from extensions.tasks import war_reminders as war
    async def run():
        both=asyncio.Event();entered=[];cleaned=[]
        async def scan(*args):
            config=args[-1];entered.append(config['_id'])
            if len(entered)==2:both.set()
            try:
                await both.wait()
                if config['_id']=='a':raise asyncio.CancelledError()
                await asyncio.Event().wait()
            finally:cleaned.append(config['_id'])
        store=NS(ensure_indexes=AsyncMock(),enabled_settings=AsyncMock(return_value=[{'_id':'a'},{'_id':'b'}]))
        monkeypatch.setattr(war,'WarReminderStore',lambda db:store)
        monkeypatch.setattr(war,'scan_clan',scan)
        with pytest.raises(asyncio.CancelledError):await war.loop(object(),object(),object())
        assert sorted(cleaned)==['a','b']
        assert not bg.job_health()['war-reminders']['running']
    asyncio.run(run())


def test_real_cwl_partial_reconciliation_keeps_independent_queue_and_failed_health(monkeypatch):
    from extensions.tasks import cwl_reminder as bridge
    async def run():
        pending=AsyncMock();post=NS(ensure_ready=AsyncMock(return_value=True),poll=AsyncMock())
        monkeypatch.setattr(bridge,'mongo_client',object())
        monkeypatch.setattr(bridge,'bot_instance',object())
        monkeypatch.setattr(bridge,'_post_update_worker_for_runtime',lambda:post)
        monkeypatch.setattr(bridge,'_loaded_campaign_generations',lambda guild:{})
        monkeypatch.setattr(bridge.cwl_web_bridge,'reconcile_campaign_changes',AsyncMock(side_effect=RuntimeError('synthetic-outage')))
        monkeypatch.setattr(bridge.cwl_web_bridge,'process_pending_roster_requests',pending)
        assert await bridge._poll_web_roster_bridge() is False
        pending.assert_awaited_once();post.poll.assert_awaited_once()
        bridge.cwl_web_bridge.reconcile_campaign_changes.side_effect=None
        post.ensure_ready.return_value=False;post.poll.reset_mock()
        assert await bridge._poll_web_roster_bridge() is False
        post.poll.assert_not_awaited()
        pending.side_effect=ValueError('synthetic-malformed-data')
        assert await bridge._poll_web_roster_bridge() is False
        assert pending.await_count==3
        pending.side_effect=None
        post.ensure_ready.return_value=True
        monkeypatch.setattr(bridge,'_loaded_campaign_generations',lambda guild:None)
        assert await bridge._poll_web_roster_bridge() is False
        assert pending.call_args.kwargs['schedule_ready'] is False
    asyncio.run(run())


def test_partial_war_clan_does_not_report_success_then_whole_pass_recovers(monkeypatch):
    from extensions.tasks import war_reminders as war
    async def run():
        store=NS(ensure_indexes=AsyncMock(),enabled_settings=AsyncMock(return_value=[{'_id':'a'},{'_id':'b'}]))
        monkeypatch.setattr(war,'WarReminderStore',lambda db:store)
        scan=AsyncMock(side_effect=[None,False])
        monkeypatch.setattr(war,'scan_clan',scan)
        async def one(name,job,interval,*,logger):
            return await bg.run_periodic(name,job,interval,once=True,logger=logger)
        monkeypatch.setattr(war,'run_periodic',one)
        await war.loop(object(),object(),object())
        assert bg.job_health()['war-reminders']['last_success'] is None
        assert scan.await_count==2
        scan.side_effect=[None,None]
        await war.loop(object(),object(),object())
        assert bg.job_health()['war-reminders']['last_success'] is not None
    asyncio.run(run())


def test_success_clears_only_its_own_error_namespace():
    async def run():
        for name in ('fixture','fixture.step','unrelated'):
            bg.log_failure(Mock(),name,RuntimeError())
        await bg.run_periodic('fixture',AsyncMock(),10,once=True)
        assert {key[0] for key in bg._errors}=={'unrelated'}
    asyncio.run(run())


def test_repeated_cancellation_waits_for_owned_task_cleanup():
    async def run():
        entered=asyncio.Event();cleaning=asyncio.Event();release=asyncio.Event();finished=[]
        async def child():
            try:
                entered.set();await asyncio.Event().wait()
            finally:
                cleaning.set();await release.wait();finished.append(True)
        task=asyncio.create_task(child());await entered.wait()
        owner=asyncio.create_task(bg.cancel_and_wait([task]))
        await cleaning.wait();owner.cancel();await asyncio.sleep(0)
        assert not owner.done() and not finished
        release.set()
        with pytest.raises(asyncio.CancelledError):await owner
        assert finished==[True] and task.done()
    asyncio.run(run())


@pytest.mark.parametrize('missing_generation',[False,True],ids=['stale-non-none','none'])
def test_actual_repair_backoff_keeps_health_unhealthy_until_acknowledged(monkeypatch,caplog,missing_generation):
    """Actual reconciliation + periodic health; only Mongo/provider inputs fake."""
    from extensions.tasks import cwl_reminder as bridge
    from utils import cwl_web_bridge as durable
    async def run():
        clock=[0.0];mode=['baseline'];generations=[{'2026-11':'old-gen'}]
        name='cwl-web-roster-bridge';epoch='m121-synthetic-current-epoch'
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(bg,'time',NS(monotonic=lambda:clock[0]))
        monkeypatch.setattr(durable,'time',NS(monotonic=lambda:clock[0]))
        durable._schedule_repair_attempts.clear()
        class Cursor:
            def __init__(self,rows):self.rows=rows
            async def to_list(self,length=None):return [dict(row) for row in self.rows]
        class Collection:
            def __init__(self):
                self.rows=[{'_id':'active-cycle','revision':1,'updated_at':'one',
                            'recurring_updated_at':'','cycle':'2026-11'}]
                self.worker={};self.updates=[];self.find_calls=0;self.find_one_calls=0
            def find(self,*args,**kwargs):
                self.find_calls+=1;return Cursor(self.rows)
            async def find_one(self,*args,**kwargs):
                self.find_one_calls+=1;return dict(self.worker)
            async def update_one(self,query,update,**kwargs):
                self.updates.append((query,update,kwargs));self.worker.update(update['$set'])
        collection=Collection()
        async def reload_schedule():
            if mode[0]=='fail':raise OSError('synthetic schedule unavailable')
            generations[0]={'2026-11':'new-gen' if mode[0]=='repair' else 'old-gen'}
            return True
        reload=AsyncMock(side_effect=reload_schedule)
        queue=AsyncMock(return_value=0)
        post=NS(ensure_ready=AsyncMock(return_value=True),poll=AsyncMock(return_value=0))
        observed=[];actual_reconcile=durable.reconcile_campaign_changes
        async def reconcile(*args,**kwargs):
            result=await actual_reconcile(*args,**kwargs)
            observed.append(result)
            return result
        monkeypatch.setattr(bridge,'mongo_client',NS(bot_config=collection))
        monkeypatch.setattr(bridge,'bot_instance',object())
        monkeypatch.setattr(bridge,'_campaign_runtime_id',epoch)
        monkeypatch.setattr(bridge,'_loaded_campaign_generations',lambda guild:generations[0])
        monkeypatch.setattr(bridge,'_sync_all_campaigns',reload)
        monkeypatch.setattr(bridge,'_post_update_worker_for_runtime',lambda:post)
        monkeypatch.setattr(durable,'process_pending_roster_requests',queue)
        monkeypatch.setattr(durable,'reconcile_campaign_changes',reconcile)
        async def tick():
            return await bg.run_periodic(name,bridge._poll_web_roster_bridge,10,once=True)
        try:
            assert await tick() is True  # Real initial acknowledgement.
            assert observed==[True] and len(collection.updates)==1
            assert await tick() is True  # Healthy no-op still returns False publicly.
            assert observed==[True,False] and reload.await_count==1
            previous=bg.job_health()[name]['last_success']
            collection.rows[0].update(revision=2,updated_at='two')
            if missing_generation:generations[0]=None
            mode[0]='fail';clock[0]=1
            assert await tick() is False
            assert bg.job_health()[name]['last_success']==previous
            assert durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID,epoch)
            assert not durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID,'different-epoch')
            assert not durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID+1,epoch)
            assert reload.await_count==2 and queue.await_count==3
            clock[0]=40
            assert await tick() is False  # Actual repair backoff, not an AsyncMock bool.
            assert observed[-1] is False and reload.await_count==2
            assert queue.await_count==4 and post.poll.await_count==4
            assert bg.job_health()[name]['last_success']==previous
            assert bg.job_health()[name]['stale'] is True
            assert sum('Background job recovered' in r.message for r in caplog.records)==0
            clock[0]=301
            assert durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID,epoch)
            assert bg.job_health()[name]['last_success']==previous  # Deadline alone is not recovery.
            clock[0]=302;mode[0]='repair'
            assert await tick() is True
            assert reload.await_count==3 and len(collection.updates)==2
            assert not durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID,epoch)
            assert bg.job_health()[name]['last_success']!=previous
            assert bg.job_health()[name]['stale'] is False
            clock[0]=303
            assert await tick() is True and observed[-1] is False  # Healthy unchanged no-op.
            assert reload.await_count==3 and len(collection.updates)==2
            assert queue.await_count==post.poll.await_count==6
            # Health observation adds no preview/provider read or persistent write.
            assert collection.find_calls==collection.find_one_calls==6
            assert sum('no success for three intervals' in r.message for r in caplog.records)==1
            assert sum('Background job recovered' in r.message for r in caplog.records)==1
            # A reverted desired fingerprint matches the acknowledged installed
            # generation: actual reconcile clears the failed-attempt cache.
            collection.rows[0].update(revision=3,updated_at='three')
            clock[0]=304;mode[0]='fail'
            assert await tick() is False
            assert durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID,epoch)
            collection.rows[0].update(revision=2,updated_at='two')
            clock[0]=305
            assert await tick() is True and observed[-1] is False
            assert reload.await_count==4 and len(collection.updates)==2
            assert not durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID,epoch)
            assert queue.await_count==post.poll.await_count==8
            assert collection.find_calls==collection.find_one_calls==8
        finally:
            durable._schedule_repair_attempts.clear()
    asyncio.run(run())


@pytest.mark.parametrize('missing_generation',[False,True],ids=['stale-non-none','none'])
def test_actual_reconcile_cancellation_never_advances_health_or_runs_queue(monkeypatch,missing_generation):
    from extensions.tasks import cwl_reminder as bridge
    from utils import cwl_web_bridge as durable
    async def run():
        entered=asyncio.Event();epoch='m121-synthetic-cancel-epoch'
        durable._schedule_repair_attempts.clear()
        class Cursor:
            async def to_list(self,length=None):
                return [{'_id':'active-cycle','revision':2,'updated_at':'two','recurring_updated_at':'','cycle':'2026-11'}]
        class Collection:
            def find(self,*args,**kwargs):return Cursor()
            async def find_one(self,*args,**kwargs):return {'schedule_fingerprint':'old'}
            async def update_one(self,*args,**kwargs):raise AssertionError('Cancelled reload cannot acknowledge')
        async def reload():entered.set();await asyncio.Event().wait()
        queue=AsyncMock()
        monkeypatch.setattr(bridge,'mongo_client',NS(bot_config=Collection()))
        monkeypatch.setattr(bridge,'bot_instance',object())
        monkeypatch.setattr(bridge,'_campaign_runtime_id',epoch)
        monkeypatch.setattr(bridge,'_loaded_campaign_generations',lambda guild:None if missing_generation else {'2026-11':'old-gen'})
        monkeypatch.setattr(bridge,'_sync_all_campaigns',reload)
        monkeypatch.setattr(durable,'process_pending_roster_requests',queue)
        task=asyncio.create_task(bg.run_periodic('cwl-web-roster-bridge',bridge._poll_web_roster_bridge,10,once=True))
        try:
            await entered.wait();task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            queue.assert_not_awaited()
            assert bg.job_health()['cwl-web-roster-bridge']['last_success'] is None
            assert not bg.job_health()['cwl-web-roster-bridge']['running']
            assert durable.schedule_repair_pending(bridge.cwl_campaign.LEGACY_WU_GUILD_ID,epoch)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
            durable._schedule_repair_attempts.clear()
    asyncio.run(run())

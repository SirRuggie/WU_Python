import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import coc
import pytest
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from extensions.commands.fwa import lazy_cwl_service as service
from utils import lazy_cwl_store as store
from tests.test_lazy_cwl_store import _Collection, _Mongo, _list_doc, NOW


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- fakes ----


class FakeMember:
    def __init__(self, tag, name, town_hall):
        self.tag = tag
        self.name = name
        self.town_hall = town_hall


class FakeClan:
    def __init__(self, tag, name, members):
        self.tag = tag
        self.name = name
        self.members = members


class FakeCoc:
    def __init__(self, clan=None, player=None, player_error=None):
        self.clan = clan
        self.player = player
        self.player_error = player_error
        self.get_clan_calls = []
        self.get_player_calls = []

    async def get_clan(self, tag):
        self.get_clan_calls.append(tag)
        if self.clan is None:
            raise coc.NotFound(SimpleNamespace(status=404), "not found")
        return self.clan

    async def get_player(self, tag):
        self.get_player_calls.append(tag)
        if self.player_error is not None:
            raise self.player_error
        return self.player


class FakeRest:
    def __init__(self):
        self.sent = []

    async def create_message(self, **kwargs):
        self.sent.append(kwargs)


class FakeBot:
    def __init__(self):
        self.rest = FakeRest()


class FakeScheduler:
    def __init__(self, fail_add=False):
        self.running = False
        self.jobs = {}
        self.add_job_calls = []
        self.removed = []
        self.fail_add = fail_add
        self.shutdown_calls = []

    def start(self):
        self.running = True

    def add_job(self, function, **kwargs):
        self.add_job_calls.append((function, kwargs))
        if self.fail_add:
            raise RuntimeError("scheduler unavailable")
        job_id = kwargs["id"]
        if job_id in self.jobs and not kwargs.get("replace_existing"):
            raise Exception(f"Job {job_id!r} already exists")
        self.jobs[job_id] = (function, kwargs)

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise JobLookupError(job_id)
        self.removed.append(job_id)
        self.jobs.pop(job_id, None)

    def shutdown(self, wait=True):
        self.shutdown_calls.append(wait)


def _fake_mongo(docs=(), clans=None):
    mongo = _Mongo(docs)
    mongo.clans = _Collection(clans or [])
    return mongo


def _wire(monkeypatch, *, mongo, coc_client=None, bot=None, scheduler=None, links):
    monkeypatch.setattr(service, "mongo_client", mongo)
    monkeypatch.setattr(service, "coc_client", coc_client)
    monkeypatch.setattr(service, "bot_instance", bot)
    monkeypatch.setattr(service, "scheduler", scheduler)

    async def fake_get_discord_ids(tags):
        return links

    monkeypatch.setattr(service, "get_discord_ids", fake_get_discord_ids)


# ------------------------------------------------------------ save_list ----


def test_save_list_happy_path(monkeypatch):
    clan = FakeClan("#ABC", "Alpha", [
        FakeMember("#PQ8GR", "One", 15),
        FakeMember("#P2", "Two", 14),
    ])
    mongo = _fake_mongo()
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan), links={"#PQ8GR": "111", "#P2": None})

    result = asyncio.run(service.save_list("#ABC", saved_by=42))

    assert result["ok"] is True
    assert result["clan_name"] == "Alpha"
    assert result["player_count"] == 2
    assert result["linked_count"] == 1
    assert result["already_saved"] is False
    doc = asyncio.run(store.get_active(mongo, "#ABC"))
    assert doc["players"][0]["discord_id"] == 111
    assert doc["players"][1]["discord_id"] is None


def test_save_list_link_service_down(monkeypatch):
    clan = FakeClan("#ABC", "Alpha", [FakeMember("#PQ8GR", "One", 15)])
    mongo = _fake_mongo()
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan), links=None)

    result = asyncio.run(service.save_list("#ABC", saved_by=42))

    assert result["ok"] is False
    assert "link service" in result["error"]
    assert asyncio.run(store.get_active(mongo, "#ABC")) is None


def test_save_list_already_saved(monkeypatch):
    clan = FakeClan("#ABC", "Alpha", [FakeMember("#PQ8GR", "One", 15)])
    existing = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    mongo = _fake_mongo([existing])
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan), links={"#PQ8GR": None})

    result = asyncio.run(service.save_list("#ABC", saved_by=42))

    assert result["ok"] is False
    assert result["already_saved"] is True
    assert result["existing_saved_at"] == existing["saved_at"]


# ------------------------------------------------------------ remind_now ----


def test_remind_now_none_away(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    doc["players"] = [{"tag": "#PQ8GR", "name": "One", "town_hall": 15, "discord_id": 111,
                        "added_manually": False, "added_at": NOW}]
    clan = FakeClan("#ABC", "Alpha", [FakeMember("#PQ8GR", "One", 15)])
    mongo = _fake_mongo([doc])
    bot = FakeBot()
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan), bot=bot, links={})

    result = asyncio.run(service.remind_now("#ABC"))

    assert result == {
        "ok": True, "clan_name": "Alpha", "away_count": 0,
        "total_count": 1, "sent": False, "error": None,
    }
    assert bot.rest.sent == []


def test_remind_now_some_away_sends_once_and_records(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    doc["players"] = [
        {"tag": "#PQ8GR", "name": "One", "town_hall": 15, "discord_id": 111,
         "added_manually": False, "added_at": NOW},
        {"tag": "#P2", "name": "Two", "town_hall": 14, "discord_id": None,
         "added_manually": False, "added_at": NOW},
    ]
    clan = FakeClan("#ABC", "Alpha", [FakeMember("#PQ8GR", "One", 15)])  # P2 is away
    mongo = _fake_mongo([doc], clans=[{"_id": "c1", "tag": "#ABC", "role_id": "555"}])
    bot = FakeBot()
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan), bot=bot, links={})

    result = asyncio.run(service.remind_now("#ABC"))

    assert result["sent"] is True
    assert result["away_count"] == 1
    assert len(bot.rest.sent) == 1
    assert bot.rest.sent[0]["role_mentions"] == [555]
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["reminders"]["sent_count"] == 1
    assert refreshed["reminders"]["last_sent_at"] is not None


def test_remind_now_no_active_list(monkeypatch):
    mongo = _fake_mongo()
    _wire(monkeypatch, mongo=mongo, links={})

    result = asyncio.run(service.remind_now("#ABC"))
    assert result == {
        "ok": False, "clan_name": None, "away_count": 0, "total_count": 0,
        "sent": False, "error": "No saved list for this clan.",
    }


# ------------------------------------------------------- add_player_by_tag ----


def test_add_player_by_tag_invalid_tag(monkeypatch):
    mongo = _fake_mongo()
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(), links={})

    result = asyncio.run(service.add_player_by_tag("#ABC", "not-a-tag"))
    assert result["ok"] is False
    assert result["reason"] == "invalid_tag"


def test_add_player_by_tag_not_found(monkeypatch):
    mongo = _fake_mongo()
    error = coc.NotFound(SimpleNamespace(status=404), "not found")
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(player_error=error), links={})

    result = asyncio.run(service.add_player_by_tag("#ABC", "#PQ8GR"))
    assert result["ok"] is False
    assert result["reason"] == "not_found"


def test_add_player_by_tag_no_list(monkeypatch):
    mongo = _fake_mongo()
    player = FakeMember("#PQ8GR", "One", 15)
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(player=player), links={"#PQ8GR": None})

    result = asyncio.run(service.add_player_by_tag("#ABC", "#PQ8GR"))
    assert result["ok"] is False
    assert result["reason"] == "no_list"


def test_add_player_by_tag_already_listed(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["players"] = [{"tag": "#PQ8GR", "name": "One", "town_hall": 15, "discord_id": None,
                        "added_manually": False, "added_at": NOW}]
    mongo = _fake_mongo([doc])
    clan = FakeClan("#ABC", "Alpha", [FakeMember("#PQ8GR", "One", 15)])
    player = FakeMember("#PQ8GR", "One", 15)
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan, player=player), links={"#PQ8GR": None})

    result = asyncio.run(service.add_player_by_tag("#ABC", "#PQ8GR"))
    assert result["ok"] is False
    assert result["reason"] == "already_listed"


def test_add_player_by_tag_link_service_down_still_adds(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC")
    mongo = _fake_mongo([doc])
    clan = FakeClan("#ABC", "Alpha", [])  # player absent from clan -> away
    player = FakeMember("#PQ8GR", "One", 15)
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan, player=player), links=None)

    result = asyncio.run(service.add_player_by_tag("#ABC", "#PQ8GR"))

    assert result["ok"] is True
    assert result["discord_id"] is None
    assert result["reason"] == "link_service_down"
    assert result["away_now"] is True


def test_add_player_by_tag_away_now_true(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC")
    mongo = _fake_mongo([doc])
    clan = FakeClan("#ABC", "Alpha", [])  # player not in clan
    player = FakeMember("#PQ8GR", "One", 15)
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan, player=player), links={"#PQ8GR": "222"})

    result = asyncio.run(service.add_player_by_tag("#ABC", "#PQ8GR"))

    assert result["ok"] is True
    assert result["discord_id"] == 222
    assert result["away_now"] is True
    assert result["reason"] is None


# --------------------------------------------------------- set_reminders ----


def test_set_reminders_enable_adds_job(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC")
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    result = asyncio.run(service.set_reminders("#ABC", True, every_minutes=30))

    assert result == {"ok": True, "error": None}
    assert "lazycwl_reminder_list-1" in scheduler.jobs
    _function, kwargs = scheduler.jobs["lazycwl_reminder_list-1"]
    trigger = kwargs["trigger"]
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 30 * 60
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["reminders"]["enabled"] is True


def test_set_reminders_enabled_without_every_minutes_rejected(monkeypatch):
    """builder-05 NOTED 7: return ok False before touching the store."""
    doc = _list_doc("list-1", clan_tag="ABC")
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    result = asyncio.run(service.set_reminders("#ABC", True, every_minutes=None))

    assert result == {"ok": False, "error": "Choose how often."}
    assert scheduler.add_job_calls == []
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["reminders"]["enabled"] is False


def test_set_reminders_add_job_failure_rolls_back(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC")
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler(fail_add=True)
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    result = asyncio.run(service.set_reminders("#ABC", True, every_minutes=30))

    assert result["ok"] is False
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["reminders"]["enabled"] is False


# ----------------------------------------------------------- reminder_job ----


def test_remove_job_logs_warning_on_unexpected_exception(monkeypatch, caplog):
    """builder-05 NOTED 8: JobLookupError stays silent, anything else logs
    at WARNING."""
    class BoomScheduler:
        def remove_job(self, job_id):
            raise RuntimeError("boom")

    monkeypatch.setattr(service, "scheduler", BoomScheduler())

    with caplog.at_level(logging.WARNING):
        service._remove_job("some-job")

    assert any("unexpected error" in record.message for record in caplog.records)


def test_remove_job_silent_on_job_lookup_error(monkeypatch, caplog):
    class MissingScheduler:
        def remove_job(self, job_id):
            raise JobLookupError(job_id)

    monkeypatch.setattr(service, "scheduler", MissingScheduler())

    with caplog.at_level(logging.WARNING):
        service._remove_job("missing-job")

    assert caplog.records == []


def test_reminder_job_coc_error_does_not_propagate(monkeypatch):
    """builder-05 NOTED 5: a coc outage inside remind_now must not escape
    reminder_job and reach APScheduler."""
    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    doc["reminders"]["enabled"] = True
    doc["reminders"]["every_minutes"] = 30
    doc["reminders"]["started_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()

    class ExplodingCoc:
        async def get_clan(self, tag):
            raise RuntimeError("coc api outage")

    _wire(monkeypatch, mongo=mongo, coc_client=ExplodingCoc(), scheduler=scheduler, links={})

    asyncio.run(service.reminder_job("list-1"))  # must not raise


def test_reminder_job_inactive_removes_job(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC", status="finished")
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    scheduler.jobs["lazycwl_reminder_list-1"] = (None, {})
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    asyncio.run(service.reminder_job("list-1"))

    assert "lazycwl_reminder_list-1" in scheduler.removed


def test_reminder_job_seven_day_limit_disables(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    doc["reminders"]["enabled"] = True
    doc["reminders"]["every_minutes"] = 30
    doc["reminders"]["started_at"] = datetime.now(timezone.utc) - timedelta(days=8)
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    scheduler.jobs["lazycwl_reminder_list-1"] = (None, {})
    bot = FakeBot()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, bot=bot, links={})

    asyncio.run(service.reminder_job("list-1"))

    assert "lazycwl_reminder_list-1" in scheduler.removed
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["reminders"]["enabled"] is False
    assert len(bot.rest.sent) == 1
    assert "stopped after 7 days" in bot.rest.sent[0]["components"][0].components[0].content


def test_reminder_job_sends_when_eligible(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    doc["reminders"]["enabled"] = True
    doc["reminders"]["every_minutes"] = 30
    doc["reminders"]["started_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    doc["players"] = [{"tag": "#PQ8GR", "name": "One", "town_hall": 15, "discord_id": None,
                        "added_manually": False, "added_at": NOW}]
    clan = FakeClan("#ABC", "Alpha", [])  # P1 away
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    bot = FakeBot()
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan), scheduler=scheduler, bot=bot, links={})

    asyncio.run(service.reminder_job("list-1"))

    assert len(bot.rest.sent) == 1
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["reminders"]["sent_count"] == 1


# ------------------------------------------------------ restore_reminder_jobs ----


def test_restore_skips_existing_job(monkeypatch):
    """builder-05 must-fix 1: FakeScheduler.add_job now records every call
    and raises on a duplicate id, so the assertion below only holds if the
    get_job guard in restore_reminder_jobs actually skipped the call.
    Proven failing-first: with lazy_cwl_service.py's
    `if scheduler.get_job(job_id) is not None: continue` guard removed,
    add_job is called for list-1 and the seeded tuple is overwritten."""
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["reminders"]["enabled"] = True
    doc["reminders"]["every_minutes"] = 30
    doc["reminders"]["started_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    seeded = (None, {"id": "lazycwl_reminder_list-1"})
    scheduler.jobs["lazycwl_reminder_list-1"] = seeded
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    asyncio.run(service.restore_reminder_jobs())

    assert len(scheduler.add_job_calls) == 0
    assert scheduler.jobs["lazycwl_reminder_list-1"] is seeded


def test_restore_disables_after_seven_days(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["reminders"]["enabled"] = True
    doc["reminders"]["every_minutes"] = 30
    doc["reminders"]["started_at"] = datetime.now(timezone.utc) - timedelta(days=8)
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    asyncio.run(service.restore_reminder_jobs())

    assert scheduler.jobs == {}
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["reminders"]["enabled"] is False


# --------------------------------------------------------------- reconcile ----


def test_reconcile_order_indexes_before_expire_before_restore(monkeypatch):
    calls = []

    async def fake_ensure_indexes(mongo):
        calls.append("ensure_indexes")

    async def fake_expire(now=None):
        calls.append("expire")
        return 0

    async def fake_restore():
        calls.append("restore")

    mongo = _fake_mongo()
    scheduler = FakeScheduler()
    scheduler.running = True
    monkeypatch.setattr(service, "mongo_client", mongo)
    monkeypatch.setattr(service, "scheduler", scheduler)
    monkeypatch.setattr(store, "ensure_indexes", fake_ensure_indexes)
    monkeypatch.setattr(service, "expire_due_and_stop_jobs", fake_expire)
    monkeypatch.setattr(service, "restore_reminder_jobs", fake_restore)

    asyncio.run(service.reconcile())

    assert calls == ["ensure_indexes", "expire", "restore"]
    assert service.EXPIRY_JOB_ID in scheduler.jobs
    _function, kwargs = scheduler.jobs[service.EXPIRY_JOB_ID]
    trigger = kwargs["trigger"]
    assert isinstance(trigger, CronTrigger)
    fields_by_name = {field.name: field for field in trigger.fields}
    assert str(fields_by_name["hour"]) == "0"
    assert str(fields_by_name["minute"]) == "10"
    assert str(trigger.timezone) == "UTC"


def test_reconcile_scheduler_none_raises(monkeypatch):
    """builder-05 NOTED 6: reconcile() must fail loudly, not silently skip
    start() and die later inside restore's get_job call."""
    monkeypatch.setattr(service, "scheduler", None)

    with pytest.raises(RuntimeError, match="service not started"):
        asyncio.run(service.reconcile())


def test_reconcile_reraises_on_index_failure_and_skips_restore(monkeypatch):
    calls = []

    async def fake_ensure_indexes(mongo):
        raise RuntimeError("index permission denied")

    async def fake_restore():
        calls.append("restore")

    mongo = _fake_mongo()
    scheduler = FakeScheduler()
    scheduler.running = True
    monkeypatch.setattr(service, "mongo_client", mongo)
    monkeypatch.setattr(service, "scheduler", scheduler)
    monkeypatch.setattr(store, "ensure_indexes", fake_ensure_indexes)
    monkeypatch.setattr(service, "restore_reminder_jobs", fake_restore)

    with pytest.raises(RuntimeError):
        asyncio.run(service.reconcile())

    assert calls == []
    assert service.EXPIRY_JOB_ID not in scheduler.jobs


# ------------------------------------------------- expire_due_and_stop_jobs ----


def test_expire_due_and_stop_jobs_removes_jobs(monkeypatch):
    past = NOW - timedelta(days=1)
    doc = _list_doc("list-1", clan_tag="ABC", expires_at=past)
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    scheduler.jobs["lazycwl_reminder_list-1"] = (None, {})
    monkeypatch.setattr(service, "mongo_client", mongo)
    monkeypatch.setattr(service, "scheduler", scheduler)

    count = asyncio.run(service.expire_due_and_stop_jobs(NOW))

    assert count == 1
    assert "lazycwl_reminder_list-1" in scheduler.removed
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["status"] == "expired"


# --------------------------------------------------------------- start/stop ----


def test_start_twice_creates_one_scheduler(monkeypatch):
    monkeypatch.setattr(service, "scheduler", None)
    monkeypatch.setattr(service, "startup_reconciler", None)

    started = []

    class FakeReconciler:
        def __init__(self, name, operation):
            started.append((name, operation))

        def start(self):
            started.append("start")

    monkeypatch.setattr(service, "StartupReconciler", FakeReconciler)

    bot, coc_api, mongo = FakeBot(), FakeCoc(), _fake_mongo()
    asyncio.run(service.start(bot, coc_api, mongo))
    first_scheduler = service.scheduler
    first_reconciler = service.startup_reconciler

    asyncio.run(service.start(bot, coc_api, mongo))

    assert service.scheduler is first_scheduler
    assert service.startup_reconciler is first_reconciler


def test_stop_shuts_down_scheduler_and_clears_globals(monkeypatch):
    scheduler = FakeScheduler()

    class FakeReconciler:
        def __init__(self):
            self.stopped = False

        async def stop(self):
            self.stopped = True

    reconciler = FakeReconciler()
    monkeypatch.setattr(service, "scheduler", scheduler)
    monkeypatch.setattr(service, "startup_reconciler", reconciler)

    asyncio.run(service.stop())

    assert scheduler.shutdown_calls == [False]
    assert reconciler.stopped is True
    assert service.scheduler is None
    assert service.startup_reconciler is None


def test_stop_twice_is_safe(monkeypatch):
    monkeypatch.setattr(service, "scheduler", None)
    monkeypatch.setattr(service, "startup_reconciler", None)

    asyncio.run(service.stop())  # must not raise

    assert service.scheduler is None


# ------------------------------------------------------------------ finish ----


def test_finish_happy_path(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    mongo = _fake_mongo([doc])
    scheduler = FakeScheduler()
    scheduler.jobs["lazycwl_reminder_list-1"] = (None, {})
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    result = asyncio.run(service.finish("#ABC"))

    assert result == {"ok": True, "clan_name": "Alpha", "error": None}
    assert "lazycwl_reminder_list-1" in scheduler.removed
    refreshed = asyncio.run(store.get_by_id(mongo, "list-1"))
    assert refreshed["status"] == "finished"


def test_finish_no_active_list(monkeypatch):
    mongo = _fake_mongo()
    scheduler = FakeScheduler()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})

    result = asyncio.run(service.finish("#ABC"))

    assert result == {"ok": False, "clan_name": None, "error": "No saved list for this clan."}


# ------------------------------------------------------------ away_players ----


def test_away_players_filters_current_members(monkeypatch):
    doc = _list_doc("list-1", clan_tag="ABC")
    doc["players"] = [
        {"tag": "#P1", "name": "One", "town_hall": 15, "discord_id": None,
         "added_manually": False, "added_at": NOW},
        {"tag": "#P2", "name": "Two", "town_hall": 14, "discord_id": None,
         "added_manually": False, "added_at": NOW},
    ]
    clan = FakeClan("#ABC", "Alpha", [FakeMember("#P1", "One", 15)])  # P2 is away
    _wire(monkeypatch, mongo=_fake_mongo(), coc_client=FakeCoc(clan=clan), links={})

    away = asyncio.run(service.away_players(doc))

    assert [player["tag"] for player in away] == ["#P2"]


# ------------------------------------------------------- calculate_next_run ----
# Ported cadence cases from tests/test_lazy_cwl_scheduler.py:122-150, using
# reminders.last_sent_at / started_at / every_minutes instead of the old
# auto_ping_* field names.


def test_calculate_next_run_preserves_future_cadence_and_skips_missed_intervals():
    anchor = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    doc = {"reminders": {"last_sent_at": anchor, "every_minutes": 60}}

    assert service.calculate_next_run(
        doc, datetime(2026, 8, 4, 12, 25, tzinfo=timezone.utc),
    ) == datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc)
    assert service.calculate_next_run(
        doc, datetime(2026, 8, 4, 14, 5, tzinfo=timezone.utc),
    ) == datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)


def test_calculate_next_run_uses_start_time_before_first_send():
    doc = {"reminders": {
        "started_at": datetime(2026, 8, 4, 12, 0),
        "last_sent_at": None,
        "every_minutes": 30,
    }}

    assert service.calculate_next_run(
        doc, datetime(2026, 8, 4, 12, 10, tzinfo=timezone.utc),
    ) == datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc)


# ---------------------------------------------------- result-dict key sets ----
# D008: the full key set declared in briefs/builder-04.md section 4 is a
# contract every orchestration function must honour on every return path.

SAVE_LIST_KEYS = {
    "ok", "clan_name", "clan_tag", "player_count", "linked_count",
    "already_saved", "existing_saved_at", "error",
}
REMIND_NOW_KEYS = {"ok", "clan_name", "away_count", "total_count", "sent", "error"}
ADD_PLAYER_KEYS = {"ok", "name", "town_hall", "discord_id", "away_now", "error", "reason"}
SET_REMINDERS_KEYS = {"ok", "error"}
FINISH_KEYS = {"ok", "clan_name", "error"}


def test_save_list_key_set_matches_on_every_path(monkeypatch):
    happy_clan = FakeClan("#ABC", "Alpha", [FakeMember("#PQ8GR", "One", 15)])
    happy = asyncio.run(_call_save_list(monkeypatch, clan=happy_clan, links={"#PQ8GR": None}))
    assert set(happy.keys()) == SAVE_LIST_KEYS

    not_found = asyncio.run(_call_save_list(monkeypatch, clan=None, links={}))
    assert set(not_found.keys()) == SAVE_LIST_KEYS

    link_down = asyncio.run(_call_save_list(monkeypatch, clan=happy_clan, links=None))
    assert set(link_down.keys()) == SAVE_LIST_KEYS

    existing = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    already_saved = asyncio.run(_call_save_list(
        monkeypatch, clan=happy_clan, links={"#PQ8GR": None}, seeded=[existing],
    ))
    assert set(already_saved.keys()) == SAVE_LIST_KEYS


async def _call_save_list(monkeypatch, *, clan, links, seeded=()):
    mongo = _fake_mongo(seeded)
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(clan=clan), links=links)
    return await service.save_list("#ABC", saved_by=42)


def test_remind_now_key_set_matches_on_every_path(monkeypatch):
    mongo = _fake_mongo()
    _wire(monkeypatch, mongo=mongo, links={})
    no_list = asyncio.run(service.remind_now("#ABC"))
    assert set(no_list.keys()) == REMIND_NOW_KEYS

    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    doc["players"] = [{"tag": "#PQ8GR", "name": "One", "town_hall": 15, "discord_id": 111,
                        "added_manually": False, "added_at": NOW}]
    clan = FakeClan("#ABC", "Alpha", [FakeMember("#PQ8GR", "One", 15)])
    mongo2 = _fake_mongo([doc])
    _wire(monkeypatch, mongo=mongo2, coc_client=FakeCoc(clan=clan), bot=FakeBot(), links={})
    none_away = asyncio.run(service.remind_now("#ABC"))
    assert set(none_away.keys()) == REMIND_NOW_KEYS


def test_add_player_by_tag_key_set_matches_on_every_path(monkeypatch):
    mongo = _fake_mongo()
    _wire(monkeypatch, mongo=mongo, coc_client=FakeCoc(), links={})
    invalid = asyncio.run(service.add_player_by_tag("#ABC", "not-a-tag"))
    assert set(invalid.keys()) == ADD_PLAYER_KEYS

    doc = _list_doc("list-1", clan_tag="ABC")
    mongo2 = _fake_mongo([doc])
    clan = FakeClan("#ABC", "Alpha", [])
    player = FakeMember("#PQ8GR", "One", 15)
    _wire(monkeypatch, mongo=mongo2, coc_client=FakeCoc(clan=clan, player=player), links={"#PQ8GR": "222"})
    happy = asyncio.run(service.add_player_by_tag("#ABC", "#PQ8GR"))
    assert set(happy.keys()) == ADD_PLAYER_KEYS


def test_set_reminders_key_set_matches_on_every_path(monkeypatch):
    mongo = _fake_mongo()
    scheduler = FakeScheduler()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})
    no_list = asyncio.run(service.set_reminders("#ABC", True, every_minutes=30))
    assert set(no_list.keys()) == SET_REMINDERS_KEYS

    doc = _list_doc("list-1", clan_tag="ABC")
    mongo2 = _fake_mongo([doc])
    scheduler2 = FakeScheduler()
    _wire(monkeypatch, mongo=mongo2, scheduler=scheduler2, links={})
    happy = asyncio.run(service.set_reminders("#ABC", True, every_minutes=30))
    assert set(happy.keys()) == SET_REMINDERS_KEYS


def test_finish_key_set_matches_on_every_path(monkeypatch):
    mongo = _fake_mongo()
    scheduler = FakeScheduler()
    _wire(monkeypatch, mongo=mongo, scheduler=scheduler, links={})
    no_list = asyncio.run(service.finish("#ABC"))
    assert set(no_list.keys()) == FINISH_KEYS

    doc = _list_doc("list-1", clan_tag="ABC", clan_name="Alpha")
    mongo2 = _fake_mongo([doc])
    scheduler2 = FakeScheduler()
    _wire(monkeypatch, mongo=mongo2, scheduler=scheduler2, links={})
    happy = asyncio.run(service.finish("#ABC"))
    assert set(happy.keys()) == FINISH_KEYS


# --------------------------------------------------------- repo-wide grep ----


def test_only_store_mongo_and_tests_reference_lazy_cwl_lists():
    result = subprocess.run(
        ["grep", "-rl", "lazy_cwl_lists", "--include=*.py", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    hits = [
        line for line in result.stdout.splitlines()
        if not line.startswith("./.worktrees/") and not line.startswith("./.claude/")
    ]
    allowed_exact = {"./utils/lazy_cwl_store.py", "./utils/mongo.py"}
    disallowed = [
        hit for hit in hits
        if hit not in allowed_exact and not hit.startswith("./tests/")
    ]
    assert disallowed == []
    # builder-05 NOTED 9: a vacuous grep (zero hits at all) would also pass
    # the assertion above; require the accessor itself to actually show up.
    assert hits, "grep for lazy_cwl_lists returned nothing at all"
    assert "./utils/lazy_cwl_store.py" in hits


def test_service_module_never_references_collection_or_registers_actions():
    source = (REPO_ROOT / "extensions/commands/fwa/lazy_cwl_service.py").read_text()
    assert "lazy_cwl_lists" not in source
    for marker in ("@loader", "register_action", "listener"):
        assert marker not in source

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pendulum

from extensions.tasks import cwl_reminder as cwl


class FakeResult:
    def __init__(self, deleted_count=0):
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length=None):
        return deepcopy(self.documents)


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = deepcopy(documents or {})
        self.updates = []
        self.deletes = []

    async def find_one(self, query):
        return deepcopy(self.documents.get(query.get("_id")))

    def find(self):
        return FakeCursor(list(self.documents.values()))

    async def update_one(self, query, update, upsert=False):
        self.updates.append((deepcopy(query), deepcopy(update), upsert))
        document_id = query["_id"]
        inserted = document_id not in self.documents
        document = self.documents.setdefault(document_id, {"_id": document_id})

        def set_path(path, value):
            target = document
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = deepcopy(value)

        def unset_path(path):
            target = document
            parts = path.split(".")
            for part in parts[:-1]:
                target = target.get(part, {})
            target.pop(parts[-1], None)

        for path, value in update.get("$set", {}).items():
            set_path(path, value)
        if inserted:
            for path, value in update.get("$setOnInsert", {}).items():
                set_path(path, value)
        for path in update.get("$unset", {}):
            unset_path(path)
        return SimpleNamespace(modified_count=1)

    async def delete_one(self, query):
        self.deletes.append(deepcopy(query))
        existed = self.documents.pop(query.get("_id"), None) is not None
        return FakeResult(int(existed))


class FakeMongo:
    def __init__(self, schedule=None, pending=None):
        self.database = SimpleNamespace(
            cwl_reminder=FakeCollection(
                {"schedule": schedule} if schedule is not None else {},
            ),
            cwl_pending_reminders=FakeCollection(pending),
        )


class FakeScheduler:
    def __init__(self, fail_add=False):
        self.jobs = {}
        self.add_calls = []
        self.removed = []
        self.fail_add = fail_add

    def add_job(self, function, **kwargs):
        if self.fail_add:
            raise RuntimeError("scheduler unavailable")
        self.add_calls.append((function, kwargs))
        trigger = kwargs["trigger"]
        next_run_time = getattr(trigger, "run_date", None)
        self.jobs[kwargs["id"]] = SimpleNamespace(
            id=kwargs["id"],
            next_run_time=next_run_time,
            function=function,
            kwargs=kwargs,
        )

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.removed.append(job_id)
        self.jobs.pop(job_id, None)


class FakeRest:
    def __init__(self, failing_channels=None, channel_errors=None):
        self.failing_channels = set(failing_channels or [])
        self.channel_errors = dict(channel_errors or {})
        self.messages = []

    async def create_message(self, **kwargs):
        if kwargs["channel"] in self.channel_errors:
            raise self.channel_errors[kwargs["channel"]]
        if kwargs["channel"] in self.failing_channels:
            raise RuntimeError("delivery failed")
        self.messages.append(kwargs)


def configure(
    monkeypatch,
    *,
    schedule=None,
    pending=None,
    failing_channels=None,
    channel_errors=None,
):
    mongo = FakeMongo(schedule=schedule, pending=pending)
    scheduler = FakeScheduler()
    rest = FakeRest(failing_channels, channel_errors)
    monkeypatch.setattr(cwl, "mongo_client", mongo)
    monkeypatch.setattr(cwl, "scheduler", scheduler)
    monkeypatch.setattr(cwl, "bot_instance", SimpleNamespace(rest=rest))
    return mongo, scheduler, rest


def test_test_mode_is_delivery_only(monkeypatch):
    mongo, scheduler, rest = configure(
        monkeypatch,
        schedule={"_id": "schedule", "followups": [{"number": 1, "delay_minutes": 5}]},
    )

    delivered = asyncio.run(cwl.send_cwl_reminder(0, test_mode=True))

    assert delivered is True
    assert [message["channel"] for message in rest.messages] == [cwl.TEST_CHANNEL_ID]
    assert mongo.database.cwl_reminder.updates == []
    assert mongo.database.cwl_pending_reminders.updates == []
    assert mongo.database.cwl_pending_reminders.deletes == []
    assert scheduler.add_calls == []


def test_success_is_accounted_and_initial_schedules_followups_once(monkeypatch):
    mongo, scheduler, rest = configure(
        monkeypatch,
        schedule={
            "_id": "schedule",
            "followups": [{"number": 1, "delay_minutes": 10, "enabled": True}],
        },
    )

    delivered = asyncio.run(cwl.send_cwl_reminder(0))

    assert delivered is True
    assert {message["channel"] for message in rest.messages} == {
        cwl.CWL_CHANNEL_ID,
        cwl.LAZY_CWL_CHANNEL_ID,
    }
    saved_schedule = mongo.database.cwl_reminder.documents["schedule"]
    assert saved_schedule["last_sent_0"]
    assert set(scheduler.jobs) == {"cwl_followup_1"}
    assert set(mongo.database.cwl_pending_reminders.documents) == {"cwl_followup_1"}


def test_failed_channel_is_retried_without_false_success_accounting(monkeypatch):
    mongo, scheduler, rest = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        failing_channels={cwl.LAZY_CWL_CHANNEL_ID},
    )

    delivered = asyncio.run(cwl.send_cwl_reminder(2))

    assert delivered is False
    assert "last_sent_2" not in mongo.database.cwl_reminder.documents["schedule"]
    pending = mongo.database.cwl_pending_reminders.documents["cwl_followup_2"]
    assert pending["channel_keys"] == ["lazy"]
    assert pending["failure_count"] == 1
    assert pending["first_failed_at"] == pending["last_failed_at"]
    issue = mongo.database.cwl_reminder.documents["schedule"]["delivery_issues"]["2"]
    assert issue["status"] == "retrying"
    assert issue["failure_count"] == 1
    retry = scheduler.jobs["cwl_followup_2"]
    assert retry.kwargs["args"] == [2, False, ["lazy"]]

    rest.failing_channels.clear()
    retry_start = len(rest.messages)
    delivered = asyncio.run(retry.function(*retry.kwargs["args"]))

    assert delivered is True
    assert [message["channel"] for message in rest.messages[retry_start:]] == [
        cwl.LAZY_CWL_CHANNEL_ID,
    ]
    assert mongo.database.cwl_reminder.documents["schedule"]["last_sent_2"]
    assert "2" not in mongo.database.cwl_reminder.documents["schedule"]["delivery_issues"]
    assert "cwl_followup_2" not in mongo.database.cwl_pending_reminders.documents


def test_transient_failures_back_off_then_stop_at_the_cap(monkeypatch, capsys):
    mongo, scheduler, _ = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        failing_channels={cwl.LAZY_CWL_CHANNEL_ID},
    )

    observed_delays = []
    for expected_failure in range(1, cwl.MAX_DELIVERY_FAILURES + 1):
        delivered = asyncio.run(cwl.send_cwl_reminder(3, channel_keys=["lazy"]))
        assert delivered is False
        if expected_failure < cwl.MAX_DELIVERY_FAILURES:
            pending = mongo.database.cwl_pending_reminders.documents["cwl_followup_3"]
            assert pending["failure_count"] == expected_failure
            observed_delays.append(
                round(
                    (
                        pendulum.parse(pending["run_time"])
                        - pendulum.parse(pending["last_failed_at"])
                    ).total_seconds() / 60
                )
            )

    assert observed_delays == list(cwl.DELIVERY_RETRY_DELAYS_MINUTES)
    assert "cwl_followup_3" not in scheduler.jobs
    assert "cwl_followup_3" not in mongo.database.cwl_pending_reminders.documents
    issue = mongo.database.cwl_reminder.documents["schedule"]["delivery_issues"]["3"]
    assert issue["status"] == "abandoned"
    assert issue["reason"] == "max_failures_reached"
    assert issue["failure_count"] == cwl.MAX_DELIVERY_FAILURES
    output = capsys.readouterr().out
    assert "delivery_retry_scheduled" in output
    assert "ALERT delivery_abandoned" in output


def test_permanent_discord_error_is_not_retried(monkeypatch, capsys):
    class PermanentDeliveryError(RuntimeError):
        pass

    error = PermanentDeliveryError("missing access")
    mongo, scheduler, _ = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        channel_errors={cwl.LAZY_CWL_CHANNEL_ID: error},
    )
    monkeypatch.setattr(
        cwl,
        "_is_permanent_delivery_error",
        lambda exc: isinstance(exc, PermanentDeliveryError),
    )

    delivered = asyncio.run(cwl.send_cwl_reminder(4, channel_keys=["lazy"]))

    assert delivered is False
    assert "cwl_followup_4" not in scheduler.jobs
    assert "cwl_followup_4" not in mongo.database.cwl_pending_reminders.documents
    issue = mongo.database.cwl_reminder.documents["schedule"]["delivery_issues"]["4"]
    assert issue["reason"] == "permanent_discord_error"
    output = capsys.readouterr().out
    assert "retryable=false" in output
    assert "action=check channel IDs" in output


def test_retry_error_detail_is_bounded_and_single_line(monkeypatch):
    mongo, _, _ = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        channel_errors={
            cwl.LAZY_CWL_CHANNEL_ID: RuntimeError("x" * 300 + "\nsecret-looking-tail"),
        },
    )

    asyncio.run(cwl.send_cwl_reminder(5, channel_keys=["lazy"]))

    pending = mongo.database.cwl_pending_reminders.documents["cwl_followup_5"]
    assert len(pending["last_error"]) <= cwl.DELIVERY_ERROR_TEXT_LIMIT
    assert "\n" not in pending["last_error"]
    assert "secret-looking-tail" not in pending["last_error"]


def test_retry_scheduler_failure_keeps_durable_state_and_logs_alert(monkeypatch, capsys):
    mongo, _, _ = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        failing_channels={cwl.LAZY_CWL_CHANNEL_ID},
    )
    monkeypatch.setattr(cwl, "scheduler", FakeScheduler(fail_add=True))

    delivered = asyncio.run(cwl.send_cwl_reminder(2, channel_keys=["lazy"]))

    assert delivered is False
    pending = mongo.database.cwl_pending_reminders.documents["cwl_followup_2"]
    assert pending["failure_count"] == 1
    assert pending["status"] == "retrying"
    assert "ALERT delivery_retry_setup_failed" in capsys.readouterr().out


def test_invalid_stored_channel_is_terminal_and_cannot_restore(monkeypatch):
    mongo, scheduler, _ = configure(monkeypatch, schedule={"_id": "schedule"})

    delivered = asyncio.run(cwl.send_cwl_reminder(2, channel_keys=["removed-channel"]))

    assert delivered is False
    assert "cwl_followup_2" not in scheduler.jobs
    assert "cwl_followup_2" not in mongo.database.cwl_pending_reminders.documents
    issue = mongo.database.cwl_reminder.documents["schedule"]["delivery_issues"]["2"]
    assert issue["reason"] == "no_valid_channels"


def test_success_without_mongo_logs_missing_accounting(monkeypatch, capsys):
    rest = FakeRest()
    monkeypatch.setattr(cwl, "mongo_client", None)
    monkeypatch.setattr(cwl, "scheduler", FakeScheduler())
    monkeypatch.setattr(cwl, "bot_instance", SimpleNamespace(rest=rest))

    delivered = asyncio.run(cwl.send_cwl_reminder(0))

    assert delivered is True
    assert len(rest.messages) == 2
    assert "ALERT delivery_state_unavailable" in capsys.readouterr().out


def test_initial_failure_waits_to_schedule_followups_until_retry_succeeds(monkeypatch):
    mongo, scheduler, rest = configure(
        monkeypatch,
        schedule={
            "_id": "schedule",
            "followups": [{"number": 1, "delay_minutes": 10, "enabled": True}],
        },
        failing_channels={cwl.LAZY_CWL_CHANNEL_ID},
    )

    delivered = asyncio.run(cwl.send_cwl_reminder(0))

    assert delivered is False
    assert set(scheduler.jobs) == {cwl.cwl_initial_retry_job_id}
    assert "last_sent_0" not in mongo.database.cwl_reminder.documents["schedule"]

    retry = scheduler.jobs[cwl.cwl_initial_retry_job_id]
    rest.failing_channels.clear()
    delivered = asyncio.run(retry.function(*retry.kwargs["args"]))

    assert delivered is True
    assert set(scheduler.jobs) == {"cwl_followup_1"}
    assert mongo.database.cwl_reminder.documents["schedule"]["last_sent_0"]


def test_startup_restores_current_pending_before_next_base_schedule(monkeypatch):
    run_time = pendulum.now(cwl.DEFAULT_TIMEZONE).add(hours=2)
    pending = {
        "cwl_followup_1": {
            "_id": "cwl_followup_1",
            "job_id": "cwl_followup_1",
            "reminder_number": 1,
            "run_time": run_time.isoformat(),
        },
    }
    mongo, scheduler, rest = configure(
        monkeypatch,
        schedule={
            "_id": "schedule",
            "enabled": True,
            "day": 31,
            "hour": 18,
            "minute": 0,
            "followups": [{"number": 1, "delay_minutes": 60}],
        },
        pending=pending,
    )

    event = SimpleNamespace(app=SimpleNamespace(rest=rest))
    asyncio.run(cwl.on_bot_started(event, mongo))

    assert set(scheduler.jobs) == {cwl.cwl_base_job_id, "cwl_followup_1"}
    assert [call[1]["id"] for call in scheduler.add_calls] == [
        "cwl_followup_1",
        cwl.cwl_base_job_id,
    ]
    restored_run = scheduler.jobs["cwl_followup_1"].next_run_time
    assert restored_run == run_time
    assert mongo.database.cwl_pending_reminders.documents["cwl_followup_1"]["run_time"] == run_time.isoformat()


def test_overdue_restore_preserves_retry_age_and_failure_count(monkeypatch):
    first_failed_at = pendulum.now(cwl.DEFAULT_TIMEZONE).subtract(hours=3).isoformat()
    created_at = pendulum.now(cwl.DEFAULT_TIMEZONE).subtract(hours=4).isoformat()
    pending = {
        "cwl_followup_1": {
            "_id": "cwl_followup_1",
            "job_id": "cwl_followup_1",
            "reminder_number": 1,
            "run_time": pendulum.now(cwl.DEFAULT_TIMEZONE).subtract(minutes=1).isoformat(),
            "failure_count": 3,
            "first_failed_at": first_failed_at,
            "created_at": created_at,
        },
    }
    mongo, scheduler, _ = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        pending=pending,
    )

    asyncio.run(cwl.restore_pending_reminders())

    restored = mongo.database.cwl_pending_reminders.documents["cwl_followup_1"]
    assert restored["failure_count"] == 3
    assert restored["first_failed_at"] == first_failed_at
    assert restored["created_at"] == created_at
    assert "cwl_followup_1" in scheduler.jobs


def test_startup_discards_terminal_pending_row(monkeypatch):
    pending = {
        "cwl_followup_1": {
            "_id": "cwl_followup_1",
            "job_id": "cwl_followup_1",
            "reminder_number": 1,
            "run_time": pendulum.now(cwl.DEFAULT_TIMEZONE).add(hours=1).isoformat(),
            "status": "abandoned",
        },
    }
    mongo, scheduler, _ = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        pending=pending,
    )

    asyncio.run(cwl.restore_pending_reminders())

    assert scheduler.jobs == {}
    assert mongo.database.cwl_pending_reminders.documents == {}


def test_remove_followup_deletes_memory_and_durable_pending_state(monkeypatch):
    mongo, scheduler, _ = configure(
        monkeypatch,
        schedule={
            "_id": "schedule",
            "followups": [{"number": 1}, {"number": 2}],
        },
        pending={"cwl_followup_1": {"_id": "cwl_followup_1"}},
    )
    scheduler.jobs["cwl_followup_1"] = SimpleNamespace()

    removed = asyncio.run(cwl.remove_followup_configuration(1, mongo))

    assert removed is True
    assert mongo.database.cwl_reminder.documents["schedule"]["followups"] == [{"number": 2}]
    assert "cwl_followup_1" not in scheduler.jobs
    assert "cwl_followup_1" not in mongo.database.cwl_pending_reminders.documents


def test_new_full_delivery_job_clears_stale_retry_channel_filter(monkeypatch):
    pending = {
        "cwl_followup_1": {
            "_id": "cwl_followup_1",
            "job_id": "cwl_followup_1",
            "reminder_number": 1,
            "channel_keys": ["lazy"],
            "failure_count": 2,
        },
    }
    mongo, _, _ = configure(
        monkeypatch,
        schedule={"_id": "schedule"},
        pending=pending,
    )

    asyncio.run(
        cwl._persist_pending_reminder(
            "cwl_followup_1",
            pendulum.now(cwl.DEFAULT_TIMEZONE).add(hours=1),
            1,
        )
    )

    restored = mongo.database.cwl_pending_reminders.documents["cwl_followup_1"]
    assert "channel_keys" not in restored
    assert "failure_count" not in restored


def test_days_through_31_skip_months_where_the_day_does_not_exist():
    now = pendulum.datetime(2026, 4, 1, 0, 0, tz=cwl.DEFAULT_TIMEZONE)

    next_run = cwl.next_monthly_run(31, 18, 30, now)

    assert (next_run.year, next_run.month, next_run.day) == (2026, 5, 31)
    assert (next_run.hour, next_run.minute) == (18, 30)


def test_jobs_use_safe_execution_defaults(monkeypatch):
    _, scheduler, _ = configure(monkeypatch, schedule={"_id": "schedule"})

    asyncio.run(cwl.schedule_cwl_reminder(31, 18, 0))

    options = scheduler.jobs[cwl.cwl_base_job_id].kwargs
    assert options["misfire_grace_time"] == 86400
    assert options["coalesce"] is True
    assert options["max_instances"] == 1


def test_status_reads_the_timestamp_that_delivery_writes():
    assert cwl.get_last_sent({"last_sent_0": "new", "last_sent": "legacy"}) == "new"
    assert cwl.get_last_sent({"last_sent": "legacy"}) == "legacy"


def test_recent_missed_base_is_restored_as_durable_retry(monkeypatch):
    now = pendulum.datetime(2026, 8, 2, 12, 0, tz=cwl.DEFAULT_TIMEZONE)
    mongo, scheduler, _ = configure(monkeypatch, schedule={"_id": "schedule"})

    restored = asyncio.run(cwl.restore_missed_base_reminder({
        "day": 1,
        "hour": 18,
        "minute": 30,
    }, now))

    assert restored is True
    assert cwl.cwl_initial_retry_job_id in scheduler.jobs
    pending = mongo.database.cwl_pending_reminders.documents[cwl.cwl_initial_retry_job_id]
    assert pending["reminder_number"] == 0


def test_sent_or_stale_base_is_not_restored(monkeypatch):
    now = pendulum.datetime(2026, 8, 20, 12, 0, tz=cwl.DEFAULT_TIMEZONE)
    _, scheduler, _ = configure(monkeypatch, schedule={"_id": "schedule"})

    stale = asyncio.run(cwl.restore_missed_base_reminder({
        "day": 1,
        "hour": 18,
        "minute": 30,
    }, now))
    already_sent = asyncio.run(cwl.restore_missed_base_reminder({
        "day": 19,
        "hour": 18,
        "minute": 30,
        "last_sent_0": now.subtract(hours=1).isoformat(),
    }, now))

    assert stale is False
    assert already_sent is False
    assert scheduler.jobs == {}


def test_scheduler_failure_leaves_followup_durable(monkeypatch):
    mongo, _, _ = configure(monkeypatch, schedule={"_id": "schedule"})
    scheduler = FakeScheduler(fail_add=True)
    monkeypatch.setattr(cwl, "scheduler", scheduler)
    base_time = pendulum.now(cwl.DEFAULT_TIMEZONE)

    try:
        asyncio.run(cwl.schedule_followup_reminder(base_time, 1, 30))
    except RuntimeError as exc:
        assert str(exc) == "scheduler unavailable"
    else:
        raise AssertionError("scheduler failure should be reported")

    assert "cwl_followup_1" in mongo.database.cwl_pending_reminders.documents

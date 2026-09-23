import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pendulum
import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands import cwl_dashboard as dashboard
from extensions.tasks import cwl_reminder
from utils import cwl_campaign, cwl_media


@pytest.mark.parametrize("cycle,offset,expected", [
    ("2026-02", 2, "2026-02-26T17:00:00-05:00"),
    ("2028-02", 2, "2028-02-27T17:00:00-05:00"),
    ("2026-04", 2, "2026-04-28T17:00:00-04:00"),
    ("2026-03", 2, "2026-03-29T17:00:00-04:00"),
    ("2026-02", 0, "2026-02-28T17:00:00-05:00"),
    ("2026-02", 27, "2026-02-01T17:00:00-05:00"),
])
def test_month_end_delivery_uses_calendar_month_and_local_time(cycle, offset, expected):
    campaign = cwl_campaign.default_campaign()
    campaign["messages"]["signup"]["schedule"] = {
        "mode": "monthly", "month_end_offset_days": offset, "hour": 17, "minute": 0,
    }
    cwl_campaign.validate_campaign(campaign)
    entry = next(item for item in cwl_campaign.resolve_schedule(campaign, cycle) if item["message_id"] == "signup")
    assert entry["run_at"] == expected


def test_monthly_choice_survives_apply_reload_and_switch_back(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        choice = modal_context()
        await dashboard.choose_monthly(choice, f"{draft['token']}|signup|end", mongo=mongo)
        custom_id = choice.respond_with_modal.await_args.kwargs["custom_id"]
        await dashboard.submit_schedule(modal_context(values={"offset_days": "2", "time": "5:00 PM"}), custom_id.partition(":")[2], mongo=mongo)
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        loaded = await cwl_campaign.load_campaign(mongo, 22, "2026-10")
        rule = loaded["campaign"]["messages"]["signup"]["schedule"]
        assert rule == {"mode": "monthly", "month_end_offset_days": 2, "hour": 17, "minute": 0}
        assert "2 days before month end" in dashboard._time_description(rule)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        await dashboard.submit_schedule(modal_context(values={"day": "20", "time": "17:00"}), f"{draft['token']}|signup|monthly_day", mongo=mongo)
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        loaded = await cwl_campaign.load_campaign(mongo, 22, "2026-10")
        assert loaded["campaign"]["messages"]["signup"]["schedule"] == {"mode": "monthly", "day": 20, "hour": 17, "minute": 0}
    asyncio.run(scenario())


def test_monthly_rule_rejects_both_date_choices():
    campaign = cwl_campaign.default_campaign()
    campaign["messages"]["signup"]["schedule"]["month_end_offset_days"] = 2
    with pytest.raises(ValueError, match="either"):
        cwl_campaign.validate_campaign(campaign)


class MemoryCollection:
    """Small Mongo-compatible store for campaign integration boundaries."""

    def __init__(self, documents=None):
        self.documents = deepcopy(documents or {})

    @staticmethod
    def _path(document, path, missing=None):
        value = document
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return missing
            value = value[part]
        return value

    @classmethod
    def _matches(cls, document, query):
        if document is None:
            return False
        missing = object()
        for key, expected in query.items():
            actual = cls._path(document, key, missing)
            if isinstance(expected, dict) and "$exists" in expected:
                if (actual is not missing) != bool(expected["$exists"]):
                    return False
            elif isinstance(expected, dict) and "$lte" in expected:
                if actual is missing or actual > expected["$lte"]:
                    return False
            elif actual is missing or actual != expected:
                return False
        return True

    @staticmethod
    def _set_path(document, path, value):
        target = document
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = deepcopy(value)

    @staticmethod
    def _unset_path(document, path):
        target = document
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.get(part, {})
        target.pop(parts[-1], None)

    async def find_one(self, query):
        if "_id" in query:
            document = self.documents.get(query["_id"])
            return deepcopy(document) if self._matches(document, query) else None
        for document in self.documents.values():
            if self._matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query=None):
        documents = [
            deepcopy(document) for document in self.documents.values()
            if self._matches(document, query or {})
        ]
        return SimpleNamespace(to_list=AsyncMock(return_value=documents))

    async def update_one(self, query, update, upsert=False):
        document = None
        for candidate in self.documents.values():
            if self._matches(candidate, query):
                document = candidate
                break

        inserted = False
        if document is None:
            if not upsert:
                return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
            document_id = query.get("_id")
            if document_id in self.documents:
                raise DuplicateKeyError("duplicate _id")
            document = {
                key: deepcopy(value) for key, value in query.items()
                if not isinstance(value, dict)
            }
            self.documents[document_id] = document
            inserted = True

        if inserted:
            for key, value in update.get("$setOnInsert", {}).items():
                self._set_path(document, key, value)
        for key, value in update.get("$set", {}).items():
            self._set_path(document, key, value)
        for key in update.get("$unset", {}):
            self._unset_path(document, key)

        for key, spec in update.get("$push", {}).items():
            values = spec.get("$each", []) if isinstance(spec, dict) else [spec]
            destination = document.setdefault(key, [])
            destination.extend(deepcopy(values))
            if isinstance(spec, dict) and "$slice" in spec:
                size = int(spec["$slice"])
                document[key] = destination[size:] if size < 0 else destination[:size]
        for key, value in update.get("$addToSet", {}).items():
            destination = document.setdefault(key, [])
            if value not in destination:
                destination.append(deepcopy(value))
        for key, value in update.get("$pull", {}).items():
            document[key] = [item for item in document.get(key, []) if item != value]

        return SimpleNamespace(
            matched_count=0 if inserted else 1,
            modified_count=1,
            upserted_id=document.get("_id") if inserted else None,
        )

    async def delete_one(self, query):
        document = await self.find_one(query)
        if document is None:
            return SimpleNamespace(deleted_count=0)
        del self.documents[document["_id"]]
        return SimpleNamespace(deleted_count=1)


class MemoryMongo:
    def __init__(self, *, legacy=None):
        self.bot_config = MemoryCollection()
        self.cwl_pending_reminders = MemoryCollection()
        self.cwl_reminder = MemoryCollection(
            {"schedule": {"_id": "schedule", **legacy}} if legacy else {}
        )


class MemoryScheduler:
    def __init__(self):
        self.jobs = {}
        self.added = []
        self.removed = []
        self.running = True

    def add_job(self, function, **kwargs):
        job = SimpleNamespace(function=function, **kwargs)
        self.jobs[kwargs["id"]] = job
        self.added.append(job)
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.removed.append(job_id)
        self.jobs.pop(job_id, None)

    def start(self):
        self.running = True


class StrictCampaignRest:
    """Match Hikari 2.6's supported campaign-send keyword surface."""

    def __init__(self, *, guild_id=22, failing_channels=()):
        self.guild_id = guild_id
        self.failing_channels = set(failing_channels)
        self.sent = []

    async def fetch_channel(self, channel_id):
        return SimpleNamespace(id=channel_id, guild_id=self.guild_id)

    async def create_message(
        self, channel, content=hikari.UNDEFINED, *, components=hikari.UNDEFINED,
        role_mentions=hikari.UNDEFINED, user_mentions=hikari.UNDEFINED,
        mentions_everyone=hikari.UNDEFINED, nonce=hikari.UNDEFINED,
    ):
        if channel in self.failing_channels:
            raise RuntimeError("Discord temporarily unavailable")
        message = SimpleNamespace(id=9000 + len(self.sent))
        self.sent.append({
            "channel": channel, "components": components,
            "role_mentions": role_mentions, "user_mentions": user_mentions,
            "mentions_everyone": mentions_everyone, "nonce": nonce,
        })
        return message


async def applied_campaign(mongo, monkeypatch, *, cycle="2026-10", guild_id=22):
    monkeypatch.setattr(cwl_reminder, "mongo_client", None)
    draft = await cwl_campaign.new_draft(mongo, guild_id, 11, cycle=cycle)
    await cwl_campaign.apply_draft(mongo, draft["token"], 11)
    return await cwl_campaign.load_campaign(mongo, guild_id, cycle)


def install_runtime(monkeypatch, mongo, *, rest=None):
    scheduler = MemoryScheduler()
    rest = rest or StrictCampaignRest()
    monkeypatch.setattr(cwl_reminder, "mongo_client", mongo)
    monkeypatch.setattr(cwl_reminder, "scheduler", scheduler)
    monkeypatch.setattr(
        cwl_reminder, "bot_instance",
        SimpleNamespace(rest=rest, cache=SimpleNamespace(get_guild_channel=lambda _channel: None)),
    )
    return scheduler, rest


def run(coroutine):
    return asyncio.run(coroutine)


def modal_context(*, values=None, selections=(), guild_id=22, user_id=11):
    values = values or {}
    interaction = SimpleNamespace(
        guild_id=guild_id,
        member=SimpleNamespace(permissions=hikari.Permissions.MANAGE_GUILD),
        components=[
            [SimpleNamespace(custom_id=custom_id, value=value)]
            for custom_id, value in values.items()
        ],
        values=selections,
        message=None,
        edit_initial_response=AsyncMock(),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        interaction=interaction,
        defer=AsyncMock(),
        respond_with_modal=AsyncMock(),
    )


def test_ui_edit_apply_reload_and_render_share_one_schema(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        token = draft["token"]

        schedule_picker = modal_context(selections=("monthly",))
        await dashboard.edit_schedule(schedule_picker, f"{token}|signup", mongo=mongo)
        schedule_picker.respond_with_modal.assert_not_awaited()
        assert "Days before month end" in str(schedule_picker.interaction.edit_initial_response.await_args)
        schedule_picker = modal_context()
        await dashboard.choose_monthly(schedule_picker, f"{token}|signup|day", mongo=mongo)
        schedule_custom_id = schedule_picker.respond_with_modal.await_args.kwargs["custom_id"]
        await dashboard.submit_schedule(
            modal_context(values={"day": "21", "time": "18:30"}),
            schedule_custom_id.partition(":")[2],
            mongo=mongo,
        )
        settings_button = modal_context()
        await dashboard.edit_settings(settings_button, token, mongo=mongo)
        settings_custom_id = settings_button.respond_with_modal.await_args.kwargs["custom_id"]
        await dashboard.submit_settings(
            modal_context(values={"deadline": "end-3 19:15", "timezone": "America/New_York"}),
            settings_custom_id.partition(":")[2],
            mongo=mongo,
        )
        text_button = modal_context()
        await dashboard.edit_text(text_button, f"{token}|signup|main", mongo=mongo)
        text_custom_id = text_button.respond_with_modal.await_args.kwargs["custom_id"]
        await dashboard.submit_text(
            modal_context(values={"title": "October signups", "body": "Join before {signup_deadline}."}),
            text_custom_id.partition(":")[2],
            mongo=mongo,
        )

        applied = await cwl_campaign.apply_draft(mongo, token, 11)
        loaded = await cwl_campaign.load_campaign(mongo, 22, "2026-10")
        signup = next(
            item for item in loaded["schedule"]
            if item["message_id"] == "signup" and item["variant"] == "main"
        )
        assert signup["run_at"] == "2026-10-21T18:30:00-04:00"
        assert loaded["deadline"] == "2026-10-28T19:15:00-04:00"
        assert loaded["campaign"]["messages"]["signup"]["variants"]["main"]["title"] == "October signups"
        built = (await cwl_campaign.render_message(loaded, "signup", "main", preview=False))[0].build()[0]
        encoded = str(built)
        assert "October signups" in encoded
        assert "<@&1080521665584308286>" in encoded
        assert "{signup_deadline}" not in encoded
        assert applied["revision"] == 3  # Two timing saves, then message content.
        assert await cwl_campaign.load_draft(mongo, token) is None

    run(scenario())


def test_cycle_actions_keep_revision_applyable(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)

        await cwl_campaign.set_paused(mongo, 22, True, cycle="2026-10", user_id=11)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        campaign = draft["campaign"]
        campaign["messages"]["signup"]["variants"]["main"]["title"] = "Saved after pause"
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})

        await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        loaded = await cwl_campaign.load_campaign(mongo, 22, "2026-10")
        assert loaded["revision"] == 2
        assert loaded["campaign"]["paused"] is True
        assert loaded["campaign"]["messages"]["signup"]["variants"]["main"]["title"] == "Saved after pause"

    run(scenario())


def test_pause_invalidates_an_older_open_draft(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        await cwl_campaign.set_paused(mongo, 22, True, cycle="2026-10", user_id=12)
        try:
            await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        except RuntimeError as exc:
            assert "changed while this draft was open" in str(exc)
        else:
            raise AssertionError("stale draft unexpectedly replaced the live pause state")

    run(scenario())


def test_defaults_roll_into_new_month_without_becoming_cycle_revision(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        defaults = await cwl_campaign.new_draft(
            mongo, 22, 11, cycle="2026-10", scope="defaults"
        )
        defaults_campaign = defaults["campaign"]
        defaults_campaign["messages"]["signup"]["variants"]["main"]["title"] = "Future default"
        await cwl_campaign.patch_draft(
            mongo, defaults["token"], {"campaign": defaults_campaign}
        )
        await cwl_campaign.apply_draft(mongo, defaults["token"], 11)

        november = await cwl_campaign.load_campaign(mongo, 22, "2026-11")
        assert november["defaults_revision"] == 1
        assert november["revision"] == 0
        assert november["campaign"]["messages"]["signup"]["variants"]["main"]["title"] == "Future default"

        cycle = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-11")
        cycle_campaign = cycle["campaign"]
        cycle_campaign["messages"]["signup"]["variants"]["main"]["title"] = "November only"
        await cwl_campaign.patch_draft(mongo, cycle["token"], {"campaign": cycle_campaign})
        await cwl_campaign.apply_draft(mongo, cycle["token"], 11)

        november = await cwl_campaign.load_campaign(mongo, 22, "2026-11")
        december = await cwl_campaign.load_campaign(mongo, 22, "2026-12")
        assert november["revision"] == 1
        assert november["campaign"]["messages"]["signup"]["variants"]["main"]["title"] == "November only"
        assert december["revision"] == 0
        assert december["campaign"]["messages"]["signup"]["variants"]["main"]["title"] == "Future default"

    run(scenario())


def test_saving_defaults_pins_current_cycle_and_changes_future_only(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        now = pendulum.now("America/New_York")
        current_cycle = now.format("YYYY-MM")
        following = now.add(months=1).format("YYYY-MM")
        before = await cwl_campaign.load_campaign(mongo, 22, current_cycle)
        old_title = before["campaign"]["messages"]["signup"]["variants"]["main"]["title"]

        draft = await cwl_campaign.new_draft(
            mongo, 22, 11, cycle=current_cycle, scope="defaults"
        )
        draft["campaign"]["messages"]["signup"]["variants"]["main"]["title"] = "Future title"
        await cwl_campaign.patch_draft(
            mongo, draft["token"], {"campaign": draft["campaign"]}
        )
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)

        current = await cwl_campaign.load_campaign(mongo, 22, current_cycle)
        future = await cwl_campaign.load_campaign(mongo, 22, following)
        assert current["campaign"]["messages"]["signup"]["variants"]["main"]["title"] == old_title
        assert future["campaign"]["messages"]["signup"]["variants"]["main"]["title"] == "Future title"

    run(scenario())


def test_sent_audience_is_immutable_while_unsent_audience_can_change(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        first = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        await cwl_campaign.apply_draft(mongo, first["token"], 11)
        await cwl_campaign.record_delivery(mongo, 22, "2026-10", {
            "occurrence_id": "2026-10|signup|main", "status": "sent",
        })

        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2026-10")
        campaign = draft["campaign"]
        campaign["messages"]["signup"]["schedule"] = {
            "mode": "monthly", "day": 25, "hour": 12, "minute": 0,
        }
        campaign["messages"]["signup"]["variants"]["main"]["title"] = "Must not replace sent"
        campaign["messages"]["signup"]["variants"]["lazy"]["title"] = "Lazy remains editable"
        await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        result = await cwl_campaign.apply_draft(mongo, draft["token"], 11)

        main = result["campaign"]["messages"]["signup"]["variants"]["main"]
        lazy = result["campaign"]["messages"]["signup"]["variants"]["lazy"]
        assert main["title"] != "Must not replace sent"
        assert lazy["title"] == "Lazy remains editable"
        assert result["campaign"]["messages"]["signup"]["schedule"]["day"] == 25
        assert result["protected_sent"] == ["2026-10|signup|main"]

    run(scenario())


def test_campaign_send_matches_pinned_rest_contract_and_is_idempotent(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        scheduler, rest = install_runtime(monkeypatch, mongo)
        generation = cwl_reminder._campaign_generation(loaded)

        assert await cwl_reminder.send_campaign_message(
            22, "2026-10", "signup", ["main"], generation
        ) is True
        assert len(rest.sent) == 1
        assert rest.sent[0]["user_mentions"] is False
        assert rest.sent[0]["mentions_everyone"] is False
        assert rest.sent[0]["role_mentions"] == [1080521665584308286]
        assert isinstance(rest.sent[0]["nonce"], str)

        # A second task/restart sees the durable sent ledger and never posts again.
        assert await cwl_reminder.send_campaign_message(
            22, "2026-10", "signup", ["main"], generation
        ) is False
        assert len(rest.sent) == 1
        assert not scheduler.jobs

    run(scenario())


def test_restart_restores_campaign_job_instead_of_deleting_as_legacy(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        scheduler, _rest = install_runtime(monkeypatch, mongo)
        run_at = pendulum.datetime(2026, 10, 20, 17, 0, tz="America/New_York")
        job_id = cwl_reminder._campaign_job_id(22, "2026-10", "signup", "main")
        await cwl_reminder._persist_campaign_job(
            job_id, run_at, 22, "2026-10", "signup", ["main"],
            cwl_reminder._campaign_generation(loaded),
        )

        scheduler.jobs.clear()
        await cwl_reminder.restore_pending_reminders()
        assert job_id in scheduler.jobs
        assert job_id in mongo.cwl_pending_reminders.documents
        assert scheduler.jobs[job_id].args[3] == ["main"]

    run(scenario())


def test_monthly_reconcile_creates_next_cycle_and_rollover_job(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        monkeypatch.setattr(cwl_reminder, "mongo_client", None)
        draft = await cwl_campaign.new_draft(
            mongo, 22, 11, cycle="2026-09", scope="defaults"
        )
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)
        scheduler, _rest = install_runtime(monkeypatch, mongo)

        await cwl_reminder._reconcile_cwl_startup()
        assert cwl_reminder.CAMPAIGN_ROLLOVER_JOB_ID in scheduler.jobs
        assert any(":2026-10:" in job_id for job_id in scheduler.jobs)
        assert any(
            row.get("kind") == "campaign" and row.get("cycle") == "2026-10"
            for row in mongo.cwl_pending_reminders.documents.values()
        )

    run(scenario())


def test_manual_main_and_lazy_jobs_survive_schedule_reconciliation(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        await applied_campaign(mongo, monkeypatch)
        scheduler, _rest = install_runtime(monkeypatch, mongo)

        await cwl_reminder.queue_manual_campaign_occurrence(
            22, "2026-10", "roster", ["main", "lazy"]
        )
        main_id = cwl_reminder._campaign_job_id(22, "2026-10", "roster", "main")
        lazy_id = cwl_reminder._campaign_job_id(22, "2026-10", "roster", "lazy")
        assert {main_id, lazy_id} <= set(scheduler.jobs)

        await cwl_reminder.sync_campaign_schedule(22, "2026-10")
        assert {main_id, lazy_id} <= set(scheduler.jobs)
        assert {main_id, lazy_id} <= set(mongo.cwl_pending_reminders.documents)

    run(scenario())


def test_retry_for_past_occurrence_survives_schedule_reconciliation(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch, cycle="2026-09")
        scheduler, _rest = install_runtime(monkeypatch, mongo)
        job_id = cwl_reminder._campaign_job_id(22, "2026-09", "signup", "main")
        await cwl_reminder._persist_campaign_job(
            job_id, pendulum.now("America/New_York").add(minutes=5),
            22, "2026-09", "signup", ["main"],
            cwl_reminder._campaign_generation(loaded), failure_count=1,
            job_kind="retry",
        )
        cwl_reminder._add_campaign_job(
            job_id, pendulum.now("America/New_York").add(minutes=5),
            22, "2026-09", "signup", ["main"],
            cwl_reminder._campaign_generation(loaded),
        )

        await cwl_reminder.sync_campaign_schedule(22, "2026-09")
        assert job_id in scheduler.jobs
        assert mongo.cwl_pending_reminders.documents[job_id]["failure_count"] == 1

    run(scenario())


def test_manual_legacy_announcement_does_not_activate_dashboard_scheduler(monkeypatch):
    async def scenario():
        guild_id = cwl_campaign.LEGACY_WU_GUILD_ID
        mongo = MemoryMongo(legacy={
            "enabled": True, "day": 29, "hour": 17, "minute": 0,
            "followups": [],
        })
        scheduler, rest = install_runtime(
            monkeypatch, mongo, rest=StrictCampaignRest(guild_id=guild_id)
        )
        scheduler.add_job(lambda: None, id=cwl_reminder.cwl_base_job_id)
        cycle = pendulum.now("America/New_York").format("YYYY-MM")
        loaded = await cwl_campaign.load_campaign(mongo, guild_id, cycle)

        assert await cwl_reminder.send_campaign_message(
            guild_id, cycle, "signup", ["main"],
            cwl_reminder._campaign_generation(loaded),
        ) is True
        await cwl_reminder._sync_all_campaigns()

        legacy = await mongo.cwl_reminder.find_one({"_id": "schedule"})
        assert legacy["enabled"] is True
        assert legacy.get("campaign_managed") is not True
        assert cwl_reminder.cwl_base_job_id in scheduler.jobs
        cycle_row = await mongo.bot_config.find_one(
            {"_id": cwl_campaign.cycle_id(guild_id, cycle)}
        )
        assert cycle_row.get("activated") is not True
        assert not any(
            job_id.startswith(f"cwl_campaign:{guild_id}:")
            for job_id in scheduler.jobs
        )

    run(scenario())


def test_first_cycle_apply_migrates_legacy_defaults_and_sent_markers(monkeypatch):
    async def scenario():
        guild_id = cwl_campaign.LEGACY_WU_GUILD_ID
        now = pendulum.now("America/New_York")
        cycle = now.format("YYYY-MM")
        following = now.add(months=1).format("YYYY-MM")
        mongo = MemoryMongo(legacy={
            "enabled": True, "day": 29, "hour": 18, "minute": 45,
            "followups": [{"number": 1, "enabled": True, "delay_minutes": 90}],
            "last_sent_0": now.isoformat(),
        })
        scheduler, _rest = install_runtime(
            monkeypatch, mongo, rest=StrictCampaignRest(guild_id=guild_id)
        )
        draft = await cwl_campaign.new_draft(mongo, guild_id, 11, cycle=cycle)
        await cwl_campaign.apply_draft(mongo, draft["token"], 11)

        legacy = await mongo.cwl_reminder.find_one({"_id": "schedule"})
        assert legacy["enabled"] is False
        assert legacy["campaign_managed"] is True
        defaults = await mongo.bot_config.find_one(
            {"_id": cwl_campaign.defaults_id(guild_id)}
        )
        assert defaults["activated"] is True
        assert defaults["campaign"]["messages"]["signup"]["schedule"] == {
            "mode": "monthly", "day": 29, "hour": 18, "minute": 45,
            "missing_day": "skip",
        }

        future = await cwl_campaign.load_campaign(mongo, guild_id, following)
        assert future["campaign"]["messages"]["signup"]["schedule"]["day"] == 29
        assert future["campaign"]["messages"]["reminder:1"]["schedule"]["offset_minutes"] == 90

        current = await cwl_campaign.load_campaign(mongo, guild_id, cycle)
        expected = {
            cwl_campaign.occurrence_id(cycle, "signup", "main"),
            cwl_campaign.occurrence_id(cycle, "signup", "lazy"),
        }
        assert expected <= set(current["sent_occurrences"])
        assert not expected.intersection({
            row.get("occurrence_id")
            for row in mongo.cwl_pending_reminders.documents.values()
        })
        assert not any(
            job_id in scheduler.jobs
            for job_id in (
                cwl_reminder._campaign_job_id(guild_id, cycle, "signup", "main"),
                cwl_reminder._campaign_job_id(guild_id, cycle, "signup", "lazy"),
            )
        )

    run(scenario())


def test_pause_is_durable_activation_discovered_after_restart(monkeypatch):
    async def scenario():
        guild_id = cwl_campaign.LEGACY_WU_GUILD_ID
        now = pendulum.now("America/New_York")
        cycle = now.format("YYYY-MM")
        following = now.add(months=1).format("YYYY-MM")
        mongo = MemoryMongo(legacy={
            "enabled": True, "day": 20, "hour": 17, "minute": 0,
            "followups": [],
        })
        scheduler, _rest = install_runtime(
            monkeypatch, mongo, rest=StrictCampaignRest(guild_id=guild_id)
        )

        await cwl_campaign.set_paused(
            mongo, guild_id, True, cycle=cycle, user_id=11
        )
        row = await mongo.bot_config.find_one(
            {"_id": cwl_campaign.cycle_id(guild_id, cycle)}
        )
        assert row["activated"] is True
        assert (await mongo.cwl_reminder.find_one({"_id": "schedule"}))["enabled"] is False

        scheduler.jobs.clear()  # process restart
        await cwl_reminder._sync_all_campaigns()
        assert any(
            row.get("cycle") == following
            for row in mongo.cwl_pending_reminders.documents.values()
        )

    run(scenario())


def test_confirmed_send_receipt_recovers_without_second_discord_post(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        scheduler, rest = install_runtime(monkeypatch, mongo)
        job_id = cwl_reminder._campaign_job_id(22, "2026-10", "signup", "main")
        run_at = pendulum.now("America/New_York").add(seconds=2)
        await cwl_reminder._persist_campaign_job(
            job_id, run_at, 22, "2026-10", "signup", ["main"],
            cwl_reminder._campaign_generation(loaded),
        )
        real_record = cwl_campaign.record_delivery
        attempts = 0

        async def fail_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("Mongo write interrupted")
            return await real_record(*args, **kwargs)

        monkeypatch.setattr(cwl_campaign, "record_delivery", fail_once)
        assert await cwl_reminder.send_campaign_message(
            22, "2026-10", "signup", ["main"],
            cwl_reminder._campaign_generation(loaded),
        ) is True
        assert len(rest.sent) == 1
        assert mongo.cwl_pending_reminders.documents[job_id]["status"] == "ledger_pending"

        scheduler.jobs.clear()
        await cwl_reminder.restore_pending_reminders()
        assert len(rest.sent) == 1
        assert job_id not in mongo.cwl_pending_reminders.documents
        recovered = await cwl_campaign.load_campaign(mongo, 22, "2026-10")
        assert any(
            item.get("occurrence_id") == "2026-10|signup|main"
            and item.get("status") == "sent"
            for item in recovered["deliveries"]
        )

    run(scenario())


def test_partial_failure_retries_only_failed_audience(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        lazy_channel = loaded["campaign"]["messages"]["signup"]["variants"]["lazy"]["destination_channel_id"]
        scheduler, rest = install_runtime(
            monkeypatch, mongo, rest=StrictCampaignRest(failing_channels={lazy_channel})
        )

        assert await cwl_reminder.send_campaign_message(
            22, "2026-10", "signup", ["main", "lazy"],
            cwl_reminder._campaign_generation(loaded),
        ) is False
        assert len(rest.sent) == 1
        main_id = cwl_reminder._campaign_job_id(22, "2026-10", "signup", "main")
        lazy_id = cwl_reminder._campaign_job_id(22, "2026-10", "signup", "lazy")
        assert main_id not in mongo.cwl_pending_reminders.documents
        assert mongo.cwl_pending_reminders.documents[lazy_id]["variants"] == ["lazy"]
        assert scheduler.jobs[lazy_id].args[3] == ["lazy"]

    run(scenario())


def test_pinned_hikari_dispatches_raw_upload_and_typed_modal_together():
    async def scenario():
        bot = hikari.GatewayBot("MTIz.NA.x")
        typed = []
        cwl_media._pending.clear()
        bot.event_manager.subscribe(hikari.ShardPayloadEvent, cwl_media.capture_upload_payload)

        async def capture_typed(event):
            typed.append(event.interaction)

        bot.event_manager.subscribe(hikari.ModalInteractionCreateEvent, capture_typed)
        payload = {
            "id": "55", "application_id": "123", "type": 5,
            "guild_id": "22", "app_permissions": "32", "locale": "en-US",
            "channel": {"id": "44", "type": 0, "name": "admin", "permissions": "32"},
            "member": {
                "user": {"id": "11", "username": "admin", "discriminator": "0", "avatar": None,
                         "global_name": "Admin", "public_flags": 0},
                "roles": [], "joined_at": "2026-01-01T00:00:00+00:00",
                "deaf": False, "mute": False, "flags": 0, "permissions": "32",
            },
            "token": "not-retained", "version": 1,
            "data": {
                "custom_id": "cwl_image_submit:draft|signup|main",
                "components": [{"type": 18, "component": {
                    "type": 19, "custom_id": "cwl_image", "values": ["66"],
                }}],
                "resolved": {"attachments": {"66": {
                    "id": "66", "size": 100, "filename": "image.png",
                    "url": "https://cdn.discordapp.com/ephemeral-attachments/22/66/image.png",
                }}},
            },
            "authorizing_integration_owners": {"0": "22"},
            "context": 0, "attachment_size_limit": 10 * 1024 * 1024,
        }
        bot.event_manager.consume_raw_event("INTERACTION_CREATE", SimpleNamespace(), payload)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert len(typed) == 1
        assert typed[0].components == []  # Hikari 2.6 drops Label/File Upload.
        assert cwl_media._pending[55][1]["attachment"]["id"] == "66"
        assert "not-retained" not in repr(cwl_media._pending)
        cwl_media._pending.clear()

    run(scenario())

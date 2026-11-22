"""WU signup gate: isolated SQLite snapshots, in-memory Mongo and fake Discord."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pendulum
import pytest

from cwl_web.store import Store
from extensions.tasks import cwl_reminder as worker
from utils import cwl_campaign as campaign
from utils.cwl_dashboard_state import (
    DashboardDurabilityError, encode, read_member_signup_state, utcnow,
)
from test_cwl_dashboard_integration import MemoryMongo, StrictCampaignRest, install_runtime

GUILD = campaign.LEGACY_WU_GUILD_ID
CYCLE = "2026-12"


class Snapshot:
    def __init__(self, document):
        self.document = document
        self.reads = 0
        self.options = None

    def with_options(self, **options):
        self.options = options
        return self

    async def find_one(self, query):
        assert query == {"_id": "warriors-united-dashboard"}
        self.reads += 1
        return deepcopy(self.document)


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    fixed = pendulum.datetime(2026, 12, 2, 12, tz="UTC")
    monkeypatch.setattr(pendulum, "now", lambda tz=None: fixed.in_timezone(tz or "UTC"))
    store = Store(tmp_path / "fixture.sqlite")
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label,signup_open) VALUES(1,'2026-12',0)")
        db.execute("INSERT INTO seasons(id,label,signup_open) VALUES(2,'2026-11',1)")
        db.execute("UPDATE member_season SET season_id=1,revision=4 WHERE id=1")
        head = {**encode(db), "revision": 1, "owner": "fixture-writer", "lease_until": utcnow() + timedelta(minutes=5)}
    mongo = MemoryMongo()
    mongo.cwl_dashboard_state = Snapshot(head)
    template = campaign.default_campaign()
    template["reminder_sequence"] = {"enabled": False}
    template["messages"]["signup"]["schedule"] = {"mode": "monthly", "day": 1, "hour": 1, "minute": 0}
    template["messages"]["signup"]["variants"]["main"]["destination_channel_id"] = 300
    template["messages"]["signup"]["variants"]["lazy"]["enabled"] = False
    mongo.bot_config.documents[campaign.defaults_id(GUILD)] = {
        "_id": campaign.defaults_id(GUILD), "kind": "cwl_campaign_defaults",
        "guild_id": GUILD, "activated": True, "revision": 1, "campaign": template,
    }
    monkeypatch.setattr(worker, "_signup_wait_cursor", None)
    scheduler, rest = install_runtime(monkeypatch, mongo, rest=StrictCampaignRest(guild_id=GUILD))
    return SimpleNamespace(mongo=mongo, store=store, rest=rest, scheduler=scheduler, monkeypatch=monkeypatch)


def update_state(runtime, sql, args=()):
    with runtime.store.tx() as db:
        db.execute(sql, args)
        runtime.mongo.cwl_dashboard_state.document.update(encode(db))
        runtime.mongo.cwl_dashboard_state.document["revision"] += 1


async def deliver(runtime, *, manual=False, message="signup", staff_request_id=None):
    loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
    return await worker._deliver_campaign_message(GUILD, CYCLE, message, ["main"], worker._campaign_generation(loaded), manual=manual, staff_request_id=staff_request_id)


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("status,opened", [("draft", 0), ("archived", 1)])
def test_closed_or_archived_held_once_no_post_no_signup_write(runtime, status, opened, manual):
    update_state(runtime, "UPDATE seasons SET status=?,signup_open=? WHERE id=1", (status, opened))
    async def run():
        before = deepcopy(runtime.mongo.cwl_dashboard_state.document)
        assert not await deliver(runtime, manual=manual)
        assert not await deliver(runtime, manual=manual)
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert len(loaded["signup_holds"]) == 1
        held = [row for row in loaded["deliveries"] if row["status"] == "held"]
        assert len(held) == 1 and held[0]["staff_alert"] == "dashboard only"
        assert not loaded["sent_occurrences"] and not loaded["uncertain_occurrences"]
        assert not runtime.rest.sent
        assert runtime.mongo.cwl_dashboard_state.document == before
        assert not runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)].get("delivery_claims")
    asyncio.run(run())


def test_held_survives_elapsed_schedule_rebuild_and_open_sends_once(runtime):
    async def run():
        assert not await deliver(runtime)
        # A fresh process has no local activity/claim; durable hold is authoritative.
        runtime.monkeypatch.setattr(worker, "_campaign_active_deliveries", {}) if hasattr(worker, "_campaign_active_deliveries") else None
        await worker.sync_campaign_schedule(GUILD, CYCLE)
        update_state(runtime, "UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        await worker._resume_held_signups()
        assert len(runtime.rest.sent) == 1
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert not loaded["signup_holds"] and len(loaded["sent_occurrences"]) == 1
        assert not loaded["uncertain_occurrences"]
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["lost_response", "cancel", "invalid_response"])
def test_prepost_reservation_never_retries_uncertainty(runtime, failure):
    update_state(runtime, "UPDATE seasons SET signup_open=1 WHERE id=1")
    calls = []
    async def accepted(**kwargs):
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert campaign.occurrence_id(CYCLE, "signup", "main") in loaded["uncertain_occurrences"]
        calls.append(kwargs)
        if failure == "cancel": raise asyncio.CancelledError()
        if failure == "lost_response": raise OSError("response lost after acceptance")
        return SimpleNamespace(id=None)
    runtime.monkeypatch.setattr(runtime.rest, "create_message", accepted)
    async def run():
        try: await deliver(runtime)
        except asyncio.CancelledError: pass
        assert not await deliver(runtime)
        await worker._resume_held_signups()
        assert len(calls) == 1
        assert (await campaign.load_campaign(runtime.mongo, GUILD, CYCLE))["uncertain_occurrences"]
    asyncio.run(run())


@pytest.mark.parametrize("change", ["member", "date", "disabled", "skip"])
def test_obsolete_hold_cannot_replay(runtime, change):
    async def run():
        await deliver(runtime)
        update_state(runtime, "UPDATE seasons SET signup_open=1 WHERE id=1")
        if change == "member": update_state(runtime, "UPDATE member_season SET season_id=2,revision=5")
        elif change == "skip":
            await campaign.skip_occurrence(runtime.mongo, GUILD, campaign.occurrence_id(CYCLE, "signup", "main"), CYCLE)
        else:
            item = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]
            item["revision"] += 1
            message = item["campaign"]["messages"]["signup"]
            if change == "date": message["schedule"] = {"mode": "monthly", "day": 3, "hour": 1, "minute": 0}
            if change == "copy": message["variants"]["main"]["body"] = "Changed copy"
            if change == "disabled": message["enabled"] = False
        await worker._resume_held_signups()
        assert not runtime.rest.sent
    asyncio.run(run())


def test_close_between_preflight_and_post_is_held(runtime):
    update_state(runtime, "UPDATE seasons SET signup_open=1 WHERE id=1")
    original = campaign.render_message
    async def render(*args, **kwargs):
        result = await original(*args, **kwargs)
        update_state(runtime, "UPDATE seasons SET signup_open=0 WHERE id=1")
        return result
    runtime.monkeypatch.setattr(campaign, "render_message", render)
    asyncio.run(deliver(runtime))
    assert not runtime.rest.sent


@pytest.mark.parametrize("broken", ["missing", "checksum", "expired", "wrong_cycle", "bad_bool", "no_member"])
def test_unknown_state_failclosed_distinct_from_closed(runtime, broken):
    if broken == "missing": runtime.mongo.cwl_dashboard_state.document = None
    if broken == "checksum": runtime.mongo.cwl_dashboard_state.document["sha256"] = "0" * 64
    if broken == "expired": runtime.mongo.cwl_dashboard_state.document["lease_until"] = utcnow() - timedelta(seconds=1)
    if broken == "wrong_cycle": update_state(runtime, "UPDATE seasons SET label='2027-01' WHERE id=1")
    if broken == "bad_bool": update_state(runtime, "UPDATE seasons SET signup_open=2 WHERE id=1")
    if broken == "no_member": update_state(runtime, "UPDATE member_season SET season_id=NULL")
    asyncio.run(deliver(runtime))
    assert not runtime.rest.sent
    row = runtime.mongo.bot_config.documents.get(campaign.cycle_id(GUILD, CYCLE), {})
    if broken != "wrong_cycle":
        assert row.get("signup_state_unavailable") is True
        assert all(hold["status"] == "waiting_state" for hold in row["signup_holds"].values())
    else: assert all(hold["status"] == "waiting_member" for hold in row["signup_holds"].values())


def test_majority_snapshot_reader_never_acquires_or_writes(runtime):
    state = asyncio.run(read_member_signup_state(runtime.mongo))
    assert state["season_id"] == 1 and state["cycle"] == CYCLE and state["signup_open"] is False
    assert runtime.mongo.cwl_dashboard_state.options["read_concern"].document == {"level": "majority"}
    assert runtime.mongo.cwl_dashboard_state.options["read_preference"].name == "Primary"


def test_other_guild_and_nonsignup_never_read_wu_season(runtime):
    async def run():
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        runtime.mongo.bot_config.documents[campaign.defaults_id(22)] = {
            **deepcopy(runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]), "_id": campaign.defaults_id(22), "guild_id": 22,
        }
        runtime.rest.guild_id = 22
        assert await worker._deliver_campaign_message(22, CYCLE, "signup", ["main"])
        assert runtime.mongo.cwl_dashboard_state.reads == 0
        runtime.rest.guild_id = GUILD
        assert await deliver(runtime, message="reminder:1")
        assert runtime.mongo.cwl_dashboard_state.reads == 0
    asyncio.run(run())


@pytest.mark.parametrize("recover_open", [False, True])
def test_unavailable_state_durably_resumes_after_restart(runtime, recover_open):
    saved = deepcopy(runtime.mongo.cwl_dashboard_state.document)
    runtime.mongo.cwl_dashboard_state.document = None
    async def run():
        await deliver(runtime)
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        assert next(iter(loaded["signup_holds"].values()))["status"] == "waiting_state"
        runtime.mongo.cwl_dashboard_state.document = saved
        if recover_open: update_state(runtime, "UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        if recover_open:
            assert len(runtime.rest.sent) == 1 and not loaded["signup_holds"]
        else:
            assert not runtime.rest.sent
            assert next(iter(loaded["signup_holds"].values()))["status"] == "held"
    asyncio.run(run())


def test_new_generation_normal_send_can_retire_obsolete_nonpost_hold(runtime):
    async def run():
        await deliver(runtime)
        defaults = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]
        defaults["revision"] += 1
        defaults["campaign"]["messages"]["signup"]["variants"]["main"]["body"] = "New approved fixture copy"
        update_state(runtime, "UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        assert len(runtime.rest.sent) == 1
        assert "New approved fixture copy" in str(runtime.rest.sent[0]["components"][0].build()[0])
        assert not await deliver(runtime)
    asyncio.run(run())


@pytest.mark.parametrize("unavailable", [False, True])
def test_catchup_is_gated_and_recoverable(runtime, unavailable):
    async def run():
        due = pendulum.now("America/New_York").subtract(minutes=5)
        template = runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]
        template["messages"]["signup"]["schedule"] = {"mode":"monthly", "day":due.day,"hour":due.hour,"minute":due.minute}
        loaded = await campaign.load_campaign(runtime.mongo, GUILD, CYCLE)
        generation = worker._campaign_generation(loaded)
        job_id = worker._campaign_job_id(GUILD, CYCLE, "signup", "main")
        await worker._persist_campaign_job(job_id, due, GUILD, CYCLE, "signup", ["main"], generation)
        row = await runtime.mongo.cwl_pending_reminders.find_one({"_id":job_id})
        assert await campaign.prepare_catchup_job(runtime.mongo, row, due, pendulum.now("America/New_York"))
        saved = deepcopy(runtime.mongo.cwl_dashboard_state.document)
        if unavailable: runtime.mongo.cwl_dashboard_state.document = None
        assert not await worker._deliver_catchup_message(GUILD,CYCLE,"signup",["main"],generation,due.isoformat())
        assert not runtime.rest.sent
        runtime.mongo.cwl_dashboard_state.document = saved
        update_state(runtime,"UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        await worker._resume_held_signups()
        assert len(runtime.rest.sent) == 1
    asyncio.run(run())


def test_current_member_not_selected_season_drives_status_api(runtime):
    from cwl_web import manage_reminders
    runtime.monkeypatch.setattr(manage_reminders,"_worker_ready",AsyncMock(return_value=True))
    request = SimpleNamespace(app={"store":runtime.store},match_info={"season_id":"2"})
    async def run():
        await deliver(runtime)
        loaded = await campaign.load_campaign(runtime.mongo,GUILD,CYCLE)
        response = await manage_reminders._response(request,runtime.mongo,loaded)
        assert response["signup_open"] is False
        assert response["signup_gate"]["status"] == "held" and response["signup_gate"]["season_id"] == 1
        assert any(row["status"]=="held" for row in response["schedule"])
        assert any(row.get("staff_alert")=="dashboard only" for row in response["history"])
    asyncio.run(run())


def test_hikari_snowflake_confirmation_records_sent(runtime):
    import hikari
    update_state(runtime,"UPDATE seasons SET signup_open=1 WHERE id=1")
    async def confirmed(**kwargs):
        runtime.rest.sent.append(kwargs)
        return SimpleNamespace(id=hikari.Snowflake(987654321))
    runtime.monkeypatch.setattr(runtime.rest,"create_message",confirmed)
    async def run():
        assert await deliver(runtime)
        loaded=await campaign.load_campaign(runtime.mongo,GUILD,CYCLE)
        assert len(loaded["sent_occurrences"])==1 and not loaded["uncertain_occurrences"]
        assert not await deliver(runtime)
    asyncio.run(run())


def test_mismatched_member_cycle_waits_until_matching_month_is_shown(runtime):
    update_state(runtime,"UPDATE member_season SET season_id=2,revision=5")
    async def run():
        await deliver(runtime)
        loaded=await campaign.load_campaign(runtime.mongo,GUILD,CYCLE)
        assert next(iter(loaded["signup_holds"].values()))["status"]=="waiting_member"
        assert not runtime.rest.sent
        update_state(runtime,"UPDATE member_season SET season_id=1,revision=6")
        update_state(runtime,"UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        await worker._resume_held_signups()
        assert len(runtime.rest.sent)==1
    asyncio.run(run())


def test_hold_scan_is_wu_only_paged_and_one_snapshot_per_closed_batch(runtime):
    async def run():
        for number in range(45):
            cycle=f"{2020+number//12:04d}-{number%12+1:02d}"
            oid=campaign.occurrence_id(cycle,"signup","main")
            key=campaign.signup_hold_key(oid)
            runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD,cycle)]={
                "_id":campaign.cycle_id(GUILD,cycle),"kind":"cwl_campaign_cycle","guild_id":GUILD,"cycle":cycle,"revision":0,
                "signup_holds":{key:{"occurrence_id":oid,"generation":"1:0","status":"held","cycle":cycle,"season_id":1,"run_at":"2000-01-01T00:00:00Z"}},
            }
        page,cursor=await campaign.signup_wait_page(runtime.mongo)
        assert len(page)==20 and cursor
        second,_=await campaign.signup_wait_page(runtime.mongo,cursor)
        assert len(second)==20 and {r['_id'] for r in page}.isdisjoint({r['_id'] for r in second})
        before=runtime.mongo.cwl_dashboard_state.reads
        await worker._resume_held_signups()
        assert runtime.mongo.cwl_dashboard_state.reads-before==1
    asyncio.run(run())


def test_defaults_edit_interleaving_old_hold_cas_does_not_strand_current_due_copy(runtime):
    async def run():
        original = runtime.mongo.bot_config.update_one
        raced = False
        async def update(query, patch, **kwargs):
            nonlocal raced
            if not raced and any(path.startswith("signup_holds.") for path in patch.get("$set", {})):
                raced=True
                defaults=runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]
                defaults["revision"]+=1
                defaults["campaign"]["messages"]["signup"]["variants"]["main"]["body"]="Current copy after race"
            return await original(query,patch,**kwargs)
        runtime.monkeypatch.setattr(runtime.mongo.bot_config,"update_one",update)
        await deliver(runtime)
        assert raced and not runtime.rest.sent
        update_state(runtime,"UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        await worker._resume_held_signups()
        assert len(runtime.rest.sent)==1
        assert "Current copy after race" in str(runtime.rest.sent[0]["components"][0].build()[0])
    asyncio.run(run())


def test_retirement_cas_does_not_erase_replaced_hold_owner(runtime):
    async def run():
        await deliver(runtime)
        loaded=await campaign.load_campaign(runtime.mongo,GUILD,CYCLE)
        old=next(iter(loaded["signup_holds"].values()))
        key=campaign.signup_hold_key(old["occurrence_id"])
        newer={**old,"generation":"replacement-owner"}
        runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD,CYCLE)]["signup_holds"][key]=newer
        assert not await campaign.retire_signup_wait(runtime.mongo,GUILD,CYCLE,old,loaded["revision"])
        assert runtime.mongo.bot_config.documents[campaign.cycle_id(GUILD,CYCLE)]["signup_holds"][key]==newer
    asyncio.run(run())


def test_reconcile_cursor_visits_beyond_first_twenty_retained_cycles(runtime):
    async def run():
        expected=set()
        for number in range(45):
            cycle=f"{2020+number//12:04d}-{number%12+1:02d}"
            oid=campaign.occurrence_id(cycle,"signup","main")
            identity=campaign.cycle_id(GUILD,cycle);expected.add(identity)
            runtime.mongo.bot_config.documents[identity]={"_id":identity,"kind":"cwl_campaign_cycle","guild_id":GUILD,"cycle":cycle,"revision":0,
                "signup_holds":{campaign.signup_hold_key(oid):{"occurrence_id":oid,"generation":"1:0","status":"held","cycle":cycle,"season_id":1,"run_at":"2000-01-01T00:00:00Z"}}}
        visited=set();original=campaign.signup_wait_page
        async def page(*args,**kwargs):
            rows,cursor=await original(*args,**kwargs);visited.update(row['_id'] for row in rows);return rows,cursor
        runtime.monkeypatch.setattr(campaign,"signup_wait_page",page)
        before=runtime.mongo.cwl_dashboard_state.reads
        for _ in range(3):await worker._resume_held_signups()
        assert visited==expected
        assert runtime.mongo.cwl_dashboard_state.reads-before==3
        assert not runtime.rest.sent
    asyncio.run(run())


def test_member_month_label_fallback_matches_public_metadata_precedence():
    import sqlite3
    from utils.cwl_dashboard_state import member_signup_state
    # Nullable Results cycle models an unavailable optional metadata projection;
    # it must not force staff to configure Results before opening signup.
    db=sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE member_season(id,season_id,revision); INSERT INTO member_season VALUES(1,1,2);"
                     "CREATE TABLE seasons(id,label,signup_open,status,history_only); INSERT INTO seasons VALUES(1,'December 2026',1,'draft',0);"
                     "CREATE TABLE participation_sync_settings(season_id,cycle);"
                     "CREATE TABLE manage_campaign_bindings(season_id,cycle); INSERT INTO manage_campaign_bindings VALUES(1,'2026-11');")
    try:
        assert member_signup_state(db)["cycle"]=="2026-11"  # Binding if no Results row.
        db.execute("INSERT INTO participation_sync_settings VALUES(1,NULL)")
        assert member_signup_state(db)["cycle"]=="2026-12"  # NULL setting overrides binding, then label.
        db.execute("UPDATE participation_sync_settings SET cycle='2027-01'")
        assert member_signup_state(db)["cycle"]=="2027-01"
        db.execute("UPDATE participation_sync_settings SET cycle='not a cycle'")
        with pytest.raises(DashboardDurabilityError):member_signup_state(db)
    finally:db.close()


def test_held_release_preserves_roster_signup_assigned_and_locks_counts(runtime):
    with runtime.store.tx() as db:
        for pool,tag in [('main','#MAIN'),('lazy','#LAZY')]:
            db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(1,?,'fixture',?,0,?,18)",(tag,pool,tag))
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES(1,?,'#CLAN',1)",(tag,))
    def counts():
        with runtime.store.tx() as db:
            return [tuple(row) for row in db.execute("SELECT s.pool,COUNT(*),COUNT(r.assigned_clan_tag),SUM(COALESCE(r.kept,0)) FROM signups s LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag WHERE s.season_id=1 GROUP BY s.pool ORDER BY s.pool")]
    before=counts()
    async def run():
        await deliver(runtime)
        update_state(runtime,"UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        assert len(runtime.rest.sent)==1
    asyncio.run(run())
    assert before==counts()==[('lazy',1,1,1),('main',1,1,1)]


def test_explicit_manual_signup_without_scheduled_date_releases_once_after_open(runtime):
    # Manual opening cannot be the missing dependency of a legacy timed chain.
    for message in runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]["messages"].values():
        message["schedule"] = {"mode": "manual"}
    async def run():
        identity=await worker.queue_manual_campaign_occurrence(GUILD,CYCLE,"signup",["main"])
        job=await runtime.mongo.cwl_pending_reminders.find_one({"_id":identity})
        assert not await deliver(runtime,staff_request_id=job["staff_request_id"])
        loaded=await campaign.load_campaign(runtime.mongo,GUILD,CYCLE)
        hold=next(iter(loaded["signup_holds"].values()))
        assert hold["staff_job"]=={"job_id":identity,"staff_request_id":job["staff_request_id"]} and hold["run_at"] is None
        update_state(runtime,"UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        await worker._resume_held_signups()
        assert len(runtime.rest.sent)==1
    asyncio.run(run())


@pytest.mark.parametrize("cancel", [True,False])
def test_held_manual_cancel_or_replaced_request_never_gains_authority(runtime,cancel):
    # Manual opening cannot be the missing dependency of a legacy timed chain.
    for message in runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]["messages"].values():
        message["schedule"] = {"mode": "manual"}
    async def run():
        identity=await worker.queue_manual_campaign_occurrence(GUILD,CYCLE,"signup",["main"])
        job=await runtime.mongo.cwl_pending_reminders.find_one({"_id":identity})
        await deliver(runtime,staff_request_id=job["staff_request_id"])
        if cancel: await runtime.mongo.cwl_pending_reminders.delete_one({"_id":identity})
        else: runtime.mongo.cwl_pending_reminders.documents[identity]["staff_request_id"]="f"*32
        update_state(runtime,"UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        assert not runtime.rest.sent
    asyncio.run(run())


def test_hold_bound_to_member_id_does_not_release_into_same_cycle_alias(runtime):
    async def run():
        await deliver(runtime)
        update_state(runtime,"INSERT INTO seasons(id,label,signup_open) VALUES(3,'December 2026',1)")
        update_state(runtime,"UPDATE member_season SET season_id=3,revision=9")
        await worker._resume_held_signups()
        assert not runtime.rest.sent
        loaded=await campaign.load_campaign(runtime.mongo,GUILD,CYCLE)
        hold=next(iter(loaded['signup_holds'].values()))
        assert hold['season_id']==1 and hold['status']=='waiting_member'
    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_held_original_staff_signup_survives_eight_day_restart_only_if_not_cancelled(runtime, cancel):
    for message in runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]["messages"].values():
        message["schedule"] = {"mode": "manual"}
    async def run():
        identity = await worker.queue_manual_campaign_occurrence(GUILD, CYCLE, "signup", ["main"])
        original = await runtime.mongo.cwl_pending_reminders.find_one({"_id": identity})
        await deliver(runtime, staff_request_id=original["staff_request_id"])
        assert await runtime.mongo.cwl_pending_reminders.find_one({"_id": identity}) == original
        if cancel:
            await runtime.mongo.cwl_pending_reminders.delete_one({"_id": identity})
        later = pendulum.now("UTC").add(days=8)
        runtime.monkeypatch.setattr(pendulum, "now", lambda tz=None: later.in_timezone(tz or "UTC"))
        await worker.restore_pending_reminders()
        retained = await runtime.mongo.cwl_pending_reminders.find_one({"_id": identity})
        assert retained == (None if cancel else original)
        assert not runtime.rest.sent
        update_state(runtime, "UPDATE seasons SET signup_open=1 WHERE id=1")
        await worker._resume_held_signups()
        await worker._resume_held_signups()
        assert len(runtime.rest.sent) == (0 if cancel else 1)
    asyncio.run(run())


def test_non_signup_manual_job_keeps_existing_seven_day_expiry(runtime):
    for message in runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)]["campaign"]["messages"].values():
        message["schedule"] = {"mode": "manual"}
        message["variants"]["main"]["destination_channel_id"] = 300
    async def run():
        identity = await worker.queue_manual_campaign_occurrence(GUILD, CYCLE, "reminder:1", ["main"])
        assert await runtime.mongo.cwl_pending_reminders.find_one({"_id": identity})
        later = pendulum.now("UTC").add(days=8)
        runtime.monkeypatch.setattr(pendulum, "now", lambda tz=None: later.in_timezone(tz or "UTC"))
        await worker.restore_pending_reminders()
        assert not await runtime.mongo.cwl_pending_reminders.find_one({"_id": identity})
        assert not runtime.rest.sent
    asyncio.run(run())

import asyncio
from copy import deepcopy
from datetime import datetime, timezone

from extensions.commands import ticket_runtime
from tools import rename_ticket_threads as tool


class Response:
    status = 200
    content_type = "application/json"

    def __init__(self, body): self.body = body
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): return None
    async def json(self): return deepcopy(self.body)


class DiscordSession:
    def __init__(self, *, fail_name_once=False):
        self.channel = {"id": "101", "name": "main-7-applicant",
                        "thread_metadata": {"archived": True, "locked": True}}
        self.fail_name_once = fail_name_once
        self.calls = []

    def request(self, method, _url, *, headers, json=None):
        self.calls.append((method, deepcopy(json), dict(headers)))
        if method == "PATCH" and json and "name" in json and self.fail_name_once:
            self.fail_name_once = False
            return ErrorResponse()
        if method == "PATCH":
            if "name" in json: self.channel["name"] = json["name"]
            self.channel["thread_metadata"].update(
                {key: value for key, value in json.items() if key in {"archived", "locked"}}
            )
        return Response(self.channel)


class ErrorResponse(Response):
    status = 500

    def __init__(self): super().__init__({"message": "injected failure"})


def test_fault_after_successful_unarchive_resumes_and_restores_original_flags():
    session = DiscordSession(fail_name_once=True)
    writes = []
    async def save(value): writes.append(deepcopy(value))

    async def scenario():
        try:
            await tool.rename_one(session, "token", 101, "✅ main-7-applicant", None, save)
        except RuntimeError:
            pass
        assert session.channel["thread_metadata"] == {"archived": False, "locked": True}
        assert writes[-1]["state"] == "unarchived"
        await tool.rename_one(session, "token", 101, "✅ main-7-applicant", writes[-1], save)

    asyncio.run(scenario())
    assert session.channel["name"] == "✅ main-7-applicant"
    assert session.channel["thread_metadata"] == {"archived": True, "locked": True}
    assert writes[-1]["state"] == "complete"


def test_audit_reason_is_a_header_and_never_enters_patch_json():
    session = DiscordSession()
    writes = []
    asyncio.run(tool.rename_one(
        session, "token", 101, "❌ main-7-applicant", None,
        lambda value: _append(writes, value),
    ))
    patches = [(body, headers) for method, body, headers in session.calls if method == "PATCH"]
    assert patches
    assert all("reason" not in body for body, _headers in patches)
    assert all("X-Audit-Log-Reason" in headers for _body, headers in patches)


async def _append(items, value):
    items.append(deepcopy(value))


def test_completed_import_filter_excludes_live_and_incomplete_rows():
    base = {"_id": "ticket_1", "runtime": ticket_runtime.THREAD_RUNTIME,
            "venue": "thread", "status": "approved", "source": {"channel_id": 9}}
    assert tool.is_completed_import(base, {"ticket_1"})
    assert not tool.is_completed_import({**base, "status": "open"}, {"ticket_1"})
    assert not tool.is_completed_import(base, set())
    assert not tool.is_completed_import({**base, "source": {}}, {"ticket_1"})


def test_changed_target_starts_a_new_plan_from_current_state():
    session = DiscordSession()
    session.channel["thread_metadata"] = {"archived": False, "locked": False}
    writes = []
    old = {"state": "complete", "target": "✅ main-7-applicant",
           "original_archived": True, "original_locked": True}
    asyncio.run(tool.rename_one(
        session, "token", 101, "❌ main-7-applicant", old,
        lambda value: _append(writes, value),
    ))
    assert writes[0]["state"] == "planned"
    assert writes[0]["original_archived"] is False
    assert session.channel["name"] == "❌ main-7-applicant"
    assert session.channel["thread_metadata"] == {"archived": False, "locked": False}


def test_overturn_during_incomplete_plan_restores_old_archive_state_first():
    session = DiscordSession()
    session.channel["thread_metadata"] = {"archived": False, "locked": True}
    writes = []
    interrupted = {"state": "unarchived", "target": "✅ main-7-applicant",
                   "original_archived": True, "original_locked": True}
    asyncio.run(tool.rename_one(
        session, "token", 101, "❌ main-7-applicant", interrupted,
        lambda value: _append(writes, value),
    ))
    assert session.channel["name"] == "❌ main-7-applicant"
    assert session.channel["thread_metadata"] == {"archived": True, "locked": True}
    assert writes[0]["original_archived"] is True


def test_maintenance_lease_refuses_a_concurrent_owner():
    class BusyRuns:
        async def find_one_and_update(self, *_args, **_kwargs):
            # Mongo returns no match when the existing lease has not expired.
            return None

    assert asyncio.run(tool._acquire_lease(BusyRuns(), "new-owner", "run-2")) is False


def test_maintenance_lease_accepts_only_the_returned_owner():
    class Runs:
        async def find_one_and_update(self, _query, update, **_kwargs):
            return {"lease_owner": update["$set"]["lease_owner"]}

    assert asyncio.run(tool._acquire_lease(Runs(), "owner", "run-1")) is True


def test_deployed_capability_requires_runtime_published_boot_proof():
    now = datetime.now(timezone.utc)
    complete = {
        "thread_name_capability_version": tool.thread_service.THREAD_NAME_CAPABILITY_VERSION,
        "thread_name_capability_booted_at": now,
        "thread_name_capability_boot_id": "boot-1",
        "thread_name_capability_heartbeat_at": now,
    }
    assert tool.deployed_capability_ready(complete, now=now)
    assert not tool.deployed_capability_ready({**complete, "thread_name_capability_boot_id": ""})
    assert not tool.deployed_capability_ready({**complete, "thread_name_capability_booted_at": "operator supplied"})
    assert not tool.deployed_capability_ready({**complete, "thread_name_capability_version": 0})
    stale = {**complete, "thread_name_capability_heartbeat_at": now - tool.CAPABILITY_MAX_AGE - tool.timedelta(seconds=1)}
    assert not tool.deployed_capability_ready(stale, now=now)

"""World clocks bot task and store, with in-memory Mongo and a fake Discord REST."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import hikari
import pytest

from extensions.tasks import world_clocks as task
from tests.world_clock_fakes import memory_db
from utils.world_clock_store import ChannelInUse, Conflict, WorldClockStore

NOW = datetime(2026, 11, 11, 2, 31, 3, tzinfo=timezone.utc)  # Mark 2:30 at 6 minutes.
VOICE = hikari.ChannelType.GUILD_VOICE


def channel(cid, name, position, parent="900", kind=VOICE):
    return NS(id=int(cid), name=name, position=position, parent_id=int(parent), type=kind)


class FakeRepositioner:
    def __init__(self, rest):
        self.rest, self.items = rest, {}

    def add_reposition_channel(self, *, position, channel):
        self.items[channel] = position

    def __await__(self):
        async def send():
            self.rest.moves.append(dict(self.items))
        return send().__await__()


class FakeRest:
    def __init__(self, channels):
        self.channels = {str(c.id): c for c in channels}
        self.renames, self.moves, self.errors = [], [], {}

    async def fetch_guild_channels(self, guild):
        return list(self.channels.values())

    async def edit_channel(self, cid, *, name, reason):
        error = self.errors.get(str(cid))
        if error:
            raise error
        self.renames.append((str(cid), name))
        self.channels[str(cid)].name = name

    def reposition_channels(self, guild, *, reason):
        return FakeRepositioner(self)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def store():
    return WorldClockStore(memory_db())


async def add(store, zone, channel_id, flag="", code=None, enabled=True):
    row = await store.add_clock({"zone": zone, "flag": flag, "code": code, "channel_id": channel_id}, "1")
    if not enabled:
        row = await store.update_clock(row["_id"], row["version"], {"enabled": False}, "1")
    return row


def test_renames_wrong_names_and_skips_correct_ones(store):
    async def scenario():
        await add(store, "America/New_York", "101", "🇺🇸")
        await add(store, "Europe/London", "102", "🇬🇧")
        rest = FakeRest([channel("101", "EST : 9:21pm", 1), channel("102", "🇬🇧 GMT · 2:30am", 2)])
        entry = await task.run_once(store, rest, NOW)
        return entry, rest, await store.list_clocks()
    entry, rest, clocks = run(scenario())
    assert rest.renames == [("101", "🇺🇸 EST GMT-5 · 9:30pm")]
    assert entry["renamed"] == 1 and entry["unchanged"] == 1
    assert {c["status"] for c in clocks} == {"ok"}


def test_second_run_in_same_mark_never_renames_again(store):
    async def scenario():
        await add(store, "America/New_York", "101", "🇺🇸")
        rest = FakeRest([channel("101", "old", 1)])
        await task.run_once(store, rest, NOW)
        await task.run_once(store, rest, NOW)  # Restart inside the same mark.
        return rest
    assert len(run(scenario()).renames) == 1


def test_off_clocks_are_never_renamed(store):
    async def scenario():
        await add(store, "America/New_York", "101", enabled=False)
        rest = FakeRest([channel("101", "frozen", 1)])
        entry = await task.run_once(store, rest, NOW)
        return entry, rest
    entry, rest = run(scenario())
    assert rest.renames == [] and entry["renamed"] == 0


def test_missing_channel_marks_only_that_clock(store):
    async def scenario():
        await add(store, "Asia/Manila", "103", "🇵🇭")
        await add(store, "America/New_York", "101", "🇺🇸")
        rest = FakeRest([channel("101", "old", 1)])
        entry = await task.run_once(store, rest, NOW)
        return entry, rest, {c["channel_id"]: c for c in await store.list_clocks()}
    entry, rest, clocks = run(scenario())
    assert clocks["103"]["status"] == "problem" and "missing" in clocks["103"]["status_detail"]
    assert clocks["101"]["status"] == "ok" and entry["problem"] == 1 and entry["renamed"] == 1


def test_text_channel_is_not_a_clock_channel(store):
    async def scenario():
        await add(store, "America/New_York", "101")
        rest = FakeRest([channel("101", "general", 1, kind=hikari.ChannelType.GUILD_TEXT)])
        await task.run_once(store, rest, NOW)
        return rest, (await store.list_clocks())[0]
    rest, row = run(scenario())
    assert rest.renames == [] and row["status"] == "problem"


@pytest.mark.parametrize("error,status", [
    (asyncio.TimeoutError(), "waiting"),
    (hikari.RateLimitTooLongError(route="r", is_global=False, retry_after=500, max_retry_after=300, reset_at=0, limit=2, period=600), "waiting"),
    (RuntimeError("network"), "problem"),
])
def test_rate_limit_waits_for_next_mark_and_other_errors_mark_problem(store, error, status):
    async def scenario():
        await add(store, "America/New_York", "101")
        await add(store, "Europe/London", "102")
        rest = FakeRest([channel("101", "old", 1), channel("102", "old", 2)])
        rest.errors["101"] = error
        entry = await task.run_once(store, rest, NOW)
        return entry, rest, {c["channel_id"]: c for c in await store.list_clocks()}
    entry, rest, clocks = run(scenario())
    assert clocks["101"]["status"] == status
    assert rest.renames == [("102", "GMT · 2:30am")]  # The other clock still runs.


def test_forbidden_marks_problem(store):
    class Forbidden(hikari.ForbiddenError):
        def __init__(self):
            pass
    async def scenario():
        await add(store, "America/New_York", "101")
        rest = FakeRest([channel("101", "old", 1)])
        rest.errors["101"] = Forbidden()
        await task.run_once(store, rest, NOW)
        return (await store.list_clocks())[0]
    row = run(scenario())
    assert row["status"] == "problem" and "permissions" in row["status_detail"]


def test_missing_code_marks_problem_without_rename(store):
    async def scenario():
        await add(store, "Asia/Dubai", "101")
        rest = FakeRest([channel("101", "old", 1)])
        await task.run_once(store, rest, NOW)
        return rest, (await store.list_clocks())[0]
    rest, row = run(scenario())
    assert rest.renames == [] and "code" in row["status_detail"]


def test_reorders_only_clock_channels(store):
    async def scenario():
        await add(store, "Australia/Sydney", "101")
        await add(store, "America/Los_Angeles", "102")
        rest = FakeRest([channel("101", "a", 1), channel("555", "Statbot EST", 2), channel("102", "b", 3)])
        entry = await task.run_once(store, rest, NOW)
        return entry, rest
    entry, rest = run(scenario())
    assert entry["moved"] is True
    assert rest.moves == [{102: 1, 101: 3}]


def test_staff_edit_during_run_is_not_overwritten(store):
    async def scenario():
        row = await add(store, "America/New_York", "101")
        edited = await store.update_clock(row["_id"], row["version"], {"enabled": False}, "2")
        ok = await store.record_result(row["_id"], row["version"], status="ok")
        return ok, await store.get_clock(row["_id"]), edited
    ok, current, edited = run(scenario())
    assert ok is False and current["status"] == "waiting" and current["version"] == edited["version"]


def test_no_clocks_means_no_discord_calls(store):
    class Untouchable:
        async def fetch_guild_channels(self, guild):
            raise AssertionError("no clocks: no Discord call")
    assert run(task.run_once(store, Untouchable(), NOW)) is None


def test_store_conflicts_and_one_clock_per_channel(store):
    async def scenario():
        row = await add(store, "America/New_York", "101")
        with pytest.raises(ChannelInUse):
            await add(store, "Europe/London", "101")
        with pytest.raises(Conflict):
            await store.update_clock(row["_id"], row["version"] + 5, {"enabled": False}, "1")
        with pytest.raises(Conflict):
            await store.remove_clock(row["_id"], row["version"] + 5)
        await store.remove_clock(row["_id"], row["version"])
        return await store.list_clocks()
    assert run(scenario()) == []


def test_settings_defaults_save_and_conflict(store):
    async def scenario():
        first = await store.get_settings()
        saved = await store.save_settings(0, {"category_id": "900", "time_format": "24h", "interval_minutes": 10}, "1")
        with pytest.raises(Conflict):
            await store.save_settings(0, {"category_id": None, "time_format": "12h", "interval_minutes": 6}, "2")
        again = await store.save_settings(saved["version"], {"category_id": None, "time_format": "12h", "interval_minutes": 6}, "2")
        return first, saved, again
    first, saved, again = run(scenario())
    assert first["interval_minutes"] == 6 and first["time_format"] == "12h"
    assert saved["time_format"] == "24h" and saved["version"] == 1 and again["version"] == 2


def test_task_uses_saved_interval_and_format(store):
    async def scenario():
        await store.save_settings(0, {"category_id": None, "time_format": "24h", "interval_minutes": 10}, "1")
        await add(store, "Europe/London", "101")
        rest = FakeRest([channel("101", "old", 1)])
        await task.run_once(store, rest, datetime(2026, 11, 11, 2, 39, tzinfo=timezone.utc))
        return rest
    assert run(scenario()).renames == [("101", "GMT · 02:30")]


def test_run_history_is_pruned(store):
    async def scenario():
        old = datetime(2026, 10, 1, tzinfo=timezone.utc)
        await store.add_run({"at": old})
        await store.add_run({"at": NOW})
        return await store.recent_runs()
    rows = run(scenario())
    assert [row["at"] for row in rows] == [NOW]


def test_record_result_rejects_staff_fields(store):
    with pytest.raises(ValueError):
        run(store.record_result("x", 1, enabled=False))


def test_task_and_store_do_not_import_dashboard():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in ("extensions/tasks/world_clocks.py", "utils/world_clocks.py", "utils/world_clock_store.py"):
        tree = ast.parse((root / path).read_text())
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not any(name.startswith(("cwl_web", "aiohttp")) for name in names), path
    rules_tree = ast.parse((root / "utils/world_clocks.py").read_text())
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and "pymongo" in ast.unparse(n) for n in ast.walk(rules_tree))


def test_clock_turned_off_during_a_run_is_not_renamed(store):
    async def scenario():
        row = await add(store, "America/New_York", "101")
        rest = FakeRest([channel("101", "old", 1)])
        original = store.get_clock

        async def turned_off(clock_id):  # Staff turn the clock off while the run is busy.
            current = await original(clock_id)
            await store.update_clock(clock_id, current["version"], {"enabled": False}, "2")
            return await original(clock_id)
        store.get_clock = turned_off
        entry = await task.run_once(store, rest, NOW)
        return entry, rest
    entry, rest = run(scenario())
    assert rest.renames == [] and entry["skipped"] == 1


def test_discord_down_records_a_run_and_renames_nothing(store):
    class Down(FakeRest):
        async def fetch_guild_channels(self, guild):
            raise RuntimeError("down")

    async def scenario():
        await add(store, "America/New_York", "101")
        rest = Down([channel("101", "old", 1)])
        entry = await task.run_once(store, rest, NOW)
        return entry, rest, await store.recent_runs()
    entry, rest, runs = run(scenario())
    assert entry["discord_unavailable"] is True and rest.renames == []
    assert runs[0]["discord_unavailable"] is True


def test_float_interval_in_storage_falls_back_to_default(store):
    async def scenario():
        await store.settings_rows.insert_one({"_id": "settings", "interval_minutes": 6.0, "version": 1})
        return await store.get_settings()
    assert type(run(scenario())["interval_minutes"]) is int


def test_dashboard_add_creates_the_unique_index_first(store):
    calls = []
    original = store.clocks.create_index

    async def spy(*args, **kwargs):
        calls.append(kwargs.get("name"))
        return await original(*args, **kwargs)
    store.clocks.create_index = spy
    run(add(store, "America/New_York", "101"))
    assert "one_clock_per_channel" in calls

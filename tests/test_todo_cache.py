import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import coc

from utils import todo_data


def test_coc_utc_timestamps_do_not_use_the_host_timezone(monkeypatch):
    saved_tz = os.environ.get("TZ")

    try:
        for host_tz in (
            "UTC", "America/New_York", "Asia/Kolkata", "Asia/Tokyo", "Pacific/Auckland",
        ):
            monkeypatch.setenv("TZ", host_tz)
            time.tzset()
            for start in (datetime(2026, 1, 15, 12), datetime(2026, 9, 14, 12)):
                war = SimpleNamespace(
                    start_time=SimpleNamespace(time=start),
                    end_time=SimpleNamespace(time=start + timedelta(days=1)),
                )
                assert todo_data._starts_at(war) == int(
                    start.replace(tzinfo=timezone.utc).timestamp()
                )
                assert todo_data._ends_at(war) == int(
                    (start + timedelta(days=1)).replace(tzinfo=timezone.utc).timestamp()
                )

        aware = SimpleNamespace(
            start_time=SimpleNamespace(
                time=datetime(2026, 9, 14, 14, tzinfo=timezone(timedelta(hours=2)))
            )
        )
        assert todo_data._starts_at(aware) == int(
            datetime(2026, 9, 14, 12, tzinfo=timezone.utc).timestamp()
        )
    finally:
        if saved_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", saved_tz)
        time.tzset()


def test_actionable_war_state_reconciles_phase_with_authoritative_deadlines():
    now = 1_800_000_000

    assert todo_data._actionable_war_state(
        "inWar", now - 86_400, now - 1, observed_at=now,
    ) == ""
    assert todo_data._actionable_war_state(
        "preparation", now - 1, now + 86_400, observed_at=now,
    ) == "inWar"
    assert todo_data._actionable_war_state(
        "preparation", now + 1, now + 86_400, observed_at=now,
    ) == "preparation"
    assert todo_data._actionable_war_state(
        "inWar", None, None, observed_at=now,
    ) == "inWar"


def test_process_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(todo_data, "CACHE_MAX_ENTRIES", 2)
    todo_data._cache.clear()

    todo_data.cache_put("player:#ONE", object(), 600)
    todo_data.cache_put("player:#TWO", object(), 600)
    todo_data.cache_put("player:#THREE", object(), 600)

    assert len(todo_data._cache) == 2
    assert "player:#THREE" in todo_data._cache
    todo_data._cache.clear()


def test_private_war_log_is_explicit_cached_and_concisely_logged(capsys):
    class Client:
        calls = 0

        async def get_clan_war(self, _clan_tag):
            self.calls += 1
            raise coc.PrivateWarLog(data={"reason": "accessDenied"})

    todo_data._cache.clear()
    client = Client()

    first = asyncio.run(todo_data._get_war(client, "#PRIVATE"))
    second = asyncio.run(todo_data._get_war(client, "#PRIVATE"))

    assert first == second == ("private", None)
    assert client.calls == 1
    assert capsys.readouterr().out.count(
        "current-war unreadable clan=#PRIVATE reason=private-war-log"
    ) == 1
    todo_data._cache.clear()


def test_warm_count_is_scoped_to_current_distinct_linked_tags():
    todo_data._cache.clear()
    todo_data.cache_put("player:#MINE", object(), 600)
    todo_data.cache_put("player:#OTHER", object(), 600)
    todo_data.cache_put("player:#EXPIRED", object(), -1)

    warm, linked = todo_data.live_keys_for(
        "player:", ["#mine", "#MINE", "#COLD", "#EXPIRED"]
    )

    assert (warm, linked) == (1, 3)
    assert warm <= linked
    todo_data._cache.clear()

def test_call_counters_are_isolated_between_concurrent_invocations():
    async def invocation(label):
        todo_data.reset_calls()
        todo_data.note_call(label, 0.1)
        await asyncio.sleep(0)
        return todo_data.call_stats()

    async def exercise():
        return await asyncio.gather(invocation("first"), invocation("second"))

    first, second = asyncio.run(exercise())

    assert first["by_label"] == {"first": 1}
    assert second["by_label"] == {"second": 1}


def _age_cache_entry(key: str, seconds: int = 600) -> float:
    expires_at, _filled_at, value = todo_data._cache[key]
    todo_data._cache[key] = (expires_at, time.time() - seconds, value)
    return time.time()


def test_automatic_check_revalidates_only_old_negative_war_cache():
    class Client:
        calls = 0

        async def get_clan_war(self, _clan_tag):
            self.calls += 1
            return SimpleNamespace(state="inWar")

    todo_data._cache.clear()
    todo_data.cache_put("war:#CLAN", ("none", None), 3600)
    cutoff = _age_cache_entry("war:#CLAN")
    client = Client()

    result = asyncio.run(todo_data._get_war(
        client, "#CLAN", recheck_negative_after=cutoff
    ))

    assert result[0] == "war"
    assert client.calls == 1
    todo_data._cache.clear()


def test_automatic_check_keeps_positive_and_unrelated_war_cache():
    positive = ("war", SimpleNamespace(state="inWar"))
    unrelated = ("none", None)
    todo_data._cache.clear()
    todo_data.cache_put("war:#CLAN", positive, 3600)
    todo_data.cache_put("war:#OTHER", unrelated, 3600)
    cutoff = _age_cache_entry("war:#CLAN")
    _age_cache_entry("war:#OTHER")

    class Client:
        async def get_clan_war(self, _clan_tag):
            raise AssertionError("positive cache must be reused")

    result = asyncio.run(todo_data._get_war(
        Client(), "#CLAN", recheck_negative_after=cutoff
    ))

    assert result is positive
    assert todo_data.cache_get("war:#OTHER") is unrelated
    todo_data._cache.clear()


def test_automatic_check_revalidates_ended_regular_war():
    ended = ("war", SimpleNamespace(state="warEnded"))
    todo_data._cache.clear()
    todo_data.cache_put("war:#CLAN", ended, 3600)
    cutoff = _age_cache_entry("war:#CLAN")

    class Client:
        calls = 0

        async def get_clan_war(self, _clan_tag):
            self.calls += 1
            return SimpleNamespace(state="preparation")

    client = Client()
    result = asyncio.run(todo_data._get_war(
        client, "#CLAN", recheck_negative_after=cutoff
    ))

    assert result[0] == "war"
    assert result[1].state == "preparation"
    assert client.calls == 1
    todo_data._cache.clear()


def test_automatic_check_revalidates_old_absent_cwl_cache():
    class Client:
        calls = 0

        async def get_league_group(self, _clan_tag):
            self.calls += 1
            return SimpleNamespace(state="notInWar", rounds=[])

    todo_data._cache.clear()
    todo_data.cache_put("cwl:#CLAN", ("none", None), 3600)
    cutoff = _age_cache_entry("cwl:#CLAN")
    client = Client()

    result = asyncio.run(todo_data._get_cwl_round(
        client, "#CLAN", recheck_negative_after=cutoff
    ))

    assert result == ("none", None)
    assert client.calls == 1
    todo_data._cache.clear()


def test_concurrent_empty_war_responses_share_one_short_lived_error():
    class Client:
        calls = 0

        async def get_clan_war(self, _clan_tag):
            self.calls += 1
            await asyncio.sleep(0)
            return None

    todo_data._cache.clear()
    todo_data._fetch_locks.clear()
    todo_data.cache_put("war:#CLAN", ("none", None), 3600)
    cutoff = _age_cache_entry("war:#CLAN")
    client = Client()

    async def exercise():
        return await asyncio.gather(
            todo_data._get_war(
                client, "#CLAN", recheck_negative_after=cutoff
            ),
            todo_data._get_war(
                client, "#CLAN", recheck_negative_after=cutoff
            ),
        )

    results = asyncio.run(exercise())

    assert results == [("error", None), ("error", None)]
    assert client.calls == 1
    todo_data._cache.clear()


def test_failed_negative_rechecks_share_one_short_lived_error():
    class Client:
        calls = 0

        async def get_clan_war(self, _clan_tag):
            self.calls += 1
            await asyncio.sleep(0)
            raise RuntimeError("temporary outage")

    todo_data._cache.clear()
    todo_data._fetch_locks.clear()
    todo_data.cache_put("war:#CLAN", ("none", None), 3600)
    cutoff = _age_cache_entry("war:#CLAN")
    client = Client()

    async def exercise():
        return await asyncio.gather(
            todo_data._get_war(
                client, "#CLAN", recheck_negative_after=cutoff
            ),
            todo_data._get_war(
                client, "#CLAN", recheck_negative_after=cutoff
            ),
        )

    results = asyncio.run(exercise())

    assert results == [("error", None), ("error", None)]
    assert client.calls == 1
    todo_data._cache.clear()

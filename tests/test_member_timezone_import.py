import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from utils.member_timezone_import import (
    canonical_zone,
    parsed_zone,
    import_nicknames,
    nickname_country,
)
from utils.member_timezones import profile_fields
from utils.member_profiles import ProfileConflict

import json
from pathlib import Path

VECTORS = json.loads(
    (Path(__file__).parents[1] / "utils/member_timezone_vectors.json").read_text()
)


@pytest.mark.parametrize("nickname,expected", VECTORS)
def test_shared_parser(nickname, expected):
    assert parsed_zone(nickname) == expected


def test_import_offsets_and_missing_country_are_explicit():
    for offset in (-840, -585, 0, 345, 840):
        fields = canonical_zone(offset)
        assert (
            profile_fields(dict(fields, country=None), source="nickname_import")[
                "utc_offset_minutes"
            ]
            == offset
        )
        with pytest.raises(ValueError):
            profile_fields(dict(fields, country=None), source="staff")
    assert nickname_country("N | GMT 🇺🇸 🇨🇦") is None
    assert nickname_country("N | GMT 🇺🇸") == "US"
    for invalid in (True, 841, "60"):
        with pytest.raises(ValueError):
            canonical_zone(invalid)


def test_import_preserves_every_prior_decision_and_reports_conflicts():
    async def run():
        ids = [str(123456789012345670 + i) for i in range(7)]
        store = SimpleNamespace(
            for_members=AsyncMock(
                return_value={
                    ids[0]: {"source": "staff"},
                    ids[1]: {"source": "warrior"},
                    ids[2]: {"source": "nickname_import"},
                }
            ),
            write=AsyncMock(
                side_effect=[{"source": "nickname_import"}, ProfileConflict("race")]
            ),
        )
        rows = [dict(discord_id=key, nickname="N | GMT+5:45") for key in ids[:5]]
        rows += [
            dict(discord_id=ids[5], nickname="N | huh"),
            dict(discord_id=ids[6], nickname=None),
        ]
        result = await import_nicknames(store, rows, actor_id=ids[0])
        assert result == dict(
            known=5, unknown=1, none=1, imported=1, preserved=3, conflicts=1, bots=0
        )
        assert store.write.await_count == 2
        assert store.write.await_args_list[0].args[1]["country"] is None
        store.for_members.reset_mock()
        with pytest.raises(ValueError):
            await import_nicknames(store, rows + rows, actor_id=ids[0])
        store.for_members.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "value,name,review",
    [
        ("Sir | Ruggie | EST 🇺🇸", "Sir | Ruggie", False),
        ("Bob | Co-Leader", "Bob | Co-Leader", True),
        ("Alice", "Alice", True),
        ("Ana | UTC+5:45 🇳🇵", "Ana", False),
    ],
)
def test_nickname_name_only_removes_the_last_recognized_zone(value, name, review):
    from utils.member_timezone_import import nickname_name

    assert nickname_name(value) == {"name": name, "needs_review": review}


@pytest.mark.parametrize(
    "literal,offset",
    [
        ("EDT", -300),
        ("CDT", -360),
        ("MDT", -420),
        ("PDT", -480),
        ("BST", 0),
        ("CEST", 60),
        ("EEST", 120),
        ("AEDT", 600),
        ("NZDT", 720),
    ],
)
def test_profile_import_uses_standard_time_without_changing_compare_literals(
    literal, offset
):
    from utils.member_timezone_import import profile_zone

    assert profile_zone(f"Name | {literal}")["offsetMinutes"] == offset

    async def run():
        store = SimpleNamespace(
            for_members=AsyncMock(return_value={}),
            write=AsyncMock(return_value={"source": "nickname_import"}),
        )
        await import_nicknames(
            store,
            [{"discord_id": "123456789012345678", "nickname": f"Name | {literal}"}],
            actor_id="234567890123456789",
        )
        assert store.write.await_args.args[1]["utc_offset_minutes"] == offset

    asyncio.run(run())


def test_non_menu_offset_import_persists_literal_minutes():
    async def run():
        store = SimpleNamespace(
            for_members=AsyncMock(return_value={}),
            write=AsyncMock(return_value={"source": "nickname_import"}),
        )
        result = await import_nicknames(
            store,
            [dict(discord_id="123456789012345678", nickname="Ana| GMT+5:45🇳🇵")],
            actor_id="234567890123456789",
        )
        assert result["imported"] == 1
        fields = store.write.await_args.args[1]
        assert fields["zone_id"] == "gmt+5:45" and fields["utc_offset_minutes"] == 345
        assert fields["country"] == "NP"

    asyncio.run(run())


def test_1447_members_complete_with_scaled_atlas_latency_inside_budget():
    async def run():
        active = peak = 0

        async def write(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                # 20ms represents 200ms per lease/CAS write path (10x time scale).
                await asyncio.sleep(0.02)
                return {"source": "nickname_import"}
            finally:
                active -= 1

        store = SimpleNamespace(for_members=AsyncMock(return_value={}), write=write)
        members = [
            dict(discord_id=str(123456789012340000 + i), nickname="N | EST 🇺🇸")
            for i in range(1447)
        ]
        async with asyncio.timeout(10):
            result = await import_nicknames(
                store, members, actor_id="234567890123456789"
            )
        assert result["imported"] == 1447 and peak == 8 and active == 0
        store.for_members.assert_awaited_once()

    asyncio.run(run())


def test_partial_import_drains_workers_then_rerun_preserves_saved_and_imported():
    async def run():
        from copy import deepcopy

        ids = [str(123456789012340000 + i) for i in range(80)]
        saved = {
            ids[0]: {"source": "staff", "revision": 4},
            ids[1]: {"source": "warrior", "revision": 9},
        }
        protected = deepcopy(saved)
        failed = False
        active = 0
        writes = {}

        async def batch(*args, **kwargs):
            return deepcopy(saved)

        async def write(uid, *args, **kwargs):
            nonlocal failed, active
            active += 1
            try:
                await asyncio.sleep(0.001)
                if uid == ids[25] and not failed:
                    failed = True
                    raise RuntimeError("temporary Atlas failure")
                assert uid not in saved
                saved[uid] = {"source": "nickname_import", "revision": 1}
                writes[uid] = writes.get(uid, 0) + 1
                return saved[uid]
            finally:
                active -= 1

        store = SimpleNamespace(for_members=batch, write=write)
        members = [dict(discord_id=uid, nickname="N | EST 🇺🇸") for uid in ids]
        progress = {}
        with pytest.raises(ExceptionGroup):
            await import_nicknames(store, members, actor_id=ids[0], progress=progress)
        assert active == 0 and 0 < progress["imported"] < 78
        result = await import_nicknames(store, members, actor_id=ids[0])
        assert len(saved) == 80 and result["preserved"] >= 2
        assert all(n == 1 for n in writes.values())
        assert all(saved[k] == v for k, v in protected.items())

    asyncio.run(run())

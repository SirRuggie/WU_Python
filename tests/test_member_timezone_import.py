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
            get=AsyncMock(
                side_effect=[
                    {"source": "staff"},
                    {"source": "warrior"},
                    {"source": "nickname_import"},
                    None,
                    None,
                ]
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
        store.get.reset_mock()
        with pytest.raises(ValueError):
            await import_nicknames(store, rows + rows, actor_id=ids[0])
        store.get.assert_not_awaited()

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
            get=AsyncMock(return_value=None),
            write=AsyncMock(return_value={"source": "nickname_import"}),
        )
        await import_nicknames(
            store,
            [{"discord_id": "123456789012345678", "nickname": f"Name | {literal}"}],
            actor_id="234567890123456789",
        )
        assert store.write.await_args.args[1]["utc_offset_minutes"] == offset

    asyncio.run(run())

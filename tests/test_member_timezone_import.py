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

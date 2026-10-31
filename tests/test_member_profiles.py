import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from pymongo.errors import DuplicateKeyError
from utils.member_profiles import MemberProfiles, ProfileConflict, LEFT_TTL_SECONDS
from utils.member_timezones import (
    highest_account,
    nickname,
    ZONE_CHOICES,
    COUNTRY_CHOICES,
    profile_fields,
)

USER = "123456789012345678"
ACTOR = "234567890123456789"
FIELDS = {"zone_id": "gmt-5", "country": "US", "name_source_tag": "#PYY"}


class Collection:
    def __init__(self):
        self.row = None
        self.create_index = AsyncMock()

    async def find_one(self, q):
        return deepcopy(self.row)

    async def insert_one(self, row):
        if self.row:
            raise DuplicateKeyError("already exists")
        self.row = deepcopy(row)

    async def replace_one(self, q, row):
        matched = bool(self.row and self.row["revision"] == q["revision"])
        if matched:
            self.row = deepcopy(row)
        return S(matched_count=int(matched))


def test_bounded_revision_writer_import_protection_and_membership_ttl():
    async def run():
        coll = Collection()
        store = MemberProfiles(S(member_profiles=coll))
        await store.ensure_indexes()
        coll.create_index.assert_awaited_once_with(
            "left_at", name="member_profile_left_90d", expireAfterSeconds=90 * 86400
        )
        first = await store.write(
            USER, FIELDS, expected_revision=0, updated_by=ACTOR, source="staff"
        )
        assert first["revision"] == 1 and coll.row["gmt_label"] == "GMT-5"
        with pytest.raises(ProfileConflict):
            await store.write(
                USER, FIELDS, expected_revision=0, updated_by=ACTOR, source="warrior"
            )
        before = deepcopy(coll.row)
        assert (
            await store.write(
                USER,
                dict(FIELDS, zone_id="gmt"),
                expected_revision=1,
                updated_by=ACTOR,
                source="nickname_import",
            )
            == before
        )
        assert coll.row == before
        left = datetime(2026, 10, 31, tzinfo=timezone.utc)
        await store.membership(USER, left_at=left)
        assert coll.row["left_at"] == left and coll.row["revision"] == 2
        await store.membership(USER, left_at=None)
        assert coll.row["left_at"] is None and coll.row["revision"] == 3
        assert len(str(coll.row)) < 1500 and LEFT_TTL_SECONDS == 7776000

    asyncio.run(run())


def test_highest_tie_no_links_and_partial_results_never_silently_pick():
    low = {"tag": "#PYY", "name": "Low", "townHallLevel": 17}
    high = {"tag": "#PQQ", "name": "High", "townHallLevel": 18}
    assert highest_account([low, high]) == high
    assert highest_account([high, dict(high, tag="#PYQ")]) is None
    assert highest_account([]) is None
    assert highest_account([high], complete=False) is None
    assert highest_account([high, {"name": "Missing TH"}]) is None


def test_zone_country_limits_format_and_length():
    assert len(ZONE_CHOICES) == 19 and len(COUNTRY_CHOICES) + 1 <= 25
    assert nickname("Sir Ruggie", "gmt-5", "us") == "Sir Ruggie | GMT-5 🇺🇸"
    assert nickname("Name", "gmt+5:30", "IN") == "Name | GMT+5:30 🇮🇳"
    assert (
        profile_fields(dict(FIELDS, utc_offset_minutes=99, gmt_label="untrusted"))[
            "utc_offset_minutes"
        ]
        == -300
    )
    for name in ("", "a" * 32, "bad\nname"):
        with pytest.raises(ValueError):
            nickname(name, "gmt", "GB")
    with pytest.raises(ValueError):
        profile_fields(dict(FIELDS, zone_id="bogus"))


def test_name_choice_official_lookup_partial_and_api_failure(monkeypatch):
    from utils import recruit_links, todo_data
    from utils.member_timezones import name_choices

    async def run():
        links = AsyncMock(
            return_value=S(
                sources={"#PYY": ("ClashKing",)}, unavailable=(), conflicts=()
            )
        )
        players = AsyncMock(
            return_value=([S(tag="#PYY", name="Main", town_hall=18)], [])
        )
        monkeypatch.setattr(recruit_links, "resolve", links)
        monkeypatch.setattr(todo_data, "fetch_accounts", players)
        result = await name_choices(None, USER)
        assert result["suggested"]["name"] == "Main" and result["complete"]
        players.return_value = ([], ["upstream unavailable"])
        result = await name_choices(None, USER)
        assert result["suggested"] is None and not result["complete"]
        links.side_effect = TimeoutError()
        assert (await name_choices(None, USER))["unavailable"]

    asyncio.run(run())

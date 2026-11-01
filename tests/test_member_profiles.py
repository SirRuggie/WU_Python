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
        edited_at = coll.row["updated_at"]
        await store.membership(USER, left_at=left)
        assert coll.row["updated_at"] == edited_at
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
    with pytest.raises(ValueError):
        nickname("Name", "gmt", "notflag")


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
        links.side_effect = RuntimeError("upstream failure")
        assert (await name_choices(None, USER))["suggested"] is None

    asyncio.run(run())


@pytest.fixture(autouse=True)
def isolated_lease(monkeypatch):
    from contextlib import asynccontextmanager
    from utils import member_profile_leases

    @asynccontextmanager
    async def claim(*args):
        yield {"owner": "test"}

    monkeypatch.setattr(member_profile_leases, "editing", claim)
    monkeypatch.setattr(member_profile_leases, "verify", AsyncMock())


def test_discord_failure_never_saves_and_stale_revision_never_edits():
    async def run():
        coll = Collection()
        store = MemberProfiles(S(member_profiles=coll))
        edit = AsyncMock(side_effect=RuntimeError("Discord refused"))
        with pytest.raises(RuntimeError):
            await store.commit_after(
                USER,
                FIELDS,
                change=edit,
                expected_revision=0,
                updated_by=ACTOR,
                source="warrior",
            )
        assert coll.row is None
        edit.side_effect = None
        await store.commit_after(
            USER,
            FIELDS,
            change=edit,
            expected_revision=0,
            updated_by=ACTOR,
            source="warrior",
        )
        assert coll.row["revision"] == 1
        edit.reset_mock()
        with pytest.raises(ProfileConflict):
            await store.commit_after(
                USER,
                FIELDS,
                change=edit,
                expected_revision=0,
                updated_by=ACTOR,
                source="warrior",
            )
        edit.assert_not_awaited()

    asyncio.run(run())


def test_delayed_departure_cannot_expire_a_newer_rejoin():
    async def run():
        coll = Collection()
        store = MemberProfiles(S(member_profiles=coll))
        await store.write(
            USER,
            FIELDS,
            expected_revision=0,
            updated_by=ACTOR,
            source="warrior",
            now=datetime(2026, 10, 31, 11, tzinfo=timezone.utc),
        )
        departed = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        joined = datetime(2026, 10, 31, 13, tzinfo=timezone.utc)
        # The newer join can complete while the older departure waits for an edit lease.
        await store.membership(USER, left_at=None, observed_at=joined)
        revision = coll.row["revision"]
        await store.membership(USER, left_at=departed, observed_at=departed)
        assert coll.row["left_at"] is None and coll.row["revision"] == revision
        await store.write(
            USER, FIELDS, expected_revision=revision, updated_by=ACTOR, source="staff"
        )
        assert coll.row["membership_at"] >= joined

    asyncio.run(run())


def test_retention_index_failure_refuses_edit_before_discord():
    async def run():
        coll = Collection()
        coll.create_index.side_effect = RuntimeError("index unavailable")
        edit = AsyncMock()
        store = MemberProfiles(S(member_profiles=coll))
        with pytest.raises(RuntimeError, match="index unavailable"):
            await store.commit_after(
                USER,
                FIELDS,
                change=edit,
                expected_revision=0,
                updated_by=ACTOR,
                source="warrior",
            )
        edit.assert_not_awaited()
        assert coll.row is None

    asyncio.run(run())


def test_lease_lost_during_confirmed_edit_never_commits_a_profile(monkeypatch):
    async def run():
        from utils import member_profile_leases

        coll = Collection()
        store = MemberProfiles(S(member_profiles=coll))
        change = AsyncMock()
        monkeypatch.setattr(
            member_profile_leases,
            "verify",
            AsyncMock(
                side_effect=[None, member_profile_leases.ProfileBusy("Lease replaced")]
            ),
        )
        with pytest.raises(member_profile_leases.ProfileBusy):
            await store.commit_after(
                USER,
                FIELDS,
                change=change,
                expected_revision=0,
                updated_by=ACTOR,
                source="warrior",
            )
        change.assert_awaited_once()
        assert coll.row is None

    asyncio.run(run())


def test_preview_cannot_be_consumed_for_another_target_actor_or_guild():
    async def run():
        row = {
            "_id": "wizard",
            "type": "warrior_setup",
            "guild_id": 10,
            "user_id": int(USER),
            "recruiter_id": int(ACTOR),
            "nickname_setup": {"nonce": "n", "step": "preview"},
        }

        async def update(query, change, **kwargs):
            def value(path):
                current = row
                for key in path.split("."):
                    current = current.get(key) if isinstance(current, dict) else None
                return current

            matched = all(value(key) == expected for key, expected in query.items())
            if matched:
                row["nickname_setup"]["step"] = change["$set"]["nickname_setup.step"]
            return S(matched_count=int(matched), upserted_id=None)

        store = MemberProfiles(
            S(
                member_profiles=Collection(),
                component_state=S(
                    update_one=update, find_one=AsyncMock(return_value=row)
                ),
            )
        )
        for wrong in (
            dict(guild_id=11, discord_id=USER, actor_id=ACTOR),
            dict(guild_id=10, discord_id=ACTOR, actor_id=ACTOR),
            dict(guild_id=10, discord_id=USER, actor_id=USER),
        ):
            assert not await store.consume_preview("wizard", "n", **wrong)
            assert row["nickname_setup"]["step"] == "preview"
        assert await store.consume_preview(
            "wizard", "n", guild_id=10, discord_id=USER, actor_id=ACTOR
        )
        assert not await store.consume_preview(
            "wizard", "n", guild_id=10, discord_id=USER, actor_id=ACTOR
        )

    asyncio.run(run())


def test_consume_preview_rejects_a_replaced_nonce(monkeypatch):
    from utils import component_state

    async def run():
        record = {
            "_id": "s",
            "type": "warrior_setup",
            "guild_id": 10,
            "user_id": int(USER),
            "recruiter_id": int(ACTOR),
            "nickname_setup.nonce": "new",
            "nickname_setup.step": "preview",
        }

        async def update(mongo, query, change):
            matched = all(record.get(key) == value for key, value in query.items())
            if matched:
                record.update(change["$set"])
            return S(matched_count=int(matched))

        monkeypatch.setattr(component_state, "update_state", update)
        store = MemberProfiles(S(member_profiles=object()))
        assert not await store.consume_preview(
            "s", "old", guild_id=10, discord_id=USER, actor_id=ACTOR
        )
        assert record["nickname_setup.step"] == "preview"
        assert await store.consume_preview(
            "s", "new", guild_id=10, discord_id=USER, actor_id=ACTOR
        )
        assert record["nickname_setup.step"] == "applying"

    asyncio.run(run())

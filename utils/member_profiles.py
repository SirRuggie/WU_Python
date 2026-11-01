"""One bounded profile per Discord member; the sole profile collection writer."""

from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

SOURCES = frozenset({"warrior", "nickname_import", "staff"})
LEFT_TTL_SECONDS = 90 * 24 * 60 * 60


class ProfileConflict(ValueError):
    pass


def member_id(value):
    text = str(value)
    if (
        not text.isascii()
        or not text.isdigit()
        or not 15 <= len(text) <= 22
        or int(text) <= 0
    ):
        raise ValueError("Choose a valid Discord member.")
    return str(int(text))


class MemberProfiles:
    def __init__(self, mongo):
        self.mongo = mongo
        self.collection = mongo.member_profiles

    async def ensure_indexes(self):
        await self.collection.create_index(
            "left_at",
            name="member_profile_left_90d",
            expireAfterSeconds=LEFT_TTL_SECONDS,
        )

    async def get(self, discord_id):
        return await self.collection.find_one({"_id": member_id(discord_id)})

    async def for_members(self, discord_ids):
        keys = sorted({member_id(value) for value in discord_ids})
        if not keys:
            return {}
        rows = await self.collection.find(
            {"_id": {"$in": keys}, "left_at": None}
        ).to_list(length=None)
        return {row["discord_id"]: row for row in rows}

    async def write(self, discord_id, fields, **options):
        from utils.member_profile_leases import editing, verify

        async with editing(self.mongo, member_id(discord_id)) as claim:
            await verify(self.mongo, claim)
            return await self._write(discord_id, fields, **options)

    async def commit_after(
        self, discord_id, fields, *, change, expected_revision, updated_by, source
    ):
        """Serialize the external edit with CAS; failed edits never save a profile.

        The caller owns Discord transport and must use a bounded one-shot call.
        On cancellation/uncertain delivery the caller's durable preview receipt
        stays consumed. Never automatically retry that callback.
        """
        from utils.member_profile_leases import editing, verify

        if (
            source not in ("warrior", "staff")
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise ValueError("Invalid profile edit source or revision.")
        member_id(updated_by)
        async with editing(self.mongo, member_id(discord_id)) as claim:
            current = await self.get(discord_id)
            if int((current or {}).get("revision", 0)) != expected_revision:
                raise ProfileConflict("Member profile changed. Refresh before saving.")
            from utils.member_timezones import profile_fields

            profile_fields(fields)
            await verify(self.mongo, claim)
            await change()
            await verify(self.mongo, claim)
            return await self._write(
                discord_id,
                fields,
                expected_revision=expected_revision,
                updated_by=updated_by,
                source=source,
            )

    async def _write(
        self,
        discord_id,
        fields,
        *,
        expected_revision,
        updated_by,
        source,
        now=None,
        left_at=None
    ):
        """CAS replace, never append history; imported values cannot displace staff."""
        from utils.member_timezones import profile_fields

        key = member_id(discord_id)
        actor = member_id(updated_by)
        if (
            source not in SOURCES
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise ValueError("Invalid profile source or revision.")
        current = await self.get(key)
        if int((current or {}).get("revision", 0)) != expected_revision:
            raise ProfileConflict("Member profile changed. Refresh before saving.")
        if (
            source == "nickname_import"
            and current
            and current.get("source") in ("warrior", "staff")
        ):
            return current
        checked = profile_fields(fields)
        at = now or datetime.now(timezone.utc)
        row = dict(
            checked,
            _id=key,
            discord_id=key,
            source=source,
            updated_by=actor,
            updated_at=at,
            revision=expected_revision + 1,
            left_at=left_at,
        )
        try:
            if current is None:
                await self.collection.insert_one(row)
            else:
                result = await self.collection.replace_one(
                    {"_id": key, "revision": expected_revision}, row
                )
                if not result.matched_count:
                    raise ProfileConflict(
                        "Member profile changed. Refresh before saving."
                    )
        except DuplicateKeyError as error:
            raise ProfileConflict(
                "Member profile changed. Refresh before saving."
            ) from error
        return row

    async def membership(self, discord_id, *, left_at):
        """Membership events update existing profiles only, through the same CAS writer."""
        import asyncio
        from utils.member_profile_leases import ProfileBusy

        for _ in range(65):
            current = await self.get(discord_id)
            if current is None or current.get("left_at") == left_at:
                return current
            try:
                return await self.write(
                    discord_id,
                    current,
                    expected_revision=current["revision"],
                    updated_by=current["updated_by"],
                    source=current["source"],
                    left_at=left_at,
                )
            except (ProfileConflict, ProfileBusy):
                await asyncio.sleep(1)
                continue
        raise ProfileConflict("Member membership changed concurrently.")

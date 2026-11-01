"""One bounded profile per Discord member; the sole profile collection writer."""

from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

SOURCES = frozenset({"warrior", "nickname_import", "staff"})
LEFT_TTL_SECONDS = 90 * 24 * 60 * 60


class ProfileOutcomeUncertain(RuntimeError):
    """Safe, explicit split outcome for durable management receipts."""


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

    async def for_members(self, discord_ids, *, include_departed=False):
        keys = sorted({member_id(value) for value in discord_ids})
        if not keys:
            return {}
        query = {"_id": {"$in": keys}}
        if not include_departed:
            query["left_at"] = None
        rows = await self.collection.find(query).to_list(length=None)
        return {row["discord_id"]: row for row in rows}

    async def membership_rows(self):
        rows = await self.collection.find({}, {"_id": 1, "left_at": 1}).to_list(
            length=10001
        )
        if len(rows) > 10000:
            raise ValueError(
                "Member profile reconciliation limit exceeded; no absence marks applied."
            )
        return rows

    async def consume_preview(
        self, session_id, nonce, *, guild_id, discord_id, actor_id
    ):
        from utils.component_state import update_state

        query = {
            "_id": session_id,
            "type": "warrior_setup",
            "guild_id": int(guild_id),
            "user_id": int(member_id(discord_id)),
            "recruiter_id": int(member_id(actor_id)),
            "nickname_setup.nonce": nonce,
            "nickname_setup.step": "preview",
        }
        result = await update_state(
            self.mongo, query, {"$set": {"nickname_setup.step": "applying"}}
        )
        return bool(result.matched_count)

    async def finish_preview(self, session_id, nonce, status):
        from utils.component_state import update_state

        if status not in ("saved", "needs_attention"):
            raise ValueError("Invalid nickname receipt status.")
        result = await update_state(
            self.mongo,
            {
                "_id": session_id,
                "nickname_setup.nonce": nonce,
                "nickname_setup.step": "applying",
            },
            {"$set": {"nickname_setup.step": status}},
        )
        return bool(result.matched_count)

    async def preview_current(self, session_id, nonce):
        from utils.component_state import get_state

        row = await get_state(self.mongo, session_id)
        return bool(row and (row.get("nickname_setup") or {}).get("nonce") == nonce)

    async def write(self, discord_id, fields, **options):
        await self.ensure_indexes()
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
        await self.ensure_indexes()
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
        left_at=None,
        membership_at=None,
        preserve_edit_timestamp=False,
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
            and current.get("source") in ("warrior", "staff", "nickname_import")
        ):
            return current
        checked = profile_fields(fields, source=source)
        at = now or datetime.now(timezone.utc)
        row = dict(
            checked,
            _id=key,
            discord_id=key,
            source=source,
            updated_by=actor,
            updated_at=(
                current.get("updated_at", at)
                if preserve_edit_timestamp and current
                else at
            ),
            revision=expected_revision + 1,
            left_at=left_at,
            membership_at=membership_at or at,
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

    async def membership(self, discord_id, *, left_at, observed_at=None):
        """Membership events update existing profiles only, through the same CAS writer."""
        import asyncio
        from utils.member_profile_leases import ProfileBusy

        observed_at = observed_at or datetime.now(timezone.utc)
        for _ in range(65):
            current = await self.get(discord_id)
            if current is None:
                return current
            prior = current.get("membership_at")
            if prior is not None and prior.tzinfo is None:
                prior = prior.replace(tzinfo=timezone.utc)
            if prior is not None and prior >= observed_at:
                return current
            try:
                return await self.write(
                    discord_id,
                    current,
                    expected_revision=current["revision"],
                    updated_by=current["updated_by"],
                    source=current["source"],
                    left_at=left_at,
                    membership_at=observed_at,
                    preserve_edit_timestamp=True,
                )
            except (ProfileConflict, ProfileBusy):
                await asyncio.sleep(1)
                continue
        raise ProfileConflict("Member membership changed concurrently.")

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from utils import gauntlet_help as state
from extensions.tasks import gauntlet_help as task


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row.get(key) or datetime.min.replace(tzinfo=timezone.utc), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, length=None):
        return [dict(row) for row in self.rows[:length]] if length else [dict(row) for row in self.rows]


def matches(row, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(row, part) for part in expected):
                return False
        elif key == "$and":
            if not all(matches(row, part) for part in expected):
                return False
        elif isinstance(expected, dict):
            actual = row.get(key)
            for op, value in expected.items():
                if op == "$lt" and not (actual is not None and actual < value):
                    return False
                if op == "$lte" and not (actual is not None and actual <= value):
                    return False
                if op == "$gte" and not (actual is not None and actual >= value):
                    return False
                if op == "$ne" and actual == value:
                    return False
                if op == "$in" and actual not in value:
                    return False
                if op == "$nin" and actual in value:
                    return False
        elif row.get(key) != expected:
            return False
    return True


class Collection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query):
        return next((dict(row) for row in self.rows.values() if matches(row, query)), None)

    def find(self, query):
        return Cursor([dict(row) for row in self.rows.values() if matches(row, query)])

    async def insert_one(self, row):
        from pymongo.errors import DuplicateKeyError
        if row["_id"] in self.rows:
            raise DuplicateKeyError("duplicate")
        self.rows[row["_id"]] = dict(row)

    async def update_one(self, query, update, upsert=False):
        key = next((key for key, row in self.rows.items() if matches(row, query)), None)
        if key is None and not upsert:
            return SimpleNamespace(matched_count=0)
        if key is None:
            key = query["_id"]
            self.rows[key] = {"_id": key, **update.get("$setOnInsert", {})}
        row = self.rows[key]
        row.update(update.get("$set", {}))
        for field, value in update.get("$max", {}).items():
            if field not in row or row[field] < value:
                row[field] = value
        for field in update.get("$unset", {}):
            row.pop(field, None)
        return SimpleNamespace(matched_count=1)

    async def update_many(self, query, update):
        for row in self.rows.values():
            if matches(row, query):
                row["due_at"] = row["advanced_at"] + timedelta(minutes=update[0]["$set"]["due_at"]["$dateAdd"]["amount"])
                row.update({k: v for k, v in update[0]["$set"].items() if k != "due_at"})
                for field in update[-1].get("$unset", []):
                    row.pop(field, None)

    async def find_one_and_update(self, query, update, return_document=None):
        found = await self.find_one(query)
        if found is None:
            return None
        await self.update_one({"_id": found["_id"]}, update)
        return await self.find_one({"_id": found["_id"]})

    async def delete_one(self, query):
        row = await self.find_one(query)
        if row:
            self.rows.pop(row["_id"], None)


class Rest:
    def __init__(self, *, roles=()):
        self.roles = roles
        self.created = []
        self.deleted = []
        self.message_id = 900
        self.history = []
        self.missing_messages = set()

    async def fetch_channel(self, channel_id):
        return SimpleNamespace(id=channel_id, guild_id=task.GUILD_ID, last_message_id=self.history[0].id if self.history else None)

    async def fetch_member(self, guild_id, user_id):
        return SimpleNamespace(role_ids=self.roles)

    async def create_message(self, **kwargs):
        self.created.append(kwargs)
        self.message_id += 1
        message = SimpleNamespace(id=self.message_id, author=SimpleNamespace(is_bot=True, id=42),
                                  created_at=datetime.now(timezone.utc), components=kwargs["components"])
        self.history.insert(0, message)
        return message

    async def fetch_message(self, channel_id, message_id):
        if message_id in self.missing_messages:
            import hikari
            raise hikari.NotFoundError(url="https://discord.test", headers={}, raw_body="missing")
        return next((m for m in self.history if m.id == message_id), SimpleNamespace(id=message_id))

    async def delete_message(self, channel_id, message_id):
        self.deleted.append((channel_id, message_id))

    def fetch_messages(self, channel_id):
        history = self.history
        class Messages:
            def limit(self, count):
                self.count = count
                return self
            def __aiter__(self):
                async def values():
                    for message in history[:self.count]:
                        yield message
                return values()
        return Messages()


@pytest.fixture
def db():
    return SimpleNamespace(bot_config=Collection(), tickets=Collection(), button_store=Collection())


def test_settings_and_stage_monotonic(db):
    async def run():
        assert await state.get_settings(db, task.GUILD_ID) == {"reminder_minutes": 30, "enabled": True}
        with pytest.raises(ValueError):
            await state.save_settings(db, task.GUILD_ID, 0, 3)
        await state.save_settings(db, task.GUILD_ID, 45, 3)
        await state.record_progress(db, task.GUILD_ID, 7, 2)
        first = await db.bot_config.find_one({"_id": state.progress_id(task.GUILD_ID, 7)})
        await state.record_progress(db, task.GUILD_ID, 7, 1)
        assert (await db.bot_config.find_one({"_id": first["_id"]}))["due_at"] == first["due_at"]
        await state.record_progress(db, task.GUILD_ID, 7, 3)
        assert (await db.bot_config.find_one({"_id": first["_id"]}))["stage"] == 3
        await state.complete_progress(db, task.GUILD_ID, 7)
        await state.record_progress(db, task.GUILD_ID, 7, 4)
        assert (await db.bot_config.find_one({"_id": first["_id"]}))["status"] == "complete"
    asyncio.run(run())


def test_reminder_one_shot_mentions_only_recruit_and_deletes_after_ten_minutes(db):
    async def run():
        bot = SimpleNamespace(rest=Rest(roles=(task.STAGE_ROLES[0],)))
        await state.record_progress(db, task.GUILD_ID, 7, 1)
        row = db.bot_config.rows[state.progress_id(task.GUILD_ID, 7)]
        row["due_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
        now = datetime.now(timezone.utc)
        await task._sweep_progress(bot, db, {"enabled": True}, now)
        assert len(bot.rest.created) == 1
        sent = bot.rest.created[0]
        assert sent["user_mentions"] == [7]
        assert sent["role_mentions"] is False
        assert f"<@&{task.RECRUIT_ROLE_ID}>" in sent["components"][0].components[0].content or f"<@&{task.RECRUIT_ROLE_ID}>" in sent["components"][0].components[1].content
        await task._sweep_progress(bot, db, {"enabled": True}, now + timedelta(hours=1))
        assert len(bot.rest.created) == 1
        await task._drain_deletes(bot, db, now + timedelta(minutes=11))
        assert bot.rest.deleted == [(task.HELP_CHANNEL_ID, 901)]
    asyncio.run(run())


def test_next_role_and_existing_ticket_suppress_reminder(db):
    async def run():
        now = datetime.now(timezone.utc)
        await state.record_progress(db, task.GUILD_ID, 8, 1)
        db.bot_config.rows[state.progress_id(task.GUILD_ID, 8)]["due_at"] = now - timedelta(minutes=1)
        bot = SimpleNamespace(rest=Rest(roles=(task.STAGE_ROLES[1],)))
        await task._sweep_progress(bot, db, {"enabled": True}, now)
        assert bot.rest.created == []
        assert db.bot_config.rows[state.progress_id(task.GUILD_ID, 8)]["stage"] == 2
        await state.record_progress(db, task.GUILD_ID, 9, 4)
        last = db.bot_config.rows[state.progress_id(task.GUILD_ID, 9)]
        last["due_at"] = now - timedelta(minutes=1)
        db.tickets.rows["ticket"] = {"_id": "ticket", "type": "ticket", "guild_id": task.GUILD_ID,
                                      "user_id": 9, "ticket_type": "main", "status": "open"}
        await task._sweep_progress(bot, db, {"enabled": True}, now)
        assert bot.rest.created == []
        assert last["status"] == "complete"
    asyncio.run(run())


def test_deleted_sticky_is_recreated_without_new_human_activity(db):
    async def run():
        now = datetime.now(timezone.utc)
        rest = Rest()
        rest.missing_messages.add(123)
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=42))
        db.bot_config.rows[state.settings_id(task.GUILD_ID)] = {
            "_id": state.settings_id(task.GUILD_ID), "enabled": True,
            "sticky_message_id": 123, "sticky_posted_at": now - timedelta(minutes=2),
            "last_human_at": now - timedelta(hours=2),
        }
        await task._sticky(bot, db, {"enabled": True}, now)
        assert len(rest.created) == 1
        assert db.bot_config.rows[state.settings_id(task.GUILD_ID)]["sticky_message_id"] == 901
    asyncio.run(run())


def test_unknown_reminder_is_recovered_and_cleanup_queued(db):
    async def run():
        now = datetime.now(timezone.utc)
        rest = Rest()
        rest.history = [SimpleNamespace(id=555, author=SimpleNamespace(is_bot=True, id=42),
                                        created_at=now, components=task._reminder_components(7, 2))]
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=42))
        await state.record_progress(db, task.GUILD_ID, 7, 2)
        row = db.bot_config.rows[state.progress_id(task.GUILD_ID, 7)]
        row.update(status="send_unknown", claim_token="x", send_started_at=now - timedelta(seconds=1))
        await task._reconcile_unknown(bot, db, now)
        assert row["status"] == "reminded"
        assert row["message_id"] == 555
        assert "gauntlet_help_delete:" + str(task.GUILD_ID) + ":555" in db.bot_config.rows
        await task._sweep_progress(bot, db, {"enabled": True}, now + timedelta(hours=1))
        assert rest.created == []
    asyncio.run(run())


def test_disabled_stops_posts_but_still_deletes_due_reminders(db):
    async def run():
        now = datetime.now(timezone.utc)
        rest = Rest()
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=42))
        db.bot_config.rows[state.settings_id(task.GUILD_ID)] = {
            "_id": state.settings_id(task.GUILD_ID), "enabled": False,
        }
        await task._queue_delete(db, 123, now - timedelta(minutes=1))
        await task.sweep_once(bot, db, now=now)
        assert rest.created == []
        assert rest.deleted == [(task.HELP_CHANNEL_ID, 123)]
    asyncio.run(run())


def test_recovery_ignores_other_bots_even_with_matching_text(db):
    async def run():
        now = datetime.now(timezone.utc)
        rest = Rest()
        rest.history = [SimpleNamespace(id=556, author=SimpleNamespace(is_bot=True, id=999),
                                        created_at=now - timedelta(minutes=11),
                                        components=task._reminder_components(7, 2))]
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=42))
        await task._reconcile_unknown(bot, db, now)
        assert not any(key.startswith("gauntlet_help_delete:") for key in db.bot_config.rows)
    asyncio.run(run())


def test_settings_change_retimes_and_invalidates_claim(db):
    async def run():
        await state.record_progress(db, task.GUILD_ID, 7, 1)
        row = db.bot_config.rows[state.progress_id(task.GUILD_ID, 7)]
        original = row["due_at"]
        row.update(status="checking", claim_token="old", lease_until=datetime.now(timezone.utc) + timedelta(minutes=5))
        await state.save_settings(db, task.GUILD_ID, 60, 3)
        assert row["status"] == "waiting"
        assert "claim_token" not in row and "lease_until" not in row
        assert row["due_at"] == original + timedelta(minutes=30)
    asyncio.run(run())


def test_old_sticky_deletion_receipt_survives_crash(db):
    async def run():
        now = datetime.now(timezone.utc)
        key = state.settings_id(task.GUILD_ID)
        db.bot_config.rows[key] = {"_id": key, "enabled": True, "sticky_message_id": 222,
                                   "pending_sticky_delete_id": 111}
        rest = Rest()
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=42))
        await task._drain_pending_sticky(db, now)
        assert "pending_sticky_delete_id" not in db.bot_config.rows[key]
        await task._drain_deletes(bot, db, now)
        assert rest.deleted == [(task.HELP_CHANNEL_ID, 111)]
    asyncio.run(run())


def test_revoked_stage_role_stops_reminder(db):
    async def run():
        now = datetime.now(timezone.utc)
        await state.record_progress(db, task.GUILD_ID, 7, 1)
        row = db.bot_config.rows[state.progress_id(task.GUILD_ID, 7)]
        row["due_at"] = now - timedelta(minutes=1)
        rest = Rest(roles=())
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=42))
        await task._sweep_progress(bot, db, {"enabled": True}, now)
        assert rest.created == []
        assert row["status"] == "role_revoked"
    asyncio.run(run())


def test_start_posts_one_sticky_and_bot_activity_does_not_move_it(db):
    async def run():
        now = datetime.now(timezone.utc)
        rest = Rest()
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=42))
        await task.sweep_once(bot, db, now=now)
        assert len(rest.created) == 1
        sticky = db.bot_config.rows[state.settings_id(task.GUILD_ID)]
        assert sticky["sticky_message_id"] == 901
        await task.sweep_once(bot, db, now=now + timedelta(minutes=31))
        assert len(rest.created) == 1
    asyncio.run(run())

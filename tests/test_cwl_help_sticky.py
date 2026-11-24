"""Mocked Discord only: sticky scheduling, durable outcomes and destinations."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.tasks import cwl_help, gauntlet_help
from extensions.tasks.sticky_transport import DiscordStickyTransport
from tests.test_gauntlet_help import Collection
from utils.sticky_message import StickyMessage, StickyTarget

NOW = datetime(2030, 1, 10, 12, tzinfo=timezone.utc)
MAIN, LAZY = cwl_help.CHANNEL_IDS


def message(message_id, at, *, bot=False):
    return SimpleNamespace(id=message_id, created_at=at, author=SimpleNamespace(is_bot=bot, id=42 if bot else 7))


class Rest:
    def __init__(self):
        self.history = {MAIN: [], LAZY: [], gauntlet_help.HELP_CHANNEL_ID: []}
        self.created = []
        self.deleted = []
        self.events = []
        self.next_id = 1000
        self.fail_create = False
        self.fail_delete = False
        self.fail_history = False
        self.wrong_channel = None
        self.wrong_guild = None

    async def fetch_channel(self, channel_id):
        return SimpleNamespace(
            id=self.wrong_channel if self.wrong_channel is not None else channel_id,
            guild_id=self.wrong_guild if self.wrong_guild is not None else cwl_help.GUILD_ID,
            last_message_id=self.history[channel_id][0].id if self.history[channel_id] else None,
        )

    def fetch_messages(self, channel_id):
        rest = self
        class Messages:
            def limit(self, count):
                self.count = count
                return self

            def __aiter__(self):
                async def values():
                    if rest.fail_history:
                        raise RuntimeError("history unavailable")
                    for value in rest.history[channel_id][:self.count]:
                        yield value
                return values()
        return Messages()

    async def fetch_message(self, channel_id, message_id):
        for value in self.history[channel_id]:
            if value.id == message_id:
                return value
        raise hikari.NotFoundError(url="https://discord.test", headers={}, raw_body="missing")

    async def create_message(self, **kwargs):
        self.created.append(kwargs)
        self.events.append(("create", kwargs["channel"]))
        if self.fail_create:
            raise TimeoutError("accepted outcome unknown")
        self.next_id += 1
        value = message(self.next_id, NOW, bot=True)
        self.history[kwargs["channel"]].insert(0, value)
        return value

    async def delete_message(self, channel_id, message_id):
        self.events.append(("delete", message_id))
        if self.fail_delete:
            raise RuntimeError("delete unavailable")
        self.deleted.append((channel_id, message_id))
        self.history[channel_id] = [value for value in self.history[channel_id] if value.id != message_id]


def fixture(channel=MAIN):
    mongo = SimpleNamespace(bot_config=Collection())
    rest = Rest()
    bot = SimpleNamespace(rest=rest)
    sticky = cwl_help.STICKIES[channel] if channel in cwl_help.STICKIES else gauntlet_help.STICKY
    transport = DiscordStickyTransport(bot, sticky.target, cwl_help._sticky_components)
    return mongo, rest, bot, sticky, transport


def seed(mongo, rest, sticky, *, human_at=NOW - timedelta(minutes=31), posted_at=NOW - timedelta(hours=2), previous=100):
    mongo.bot_config.rows[sticky.target.key] = {
        "_id": sticky.target.key, "guild_id": cwl_help.GUILD_ID,
        "sticky_state": "posted", "sticky_message_id": previous,
        "sticky_posted_at": posted_at, "last_human_at": human_at,
    }
    rest.history[sticky.target.channel_id] = [message(200, human_at), message(previous, posted_at, bot=True)]


def test_first_post_after_human_quiet_has_exact_gold_components_and_no_mentions():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        rest.history[MAIN] = [message(20, NOW - timedelta(minutes=30))]
        await sticky.refresh(transport, mongo, NOW)
        assert len(rest.created) == 1
        call = rest.created[0]
        assert call["channel"] == MAIN
        assert call["role_mentions"] is call["user_mentions"] is call["mentions_everyone"] is False
        assert call["flags"] & hikari.MessageFlag.SUPPRESS_NOTIFICATIONS
        container = call["components"][0].build()[0]
        assert container["accent_color"] == int(cwl_help.WU_GOLD) == 0xF2B62A
        assert container["components"] == [
            {"type": 10, "content": "### CWL Signup Help"},
            {"type": 14, "divider": True, "spacing": 1},
            {"type": 10, "content": "If you need help with signing up for CWL or anything else about the event, ask your question here. Ping <@&1574854005417316483> and they will get with you as soon as possible."},
        ]
        assert rest.deleted == []
    asyncio.run(run())


def test_first_post_waits_thirty_minutes_if_no_human_history():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        await sticky.refresh(transport, mongo, NOW)
        await sticky.refresh(transport, mongo, NOW + timedelta(minutes=29))
        assert not rest.created
        await sticky.refresh(transport, mongo, NOW + timedelta(minutes=30))
        assert len(rest.created) == 1
    asyncio.run(run())


def test_newest_sticky_and_bot_only_burial_do_not_repost():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky, human_at=NOW - timedelta(hours=3))
        rest.history[MAIN] = [rest.history[MAIN][-1]]
        await sticky.refresh(transport, mongo, NOW)
        rest.history[MAIN].insert(0, message(300, NOW - timedelta(minutes=40), bot=True))
        await sticky.refresh(transport, mongo, NOW)
        assert not rest.created
        assert not rest.deleted
    asyncio.run(run())


def test_buried_sticky_waits_then_creates_before_deleting_only_stored_previous():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky, human_at=NOW - timedelta(minutes=29))
        await sticky.refresh(transport, mongo, NOW)
        assert not rest.created
        await sticky.refresh(transport, mongo, NOW + timedelta(minutes=1))
        assert rest.deleted == []
        await sticky.drain_deletes(transport, mongo, NOW + timedelta(minutes=1))
        assert rest.events == [("create", MAIN), ("delete", 100)]
        assert rest.deleted == [(MAIN, 100)]
        assert any(value.id == 200 for value in rest.history[MAIN])
    asyncio.run(run())


def test_history_catches_human_activity_missed_while_offline():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        rest.history[MAIN].insert(0, message(300, NOW - timedelta(minutes=2)))
        await sticky.refresh(transport, mongo, NOW)
        assert not rest.created
        assert mongo.bot_config.rows[sticky.target.key]["last_human_at"] == NOW - timedelta(minutes=2)
    asyncio.run(run())


@pytest.mark.parametrize("quiet_minutes, expected_posts", [(30, 1), (2, 0)])
def test_restart_reads_history_before_bot_only_burial_gate(quiet_minutes, expected_posts):
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky, human_at=NOW - timedelta(hours=3))
        # Saved activity predates the sticky; this human message happened while
        # the gateway worker was offline and was never written into its state.
        latest = NOW - timedelta(minutes=quiet_minutes)
        rest.history[MAIN] = [message(300, latest), message(100, NOW - timedelta(hours=2), bot=True)]
        await sticky.refresh(transport, mongo, NOW)
        assert len(rest.created) == expected_posts
        assert mongo.bot_config.rows[sticky.target.key]["last_human_at"] == latest
    asyncio.run(run())


def test_missing_sticky_reposts_only_after_human_quiet():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky, human_at=NOW - timedelta(minutes=1))
        rest.history[MAIN].pop()
        await sticky.refresh(transport, mongo, NOW)
        assert not rest.created
        await sticky.refresh(transport, mongo, NOW + timedelta(minutes=29))
        assert len(rest.created) == 1
    asyncio.run(run())


@pytest.mark.parametrize("state", ["posting", "unknown"])
def test_restart_never_retries_unknown_or_inflight_create(state):
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        mongo.bot_config.rows[sticky.target.key]["sticky_state"] = state
        restarted = StickyMessage(sticky.target, quiet=timedelta(minutes=30))
        await restarted.refresh(transport, mongo, NOW)
        assert not rest.created
    asyncio.run(run())


def test_create_timeout_records_unknown_and_preserves_previous():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        rest.fail_create = True
        await sticky.refresh(transport, mongo, NOW)
        assert mongo.bot_config.rows[sticky.target.key]["sticky_state"] == "unknown"
        rest.fail_create = False
        await sticky.refresh(transport, mongo, NOW + timedelta(hours=1))
        assert len(rest.created) == 1
        assert not rest.deleted
        assert mongo.bot_config.rows[sticky.target.key]["sticky_message_id"] == 100
    asyncio.run(run())


def test_receipt_failure_keeps_posting_intent_and_does_not_duplicate():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        update = mongo.bot_config.update_one
        async def fail_receipt(query, changes, **kwargs):
            if changes.get("$set", {}).get("sticky_state") == "posted":
                raise RuntimeError("receipt unavailable")
            return await update(query, changes, **kwargs)
        mongo.bot_config.update_one = fail_receipt
        with pytest.raises(RuntimeError):
            await sticky.refresh(transport, mongo, NOW)
        mongo.bot_config.update_one = update
        await sticky.refresh(transport, mongo, NOW + timedelta(hours=1))
        assert len(rest.created) == 1
        assert not rest.deleted
        assert mongo.bot_config.rows[sticky.target.key]["sticky_state"] == "posting"
    asyncio.run(run())


def test_concurrent_sweeps_claim_one_create():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        await asyncio.gather(sticky.refresh(transport, mongo, NOW), sticky.refresh(transport, mongo, NOW))
        assert len(rest.created) == 1
    asyncio.run(run())


def test_delete_failure_is_durable_and_restart_retries_only_stored_id():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        await sticky.refresh(transport, mongo, NOW)
        rest.fail_delete = True
        await sticky.drain_deletes(transport, mongo, NOW)
        key = sticky.target.delete_key(100)
        assert mongo.bot_config.rows[key]["attempts"] == 1
        rest.fail_delete = False
        await StickyMessage(sticky.target, quiet=timedelta(minutes=30)).drain_deletes(transport, mongo, NOW + timedelta(minutes=2))
        assert rest.deleted == [(MAIN, 100)]
        assert key not in mongo.bot_config.rows
    asyncio.run(run())


@pytest.mark.parametrize("field, value", [("wrong_channel", LAZY), ("wrong_guild", 123), ("wrong_channel", "invalid"), ("wrong_guild", None)])
def test_invalid_destination_prevents_posts_and_deletes(field, value):
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        # None is valid in the mock, so use a malformed None guild explicitly.
        if value is None:
            rest.fetch_channel = AsyncMock(return_value=SimpleNamespace(id=MAIN, guild_id=None))
        else:
            setattr(rest, field, value)
        before = {key: dict(row) for key, row in mongo.bot_config.rows.items()}
        try:
            await sticky.refresh(transport, mongo, NOW)
            await sticky.drain_deletes(transport, mongo, NOW)
        except (ValueError, TypeError):
            pass
        assert not rest.created and not rest.deleted
        assert mongo.bot_config.rows == before
    asyncio.run(run())


def test_history_failure_is_not_quiet_permission():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        rest.fail_history = True
        with pytest.raises(RuntimeError):
            await sticky.refresh(transport, mongo, NOW)
        assert not rest.created and not rest.deleted
    asyncio.run(run())


def test_cwl_channels_and_gauntlet_state_are_independent():
    async def run():
        mongo, rest, bot, sticky, _ = fixture()
        for channel in (MAIN, LAZY):
            rest.history[channel] = [message(channel + 1, NOW - timedelta(hours=1))]
        gauntlet_key = gauntlet_help.STICKY.target.key
        mongo.bot_config.rows[gauntlet_key] = {"_id": gauntlet_key, "sticky_state": "unknown", "sticky_message_id": 333}
        gauntlet_before = dict(mongo.bot_config.rows[gauntlet_key])
        await cwl_help.sweep_once(bot, mongo, now=NOW)
        assert [call["channel"] for call in rest.created] == [MAIN, LAZY]
        assert mongo.bot_config.rows[gauntlet_key] == gauntlet_before
        main_before = dict(mongo.bot_config.rows[sticky.target.key])
        await cwl_help.STICKIES[LAZY].note_human(mongo, NOW)
        assert mongo.bot_config.rows[sticky.target.key] == main_before
        assert gauntlet_help.STICKY.target.key == f"gauntlet_help:{cwl_help.GUILD_ID}"
        assert gauntlet_help.STICKY.target.delete_key(22) == f"gauntlet_help_delete:{cwl_help.GUILD_ID}:22"
        assert not gauntlet_help.STICKY.target.require_initial_quiet
        assert not gauntlet_help.STICKY.target.require_missing_quiet
    asyncio.run(run())


def test_bot_and_foreign_events_do_not_record_human_activity():
    async def run():
        mongo, _, _, sticky, _ = fixture()
        for guild, channel, is_bot in [(123, MAIN, False), (cwl_help.GUILD_ID, 1072714594625257502, False), (cwl_help.GUILD_ID, MAIN, True)]:
            event = SimpleNamespace(guild_id=guild, channel_id=channel, message=message(30, NOW, bot=is_bot))
            await cwl_help.on_help_message(event, mongo)
        assert not mongo.bot_config.rows
        event = SimpleNamespace(guild_id=cwl_help.GUILD_ID, channel_id=MAIN, message=message(31, NOW))
        await cwl_help.on_help_message(event, mongo)
        assert mongo.bot_config.rows[sticky.target.key]["last_human_at"] == NOW
    asyncio.run(run())


def test_quiet_interval_is_a_parameter():
    async def run():
        mongo, rest, bot, sticky, _ = fixture()
        seed(mongo, rest, sticky, human_at=NOW - timedelta(minutes=10))
        faster = StickyMessage(StickyTarget(cwl_help.GUILD_ID, MAIN), quiet=timedelta(minutes=5))
        await faster.refresh(DiscordStickyTransport(bot, faster.target, cwl_help._sticky_components), mongo, NOW)
        assert len(rest.created) == 1
    asyncio.run(run())


def test_human_activity_before_claim_invalidates_the_candidate():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        update = mongo.bot_config.update_one
        async def human_arrives(query, changes, **kwargs):
            if changes.get("$set", {}).get("sticky_state") == "posting":
                mongo.bot_config.rows[sticky.target.key]["last_human_at"] = NOW
            return await update(query, changes, **kwargs)
        mongo.bot_config.update_one = human_arrives
        await sticky.refresh(transport, mongo, NOW)
        assert not rest.created and not rest.deleted
    asyncio.run(run())


def test_one_channel_permission_failure_does_not_stop_the_other():
    async def run():
        mongo, rest, bot, _, _ = fixture()
        fetch = rest.fetch_channel
        async def denied(channel_id):
            if channel_id == MAIN:
                raise hikari.ForbiddenError(url="https://discord.test", headers={}, raw_body="denied")
            return await fetch(channel_id)
        rest.fetch_channel = denied
        rest.history[LAZY] = [message(20, NOW - timedelta(hours=1))]
        await cwl_help.sweep_once(bot, mongo, now=NOW)
        assert [call["channel"] for call in rest.created] == [LAZY]
        assert cwl_help.STICKIES[MAIN].target.key not in mongo.bot_config.rows
    asyncio.run(run())


def test_cancellation_after_claim_remains_inflight_and_never_retries():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky)
        transport.create = AsyncMock(side_effect=asyncio.CancelledError)
        with pytest.raises(asyncio.CancelledError):
            await sticky.refresh(transport, mongo, NOW)
        assert mongo.bot_config.rows[sticky.target.key]["sticky_state"] == "posting"
        await sticky.refresh(transport, mongo, NOW + timedelta(hours=1))
        assert transport.create.call_count == 1
        assert not rest.deleted
    asyncio.run(run())


@pytest.mark.parametrize("channel", [MAIN, gauntlet_help.HELP_CHANNEL_ID])
@pytest.mark.parametrize("created_at_available", [True, False])
def test_slow_create_does_not_count_human_before_actual_sticky_as_later_activity(channel, created_at_available):
    async def run():
        mongo, rest, bot, original, _ = fixture(channel)
        posted_at = NOW + timedelta(minutes=10)
        sticky = StickyMessage(original.target, quiet=original.quiet, clock=lambda: posted_at)
        transport = DiscordStickyTransport(
            bot, sticky.target, cwl_help._sticky_components,
            history_reader=gauntlet_help._latest_human_at if channel == gauntlet_help.HELP_CHANNEL_ID else None,
        )
        seed(mongo, rest, sticky)
        create = rest.create_message
        async def slow_create(**kwargs):
            during = NOW + timedelta(minutes=5)
            rest.history[channel].insert(0, message(400, during))
            await sticky.note_human(mongo, during)
            value = await create(**kwargs)
            value.created_at = posted_at if created_at_available else None
            return value
        rest.create_message = slow_create
        await sticky.refresh(transport, mongo, NOW)
        assert mongo.bot_config.rows[sticky.target.key]["sticky_posted_at"] == posted_at
        rest.history[channel].insert(0, message(500, NOW + timedelta(minutes=50), bot=True))
        await sticky.refresh(transport, mongo, NOW + timedelta(hours=1))
        assert len(rest.created) == 1
    asyncio.run(run())


def test_restart_pages_past_one_hundred_bots_to_find_recent_human():
    async def run():
        mongo, rest, _, sticky, transport = fixture()
        seed(mongo, rest, sticky, human_at=NOW - timedelta(hours=3))
        rest.history[MAIN] = [message(1000 + i, NOW - timedelta(seconds=i), bot=True) for i in range(101)]
        rest.history[MAIN] += [message(300, NOW - timedelta(minutes=2)), message(100, NOW - timedelta(hours=2), bot=True)]
        await sticky.refresh(transport, mongo, NOW)
        assert not rest.created
        assert mongo.bot_config.rows[sticky.target.key]["last_human_at"] == NOW - timedelta(minutes=2)
    asyncio.run(run())


def test_history_bound_with_only_bots_is_unknown_not_quiet():
    async def run():
        mongo, rest, bot, sticky, _ = fixture()
        seed(mongo, rest, sticky)
        rest.history[MAIN] = [message(1000 + i, NOW - timedelta(seconds=i), bot=True) for i in range(101)]
        transport = DiscordStickyTransport(bot, sticky.target, cwl_help._sticky_components, history_limit=100)
        before = {key: dict(row) for key, row in mongo.bot_config.rows.items()}
        with pytest.raises(RuntimeError, match="quiet is unknown"):
            await sticky.refresh(transport, mongo, NOW)
        assert not rest.created and not rest.deleted
        assert mongo.bot_config.rows == before
    asyncio.run(run())

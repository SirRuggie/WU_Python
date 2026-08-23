import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from extensions.events.channel import ticket_channel_monitor as monitor
from tests import test_ticket_channel_monitor as support


BOT_ID = 900


class RecordingRest:
    def __init__(self, *, accepted_response_loss_at=None):
        self.accepted_response_loss_at = accepted_response_loss_at
        self.send_calls = 0
        self.messages = []

    async def create_message(self, **kwargs):
        self.send_calls += 1
        self.messages.append(SimpleNamespace(
            channel_id=int(kwargs["channel"]),
            author=SimpleNamespace(id=BOT_ID),
            content=str(kwargs.get("content", "") or ""),
            components=tuple(kwargs.get("components", ()) or ()),
        ))
        if self.send_calls == self.accepted_response_loss_at:
            raise RuntimeError("Discord accepted the POST but lost its response")

    def fetch_messages(self, channel_id):
        return support._OnlineHistory([
            message
            for message in self.messages
            if message.channel_id == int(channel_id)
        ])


def _opening_fixture(monkeypatch, *, ticket_type="fwa", channel_id=601):
    now = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)
    ticket = support._committed_ticket(channel_id)
    ticket["ticket_type"] = ticket_type
    plan = monitor._delivery_message_plan(
        user_id=ticket["user_id"],
        ticket_type=ticket_type,
        recruiter_role=777,
        guild_icon_url=None,
    )
    document = monitor.build_automation_document(
        channel_id=channel_id,
        thread_id=ticket["thread_id"],
        guild_id=ticket["guild_id"],
        user_id=ticket["user_id"],
        ticket_type=ticket_type,
        now=now,
        initial_delivery={
            "status": "processing",
            "lease_owner": "opening-owner",
            "lease_until": now + monitor.DELIVERY_LEASE,
            "message_plan": plan,
        },
    )
    automation = support._RecoveryAutomation([document], now)
    mongo = SimpleNamespace(ticket_automation_state=automation)
    ticket_state = support._install_ticket_lookup(monkeypatch, ticket)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)

    async def no_delay(_delay):
        return None

    monkeypatch.setattr(monitor.asyncio, "sleep", no_delay)
    return mongo, automation, ticket_state, plan, deepcopy(document)


def _bot(rest):
    return SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=BOT_ID))


def _expected_messages(plan, ticket_type):
    messages = [
        plan["welcome_content"],
        "",
        plan["staff_privacy_content"],
        plan["staff_how_heard_content"],
        plan["staff_hook_content"],
    ]
    if ticket_type == "fwa":
        messages.append(plan["staff_fwa_donation_content"])
    return messages


@pytest.mark.parametrize(
    ("ticket_type", "expected_count"),
    [("main", 5), ("fwa", 6)],
)
def test_opening_messages_are_exact_and_ordered(
    monkeypatch, ticket_type, expected_count,
):
    mongo, automation, _ticket, plan, document = _opening_fixture(
        monkeypatch, ticket_type=ticket_type,
    )
    rest = RecordingRest()

    delivered = asyncio.run(
        monitor.deliver_claimed_automation(rest, mongo, document)
    )

    channel_id = document["channel_id"]
    thread_id = document["thread_id"]
    assert delivered is True
    assert len(rest.messages) == expected_count
    assert [message.channel_id for message in rest.messages] == [
        channel_id,
        channel_id,
        *([thread_id] * (expected_count - 2)),
    ]
    assert [message.content for message in rest.messages] == _expected_messages(
        plan, ticket_type,
    )
    assert rest.messages[1].components
    assert automation.rows[str(channel_id)]["initial_delivery"]["status"] == (
        "complete"
    )


@pytest.mark.parametrize(
    ("failed_call", "failed_step"),
    list(enumerate(monitor.DELIVERY_STEP_FIELDS, start=1)),
)
def test_accepted_response_loss_at_every_step_recovers_without_duplicate(
    monkeypatch, failed_call, failed_step,
):
    mongo, automation, ticket, plan, document = _opening_fixture(monkeypatch)
    rest = RecordingRest(accepted_response_loss_at=failed_call)

    with pytest.raises(monitor.DeliveryPostUncertain):
        asyncio.run(monitor.deliver_claimed_automation(rest, mongo, document))

    assert ticket["opening_post_intent"]["step"] == failed_step
    observed = asyncio.run(monitor._existing_delivery_steps(
        _bot(rest), automation_doc=document, message_plan=plan,
    ))
    asyncio.run(monitor.checkpoint_delivery_history(
        mongo,
        document["channel_id"],
        "opening-owner",
        observed_steps=observed,
    ))
    asyncio.run(monitor._settle_opening_post_intent_after_history(mongo, document))

    resumed = deepcopy(automation.rows[str(document["channel_id"])])
    assert asyncio.run(
        monitor.deliver_claimed_automation(rest, mongo, resumed)
    ) is True

    assert rest.send_calls == 6
    assert len(rest.messages) == 6
    assert [message.content for message in rest.messages] == _expected_messages(
        plan, "fwa",
    )
    assert "opening_post_intent" not in ticket


@pytest.mark.parametrize("terminal_after", range(1, 6))
def test_terminal_transition_between_steps_stops_all_remaining_posts(
    monkeypatch, terminal_after,
):
    mongo, automation, ticket, _plan, document = _opening_fixture(monkeypatch)
    rest = RecordingRest()
    original_clear = monitor.store.clear_opening_post_intent
    clears = 0

    async def terminal_after_clear(*args, **kwargs):
        nonlocal clears
        cleared = await original_clear(*args, **kwargs)
        if cleared:
            clears += 1
            if clears == terminal_after:
                ticket["status"] = "denied"
        return cleared

    monkeypatch.setattr(
        monitor.store, "clear_opening_post_intent", terminal_after_clear,
    )

    delivered = asyncio.run(
        monitor.deliver_claimed_automation(rest, mongo, document)
    )

    assert delivered is False
    assert rest.send_calls == terminal_after
    delivery = automation.rows[str(document["channel_id"])]["initial_delivery"]
    assert delivery["status"] == "cancelled"
    assert "opening_post_intent" not in ticket


def test_wrong_author_and_wrong_surface_never_checkpoint_exact_signatures():
    channel_id = 701
    thread_id = 702
    plan = monitor._delivery_message_plan(
        user_id=801,
        ticket_type="fwa",
        recruiter_role=777,
        guild_icon_url=None,
    )
    questionnaire = tuple(monitor._questionnaire_components("fwa", None))

    def message(surface, author, *, content="", components=()):
        return SimpleNamespace(
            channel_id=surface,
            author=SimpleNamespace(id=author),
            content=content,
            components=components,
        )

    rest = RecordingRest()
    rest.messages = [
        message(channel_id, 901, content=plan["welcome_content"]),
        message(channel_id, 901, components=questionnaire),
        message(channel_id, BOT_ID, content=plan["staff_privacy_content"]),
        message(channel_id, BOT_ID, content=plan["staff_how_heard_content"]),
        message(channel_id, BOT_ID, content=plan["staff_hook_content"]),
        message(channel_id, BOT_ID, content=plan["staff_fwa_donation_content"]),
        message(thread_id, BOT_ID, content=plan["welcome_content"]),
        message(thread_id, BOT_ID, components=questionnaire),
        message(thread_id, 901, content=plan["staff_privacy_content"]),
        message(thread_id, 901, content=plan["staff_how_heard_content"]),
        message(thread_id, 901, content=plan["staff_hook_content"]),
        message(thread_id, 901, content=plan["staff_fwa_donation_content"]),
    ]

    observed = asyncio.run(monitor._existing_delivery_steps(
        _bot(rest),
        automation_doc={
            "channel_id": channel_id,
            "thread_id": thread_id,
            "ticket_type": "fwa",
        },
        message_plan=plan,
    ))

    assert observed == {step: False for step in monitor.DELIVERY_STEP_FIELDS}


def test_questionnaire_builder_matches_discord_deserialized_components():
    hikari = monitor.hikari
    components = hikari.components
    logo = (
        "https://res.cloudinary.com/dxmtzuomk/image/upload/"
        "v1752836911/misc_images/WU_Logo.png"
    )

    def media():
        return components.MediaResource(
            resource=hikari.files.URL(logo),
            width=hikari.UNDEFINED,
            height=hikari.UNDEFINED,
            content_type=hikari.UNDEFINED,
            loading_state=hikari.UNDEFINED,
        )

    questions = (
        "1) In-game name & Player Tag\n"
        "2) Age & Timezone. Country name would be good too.\n"
        "3) Do you have multiple accounts?\n"
        "4) If yes to #3, please provide all Player Tags.\n"
        "5) What exactly are you looking for in a Clan?"
    )
    deserialized = [components.ContainerComponent(
        type=hikari.ComponentType.CONTAINER,
        id=7,
        accent_color=hikari.Color(0xEEEEAA),
        is_spoiler=False,
        components=[
            components.SectionComponent(
                type=hikari.ComponentType.SECTION,
                id=4,
                components=[
                    components.TextDisplayComponent(
                        type=hikari.ComponentType.TEXT_DISPLAY,
                        id=2,
                        content="## **Warriors United Main Clan Entry Ticket**",
                    ),
                    components.TextDisplayComponent(
                        type=hikari.ComponentType.TEXT_DISPLAY,
                        id=3,
                        content=questions,
                    ),
                ],
                accessory=components.ThumbnailComponent(
                    type=hikari.ComponentType.THUMBNAIL,
                    id=1,
                    media=media(),
                    description=None,
                    is_spoiler=False,
                ),
            ),
            components.MediaGalleryComponent(
                type=hikari.ComponentType.MEDIA_GALLERY,
                id=5,
                items=[components.MediaGalleryItem(
                    media=media(), description=None, is_spoiler=False,
                )],
            ),
            components.TextDisplayComponent(
                type=hikari.ComponentType.TEXT_DISPLAY,
                id=6,
                content="-# Patience is key! A Recruiter will be with you soon.",
            ),
        ],
    )]

    assert monitor._component_signature(
        monitor._questionnaire_components("main", None)
    ) == monitor._component_signature(deserialized)


def test_checkpoint_success_then_intent_clear_failure_recovers_without_repost(
    monkeypatch,
):
    mongo, automation, ticket, plan, document = _opening_fixture(
        monkeypatch, ticket_type="main",
    )
    rest = RecordingRest()
    original_clear = monitor.store.clear_opening_post_intent
    fail_once = True

    async def clear_fails_once(*args, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            return False
        return await original_clear(*args, **kwargs)

    monkeypatch.setattr(
        monitor.store, "clear_opening_post_intent", clear_fails_once,
    )

    with pytest.raises(RuntimeError, match="could not be cleared after checkpoint"):
        asyncio.run(monitor.deliver_claimed_automation(rest, mongo, document))

    delivery = automation.rows[str(document["channel_id"])]["initial_delivery"]
    assert delivery["welcome_sent"] is True
    assert ticket["opening_post_intent"]["step"] == "welcome_sent"

    observed = asyncio.run(monitor._existing_delivery_steps(
        _bot(rest), automation_doc=document, message_plan=plan,
    ))
    asyncio.run(monitor.checkpoint_delivery_history(
        mongo,
        document["channel_id"],
        "opening-owner",
        observed_steps=observed,
    ))
    asyncio.run(monitor._settle_opening_post_intent_after_history(mongo, document))
    resumed = deepcopy(automation.rows[str(document["channel_id"])])
    assert asyncio.run(
        monitor.deliver_claimed_automation(rest, mongo, resumed)
    ) is True

    assert rest.send_calls == 5
    assert sum(
        message.content == plan["welcome_content"] for message in rest.messages
    ) == 1
    assert "opening_post_intent" not in ticket


def test_markerless_preupgrade_retry_row_is_fenced_upgraded_and_delivered(
    monkeypatch,
):
    now = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)
    ticket = support._committed_ticket(811)
    row = monitor.build_automation_document(
        channel_id=811,
        thread_id=812,
        guild_id=7,
        user_id=911,
        ticket_type="main",
        now=now,
        initial_delivery={"status": "retry"},
    )
    for field in ("kind", "route", "runtime", "guild_id"):
        row.pop(field)
    automation = support._RecoveryAutomation([row], now)
    mongo = SimpleNamespace(
        ticket_automation_state=automation,
        ticket_setup=support._OnlineSetup(),
    )
    rest = support._OnlineDeliveryRest()
    bot = support._online_delivery_bot(rest)
    support._install_ticket_lookup(monkeypatch, ticket)
    monkeypatch.setattr(monitor, "delivery_now", lambda: now)

    async def no_delay(_delay):
        return None

    monkeypatch.setattr(monitor.asyncio, "sleep", no_delay)

    result = asyncio.run(monitor.recover_pending_automation_deliveries(
        bot=bot,
        mongo=mongo,
        only_channel_id=811,
        now=now,
    ))

    assert result["completed"] == 1
    assert result["failed"] == 0
    upgraded = automation.rows["811"]
    assert upgraded["kind"] == "legacy_initial_delivery"
    assert upgraded["route"] == "legacy"
    assert upgraded["runtime"] == "legacy_channel"
    assert upgraded["guild_id"] == 7
    assert len(rest.messages) == 5

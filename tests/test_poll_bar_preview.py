import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands import poll_bar_preview as preview
from extensions.commands.help_catalog import command_paths


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _walk_payload(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_payload(child)


def _built_payload(component):
    payload = component.build()
    return payload[0] if isinstance(payload, tuple) else payload


def _payload_nodes(view):
    return list(_walk_payload([_built_payload(component) for component in view]))


EXPECTED_LINES = {
    "A": (
        "`░░░░░░░░░░` **0%** · 0 votes",
        "`█░░░░░░░░░` **10%** · 10 votes",
        "`██░░░░░░░░` **25%** · 25 votes",
        "`███░░░░░░░` **32%** · 32 votes",
        "`████░░░░░░` **38%** · 38 votes",
        "`█████░░░░░` **50%** · 50 votes",
        "`███████░░░` **67%** · 67 votes",
        "`████████░░` **75%** · 75 votes",
        "`█████████░` **90%** · 90 votes",
        "`██████████` **100%** · 100 votes",
    ),
    "B": (
        "▱▱▱▱▱▱▱▱▱▱ **0%** · 0 votes",
        "▰▱▱▱▱▱▱▱▱▱ **10%** · 10 votes",
        "▰▰▰▱▱▱▱▱▱▱ **25%** · 25 votes",
        "▰▰▰▱▱▱▱▱▱▱ **32%** · 32 votes",
        "▰▰▰▰▱▱▱▱▱▱ **38%** · 38 votes",
        "▰▰▰▰▰▱▱▱▱▱ **50%** · 50 votes",
        "▰▰▰▰▰▰▰▱▱▱ **67%** · 67 votes",
        "▰▰▰▰▰▰▰▰▱▱ **75%** · 75 votes",
        "▰▰▰▰▰▰▰▰▰▱ **90%** · 90 votes",
        "▰▰▰▰▰▰▰▰▰▰ **100%** · 100 votes",
    ),
    "C": (
        "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱ **0%** · 0 votes",
        "▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱ **10%** · 10 votes",
        "▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱ **25%** · 25 votes",
        "▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱ **32%** · 32 votes",
        "▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱ **38%** · 38 votes",
        "▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱ **50%** · 50 votes",
        "▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱ **67%** · 67 votes",
        "▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱ **75%** · 75 votes",
        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱ **90%** · 90 votes",
        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰ **100%** · 100 votes",
    ),
    "D": (
        "░░░░░░░░░░ **0%** · 0 votes",
        "█░░░░░░░░░ **10%** · 10 votes",
        "██▌░░░░░░░ **25%** · 25 votes",
        "███▎░░░░░░ **32%** · 32 votes",
        "███▊░░░░░░ **38%** · 38 votes",
        "█████░░░░░ **50%** · 50 votes",
        "██████▊░░░ **67%** · 67 votes",
        "███████▌░░ **75%** · 75 votes",
        "█████████░ **90%** · 90 votes",
        "██████████ **100%** · 100 votes",
    ),
}


@pytest.mark.parametrize("style", ["A", "B", "C", "D"])
def test_preview_lines_are_exact_for_every_requested_percentage(style):
    assert tuple(
        preview._preview_result_line(style, percent)
        for percent in preview.PREVIEW_PERCENTAGES
    ) == EXPECTED_LINES[style]


def test_preview_rounding_widths_plain_text_and_vote_grammar_are_explicit():
    assert preview._round_half_up(5, 2) == 3
    assert preview._preview_result_line("A", 1, 4).startswith("`██░░░░░░░░`")
    assert preview._preview_result_line("B", 1, 4) == (
        "▰▰▰▱▱▱▱▱▱▱ **25%** · 1 vote"
    )
    assert preview._preview_result_line("C", 3, 4) == (
        "▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱ **75%** · 3 votes"
    )
    assert preview._preview_result_line("D", 1, 4) == (
        "██▌░░░░░░░ **25%** · 1 vote"
    )

    for style in ("B", "C", "D"):
        assert "`" not in preview._preview_result_line(style, 38)
    for percent in preview.PREVIEW_PERCENTAGES:
        c_bar = preview._preview_result_line("C", percent).split(" ", 1)[0]
        d_bar = preview._preview_result_line("D", percent).split(" ", 1)[0]
        assert len(c_bar) == 16
        assert len(d_bar) == 10


@pytest.mark.parametrize("style", ["A", "B", "C", "D"])
def test_preview_card_uses_real_poll_hierarchy_and_stays_within_budgets(style):
    view = preview.build_poll_bar_preview_components(
        style,
        creator_id=preview.OWNER_ID,
        observed_at=NOW,
    )
    container = _built_payload(view[0])
    children = container["components"]
    nodes = _payload_nodes(view)
    text = [node["content"] for node in nodes if "content" in node]
    buttons = [node for node in nodes if "label" in node]
    custom_ids = [str(node["custom_id"]) for node in nodes if "custom_id" in node]

    assert container["accent_color"] == int(preview.GOLD_ACCENT)
    assert text[0].startswith(f"# 📊 {style} · ")
    assert text[1] == (
        "Poll progress-bar phone preview\n"
        "Each result below is an independent poll sample."
    )
    assert text[2:12] == [
        f"**{index}. Result at {percent}%**\n{line}"
        for index, (percent, line) in enumerate(
            zip(preview.PREVIEW_PERCENTAGES, EXPECTED_LINES[style]),
            start=1,
        )
    ]
    assert text[-2] == "100 votes · You can change your vote."
    assert text[-1] == (
        f"-# ⏱️ Closes <t:{int((NOW.timestamp()) + 3600)}:R> · "
        f"<@{preview.OWNER_ID}>"
    )

    option_positions = [
        index for index, child in enumerate(children)
        if str(child.get("content", "")).startswith("**")
    ]
    assert len(option_positions) == 10
    assert all(
        right == left + 2
        for left, right in zip(option_positions, option_positions[1:])
    )
    for position in option_positions[:-1]:
        separator = children[position + 1]
        assert separator["type"] == hikari.ComponentType.SEPARATOR
        assert separator["divider"] is False
        assert separator["spacing"] == hikari.SpacingType.SMALL

    assert len([node for node in nodes if "type" in node]) == 35
    assert len(children) == 29
    assert len(buttons) == 5
    assert all(button["disabled"] is True for button in buttons)
    assert custom_ids and len(custom_ids) == len(set(custom_ids))
    assert all(value.startswith("poll_bar_preview_noop:") for value in custom_ids)
    assert not any(value.startswith("poll_vote:") for value in custom_ids)
    assert all(value.count(":") == 1 and len(value) <= 100 for value in custom_ids)
    assert all(len(str(node["content"])) <= 4000 for node in nodes if "content" in node)
    assert all(len(str(node["label"])) <= 80 for node in buttons)


class _Rest:
    def __init__(self):
        self.dm_users = []
        self.messages = []

    async def create_dm_channel(self, user_id):
        self.dm_users.append(int(user_id))
        return SimpleNamespace(id=700)

    async def create_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(id=701 + len(self.messages))


class _Context:
    def __init__(self, user_id):
        self.user = SimpleNamespace(id=user_id)
        self.deferred = []
        self.responses = []

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


def test_preview_delivery_sends_four_private_v2_cards_and_uses_no_storage():
    rest = _Rest()
    sent = asyncio.run(preview._send_poll_bar_previews(
        SimpleNamespace(rest=rest),
        owner_id=preview.OWNER_ID,
        observed_at=NOW,
    ))

    assert sent == 4
    assert rest.dm_users == [preview.OWNER_ID]
    assert len(rest.messages) == 4
    for (style, _name), message in zip(preview.PREVIEW_STYLES, rest.messages):
        assert message["channel"].id == 700
        assert message["flags"] == hikari.MessageFlag.IS_COMPONENTS_V2
        assert message["user_mentions"] is False
        assert message["role_mentions"] is False
        assert message["mentions_everyone"] is False
        assert message["mentions_reply"] is False
        card_text = "\n".join(
            str(node["content"])
            for node in _payload_nodes(message["components"])
            if "content" in node
        )
        assert card_text.startswith(f"# 📊 {style} · ")


def test_preview_command_enforces_owner_before_any_dm_work():
    denied_rest = _Rest()
    denied = _Context(preview.OWNER_ID + 1)
    command = SimpleNamespace()

    asyncio.run(preview.PollBarPreview.invoke._func(
        command,
        denied,
        bot=SimpleNamespace(rest=denied_rest),
    ))

    assert denied_rest.dm_users == []
    assert denied_rest.messages == []
    assert denied.deferred == []
    assert denied.responses[0][1]["ephemeral"] is True
    assert "owner only" in denied.responses[0][0][0]

    owner_rest = _Rest()
    owner = _Context(preview.OWNER_ID)
    asyncio.run(preview.PollBarPreview.invoke._func(
        command,
        owner,
        bot=SimpleNamespace(rest=owner_rest),
    ))

    assert owner.deferred == [{"ephemeral": True}]
    assert len(owner_rest.messages) == 4
    assert owner.responses[-1][1]["ephemeral"] is True
    assert owner.responses[-1][0] == (
        "Sent 4 poll progress-bar previews to your DMs.",
    )


def test_preview_is_admin_discoverable_but_intentionally_absent_from_public_help():
    command = preview.PollBarPreview._command_data

    assert command.name == "poll-bar-preview"
    assert command.default_member_permissions == hikari.Permissions.ADMINISTRATOR
    assert "/poll-bar-preview" not in command_paths()

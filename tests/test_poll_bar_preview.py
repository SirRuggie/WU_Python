import asyncio
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands import poll_bar_preview as preview
from extensions.commands.help_catalog import command_paths


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
EXPECTED_RESULTS = {
    "A": (
        "**1. Minecraft** █████████░░░░░░░ **55% · 12**\n"
        "**2. Jackbox Party Pack** █████░░░░░░░░░░░ **32% · 7**\n"
        "**3. Gartic Phone with custom prompts**\n"
        "██░░░░░░░░░░░░░░ **14% · 3**"
    ),
    "B": (
        "**1. Minecraft** ███████████░░░░░░░░░ **55% · 12**\n"
        "**2. Jackbox Party Pack** ██████░░░░░░░░░░░░░░ **32% · 7**\n"
        "**3. Gartic Phone with custom prompts**\n"
        "███░░░░░░░░░░░░░░░░░ **14% · 3**"
    ),
}


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


def _component_nodes(view):
    return [node for node in _payload_nodes(view) if "type" in node]


def _button_nodes(view):
    return [
        node for node in _component_nodes(view)
        if node["type"] == hikari.ComponentType.BUTTON
    ]


def test_realistic_fixture_and_two_bar_lengths_are_exact():
    assert preview.POLL_QUESTION == "What should we play tonight?"
    assert preview.POLL_DETAILS == "Pick one for game night."
    assert preview.POLL_OPTIONS == (
        (1, "Minecraft", 12),
        (2, "Jackbox Party Pack", 7),
        (3, "Gartic Phone with custom prompts", 3),
    )
    assert preview.POLL_TOTAL == 22
    assert tuple(
        (variant.code, variant.width)
        for variant in preview.FINALISTS
    ) == (("A", 16), ("B", 20))


def test_wu_bars_use_exact_half_up_lengths_without_backticks():
    assert preview._round_half_up(5, 2) == 3
    assert preview._round_half_up(15, 10) == 2
    assert preview._percent(12, 22) == 55
    assert preview._percent(7, 22) == 32
    assert preview._percent(3, 22) == 14

    expected = {
        16: (
            "█████████░░░░░░░",
            "█████░░░░░░░░░░░",
            "██░░░░░░░░░░░░░░",
        ),
        20: (
            "███████████░░░░░░░░░",
            "██████░░░░░░░░░░░░░░",
            "███░░░░░░░░░░░░░░░░░",
        ),
    }
    for width, bars in expected.items():
        for (_option_id, _label, count), bar in zip(preview.POLL_OPTIONS, bars):
            rendered = preview._bar(width, count, preview.POLL_TOTAL)
            assert rendered == bar
            assert len(rendered) == width
            assert "`" not in rendered

    assert preview._bar(16, 1, 0) == "░" * 16
    assert preview._bar(16, 23, 22) == "█" * 16


@pytest.mark.parametrize("variant", preview.FINALISTS)
def test_result_rows_are_exact_and_only_long_option_forces_a_line_break(variant):
    rendered = "\n".join(
        preview._result_line(
            variant,
            option_id=option_id,
            label=label,
            count=count,
        )
        for option_id, label, count in preview.POLL_OPTIONS
    )
    assert rendered == EXPECTED_RESULTS[variant.code]
    assert "`" not in rendered

    rows = [
        preview._result_line(
            variant,
            option_id=option_id,
            label=label,
            count=count,
        )
        for option_id, label, count in preview.POLL_OPTIONS
    ]
    assert "\n" not in rows[0]
    assert "\n" not in rows[1]
    assert rows[2].count("\n") == 1
    assert rows[0].endswith("**55% · 12**")
    assert rows[1].endswith("**32% · 7**")
    assert rows[2].endswith("**14% · 3**")


@pytest.mark.parametrize("variant", preview.FINALISTS)
def test_complete_poll_card_keeps_the_approved_layout_and_component_budget(variant):
    view = preview.build_poll_bar_preview_components(
        variant.code,
        creator_id=preview.OWNER_ID,
        observed_at=NOW,
    )
    container = _built_payload(view[0])
    children = container["components"]
    nodes = _component_nodes(view)
    text = [node["content"] for node in nodes if "content" in node]
    buttons = _button_nodes(view)
    type_counts = Counter(node["type"] for node in nodes)

    assert container["accent_color"] == int(preview.GOLD_ACCENT)
    assert len(children) == 7
    assert len(nodes) == 13
    assert type_counts == Counter({
        hikari.ComponentType.BUTTON: 5,
        hikari.ComponentType.TEXT_DISPLAY: 3,
        hikari.ComponentType.SEPARATOR: 2,
        hikari.ComponentType.ACTION_ROW: 2,
        hikari.ComponentType.CONTAINER: 1,
    })
    assert text == [
        "# 📊 What should we play tonight?\nPick one for game night.",
        EXPECTED_RESULTS[variant.code],
        (
            "-# 22 votes · You can change your vote.\n"
            f"-# ⏱️ Closes <t:{int(NOW.timestamp()) + 3600}:R> · "
            f"<@{preview.OWNER_ID}>\n"
            f"-# Preview {variant.code} · WU bar · {variant.width} cells"
        ),
    ]
    assert all("Poll ID" not in content for content in text)
    assert all("`" not in content for content in text)

    vote_buttons = children[4]["components"]
    admin_buttons = children[5]["components"]
    assert [button["label"] for button in vote_buttons] == ["1", "2", "3"]
    assert all("emoji" not in button for button in vote_buttons)
    assert [button["style"] for button in vote_buttons] == [
        hikari.ButtonStyle.PRIMARY,
    ] * 3
    assert [button["label"] for button in admin_buttons] == [
        "View voters",
        "End poll",
    ]
    assert [button["style"] for button in admin_buttons] == [
        hikari.ButtonStyle.SECONDARY,
        hikari.ButtonStyle.SECONDARY,
    ]
    assert all(button["disabled"] is True for button in buttons)

    custom_ids = [str(button["custom_id"]) for button in buttons]
    assert len(custom_ids) == len(set(custom_ids))
    assert all(value.startswith("poll_bar_preview_noop:") for value in custom_ids)
    assert all(value.count(":") == 1 and len(value) <= 100 for value in custom_ids)
    assert not any(value.startswith("poll_vote:") for value in custom_ids)
    assert not any(value.startswith("poll_details:") for value in custom_ids)
    assert not any(value.startswith("poll_end:") for value in custom_ids)
    assert all(len(content) <= 4000 for content in text)
    assert all(len(button.get("label", "")) <= 80 for button in buttons)


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


def test_delivery_sends_only_two_gold_complete_polls_without_mentions():
    rest = _Rest()
    sent = asyncio.run(preview._send_poll_bar_previews(
        SimpleNamespace(rest=rest),
        owner_id=preview.OWNER_ID,
        observed_at=NOW,
    ))

    assert sent == 2
    assert rest.dm_users == [preview.OWNER_ID]
    assert len(rest.messages) == 2
    for message in rest.messages:
        assert message["channel"].id == 700
        assert message["flags"] == hikari.MessageFlag.IS_COMPONENTS_V2
        assert message["user_mentions"] is False
        assert message["role_mentions"] is False
        assert message["mentions_everyone"] is False
        assert message["mentions_reply"] is False
        assert _built_payload(message["components"][0])["accent_color"] == int(
            preview.GOLD_ACCENT
        )


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
    assert len(owner_rest.messages) == 2
    assert owner.responses[-1][1]["ephemeral"] is True
    assert owner.responses[-1][0] == (
        "Sent 2 WU poll bar-length previews to your DMs.",
    )


def test_preview_is_discoverable_owner_gated_and_isolated_from_production_paths():
    command = preview.PollBarPreview._command_data
    source = Path(preview.__file__).read_text(encoding="utf-8")

    assert command.name == "poll-bar-preview"
    assert command.default_member_permissions == hikari.Permissions.ADMINISTRATOR
    assert "/poll-bar-preview" not in command_paths()
    assert "extensions.commands.poll" not in source
    assert "poll_store" not in source
    assert "MongoClient" not in source
    assert "register_action" not in source
    assert 'custom_id=f"poll_vote:' not in source
    assert 'custom_id=f"poll_details:' not in source
    assert 'custom_id=f"poll_end:' not in source

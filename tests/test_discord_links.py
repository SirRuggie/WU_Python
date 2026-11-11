"""Profile link labels stay clickable for names with Markdown characters or emoji."""
import re

import pytest

from utils.discord_links import profile_label
from utils.member_event_cards import OBJECT_KINDS, build_card, build_forum_message, sample_row

UID = "123456789012345678"
MOD = "987654321098765432"
MARKDOWN = "\\[]()*_~`|<>"
LINK = re.compile(r"\[([^\[\]\n]+)\]\(https://discord\.com/users/([0-9]+)\)")
NAMES = [
    "Sir Ruggie | GMT-5 🇺🇸",
    "ClashPerk [ -- ]",
    "back\\slash",
    "*bold* _under_ `code`",
    "~strike~ (paren) <tag>",
    "☀️ Hawk Moth ☀️",
    "👨‍👩‍👧 family 👍🏽",
    "a|b|c",
]


@pytest.mark.parametrize(("name", "expected"), [
    ("Sir Ruggie | GMT-5 🇺🇸", "Sir Ruggie │ GMT-5"),
    ("ClashPerk [ -- ]", "ClashPerk ［ -- ］"),
    ("back\\slash", "back╲slash"),
    ("*bold* _under_ `code`", "∗bold∗ ＿under＿ ′code′"),
    ("~strike~ (paren) <tag>", "～strike～ （paren） ‹tag›"),
    ("☀️ Hawk Moth ☀️", "Hawk Moth"),
    ("@everyone", "@\u200beveryone"),
    ("see https://evil.example", "see https\u200b://evil.example"),
    ("🇬🇧", "Discord profile"),
])
def test_label_uses_lookalikes_without_escapes_or_emoji(name, expected):
    assert profile_label(name) == expected


@pytest.mark.parametrize("name", NAMES)
def test_label_has_no_markdown_or_backslash(name):
    label = profile_label(name)
    assert not any(c in label for c in MARKDOWN)


def _text(payload):
    if "embeds" in payload:
        embed = payload["embeds"][0]
        return "\n".join([embed.get("description", "")]
                         + [f["value"] for f in embed.get("fields", [])])
    parts = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == 10:
                parts.append(node["content"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(payload["components"])
    return "\n".join(parts)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("builder", [build_card, build_forum_message])
@pytest.mark.parametrize("kind", ["join", "leave", "kick", "roles_added", "roles_removed",
                                  "member_update", "message_delete", *OBJECT_KINDS])
def test_every_log_kind_renders_clean_profile_links(name, builder, kind):
    row = {**sample_row(kind), "display_name": name}
    text = _text(builder(row, MOD, {MOD: name}))
    links = LINK.findall(text)
    assert links, text
    for label, uid in links:
        assert uid in {UID, MOD}
        assert "\\" not in label and not any(c in label for c in MARKDOWN)
    assert f"[{profile_label(name)}](https://discord.com/users/{MOD})" in text


@pytest.mark.parametrize("builder", [build_card, build_forum_message])
def test_emoji_only_name_falls_back_to_mention(builder):
    text = _text(builder(sample_row("kick"), None, {MOD: "🇬🇧✨"}))
    assert f"<@{MOD}>" in text
    assert f"](https://discord.com/users/{MOD})" not in text

"""Exact moderation card content and one-attempt transport payloads."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch

from utils.member_event_cards import (
    DEFAULT_AVATAR, accent, build_card, build_forum_message, sample_row,
)


def card_text(payload):
    return "\n".join(
        component["content"]
        for component in payload["components"][0]["components"]
        if component["type"] == 10
    )


class CardTests(unittest.TestCase):
    def test_all_four_cards_have_the_approved_identity_fields_and_profile(self):
        expectations = {
            "join": (0x2BA66A, "👋 Member joined", "joined", "Account created"),
            "leave": (0xD34A4A, "🚪 Member left", "left", "Joined"),
            "kick": (0xE69935, "👢 Member kicked", "was kicked", "Reason"),
            "ban": (0xA8384B, "🔨 Member banned", "was banned", "Reason"),
        }
        for kind, (color, title, action, field) in expectations.items():
            with self.subTest(kind=kind):
                row = sample_row(kind)
                payload = build_card(row)
                self.assertEqual(payload["flags"], 32768)
                self.assertEqual(payload["allowed_mentions"], {"parse": []})
                container = payload["components"][0]
                self.assertEqual(container["type"], 17)
                self.assertEqual(container["accent_color"], color)
                self.assertEqual(accent(kind), color)
                children = container["components"]
                self.assertEqual([child["type"] for child in children][0], 9)
                self.assertEqual([child["type"] for child in children][-3:], [14, 10, 1])
                self.assertEqual(children[0]["accessory"]["type"], 11)
                self.assertEqual(children[0]["accessory"]["media"]["url"], DEFAULT_AVATAR)
                text = card_text(payload)
                self.assertIn(title, text)
                self.assertIn(f"<@{row['user_id']}> {action}", text)
                self.assertIn(field, text)
                self.assertIn("Members: 1,284", text)
                self.assertIn(f"ID {row['user_id']}", text)
                self.assertIn("<t:1793296800:f>", text)
                button = children[-1]["components"][0]
                self.assertEqual(button, {"type": 2, "style": 5,
                                          "label": "View profile ↗",
                                          "url": f"https://discord.com/users/{row['user_id']}"})
                self.assertEqual(json.dumps(payload, ensure_ascii=False).count("View profile ↗"), 1)

    def test_unknown_moderator_reason_roles_and_dates_are_honest(self):
        row = sample_row("kick")
        row.update(moderator_id=None, reason=None, joined_at=None,
                   member_count=None, roles=None)
        text = card_text(build_card(row))
        self.assertIn("by an unknown moderator", text)
        self.assertIn("No reason given", text)
        self.assertIn("Date unavailable", text)
        self.assertIn("Roles**\nUnavailable", text)
        self.assertIn("Members: unavailable", text)
        row["roles"] = []
        self.assertIn("Roles**\nNone", card_text(build_card(row)))

    def test_saved_roles_and_untrusted_text_are_inert(self):
        row = sample_row("ban")
        row.update(display_name="@everyone <@42> **bad**", reason="@here <@55> **ping**",
                   roles=["@everyone", "Guild <@44>"])
        payload = build_card(row)
        text = json.dumps(payload)
        for unsafe in ("@everyone", "@here", "<@42>", "<@55>", "<@44>"):
            self.assertNotIn(unsafe, text)
        self.assertIn("Guild", text)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_join_metadata_test_staff_and_forum_fallback(self):
        row = sample_row("join")
        row.update(account_created_at=None, member_count=None,
                   avatar=b"png", avatar_type="image/png")
        payload = build_card(row, test_staff_id="987654321098765432")
        self.assertIn("Account created**\nDate unavailable", card_text(payload))
        self.assertIn("Members: unavailable", card_text(payload))
        self.assertIn("Test log · sent by <@987654321098765432>", card_text(payload))
        self.assertEqual(payload["components"][0]["components"][0]["accessory"]["media"]["url"],
                         "attachment://member-avatar.png")
        forum = build_forum_message(row, test_staff_id="987654321098765432")
        self.assertNotIn("flags", forum)
        self.assertEqual(forum["embeds"][0]["color"], 0x2BA66A)
        self.assertEqual(forum["allowed_mentions"], {"parse": []})
        self.assertEqual(forum["components"][0]["components"][0]["url"],
                         "https://discord.com/users/123456789012345678")
        self.assertIn("Test log", forum["embeds"][0]["description"])

    def test_naive_saved_dates_are_utc(self):
        row = sample_row("leave")
        row["joined_at"] = datetime(2025, 7, 30, 13, 45, 12)
        naive = build_card(row)
        row["joined_at"] = row["joined_at"].replace(tzinfo=timezone.utc)
        self.assertEqual(naive, build_card(row))


class DeliveryPayloadTests(unittest.IsolatedAsyncioTestCase):
    def test_identity_metadata_snapshots_roles_and_reuses_departed_identity(self):
        from extensions.events import member_events as transport

        roles = {222: NS(name="Raid lead"), 333: NS(name="CWL player")}
        cache = NS(get_guild=lambda _guild: NS(member_count=1284),
                   get_role=lambda role_id: roles.get(int(role_id)))
        bot = NS(cache=cache)
        created, count, names = transport.identity_metadata(
            bot, 123456789012345678, NS(role_ids=[222, 333]), None,
        )
        self.assertIsInstance(created, datetime)
        self.assertEqual(count, 1284)
        self.assertEqual(names, ["Raid lead", "CWL player"])
        self.assertEqual(transport.identity_metadata(
            NS(), 123456789012345678, None, {"roles": names},
        )[2], names)

    async def test_text_and_forum_starter_are_one_http_attempt_each(self):
        from extensions.events import member_events as transport

        class Response:
            status = 201
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def json(self):
                return {"message": {"id": "123456789012345678"}}

        class Session:
            def __init__(self, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def post(self, url, **kwargs):
                attempts.append((url, kwargs))
                return Response()

        row = {**sample_row("kick"), "channel_id": 123456789012345679,
               "forum_tag_id": 123456789012345680}
        attempts = []
        with patch.dict("os.environ", {"DISCORD_TOKEN": "fake"}), \
             patch.object(transport.aiohttp, "ClientSession", Session):
            self.assertEqual(await transport.post_card(row, forum=False), "123456789012345678")
            self.assertEqual(await transport.post_card(row, forum=True), "123456789012345678")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(attempts[0][0].endswith("/messages"))
        self.assertEqual(attempts[0][1]["json"], build_card(row))
        self.assertTrue(attempts[1][0].endswith("/threads"))
        starter = attempts[1][1]["json"]
        self.assertEqual(starter["applied_tags"], [str(row["forum_tag_id"])])
        self.assertEqual(starter["message"], build_forum_message(row))


if __name__ == "__main__":
    unittest.main()

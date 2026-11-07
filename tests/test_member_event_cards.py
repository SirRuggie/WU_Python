"""Exact moderation card content and one-attempt transport payloads."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch

from utils.member_event_cards import (
    DEFAULT_AVATAR, _content, accent, build_card, build_forum_message, sample_row,
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

    def test_names_of_only_joiners_use_the_fallbacks(self):
        row = sample_row("kick")
        row["display_name"] = "\u200d \u200d"
        self.assertEqual(_content(row)[0][0], "Unknown member")
        row = sample_row("timeout_add")
        row["display_name"] = "\u200d"
        self.assertEqual(_content(row)[0][0], "Unknown member")
        row = sample_row("member_update")
        row["details"] = {"changes": [{"field": "nickname", "before": "\u200d", "after": "\u200d"}]}
        self.assertIn("None → None", card_text(build_card(row)))

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


NEW_KINDS = ("unban", "role_create", "role_update", "role_delete", "roles_added", "roles_removed",
             "message_delete", "message_edit", "message_bulk_delete", "channel_create", "channel_update",
             "channel_delete", "channel_permissions", "thread_delete", "thread_lock", "server_update",
             "emoji", "sticker", "app", "webhook", "automod")


def buttons(payload):
    return [c for container in payload["components"] for row in container["components"]
            if row["type"] == 1 for c in row["components"]]


class BatchTwoCardTests(unittest.TestCase):
    def test_every_new_kind_renders_in_both_shapes_with_a_distinct_title(self):
        titles = set()
        for kind in NEW_KINDS:
            with self.subTest(kind=kind):
                row = sample_row(kind)
                text = card_text(build_card(row))
                forum = build_forum_message(row)["embeds"][0]["description"]
                self.assertIn(row["display_name"], json.dumps(build_card(row)))
                self.assertNotIn("Unknown", text)
                title = next(line for line in text.split("\n") if line.startswith("###"))
                self.assertIn(title, forum)
                titles.add(title)
        self.assertEqual(len(titles), len(NEW_KINDS))

    def test_object_cards_state_the_action_changes_and_subject(self):
        update = card_text(build_card(sample_row("role_update")))
        self.assertIn("Role <@&423456789012345678> was updated by <@987654321098765432>", update)
        self.assertIn("**Name**\nRecruit → Member", update)
        self.assertIn("**Permissions**\nChanged", update)
        self.assertIn("**Applies to**\n<@&423456789012345678>", card_text(build_card(sample_row("channel_permissions"))))
        for kind, word in (("emoji", "added"), ("sticker", "changed"), ("webhook", "removed"), ("app", "added")):
            self.assertIn(f"was {word}", card_text(build_card(sample_row(kind))))
        row = sample_row("server_update")
        row["details"] = {"action": "updated", "changes": [{"field": "name", "before": "https://a.example", "after": "@everyone"}]}
        text = card_text(build_card(row))
        self.assertNotIn("https://a", text)
        self.assertNotIn("@everyone", text)

    def test_member_cards_show_roles_messages_and_attachments_without_raw_markup(self):
        added = card_text(build_card(sample_row("roles_added")))
        self.assertIn("<@123456789012345678> had roles added by <@987654321098765432>", added)
        self.assertIn("**Roles**\nCWL player, Member", added)
        self.assertIn("was unbanned by", card_text(build_card(sample_row("unban"))))
        deleted = sample_row("message_delete")
        deleted["moderator_id"] = None
        text = card_text(build_card(deleted))
        self.assertIn("had a message deleted in <#223456789012345678>", text)
        self.assertNotIn(" by <@", text.split("\n")[2])  # Moderator omitted when unsure.
        self.assertIn("screenshot.png (image/png)", text)
        edit = card_text(build_card(sample_row("message_edit")))
        self.assertIn("**Before**\nSample message before the edit.", edit)
        self.assertIn("**After**\nSample message after the edit.", edit)
        bulk = card_text(build_card(sample_row("message_bulk_delete")))
        self.assertIn("12 messages were deleted in <#223456789012345678> by <@987654321098765432>", bulk)

    def test_member_history_button_only_on_member_kinds_and_only_with_a_base(self):
        from utils import dashboard_urls
        url = "https://dash.warriorsunited.cc/server/moderation/member/123456789012345678"
        with_button = ("join", "leave", "member_update", "kick", "ban", "unban", "timeout_add", "timeout_remove",
                       "roles_added", "roles_removed", "invite_use", "message_delete", "message_edit", "link")
        for kind in ("join", "leave", "kick", "ban", "timeout_add", "timeout_remove", "member_update", "link",
                     "invite_use", *NEW_KINDS):
            row = sample_row(kind)
            labels = [b["label"] for b in buttons(build_card(row))]
            forum_labels = [b["label"] for b in buttons({"components": [{"components": build_forum_message(row).get(
                "components", [])}]})]
            with self.subTest(kind=kind):
                self.assertEqual("Member history ↗" in labels, kind in with_button)
                self.assertEqual(labels, forum_labels)
                if kind in with_button:
                    self.assertIn(url, [b.get("url") for b in buttons(build_card(row))])
        with patch.object(dashboard_urls, "DASHBOARD_ORIGIN", ""):
            self.assertEqual([b["label"] for b in buttons(build_card(sample_row("kick")))], ["View profile ↗"])
        self.assertEqual(dashboard_urls.member_history_url(5), "https://dash.warriorsunited.cc/server/moderation/member/5")

    def test_join_card_extras_account_age_new_account_ordinal_and_invite(self):
        row = sample_row("join")
        text = card_text(build_card(row))
        self.assertIn("**Account age**\n6y 7mo", text)
        self.assertNotIn("New account", text)
        self.assertIn("**Join**\n3rd join", text)
        self.assertIn("**Invite**\nvia Spring recruitment", text)
        fresh = {**row, "account_created_at": datetime(2026, 10, 27, tzinfo=timezone.utc),
                 "details": {"join_count": 1, "invite": "x_y"}}
        text = card_text(build_card(fresh))
        self.assertIn("**Account age**\n2d · New account", text)
        self.assertNotIn("**Join**", text)  # First join: no ordinal.
        self.assertIn("via x\\_y", text)
        bare = card_text(build_card({**row, "details": None, "account_created_at": None}))
        self.assertNotIn("Account age", bare)
        self.assertNotIn("Invite", bare)
        for number, word in ((2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (21, "21st"), (22, "22nd")):
            self.assertIn(f"**Join**\n{word} join", card_text(build_card({**row, "details": {"join_count": number}})))

    def test_leave_card_extras_time_in_server_and_roles_omitted_when_unknown(self):
        text = card_text(build_card(sample_row("leave")))
        self.assertIn("**Time in server**\n2y 5mo", text)
        self.assertIn("**Roles**\nMember, CWL player", text)
        unknown = card_text(build_card({**sample_row("leave"), "roles": None, "joined_at": None}))
        self.assertNotIn("Time in server", unknown)
        self.assertNotIn("**Roles**", unknown)
        self.assertIn("**Roles**\nUnavailable", card_text(build_card({**sample_row("kick"), "roles": None})))


if __name__ == "__main__":
    unittest.main()

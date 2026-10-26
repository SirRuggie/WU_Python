"""Focused transport tests for the private Discord CWL member flow."""
import unittest

from extensions.commands import cwl_member as member


GUILD_ID = 644963518025826315


class User:
    def __init__(self, user_id=123):
        self.id = user_id


class Interaction:
    def __init__(self, user_id=123, guild_id=GUILD_ID, *, in_guild=True, values=()):
        self.guild_id = guild_id
        self.member = object() if in_guild else None
        self.values = values
        self.edits = []

    async def edit_initial_response(self, **kwargs):
        self.edits.append(kwargs)


class Context:
    def __init__(self, user_id=123, guild_id=GUILD_ID, *, in_guild=True, values=()):
        self.user = User(user_id)
        self.interaction = Interaction(user_id, guild_id, in_guild=in_guild, values=values)
        self.followups = []

    async def respond(self, *args, **kwargs):
        self.followups.append((args, kwargs))


def edited_text(edit):
    return edit["components"][0].components[0].content


def make_session(**kwargs):
    return member.MemberSession(123, GUILD_ID, member.time.monotonic(), **kwargs)


class CwlMemberTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        member._sessions.clear()

    async def test_component_rejects_other_member_without_editing_owner_panel(self):
        token = "owner-token"
        member._sessions[token] = make_session()
        ctx = Context(user_id=456)

        await member._handle(ctx, f"{token}:0", "home")

        self.assertTrue(ctx.followups)
        self.assertIn("belongs to another member", ctx.followups[0][0][0])
        self.assertEqual(ctx.interaction.edits, [])

    async def test_expired_and_stale_controls_do_not_replace_current_panel(self):
        token = "stale-token"
        session = make_session()
        member._sessions[token] = session
        session.version = 3
        ctx = Context()

        await member._handle(ctx, f"{token}:2", "home")

        self.assertTrue(ctx.followups)
        self.assertIn("expired or changed", ctx.followups[0][0][0])
        self.assertEqual(ctx.interaction.edits, [])

        session.created_at = member.time.monotonic() - member.SESSION_TTL - 1
        await member._handle(ctx, f"{token}:3", "home")
        self.assertNotIn(token, member._sessions)
        self.assertEqual(len(ctx.followups), 2)

    async def test_provider_unavailable_is_not_rendered_as_no_linked_accounts(self):
        token = "provider-token"
        session = make_session(screen="signup_pool", view={
            "season": {"id": 55, "label": "October", "signup_open": True, "status": "draft"},
            "revision": 7,
            "accounts_status": "unavailable",
            "accounts": [],
            "signups": [{"tag": "#ABC23", "pool": "main", "player_name": "Saved"}],
        })
        member._sessions[token] = session
        ctx = Context()

        await member._handle(ctx, f"{token}:0", "pool_main")

        content = edited_text(ctx.interaction.edits[-1])
        self.assertIn("temporarily unavailable", content)
        self.assertNotIn("No verified linked accounts", content)
        self.assertEqual(session.view["signups"][0]["tag"], "#ABC23")

    def test_account_menu_pages_fifteen_and_marks_selected_choices(self):
        accounts = [{"tag": f"#ABC{i:02d}", "name": f"Player {i}", "town_hall": 17, "verified": True}
                    for i in range(1, 26)]
        session = make_session(view={"accounts": accounts}, screen="select_accounts", pool="main")
        session.selected = {"#ABC03"}
        components = member._components("pages", session)

        menu = components[0].components[0]
        self.assertEqual(len(menu.options), member.PAGE_SIZE)
        self.assertTrue(menu.options[2].is_default)
        next_button = next(button for row in components for button in row.components
                           if getattr(button, "custom_id", "").startswith("cwl_member_next:"))
        self.assertFalse(next_button.is_disabled)

    def test_unpublished_view_never_uses_draft_assignments(self):
        session = make_session(view={
            "published": None,
            "signups": [{"tag": "#ABC23", "pool": "main"}],
            "assignments": [],
            "draft_assignments": [{"tag": "#ABC23", "assigned_clan_name": "Secret draft"}],
        }, screen="assignments")

        text = member._main_text(session)

        self.assertIn("signup is saved", text)
        self.assertIn("not published", text)
        self.assertNotIn("Secret draft", text)

    def test_published_assignment_shows_only_service_rows_and_safe_clan_link(self):
        session = make_session(view={
            "published": {"version": 4},
            "assignments": [{"tag": "#ABC23", "player_name": "P@layer", "assigned_clan_tag": "#2P0Y", "assigned_clan_name": "Clan"}],
            "draft_assignments": [{"tag": "#XYZ99", "assigned_clan_name": "Secret draft"}],
        }, screen="assignments")

        text = member._main_text(session)

        self.assertIn("P@\u200blayer", text)
        self.assertIn("Clan · #2P0Y", text)
        self.assertIn("[Open clan](https://link.clashofclans.com/", text)
        self.assertNotIn("Secret draft", text)
        self.assertNotIn("#XYZ99", text)

    async def test_confirm_sends_revision_and_source_pool_once_and_reports_uncertain_outcome(self):
        token = "write-token"
        session = make_session(
            view={
                "season": {"id": 77, "label": "October", "signup_open": True, "status": "draft"},
                "revision": 12,
                "accounts_status": "ok",
                "accounts": [{"tag": "#ABC23", "name": "Player", "town_hall": 17, "verified": True}],
                "signups": [{"tag": "#ABC23", "pool": "main", "prefer_crystal_1_or_lower": True}],
            },
            screen="review",
            pool="lazy",
        )
        session.selected = {"#ABC23"}
        member._sessions[token] = session
        calls = []

        class Error(Exception):
            uncertain = True

        async def request(action, **kwargs):
            calls.append((action, kwargs))
            if action == "submit":
                raise Error("timeout")
            return session.view

        from unittest.mock import patch
        with patch("utils.cwl_member_client.request", request):
            ctx = Context()
            await member._handle(ctx, f"{token}:0", "confirm")

            self.assertEqual(len(calls), 1)
            action, payload = calls[0]
            self.assertEqual(action, "submit")
            self.assertEqual(payload["guild_id"], str(GUILD_ID))
            self.assertEqual(payload["season_id"], 77)
            self.assertEqual(payload["expected_revision"], 12)
            self.assertEqual(payload["accounts"], [{"tag": "#ABC23", "prefer_crystal_1_or_lower": True, "move_from_pool": "main"}])
            self.assertIn("result is unclear", edited_text(ctx.interaction.edits[-1]))

            # The old confirmation is consumed; a duplicate click cannot issue another write.
            await member._handle(ctx, f"{token}:0", "confirm")
            self.assertEqual(len(calls), 1)

    async def test_forged_confirmation_from_other_screen_cannot_mutate(self):
        token = "forged-token"
        session = make_session(
            screen="select_accounts",
            pool="lazy",
            selected={"#ABC23"},
            view={
                "season": {"id": 10, "label": "October", "signup_open": True, "status": "draft"},
                "revision": 3,
                "accounts": [{"tag": "#ABC23", "name": "Player", "verified": True}],
            },
        )
        member._sessions[token] = session
        ctx = Context()
        from unittest.mock import patch
        with patch("utils.cwl_member_client.request") as request:
            await member._handle(ctx, f"{token}:0", "confirm")
        request.assert_not_called()
        self.assertIn("out of date", edited_text(ctx.interaction.edits[-1]))

    async def test_closed_season_blocks_writes_but_keeps_read_controls(self):
        token = "closed-token"
        session = make_session(
            screen="review",
            pool="main",
            selected={"#ABC23"},
            view={
                "season": {"id": 10, "label": "Archived season", "signup_open": False, "status": "archived"},
                "revision": 3,
                "accounts": [{"tag": "#ABC23", "name": "Player", "verified": True}],
            },
        )
        member._sessions[token] = session
        ctx = Context()
        from unittest.mock import patch
        with patch("utils.cwl_member_client.request") as request:
            await member._handle(ctx, f"{token}:0", "confirm")
        request.assert_not_called()
        self.assertIn("Signups are closed", edited_text(ctx.interaction.edits[-1]))

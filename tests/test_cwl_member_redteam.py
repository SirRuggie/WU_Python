"""Adversarial regressions for the Discord member CWL panel builder."""

import tempfile
import time
import unittest
from unittest.mock import patch

from extensions.commands import cwl_member
from cwl_web.store import Store
from utils.cwl_member_service import accounts_for_member, member_view


class CwlMemberPanelRedteamTests(unittest.TestCase):
    def test_home_panel_renders_open_state(self):
        session = cwl_member.MemberSession(
            user_id=123,
            guild_id=644963518025826315,
            created_at=time.monotonic(),
            view={"season": {"id": 4, "label": "October", "signup_open": True,
                             "status": "draft"}},
        )

        content = cwl_member._main_text(session)

        self.assertIn("October", content)
        self.assertIn("Signups open", content)

    def test_account_picker_uses_supported_hikari_builder_api(self):
        session = cwl_member.MemberSession(
            user_id=123,
            guild_id=644963518025826315,
            created_at=time.monotonic(),
            screen="select_accounts",
            pool="lazy",
            view={"accounts": [{"tag": "#P2Y", "name": "Player", "town_hall": 17,
                                "verified": True}]},
        )

        components = cwl_member._components("panel", session)

        self.assertEqual(len(components), 2)
        self.assertEqual(len(components[0].components[0].options), 1)


class CwlMemberProviderRedteamTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_family_directory_keeps_lazy_accounts_available(self):
        class Provider:
            async def linked_tags(self, user_id):
                return {"#P2Y": True}

            async def player(self, tag):
                return {"tag": tag, "name": "Player", "town_hall": 17,
                        "current_clan_tag": "#Q2Y", "current_clan_name": "Family"}

            async def family_clans(self):
                return {"clans": None}

        accounts = await accounts_for_member(Provider(), "123", verified_only=True)

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["family_clan_status"], "unknown")
        self.assertTrue(accounts[0]["lazy_eligible"])


class CwlMemberReviewRedteamTests(unittest.TestCase):
    def test_pool_change_confirmation_discloses_working_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(f"{directory}/cwl.sqlite")
            with store.tx() as db:
                db.execute("INSERT INTO seasons(label, signup_open) VALUES ('Test', 1)")
                season_id = db.execute("SELECT id FROM seasons").fetchone()[0]
                db.execute("UPDATE member_season SET season_id=? WHERE id=1", (season_id,))
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (season_id, "#P2Y", "123", "lazy", 0, "Player", 17))
                db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept) VALUES (?,?,?,1)",
                           (season_id, "#P2Y", "#Q2Y"))

            view = member_view(store, "123")
            session = cwl_member.MemberSession(
                user_id=123,
                guild_id=644963518025826315,
                created_at=time.monotonic(),
                view=view,
                screen="pool_change_confirm",
                pending_tag="#P2Y",
                pending_pool="main",
                source_pools={"#P2Y": "lazy"},
            )

            content = cwl_member._main_text(session)

            self.assertIn("Any working placement will be cleared", content)

    def test_assignments_without_signup_dont_claim_signup_saved(self):
        session = cwl_member.MemberSession(
            user_id=123,
            guild_id=644963518025826315,
            created_at=time.monotonic(),
            view={"published": None, "signups": [], "assignments": []},
            screen="assignments",
        )

        content = cwl_member._main_text(session)

        self.assertNotIn("Your signup is saved", content)


class CwlMemberUnicodeRedteamTests(unittest.TestCase):
    def test_select_option_labels_fit_discord_utf16_limit(self):
        emoji_name = "😀" * 60
        session = cwl_member.MemberSession(
            user_id=123,
            guild_id=644963518025826315,
            created_at=time.monotonic(),
            screen="select_accounts",
            pool="lazy",
            view={"accounts": [{"tag": "#P2Y", "name": emoji_name, "town_hall": 17,
                                "verified": True}]},
        )

        account_option = cwl_member._components("panel", session)[0].components[0].options[0]
        units = len(account_option.label.encode("utf-16-le")) // 2
        self.assertLessEqual(units, 100)

    def test_saved_signup_option_labels_fit_discord_utf16_limit(self):
        emoji_name = "😀" * 60
        session = cwl_member.MemberSession(
            user_id=123,
            guild_id=644963518025826315,
            created_at=time.monotonic(),
            screen="my_signups",
            view={"signups": [{"tag": "#P2Y", "player_name": emoji_name, "pool": "lazy"}]},
        )

        option = cwl_member._components("panel", session)[0].components[0].options[0]
        units = len(option.label.encode("utf-16-le")) // 2
        self.assertLessEqual(units, 100)

    def test_maximal_assignment_page_fits_discord_content_limit(self):
        session = cwl_member.MemberSession(
            user_id=123,
            guild_id=644963518025826315,
            created_at=time.monotonic(),
            screen="assignments",
            view={"published": {"version": 1}, "assignments": [
                {"tag": "#P2Y", "player_name": "😀" * 50,
                 "assigned_clan_tag": "#Q2Y", "assigned_clan_name": "😀" * 60}
                for _ in range(5)
            ]},
        )

        content = cwl_member._main_text(session)

        self.assertLessEqual(len(content.encode("utf-16-le")) // 2, 2000)


class CwlMemberStaleSeasonRedteamTests(unittest.IsolatedAsyncioTestCase):
    async def test_refreshing_new_member_season_discards_old_season_selection(self):
        session = cwl_member.MemberSession(
            user_id=123,
            guild_id=644963518025826315,
            created_at=time.monotonic(),
            view={"season": {"id": 10, "signup_open": True, "status": "draft"},
                  "revision": 3, "accounts": [{"tag": "#P2Y", "verified": True}]},
            screen="select_accounts",
            pool="lazy",
            selected={"#P2Y"},
        )

        async def refreshed_view(action, **kwargs):
            return {"season": {"id": 11, "signup_open": True, "status": "draft"},
                    "revision": 0, "accounts": [{"tag": "#P2Y", "verified": True}],
                    "accounts_status": "ok", "signups": []}

        with patch("utils.cwl_member_client.request", refreshed_view):
            await cwl_member._refresh(session, 123, 644963518025826315)

        self.assertEqual(session.view["season"]["id"], 11)
        self.assertEqual(session.selected, set())


if __name__ == "__main__":
    unittest.main()

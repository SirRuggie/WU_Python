"""Independent review regressions for the Discord CWL member controls."""

import tempfile
import time
import unittest
from unittest.mock import patch

from extensions.commands import cwl_member
from cwl_web.store import Store
from utils.cwl_member_service import assignment_view, member_view


GUILD_ID = 644963518025826315


def session(screen):
    return cwl_member.MemberSession(
        user_id=123,
        guild_id=GUILD_ID,
        created_at=time.monotonic(),
        screen=screen,
        view={
            "season": {"id": 1, "label": "October", "signup_open": True, "status": "draft"},
            "revision": 1,
            "accounts": [{"tag": "#P2Y", "name": "Player", "verified": True}],
            "signups": [{"tag": "#P2Y", "pool": "lazy", "player_name": "Player"}],
        },
        pending_tag="#P2Y",
        source_pools={"#P2Y": "lazy"},
        pending_pool="main",
    )


class Context:
    def __init__(self):
        self.user = type("User", (), {"id": 123})()
        self.interaction = type("Interaction", (), {
            "guild_id": GUILD_ID,
            "member": object(),
            "edit_initial_response": self._edit,
        })()
        self.edits = []

    async def _edit(self, **kwargs):
        self.edits.append(kwargs)

    async def respond(self, *_args, **_kwargs):
        pass


class SolReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cwl_member._sessions.clear()

    def test_pool_change_confirmation_has_confirm_and_cancel_controls(self):
        controls = cwl_member._components("review", session("pool_change_confirm"))
        ids = [button.custom_id for row in controls for button in row.components]
        self.assertTrue(any(value.startswith("cwl_member_confirm_move:") for value in ids))
        self.assertTrue(any(value.startswith("cwl_member_change_pool:") or value.startswith("cwl_member_signup_action:") for value in ids))

    async def test_change_pool_cancel_returns_to_saved_signup(self):
        current = session("change_pool")
        cwl_member._sessions["review"] = current
        ctx = Context()

        await cwl_member._handle(ctx, "review:0", "signup_action")

        self.assertEqual(current.screen, "signup_action")
        self.assertNotIn("no longer available", ctx.edits[-1]["components"][0].components[0].content)


    async def test_rendered_pool_change_buttons_reach_single_confirmed_write(self):
        current = session("change_pool")
        cwl_member._sessions["review"] = current
        ctx = Context()
        writes = []

        async def request(action, **kwargs):
            if action == "submit":
                writes.append(kwargs)
            return current.view

        with patch("utils.cwl_member_client.request", request):
            move_button = cwl_member._components("review", current)[0].components[0]
            action_id = move_button.custom_id.split(":", 1)[1]
            await cwl_member._handle(ctx, action_id, "move_main")
            self.assertEqual(current.screen, "pool_change_confirm")

            confirm_button = next(
                button for row in cwl_member._components("review", current)
                for button in row.components
                if button.custom_id.startswith("cwl_member_confirm_move:")
            )
            action_id = confirm_button.custom_id.split(":", 1)[1]
            await cwl_member._handle(ctx, action_id, "confirm_move")

            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0]["pool"], "main")
            self.assertEqual(writes[0]["accounts"][0]["move_from_pool"], "lazy")
            await cwl_member._handle(ctx, action_id, "confirm_move")
            self.assertEqual(len(writes), 1)


class PublicationSnapshotReviewTests(unittest.TestCase):
    def test_new_signup_after_publication_is_not_a_published_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(f"{directory}/cwl.sqlite")
            with store.tx() as db:
                db.execute("INSERT INTO seasons(label,signup_open) VALUES ('October',1)")
                season_id = db.execute("SELECT id FROM seasons").fetchone()[0]
                db.execute("UPDATE member_season SET season_id=? WHERE id=1", (season_id,))
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (season_id, "#P2Y", "123", "lazy", 0, "Published", 17))
                db.execute("INSERT INTO roster_publications(season_id,version,revision,published_by,published_at,"
                           "joining_instructions,assigned_count,unassigned_count,clans_json) "
                           "VALUES (?,?,?,?,?,?,?,?,?)",
                           (season_id, 1, 1, "staff", "2026-10-25T00:00:00Z", "", 1, 0, "[]"))
                publication_id = db.execute("SELECT id FROM roster_publications").fetchone()[0]
                db.execute("INSERT INTO publication_accounts(publication_id,tag,user_id,player_name,town_hall,"
                           "pool,prefer_crystal_1_or_lower,assigned_clan_tag,assigned_clan_name,kept) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (publication_id, "#P2Y", "123", "Published", 17, "lazy", 0, "#Q2Y", "Hosting", 0))
                db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
                           "VALUES (?,?,?,?,?,?,?)", (season_id, "#R2Y", "123", "lazy", 0, "Later", 16))

            view = member_view(store, "123")
            self.assertEqual({row["tag"] for row in view["signups"]}, {"#P2Y", "#R2Y"})
            self.assertEqual([row["tag"] for row in view["assignments"]], ["#P2Y"])
            dashboard = assignment_view(store, "123", season_id)
            self.assertEqual([row["tag"] for row in dashboard["accounts"]], ["#P2Y", "#R2Y"])
            self.assertIsNone(dashboard["accounts"][1]["assigned_clan_tag"])


if __name__ == "__main__":
    unittest.main()

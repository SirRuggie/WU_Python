"""Independent regressions for the private CWL member interaction lifecycle."""

import tempfile
import time
import unittest
from unittest.mock import patch

import hikari
from hikari.impl.rest import RESTClientImpl

from extensions.commands import cwl_member as member
from cwl_web.store import Store
from utils.cwl_member_service import MemberError, submit


GUILD_ID = 644963518025826315


class Context:
    def __init__(self, *, values=(), edit_error=None):
        self.user = type("User", (), {"id": 123})()
        self.values = values
        self.edit_error = edit_error
        self.edits = []
        self.responses = []
        self.interaction = type("Interaction", (), {
            "guild_id": GUILD_ID,
            "member": object(),
            "values": values,
            "edit_initial_response": self.edit_initial_response,
        })()

    async def edit_initial_response(self, **kwargs):
        if self.edit_error:
            raise self.edit_error
        self.edits.append(kwargs)

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


def session(*, screen="home", season_id=1, accounts=None):
    return member.MemberSession(
        user_id=123,
        guild_id=GUILD_ID,
        created_at=time.monotonic(),
        screen=screen,
        view={
            "season": {"id": season_id, "label": "October", "signup_open": True, "status": "draft"},
            "revision": 0,
            "accounts_status": "ok",
            "accounts": accounts or [],
            "signups": [],
        },
    )


class MemberInteractionAuditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        member._sessions.clear()

    def test_linked_unverified_account_appears_but_malformed_rows_do_not(self):
        current = session(screen="select_accounts", accounts=[
            {"tag": "#P2Y", "name": "Linked", "verified": False, "town_hall": 16},
            {"name": "Missing tag", "verified": True},
            {"tag": None, "name": "Null tag", "verified": True},
            "not an account",
        ])
        current.pool = "lazy"

        self.assertEqual([row["tag"] for row in member._accounts(current)], ["#P2Y"])
        menu = member._components("audit", current)[0].components[0]
        self.assertEqual([option.value for option in menu.options], ["#P2Y"])
        current.pool = "main"
        self.assertEqual([row["tag"] for row in member._eligible_accounts(current)], ["#P2Y"])

    def test_picker_and_review_share_highest_th_order_with_stable_ties(self):
        accounts = [
            {"tag": "#P2Y", "name": "Low", "town_hall": 12},
            {"tag": "#Q2Y", "name": "High B", "town_hall": 17},
            {"tag": "#R2Y", "name": "Unknown"},
            {"tag": "#G2Y", "name": "High A", "town_hall": 17},
            {"tag": "#J2Y", "name": "Invalid", "town_hall": True},
        ]
        current = session(screen="select_accounts", accounts=accounts)
        current.pool = "lazy"
        order = ["#G2Y", "#Q2Y", "#P2Y", "#J2Y", "#R2Y"]

        self.assertEqual([row["tag"] for row in member._accounts(current)], order)
        menu = member._components("audit", current)[0].components[0]
        self.assertEqual([option.value for option in menu.options], order)
        current.screen = "review"
        current.selected = set(order)
        review = member._main_text(current)
        names = ["High A", "High B", "Low", "Invalid", "Unknown"]
        positions = [review.index(name) for name in names]
        self.assertEqual(positions, sorted(positions))

    def test_linked_unverified_fwa_account_still_uses_lazy_only(self):
        current = session(screen="select_accounts", accounts=[
            {"tag": "#P2Y", "name": "FWA", "verified": False, "town_hall": 16,
             "current_clan_tag": "#R2Y", "current_clan_type": "FWA",
             "family_clan_status": "approved"},
        ])
        current.pool = "main"
        self.assertEqual(member._eligible_accounts(current), [])
        current.pool = "lazy"
        self.assertEqual([row["tag"] for row in member._eligible_accounts(current)], ["#P2Y"])

    async def test_over_limit_select_keeps_every_prior_choice(self):
        accounts = [{"tag": f"#P{i:03d}", "name": f"Player {i}", "verified": True}
                    for i in range(101)]
        current = session(screen="select_accounts", accounts=accounts)
        current.pool = "lazy"
        current.page = 6
        current.selected = {row["tag"] for row in accounts[:99]}
        original = current.selected.copy()
        member._sessions["audit"] = current
        ctx = Context(values=tuple(row["tag"] for row in accounts[90:101]))

        await member._handle(ctx, "audit:0", "select")

        self.assertEqual(current.selected, original)
        panel = ctx.edits[-1]["components"][0]
        self.assertIn("100 accounts", panel.components[0].content)

    async def test_new_season_refresh_discards_old_selection_and_confirmation(self):
        current = session(screen="select_accounts", season_id=1,
                          accounts=[{"tag": "#P2Y", "name": "Player", "verified": True}])
        current.pool = "lazy"
        current.selected = {"#P2Y"}
        current.pending_tag = "#P2Y"
        current.pending_pool = "main"
        current.source_pools = {"#P2Y": "lazy"}
        member._sessions["audit"] = current
        actions = []

        async def request(action, **_kwargs):
            actions.append(action)
            return {**current.view,
                    "season": {"id": 2, "label": "November", "signup_open": True, "status": "draft"},
                    "accounts": [{"tag": "#P2Y", "name": "Player", "verified": True}]}

        with patch("utils.cwl_member_client.request", request):
            await member._handle(Context(), "audit:0", "refresh")
            await member._handle(Context(), "audit:0", "confirm")

        self.assertEqual(actions, ["view"])
        self.assertEqual(current.screen, "home")
        self.assertEqual(current.view["season"]["id"], 2)
        self.assertEqual(current.selected, set())
        self.assertEqual(current.source_pools, {})
        self.assertIsNone(current.pending_tag)
        self.assertIsNone(current.pending_pool)
        self.assertIsNone(current.pool)

    async def test_signup_from_old_home_requires_review_of_new_season(self):
        current = session(screen="home", season_id=1)
        member._sessions["audit"] = current
        actions = []

        async def request(action, **_kwargs):
            actions.append(action)
            return {**current.view,
                    "season": {"id": 2, "label": "November", "signup_open": True, "status": "draft"},
                    "accounts": [{"tag": "#P2Y", "name": "Player", "verified": True}]}

        with patch("utils.cwl_member_client.request", request):
            ctx = Context()
            await member._handle(ctx, "audit:0", "signup")

        self.assertEqual(actions, ["view"])
        self.assertEqual(current.screen, "home")
        self.assertEqual(current.view["season"]["id"], 2)
        panel = ctx.edits[-1]["components"][0]
        self.assertIn("November", panel.components[0].content)
        self.assertIn("season changed", panel.components[0].content.lower())

    async def test_pool_change_holds_when_linked_accounts_unavailable(self):
        current = session(screen="signup_action")
        current.pending_tag = "#P2Y"
        current.source_pools = {"#P2Y": "lazy"}
        current.view["signups"] = [{"tag": "#P2Y", "pool": "lazy", "player_name": "Player"}]
        member._sessions["audit"] = current
        actions = []

        async def request(action, **_kwargs):
            actions.append(action)
            return {**current.view, "accounts_status": "unavailable", "accounts": []}

        with patch("utils.cwl_member_client.request", request):
            ctx = Context()
            await member._handle(ctx, "audit:0", "change_pool")

        self.assertEqual(actions, ["view"])
        self.assertEqual(current.screen, "signup_action")
        panel = ctx.edits[-1]["components"][0]
        self.assertIn("unavailable", panel.components[0].content.lower())

    async def test_legacy_entry_edit_serializes_valid_v2_conversion(self):
        current = session()
        ctx = Context()
        ctx.interaction.message = type("Message", (), {"flags": hikari.MessageFlag(0)})()

        await member._edit(ctx, "audit", current)

        edit = ctx.edits[-1]
        self.assertIsNone(edit["content"])
        self.assertEqual(edit["embeds"], [])
        # Verify Hikari's real serialization path sets the required flag when
        # converting an existing legacy message to a V2 container.
        rest = object.__new__(RESTClientImpl)
        body, form = rest._build_message_payload(edit=True, **edit)
        self.assertIsNone(form)
        self.assertTrue(body["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2)
        self.assertIsNone(body["content"])
        self.assertEqual(body["embeds"], [])
        self.assertEqual(body["components"][0]["type"], hikari.ComponentType.CONTAINER)

    async def test_ambiguous_edit_after_save_does_not_repeat_write(self):
        current = session(screen="review", accounts=[
            {"tag": "#P2Y", "name": "Player", "verified": True}])
        current.pool = "lazy"
        current.selected = {"#P2Y"}
        member._sessions["audit"] = current
        actions = []

        async def request(action, **_kwargs):
            actions.append(action)
            return current.view

        with patch("utils.cwl_member_client.request", request):
            first = Context(edit_error=RuntimeError("edit response lost"))
            await member._handle(first, "audit:0", "confirm")
            retry = Context()
            await member._handle(retry, "audit:0", "confirm")

        self.assertEqual(actions.count("submit"), 1)
        self.assertIn("fresh private panel", first.responses[0][0][0])
        self.assertTrue(retry.responses)
        self.assertIn("expired or changed", retry.responses[0][0][0])


class MemberOwnershipAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_unverified_link_cannot_spoof_unlinked_tag_and_fwa_stays_lazy(self):
        class Provider:
            async def linked_tags(self, user_id):
                return {"#P2Y": False} if user_id == "123" else {}

            async def player(self, tag):
                return {"tag": tag, "name": "Player", "town_hall": 16,
                        "current_clan_tag": "#R2Y", "current_clan_name": "FWA Family"}

            async def family_clans(self):
                return {"status": "ok", "clans": [
                    {"tag": "#R2Y", "name": "FWA Family", "type": "FWA"}]}

        with tempfile.TemporaryDirectory() as directory:
            store = Store(f"{directory}/cwl.sqlite")
            with store.tx() as db:
                db.execute("INSERT INTO seasons(label, signup_open) VALUES ('October', 1)")
                season_id = db.execute("SELECT id FROM seasons").fetchone()[0]
                db.execute("UPDATE member_season SET season_id=? WHERE id=1", (season_id,))
            fields = {"tag": "#P2Y", "prefer_crystal_1_or_lower": False}
            with self.assertRaises(MemberError) as fwa:
                await submit(store, Provider(), season_id, "123", "main", [fields],
                             verified_only=False, expected_revision=0)
            self.assertEqual(fwa.exception.status, 409)
            saved = await submit(store, Provider(), season_id, "123", "lazy", [fields],
                                 verified_only=False, expected_revision=0)
            self.assertEqual(saved["count"], 1)
            with self.assertRaises(MemberError) as spoof:
                await submit(store, Provider(), season_id, "123", "lazy",
                             [{"tag": "#Q2Y", "prefer_crystal_1_or_lower": False}],
                             verified_only=False, expected_revision=1)
            self.assertEqual(spoof.exception.status, 403)
            self.assertEqual(
                [dict(row) for row in store.rows("SELECT tag,user_id,pool FROM signups")],
                [{"tag": "#P2Y", "user_id": "123", "pool": "lazy"}],
            )


if __name__ == "__main__":
    unittest.main()

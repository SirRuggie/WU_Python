"""Isolated classification evidence for the parked, unapproved alignment."""
import unittest
from unittest.mock import AsyncMock

from utils.cwl_member_service import accounts_for_member


class ClanTypeAlignmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_cwl_and_legacy_competitive_accounts_keep_saved_type(self):
        for kind in ("CWL", "Competitive"):
            with self.subTest(kind=kind):
                provider = AsyncMock()
                provider.linked_tags.return_value = {"#P2Y": True}
                provider.player.return_value = {"tag": "#P2Y", "current_clan_tag": "#R2Y"}
                provider.family_clans.return_value = {"status": "ok", "clans": [
                    {"tag": "#R2Y", "name": "Fixture family", "type": kind}
                ]}
                accounts = await accounts_for_member(provider, "fixture-user")
                self.assertEqual(accounts[0]["family_clan_status"], "approved")
                self.assertEqual(accounts[0]["current_clan_type"], kind)

"""Review136 regressions: preserve metadata and saved-lineup routing."""

import asyncio
import unittest
from unittest.mock import AsyncMock
import pytest
import test_last_war_weights as previous

ledger = previous.ledger
lineup = previous.lineup


@pytest.mark.parametrize("lineup_known", [False, True])
def test_departed_metadata_prefers_lineup_then_ledger_on_display_and_write(
    ledger, lineup_known
):
    store, weights = ledger
    roster = {
        "tag": "#R2Y",
        "name": "Family",
        "members": [
            {
                "tag": "#G2Y",
                "name": "Ace" if not lineup_known else "#G2Y",
                "town_hall": 16 if not lineup_known else None,
            }
        ],
    }
    weights.save(
        roster,
        [{"tag": "#G2Y", "weight": 150000, "storages": 5, "revision": 0}],
        "owner",
    )
    weights.remember_lineup("#R2Y", lineup(details=lineup_known))
    departed = {**roster, "members": []}
    row = next(r for r in weights.members_with_lineups(departed) if r["tag"] == "#G2Y")
    expected = ("Saved #G2Y", 15) if lineup_known else ("Ace", 16)
    assert (row["name"], row["town_hall"]) == expected
    weights.save(
        departed,
        [{"tag": "#G2Y", "weight": 155000, "storages": 5, "revision": 1}],
        "owner",
    )
    saved = weights.for_members(["#G2Y"])["#G2Y"]
    assert (saved["player_name"], saved["town_hall"]) == expected
    # A later payload containing only a blank/tag must never erase known metadata.
    weights.save(
        {**roster, "members": [{"tag": "#G2Y", "name": "#G2Y", "town_hall": None}]},
        [{"tag": "#G2Y", "weight": 160000, "storages": 5, "revision": 2}],
        "owner",
    )
    saved = weights.for_members(["#G2Y"])["#G2Y"]
    assert (saved["player_name"], saved["town_hall"]) == expected


def test_same_war_cannot_remove_previously_saved_people(ledger):
    _, weights = ledger
    tags = ("#G2Y", "#P2Y", "#Q2Y", "#L2Y", "#V2Y", "#R2Y", "#J2Y")
    weights.remember_lineup("#R2Y", lineup(players=tags))
    with pytest.raises(ValueError, match="Incomplete"):
        weights.remember_lineup("#R2Y", lineup(players=tags[:2], state="warEnded"))
    assert set(weights.saved_lineup("#R2Y")["order"]) == set(tags)


class ColdRosterLineupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = previous.LastWarWeightsTests.asyncSetUp
    asyncTearDown = previous.LastWarWeightsTests.asyncTearDown
    auth = previous.LastWarWeightsTests.auth
    call = previous.LastWarWeightsTests.call
    roster = previous.LastWarWeightsTests.roster
    save = previous.LastWarWeightsTests.save
    open_lineup = previous.LastWarWeightsTests.open_lineup

    async def test_background_first_load_routes_departed_signup_from_saved_lineup(self):
        import test_cwl_web_foundation as foundation

        await self.open_lineup(lineup(details=False))
        self.providers.players["#G2Y"]["current_clan_tag"] = "#J2Y"
        sid = await foundation.WebFoundationTests.season(self)
        response = await self.call(
            "POST",
            f"/seasons/{sid}/signups",
            self.other,
            json={
                "pool": "lazy",
                "accounts": [{"tag": "#G2Y", "prefer_crystal_1_or_lower": False}],
            },
        )
        assert response.status == 200
        self.app.pop("roster_family_snapshot", None)
        from cwl_web.providers import ProviderUnavailable

        original = self.providers.family_clans
        self.providers.family_clans = AsyncMock(
            side_effect=ProviderUnavailable("cold directory")
        )
        response = await self.call(
            "GET", f"/seasons/{sid}/roster?background=1", self.owner
        )
        assert response.status == 200
        cold = next(
            r for r in (await response.json())["accounts"] if r["tag"] == "#G2Y"
        )
        assert cold["weight_lineup_clan_tag"] == "#R2Y"
        assert cold["current_fwa_clan_tag"] is None
        self.providers.family_clans = original
        self.app.pop("roster_family_snapshot", None)
        response = await self.call(
            "GET", f"/seasons/{sid}/roster?background=1", self.owner
        )
        warm = next(
            r for r in (await response.json())["accounts"] if r["tag"] == "#G2Y"
        )
        assert warm["weight_lineup_clan_tag"] == "#R2Y"

    async def test_saved_player_creation_rechecks_fresh_fwa_family_after_capture(self):
        await self.open_lineup()
        self.providers.family_clans.return_value = {
            "clans": [{"tag": "#R2Y", "name": "Former family FWA", "type": "Tactical"}]
        }
        response = await self.call(
            "PUT",
            "/weight-trial/saved-players/%23G2Y",
            self.owner,
            json={"weight": 150000, "storages": 5, "revision": 0},
        )
        assert response.status == 409
        assert self.app["clan_weight_trial"].all() == []

    async def test_legacy_lineup_keeps_known_metadata_through_save_find_and_export(
        self,
    ):
        from io import BytesIO
        from openpyxl import load_workbook

        self.roster(members=[{"tag": "#G2Y", "name": "Ace", "town_hall": 16}])
        assert (
            await self.save(
                [{"tag": "#G2Y", "weight": 150000, "storages": 5, "revision": 0}]
            )
        ).status == 200
        result = await self.open_lineup(lineup(details=False))
        row = next(r for r in result["weight_members"] if r["tag"] == "#G2Y")
        assert (
            row["name"],
            row["town_hall"],
            row["saved_name"],
            row["saved_town_hall"],
        ) == ("Ace", 16, "Ace", 16)
        assert (
            await self.save(
                [{"tag": "#G2Y", "weight": 155000, "storages": 5, "revision": 1}]
            )
        ).status == 200
        search = await (
            await self.call("GET", "/weight-trial/saved-players?q=Ace", self.owner)
        ).json()
        assert (
            search["players"][0]["name"] == "Ace"
            and search["players"][0]["town_hall"] == 16
        )
        sheet = load_workbook(
            BytesIO(
                await (
                    await self.call("GET", "/weight-trial/export.xlsx", self.owner)
                ).read()
            )
        ).active
        assert (sheet["A2"].value, sheet["B2"].value, sheet["C2"].value) == (
            "#G2Y",
            "Ace",
            16,
        )

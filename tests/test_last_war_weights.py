"""Two saved wars grant bounded weight-edit eligibility, never client lists."""

import json
import sqlite3
import unittest
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook

import test_clan_weight_trial as trial
import test_cwl_web_foundation as foundation
from cwl_web.providers import ProviderUnavailable
from cwl_web.store import Store
from utils.clan_weight_store import ClanWeightStore, WeightConflict


def lineup(day=2, players=("#G2Y", "#P2Y"), *, state="inWar", details=True):
    value = {
        "order": {tag: i + 1 for i, tag in enumerate(players)},
        "state": state,
        "end_time": f"202611{day:02d}T070000.000Z",
        "opponent": "Fixture opponent",
    }
    if details:
        value.update(
            names={tag: f"Saved {tag}" for tag in players},
            town_halls={tag: 15 for tag in players},
        )
    return value


@pytest.fixture
def ledger(tmp_path):
    store = Store(tmp_path / "weights.sqlite")
    return store, ClanWeightStore(store.path, transaction_factory=store.tx)


def test_two_latest_rotation_same_war_progress_and_stale_older_capture(ledger):
    store, weights = ledger
    weights.remember_lineup("#R2Y", lineup(2))
    original = store.rows("SELECT * FROM clan_weight_war_lineups")
    weights.remember_lineup("#R2Y", lineup(3, ("#Q2Y",)))
    assert [war["end_time"] for war in weights.saved_lineups("#R2Y")] == [
        "20261103T070000.000Z",
        "20261102T070000.000Z",
    ]
    weights.remember_lineup("#R2Y", lineup(4, ("#L2Y",)))
    weights.remember_lineup("#R2Y", lineup(1, ("#V2Y",)))
    weights.remember_lineup("#R2Y", lineup(4, ("#L2Y",), state="warEnded"))
    weights.remember_lineup("#R2Y", lineup(4, ("#L2Y",), state="preparation"))
    wars = ClanWeightStore(store.path).saved_lineups("#R2Y")
    assert [war["end_time"] for war in wars] == [
        "20261104T070000.000Z",
        "20261103T070000.000Z",
    ]
    assert wars[0]["state"] == "warEnded"
    assert len(store.rows("SELECT * FROM clan_weight_war_lineup_previous")) == 1
    assert original[0]["lineup_json"] == json.dumps(lineup(2), sort_keys=True)


def test_same_war_omitted_optional_metadata_does_not_erase_known_details(ledger):
    _, weights = ledger
    weights.remember_lineup("#R2Y", lineup())
    weights.remember_lineup("#R2Y", lineup(state="warEnded", details=False))
    saved = weights.saved_lineup("#R2Y")
    assert saved["names"]["#G2Y"] == "Saved #G2Y"
    assert saved["town_halls"]["#G2Y"] == 15


@pytest.mark.parametrize(
    "mutation", ["gap", "partial", "bad_th", "bad_names", "no_identity"]
)
def test_bad_lineup_never_clears_either_saved_war(ledger, mutation):
    _, weights = ledger
    weights.remember_lineup("#R2Y", lineup(2))
    weights.remember_lineup("#R2Y", lineup(3))
    before = weights.saved_lineups("#R2Y")
    bad = lineup(4)
    if mutation == "gap":
        bad["order"]["#G2Y"] = 7
    elif mutation == "partial":
        bad["order"] = {}
    elif mutation == "bad_th":
        bad["town_halls"]["#G2Y"] = True
    elif mutation == "bad_names":
        bad["names"] = ["not a mapping"]
    else:
        bad["end_time"] = None
    if mutation == "no_identity":
        weights.remember_lineup("#R2Y", bad)
    else:
        with pytest.raises(ValueError):
            weights.remember_lineup("#R2Y", bad)
    assert weights.saved_lineups("#R2Y") == before


def test_additive_migration_preserves_single_legacy_row_and_old_four_column_write(
    tmp_path,
):
    path = tmp_path / "old.sqlite"
    payload = json.dumps(lineup())
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE clan_weight_war_lineups (clan_tag TEXT PRIMARY KEY,end_time TEXT NOT NULL,captured_at TEXT NOT NULL,lineup_json TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO clan_weight_war_lineups VALUES(?,?,?,?)",
            ("#R2Y", "2026-11-02T07:00:00+00:00", "2026-11-01T00:00:00Z", payload),
        )
        before = db.execute("SELECT * FROM clan_weight_war_lineups").fetchall()
    weights = ClanWeightStore(path)
    assert len(weights.saved_lineups("#R2Y")) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM clan_weight_war_lineups").fetchall() == before
        assert (
            db.execute(
                "SELECT count(*) FROM clan_weight_war_lineup_previous"
            ).fetchone()[0]
            == 0
        )
        # Old code's four-value latest-lineup write is still compatible on rollback.
        db.execute(
            "INSERT OR REPLACE INTO clan_weight_war_lineups VALUES(?,?,?,?)", before[0]
        )
    assert weights.saved_lineup("#R2Y")["order"] == lineup()["order"]


class LastWarWeightsTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = trial.WeightTrialTests.asyncSetUp
    asyncTearDown = trial.WeightTrialTests.asyncTearDown
    auth = trial.WeightTrialTests.auth
    call = trial.WeightTrialTests.call
    roster = trial.WeightTrialTests.roster
    save = trial.WeightTrialTests.save

    async def open_lineup(self, value=None, members=None):
        self.roster(
            members=(
                members
                if members is not None
                else [{"tag": "#P2Y", "name": "Current", "town_hall": 16}]
            )
        )
        self.providers.weight_war_lineup = AsyncMock(return_value=value or lineup())
        response = await self.call("GET", "/weight-trial/clans/%23R2Y", self.owner)
        assert response.status == 200
        return await response.json()

    async def test_departed_lineup_player_save_reload_history_roster_and_export(self):
        result = await self.open_lineup()
        departed = next(row for row in result["weight_members"] if row["tag"] == "#G2Y")
        assert (
            departed["name"],
            departed["town_hall"],
            departed["storages"],
            departed["current_member"],
        ) == ("Saved #G2Y", 15, 5, False)
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
        saved = await self.save(
            [{"tag": "#G2Y", "weight": 150000, "storages": 5, "revision": 0}]
        )
        assert saved.status == 200
        row = next(
            row
            for row in (await saved.json())["weight_members"]
            if row["tag"] == "#G2Y"
        )
        assert row["weight"] == 150000 and row["revision"] == 1
        history = self.app["store"].one(
            "SELECT * FROM clan_player_weight_history WHERE tag='#G2Y'"
        )
        assert (
            history["actor_id"] == "505227988229554179"
            and history["source"] == "Clan weights"
        )
        assert history["storages"] == 5 and history["clan_tag"] == "#R2Y"
        latest = await (
            await self.call("GET", f"/seasons/{sid}/roster", self.owner)
        ).json()
        account = next(row for row in latest["accounts"] if row["tag"] == "#G2Y")
        assert (
            account["effective_weight"] == 150000
            and account["weight_lineup_clan_tag"] == "#R2Y"
        )
        assert account["current_fwa_clan_tag"] is None
        self.providers.weight_war_lineup.side_effect = ProviderUnavailable("private")
        reload = await (
            await self.call("GET", "/weight-trial/clans/%23R2Y", self.owner)
        ).json()
        assert (
            next(row for row in reload["weight_members"] if row["tag"] == "#G2Y")[
                "weight"
            ]
            == 150000
        )
        progress = await (
            await self.call("GET", "/weight-trial/clans", self.owner)
        ).json()
        assert (
            progress["clans"][0]["members_count"],
            progress["clans"][0]["weighed_count"],
        ) == (2, 1)
        sheet = load_workbook(
            BytesIO(
                await (
                    await self.call("GET", "/weight-trial/export.xlsx", self.owner)
                ).read()
            )
        ).active
        assert sheet["A2"].value == "#G2Y" and sheet["E2"].value == 150000

    async def test_unknown_departed_details_never_guess_storages(self):
        result = await self.open_lineup(lineup(details=False))
        row = next(row for row in result["weight_members"] if row["tag"] == "#G2Y")
        assert (
            row["name"] == "#G2Y"
            and row["town_hall"] is None
            and row["storages"] is None
        )

    async def test_previous_only_eligibility_cas_idempotent_replay_and_two_staff(self):
        await self.open_lineup()
        await self.open_lineup(lineup(3, ("#P2Y",)))
        item = {"tag": "#G2Y", "weight": 150000, "storages": 5, "revision": 0}
        assert (await self.save([item])).status == 200
        assert (await self.save([item])).status == 200
        assert (
            len(self.app["store"].rows("SELECT * FROM clan_player_weight_history")) == 1
        )
        assert (await self.save([{**item, "weight": 160000}])).status == 409
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO grants(user_id,granted_by,permissions) VALUES('200','owner','[\"clans\"]')"
            )
        response = await self.save(
            [{**item, "revision": 1, "weight": 160000}], self.other
        )
        assert response.status == 200
        assert (
            await self.save([{**item, "revision": 1, "weight": 170000}])
        ).status == 409
        assert (
            self.app["store"].rows(
                "SELECT actor_id FROM clan_player_weight_history ORDER BY id"
            )[-1]["actor_id"]
            == "200"
        )

    async def test_stale_page_third_war_removes_creation_rights_not_saved_weights(self):
        await self.open_lineup()
        await self.open_lineup(lineup(3, ("#Q2Y",)))
        shown = await (
            await self.call("GET", "/weight-trial/clans/%23R2Y", self.owner)
        ).json()
        assert any(row["tag"] == "#G2Y" for row in shown["weight_members"])
        self.app["clan_weight_trial"].remember_lineup("#R2Y", lineup(4, ("#L2Y",)))
        response = await self.save([{"tag": "#G2Y", "weight": 150000, "revision": 0}])
        assert response.status == 409
        assert self.app["clan_weight_trial"].all() == []

    async def test_random_tags_missing_lineup_family_loss_and_membership_failure_refuse(
        self,
    ):
        self.roster()
        for tag in ("#G2Y", "#V2Y"):
            assert (
                await self.save([{"tag": tag, "weight": 150000, "revision": 0}])
            ).status == 409
        await self.open_lineup()
        self.providers.family_clans.return_value = {"clans": []}
        assert (
            await self.save([{"tag": "#G2Y", "weight": 150000, "revision": 0}])
        ).status == 404
        self.providers.family_clans.return_value = {
            "clans": [{"tag": "#R2Y", "name": "Family", "type": "FWA"}]
        }
        self.providers.clan_roster.side_effect = ProviderUnavailable("offline")
        assert (
            await self.save([{"tag": "#G2Y", "weight": 150000, "revision": 0}])
        ).status == 503
        assert self.app["clan_weight_trial"].all() == []

    async def test_never_saved_player_endpoint_only_allows_fresh_family_lineup(self):
        await self.open_lineup()
        body = {"weight": 150000, "storages": 5, "revision": 0}
        assert (
            await self.call(
                "PUT", "/weight-trial/saved-players/%23V2Y", self.owner, json=body
            )
        ).status == 409
        assert (
            await self.call(
                "PUT", "/weight-trial/saved-players/%23G2Y", self.owner, json=body
            )
        ).status == 200
        assert self.app["clan_weight_trial"].all()[0]["last_clan_tag"] == "#R2Y"

    async def test_client_cannot_supply_membership_or_lineup_or_partial_batch(self):
        await self.open_lineup()
        item = {"tag": "#V2Y", "weight": 150000, "revision": 0}
        for body in (
            [item],
            {
                "changes": [item],
                "members": [{"tag": "#V2Y", "name": "Forged", "town_hall": 16}],
            },
            {"changes": [item], "war_order": {"#V2Y": 1}},
        ):
            response = await self.call(
                "PUT", "/weight-trial/clans/%23R2Y", self.owner, json=body
            )
            assert response.status == 400
        response = await self.save(
            [{"tag": "#G2Y", "weight": 150000, "revision": 0}, item]
        )
        assert response.status == 409
        assert self.app["clan_weight_trial"].all() == []
        assert self.app["store"].rows("SELECT * FROM clan_player_weight_history") == []

    async def test_partial_or_invalid_war_retains_two_lineups_and_cold_failure_has_no_order(
        self,
    ):
        await self.open_lineup()
        await self.open_lineup(lineup(3, ("#P2Y",)))
        before = self.app["clan_weight_trial"].saved_lineups("#R2Y")
        self.providers.weight_war_lineup.return_value = {
            **lineup(4),
            "order": {"#G2Y": 7},
        }
        result = await (
            await self.call("GET", "/weight-trial/clans/%23R2Y", self.owner)
        ).json()
        assert result["war_source"]["cached"] is True
        assert result["war_order"] == before[0]["order"]
        assert self.app["clan_weight_trial"].saved_lineups("#R2Y") == before
        with self.app["store"].tx() as db:
            db.execute("DELETE FROM clan_weight_war_lineup_previous")
            db.execute("DELETE FROM clan_weight_war_lineups")
        result = await (
            await self.call("GET", "/weight-trial/clans/%23R2Y", self.owner)
        ).json()
        assert result["war_order"] is None and result["war_lineups"] == []

    async def test_full_current_and_two_war_union_can_save_atomically_with_bounded_size(
        self,
    ):
        def player_tag(n):
            return "#P" + "".join("0289PYLQGR"[int(d)] for d in str(n).zfill(5)) + "Y"

        current = [player_tag(n) for n in range(50)]
        latest = tuple(player_tag(n) for n in range(50, 100))
        previous = tuple(player_tag(n) for n in range(100, 150))
        self.roster(
            members=[{"tag": tag, "name": tag, "town_hall": 16} for tag in current]
        )
        weights = self.app["clan_weight_trial"]
        weights.remember_lineup("#R2Y", lineup(1, previous))
        weights.remember_lineup("#R2Y", lineup(2, latest))
        changes = [
            {"tag": tag, "weight": 150000, "storages": 5, "revision": 0}
            for tag in [*current, *latest, *previous]
        ]
        response = await self.save(changes)
        assert response.status == 200
        data = await response.json()
        assert len(data["members"]) == 50 and len(data["weight_members"]) == 150
        assert len(weights.all()) == 150
        assert (
            len(self.app["store"].rows("SELECT * FROM clan_player_weight_history"))
            == 150
        )
        assert (
            await self.save(
                [*changes, {"tag": "#V2Y", "weight": 150000, "revision": 0}]
            )
        ).status == 400
        assert (
            len(self.app["store"].rows("SELECT * FROM clan_player_weight_history"))
            == 150
        )


@pytest.mark.parametrize("town_hall", [None, 15, True, 100, "15"])
def test_public_war_parser_keeps_optional_th_without_fabricating_it(town_hall):
    import asyncio
    from unittest.mock import patch
    from cwl_web.providers import LiveProviders
    from test_cwl_web_league_provider import Response

    member = {"tag": "#G2Y", "mapPosition": 1, "name": "Saved war name"}
    if town_hall is not None:
        member["townhallLevel"] = town_hall
    body = {
        "state": "inWar",
        "endTime": "20261102T070000.000Z",
        "teamSize": 1,
        "clan": {"tag": "#R2Y", "members": [member]},
    }

    class HTTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def get(self, url, **kwargs):
            assert url.endswith("/currentwar")
            return Response(body)

    provider = LiveProviders(coc_token="fixture", mongo_uri="", routes={})
    with patch(
        "cwl_web.providers.aiohttp.ClientSession", side_effect=lambda **kw: HTTP()
    ):
        if town_hall is not None and (
            type(town_hall) is not int or not 0 < town_hall < 100
        ):
            with pytest.raises(ProviderUnavailable):
                asyncio.run(provider.weight_war_lineup("#R2Y"))
        else:
            parsed = asyncio.run(provider.weight_war_lineup("#R2Y"))
            assert parsed["town_halls"] == ({"#G2Y": 15} if town_hall == 15 else {})
            assert parsed["names"] == {"#G2Y": "Saved war name"}


@pytest.mark.parametrize("field", ["names", "town_halls"])
@pytest.mark.parametrize("value", [[], False, 0, ""])
def test_optional_metadata_rejects_nonmapping_falsey_values_without_mutation(
    ledger, field, value
):
    _, weights = ledger
    weights.remember_lineup("#R2Y", lineup())
    before = weights.saved_lineups("#R2Y")
    with pytest.raises(ValueError):
        weights.remember_lineup("#R2Y", {**lineup(3), field: value})
    assert weights.saved_lineups("#R2Y") == before

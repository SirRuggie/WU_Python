"""Read-only Clash CWL endpoint adapter tests; all responses are injected."""

import asyncio
import json
import unittest
from unittest.mock import patch

from cwl_web.providers import FixtureProviders, LiveProviders, ProviderUnavailable


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.body


class Session:
    def __init__(self, responses, calls):
        self.responses = list(responses)
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class LeagueProviderTests(unittest.IsolatedAsyncioTestCase):
    def make_provider(self):
        return LiveProviders(coc_token="test-token", mongo_uri="", routes={})

    async def test_group_preserves_round_order_and_zero_placeholders(self):
        payload = {
            "state": "inWar", "season": "2026-10", "clans": [
                {"tag": "#R2Y", "name": "Example", "members": [
                    {"tag": "#P2Y", "name": "Player", "townHallLevel": 16},
                ]},
            ],
            "rounds": [
                {"warTags": ["#C2Y"]}, {"warTags": ["#0"]},
                {"warTags": ["#V2Y"]},
            ],
        }
        calls = []
        with patch("cwl_web.providers.aiohttp.ClientSession",
                   side_effect=lambda **kw: Session([Response(payload)], calls)):
            result = await self.make_provider().league_group("R2Y")
        self.assertEqual(result["tag"], "#R2Y")
        self.assertEqual(result["state"], "WAR")
        self.assertEqual(result["rounds"], [
            {"war_tags": ["#C2Y"]}, {"war_tags": ["#0"]},
            {"war_tags": ["#V2Y"]},
        ])
        self.assertEqual(result["clans"][0]["members"][0]["town_hall"], 16)
        url, kwargs = calls[0]
        self.assertEqual(url, "https://api.clashofclans.com/v1/clans/%23R2Y/currentwar/leaguegroup")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")

    async def test_war_normalizes_both_sides_and_preserves_missing_attacks_as_unknown(self):
        payload = {
            "state": "warEnded", "teamSize": 15, "preparationStartTime": "20261001T000000.000Z",
            "startTime": "20261002T000000.000Z", "endTime": "20261003T000000.000Z",
            "clan": {"tag": "#R2Y", "name": "Example", "members": [
                {"tag": "#P2Y", "name": "Attacked", "townhallLevel": 16,
                 "attacks": [{"stars": 2}, {"stars": 3}], "opponentAttacks": 1},
                {"tag": "#Q2Y", "name": "Pending", "townhallLevel": 15},
            ]},
            "opponent": {"tag": "#J2Y", "name": "Rival", "members": [
                {"tag": "#G2Y", "name": "Zero attacks", "attacks": []},
            ]},
        }
        calls = []
        with patch("cwl_web.providers.aiohttp.ClientSession",
                   side_effect=lambda **kw: Session([Response(payload)], calls)):
            result = await self.make_provider().league_war("C2Y")
        self.assertEqual(result["state"], "ENDED")
        self.assertEqual(result["team_size"], 15)
        self.assertEqual(result["clan"]["members"][0]["attacks"], [{"stars": 2}, {"stars": 3}])
        self.assertEqual(result["clan"]["members"][1]["attacks"], [])
        self.assertEqual(result["opponent"]["members"][0]["attacks"], [])
        self.assertEqual(calls[0][0], "https://api.clashofclans.com/v1/clanwarleagues/wars/%23C2Y")

    async def test_missing_attacks_during_preparation_remain_pending(self):
        payload = {
            "state": "PREPARATION",
            "clan": {"tag": "#R2Y", "name": "Example", "members": [
                {"tag": "#P2Y", "name": "Pending"},
            ]},
            "opponent": {"tag": "#J2Y", "name": "Rival", "members": []},
        }
        with patch("cwl_web.providers.aiohttp.ClientSession",
                   side_effect=lambda **kw: Session([Response(payload)], [])):
            result = await self.make_provider().league_war("#C2Y")
        self.assertIsNone(result["clan"]["members"][0]["attacks"])

    async def test_http_status_is_available_without_exposing_error_body(self):
        calls = []
        payload = {"message": "contains private details"}
        with patch("cwl_web.providers.aiohttp.ClientSession",
                   side_effect=lambda **kw: Session([Response(payload, status=403)], calls)):
            with self.assertRaises(ProviderUnavailable) as caught:
                await self.make_provider().league_group("#R2Y")
        self.assertEqual(caught.exception.status_code, 403)
        self.assertNotIn("private details", str(caught.exception))
        self.assertNotIn("test-token", str(caught.exception))

    async def test_malformed_round_or_attack_data_fails_closed(self):
        bad_group = {"state": "WAR", "season": "2026-10", "clans": [],
                     "rounds": [{"warTags": ["not a tag"]}]}
        bad_war = {"state": "WAR", "clan": {"tag": "#R2Y", "name": "A", "members": [
                       {"tag": "#P2Y", "name": "P", "attacks": [{"stars": 4}]},
                   ]},
                   "opponent": {"tag": "#J2Y", "name": "B", "members": []}}
        with patch("cwl_web.providers.aiohttp.ClientSession",
                   side_effect=lambda **kw: Session([Response(bad_group)], [])):
            with self.assertRaises(ProviderUnavailable):
                await self.make_provider().league_group("#R2Y")
        with patch("cwl_web.providers.aiohttp.ClientSession",
                   side_effect=lambda **kw: Session([Response(bad_war)], [])):
            with self.assertRaises(ProviderUnavailable):
                await self.make_provider().league_war("#C2Y")

    async def test_fixture_provider_does_not_invent_league_results(self):
        fixture = FixtureProviders("owner")
        with self.assertRaises(ProviderUnavailable):
            await fixture.league_group("#R2Y")
        with self.assertRaises(ProviderUnavailable):
            await fixture.league_war("#C2Y")


if __name__ == "__main__":
    unittest.main()

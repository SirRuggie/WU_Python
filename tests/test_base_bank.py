from types import SimpleNamespace
from unittest.mock import AsyncMock
import unittest
from utils.base_bank import FWA_TH_LEVELS, public_bases, https_url
import test_cwl_web_roster as fixture

LINK = "https://link.clashofclans.com/en?action=OpenLayout&id=TH18%3AWB%3Afixture"


def test_all_supported_variants_mapping_and_field_allowlist():
    config = {
        name: {
            key: LINK if name == "fwa_base_links" else "https://images.example/base.png"
            for key in FWA_TH_LEVELS
        }
        for name in ("fwa_base_links", "war_base_images")
    }
    config["staff_secret"] = "never expose"
    config["active_base_images"] = {"th18": "https://images.example/wrong.png"}
    rows, details = public_bases(config)
    assert len(rows) == len(FWA_TH_LEVELS)
    for row in rows:
        assert set(row) == {
            "key",
            "town_hall",
            "variant",
            "link",
            "war_base_image",
            "has_details",
        }
        assert row["variant"] == (
            "non-merged" if row["key"].endswith("_new") else "merged"
        )
        assert row["war_base_image"] == "https://images.example/base.png"
    assert [r["key"] for r in rows[:2]] == ["th18", "th18_new"]
    assert "staff_secret" not in repr(rows) + repr(details)


def test_missing_and_malformed_fields_never_invent_base_links():
    assert public_bases(None) == ([], {})
    assert public_bases({"fwa_base_links": {"th18": "https://evil.example/"}}) == (
        [],
        {},
    )
    rows, details = public_bases(
        {
            "war_base_images": {"th18": "https://images.example/base.png"},
            "base_information": {"th18": {"secret": "never"}},
        }
    )
    assert rows[0]["link"] is None and not rows[0]["has_details"]
    assert details["th18"]["base_information"] == ""
    rows, _ = public_bases({"base_information": {"th17": "Some details"}})
    assert rows[0]["war_base_image"] is None and rows[0]["has_details"]
    for bad in (
        "javascript:alert(1)",
        "http://link.clashofclans.com/?action=OpenLayout&id=x",
        "https://link.clashofclans.com.evil/en?action=OpenLayout&id=x",
        "https://user@link.clashofclans.com/en?action=OpenLayout&id=x",
        "https://link.clashofclans.com/en?action=OpenClanProfile&id=x",
    ):
        assert https_url(bad, clash=True) is None


class BaseBankHTTP(unittest.IsolatedAsyncioTestCase):
    auth = fixture.RosterTests.auth
    call = fixture.RosterTests.call
    revision = fixture.RosterTests.revision
    asyncSetUp = fixture.RosterTests.asyncSetUp
    asyncTearDown = fixture.RosterTests.asyncTearDown

    def source(self):
        self.collection = SimpleNamespace(
            find_one=AsyncMock(
                return_value={
                    "fwa_base_links": {"th18": LINK},
                    "base_information": {"th18": "<script>plain text</script>"},
                    "staff_secret": "never",
                }
            )
        )
        self.app["server_management_mongo"] = SimpleNamespace(fwa_data=self.collection)

    async def test_member_access_cached_allowlist_and_lazy_details(self):
        self.source()
        response = await self.call("GET", "/bases", self.member)
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(set(body), {"bases"})
        self.assertNotIn("base_information", repr(body))
        self.assertNotIn("staff_secret", repr(body))
        await self.call("GET", "/bases", self.member)
        self.assertEqual(self.collection.find_one.await_count, 1)
        response = await self.call("GET", "/bases?level=th18", self.member)
        self.assertEqual(
            (await response.json())["base_information"], "<script>plain text</script>"
        )
        projection = self.collection.find_one.await_args.args[1]
        self.assertNotIn("staff_secret", projection)
        self.assertNotIn("active_base_images", projection)
        self.assertEqual(
            (await self.call("POST", "/bases", self.member, json={})).status, 405
        )
        self.assertEqual(
            (await self.call("GET", "/bases?level=bad", self.member)).status, 400
        )
        self.assertEqual(
            (await self.call("GET", "/bases?level=th9", self.member)).status, 404
        )
        response = await self.client.get("/api/cwl/bases")
        self.assertEqual(response.status, 401)
        self.assertEqual(self.collection.find_one.await_count, 1)


def test_base_route_survives_login_without_external_redirects():
    from cwl_web.app import login_destination, saved_login_destination
    assert login_destination({'view': 'bases'}) == '/bases'
    assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page': '/bases'})) == '/bases'
    assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page': 'https://evil.example/bases'})) != 'https://evil.example/bases'

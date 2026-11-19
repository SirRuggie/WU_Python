from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest
from utils.base_bank import public_bases, https_url
import test_cwl_web_roster as fixture

LINK = "https://link.clashofclans.com/en?action=OpenLayout&id=TH18%3AWB%3Afixture"


def base_registry():
    from town_halls_fixture import weight_registry
    doc = weight_registry(newest=19)
    doc.update(schema_version=2, nonbase_revision=7)
    for level in (11, 12, 18, 19):
        doc["levels"][str(level)]["bases"] = {
            "war_image": "https://images.example/base.png",
            "active_image": "https://images.example/active.png",
            "merged": {"link": LINK, "instructions": "<script>plain text</script>"},
            "non_merged": {"link": LINK + "2"}}
    return doc


def test_all_supported_variants_mapping_and_field_allowlist():
    config = base_registry()
    config["updated_by"] = 987654321
    rows, details = public_bases(config)
    assert len(rows) == 6
    for row in rows:
        assert set(row) == {"key", "town_hall", "variant", "link", "war_base_image", "has_details"}
        assert row["variant"] == ("non-merged" if row["key"].endswith("_new") else "merged")
        assert row["war_base_image"] == "https://images.example/base.png"
    assert [row["key"] for row in rows[:2]] == ["th19", "th19_new"]
    assert "th11" not in details
    assert "987654321" not in repr(rows) + repr(details)
    assert "active.png" not in repr(rows) + repr(details)


def test_missing_link_never_exposes_image_only_or_notes_only_variant():
    assert public_bases(None) == ([], {})
    doc = base_registry()
    for item in doc["levels"].values():
        if "bases" in item:
            item["bases"]["merged"].pop("link")
            item["bases"]["non_merged"].pop("link")
    assert public_bases(doc) == ([], {})
    for bad in ("javascript:alert(1)", "http://link.clashofclans.com/?action=OpenLayout&id=x",
                "https://link.clashofclans.com.evil/en?action=OpenLayout&id=x",
                "https://user@link.clashofclans.com/en?action=OpenLayout&id=x",
                "https://link.clashofclans.com/en?action=OpenClanProfile&id=x"):
        assert https_url(bad, clash=True) is None


class BaseBankHTTP(unittest.IsolatedAsyncioTestCase):
    auth = fixture.RosterTests.auth
    call = fixture.RosterTests.call
    revision = fixture.RosterTests.revision
    asyncSetUp = fixture.RosterTests.asyncSetUp
    asyncTearDown = fixture.RosterTests.asyncTearDown

    def source(self):
        registry_patch = patch('utils.town_halls.load', AsyncMock(return_value=base_registry()))
        self.registry_read = registry_patch.start()
        self.addCleanup(registry_patch.stop)
        self.collection = SimpleNamespace(find_one=AsyncMock())
        self.app["server_management_mongo"] = SimpleNamespace(fwa_data=self.collection)

    async def test_member_access_cached_allowlist_and_lazy_details(self):
        self.source()
        response = await self.call("GET", "/bases", self.member)
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(set(body), {"bases"})
        self.assertNotIn("base_information", repr(body))
        self.assertNotIn("updated_by", repr(body))
        await self.call("GET", "/bases", self.member)
        self.assertEqual(self.registry_read.await_count, 1)
        response = await self.call("GET", "/bases?level=th18", self.member)
        self.assertEqual(
            (await response.json())["base_information"], "<script>plain text</script>"
        )
        self.collection.find_one.assert_not_awaited()
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
        self.assertEqual(self.registry_read.await_count, 1)


def test_base_route_survives_login_without_external_redirects():
    from cwl_web.app import login_destination, saved_login_destination
    assert login_destination({'view': 'bases'}) == '/bases'
    assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page': '/bases'})) == '/bases'
    assert saved_login_destination(SimpleNamespace(cookies={'wu_login_page': 'https://evil.example/bases'})) != 'https://evil.example/bases'

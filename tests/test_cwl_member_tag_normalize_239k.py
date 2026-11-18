"""Member tag formatting preserves strict validation and async write ownership."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cwl_web.store import Store
from utils import cwl_member_service as service


@pytest.mark.parametrize("raw", ["#P0LYQ", "#polyq", " #pOlyq ", "polyq", " pOlyq "])
def test_member_tag_reuses_common_formatter_without_changing_canonical_output(raw):
    assert service.player_tag(raw) == "#P0LYQ"


@pytest.mark.parametrize("raw", [None, False, True, 0, 123, [], {}, ["P0LYQ"],
                                "", " ", "P", "#" + "P" * 16, "#AB!", "# P0LYQ",
                                "##P0LYQ", "# #P0LYQ", "#P 0LYQ", "#P0LYQ\nX"])
def test_member_tag_keeps_type_length_alphabet_internal_whitespace_errors(raw):
    with pytest.raises(service.MemberError, match="Invalid player tag") as caught:
        service.player_tag(raw)
    assert caught.value.status == 400


def provider(*, returned_tag="#P0LYQ", linked=True):
    return SimpleNamespace(
        linked_tags=AsyncMock(return_value={" #pOlyq ": True} if linked else {}),
        player=AsyncMock(return_value={"tag": returned_tag, "name": "Synthetic raw O account",
                                       "town_hall": 16, "current_clan_tag": "#Q2Y"}),
        family_clans=AsyncMock(return_value={"clans": [
            {"tag": "#Q2Y", "type": "FWA", "name": "Synthetic family"}]}),
    )


def test_raw_o_link_is_canonicalized_before_provider_lookup_and_selection():
    async def scenario():
        facts = provider()
        accounts = await service.accounts_for_member(facts, "100")
        facts.player.assert_awaited_once_with("#P0LYQ")
        assert accounts[0]["tag"] == "#P0LYQ"
        assert accounts[0]["verified"] is True
        assert accounts[0]["family_clan_status"] == "approved"
        assert service._selections("lazy", [{"tag": "polyq", "prefer_crystal_1_or_lower": False}]) == {
            "#P0LYQ": (False, None)}

    asyncio.run(scenario())


def test_provider_returned_other_canonical_identity_is_rejected():
    async def scenario():
        facts = provider(returned_tag="#Q0LYQ")
        with pytest.raises(ValueError, match="different player tag"):
            await service.accounts_for_member(facts, "100")

    asyncio.run(scenario())


def test_raw_o_aliases_cannot_submit_one_account_twice():
    with pytest.raises(service.MemberError, match="Duplicate account") as caught:
        service._selections("lazy", [
            {"tag": "polyq", "prefer_crystal_1_or_lower": False},
            {"tag": "#P0LYQ", "prefer_crystal_1_or_lower": False},
        ])
    assert caught.value.status == 400


def test_raw_o_submit_keeps_single_ordered_transaction_and_existing_owner(tmp_path):
    async def scenario():
        store = Store(str(tmp_path / "fixture.sqlite"))
        try:
            with store.tx() as db:
                db.execute("INSERT INTO seasons(id,label,status,signup_open) VALUES(1,'Synthetic','draft',1)")
                db.execute("UPDATE member_season SET season_id=1 WHERE id=1")
            original = store.run_tx
            store.run_tx = AsyncMock(wraps=original)
            facts = provider()
            result = await service.submit(store, facts, 1, "100", "lazy", [
                {"tag": " #pOlyq ", "prefer_crystal_1_or_lower": False}], expected_revision=0)
            assert result == {"ok": True, "count": 1, "moved": 0}
            store.run_tx.assert_awaited_once()
            assert store.rows("SELECT tag,user_id,pool FROM signups") == [
                {"tag": "#P0LYQ", "user_id": "100", "pool": "lazy"}]
            before = store.rows("SELECT * FROM signups")
            with pytest.raises(service.MemberError) as caught:
                await service.submit(store, facts, 1, "200", "lazy", [
                    {"tag": "polyq", "prefer_crystal_1_or_lower": False}], expected_revision=1)
            assert caught.value.status == 409
            assert store.rows("SELECT * FROM signups") == before
            assert store.one("SELECT revision FROM roster_meta WHERE season_id=1")["revision"] == 1
        finally:
            await store.close_writer()

    asyncio.run(scenario())


def test_raw_o_unlinked_submission_never_starts_transaction(tmp_path):
    async def scenario():
        store = Store(str(tmp_path / "fixture.sqlite"))
        try:
            store.run_tx = AsyncMock()
            with pytest.raises(service.MemberError) as caught:
                await service.submit(store, provider(linked=False), 1, "100", "lazy", [
                    {"tag": "polyq", "prefer_crystal_1_or_lower": False}])
            assert caught.value.status == 403
            store.run_tx.assert_not_awaited()
            assert store.rows("SELECT * FROM signups") == []
        finally:
            await store.close_writer()

    asyncio.run(scenario())

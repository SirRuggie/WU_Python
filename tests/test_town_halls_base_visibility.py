"""Fixture-only lowest-FWA visibility; the legacy base data is never rewritten."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from utils import base_bank, town_halls
from town_halls_fixture import weight_registry, install_snapshot

LINK='https://link.clashofclans.com/en?action=OpenLayout&id=fixture'


def test_public_projection_filters_rows_and_detail_keys_without_changing_source():
    data={'fwa_base_links':{key:LINK for key in base_bank.FWA_TH_LEVELS},
          'base_information':{key:'Guidance' for key in base_bank.FWA_TH_LEVELS}}
    before=deepcopy(data)
    rows,details=base_bank.public_bases(data,minimum=12)
    assert rows and all(row['town_hall']>=12 for row in rows)
    assert set(details)=={row['key'] for row in rows}
    assert not {'th11','th10','th9'} & set(details)
    assert data==before


def test_read_owner_uses_registry_minimum_and_never_writes_legacy_data():
    data={'fwa_base_links':{key:LINK for key in base_bank.FWA_TH_LEVELS}}
    legacy=SimpleNamespace(find_one=AsyncMock(return_value=data),insert_one=AsyncMock(),update_one=AsyncMock(),replace_one=AsyncMock())
    mongo=SimpleNamespace(fwa_data=legacy)
    registry=weight_registry();registry['lowest_fwa_town_hall']=18
    with patch.object(town_halls,'load',AsyncMock(return_value=registry)) as load:
        rows,details=asyncio.run(base_bank.read_base_bank(mongo))
    assert [row['key'] for row in rows]==['th18','th18_new']
    assert set(details)=={'th18','th18_new'}
    load.assert_awaited_once_with(mongo,base_bank.WARRIORS_UNITED_GUILD_ID)
    legacy.insert_one.assert_not_awaited();legacy.update_one.assert_not_awaited();legacy.replace_one.assert_not_awaited()
    assert set(data['fwa_base_links'])==set(base_bank.FWA_TH_LEVELS)


def test_missing_registry_is_explicit_and_does_not_read_or_seed_legacy_data():
    legacy=SimpleNamespace(find_one=AsyncMock(),insert_one=AsyncMock())
    with patch.object(town_halls,'load',AsyncMock(return_value=None)):
        with pytest.raises(town_halls.TownHallsMissing):
            asyncio.run(base_bank.read_base_bank(SimpleNamespace(fwa_data=legacy)))
    legacy.find_one.assert_not_awaited();legacy.insert_one.assert_not_awaited()


@pytest.mark.parametrize('minimum',[12,19])
def test_native_base_overview_and_select_obey_current_minimum(monkeypatch,minimum):
    from extensions.commands.clan.dashboard import fwa_data as native
    doc=install_snapshot(monkeypatch);doc['lowest_fwa_town_hall']=minimum
    monkeypatch.setattr(native,'get_fwa_data',AsyncMock(return_value={}))
    view=asyncio.run(native.build_fwa_management_screen(object(),object(),manage_token='fixture'))
    payload=[part.build()[0] for part in view]
    def nodes(value):
        if isinstance(value,dict):
            yield value
            for child in value.values():yield from nodes(child)
        elif isinstance(value,list):
            for child in value:yield from nodes(child)
    menus=[node for node in nodes(payload) if node.get('type')==3]
    assert len(menus)==1
    if minimum==19:
        assert menus[0]['disabled'] is True
        assert menus[0]['options'][0]['value']=='unavailable'
        assert 'No matching FWA base levels.' in repr(payload)
    else:
        assert all(int(option['value'][2:].split('_')[0])>=minimum for option in menus[0]['options'])
        assert '**TH11**' not in repr(payload)

"""Fixture-only registry base visibility, with no legacy base reads or writes."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from utils import base_bank, town_halls
from town_halls_fixture import weight_registry

LINK = 'https://link.clashofclans.com/en?action=OpenLayout&id=fixture'


def registry():
    doc = weight_registry(newest=19)
    doc.update(schema_version=2, nonbase_revision=7)
    for item in doc['levels'].values():
        item['bases'] = {'war_image': 'https://images.example/shared.jpg',
                         'merged': {'link': LINK, 'instructions': 'Guidance'},
                         'non_merged': {'link': LINK}}
    return doc


def test_public_projection_filters_rows_and_details_without_changing_registry():
    doc = registry()
    before = deepcopy(doc)
    rows, details = base_bank.public_bases(doc)
    assert rows and all(row['town_hall'] >= 12 for row in rows)
    assert set(details) == {row['key'] for row in rows}
    assert not {'th11', 'th10', 'th9'} & set(details)
    assert doc == before


def test_read_owner_uses_registry_minimum_and_never_reads_or_writes_legacy():
    legacy = SimpleNamespace(find_one=AsyncMock(), insert_one=AsyncMock(), update_one=AsyncMock(), replace_one=AsyncMock())
    mongo = SimpleNamespace(fwa_data=legacy)
    doc = registry()
    doc['lowest_fwa_town_hall'] = 18
    with patch.object(town_halls, 'load', AsyncMock(return_value=doc)) as load:
        rows, details = asyncio.run(base_bank.read_base_bank(mongo))
    assert [row['key'] for row in rows] == ['th19', 'th19_new', 'th18', 'th18_new']
    assert set(details) == {row['key'] for row in rows}
    load.assert_awaited_once_with(mongo, base_bank.WARRIORS_UNITED_GUILD_ID)
    legacy.find_one.assert_not_awaited()
    legacy.insert_one.assert_not_awaited()
    legacy.update_one.assert_not_awaited()
    legacy.replace_one.assert_not_awaited()


def test_missing_registry_is_explicit_and_does_not_read_or_seed_legacy():
    legacy = SimpleNamespace(find_one=AsyncMock(), insert_one=AsyncMock())
    with patch.object(town_halls, 'load', AsyncMock(return_value=None)):
        with pytest.raises(town_halls.TownHallsMissing):
            asyncio.run(base_bank.read_base_bank(SimpleNamespace(fwa_data=legacy)))
    legacy.find_one.assert_not_awaited()
    legacy.insert_one.assert_not_awaited()

import asyncio
from unittest.mock import AsyncMock

import pytest
from utils import account_links as links


def test_link_outage_is_not_an_empty_link_map():
    with pytest.raises(links.LinksUnavailable):
        asyncio.run(links.lookup_links(player_tags=['#P2Y'], king=AsyncMock(return_value=[]), perk=AsyncMock(return_value=None)))


def test_conflicting_owners_and_unrequested_records_do_not_ping(monkeypatch):
    lookup = AsyncMock(return_value=[
        ('#P2Y', '123456789012345678', True),
        ('#P2Y', '223456789012345678', True),
        ('#Q2Y', '123456789012345678', False),
        ('#Q2Y', '123456789012345678', True),
        ('#G2Y', '323456789012345678', True),
    ])
    monkeypatch.setattr(links, 'lookup_links', lookup)
    assert asyncio.run(links.linked_owners(['#P2Y', '#Q2Y'])) == {'#Q2Y': '123456789012345678'}


def test_external_records_are_normalized_and_malformed_records_ignored():
    rows = links.normalize_records([
        [None, {'player_tag': 'p2y', 'user_id': '123', 'is_verified': True},
         {'player_tag': '@everyone', 'user_id': '456'}, {'player_tag': '#Q2Y', 'user_id': '１２３'}],
        [{'tag': '#G2Y', 'userId': '456', 'verified': False}],
    ])
    assert rows == [('#P2Y', '123', True), ('#G2Y', '456', False)]

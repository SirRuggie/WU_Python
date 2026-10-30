"""Family membership is directory presence, not a CWL category allowlist."""
import asyncio
from copy import deepcopy

import pytest

from utils.cwl_member_service import accounts_for_member
from utils.cwl_signup_policy import main_signup_error


@pytest.mark.parametrize('clan_type', ['Unknown', 'CWL Hosting', 'CWL', 'FWA', 'Tactical'])
def test_stored_types_are_family_and_fwa_policy_remains_distinct(clan_type):
    rows = [dict(tag='#R2Y', name='Stored', type=clan_type)]

    class Provider:
        async def linked_tags(self, user_id):
            return {'#P2Y': True, '#Q2Y': True}

        async def player(self, tag):
            return dict(tag=tag, current_clan_tag='#R2Y' if tag == '#P2Y' else '#J2Y')

        async def family_clans(self):
            return {'status': 'ok', 'clans': deepcopy(rows)}

    before = deepcopy(rows)
    stored, outside = asyncio.run(accounts_for_member(Provider(), '100'))
    assert stored['family_clan_status'] == 'approved'
    assert outside['family_clan_status'] == 'outside'
    assert bool(main_signup_error(stored)) == (clan_type == 'FWA')
    assert rows == before


@pytest.mark.parametrize('flag', ['removed', 'archived'])
def test_removed_directory_rows_do_not_classify_accounts_as_family(flag):
    class Provider:
        async def linked_tags(self, user_id):
            return {'#P2Y': True}

        async def player(self, tag):
            return dict(tag=tag, current_clan_tag='#R2Y')

        async def family_clans(self):
            return {'clans': [dict(tag='#R2Y', name='Gone', type='FWA', **{flag: True})]}

    account, = asyncio.run(accounts_for_member(Provider(), '100'))
    assert account['family_clan_status'] == 'outside'
    assert account['current_clan_type'] is None


def test_return_choices_include_every_active_type_and_keep_fwa_scheduling_strict(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from cwl_web import manage_return_bulk
    from tests.test_lazy_cwl_store import _Collection

    rows = [
        dict(_id=1, tag='#P2Y', name='Unknown', type='Unknown'),
        dict(_id=2, tag='#Q2Y', name='Host', type='CWL Hosting'),
        dict(_id=3, tag='#R2Y', name='FWA', type='FWA'),
        dict(_id=4, tag='#J2Y', name='Removed', type='CWL', removed=True),
        dict(_id=5, tag='#L2Y', name='Archived', type='FWA', archived=True),
    ]
    db = SimpleNamespace(clans=_Collection(rows))
    monkeypatch.setattr(manage_return_bulk.store, 'list_active', AsyncMock(return_value=[]))
    choices = asyncio.run(manage_return_bulk.available(db))
    assert set(choices) == {'MAIN:#P2Y', 'MAIN:#Q2Y', 'FWA:#R2Y'}
    assert set(manage_return_bulk.eligible(choices, 'start')) == {'FWA:#R2Y'}
    assert set(manage_return_bulk.eligible(choices, 'save')) == set(choices)

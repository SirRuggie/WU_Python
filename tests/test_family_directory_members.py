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

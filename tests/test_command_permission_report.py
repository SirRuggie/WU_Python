"""Characterize existing dashboard policy only; prompt 31 must not change it."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from cwl_web.server_management import allowed
from utils.dashboard_access import PERMISSIONS, SECTION_SCOPE


def test_dashboard_scopes_are_manage_grants_not_view_only_flags():
    async def run():
        actor={'dashboard':True,'user_id':'123','role_ids':set()}
        with patch('cwl_web.access_control.dashboard_allowed',AsyncMock(return_value=True)) as check:
            assert await allowed(actor,'text_commands',None,write=False)
            assert await allowed(actor,'text_commands',None,write=True)
            assert all(call.args==(actor,'text_commands',None) for call in check.await_args_list)
        assert 'text_commands' in PERMISSIONS
        assert not any('view' in key or 'read' in key for key in PERMISSIONS)
        assert SECTION_SCOPE['text_commands']=='text_commands'
    asyncio.run(run())

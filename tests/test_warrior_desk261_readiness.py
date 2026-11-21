import pytest
from utils.ticket_settings import desk_readiness

FULL={'desk_channel_id':1,'main_staff_parent':2,'account_thread_recruiter_role':3,'staff_thread_recruiter_role':4}


def test_readiness_lists_every_missing_saved_field_and_rollout():
    result=desk_readiness({},phase='prepared')
    assert not result['ready']
    assert {item['key'] for item in result['missing']}=={'desk_channel_id','desk_staff_parent','account_thread_recruiter_role','staff_thread_recruiter_role',''}


@pytest.mark.parametrize('phase',['thread_default','thread_only'])
def test_readiness_accepts_explicit_main_staff_fallback_and_ready_phase(phase):
    assert desk_readiness(FULL,phase=phase)['ready']


def test_invalid_rollout_and_each_missing_role_stay_blocked():
    assert not desk_readiness(FULL,phase='thread_default',rollout_valid=False)['ready']
    for key in ('account_thread_recruiter_role','staff_thread_recruiter_role'):
        assert desk_readiness({**FULL,key:0},phase='thread_default')['missing']==[{'key':key,'label':'Add account staff role' if key.startswith('account') else 'Contact staff role'}]


@pytest.mark.parametrize('invalid', [False, True])
def test_http_and_runtime_share_one_rollout_read_model(invalid):
    import asyncio
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    from extensions.commands import ticket_runtime
    from utils import ticket_rollout
    from tests.test_ticket_runtime import _rollout
    row=_rollout(phase=ticket_runtime.PHASE_THREAD_DEFAULT)
    if invalid:row['schema_version']=999
    db=NS(ticket_rollout=NS(find_one=AsyncMock(return_value=row)))
    assert ticket_runtime.get_rollout is ticket_rollout.get_rollout
    assert ticket_runtime.RolloutState is ticket_rollout.RolloutState
    actual=asyncio.run(ticket_rollout.get_rollout(db))
    assert actual.valid is not invalid
    assert actual==ticket_runtime._parse_rollout(row)
    db.ticket_rollout.find_one.assert_awaited_once_with({'_id':ticket_runtime.ROLLOUT_ID})

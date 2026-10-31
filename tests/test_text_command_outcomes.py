import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from utils import text_commands as core

@pytest.mark.parametrize('failed', [False, True])
def test_attempts_record_safe_utc_outcome_without_revision_change(failed):
    async def run():
        core._recent.clear()
        row=core.validate({'command':'!use','text':'Reply','delete_trigger':False})
        row['revision']='original'
        target=NS(find_one=AsyncMock(return_value=row),update_one=AsyncMock())
        rest=NS(create_message=AsyncMock(side_effect=RuntimeError('secret https://token.invalid') if failed else None),delete_message=AsyncMock())
        event=NS(guild_id=core.GUILD_ID,channel_id=123,message=NS(id=1,content='!use',author=NS(id=7,is_bot=False),webhook_id=None))
        with patch.object(core,'collection',return_value=target),patch('utils.text_command_files.load_files',AsyncMock(return_value={})):
            assert await core.handle(event,None,NS(rest=rest)) is True
        query,update=target.update_one.await_args.args
        assert query['revision']=='original'
        assert update['$inc']=={'use_count':1}
        assert 'revision' not in update['$set']
        outcome=update['$set']['last_outcome']
        assert outcome['status']==('error' if failed else 'ok')
        assert outcome['at'].endswith('+00:00')
        assert 'secret' not in repr(update) and 'token.invalid' not in repr(update)
        rest.delete_message.assert_not_awaited()
    asyncio.run(run())

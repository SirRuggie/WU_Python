"""Command lookups and status failures must not consume or duplicate a reply."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from utils import text_commands as core


def event():
    return NS(guild_id=core.GUILD_ID, channel_id=123,
              message=NS(id=555, content='!new',
                         author=NS(id=7, is_bot=False), webhook_id=None))


def command():
    return {**core.validate({'command': '!new', 'text': 'Reply'}), 'revision': 'one'}


def test_missing_then_created_command_has_no_typo_cooldown():
    async def run():
        core._recent.clear()
        target = NS(find_one=AsyncMock(side_effect=[None, command()]), update_one=AsyncMock())
        rest = NS(create_message=AsyncMock(), delete_message=AsyncMock())
        with patch.object(core, 'collection', return_value=target), patch(
            'utils.text_command_files.load_files', AsyncMock(return_value={})
        ):
            assert await core.handle(event(), None, NS(rest=rest)) is False
            assert not core._recent
            assert await core.handle(event(), None, NS(rest=rest)) is True
        rest.create_message.assert_awaited_once()
        rest.delete_message.assert_awaited_once()
    asyncio.run(run())


def test_status_write_failure_does_not_turn_delivered_reply_into_send_failure(caplog):
    async def run():
        core._recent.clear()
        target = NS(find_one=AsyncMock(return_value=command()),
                    update_one=AsyncMock(side_effect=RuntimeError('database unavailable')))
        rest = NS(create_message=AsyncMock(), delete_message=AsyncMock())
        with patch.object(core, 'collection', return_value=target), patch(
            'utils.text_command_files.load_files', AsyncMock(return_value={})
        ):
            assert await core.handle(event(), None, NS(rest=rest)) is True
            assert await core.handle(event(), None, NS(rest=rest)) is True
        rest.create_message.assert_awaited_once()
        rest.delete_message.assert_awaited_once()
        assert target.update_one.await_args.args[0]['last_delete_error'] == {'$exists': True}
        assert 'Could not record trigger deletion outcome' in caplog.text
        assert 'could not be delivered' not in caplog.text
    asyncio.run(run())

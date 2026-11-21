import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from extensions.commands.tickets import handlers, resolve
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from tests.test_ticket_pilot_rollout import _pilot_context, _my_ticket_fixture


@pytest.mark.parametrize('host_zone', ['UTC', 'America/New_York'])
def test_mongo_utc_timestamp_does_not_depend_on_host_timezone(host_zone):
    old = os.environ.get('TZ')
    try:
        os.environ['TZ'] = host_zone
        time.tzset()
        naive = datetime(2026, 9, 28, 17, 6, 15)
        utc = naive.replace(tzinfo=timezone.utc)
        eastern = utc.astimezone(timezone(timedelta(hours=-4)))
        expected = f'<t:{int(utc.timestamp())}:f>'
        assert resolve.ts(naive, 'f') == expected
        assert resolve.ts(utc, 'f') == expected
        assert resolve.ts(eastern, 'f') == expected
    finally:
        if old is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = old
        time.tzset()


def test_member_closed_ticket_has_exact_open_presentation_and_no_decision_date(monkeypatch):
    outputs=[]
    for status in ['open','closed']:
        edits=[]
        row=dict(_id='ticket_809',ticket_type='fwa',ticket_number=809,status=status,
                 guild_id=11,user_id=50,location={'id':55,'staff_space_id':66},
                 closed_at=datetime.now(timezone.utc)-timedelta(days=1),
                 approved_at=datetime(2026,9,27),updated_at=datetime(2026,9,29))
        access=AsyncMock(return_value=True)
        monkeypatch.setattr(handlers.thread_service,'ensure_candidate_thread_access',access)
        asyncio.run(handlers.handle_my_ticket(_pilot_context(edits),'',
            bot=SimpleNamespace(rest=SimpleNamespace()),mongo=_my_ticket_fixture(monkeypatch,[row])))
        payload=edits[-1]['components'][0].build()[0]
        outputs.append(payload)
        if status=='closed':access.assert_not_awaited()
    assert outputs[0]==outputs[1]
    assert 'FWA #809' in repr(outputs[0])
    assert 'Closed' not in repr(outputs[0]) and '<t:' not in repr(outputs[0])


def test_member_ticket_card_fits_five_tickets_and_keeps_staff_data_private(monkeypatch):
    edits=[]
    row=dict(_id='ticket_809',ticket_type='fwa',ticket_number=809,status='closed',guild_id=11,
             user_id=50,location={'id':55,'staff_space_id':66},reason='private reason',
             staff_notes='private notes',flags=['ghosted'])
    asyncio.run(handlers.handle_my_ticket(_pilot_context(edits),'',
        bot=SimpleNamespace(rest=SimpleNamespace()),mongo=_my_ticket_fixture(monkeypatch,[row]*5)))
    payload=edits[-1]['components'][0].build()[0]
    assert payload['type']==17 and len(payload['components'])==16
    for private in ['private reason','private notes','ghosted','/11/66','Closed']:
        assert private not in repr(payload)
    assert repr(payload).count('https://discord.com/channels/11/55')==5
    assert edits[-1]['role_mentions'] is False

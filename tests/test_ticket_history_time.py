import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from extensions.commands.tickets import handlers, resolve


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


def test_history_uses_current_decision_not_previous_approval_or_later_updates():
    denied = datetime(2026, 9, 28, 17, 6, 15)
    ticket = dict(ticket_type='fwa', ticket_number=809, status='denied',
                  approved_at=datetime(2026, 9, 27), denied_at=denied,
                  updated_at=datetime(2026, 9, 29))
    line = handlers._my_ticket_history_line(ticket)
    assert 'FWA #809 · Denied' in line
    assert resolve.ts(denied, 'f') in line
    del ticket['denied_at']
    assert 'Date unavailable' in handlers._my_ticket_history_line(ticket)


def test_history_card_fits_five_tickets_and_keeps_staff_data_private():
    ticket = dict(ticket_type='fwa', ticket_number=809, status='denied',
                  guild_id=11, location={'id': 55, 'staff_space_id': 66},
                  reason='private reason', staff_notes='private notes', flags=['ghosted'])
    panel = handlers._my_ticket_history_components([ticket] * 5)[0]
    payload = panel.build()[0]
    assert payload['type'] == 17
    assert len(payload['components']) == 17
    assert 'private reason' not in repr(payload)
    assert 'private notes' not in repr(payload)
    assert 'ghosted' not in repr(payload)
    assert '/11/66' not in repr(payload)

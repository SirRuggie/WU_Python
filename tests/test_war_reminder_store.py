import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import DuplicateKeyError
from utils.war_reminder_store import WarReminderStore, SettingsConflict, occurrence_key
from utils import war_reminder_store as storage


@pytest.fixture
def store(monkeypatch):
    rows = {}
    def collection(db, name='war_reminder_settings'):
        return rows.setdefault(name, NS(create_index=AsyncMock(), update_one=AsyncMock(), insert_one=AsyncMock()))
    monkeypatch.setattr(storage, 'collection', collection)
    return WarReminderStore(NS()), rows


def test_indexes_support_clan_history_without_expiring_claims(store):
    value, rows = store
    asyncio.run(value.ensure_indexes())
    rows['war_reminder_deliveries'].create_index.assert_awaited_once_with(
        [('clan_tag', 1), ('at', -1)], name='clan_delivery_history')
    assert 'expireAfterSeconds' not in rows['war_reminder_deliveries'].create_index.await_args.kwargs


def test_first_save_race_is_conflict_not_overwrite(store):
    value, _ = store
    value.settings.update_one.side_effect = DuplicateKeyError('raced')
    with pytest.raises(SettingsConflict):
        asyncio.run(value.save_settings('#P2Y', None, {'enabled': True}, '123'))
    assert value.settings.update_one.await_args.args[0] == {'_id': '#P2Y', 'version': {'$exists': False}}


def test_duplicate_delivery_claim_is_rejected(store):
    value, _ = store
    value.deliveries.insert_one.side_effect = DuplicateKeyError('raced')
    assert asyncio.run(value.claim_delivery('war:one', status='sending')) is False


def test_war_occurrence_identity_does_not_include_mutable_end_time():
    assert occurrence_key('#P2Y', datetime(2026, 10, 21, tzinfo=timezone.utc), '60') == '#P2Y:1792540800:60'

@pytest.mark.parametrize('conflict', [False, True])
def test_reminder_history_has_durable_before_image_and_no_false_confirmation(store, monkeypatch, conflict):
    from utils import clan_dashboard_history as history
    value, _ = store
    audit = AsyncMock(return_value='event')
    finish = AsyncMock()
    monkeypatch.setattr(history, 'audit', audit)
    monkeypatch.setattr(history, 'finish_change', finish)
    value.settings.update_one.return_value = NS(matched_count=not conflict, upserted_id=None)
    before = {'version': 2, 'enabled': False, 'minutes': [60]}
    values = {'enabled': True, 'minutes': [30]}
    context = ({'tag': '#P2Y', 'name': 'Example'}, {'user_id': '123', 'name': 'Jamie'})
    async def run():
        if conflict:
            with pytest.raises(SettingsConflict):
                await value.save_settings('#P2Y', before, values, '123', history_context=context)
        else:
            await value.save_settings('#P2Y', before, values, '123', history_context=context)
    asyncio.run(run())
    assert audit.await_args.args[2] == 'reminders'
    assert audit.await_args.args[3]['reminder_settings']['minutes'] == [60]
    if conflict:
        finish.assert_not_awaited()
    else:
        assert finish.await_args.args[2:] == ({'enabled': False, 'minutes': [60]}, values)

def test_history_backup_failure_prevents_reminder_save(store, monkeypatch):
    from utils import clan_dashboard_history as history
    value, _ = store
    monkeypatch.setattr(history, 'audit', AsyncMock(side_effect=RuntimeError('unavailable')))
    with pytest.raises(RuntimeError):
        asyncio.run(value.save_settings('#P2Y', None, {}, '123', history_context=({'tag': '#P2Y'}, {'user_id': '123'})))
    value.settings.update_one.assert_not_awaited()

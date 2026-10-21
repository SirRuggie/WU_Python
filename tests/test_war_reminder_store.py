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

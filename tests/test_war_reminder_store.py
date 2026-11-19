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
    monkeypatch.setattr(history, 'abandon_change', AsyncMock())
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


def test_reminder_history_freezes_supplied_channel_names(store, monkeypatch):
    from utils import clan_dashboard_history as history
    value, _ = store
    monkeypatch.setattr(history, 'audit', AsyncMock(return_value='event'))
    monkeypatch.setattr(history, 'abandon_change', AsyncMock())
    finish = AsyncMock()
    monkeypatch.setattr(history, 'finish_change', finish)
    value.settings.update_one.return_value = NS(matched_count=1, upserted_id=None)
    names = {'channel_id': {'before': 'Old war chat', 'after': 'New war chat'}}
    asyncio.run(value.save_settings('#P2Y', {'version': 1}, {'channel_id': '123'}, 'staff',
        history_context=({'tag': '#P2Y'}, {'user_id': 'staff'}), history_names=names))
    assert finish.await_args.kwargs['names'] == names


@pytest.mark.parametrize('failure', [SettingsConflict(), RuntimeError('Mongo unavailable')])
def test_failed_save_is_abandoned_and_cannot_render_changed(store, monkeypatch, failure):
    from utils import clan_dashboard_history as history
    from cwl_web.clan_history import history_label, public_changes
    value, _ = store
    event = {'action': 'reminders'}
    monkeypatch.setattr(history, 'audit', AsyncMock(return_value='event'))
    async def abandon(db, event_id):
        assert event_id == 'event'
        event['abandoned'] = True
    monkeypatch.setattr(history, 'abandon_change', abandon)
    value.settings.update_one.side_effect = failure
    with pytest.raises(type(failure)):
        asyncio.run(value.save_settings('#P2Y', {'version': 2}, {'enabled': True}, 'staff',
            history_context=({'tag': '#P2Y'}, {'user_id': 'staff'})))
    assert history_label(event) == 'Not confirmed'
    assert public_changes(event) == []
    assert history_label({'action': 'reminders'}) == 'Saved snapshot'
    assert history_label({'action': 'reminders', 'confirmed': True}) == 'War reminders changed'


def test_worker_clan_exists_projects_only_id_without_changing_web_clan_read():
    clans = NS(find_one=AsyncMock(return_value={'_id': 'fixture', 'tag': '#P2Y', 'name': 'Clan'}))
    value = WarReminderStore.__new__(WarReminderStore)
    value.db = NS(clans=clans)
    assert asyncio.run(value.clan_exists('#P2Y')) is True
    clans.find_one.assert_awaited_with({'tag': '#P2Y'}, {'_id': 1})
    assert asyncio.run(value.clan('#P2Y'))['name'] == 'Clan'
    clans.find_one.assert_awaited_with({'tag': '#P2Y'})
    clans.find_one.return_value = None
    assert asyncio.run(value.clan_exists('#P2Y')) is False


def test_quiet_clan_halves_status_writes_and_health_never_overdue():
    from copy import deepcopy
    from datetime import timedelta
    from utils.war_reminder_health import health
    persisted = None
    writes = []
    async def find(query):
        return deepcopy(persisted)
    async def update(query, values, **kwargs):
        nonlocal persisted
        persisted = {'_id': query['_id'], **values['$set']}
        writes.append(deepcopy(persisted))
        return NS(matched_count=1, upserted_id=None)
    value = WarReminderStore.__new__(WarReminderStore)
    value.status = NS(find_one=find, update_one=update)
    first = datetime(2026, 11, 17, tzinfo=timezone.utc)
    config = {'enabled': True, 'channel_id': '123', 'updated_at': first}
    async def check():
        for minute in range(60):
            now = first + timedelta(minutes=minute)
            await value.record_status('#P2Y', settings_updated_at=config['updated_at'],
                                      checked_at=now, error=None, detail='Waiting for an active war', war_end=None)
            assert health(config, persisted, None, now)[0] == 'tracking'
        assert len(writes) == 30  # Before: one write each of 60 scans.
        assert all((b['checked_at'] - a['checked_at']).total_seconds() == 120
                   for a, b in zip(writes, writes[1:]))
        # A failure/recovery is visible immediately within the quiet interval.
        now = first + timedelta(minutes=59, seconds=1)
        await value.record_status('#P2Y', settings_updated_at=config['updated_at'], checked_at=now, error='TimeoutError', detail='Unavailable')
        assert len(writes) == 31
        assert health(config, persisted, None, now)[0] == 'attention'
        await value.record_status('#P2Y', settings_updated_at=config['updated_at'], checked_at=now + timedelta(seconds=1), error=None,
                                  detail='Waiting for an active war', war_end=None)
        assert len(writes) == 32
        assert health(config, persisted, None, now + timedelta(seconds=1))[0] == 'tracking'
    asyncio.run(check())


def test_failed_status_write_is_not_remembered_as_success():
    value = WarReminderStore.__new__(WarReminderStore)
    value.status = NS(find_one=AsyncMock(return_value=None), update_one=AsyncMock(side_effect=RuntimeError('offline')))
    async def check():
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await value.record_status('#P2Y', error=None, checked_at=datetime.now(timezone.utc))
        assert value.status.update_one.await_count == 2
    asyncio.run(check())


def test_active_war_bson_dates_halve_writes_and_keep_health_current():
    from bson import BSON
    from datetime import timedelta
    from utils.war_reminder_health import health
    persisted = None
    writes = []
    async def find(query):
        return persisted
    async def update(query, update, **kwargs):
        nonlocal persisted
        # Model the actual default Mongo read representation, not an aware-only fake.
        persisted = BSON.encode({'_id': query['_id'], **update['$set']}).decode()
        writes.append(persisted)
        return NS(matched_count=1, upserted_id=None)
    value = WarReminderStore.__new__(WarReminderStore)
    value.status = NS(find_one=find, update_one=update)
    first = datetime(2026, 11, 17, microsecond=123456, tzinfo=timezone.utc)
    end = first + timedelta(hours=24, microseconds=333333)
    config = {'enabled': True, 'channel_id': '123',
              'updated_at': BSON.encode({'at': first}).decode()['at']}
    async def check():
        for minute in range(60):
            now = first + timedelta(minutes=minute)
            await value.record_status('#P2Y', settings_updated_at=config['updated_at'],
                                      checked_at=now, error=None, detail='Tracking battle day', war_end=end)
            assert health(config, persisted, None, now)[0] == 'tracking'
        assert len(writes) == 30
        assert all((b['checked_at'] - a['checked_at']).total_seconds() == 120
                   for a, b in zip(writes, writes[1:]))
    asyncio.run(check())


@pytest.mark.parametrize('representation,changed', [
    ('aware_utc', False), ('naive_utc', False), ('offset_aware', False),
    ('same_bson_millisecond', False), ('different_millisecond', True),
    ('next_war', True), ('string_is_not_a_date', True),
])
def test_status_dates_compare_only_utc_bson_instants(representation, changed):
    from bson import BSON
    from datetime import timedelta
    first = datetime(2026, 11, 17, tzinfo=timezone.utc)
    end = first + timedelta(hours=1, microseconds=123456)
    stored = BSON.encode({'checked_at': first, 'war_end': end, 'error': None}).decode()
    fresh = {
        'aware_utc': end,
        'naive_utc': end.replace(tzinfo=None),
        'offset_aware': end.astimezone(timezone(timedelta(hours=5, minutes=30))),
        'same_bson_millisecond': end.replace(microsecond=123999),
        'different_millisecond': end.replace(microsecond=124000),
        'next_war': end + timedelta(days=1),
        'string_is_not_a_date': end.isoformat(),
    }[representation]
    value = WarReminderStore.__new__(WarReminderStore)
    value.status = NS(find_one=AsyncMock(return_value=stored), update_one=AsyncMock())
    result = asyncio.run(value.record_status('#P2Y', checked_at=first + timedelta(seconds=60),
                                            war_end=fresh, error=None))
    assert result is changed
    assert value.status.update_one.await_count == int(changed)


def test_status_date_equivalence_still_refreshes_liveness_and_keeps_real_changes():
    from bson import BSON
    from datetime import timedelta
    first = datetime(2026, 11, 17, tzinfo=timezone.utc)
    end = first + timedelta(hours=1, microseconds=123456)
    value = WarReminderStore.__new__(WarReminderStore)
    value.status = NS(find_one=AsyncMock(return_value=BSON.encode({
        'checked_at': first, 'war_end': end, 'error': None, 'count': 1,
    }).decode()), update_one=AsyncMock())
    async def check():
        assert not await value.record_status('#P2Y', checked_at=first + timedelta(seconds=119),
                                             war_end=end, error=None, count=1)
        assert await value.record_status('#P2Y', checked_at=first + timedelta(seconds=120),
                                         war_end=end, error=None, count=1)
        assert await value.record_status('#P2Y', checked_at=first + timedelta(seconds=60),
                                         war_end=end, error='TimeoutError', count=1)
        assert await value.record_status('#P2Y', checked_at=first + timedelta(seconds=60),
                                         war_end=end, error=None, count=2)
        assert await value.record_status('#P2Y', checked_at=first + timedelta(seconds=60),
                                         war_end=end, error=None, count='1')
    asyncio.run(check())


@pytest.mark.parametrize('representation', ['aware', 'naive', 'offset'])
def test_first_scan_after_settings_edit_refreshes_once_then_throttles(representation):
    from bson import BSON
    from datetime import timedelta
    from utils.war_reminder_health import health
    first = datetime(2026, 11, 17, tzinfo=timezone.utc)
    updated = first + timedelta(seconds=1)
    if representation == 'naive':
        updated = updated.replace(tzinfo=None)
    elif representation == 'offset':
        updated = updated.astimezone(timezone(timedelta(hours=5, minutes=30)))
    persisted = BSON.encode({'_id': '#P2Y', 'checked_at': first,
                             'error': None, 'detail': 'Waiting for an active war',
                             'war_end': None}).decode()
    writes = []
    async def update(query, values, **kwargs):
        nonlocal persisted
        persisted = BSON.encode({'_id': query['_id'], **values['$set']}).decode()
        writes.append(values['$set'])
        return NS(matched_count=1, upserted_id=None)
    async def find(query):
        return persisted
    value = WarReminderStore.__new__(WarReminderStore)
    value.status = NS(find_one=find, update_one=update)
    config = {'enabled': True, 'channel_id': '123', 'updated_at': updated}
    async def check():
        now = first + timedelta(seconds=60)
        assert health(config, persisted, None, now)[0] == 'pending'
        assert await value.record_status('#P2Y', settings_updated_at=updated,
                                         checked_at=now, error=None,
                                         detail='Waiting for an active war', war_end=None)
        assert len(writes) == 1
        assert health(config, persisted, None, now)[0] == 'tracking'
        assert persisted['settings_updated_at'].replace(tzinfo=timezone.utc) == first + timedelta(seconds=1)
        assert persisted['settings_version'] is None
        now = first + timedelta(seconds=120)
        assert not await value.record_status('#P2Y', settings_updated_at=updated,
                                             checked_at=now, error=None,
                                             detail='Waiting for an active war', war_end=None)
        assert len(writes) == 1
        assert health(config, persisted, None, now)[0] == 'tracking'
    asyncio.run(check())


def test_failed_first_settings_refresh_is_retried_without_remembering_success():
    from datetime import timedelta
    first = datetime(2026, 11, 17, tzinfo=timezone.utc)
    value = WarReminderStore.__new__(WarReminderStore)
    value.status = NS(find_one=AsyncMock(return_value={'checked_at': first, 'error': None}),
                      update_one=AsyncMock(side_effect=[RuntimeError('offline'), NS(matched_count=1, upserted_id=None)]))
    async def check():
        args = dict(settings_updated_at=first + timedelta(seconds=1),
                    checked_at=first + timedelta(seconds=60), error=None)
        with pytest.raises(RuntimeError, match='offline'):
            await value.record_status('#P2Y', **args)
        assert await value.record_status('#P2Y', **args)
        assert value.status.update_one.await_count == 2
        assert value.status.update_one.await_args.args[1]['$set']['settings_updated_at'] == first + timedelta(seconds=1)
    asyncio.run(check())


def test_editor_delivery_health_ignores_tests_without_history_page_limit():
    cursor = NS(sort=lambda *args: cursor, limit=lambda *args: cursor,
                to_list=AsyncMock(return_value=[{'status': 'uncertain', 'test': False}]))
    seen = []
    rows = NS(find=lambda *args: (seen.append(args), cursor)[1])
    value = WarReminderStore.__new__(WarReminderStore);value.deliveries = rows
    assert asyncio.run(value.latest_scheduled_delivery('#P2Y'))['status'] == 'uncertain'
    cursor.to_list.assert_awaited_once_with(length=1)
    assert seen == [({'clan_tag': '#P2Y', 'test': False}, {'_id': 0})]

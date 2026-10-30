"""No-attack opponents are tag-based, permanent history and streak-neutral."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from utils.strike_store import StrikeConflict, status_of, war_key
from tests.test_strike_streaks import setup, war, capture, GUILD, PLAYER, Collection, links


def test_no_attack_live_capture_is_neutral_even_with_missing_owner_service():
    async def run():
        db, service = setup()
        await capture(db, service, 0)
        before = deepcopy(db.strike_profiles.rows)
        item = war(1, attacks=0)
        item['opponent_tag'] = '#2CYVV92R'
        async def unavailable(_):
            raise RuntimeError('No links service')
        service.link_resolver = unavailable
        key = war_key(item)
        db.strike_war_snapshots.rows['snapshot'] = {
            '_id': f'{GUILD}:{key}', 'status': 'observing', 'seen_active': True,
            'guild_id': GUILD, 'war': item, 'war_key': key, 'end_time': item['end_time'],
        }
        # Collection queries by fields, so storage key need not be the document ID.
        result = await service.process_war(GUILD, item, official_capture=True)
        assert result['strikes'] == 0 and result['applied'] == 1
        row = next(r for r in db.strike_records.rows.values() if r['war_key'] == key)
        assert row['kind'] == 'no_attack' and status_of(row) == 'no_attack'
        assert not row.get('streak_eligible')
        assert db.strike_profiles.rows == before
        assert (await service.process_war(GUILD, item, official_capture=True))['existing'] == 1
        service.link_resolver = links
        assert (await capture(db, service, 2))['deferred_count'] == 0
    asyncio.run(run())


def test_matching_name_without_matching_tag_still_adds_strike():
    async def run():
        _, service = setup()
        item = war(1, attacks=0)
        item['opponent_name'] = 'NO WAR'
        assert (await service.process_war(GUILD, item))['strikes'] == 1
    asyncio.run(run())


def test_no_attack_setting_compare_and_swap_and_explicit_empty_list():
    async def run():
        _, service = setup()
        assert (await service.settings(GUILD))['no_attack_opponents'] == ['#2CYVV92R']
        receipt = await service.set_exempt_roles(GUILD, [], 9, expected_revision=0,
                                                no_attack_opponents=['2cyvv92r', '#2CYVV92R'])
        assert receipt['no_attack_opponents'] == ['#2CYVV92R']
        with pytest.raises(StrikeConflict):
            await service.set_exempt_roles(GUILD, [], 9, expected_revision=0, no_attack_opponents=[])
        await service.set_exempt_roles(GUILD, [], 9, expected_revision=1, no_attack_opponents=[])
        item = war(1, attacks=0)
        item['opponent_tag'] = '#2CYVV92R'
        assert (await service.process_war(GUILD, item))['strikes'] == 1
    asyncio.run(run())


def test_import_no_attack_is_history_only():
    async def run():
        db, service = setup()
        db.strike_imports = Collection()
        item = war(1, attacks=0)
        item['opponent_tag'] = '#2CYVV92R'
        preview = await service.preview_import(GUILD, [item], 9)
        assert preview['strikes'] == 0
        assert preview['items'][0]['kind'] == 'no_attack'
        result = await service.apply_import(GUILD, preview['preview_id'], 9)
        assert result['strikes'] == 0 and result['applied'] == 1
        assert not db.strike_profiles.rows
    asyncio.run(run())


def test_reviewed_correction_exact_keys_counts_idempotence_and_other_rows():
    from utils.strike_no_attack import WAR_KEYS, REASON, ACTOR
    async def run():
        db, service = setup()
        for i in range(50):
            db.strike_records.rows[str(i)] = {
                '_id': str(i), 'guild_id': GUILD, 'player_tag': PLAYER,
                'war_key': WAR_KEYS[i % 2], 'kind': 'strike',
                'expires_at': datetime.now(timezone.utc),
            }
        for i in range(2):
            db.strike_records.rows[f'm{i}'] = {
                '_id': f'm{i}', 'guild_id': GUILD, 'player_tag': PLAYER,
                'war_key': WAR_KEYS[i], 'kind': 'missed',
            }
        outside = {'_id': 'outside', 'guild_id': GUILD, 'player_tag': PLAYER,
                   'war_key': 'another-war', 'opponent_name': 'NO WAR', 'kind': 'strike'}
        db.strike_records.rows['outside'] = deepcopy(outside)
        before = deepcopy(db.strike_records.rows)
        plan = await service.no_attack_correction(GUILD)
        assert db.strike_records.rows == before
        assert plan['strike_count'] == 50 and plan['neutral_count'] == 2
        applied = await service.no_attack_correction(GUILD, reviewed_fingerprint=plan['fingerprint'])
        assert applied['applied'] == len(plan['changes']) == 52
        assert applied['unrelated_hash'] == plan['unrelated_hash']
        assert db.strike_records.rows['outside'] == outside
        assert all(db.strike_records.rows[str(i)]['revoke_reason'] == REASON for i in range(50))
        assert all(db.strike_records.rows[str(i)]['revoked_by'] == ACTOR for i in range(50))
        assert all(db.strike_records.rows[f'm{i}']['kind'] == 'no_attack' for i in range(2))
        again = await service.no_attack_correction(GUILD, reviewed_fingerprint=applied['fingerprint'])
        assert again['applied'] == 0
    asyncio.run(run())


def test_correction_refuses_stale_plan_and_streak_impact_before_any_write():
    from utils.strike_no_attack import WAR_KEYS
    async def run():
        db, service = setup()
        db.strike_records.rows['a'] = {'_id': 'a', 'guild_id': GUILD, 'player_tag': PLAYER,
                                       'war_key': WAR_KEYS[0], 'kind': 'strike'}
        plan = await service.no_attack_correction(GUILD)
        db.strike_records.rows['a']['streak_eligible'] = True
        with pytest.raises(StrikeConflict, match=r'^Correction records changed; review a fresh dry run\.$'):
            await service.no_attack_correction(GUILD, reviewed_fingerprint=plan['fingerprint'])
        plan = await service.no_attack_correction(GUILD)
        assert plan['streak_review_accounts'] == [PLAYER]
        with pytest.raises(StrikeConflict, match='streaks'):
            await service.no_attack_correction(GUILD, reviewed_fingerprint=plan['fingerprint'])
        assert not db.strike_records.rows['a'].get('revoked_at')
    asyncio.run(run())


def test_failed_begin_marks_error_without_overwriting_newer_attempt():
    from utils.strike_tracking import StrikeTracking
    from datetime import timedelta
    async def run():
        db, _ = setup()
        db.strike_tracking = Collection()
        owner = StrikeTracking(db)
        now = datetime.now(timezone.utc)
        await owner.failed_begin(GUILD, '#2UVGQU9', now)
        row = next(iter(db.strike_tracking.rows.values()))
        assert row['error'] == 'War processing failed'
        await owner.begin(GUILD, '#2UVGQU9')
        row['error'] = None
        await owner.failed_begin(GUILD, '#2UVGQU9', now - timedelta(seconds=10))
        assert row['error'] is None
        await owner.queue_retry(GUILD, '#2UVGQU9', 9)
        assert len(await owner.pending(GUILD)) == 1
        await owner.defer_due(GUILD, '#2UVGQU9', now=now)
        assert not await owner.pending(GUILD)
        assert row['retry_requested_at'] is not None
    asyncio.run(run())


def test_loop_preserves_failed_staff_retry(monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from extensions.commands import strikes
    async def run():
        owner = SimpleNamespace(pending=AsyncMock(return_value=[
            {'clan_tag': '#P2Y', 'retry_requested_at': 'one'},
            {'clan_tag': '#8GG8', 'retry_requested_at': 'two'},
        ]), consume_retry=AsyncMock())
        monkeypatch.setattr(strikes, 'StrikeTracking', lambda _: owner)
        monkeypatch.setattr(strikes, 'scan_once', AsyncMock(return_value={'#8GG8'}))
        async def stop(_):
            raise asyncio.CancelledError
        monkeypatch.setattr(strikes.asyncio, 'sleep', stop)
        with pytest.raises(asyncio.CancelledError):
            await strikes.loop(object(), object(), object())
        owner.consume_retry.assert_awaited_once_with(strikes.WARRIORS_UNITED_GUILD_ID, '#8GG8', 'two')
    asyncio.run(run())

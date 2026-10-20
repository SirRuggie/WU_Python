"""Independent CWL history checks: one-attack wars must never become strikes."""

from datetime import datetime, timedelta, timezone

import pytest

from utils.strike_store import validate_war
from utils.strike_wars import normalize, normalize_cwl


CLAN = '#2UVGQU9'
OPPONENT = '#8GG8'
WAR_TAG = '#PC9YGL0JL'
PLAYER_ZERO = '#8GG82'
PLAYER_ONE = '#YLC820G'


def raw_cwl():
    end = datetime.now(timezone.utc) - timedelta(hours=1)
    return {
        'tag': WAR_TAG, 'type': 'cwl', 'state': 'warEnded',
        'attacksPerMember': 1, 'teamSize': 2, 'endTime': end.isoformat(),
        'clan': {'tag': CLAN, 'name': 'Clan', 'attacks': 1,
                 'members': [{'tag': PLAYER_ZERO, 'name': 'Zero'},
                             {'tag': PLAYER_ONE, 'name': 'One', 'attacks': [{}]}]},
        'opponent': {'tag': OPPONENT, 'name': 'Opponent', 'attacks': 0,
                     'members': [{'tag': '#VGRJ2', 'name': 'A'},
                                 {'tag': '#CUPV2', 'name': 'B'}]},
    }


def test_cwl_normalizer_preserves_zero_and_one_attack_and_regular_stays_two():
    war = normalize_cwl(raw_cwl(), CLAN)
    assert war['type'] == 'cwl'
    assert war['war_tag'] == WAR_TAG
    assert [row['attacks'] for row in war['members']] == [0, 1]
    with pytest.raises(ValueError):
        validate_war(war)
    with pytest.raises(ValueError):
        normalize(raw_cwl(), CLAN)


@pytest.mark.parametrize('change', [
    lambda row: row.update(attacksPerMember=2),
    lambda row: row.pop('tag'),
    lambda row: row['clan']['members'].pop(),
    lambda row: row['clan']['members'][0].update(attacks=[{}, {}]),
    lambda row: row['clan'].update(attacks=2),
    lambda row: row.update(state='inWar'),
])
def test_cwl_rejects_ambiguous_or_incomplete_war(change):
    row = raw_cwl()
    change(row)
    with pytest.raises((ValueError, KeyError)):
        normalize_cwl(row, CLAN)


def test_cwl_zero_strikes_and_retry_idempotency_even_with_conflicted_owner():
    import asyncio

    from test_strike_review import Mongo
    from utils.recruit_links import PlayerOwners
    from utils.strike_store import StrikeService, status_of

    async def run():
        db = Mongo()
        async def links(tags):
            return PlayerOwners(owners={PLAYER_ONE: '456'}, conflicts=(PLAYER_ZERO,))
        service = StrikeService(db, link_resolver=links)
        row = normalize_cwl(raw_cwl(), CLAN)
        first = await service.process_cwl_war(123, row)
        second = await service.process_cwl_war(123, row)
        assert first['records'] == 2 and first['strikes'] == 0
        assert second['records'] == 0 and second['existing'] == 2
        saved = {item['player_tag']: item for item in db.strike_records.rows.values()}
        assert set(saved) == {PLAYER_ZERO, PLAYER_ONE}
        assert saved[PLAYER_ZERO]['link_status'] == 'unknown'
        assert saved[PLAYER_ZERO]['link_reason'] == 'owner_conflict'
        assert saved[PLAYER_ZERO]['attacks_used'] == 0
        assert saved[PLAYER_ZERO]['missed_attacks'] == 1
        assert saved[PLAYER_ONE]['member_id'] == 456
        assert saved[PLAYER_ONE]['attacks_used'] == 1
        assert all(item['kind'] == item['source'] == 'cwl' for item in saved.values())
        assert all(item['_id'].startswith('cwl:') for item in saved.values())
        assert all(item.get('expires_at') is None for item in saved.values())
        assert all(status_of(item) == 'recorded' for item in saved.values())
    asyncio.run(run())


def test_cwl_link_provider_failure_is_unknown_never_unlinked_or_strike():
    import asyncio

    from test_strike_review import Mongo
    from utils.recruit_links import PlayerOwners
    from utils.strike_store import StrikeService

    async def run():
        db = Mongo()
        async def links(tags):
            return PlayerOwners(owners={}, unavailable=('ClashKing',))
        service = StrikeService(db, link_resolver=links)
        result = await service.process_cwl_war(123, normalize_cwl(raw_cwl(), CLAN))
        assert result['records'] == 2 and result['strikes'] == 0
        assert {item['link_status'] for item in db.strike_records.rows.values()} == {'unknown'}
        assert {item['link_reason'] for item in db.strike_records.rows.values()} == {'link_unavailable'}
    asyncio.run(run())


def test_cwl_import_requires_preview_approval_and_stays_view_only_on_retry():
    import asyncio

    from test_strike_review import Collection, Mongo
    from utils.recruit_links import PlayerOwners
    from utils.strike_store import StrikeService

    async def run():
        db = Mongo()
        db.strike_imports = Collection()
        async def links(tags):
            return PlayerOwners(owners={})
        service = StrikeService(db, link_resolver=links)
        row = normalize_cwl(raw_cwl(), CLAN)
        first = await service.preview_import(123, [], actor_id=789, cwl_wars=[row])
        assert first['wars'] == 0 and first['strikes'] == 0
        assert first['cwl_wars'] == 1 and first['cwl_records'] == 2
        assert first['cwl_missed'] == 1
        assert {item['kind'] for item in first['items']} == {'cwl'}
        ids = {item['player_tag']: item['_id'] for item in first['items']}
        imported = await service.apply_import(123, first['preview_id'], 789,
                                              excluded_keys=[ids[PLAYER_ONE]])
        assert imported['applied'] == imported['cwl_records'] == 1
        assert imported['cwl_missed'] == 1 and imported['strikes'] == 0
        assert {item['player_tag'] for item in db.strike_records.rows.values()} == {PLAYER_ZERO}
        retried = await service.apply_import(123, first['preview_id'], 789,
                                             excluded_keys=[ids[PLAYER_ONE]])
        assert retried['applied'] == retried['cwl_records'] == 0
        assert retried['existing'] == 1
        second = await service.preview_import(123, [], actor_id=789, cwl_wars=[row])
        assert second['cwl_records'] == 1 and second['existing'] == 1
        backfill = await service.apply_import(123, second['preview_id'], 789)
        assert backfill['applied'] == 1 and backfill['strikes'] == 0
        assert len(db.strike_records.rows) == 2
    asyncio.run(run())


def test_cwl_apply_does_not_add_unapproved_new_roster_member():
    import asyncio

    from test_strike_review import Collection, Mongo
    from utils.recruit_links import PlayerOwners
    from utils.strike_store import StrikeService

    async def run():
        db = Mongo()
        db.strike_imports = Collection()
        async def links(tags):
            return PlayerOwners(owners={})
        service = StrikeService(db, link_resolver=links)
        row = normalize_cwl(raw_cwl(), CLAN)
        preview = await service.preview_import(123, [], actor_id=789, cwl_wars=[row])
        # Simulate a changed preview snapshot with an additional member that was
        # never shown to staff. Validation itself is tested separately.
        stored = db.strike_imports.rows[preview['preview_id']]['cwl_wars'][0]
        stored['members'].append({'tag': '#VGRJ2', 'name': 'New', 'attacks': 0})
        applied = await service.apply_import(123, preview['preview_id'], 789)
        assert applied['applied'] == 2 and applied['strikes'] == 0
        assert {item['player_tag'] for item in db.strike_records.rows.values()} == {PLAYER_ZERO, PLAYER_ONE}
    asyncio.run(run())


def test_monitor_regular_failure_does_not_starve_cwl(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from extensions.commands import strikes

    activation = datetime.now(timezone.utc) - timedelta(days=1)
    regular = {'type': 'regular', 'end_time': activation + timedelta(hours=1)}
    cwl = {'type': 'cwl', 'end_time': activation + timedelta(hours=2)}
    store = SimpleNamespace(ensure_indexes=AsyncMock(), monitor_activation=AsyncMock(return_value=activation),
                            sync_roster=AsyncMock(), process_war=AsyncMock(side_effect=RuntimeError('links down')),
                            process_cwl_war=AsyncMock(return_value={"records": 0}))
    cursor = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': CLAN}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: cursor),
                            strike_tracking=SimpleNamespace(update_one=AsyncMock(),
                                find_one=AsyncMock(return_value={"error_history": []})))
    coc_client = SimpleNamespace(get_clan=AsyncMock(return_value=SimpleNamespace(members=[])))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes.strike_wars, 'fetch_history_report', AsyncMock(return_value={
        'wars': [regular], 'cwl_wars': [cwl]}))
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    asyncio.run(strikes.scan_once(mongo, object(), coc_client))
    store.process_cwl_war.assert_awaited_once_with(strikes.WARRIORS_UNITED_GUILD_ID, cwl)


def test_monitor_cancellation_is_not_swallowed(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from extensions.commands import strikes

    activation = datetime.now(timezone.utc) - timedelta(days=1)
    regular = {'type': 'regular', 'end_time': activation + timedelta(hours=1)}
    store = SimpleNamespace(ensure_indexes=AsyncMock(), monitor_activation=AsyncMock(return_value=activation),
                            sync_roster=AsyncMock(), process_war=AsyncMock(side_effect=asyncio.CancelledError),
                            process_cwl_war=AsyncMock(return_value={"records": 0}))
    cursor = SimpleNamespace(to_list=AsyncMock(return_value=[{'tag': CLAN}]))
    mongo = SimpleNamespace(clans=SimpleNamespace(find=lambda *_: cursor),
                            strike_tracking=SimpleNamespace(update_one=AsyncMock(),
                                find_one=AsyncMock(return_value={"error_history": []})))
    coc_client = SimpleNamespace(get_clan=AsyncMock(return_value=SimpleNamespace(members=[])))
    monkeypatch.setattr(strikes, 'service', lambda *_: store)
    monkeypatch.setattr(strikes.strike_wars, 'fetch_history_report', AsyncMock(return_value={
        'wars': [regular], 'cwl_wars': []}))
    monkeypatch.setattr(strikes, '_warm_weight_cache', AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(strikes.scan_once(mongo, object(), coc_client))

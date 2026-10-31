"""Synthetic confirmed receipts: binding, corrections, ambiguity and strike policy."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.fwa_war_plan_store import WarPlanStore, capture_binding
from tests.test_strike_streaks import Collection, setup, war, GUILD, CLAN


def fixture():
    db, service = setup()
    db.fwa_war_plans = Collection()
    db.fwa_war_plans.create_index = AsyncMock()
    return db, service, WarPlanStore(db)


async def record(store, current, outcome='mismatch', message=1, **overrides):
    binding = {'clan_tag': CLAN, 'opponent_tag': current['opponent_tag'],
               'opponent_name': 'Enemy', 'bound': True,
               'preparation_start': current['end_time'] - timedelta(days=2),
               'war_end': current['end_time']}
    posted_at = overrides.pop('posted_at', current['end_time'] - timedelta(hours=1))
    binding.update(overrides)
    await store.record(guild_id=GUILD, message_id=message, channel_id=7, actor_id=8,
                       outcome=outcome, binding=binding, posted_at=posted_at)


@pytest.mark.parametrize('state,bound', [('preparation', True), ('inWar', True), ('notInWar', False)])
def test_capture_binding(state, bound):
    async def run():
        end = war(0)['end_time']
        current = SimpleNamespace(state=state, opponent=SimpleNamespace(tag='#8GG8', name='Enemy'),
            preparation_start_time=SimpleNamespace(time=end-timedelta(days=2)),
            end_time=SimpleNamespace(time=end))
        client = SimpleNamespace(get_clan_war=AsyncMock(return_value=current))
        result = await capture_binding(client, CLAN, 'Enemy')
        assert result['bound'] is bound
        if bound:
            assert result['war_end'] == end and result['opponent_tag'] == '#8GG8'
        conflict = await capture_binding(client, CLAN, 'Next opponent')
        assert not conflict['bound']
    asyncio.run(run())


@pytest.mark.parametrize('outcome,strikes', [('mismatch', 0), ('win', 1), ('lose', 1), ('blacklisted', 1), (None, 1)])
def test_fwa_policy(outcome, strikes):
    async def run():
        db, service, store = fixture()
        current = war(0, attacks=0)
        if outcome:
            await record(store, current, outcome)
        result = await service.process_war(GUILD, current)
        assert result['strikes'] == strikes
        row = next(iter(db.strike_records.rows.values()))
        assert row['kind'] == ('mismatch' if outcome == 'mismatch' else 'strike')
        if outcome is None:
            assert row['war_plan_reason'] == 'War plan not found'
        # Repeated processing must not relabel an already finalized receipt.
        await record(store, current, 'win' if outcome == 'mismatch' else 'mismatch', message=2,
                     posted_at=current['end_time']-timedelta(minutes=1))
        await service.process_war(GUILD, current)
        assert next(iter(db.strike_records.rows.values()))['kind'] == row['kind']
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['CWL', 'Tactical', 'Flexible Fun', 'fwa'])
def test_non_fwa_ignores_mismatch(kind):
    async def run():
        db, service, store = fixture()
        db.clans.rows['clan']['type'] = kind
        current = war(0, attacks=0)
        await record(store, current)
        assert (await service.process_war(GUILD, current))['strikes'] == 1
    asyncio.run(run())


def test_latest_confirmed_correction_wins_and_rename_uses_tag():
    async def run():
        _, _, store = fixture()
        current = war(0)
        await record(store, current)
        await record(store, current, 'win', message=2, posted_at=current['end_time']-timedelta(minutes=1))
        current['opponent_name'] = 'Renamed'
        assert await store.outcome(GUILD, current) == ('win', 'Latest confirmed war plan used')
    asyncio.run(run())


@pytest.mark.parametrize('change', ['late', 'unbound', 'opponent', 'tie', 'start', 'early'])
def test_unclear_receipts_never_suppress(change):
    async def run():
        _, service, store = fixture()
        current = war(0, attacks=0)
        overrides = {'posted_at': current['end_time']+timedelta(seconds=1)} if change == 'late' else {}
        if change == 'unbound': overrides['bound'] = False
        if change == 'opponent': overrides['opponent_tag'] = '#999'
        if change == 'early': overrides['posted_at'] = current['end_time']-timedelta(days=3)
        await record(store, current, **overrides)
        if change == 'tie': await record(store, current, 'win', message=2)
        if change == 'start': await record(store, current, message=2, preparation_start=current['end_time']-timedelta(days=1))
        assert await store.outcome(GUILD, current) == (None, 'War plan unclear')
        assert (await service.process_war(GUILD, current))['strikes'] == 1
    asyncio.run(run())


def test_storage_failure_uses_normal_strikes():
    async def run():
        db, service, _ = fixture()
        db.fwa_war_plans.find = lambda *args: (_ for _ in ()).throw(RuntimeError('unavailable'))
        assert (await service.process_war(GUILD, war(0, attacks=0)))['strikes'] == 1
        assert next(iter(db.strike_records.rows.values()))['war_plan_reason'] == 'War plan check failed'
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['none', 'send', 'receipt'])
def test_command_records_only_confirmed_post_and_never_retries(monkeypatch, failure):
    from extensions.commands.fwa import war_plans
    from tests.test_fwa_war_messages import Context, mongo
    async def run():
        db = mongo()
        db.clans = SimpleNamespace(find_one=AsyncMock(return_value={'tag': CLAN, 'announcement_id': 777}))
        db.fwa_war_plans = Collection()
        db.fwa_war_plans.create_index = AsyncMock()
        if failure == 'receipt':
            db.fwa_war_plans.insert_one = AsyncMock(side_effect=RuntimeError('storage unavailable'))
        monkeypatch.setattr(war_plans, 'Clan', lambda data: SimpleNamespace(announcement_id=777))
        current = SimpleNamespace(state='inWar', opponent=SimpleNamespace(tag='#8GG8', name='Enemy'),
            preparation_start_time=SimpleNamespace(time=war(0)['end_time']-timedelta(days=2)),
            end_time=SimpleNamespace(time=war(0)['end_time']))
        client = SimpleNamespace(get_clan_war=AsyncMock(return_value=current))
        ctx = Context()
        ctx.member.display_name = 'Planner'
        send = AsyncMock(return_value=SimpleNamespace(id=555))
        if failure == 'send': send.side_effect = TimeoutError('uncertain send')
        ctx.client = SimpleNamespace(rest=SimpleNamespace(create_message=send))
        command = war_plans.WarPlans()
        command.clan_name = f'Clan|{CLAN}|12345'
        command.war_result = 'mismatch'
        command.opponent = 'Enemy'
        await command.invoke(ctx, mongo=db, coc_client=client)
        assert send.await_count == 1
        assert len(db.fwa_war_plans.rows) == (1 if failure == 'none' else 0)
        if failure == 'receipt':
            assert 'Message posted, but' in str(ctx.events)
            assert 'Error Posting Message' not in str(ctx.events)
        if failure == 'none':
            receipt = db.fwa_war_plans.rows['20:555']
            assert receipt['bound'] and receipt['outcome'] == 'mismatch'
    asyncio.run(run())


@pytest.mark.parametrize('outcome,expected', [('mismatch', 0), ('win', 1), (None, 1)])
def test_import_uses_receipts_without_rewriting_existing_rows(outcome, expected):
    async def run():
        db, service, store = fixture()
        db.strike_imports = Collection()
        current = war(0, attacks=0)
        if outcome: await record(store, current, outcome)
        preview = await service.preview_import(GUILD, [current], 9)
        assert preview['strikes'] == expected
        result = await service.apply_import(GUILD, preview['preview_id'], 9)
        assert result['strikes'] == expected and result['applied'] == 1
        saved = dict(next(iter(db.strike_records.rows.values())))
        await record(store, current, 'win', message=2, posted_at=current['end_time']-timedelta(minutes=1))
        later = await service.preview_import(GUILD, [current], 9)
        await service.apply_import(GUILD, later['preview_id'], 9)
        assert next(iter(db.strike_records.rows.values())) == saved
    asyncio.run(run())


def test_changed_mismatch_preview_requires_new_review():
    async def run():
        db, service, store = fixture()
        db.strike_imports = Collection()
        current = war(0, attacks=0)
        await record(store, current)
        preview = await service.preview_import(GUILD, [current], 9)
        await record(store, current, 'win', message=2, posted_at=current['end_time']-timedelta(minutes=1))
        result = await service.apply_import(GUILD, preview['preview_id'], 9)
        assert result['applied'] == 0 and not db.strike_records.rows
        assert result['deferred_accounts'][0]['reason'] == 'War plan changed; create a new preview'
    asyncio.run(run())


@pytest.mark.parametrize('typed', ['  ENEMY   CLAN ', '#8gg8'])
def test_binding_normalizes_name_or_uses_explicit_tag(typed):
    async def run():
        end = war(0)['end_time']
        current = SimpleNamespace(state='inWar', opponent=SimpleNamespace(tag='#8GG8', name='Enemy  Clan'),
            preparation_start_time=SimpleNamespace(time=end-timedelta(days=2)), end_time=SimpleNamespace(time=end))
        result = await capture_binding(SimpleNamespace(get_clan_war=AsyncMock(return_value=current)), CLAN, typed)
        assert result['bound']
    asyncio.run(run())


def test_unbound_next_opponent_does_not_shadow_bound_receipt():
    async def run():
        _, _, store = fixture()
        current = war(0)
        await record(store, current)
        await record(store, current, 'win', message=2, bound=False, opponent_tag='#999')
        assert await store.outcome(GUILD, current) == ('mismatch', 'Confirmed war plan used')
    asyncio.run(run())

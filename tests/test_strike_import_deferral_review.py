"""Independent per-account import deferral and approval regressions."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from test_strike_review import Collection, Mongo
from utils.recruit_links import PlayerOwners
from utils.strike_store import StrikeService


A = '#PC9YGL0JL'
B = '#8GG82'
C = '#YLC820G'


def war():
    return {'clan_tag': '#2UVGQU9', 'opponent_tag': '#8GG8',
            'end_time': datetime.now(timezone.utc) - timedelta(hours=1),
            'type': 'regular', 'state': 'warEnded', 'attacks_per_member': 2,
            'complete': True,
            'members': [{'tag': value, 'name': value, 'attacks': 0} for value in (A, B, C)]}


def test_per_account_conflict_and_role_outage_do_not_block_genuinely_unlinked_miss():
    async def run():
        db = Mongo()
        db.strike_imports = Collection()
        status = {'disputed': True, 'roles_up': False}
        async def links(tags):
            return PlayerOwners(owners={C: '456', **({} if status['disputed'] else {A: '789'})},
                                conflicts=(A,) if status['disputed'] else ())
        async def roles(guild, member):
            return [] if status['roles_up'] else None
        ledger = StrikeService(db, link_resolver=links, role_resolver=roles)
        current_war = war()
        first = await ledger.preview_import(123, [current_war], actor_id=999)
        assert first['wars'] == 1 and first['strikes'] == 1
        assert first['deferred_count'] == 2
        assert {row['player_tag'] for row in first['items']} == {B}
        assert first['items'][0]['link_status'] == 'unlinked'
        assert {row['player_tag'] for row in first['deferred_accounts']} == {A, C}
        approved = db.strike_imports.rows[first['preview_id']]['approved_rows']
        assert len(approved) == 1

        status.update(disputed=False, roles_up=True)
        applied = await ledger.apply_import(123, first['preview_id'], 999)
        assert applied['applied'] == 1 and applied['strikes'] == 1
        assert applied['deferred_count'] == 2
        assert {row['player_tag'] for row in db.strike_records.rows.values()} == {B}

        second = await ledger.preview_import(123, [current_war], actor_id=999)
        assert second['strikes'] == 2 and second['existing'] == 1
        once = await ledger.apply_import(123, second['preview_id'], 999)
        twice = await ledger.apply_import(123, second['preview_id'], 999)
        assert once['applied'] == 2 and twice['applied'] == 0
        assert len(db.strike_records.rows) == 3
    asyncio.run(run())


def test_link_provider_outage_cannot_be_recorded_as_unlinked():
    async def run():
        db = Mongo()
        db.strike_imports = Collection()
        async def links(tags):
            return PlayerOwners(owners={}, unavailable=('ClashKing',))
        ledger = StrikeService(db, link_resolver=links, role_resolver=lambda guild, member: [])
        report = await ledger.preview_import(123, [war()], actor_id=999)
        assert report['wars'] == 0 and report['strikes'] == 0
        assert report['items'] == [] and len(report['skipped']) == 1
        with pytest.raises(RuntimeError, match='links unavailable'):
            await ledger.process_war(123, war())
        assert db.strike_records.rows == {}
    asyncio.run(run())

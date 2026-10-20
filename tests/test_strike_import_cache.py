"""Import link lookups are reused within one operation, not across approvals."""
import asyncio
from datetime import timedelta

from test_strike_review import Collection, Mongo, war
from utils.recruit_links import PlayerOwners
from utils.strike_store import StrikeService


def test_preview_reuses_links_but_apply_checks_links_again():
    async def run():
        db = Mongo()
        db.strike_imports = Collection()
        calls = []
        async def links(tags):
            calls.append(tags)
            return PlayerOwners(owners={})
        service = StrikeService(db, link_resolver=links)
        first = war()
        second = {**first, 'end_time': first['end_time'] - timedelta(days=1)}
        preview = await service.preview_import(123, [first, second], actor_id=789)
        assert len(calls) == 1
        assert preview['strikes'] == 2
        result = await service.apply_import(123, preview['preview_id'], 789)
        assert len(calls) == 2
        assert result['strikes'] == 2
    asyncio.run(run())


def test_failed_link_lookup_is_not_cached_as_unlinked():
    async def run():
        db = Mongo()
        db.strike_imports = Collection()
        calls = []
        async def links(tags):
            calls.append(tags)
            return PlayerOwners(unavailable=('ClashKing',)) if len(calls) == 1 else PlayerOwners()
        service = StrikeService(db, link_resolver=links)
        first = war()
        second = {**first, 'end_time': first['end_time'] - timedelta(days=1)}
        preview = await service.preview_import(123, [first, second], actor_id=789)
        assert len(calls) == 2
        assert len(preview['skipped']) == 1
        assert preview['strikes'] == 1
    asyncio.run(run())

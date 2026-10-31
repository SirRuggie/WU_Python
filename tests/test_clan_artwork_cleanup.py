import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from utils import clan_dashboard_history as history


class Cursor:
    def __init__(self, events): self.events = events
    def sort(self, *args): return self
    def limit(self, *args): return self
    async def to_list(self, **kwargs): return self.events


def test_cleanup_retries_failure_and_keeps_referenced_foreign_and_static_art(monkeypatch):
    old = 'https://images.example/clans/Test/logo.0123456789.png'
    shared = 'https://images.example/clans/Test/banner.0123456789.webp'
    events = [{'_id': 'one', 'artwork_cleanup': [old, shared, 'foreign', 'static']}]
    rows = NS(find=lambda query: Cursor(events), find_one=AsyncMock(return_value=None), update_one=AsyncMock())
    monkeypatch.setattr(history, 'collection', lambda db: rows)
    db = NS(clans=NS(find_one=AsyncMock(side_effect=lambda query, projection: {'_id': 'other'} if query['$or'][0]['logo'] == shared else None)))
    media = NS(key_for_url=lambda url: url.removeprefix('https://images.example/') if url.startswith('https://images.example/') else None,
               delete_url=AsyncMock(side_effect=RuntimeError('R2 unavailable')))
    asyncio.run(history.cleanup_artwork(db, media))
    assert not any(call.args[1]['$set'].get('artwork_cleanup_done') for call in rows.update_one.await_args_list)
    media.delete_url.side_effect = None
    asyncio.run(history.cleanup_artwork(db, media))
    assert media.delete_url.await_args.args == (old,)
    assert not any(call.args[1]['$set'].get('artwork_cleanup_done') for call in rows.update_one.await_args_list)  # The other clan still uses the banner.
    db.clans.find_one.side_effect = None
    db.clans.find_one.return_value = None
    asyncio.run(history.cleanup_artwork(db, media))
    assert any(call.args == ({'_id': 'one'}, {'$set': {'artwork_cleanup_done': True}}) for call in rows.update_one.await_args_list)
    assert [call.args[0] for call in media.delete_url.await_args_list] == [old, old, old, shared]


def test_successful_artwork_diff_records_durable_cleanup_intent(monkeypatch):
    rows = NS(update_one=AsyncMock(return_value=NS(matched_count=1)))
    monkeypatch.setattr(history, 'collection', lambda db: rows)
    asyncio.run(history.finish_change(None, 'event', {'logo': 'old', 'banner': ''}, {'logo': 'new', 'banner': 'first'}))
    saved = rows.update_one.await_args.args[1]['$set']
    assert saved['confirmed'] is True
    assert saved['artwork_cleanup'] == ['old']


def test_removed_snapshot_keeps_reused_logo_and_rechecks_each_pass(monkeypatch):
    url = 'https://images.example/clans/Test/logo.0123456789.png'
    rows = NS(find=lambda query: Cursor([{'_id': 'replacement', 'artwork_cleanup': [url]}]),
              find_one=AsyncMock(return_value={'_id': 'removed'}), update_one=AsyncMock())
    monkeypatch.setattr(history, 'collection', lambda db: rows)
    db = NS(clans=NS(find_one=AsyncMock(return_value=None)))
    media = NS(key_for_url=lambda value: value.removeprefix('https://images.example/'), delete_url=AsyncMock())
    for _ in range(2):
        asyncio.run(history.cleanup_artwork(db, media))
    media.delete_url.assert_not_awaited()
    assert rows.find_one.await_count == 2
    assert rows.find_one.await_args.args[0]['action'] == 'before_remove'
    assert not any(call.args[1]['$set'].get('artwork_cleanup_done') for call in rows.update_one.await_args_list)
    # Restoration returns the same logo to a live clan; it remains protected.
    db.clans.find_one.return_value = {'logo': url}
    asyncio.run(history.cleanup_artwork(db, media))
    media.delete_url.assert_not_awaited()


def test_snapshot_lookup_uses_persisted_nested_field_names(monkeypatch):
    url = 'https://images.example/clans/Test/logo.0123456789.png'
    snapshots = [{'_id': 'removed', 'action': 'before_remove', 'clan': {'logo': url, 'tag': '#ABC'}}]
    async def lookup(query, projection=None):
        for row in snapshots:
            if row['action'] != query.get('action'):
                continue
            for clause in query.get('$or', []):
                for path, value in clause.items():
                    current = row
                    for key in path.split('.'):
                        current = current.get(key) if isinstance(current, dict) else None
                    if current == value:
                        return row
        return None
    rows = NS(find=lambda query: Cursor([{'_id': 'replacement', 'artwork_cleanup': [url]}]), find_one=AsyncMock(side_effect=lookup), update_one=AsyncMock())
    monkeypatch.setattr(history, 'collection', lambda db: rows)
    db = NS(clans=NS(find_one=AsyncMock(return_value=None)))
    media = NS(key_for_url=lambda value: value.removeprefix('https://images.example/'), delete_url=AsyncMock())
    asyncio.run(history.cleanup_artwork(db, media))
    media.delete_url.assert_not_awaited()

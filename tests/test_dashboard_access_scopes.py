import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
from cwl_web.store import Store
from cwl_web.access_control import scopes, PERMISSIONS, SECTION_SCOPE
from cwl_web.server_management import allowed
from cwl_web.app import _editor


def test_legacy_grants_only_migrate_to_cwl(tmp_path):
    path = tmp_path / 'old.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE grants (user_id TEXT PRIMARY KEY, granted_by TEXT, granted_at TEXT)')
        db.execute("INSERT INTO grants VALUES ('123','owner','today')")
    store = Store(str(path))
    assert scopes(store, '123') == ['cwl']
    assert scopes(store, '456') == []
    assert scopes(Store(str(path)), '123') == ['cwl']


def test_server_grant_does_not_grant_cwl(tmp_path):
    store = Store(str(tmp_path / 'test.sqlite'))
    with store.tx() as db:
        db.execute('INSERT INTO grants(user_id,granted_by,permissions) VALUES (?,?,?)', ('123', 'owner', json.dumps(['tickets'])))
    request = SimpleNamespace(app={'store': store})
    assert not _editor(request, {'user_id': '123', 'guild_owner': False})
    with store.tx() as db:
        db.execute("UPDATE grants SET permissions='[\"cwl\"]'")
    assert _editor(request, {'user_id': '123', 'guild_owner': False})


def test_every_scope_is_isolated_and_revocation_is_live():
    async def run():
        lookup = AsyncMock()
        db = SimpleNamespace(bot_config=SimpleNamespace(find_one=lookup))
        for scope in PERMISSIONS:
            lookup.return_value = {'permissions': [scope]}
            actor = {'user_id': '123', 'dashboard': True, 'dashboard_scopes': [scope], 'permissions': 8, 'role_ids': set()}
            for section, expected in SECTION_SCOPE.items():
                for write in (False, True):
                    assert await allowed(actor, section, db, write=write) == (scope == expected)
            assert not await allowed(actor, 'unknown', db)
        lookup.return_value = None
        assert not await allowed(actor, 'band_monitor', db, write=True)
        # The bot worker must reread the grant even after a job was queued.
        actor.pop('dashboard_scopes')
        assert not await allowed(actor, 'band_monitor', db, write=True)
        lookup.return_value = {'permissions': ['server_tools']}
        assert await allowed(actor, 'band_monitor', db, write=True)
    asyncio.run(run())


def test_owners_keep_access_but_discord_admin_alone_does_not():
    async def run():
        db = SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value=None)))
        actor = {'user_id': '123', 'dashboard': True, 'permissions': 8, 'role_ids': set()}
        assert not await allowed(actor, 'roles', db)
        for owner in ({**actor, 'user_id': '644005027052126208'}, {**actor, 'user_id': '505227988229554179'}):
            for section in SECTION_SCOPE:
                assert await allowed(owner, section, db, write=True)
    asyncio.run(run())


def test_ticket_control_accepts_only_live_dashboard_ticket_grant():
    import pytest
    from extensions.commands import tickets  # Initialize native package before its control module.
    from utils.ticket_testing_control import _admin
    async def run():
        lookup = AsyncMock(return_value={'permissions': ['tickets']})
        db = SimpleNamespace(bot_config=SimpleNamespace(find_one=lookup), ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={'ticket_target_guild_id': 644963518025826315})))
        ctx = SimpleNamespace(guild_id=644963518025826315, dashboard_actor={'user_id': '123', 'dashboard': True})
        await _admin(ctx, db)
        lookup.return_value = {'permissions': ['cwl']}
        with pytest.raises(ValueError, match='access changed'):
            await _admin(ctx, db)
        ctx.guild_id = 10
        with pytest.raises(ValueError, match='different server'):
            await _admin(ctx, db)
    asyncio.run(run())

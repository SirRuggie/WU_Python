import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from extensions.commands.clan.dashboard import fwa_data
from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE


@pytest.mark.parametrize("authorized", [False, True])
def test_retired_expired_edits_keep_authorization_and_never_write(monkeypatch, authorized):
    authorize = AsyncMock(return_value=authorized)
    monkeypatch.setattr(fwa_data, 'require_dashboard_role', authorize)
    collection = SimpleNamespace(find_one=AsyncMock(), update_one=AsyncMock())
    media = SimpleNamespace(upload_from_url=AsyncMock())
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), respond=AsyncMock())
    before = (dict(FWA_WAR_BASE), dict(FWA_ACTIVE_WAR_BASE))
    for action in (fwa_data.fwa_link_submit, fwa_data.fwa_images_submit, fwa_data.fwa_descriptions_submit):
        asyncio.run(action(ctx=ctx, action_id='th18|expired',
                           mongo=SimpleNamespace(fwa_data=collection), media=media))
        if authorized:
            payload = ctx.respond.await_args.kwargs
            assert 'Town Halls' in str(payload['components'][0].build())
            assert payload['user_mentions'] is payload['role_mentions'] is payload['mentions_everyone'] is False
        else:
            ctx.respond.assert_not_awaited()
        ctx.respond.reset_mock()
    assert authorize.await_count == 3
    assert authorize.await_args.args == (ctx, fwa_data.FWA_REP_ROLE_ID, 'FWA Clan Rep')
    collection.find_one.assert_not_awaited()
    collection.update_one.assert_not_awaited()
    media.upload_from_url.assert_not_awaited()
    assert (dict(FWA_WAR_BASE), dict(FWA_ACTIVE_WAR_BASE)) == before

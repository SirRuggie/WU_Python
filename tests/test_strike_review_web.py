"""Read-only review refresh preserves guild ownership and existing grants."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from cwl_web import strikes
from tests.test_strike_streaks import setup, war, GUILD
from utils.strike_tracking import StrikeTracking


def test_public_review_lookup_keeps_guild_scope_and_resolution_receipt():
    async def run():
        db, ledger = setup()
        tracking = StrikeTracking(db)
        sample = war(1)
        await tracking.observe(GUILD, sample)
        await tracking.quarantine_old(GUILD, sample)
        row = next(iter(db.strike_war_snapshots.rows.values()))
        assert await tracking.review(GUILD+1, row['war_key']) is None
        review = await tracking.review(GUILD, row['war_key'])
        assert review['manual_review_required'] and review['review_revision'] == 1
        await tracking.resolve_review(GUILD, row['war_key'], 1, 'Confirmed', 123)
        review = await tracking.review(GUILD, row['war_key'])
        assert not review['manual_review_required'] and review['review_resolution']['reason'] == 'Confirmed'
    asyncio.run(run())


def test_review_refresh_uses_read_grant_before_any_lookup():
    async def run():
        deny = AsyncMock(side_effect=web.HTTPForbidden())
        with patch.object(strikes.shared, 'require_manage', deny), patch.object(strikes, 'StrikeTracking') as owner:
            with pytest.raises(web.HTTPForbidden):
                await strikes.tracking_review(SimpleNamespace(method='GET', query={'war_key':'war'}))
            owner.assert_not_called()
            assert deny.call_args.args[1] == 'strikes_read' and deny.call_args.kwargs['write'] is False
    asyncio.run(run())

"""Safe ordinary-capture diagnostics; unknown states retain warnings."""

import asyncio
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from cwl_web import participation_sync
from cwl_web.providers import LiveProviders, ProviderUnavailable
import test_participation_waiting as waiting_fixtures


class ExplicitStateTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = waiting_fixtures.NoGroupTests.asyncSetUp
    asyncTearDown = waiting_fixtures.NoGroupTests.asyncTearDown
    auth = waiting_fixtures.NoGroupTests.auth
    call = waiting_fixtures.NoGroupTests.call
    revision = waiting_fixtures.NoGroupTests.revision
    signup = waiting_fixtures.NoGroupTests.signup
    setup_published = waiting_fixtures.NoGroupTests.setup_published
    set_group = waiting_fixtures.NoGroupTests.set_group
    set_war = waiting_fixtures.NoGroupTests.set_war
    sync = waiting_fixtures.NoGroupTests.sync
    account = waiting_fixtures.NoGroupTests.account
    base = waiting_fixtures.NoGroupTests.base
    prepare = waiting_fixtures.NoGroupTests.prepare
    result = waiting_fixtures.NoGroupTests.result

    async def test_unconfirmed_empty_states_keep_warnings_and_unknown_counts(self):
        await self.prepare()
        provider = LiveProviders(coc_token="fixture", mongo_uri="")
        self.providers.league_group = provider.league_group
        for state in ("groupNotFound",):
            with self.subTest(state=state), patch.object(
                provider, "_league_get", AsyncMock(return_value={"state": state})
            ):
                row, data = await self.result()
            self.assertNotEqual(data["sync"]["status"], "waiting")
            self.assertIsNone(row["source_attacks"])
            self.assertEqual(self.league.war_calls, [])

    async def test_unknown_denied_and_contradictory_responses_keep_warnings(self):
        await self.prepare()
        provider = LiveProviders(coc_token="fixture", mongo_uri="")
        self.providers.league_group = provider.league_group
        bodies = [
            {"state": state}
            for state in (
                "accessDenied",
                "clanNotFound",
                "inMatchmaking",
                "unknown",
                None,
                [],
                {},
            )
        ]
        for body in bodies:
            with self.subTest(body=body), patch.object(
                provider, "_league_get", AsyncMock(return_value=body)
            ):
                _, data = await self.result()
            self.assertNotEqual(data["sync"]["status"], "waiting")

    async def test_not_in_war_does_not_hide_own_stored_preparation_group(self):
        await self.prepare()
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO participation_group_observations VALUES(?,?,'#C2Y',?,'PREPARATION','[]','[]','2026-11-01T00:00:00Z')",
                (self.sid, "2026-11", "2026-11"),
            )
        provider = LiveProviders(coc_token="fixture", mongo_uri="")
        self.providers.league_group = provider.league_group
        with patch.object(
            provider, "_league_get", AsyncMock(return_value={"state": "notInWar"})
        ):
            _, data = await self.result()
        self.assertNotEqual(data["sync"]["status"], "waiting")


def test_diagnostics_keep_only_safe_reason_and_state_codes(caplog):
    caplog.set_level(logging.INFO, logger="cwl_web.participation_sync")

    async def run():
        provider = LiveProviders(coc_token="fixture", mongo_uri="")
        with patch.object(
            provider,
            "_league_get",
            AsyncMock(return_value={"state": "notInWar", "rounds": "bad"}),
        ):
            result = await participation_sync._fetch_groups(
                provider, ["#C2Y"], "2026-11"
            )
        assert result[0][2] == "no_group"
        error = ProviderUnavailable("DO_NOT_LOG_EXTERNAL_TEXT")
        fake = SimpleNamespace(league_group=AsyncMock(side_effect=error))
        await participation_sync._fetch_groups(fake, ["#C2Y"], "2026-11")

    asyncio.run(run())
    messages = "\n".join(record.message for record in caplog.records)
    assert "reason=not_in_war" in messages
    assert "group_state=NOT_IN_WAR" in messages
    assert "error_type=ProviderUnavailable" in messages
    assert "DO_NOT_LOG_EXTERNAL_TEXT" not in messages
    assert "reason=other" in messages
    assert "clan=#C2Y" in messages


def test_malformed_state_and_outages_never_log_external_text_or_become_no_group(caplog):
    caplog.set_level(logging.INFO, logger="cwl_web.participation_sync")

    async def run():
        for status in (None, 403, 429, 500):
            error = ProviderUnavailable("DO_NOT_LOG_REMOTE_BODY")
            error.status_code = status
            error.group_state = "DO_NOT_LOG_REMOTE_STATE"
            fake = SimpleNamespace(league_group=AsyncMock(side_effect=error))
            result = await participation_sync._fetch_groups(fake, ["#C2Y"], "2026-11")
            assert result[0][2] == "unavailable"
        fake = SimpleNamespace(league_group=AsyncMock(side_effect=TimeoutError()))
        assert (await participation_sync._fetch_groups(fake, ["#C2Y"], "2026-11"))[0][
            2
        ] == "unavailable"

    asyncio.run(run())
    messages = "\n".join(r.message for r in caplog.records)
    assert "DO_NOT_LOG_REMOTE" not in messages
    assert "reason=other" in messages and "group_state=other" in messages

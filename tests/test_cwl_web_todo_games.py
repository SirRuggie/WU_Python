"""Clan Games Todo activity is observational and fails closed."""

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from cwl_web import todo_games


def account(tag="#P2Y", th=16):
    return SimpleNamespace(tag=tag, name="Main", town_hall=th, clan_tag="#Q2Y",
                           clan_name="Warriors United", clan_badge=None)


def event(when, previous=0, current=250, delta=250):
    return {"eventTime": when.isoformat().replace("+00:00", "Z"), "clanTag": "#Q2Y",
            "statType": "clan_games", "previousValue": previous,
            "currentValue": current, "delta": delta}


class GamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_observed_activity_only_current_month_and_deduplicated(self):
        now = datetime.now(timezone.utc)
        start, _ = todo_games._month_window(now)
        good = event(now - timedelta(minutes=1))
        old = event(start - timedelta(seconds=1), 0, 4000, 4000)

        async def fetch(*args):
            return [good, good, old, event(now - timedelta(minutes=2), 250, 600, 350)]

        with patch.object(todo_games, "_fetch_history", fetch):
            view = await todo_games.build_games_view([account(), account("#Q2Y", th=5)])
        row, = view["rows"]
        self.assertEqual(row["used"], 600)
        self.assertIsNone(row["remaining"])
        self.assertEqual(row["total"], 1000)
        self.assertEqual(row["state"], "partial")
        self.assertIsNone(row["starts_at"])
        self.assertIsNone(row["ends_at"])
        self.assertTrue(view["ok"])  # feed loaded, but old item makes it partial
        self.assertIn("ClashKing", view["note"])

    async def test_no_record_is_unknown_not_zero(self):
        async def fetch(*args):
            return []

        with patch.object(todo_games, "_fetch_history", fetch):
            view = await todo_games.build_games_view([account()])
        row, = view["rows"]
        self.assertEqual(row["state"], "unknown")
        self.assertIsNone(row["used"])
        self.assertIsNone(row["total"])
        self.assertIsNone(row["remaining"])
        self.assertTrue(view["ok"])
        self.assertTrue(view["incomplete"])

    async def test_goal_reached_from_valid_positive_changes(self):
        now = datetime.now(timezone.utc)
        async def fetch(*args):
            return [event(now - timedelta(minutes=1), 0, 1100, 1100)]

        with patch.object(todo_games, "_fetch_history", fetch):
            view = await todo_games.build_games_view([account()])
        self.assertTrue(view["ok"])
        self.assertEqual(view["rows"][0]["state"], "goal_reached")
        self.assertEqual(view["rows"][0]["remaining"], 0)

    async def test_invalid_and_limit_truncated_are_partial(self):
        now = datetime.now(timezone.utc)
        valid = event(now - timedelta(minutes=1))
        bad = event(now - timedelta(minutes=2), 0, 1, True)
        async def fetch(*args):
            return [valid, bad]

        with patch.object(todo_games, "_fetch_history", fetch):
            view = await todo_games.build_games_view([account()])
        self.assertEqual(view["rows"][0]["state"], "partial")
        self.assertEqual(view["rows"][0]["used"], 250)
        self.assertIsNone(view["rows"][0]["remaining"])
        self.assertTrue(view["ok"])

        async def full(*args):
            return [valid] * todo_games.HISTORY_LIMIT
        with patch.object(todo_games, "_fetch_history", full):
            view = await todo_games.build_games_view([account()])
        self.assertEqual(view["rows"][0]["state"], "partial")
        self.assertTrue(view["incomplete"])

    async def test_provider_failure_keeps_account_unknown(self):
        async def fetch(*args):
            raise TimeoutError()

        with patch.object(todo_games, "_fetch_history", fetch):
            view = await todo_games.build_games_view([account()])
        self.assertFalse(view["ok"])
        self.assertTrue(view["unavailable"])
        self.assertIsNone(view["rows"][0]["used"])


    async def test_mismatched_delta_and_conflicting_event_are_excluded(self):
        now = datetime.now(timezone.utc)
        good = event(now - timedelta(minutes=1), 0, 250, 250)
        conflict = event(now - timedelta(minutes=1), 0, 300, 300)
        unrelated = event(now - timedelta(minutes=2), 0, 100, 100)
        mismatch = event(now - timedelta(minutes=3), 0, 500, 400)

        async def fetch(*args):
            return [good, conflict, unrelated, mismatch]

        with patch.object(todo_games, "_fetch_history", fetch):
            view = await todo_games.build_games_view([account()])
        self.assertTrue(view["ok"])
        self.assertEqual(view["rows"][0]["used"], 100)
        self.assertEqual(view["rows"][0]["state"], "partial")
        self.assertIsNone(view["rows"][0]["remaining"])

    async def test_stream_reads_every_chunk_and_enforces_size(self):
        class Response:
            status = 200
            content_type = "application/json"

            def __init__(self, chunks):
                self.chunks = chunks
                self.content = self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def iter_chunked(self, size):
                for chunk in self.chunks:
                    yield chunk

        class Session:
            def __init__(self, chunks):
                self.chunks = chunks
                self.params = None

            def get(self, url, **kwargs):
                self.params = kwargs["params"]
                return Response(self.chunks)

        now = datetime.now(timezone.utc)
        start, _ = todo_games._month_window(now)
        payload = json.dumps({"items": [event(now - timedelta(minutes=1))]}).encode()
        session = Session([payload[:11], payload[11:]])
        items = await todo_games._fetch_history(session, "#P2Y", start, now, asyncio.Semaphore(1))
        self.assertEqual(len(items), 1)
        self.assertEqual(session.params["type"], "clan_games")
        self.assertEqual(session.params["limit"], "500")

        huge = Session([b" " * (todo_games.MAX_RESPONSE_BYTES + 1)])
        with self.assertRaisesRegex(ValueError, "too large"):
            await todo_games._fetch_history(huge, "#P2Y", start, now, asyncio.Semaphore(1))


if __name__ == "__main__":
    unittest.main()

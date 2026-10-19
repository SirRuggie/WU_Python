"""Read-only FWA Stats parser, cache, and additive source metadata migration."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cwl_web.providers import LiveProviders, ProviderUnavailable
from cwl_web.store import Store


class Response:
    status = 200
    content_type = "application/json"

    def __init__(self, payload):
        self.data = json.dumps(payload).encode()
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def iter_chunked(self, size):
        midpoint = len(self.data) // 2
        yield self.data[:midpoint]
        yield self.data[midpoint:]


class Session:
    def __init__(self, payload, calls):
        self.payload = payload
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append(url)
        return Response(self.payload)


class WeightSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_weights_timestamp_and_cache(self):
        rows = [
            {"tag": "#P2Y", "weight": 176000, "townhall": 16,
             "lastModified": "2026-05-15T11:37:17Z"},
            {"tag": "#Q2Y", "weight": 168000, "townhall": 15,
             "lastModified": "2026-10-14T11:41:03Z"},
        ]
        calls = []
        provider = LiveProviders(coc_token="", mongo_uri="", routes={})
        with patch("cwl_web.providers.aiohttp.ClientSession", side_effect=lambda **kw: Session(rows, calls)):
            first = await provider.weights(["#P2Y", "#G2Y"])
            second = await provider.weights(["#Q2Y"])
        self.assertEqual(first["#P2Y"]["weight"], 176000)
        self.assertEqual(first["#P2Y"]["source_name"], "FWA Stats")
        self.assertEqual(first["#P2Y"]["source_modified_at"], "2026-05-15T11:37:17Z")
        self.assertEqual(first["#P2Y"]["source_checked_at"],
                         second["#Q2Y"]["source_checked_at"])
        self.assertEqual(second["#Q2Y"]["weight"], 168000)
        self.assertEqual(calls, ["https://www.fwastats.com/Weights.json"])

    async def test_malformed_feed_is_rejected_without_caching(self):
        duplicate = [
            {"tag": "#P2Y", "weight": 176000, "lastModified": "2026-05-15T11:37:17Z"},
            {"tag": "#P2Y", "weight": 177000, "lastModified": "2026-05-15T11:37:17Z"},
        ]
        calls = []
        provider = LiveProviders(coc_token="", mongo_uri="", routes={})
        with patch("cwl_web.providers.aiohttp.ClientSession", side_effect=lambda **kw: Session(duplicate, calls)):
            with self.assertRaises(ProviderUnavailable):
                await provider.weights(["#P2Y"])
            with self.assertRaises(ProviderUnavailable):
                await provider.weights(["#P2Y"])
        self.assertEqual(len(calls), 2)

    async def test_existing_roster_database_adds_modified_time_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE roster_entries(season_id INTEGER, tag TEXT, source_weight INTEGER)")
            store = Store(str(path))
            columns = {row["name"] for row in store.rows("PRAGMA table_info(roster_entries)")}
            self.assertIn("source_modified_at", columns)


if __name__ == "__main__":
    unittest.main()

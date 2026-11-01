"""Read-only profile preference fixture; no live Mongo or Discord transport."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["WU_TIMEZONE_FIXTURE"] = "1"
sys.path.insert(0, str(Path(__file__).parent))
import player_cards as fixture

owners = sorted(fixture.app["roster_owner_nicknames"]["names"])
rows = [
    {"_id": owners[2], "discord_id": owners[2], "zone_id": "gmt-8", "left_at": None},
    {"_id": owners[3], "discord_id": owners[3], "zone_id": "gmt+1", "left_at": None},
]


class ReadOnlyProfiles:
    def find(self, query):
        selected = [
            row
            for row in rows
            if row["_id"] in query["_id"]["$in"] and row["left_at"] is None
        ]

        class Cursor:
            async def to_list(self, length=None):
                return selected

        return Cursor()


fixture.app["server_management_mongo"] = SimpleNamespace(
    member_profiles=ReadOnlyProfiles()
)
if __name__ == "__main__":
    import asyncio

    asyncio.run(fixture.main())

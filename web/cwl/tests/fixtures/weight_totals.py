"""Isolated weight-total fixture built from the 125-account readability data."""

import asyncio
import runpy
from pathlib import Path

readability = Path(__file__).with_name("roster_readability.py")
fixture = runpy.run_path(str(readability), run_name="weight_totals_fixture")

# The readability fixture later moves two accounts and changes another weight.
# Seed this account so the final first-clan total is exactly 4,512.5k.
with fixture["app"]["store"].tx() as db:
    db.execute(
        "UPDATE roster_entries SET manual_weight=2707500 WHERE season_id=1 AND tag=?",
        (fixture["players"][0],),
    )

asyncio.run(fixture["main"]())

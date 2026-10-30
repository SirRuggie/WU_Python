"""Isolated 125-account roster fixture for inclusive weight ranges and quick picks.

Usage: WU_FIXTURE_BACKEND=<checkout> python weight_range.py <built-dist> 8982
The reused readability fixture guards outbound network and uses a temporary SQLite DB.
"""

import asyncio
import json
import runpy
from pathlib import Path

fixture = runpy.run_path(
    str(Path(__file__).with_name("roster_readability.py")),
    run_name="weight_range_fixture",
)

app = fixture["app"]
players = fixture["players"]
counts = fixture["counts"]
lazy_128_second = players[sum(counts[:-1]) + 1]
lazy_128_third = players[sum(counts[:-1]) + 2]
row_sql = (
    "SELECT s.pool, s.tag, r.assigned_clan_tag, r.kept, r.manual_weight, "
    "c.min_weight, c.max_weight "
    "FROM signups s LEFT JOIN roster_entries r "
    "ON r.season_id=s.season_id AND r.tag=s.tag "
    "LEFT JOIN lineup_rules c ON c.season_id=s.season_id "
    "AND c.tag=r.assigned_clan_tag WHERE s.season_id=1"
)

def summarize(rows):
    return {
        pool: {
            "signups": sum(row["pool"] == pool for row in rows),
            "assigned": sum(
                row["pool"] == pool and row["assigned_clan_tag"] is not None
                for row in rows
            ),
            "locked": sum(row["pool"] == pool and bool(row["kept"]) for row in rows),
        }
        for pool in ("main", "lazy")
    }

def changed_by_inclusive_max(db):
    from cwl_web.app import _roster_rows, _rule_rows

    rules = {row["tag"]: row for row in _rule_rows(db, 1)}
    return [
        account["tag"]
        for account in _roster_rows(db, 1)
        if account["assigned_clan_tag"] in rules
        and account["effective_weight"] is not None
        and rules[account["assigned_clan_tag"]]["max_weight"] is not None
        and account["effective_weight"] == rules[account["assigned_clan_tag"]]["max_weight"]
        and (
            rules[account["assigned_clan_tag"]]["min_weight"] is None
            or account["effective_weight"] >= rules[account["assigned_clan_tag"]]["min_weight"]
        )
    ]

with app["store"].tx() as db:
    baseline_counts = summarize(db.execute(row_sql).fetchall())
    # 179k is now the inclusive maximum for the showcased Lazy.128 clan.
    db.execute(
        "UPDATE lineup_rules SET min_weight=172000,max_weight=179000 "
        "WHERE season_id=1 AND tag='#V2Y'"
    )
    db.execute(
        "UPDATE roster_entries SET manual_weight=179000 "
        "WHERE season_id=1 AND tag=?",
        (lazy_128_second,),
    )
    db.execute(
        "UPDATE roster_entries SET manual_weight=179001 "
        "WHERE season_id=1 AND tag=?",
        (lazy_128_third,),
    )
    # A same-pool peer starts at that maximum to exercise the advisory note.
    db.execute(
        "UPDATE lineup_rules SET min_weight=179000,max_weight=180000 "
        "WHERE season_id=1 AND tag='#J2Y'"
    )
    rows = db.execute(row_sql).fetchall()
    after_counts = summarize(rows)
    changed = changed_by_inclusive_max(db)

assert len(changed) > 0
assert lazy_128_second in changed
assert baseline_counts == after_counts
async def serve():
    task = asyncio.create_task(fixture["main"]())
    for _ in range(100):
        await asyncio.sleep(0.1)
        if task.done():
            await task
        if fixture["state"]()["unreviewed_changes"] == 1:
            with app["store"].tx() as db:
                final_counts = summarize(db.execute(row_sql).fetchall())
                final_changed = changed_by_inclusive_max(db)
            assert lazy_128_second in final_changed
            state_counts = {
                row["pool"]: {
                    "signups": row["signups"],
                    "assigned": row["assigned"],
                    "locked": row["locks"],
                }
                for row in fixture["state"]()["season_counts"]
                if row["season_id"] == 1
            }
            assert final_counts == state_counts
            print(
                json.dumps(
                    {
                        "fixture": "weight-range-1",
                        "outside_to_inside": len(final_changed),
                        "changed_tags": final_changed,
                        "fixture_seed_before": baseline_counts,
                        "fixture_seed_after": after_counts,
                        "evaluation_before": final_counts,
                        "evaluation_after": state_counts,
                        "showcase_tag": lazy_128_second,
                    }
                ),
                flush=True,
            )
            break
    else:
        raise RuntimeError("Readability fixture did not finish local setup")
    await task

asyncio.run(serve())

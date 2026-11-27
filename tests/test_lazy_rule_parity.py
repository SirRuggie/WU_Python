"""The dashboard and native Lazy participation rule must stay in parity."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from utils.cwl_lazy_rule import (
    LAZY_ALT_ATTACKS,
    LAZY_ALT_STARS,
    LAZY_MIN_ATTACKS,
    RULE_SHORT,
    lazy_qualifies,
)

ROOT = Path(__file__).resolve().parents[1]


def test_typescript_rule_matches_python() -> None:
    source = (ROOT / "web/cwl/src/lazyRule.ts").read_text(encoding="utf-8")
    for name, value in (
        ("LAZY_MIN_ATTACKS", LAZY_MIN_ATTACKS),
        ("LAZY_ALT_ATTACKS", LAZY_ALT_ATTACKS),
        ("LAZY_ALT_STARS", LAZY_ALT_STARS),
    ):
        match = re.search(rf"export const {name} = (\d+);", source)
        assert match and int(match[1]) == value
    match = re.search(r'export const LAZY_RULE_SHORT = ("(?:[^"\\]|\\.)*");', source)
    assert match and json.loads(match[1]) == RULE_SHORT


@pytest.mark.parametrize(
    ("attacks", "stars", "expected"),
    [(0, 0, False), (2, 9, False), (3, 7, False), (3, 8, True), (3, 9, True), (4, 0, True), (7, 21, True)],
)
def test_lazy_rule_thresholds(attacks: int, stars: int, expected: bool) -> None:
    assert lazy_qualifies(attacks, stars) is expected


def test_only_rule_modules_own_literal_wording() -> None:
    allowed = {"utils/cwl_lazy_rule.py", "web/cwl/src/lazyRule.ts"}
    duplicates = []
    for directory in ("utils", "cwl_web", "extensions", "web/cwl/src"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx"} or ".test." in path.name:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative in allowed:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "8+ stars" in line or "8 or more stars" in line:
                    duplicates.append(f"{relative}:{number}")
    assert not duplicates, "Lazy rule wording belongs only in its two source modules: " + ", ".join(duplicates)


def test_saved_snapshot_keeps_its_historical_rule_text(tmp_path: Path) -> None:
    import sqlite3
    from contextlib import closing
    from utils.cwl_bonus_raffle_store import RaffleStore, SCHEMA

    historical = "4+ attacks OR 3+ attacks and 8+ stars"
    snapshot = {
        "pool": "lazy",
        "clan_name": "Fixture",
        "cycle": "2026-10",
        "qualification_rule": historical,
        "winners": [],
    }
    stored_json = json.dumps(snapshot)
    path = tmp_path / "historical-raffle.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(
            "CREATE TABLE seasons(id INTEGER PRIMARY KEY);"
            "INSERT INTO seasons VALUES(1);" + SCHEMA
        )
        cursor = db.execute(
            "INSERT INTO bonus_raffle_draws"
            "(season_id,cycle,pool,clan_tag,snapshot_json,created_by,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (1, "2026-10", "lazy", "#C2Y", stored_json, "fixture", "fixture"),
        )
        draw_id = cursor.lastrowid
        db.commit()
    before_bytes = path.read_bytes()
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        tables = ("bonus_raffle_draws", "bonus_raffle_deliveries", "bonus_raffle_pages")
        before = [db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables]
        saved = RaffleStore(db, 1).get(draw_id)
        assert saved["snapshot"]["qualification_rule"] == historical
        assert f"Rule: {historical}" in saved["messages"][0]
        assert RULE_SHORT not in saved["messages"][0]
        row = db.execute(
            "SELECT snapshot_json FROM bonus_raffle_draws WHERE id=?", (draw_id,)
        ).fetchone()
        assert row[0] == stored_json
        assert db.total_changes == 0
        assert before == [db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables]
    assert path.read_bytes() == before_bytes

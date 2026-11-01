"""Role progress never uses or poisons the dashboard's per-write publisher."""

import json, os, sqlite3, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from cwl_web.store import Store
from utils import cwl_pool_roles as roles
from test_cwl_pool_roles import ROLE, USER, OTHER, signup, save, claim


class Publisher:
    def __init__(self):
        self.poisoned = False
        self.main = 0
        self.progress = []
        self.fail = False

    def check(self):
        assert not self.poisoned

    def publish(self, db):
        self.main += 1

    def save_role_progress(self, image):
        if self.fail:
            raise RuntimeError("role backup unavailable")
        self.progress.append(image)
        return True

    def load_role_progress(self):
        return None


def seeded(tmp_path, count=1):
    publisher = Publisher()
    store = Store(str(tmp_path / "roles.sqlite"), durability=publisher)
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES(1,'Current')")
        db.execute("UPDATE member_season SET season_id=1 WHERE id=1")
        for index in range(count):
            db.execute(
                "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(1,?,?,'main',0,'Fixture',16)",
                (str(index), str(int(USER) + index)),
            )
    save(store)
    return store, publisher


def test_role_failure_does_not_poison_or_block_a_later_signup(tmp_path):
    store, publisher = seeded(tmp_path)
    job = claim(store)
    with store.role_tx() as db:
        roles.finish(db, job["id"], job["lease_token"], job["generation"])
    before = publisher.main
    publisher.fail = True
    result = store.flush_role_progress()
    assert result["published"] is False and not publisher.poisoned
    assert publisher.main == before and store.role_backup_error
    signup(store, "NEW", uid=OTHER)
    assert publisher.main == before + 1
    assert store.one("SELECT COUNT(*) AS n FROM signups")["n"] == 2


def test_ninety_one_jobs_have_zero_full_publishes_and_one_coalesced_copy_per_minute(
    tmp_path,
):
    store, publisher = seeded(tmp_path, 91)
    full_before = publisher.main
    start = datetime.now(timezone.utc)
    wall = time.perf_counter()
    published_at = []
    for index in range(91):
        now = start + timedelta(seconds=index * 3)
        with store.role_tx() as db:
            job = roles.claim(db, now=now)
        assert job is not None
        with store.role_tx() as db:
            assert roles.finish(db, job["id"], job["lease_token"], job["generation"])[
                "accepted"
            ]
        if store.flush_role_progress(now=now.timestamp()).get("published"):
            published_at.append(now.timestamp())
    seconds = time.perf_counter() - wall
    assert publisher.main == full_before
    assert len(publisher.progress) == 5
    assert all(b - a >= 60 for a, b in zip(published_at, published_at[1:]))
    assert store.flush_role_progress(now=(start + timedelta(seconds=300)).timestamp())[
        "published"
    ]
    assert len(publisher.progress) == 6
    decoded = roles.decode_progress(publisher.progress[-1])
    jobs = decoded["cwl_pool_role_jobs"]
    columns = jobs["columns"]
    assert len(jobs["rows"]) == 91 and all(
        dict(zip(columns, row))["state"] == "done" for row in jobs["rows"]
    )
    evidence = dict(
        jobs=91,
        local_role_transactions=182,
        role_initiated_full_dashboard_publishes=publisher.main - full_before,
        role_only_backups_during_270_virtual_seconds=5,
        final_backup_at_virtual_seconds=300,
        role_only_backups_total=6,
        local_protocol_seconds=round(seconds, 6),
        last_compressed_bytes=len(publisher.progress[-1]["payload"]),
        last_raw_bytes=publisher.progress[-1]["raw_bytes"],
        discord_delivery="not measured; protocol fixture only",
    )
    if os.environ.get("WU_POOL_ROLE_COST_EVIDENCE"):
        Path(os.environ["WU_POOL_ROLE_COST_EVIDENCE"]).write_text(
            json.dumps(evidence, indent=2)
        )


def test_role_transaction_cannot_bypass_core_signup_durability(tmp_path):
    store, publisher = seeded(tmp_path)
    before = publisher.main
    with pytest.raises(sqlite3.DatabaseError):
        with store.role_tx() as db:
            db.execute("DELETE FROM signups")
    with pytest.raises(sqlite3.DatabaseError):
        with store.role_tx() as db:
            db.execute("UPDATE cwl_pool_role_settings SET role_id=NULL")
    assert publisher.main == before
    signup(store, "NEW", uid=OTHER)
    assert publisher.main == before + 1


def test_role_image_cannot_restore_an_old_generation_or_change_core_data(tmp_path):
    store, publisher = seeded(tmp_path)
    job = claim(store)
    with store.role_tx() as db:
        roles.finish(db, job["id"], job["lease_token"], job["generation"])
    with store.role_tx(track=False) as db:
        image = roles.progress_image(db)
    signup(store, "NEW")  # Same owner, a newer durable intent generation.
    with store.role_tx() as db:
        before = dict(
            db.execute(
                "SELECT * FROM cwl_pool_role_jobs WHERE id=?", (job["id"],)
            ).fetchone()
        )
        roles.recover_progress(db, image)
        after = dict(
            db.execute(
                "SELECT * FROM cwl_pool_role_jobs WHERE id=?", (job["id"],)
            ).fetchone()
        )
        assert after["state"] == before["state"] == "pending"
        assert after["generation"] == before["generation"] > job["generation"]
        assert db.execute("SELECT COUNT(*) FROM signups").fetchone()[0] == 2


def test_role_image_checksum_rejected_without_overwriting_progress(tmp_path):
    store, publisher = seeded(tmp_path)
    job = claim(store)
    with store.role_tx() as db:
        image = roles.progress_image(db)
    image["payload"] = image["payload"] + b"bad"
    with pytest.raises(ValueError):
        with store.role_tx() as db:
            roles.recover_progress(db, image)
    assert (
        store.one("SELECT state FROM cwl_pool_role_jobs WHERE id=?", (job["id"],))[
            "state"
        ]
        == "leased"
    )

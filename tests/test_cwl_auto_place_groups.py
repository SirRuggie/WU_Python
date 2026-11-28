"""Member grouping plans over isolated, in-memory roster fixtures."""
import pytest
from cwl_web.app import _auto_plan
from cwl_web.store import Store


@pytest.fixture
def roster(tmp_path):
    store = Store(str(tmp_path / "groups.sqlite"))
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label,signup_open,status) VALUES (1,'Fixture',1,'draft')")
        for tag, pool in (("#A", "main"), ("#B", "main"), ("#L", "lazy")):
            db.execute("INSERT INTO clans(tag,name) VALUES (?,?)", (tag, tag))
            db.execute("INSERT INTO lineup(season_id,tag) VALUES (1,?)", (tag,))
            db.execute("INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES (1,?,?,15)", (tag, pool))
    return store


def account(db, tag, owner="one", pool="main", weight=100, clan=None, kept=0):
    db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (1,?,?,?,0,?,16)", (tag, owner, pool, tag))
    db.execute("INSERT INTO roster_entries(season_id,tag,manual_weight,assigned_clan_tag,kept) VALUES (1,?,?,?,?)", (tag, weight, clan, kept))


def test_groups_stay_together_and_are_deterministic(roster):
    with roster.tx() as db:
        for owner in ("one", "two"):
            for i in range(3):
                account(db, f"#{owner}{i}", owner, weight=100-i)
        before = list(db.execute("SELECT * FROM roster_entries"))
        first = _auto_plan(db, 1)
        assert first == _auto_plan(db, 1)
        assert first[1:] == ([], [])
        assert len(first[0]) == 6
        assert len({p["assigned_clan_tag"] for p in first[0][:3]}) == 1
        assert len({p["assigned_clan_tag"] for p in first[0][3:]}) == 1
        assert list(db.execute("SELECT * FROM roster_entries")) == before


@pytest.mark.parametrize("unlocked", [0, 2])
def test_locked_anchor_beats_lower_count_and_more_unlocked(roster, unlocked):
    with roster.tx() as db:
        account(db, "#locked", clan="#B", kept=1)
        for i in range(unlocked):
            account(db, f"#old{i}", clan="#A")
        account(db, "#new")
        account(db, "#held", kept=1)
        placements, skipped, split = _auto_plan(db, 1)
        assert placements == [{"tag": "#new", "assigned_clan_tag": "#B"}]
        assert skipped == [{"tag": "#held", "reason": "kept"}]
        assert split == ([{"tag": "#new", "reason": "locked_split"}] if unlocked else [])


def test_capacity_prefers_whole_group_before_partial_anchor(roster):
    with roster.tx() as db:
        for i in range(13):
            account(db, f"#old{i}", owner="one" if i == 0 else f"other{i}", clan="#A", kept=i == 0)
        for i in range(4):
            account(db, f"#new{i}")
        placements, _, split = _auto_plan(db, 1)
        assert {p["assigned_clan_tag"] for p in placements} == {"#B"}
        assert split == [{"tag": f"#new{i}", "reason": "full"} for i in range(4)]


def test_capacity_split_marks_every_new_account(roster):
    with roster.tx() as db:
        for clan in ("#A", "#B"):
            for i in range(13):
                account(db, f"{clan}old{i}", owner="one" if clan == "#A" and i == 0 else f"{clan}{i}", clan=clan, kept=i == 0)
        for i in range(4):
            account(db, f"#new{i}")
        placements, _, split = _auto_plan(db, 1)
        assert [p["assigned_clan_tag"] for p in placements] == ["#A", "#A", "#B", "#B"]
        assert split == [{"tag": f"#new{i}", "reason": "full"} for i in range(4)]


def test_weight_split_and_pool_filter(roster):
    with roster.tx() as db:
        account(db, "#anchor", clan="#B", kept=1)
        db.execute("UPDATE lineup_rules SET min_weight=90 WHERE tag='#B'")
        db.execute("UPDATE lineup_rules SET max_weight=90 WHERE tag='#A'")
        account(db, "#heavy", weight=100)
        account(db, "#light", weight=80)
        account(db, "#lazy", pool="lazy")
        placements, _, split = _auto_plan(db, 1, "main")
        assert placements == [{"tag": "#heavy", "assigned_clan_tag": "#B"}, {"tag": "#light", "assigned_clan_tag": "#A"}]
        assert split == [{"tag": "#heavy", "reason": "weight_rule"}, {"tag": "#light", "reason": "weight_rule"}]
        assert _auto_plan(db, 1, "lazy") == ([{"tag": "#lazy", "assigned_clan_tag": "#L"}], [], [])


def test_single_member_accounts_match_old_count_total_tag_order(roster):
    with roster.tx() as db:
        for i, weight in enumerate((150, 140, 120, 110, 100)):
            account(db, f"#new{i}", owner=str(i), weight=weight)
        assert _auto_plan(db, 1)[0] == [
            {"tag": f"#new{i}", "assigned_clan_tag": clan}
            for i, clan in enumerate(("#A", "#B", "#B", "#A", "#A"))]


def test_unavailable_missing_and_no_rule_stay_unplaced(roster):
    with roster.tx() as db:
        account(db, "#missing", weight=None)
        account(db, "#unavailable", weight=None)
        db.execute("UPDATE roster_entries SET source_status='unavailable' WHERE tag='#unavailable'")
        account(db, "#outside", weight=100)
        db.execute("UPDATE lineup_rules SET max_weight=90 WHERE pool='main'")
        assert _auto_plan(db, 1) == ([], [
            {"tag": "#outside", "reason": "no_eligible_rule"},
            {"tag": "#missing", "reason": "missing_weight"},
            {"tag": "#unavailable", "reason": "source_unavailable"},
        ], [])



def test_singletons_preserve_legacy_interleaved_skip_order(roster):
    with roster.tx() as db:
        for clan in ("#A", "#B"):
            for i in range(15):
                account(db, f"{clan}{i}", owner=f"{clan}{i}", clan=clan)
        account(db, "#full-heavy", owner="heavy", weight=150)
        account(db, "#held", owner="held", weight=120, kept=1)
        account(db, "#full-light", owner="light", weight=100)
        account(db, "#missing", owner="missing", weight=None)
        assert _auto_plan(db, 1) == ([], [
            {"tag": "#full-heavy", "reason": "full"},
            {"tag": "#held", "reason": "kept"},
            {"tag": "#full-light", "reason": "full"},
            {"tag": "#missing", "reason": "missing_weight"},
        ], [])

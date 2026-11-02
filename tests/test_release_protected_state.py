from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from tools.release_protected_state import compare_protected

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def fixture():
    old = {
        "active": [["1", "#P", 7]],
        "digest": "strict",
        "streaks": [["1", "#P", 3, None]],
        "member_profiles_count": 1,
        "member_profiles_digest": "a" * 64,
        "warrior_settings_digest": "b" * 64,
        "replacement": {"1": [["#P", 7, True, 2, False]]},
    }
    new = deepcopy(old)
    new["replacement"]["1"][0][4] = True
    p = {
        "guild_id": 1,
        "player_tag": "#P",
        "current_clan_tag": "#CLAN",
        "roster_seen_at": NOW - timedelta(minutes=2),
        "roster_observed_at": NOW - timedelta(minutes=2),
        "streak_count": 3,
    }
    q = {k: v for k, v in p.items() if k != "current_clan_tag"}
    q.update(
        departed_clan_tag="#CLAN",
        departed_last_seen_at=p["roster_seen_at"],
        roster_observed_at=NOW,
    )
    return old, new, {("1", "#P"): p}, {("1", "#P"): q}


def compare(items):
    return compare_protected(
        *items, started=NOW - timedelta(seconds=1), ended=NOW + timedelta(seconds=1)
    )


def test_only_exact_sync_departure_is_accepted():
    data = fixture()
    assert len(compare(data)) == 1
    assert compare((data[0], data[0], {}, {})) == []


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "active",
        "listed",
        "priority",
        "membership",
        "raw",
        "missing",
        "late",
        "reverse",
    ],
)
def test_every_other_change_fails_closed(change):
    old, new, p, q = fixture()
    if change == "digest":
        new["digest"] = "changed"
    elif change == "active":
        new["active"][0][2] += 1
    elif change == "listed":
        new["replacement"]["1"][0][2] = False
    elif change == "priority":
        new["replacement"]["1"][0][3] += 1
    elif change == "membership":
        new["replacement"]["1"].clear()
    elif change == "raw":
        q[("1", "#P")]["streak_count"] += 1
    elif change == "missing":
        p.clear()
    elif change == "late":
        q[("1", "#P")]["roster_observed_at"] = NOW + timedelta(minutes=1)
    elif change == "reverse":
        old, new = new, old
    with pytest.raises(ValueError):
        compare((old, new, p, q))


def test_existing_marked_departure_is_preserved_exactly():
    old, new, p, q = fixture()
    p[("1", "#P")].update(
        departed_clan_tag="#ORIGINAL",
        replacement_clan_tag="#ORIGINAL",
        departed_last_seen_at=NOW - timedelta(days=1),
    )
    q[("1", "#P")].update(
        departed_clan_tag="#ORIGINAL",
        replacement_clan_tag="#ORIGINAL",
        departed_last_seen_at=NOW - timedelta(days=1),
    )
    assert len(compare((old, new, p, q))) == 1


@pytest.mark.parametrize(
    "empty",
    [
        {},
        {"replacement": {}},
        {
            "active": [],
            "streaks": [],
            "replacement": {},
            "member_profiles_count": 0,
            "member_profiles_digest": "a" * 64,
            "warrior_settings_digest": "b" * 64,
        },
    ],
)
def test_equal_empty_or_incomplete_snapshots_fail_closed(empty):
    with pytest.raises(ValueError):
        compare((empty, empty, {}, {}))


@pytest.mark.parametrize("flag", [None, 0, "False"])
def test_only_an_explicit_false_departure_flag_can_transition(flag):
    old, new, p, q = fixture()
    old["replacement"]["1"][0][4] = flag
    with pytest.raises(ValueError):
        compare((old, new, p, q))


def write_capture(directory, name, metrics, profiles):
    import json
    from bson import json_util

    (directory / (name + ".json")).write_text(json.dumps(metrics))
    (directory / (name + "-profiles.json")).write_text(
        json_util.dumps(
            {
                "started": NOW - timedelta(seconds=1),
                "ended": NOW + timedelta(seconds=1),
                "profiles": list(profiles.values()),
            }
        )
    )


def test_coordinator_capture_gate_requires_full_matching_profile_evidence(tmp_path):
    from tools.release_protected_state import compare_capture_files

    before, after, p, q = fixture()
    write_capture(tmp_path, "before", before, p)
    write_capture(tmp_path, "after", after, q)
    assert len(compare_capture_files(tmp_path, "before", "after")) == 1
    report = (tmp_path / "after-comparison.json").read_text()
    assert "#P" not in report and "departure_count" in report
    write_capture(tmp_path, "after", after, {})
    with pytest.raises(ValueError, match="profile evidence"):
        compare_capture_files(tmp_path, "before", "after")


def test_coordinator_gate_rejects_equal_empty_metrics_before_any_switch(tmp_path):
    from tools.release_protected_state import compare_capture_files

    _, _, p, _ = fixture()
    write_capture(tmp_path, "before", {}, p)
    write_capture(tmp_path, "after", {}, p)
    with pytest.raises((ValueError, KeyError)):
        compare_capture_files(tmp_path, "before", "after")
    assert not (tmp_path / "after-comparison.json").exists()


@pytest.mark.parametrize("replacement", [{}, {"1": []}])
def test_thin_nonempty_streak_snapshot_cannot_bypass_coordinator(tmp_path, replacement):
    from tools.release_protected_state import compare_capture_files
    from bson import json_util
    import json

    old, _, p, _ = fixture()
    old["active"] = []
    old["replacement"] = replacement
    for name in ("before", "after"):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(old))
        path.with_name(path.stem + "-profiles.json").write_text(
            json_util.dumps(
                {
                    "started": NOW - timedelta(seconds=1),
                    "ended": NOW,
                    "profiles": list(p.values()),
                }
            )
        )
    with pytest.raises(ValueError, match="empty or incomplete"):
        compare_capture_files(tmp_path, "before", "after")


def test_public_coordinator_gate_entry_rejects_thin_capture_without_success(
    tmp_path, capsys
):
    from tools.release_protected_state import main
    from bson import json_util
    import json

    old, _, p, _ = fixture()
    old.update(active=[], replacement={})
    for name in ("before", "after"):
        (tmp_path / (name + ".json")).write_text(json.dumps(old))
        (tmp_path / (name + "-profiles.json")).write_text(
            json_util.dumps(
                {"started": NOW, "ended": NOW, "profiles": list(p.values())}
            )
        )
    with pytest.raises(ValueError, match="empty or incomplete"):
        main([str(tmp_path), "before", "after"])
    assert "protected_gate_passed" not in capsys.readouterr().out


def test_cli_rejects_same_capture_for_both_sides(tmp_path, capsys):
    from tools.release_protected_state import main

    before, _, p, _ = fixture()
    write_capture(tmp_path, "before", before, p)
    with pytest.raises(ValueError, match="independent"):
        main([str(tmp_path), "before", "before"])
    assert "protected_gate_passed" not in capsys.readouterr().out


def test_cli_rejects_equal_replacement_junk(tmp_path, capsys):
    from tools.release_protected_state import main

    before, _, p, _ = fixture()
    before["replacement"] = {"1": "junk"}
    write_capture(tmp_path, "before", before, p)
    write_capture(tmp_path, "after", before, p)
    with pytest.raises(ValueError, match="malformed"):
        main([str(tmp_path), "before", "after"])
    assert "protected_gate_passed" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "capture,field",
    [
        ("before", "started"),
        ("before", "ended"),
        ("after", "started"),
        ("after", "ended"),
    ],
)
def test_cli_rejects_unparseable_capture_times_without_departures(
    tmp_path, capsys, capture, field
):
    from tools.release_protected_state import main
    from bson import json_util

    before, _, p, _ = fixture()
    write_capture(tmp_path, "before", before, p)
    write_capture(tmp_path, "after", before, p)
    proof = tmp_path / (capture + "-profiles.json")
    data = json_util.loads(proof.read_text())
    data[field] = "not-a-date"
    proof.write_text(json_util.dumps(data))
    with pytest.raises(ValueError, match="timestamp"):
        main([str(tmp_path), "before", "after"])
    assert "protected_gate_passed" not in capsys.readouterr().out


@pytest.mark.parametrize("field,empty", [("active", []), ("replacement", {})])
def test_cli_rejects_independently_empty_active_or_replacement(tmp_path, field, empty):
    from tools.release_protected_state import main

    before, _, p, _ = fixture()
    before[field] = empty
    write_capture(tmp_path, "before", before, p)
    write_capture(tmp_path, "after", before, p)
    with pytest.raises(ValueError, match="empty or incomplete"):
        main([str(tmp_path), "before", "after"])

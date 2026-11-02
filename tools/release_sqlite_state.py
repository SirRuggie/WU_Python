"""Fail-closed proof of ordinary staff publications/marks during a release.

Audit rows are the existing application's trusted write receipts, not signatures.
The coordinator supplies independent read-only captures and trusted staff scopes;
no actor or scope is inferred from a newly added audit row. No database mutation.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from utils.dashboard_access import OWNER_IDS, CWL_PERMISSIONS, expand_legacy

PUBLIC_META = (
    "version",
    "revision",
    "published_at",
    "published_by",
    "joining_instructions",
    "assigned_count",
    "unassigned_count",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    _require(isinstance(value, datetime), "Typed or ISO timestamp required")
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _indexed(rows, key):
    _require(isinstance(rows, list), "Missing table capture")
    result = {key(row): row for row in rows}
    _require(len(result) == len(rows), "Duplicate row key")
    return result


def _additions(before, after, key):
    old, new = _indexed(before, key), _indexed(after, key)
    _require(
        all(k in new and new[k] == row for k, row in old.items()),
        "Existing rows removed or changed",
    )
    return [row for k, row in new.items() if k not in old]


def capture_proof(db):
    """Read proof in the coordinator's same read-only SQLite transaction."""
    return {
        name: [dict(row) for row in db.execute("SELECT * FROM " + name)]
        for name in (
            "roster_audit",
            "publication_accounts",
            "roster_meta",
            "seasons",
            "grants",
        )
    }


def trusted_staff_scopes(proof):
    """Owner policy/direct grants only; role-only staff need separate proof.

    A newly observed actor ID is never treated as authority. Direct grants must
    remain identical across captures. Unknown/role-only actors fail closed here.
    """
    result = {actor: set(CWL_PERMISSIONS) for actor in OWNER_IDS}
    for row in proof["grants"]:
        values = json.loads(row["permissions"])
        _require(isinstance(values, list), "Malformed staff grant proof")
        result.setdefault(row["user_id"], set()).update(expand_legacy(values))
    return result


def compare_sqlite(
    before,
    after,
    proof_before,
    proof_after,
    *,
    staff_scopes,
    release_actors,
    started,
    ended
):
    """Report exact audited additions; reject every unproven protected change.

    ``staff_scopes`` is fixed before switching code, from owner policy or a
    separately authenticated permission capture. Never pass actor-supplied scopes.
    Proof includes all roster_audit, publication_accounts, roster_meta and seasons
    rows. Other protected tables, including role work, remain byte-for-byte equal.
    The release uses no production application session; any explicitly designated
    release actor is always denied, even if also present in staff_scopes.
    """
    start, end = _time(started), _time(ended)
    _require(start <= end, "Reversed observation window")
    _require(bool(before) and set(before) == set(after), "Incomplete protected capture")
    required = {
        "roster_publications",
        "roster_player_marks",
        "roster_player_mark_audit",
    }
    _require(required <= before.keys(), "Missing protected tables")
    evidence_tables = {
        "roster_audit",
        "publication_accounts",
        "roster_meta",
        "seasons",
        "grants",
    }
    _require(
        evidence_tables <= proof_before.keys()
        and evidence_tables <= proof_after.keys(),
        "Missing contemporaneous audit evidence",
    )
    _require(bool(proof_before["seasons"]), "Empty season proof")
    _require(proof_before["seasons"] == proof_after["seasons"], "Season state changed")
    _require(proof_before["grants"] == proof_after["grants"], "Staff grants changed")
    trusted = trusted_staff_scopes(proof_before)
    denied = set(map(str, release_actors))

    def authorized(actor, permission, stamp):
        _require(
            isinstance(actor, str)
            and actor not in denied
            and permission in staff_scopes.get(actor, ())
            and permission in trusted.get(actor, ()),
            "Untrusted or release actor",
        )
        # SQLite CURRENT_TIMESTAMP has whole-second precision. Permit only that
        # same first second, not a general grace window for stale receipts.
        _require(
            start.replace(microsecond=0) <= _time(stamp) <= end,
            "Audit outside observation window",
        )

    left, right = deepcopy(before), deepcopy(after)
    pubs_old = left.pop("roster_publications")
    pubs_new = right.pop("roster_publications")
    marks_old = left.pop("roster_player_marks")
    marks_new = right.pop("roster_player_marks")
    audits_old = left.pop("roster_player_mark_audit")
    audits_new = right.pop("roster_player_mark_audit")
    _require(left == right, "Unexplained protected table change")
    new_pubs = _additions(pubs_old, pubs_new, lambda r: r["id"])
    new_audits = _additions(
        proof_before["roster_audit"], proof_after["roster_audit"], lambda r: r["id"]
    )
    mark_audits = _additions(audits_old, audits_new, lambda r: r["id"])
    for old, additions in (
        (pubs_old, new_pubs),
        (proof_before["roster_audit"], new_audits),
        (audits_old, mark_audits),
    ):
        _require(
            all(
                type(r["id"]) is int
                and r["id"] > max((x["id"] for x in old), default=0)
                for r in additions
            ),
            "Receipt is not append-only",
        )
    _require(len(new_audits) == len(new_pubs), "Unmatched publication audit")
    reports = []
    revision_increments = Counter()
    previous = list(pubs_old)
    for pub in sorted(new_pubs, key=lambda r: r["id"]):
        actor, sid = pub["published_by"], pub["season_id"]
        authorized(actor, "cwl_publish", pub["published_at"])
        prior = [row for row in previous if row["season_id"] == sid]
        _require(
            pub["version"] == max((r["version"] for r in prior), default=0) + 1,
            "Publication version is not the next version",
        )
        _require(pub.get("withdrawn_at") is None, "New publication already withdrawn")
        meta = {key: pub[key] for key in PUBLIC_META}
        matches = [
            a
            for a in new_audits
            if a["action"] == "roster_publish"
            and a["season_id"] == sid
            and a.get("tag") is None
            and a["actor_id"] == actor
            and json.loads(a["after_json"]) == meta
        ]
        _require(len(matches) == 1, "Publication lacks one matching staff receipt")
        audit = matches[0]
        authorized(actor, "cwl_publish", audit["created_at"])
        visible = [r for r in prior if r.get("withdrawn_at") is None]
        latest = max(visible, key=lambda r: r["version"]) if visible else None
        expected_prior = {key: latest[key] for key in PUBLIC_META} if latest else None
        _require(
            (
                json.loads(audit["before_json"])
                if audit["before_json"] is not None
                else None
            )
            == expected_prior,
            "Publication receipt prior state differs",
        )
        new_audits.remove(audit)
        previous.append(pub)
        revision_increments[sid] += 1
        reports.append(
            {
                "kind": "staff_publication",
                "publication_id": pub["id"],
                "audit_id": audit["id"],
                "actor_id": actor,
            }
        )
    _require(not new_audits, "Unrelated roster audit additions")

    extra_accounts = _additions(
        proof_before["publication_accounts"],
        proof_after["publication_accounts"],
        lambda r: (r["publication_id"], r["tag"]),
    )
    new_ids = {r["id"] for r in new_pubs}
    _require(
        all(r["publication_id"] in new_ids for r in extra_accounts),
        "Snapshot added to an old or unknown publication",
    )
    for pub in new_pubs:
        accounts = [r for r in extra_accounts if r["publication_id"] == pub["id"]]
        _require(
            bool(accounts)
            and len(accounts) == pub["assigned_count"] + pub["unassigned_count"]
            and sum(r["assigned_clan_tag"] is not None for r in accounts)
            == pub["assigned_count"],
            "Publication snapshot counts differ",
        )

    old_marks = _indexed(marks_old, lambda r: r["tag"])
    final_marks = _indexed(marks_new, lambda r: r["tag"])
    _require(set(old_marks) <= set(final_marks), "Mark row removed")
    expected_marks = deepcopy(old_marks)
    for audit in sorted(mark_audits, key=lambda r: r["id"]):
        actor, tag = audit["actor_id"], audit["tag"]
        authorized(actor, "cwl_roster", audit["created_at"])
        old = expected_marks.get(tag, {"tag": tag, "roster_filler": 0, "revision": 0})
        _require(
            type(audit["revision"]) is int
            and audit["revision"] == old["revision"] + 1
            and type(audit["before_value"]) is int
            and type(audit["after_value"]) is int
            and audit["before_value"] in (0, 1)
            and audit["after_value"] in (0, 1)
            and audit["before_value"] == old["roster_filler"]
            and audit["before_value"] != audit["after_value"],
            "Broken mark receipt chain",
        )
        expected_marks[tag] = {
            "tag": tag,
            "roster_filler": audit["after_value"],
            "revision": audit["revision"],
            "updated_by": actor,
            "updated_at": audit["created_at"],
        }
        reports.append(
            {"kind": "staff_mark", "audit_id": audit["id"], "actor_id": actor}
        )
    _require(expected_marks == final_marks, "Mark changed without exact audit proof")
    # Every global mark increments every season; each publication increments its
    # own season once. No broad exclusion of roster revision counters.
    old_meta = _indexed(proof_before["roster_meta"], lambda r: r["season_id"])
    expected_meta = deepcopy(old_meta)
    if mark_audits:
        for season in proof_before["seasons"]:
            expected_meta.setdefault(
                season["id"], {"season_id": season["id"], "revision": 0}
            )
    for sid, row in expected_meta.items():
        row["revision"] += len(mark_audits) + revision_increments.pop(sid, 0)
    for sid, count in revision_increments.items():
        expected_meta[sid] = {"season_id": sid, "revision": count}
    _require(
        expected_meta == _indexed(proof_after["roster_meta"], lambda r: r["season_id"]),
        "Roster revision changed without exact audit proof",
    )
    return reports


def capture(db, protected_reader):
    """Capture tables and receipts in the caller's existing read transaction."""
    started = datetime.now(timezone.utc).isoformat()
    tables = protected_reader(db)
    proof = capture_proof(db)
    return {
        "started": started,
        "ended": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
        "proof": proof,
    }


def compare_captures(before, after, *, release_actors):
    """Coordinator seam: no scopes supplied by a new receipt or request body."""
    _require(before is not after, "Independent SQLite captures required")
    start, before_end = _time(before["started"]), _time(before["ended"])
    after_start, end = _time(after["started"]), _time(after["ended"])
    _require(start <= before_end <= after_start <= end, "Invalid SQLite capture order")
    return compare_sqlite(
        before["tables"],
        after["tables"],
        before["proof"],
        after["proof"],
        staff_scopes=trusted_staff_scopes(before["proof"]),
        release_actors=release_actors,
        started=start,
        ended=end,
    )

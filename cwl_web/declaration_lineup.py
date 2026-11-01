"""Read-only pool lineup comparison, independent of weight/source revisions."""

from utils.declaration_ping_store import PingConflict


def signature(rows, pool, clan_pools):
    return sorted(
        (r["tag"], str(r.get("user_id") or ""), r["assigned_clan_tag"])
        for r in rows
        if r.get("assigned_clan_tag")
        and (
            clan_pools.get(r["assigned_clan_tag"])
            or r.get("hosting_pool")
            or r.get("pool")
        )
        == pool
    )


def current(request, pool):
    from .app import _sid, _latest_publication, _rule_rows

    sid = _sid(request)
    with request.app["store"].tx() as db:
        latest = _latest_publication(db, sid)
        pools = {r["tag"]: r["pool"] for r in _rule_rows(db, sid)}
        draft = [
            dict(r)
            for r in db.execute(
                "SELECT s.tag,s.user_id,s.player_name,s.pool,r.assigned_clan_tag FROM signups s "
                "LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag WHERE s.season_id=?",
                (sid,),
            )
        ]
        published = (
            [
                dict(r)
                for r in db.execute(
                    "SELECT tag,user_id,player_name,pool,assigned_clan_tag FROM publication_accounts WHERE publication_id=?",
                    (latest["id"],),
                )
            ]
            if latest
            else []
        )
    old, new = signature(published, pool, pools), signature(draft, pool, pools)
    left, right = {r[0]: r for r in old}, {r[0]: r for r in new}
    names = {r["tag"]: r.get("player_name") or r["tag"] for r in [*published, *draft]}
    changes = [
        dict(
            tag=t,
            name=names[t],
            published_clan=left.get(t, (None, None, None))[2],
            draft_clan=right.get(t, (None, None, None))[2],
        )
        for t in sorted(left.keys() | right.keys())
        if left.get(t) != right.get(t)
    ]
    return dict(
        available=latest is not None, signature=old, changes=changes, pools=pools
    )


def require_reviewed(request, pool, rows):
    status = current(request, pool)
    if not status["available"]:
        raise PingConflict("Publish the roster before reviewing pings")
    if status["changes"]:
        names = ", ".join(f"{r['name']} ({r['tag']})" for r in status["changes"])
        raise PingConflict("Publish the changed " + pool + " lineup: " + names)
    if signature(rows, pool, status["pools"]) != status["signature"]:
        raise PingConflict("This pool changed while checking locations. Review again.")
    return status

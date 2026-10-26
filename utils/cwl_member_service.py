"""Member CWL reads and writes against the dashboard's single durable Store.

The caller supplies the Store and read-only provider. This module has no HTTP,
Discord, or dashboard dependency. In production the web process owns the Store
and its Mongo durability lease; a bot must call that process, not open the file.
"""

import asyncio
import json
import re

from utils.cwl_signup_policy import main_signup_error


TAG = re.compile(r"#[0289PYLQGRJCUV]{3,15}\Z")


class MemberError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def player_tag(value):
    if not isinstance(value, str):
        raise MemberError(400, "Invalid player tag")
    value = value.strip().upper().replace("O", "0")
    if value and not value.startswith("#"):
        value = "#" + value
    if not TAG.fullmatch(value):
        raise MemberError(400, "Invalid player tag")
    return value


def _season(db, season_id, *, selected_only=True):
    selected = db.execute("SELECT season_id FROM member_season WHERE id=1").fetchone()
    if selected_only and (selected is None or selected["season_id"] != season_id):
        raise MemberError(403, "This season is no longer shown to members. Reopen CWL.")
    row = db.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    if row is None:
        raise MemberError(404, "Season not found")
    return row


def _audit(db, season_id, value, user_id, action, before, after):
    db.execute(
        "INSERT INTO roster_audit(season_id,tag,actor_id,action,before_json,after_json) "
        "VALUES (?,?,?,?,?,?)",
        (season_id, value, user_id, action,
         json.dumps(before, sort_keys=True) if before is not None else None,
         json.dumps(after, sort_keys=True) if after is not None else None),
    )


def _bump(db, season_id):
    db.execute(
        "INSERT INTO roster_meta(season_id,revision) VALUES (?,1) "
        "ON CONFLICT(season_id) DO UPDATE SET revision=revision+1", (season_id,)
    )


def _check_revision(db, season_id, expected_revision):
    if expected_revision is None:
        return
    row = db.execute("SELECT revision FROM roster_meta WHERE season_id=?", (season_id,)).fetchone()
    if type(expected_revision) is not int or expected_revision != (row["revision"] if row else 0):
        raise MemberError(409, "Signups changed; reopen CWL before saving")


def _placement(db, season_id, value):
    return db.execute(
        "SELECT r.assigned_clan_tag,c.name AS assigned_clan_name "
        "FROM roster_entries r LEFT JOIN clans c ON c.tag=r.assigned_clan_tag "
        "WHERE r.season_id=? AND r.tag=?", (season_id, value)
    ).fetchone()


async def accounts_for_member(provider, user_id, *, verified_only=False):
    """Fetch all current account facts; any partial outage fails the whole write.

    The directory is optional for Lazy. Main rejects a known FWA account and
    fails closed when a current clan's category cannot be checked.
    """
    links = await provider.linked_tags(str(user_id))
    links = {player_tag(value): bool(verified) for value, verified in links.items()}
    if verified_only:
        links = {value: verified for value, verified in links.items() if verified}
    limit = asyncio.Semaphore(5)

    async def fetch(value):
        async with limit:
            result = await provider.player(value)
            if player_tag(result.get("tag")) != value:
                raise ValueError("Provider returned a different player tag")
            return result

    accounts = await asyncio.gather(*(fetch(value) for value in links))
    if not accounts:
        return []
    try:
        family = await provider.family_clans()
        if family.get("status", "ok") != "ok":
            raise ValueError("Incomplete family directory")
        clans = family["clans"]
        if not isinstance(clans, list) or not clans:
            raise ValueError("Invalid family directory")
        directory = {}
        for item in clans:
            if not isinstance(item, dict) or item.get("type") not in (
                "FWA", "Tactical", "Flexible Fun", "Competitive"
            ):
                raise ValueError("Invalid family directory category")
            value = player_tag(item.get("tag"))
            if value in directory:
                raise ValueError("Duplicate family clan")
            directory[value] = item
    except Exception:
        # Treat a partial or malformed directory as unavailable. Main fails
        # closed for accounts currently in a clan; Lazy can still proceed.
        directory = None
    for account in accounts:
        account["verified"] = links[account["tag"]]
        clan_tag = account.get("current_clan_tag")
        account["family_clan_status"] = (
            "unknown" if directory is None else
            "approved" if clan_tag in directory else "outside"
        )
        account["current_clan_type"] = (directory or {}).get(clan_tag, {}).get("type")
        account["lazy_eligible"] = True
        account["lazy_ineligible_reason"] = None
    return accounts


def member_view(store, user_id):
    """Only current signups and matching published assignments are visible."""
    with store.tx() as db:
        selected = db.execute("SELECT season_id FROM member_season WHERE id=1").fetchone()
        season_id = selected["season_id"] if selected else None
        if season_id is None:
            return {"season": None, "revision": None, "signups": [], "published": None, "assignments": []}
        season = _season(db, season_id)
        revision_row = db.execute("SELECT revision FROM roster_meta WHERE season_id=?", (season_id,)).fetchone()
        signups = [dict(row) for row in db.execute(
            "SELECT * FROM signups WHERE season_id=? AND user_id=? ORDER BY tag",
            (season_id, str(user_id)),
        )]
        published, assignments = _published_assignments(db, season_id, user_id)
        return {
            "season": {"id": season["id"], "label": season["label"],
                       "signup_open": bool(season["signup_open"]), "status": season["status"]},
            "revision": revision_row["revision"] if revision_row else 0,
            "signups": signups,
            "published": published,
            "assignments": assignments,
        }


def _published_assignments(db, season_id, user_id, *, include_pending=False):
    latest = db.execute(
        "SELECT id,version,published_at,joining_instructions FROM roster_publications "
        "WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1",
        (season_id,),
    ).fetchone()
    # The dashboard retains pending rows beside published placements. Discord
    # shows only accounts actually included in the published snapshot. Both
    # paths require matching current ownership and pool for any placement.
    join = "LEFT JOIN" if include_pending else "JOIN"
    assignments = [dict(row) for row in db.execute(
        "SELECT s.tag,s.player_name,s.town_hall,s.pool,p.assigned_clan_tag,p.assigned_clan_name "
        f"FROM signups s {join} publication_accounts p ON p.publication_id=? "
        "AND p.tag=s.tag AND p.user_id=s.user_id AND p.pool=s.pool "
        "WHERE s.season_id=? AND s.user_id=? ORDER BY s.tag",
        (latest["id"] if latest else None, season_id, str(user_id)),
    )]
    published = ({key: latest[key] for key in
                  ("version", "published_at", "joining_instructions")} if latest else None)
    return published, assignments


def assignment_view(store, user_id, season_id, *, selected_only=True):
    """Dashboard and Discord use one publication visibility rule."""
    with store.tx() as db:
        _season(db, season_id, selected_only=selected_only)
        published, assignments = _published_assignments(db, season_id, user_id, include_pending=True)
        return {"published": published, "visibility": "current",
                "draft_changed": False, "accounts": assignments}


async def member_snapshot(store, provider, user_id, *, include_accounts=True):
    initial = member_view(store, user_id)
    if not include_accounts:
        # Saved records do not depend on live game/provider availability.
        # A skipped lookup is distinct from an empty account list.
        return {**initial, "accounts": [], "accounts_status": "not_loaded"}
    if initial["season"] is None:
        return {**initial, "accounts": [], "accounts_status": "ok"}
    try:
        # Match dashboard eligibility: provider verification is metadata, not a
        # requirement for an account already linked to this Discord identity.
        accounts = await accounts_for_member(provider, user_id, verified_only=False)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Saved signups and published assignments stay visible during an outage.
        accounts, account_status = [], "unavailable"
    else:
        account_status = "ok"
    # A season or publication may have changed while providers were loading.
    return {**member_view(store, user_id), "accounts": accounts,
            "accounts_status": account_status}


def _selections(pool, selections):
    if pool not in ("main", "lazy") or not isinstance(selections, list) or len(selections) > 100:
        raise MemberError(400, "Invalid signup")
    requested = {}
    for item in selections:
        if not isinstance(item, dict) or type(item.get("prefer_crystal_1_or_lower")) is not bool:
            raise MemberError(400, "Invalid account signup")
        value = player_tag(item.get("tag"))
        if value in requested:
            raise MemberError(400, "Duplicate account in submission")
        source = item.get("move_from_pool")
        if "move_from_pool" in item and source not in ("main", "lazy"):
            raise MemberError(400, "Invalid source pool")
        requested[value] = (item["prefer_crystal_1_or_lower"], source)
    return requested


async def submit(store, provider, season_id, user_id, pool, selections, *, verified_only=True,
                 expected_revision=None, selected_only=True):
    requested = _selections(pool, selections)
    # Provider work precedes BEGIN IMMEDIATE. A failure never changes saved data.
    try:
        available = {a["tag"]: a for a in await accounts_for_member(
            provider, user_id, verified_only=verified_only
        )}
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise MemberError(503, "Linked accounts are temporarily unavailable. Nothing was saved.") from exc
    if not set(requested) <= set(available):
        raise MemberError(403, "Account is not linked to your Discord identity" if not verified_only
                          else "Account is not verified and linked to your Discord identity")
    if pool == "main":
        for value in requested:
            problem = main_signup_error(available[value])
            if problem:
                raise MemberError(*problem)
    with store.tx() as db:
        season = _season(db, season_id, selected_only=selected_only)
        _check_revision(db, season_id, expected_revision)
        if not season["signup_open"] or season["status"] != "draft":
            raise MemberError(423, "Signups are closed")
        moved = 0
        # Validate the full batch under one write lock before changing a row.
        for value, (_, source) in requested.items():
            old = db.execute(
                "SELECT user_id,pool FROM signups WHERE season_id=? AND tag=?",
                (season_id, value),
            ).fetchone()
            if old is None:
                if source is not None:
                    raise MemberError(409, "Pool transfer is stale; refresh signups")
            elif old["user_id"] != str(user_id):
                raise MemberError(409, "Account already registered by another member")
            elif old["pool"] == pool:
                if source is not None:
                    raise MemberError(409, "Pool transfer is stale; refresh signups")
            elif source != old["pool"]:
                raise MemberError(409, "Confirm the account's current pool before moving it")
            else:
                moved += 1
        for value, (preference, _) in requested.items():
            account = available[value]
            old = db.execute("SELECT * FROM signups WHERE season_id=? AND tag=?", (season_id, value)).fetchone()
            db.execute(
                "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,"
                "player_name,town_hall,signup_clan_tag,signup_clan_name) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(season_id,tag) DO UPDATE SET pool=excluded.pool,"
                "prefer_crystal_1_or_lower=excluded.prefer_crystal_1_or_lower,"
                "player_name=excluded.player_name,town_hall=excluded.town_hall,"
                "updated_at=CURRENT_TIMESTAMP",
                (season_id, value, str(user_id), pool, int(preference), account["name"],
                 account["town_hall"], account.get("current_clan_tag"),
                 account.get("current_clan_name")),
            )
            if account.get("current_clan_type"):
                db.execute(
                    "UPDATE signups SET signup_clan_type=CASE WHEN signup_clan_type='FWA' "
                    "OR ?='FWA' THEN 'FWA' ELSE COALESCE(signup_clan_type,?) END "
                    "WHERE season_id=? AND tag=?",
                    (account["current_clan_type"], account["current_clan_type"], season_id, value),
                )
            after = db.execute("SELECT * FROM signups WHERE season_id=? AND tag=?", (season_id, value)).fetchone()
            before = dict(old) if old else None
            changed_pool = old is not None and old["pool"] != pool
            if changed_pool:
                placement = _placement(db, season_id, value)
                before["assigned_clan_tag"] = placement["assigned_clan_tag"] if placement else None
                before["assigned_clan_name"] = placement["assigned_clan_name"] if placement else None
                db.execute(
                    "UPDATE roster_entries SET assigned_clan_tag=NULL,kept=0 WHERE season_id=? AND tag=?",
                    (season_id, value),
                )
            _audit(db, season_id, value, str(user_id),
                   "member_pool_change" if changed_pool else "member_signup", before, dict(after))
        if requested:
            _bump(db, season_id)
    return {"ok": True, "count": len(requested), "moved": moved}


def withdraw(store, season_id, user_id, value, *, expected_pool=None, expected_revision=None,
             selected_only=True):
    value = player_tag(value)
    if expected_pool is not None and expected_pool not in ("main", "lazy"):
        raise MemberError(400, "Invalid source pool")
    with store.tx() as db:
        season = _season(db, season_id, selected_only=selected_only)
        _check_revision(db, season_id, expected_revision)
        if not season["signup_open"] or season["status"] != "draft":
            raise MemberError(423, "Signups are closed")
        old = db.execute(
            "SELECT * FROM signups WHERE season_id=? AND tag=? AND user_id=?",
            (season_id, value, str(user_id)),
        ).fetchone()
        if expected_pool is not None and (old is None or old["pool"] != expected_pool):
            raise MemberError(409, "Signup changed; refresh before withdrawing")
        if old:
            placement = _placement(db, season_id, value)
            before = {**dict(old),
                      "assigned_clan_tag": placement["assigned_clan_tag"] if placement else None,
                      "assigned_clan_name": placement["assigned_clan_name"] if placement else None}
            db.execute("DELETE FROM signups WHERE season_id=? AND tag=? AND user_id=?",
                       (season_id, value, str(user_id)))
            _audit(db, season_id, value, str(user_id), "member_withdrawal", before, None)
            _bump(db, season_id)
    return {"ok": True, "removed": bool(old)}

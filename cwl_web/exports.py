"""Read-only, staff-only CSV downloads from a single database snapshot."""
import csv
import io
import json
from datetime import datetime, timezone
from aiohttp import web
from .bonuses import _view as bonus_view


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value)
    # Spreadsheet applications can execute formulas even in quoted CSV cells.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


async def export_csv(request):
    from .app import _require, _season, _sid, _store, _roster_rows, _latest_publication, _revision
    _require(request, "editor")
    sid = _sid(request)
    kind = request.query.get("kind", "accounts")
    basis = request.query.get("basis", "current")
    if kind not in {"accounts", "participation", "bonus-history"} or basis not in {"current", "published"}:
        raise web.HTTPBadRequest(text="Choose a supported export type and roster version")
    with _store(request).tx() as db:
        season = _season(db, sid)
        latest = _latest_publication(db, sid)
        if basis == "published" and not latest and kind == "accounts":
            raise web.HTTPConflict(text="Publish a roster before exporting its official version")
        bonus = bonus_view(db, sid)
        stamp = datetime.now(timezone.utc).isoformat()
        meta = {"season_id": sid, "season": season["label"], "season_status": season["status"],
                "exported_at_utc": stamp, "cwl_month": bonus["cycle"]}
        rows = []
        if kind == "bonus-history":
            columns = list(meta) + ["id", "tag", "player_name", "pool", "clan_tag", "clan_name", "cycle", "publication_version", "attacks", "stars", "reason", "warnings", "confirmed_by", "confirmed_at", "voided_by", "voided_at", "void_reason", "record_type"]
            rows = [{**meta, **row} for row in bonus["history"]]
        elif kind == "participation":
            columns = list(meta) + ["tag", "player_name", "town_hall", "pool", "assigned_clan_tag", "assigned_clan_name", "attacks", "stars", "notes", "attacks_origin", "stars_origin", "source_attacks", "source_stars", "source_status", "source_complete", "source_checked_at", "source_warning", "attacks_override", "stars_override", "recorded_publication_version", "in_latest_publication", "roster_changed", "updated_by", "updated_at"]
            rows = [{**meta, **row} for row in bonus["accounts"]]
        else:
            base_rows = ([dict(row) for row in db.execute("SELECT * FROM publication_accounts WHERE publication_id=? ORDER BY tag", (latest["id"],)).fetchall()] if basis == "published" else _roster_rows(db, sid))
            names = {row["tag"]: row["name"] for row in db.execute("SELECT tag,name FROM clans").fetchall()}
            participation = {row["tag"]: row for row in bonus["accounts"]}
            active = {}
            for item in bonus["history"]:
                if not item["voided_at"]:
                    active.setdefault(item["tag"], []).append(item["cycle"])
            fields = ["tag", "user_id", "player_name", "town_hall", "pool", "signup_clan_tag", "signup_clan_name", "assigned_clan_tag", "assigned_clan_name", "source_weight", "manual_weight", "effective_weight", "source_status", "source_checked_at", "source_modified_at", "kept"]
            participation_fields = ["attacks", "stars", "notes", "source_status", "source_complete", "source_warning", "source_checked_at", "attacks_origin", "stars_origin", "attacks_override", "stars_override", "assigned_clan_tag", "assigned_clan_name", "pool", "recorded_publication_version", "roster_changed", "in_latest_publication"]
            columns = list(meta) + ["roster_basis", "roster_revision", "published_version"] + fields + ["participation_" + key for key in participation_fields] + ["bonus_draft_selected", "bonus_draft_reason", "bonus_confirmed_months", "bonus_record_type"]
            for account in base_rows:
                part = participation.get(account["tag"], {})
                row = {**meta, "roster_basis": basis, "roster_revision": latest["revision"] if basis == "published" else _revision(db, sid), "published_version": latest["version"] if latest else None, **{key: account.get(key) for key in fields}}
                if basis == "current":
                    row["assigned_clan_name"] = names.get(account.get("assigned_clan_tag"))
                row.update({"participation_" + key: part.get(key) for key in participation_fields})
                row.update(bonus_draft_selected=part.get("selected", False), bonus_draft_reason=part.get("reason", ""), bonus_confirmed_months="; ".join(active.get(account["tag"], [])), bonus_record_type="dashboard_selection_not_game_award")
                rows.append(row)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_cell(row.get(key)) if key not in {"user_id", "confirmed_by", "voided_by", "updated_by"} or not row.get(key) else "'" + str(row[key]) for key in columns])
    return web.Response(body=("\ufeff" + output.getvalue()).encode("utf-8"), content_type="text/csv", charset="utf-8", headers={"Content-Disposition": f'attachment; filename="cwl-season-{sid}-{kind}-{basis}.csv"', "Cache-Control": "no-store"})

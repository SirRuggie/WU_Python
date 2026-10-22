"""Read-only, staff-only CSV exports and matching JSON previews."""

import csv
import io
import json
from datetime import datetime, timezone

from aiohttp import web

from .bonuses import _view as bonus_view

EXPORT_KINDS = {"accounts", "participation", "participation-history", "bonus-history"}
EXPORT_BASES = {"current", "published"}


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


def _export_snapshot(db, season_id: int, kind: str, basis: str, stamp: str) -> dict:
    """Build preview and CSV from one consistent database transaction snapshot."""
    from .app import _season, _roster_rows, _latest_publication, _revision

    season = _season(db, season_id)
    latest = _latest_publication(db, season_id)
    if basis == "published" and not latest and kind in {"accounts", "participation"}:
        raise web.HTTPConflict(text="Publish a roster before exporting its official version")

    # A published export must not blend a current draft bonus selection into
    # the immutable published roster. Confirmed history is still factual by tag.
    current_roster = kind != "participation-history" and basis != "published"
    bonus = bonus_view(db, season_id, current_roster=current_roster)
    meta = {
        "season_id": season_id,
        "season": season["label"],
        "season_status": season["status"],
        "exported_at_utc": stamp,
        "cwl_month": bonus["cycle"],
    }
    summary = {
        "season_label": season["label"],
        "season_status": season["status"],
        "cwl_month": bonus["cycle"],
        "published_version": latest["version"] if latest else None,
        "published_at": latest["published_at"] if latest else None,
        "roster_revision": (
            latest["revision"] if basis == "published" and latest
            else _revision(db, season_id)
        ),
        "published_available": latest is not None,
    }
    rows: list[dict] = []

    if kind == "bonus-history":
        columns = list(meta) + [
            "id", "tag", "player_name", "pool", "clan_tag", "clan_name",
            "cycle", "publication_version", "attacks", "stars", "reason",
            "warnings", "confirmed_by", "confirmed_at", "voided_by",
            "voided_at", "void_reason", "record_type",
        ]
        rows = [{**meta, **row} for row in bonus["history"]]
        output_basis = "history"
    elif kind in {"participation", "participation-history"}:
        output_basis = "saved_history" if kind == "participation-history" else basis
        columns = list(meta) + ["roster_basis", "matches_roster", "recorded_pool", "recorded_clan_tag", "recorded_clan_name"] + [
            "tag", "player_name", "town_hall", "pool", "assigned_clan_tag",
            "assigned_clan_name", "attacks", "stars", "notes", "attacks_origin",
            "stars_origin", "source_attacks", "source_stars", "source_status",
            "source_complete", "source_checked_at", "source_warning",
            "attacks_override", "stars_override", "recorded_publication_version",
            "in_latest_publication", "roster_changed", "updated_by", "updated_at",
        ]
        saved_tags = {
            row[0] for row in db.execute(
                "SELECT tag FROM participation_records WHERE season_id=?", (season_id,),
            )
        }
        if kind == "participation" and basis == "published":
            records = {row["tag"]: row for row in bonus["accounts"]}
            published_rows = [dict(row) for row in db.execute(
                "SELECT * FROM publication_accounts WHERE publication_id=? ORDER BY tag",
                (latest["id"],),
            ).fetchall()]
            value_fields = [
                "attacks", "stars", "notes", "attacks_origin", "stars_origin",
                "source_attacks", "source_stars", "source_status", "source_complete",
                "source_checked_at", "source_warning", "attacks_override",
                "stars_override", "recorded_publication_version", "roster_changed",
                "updated_by", "updated_at",
            ]
            for identity in published_rows:
                record = records.get(identity["tag"], {})
                matches_roster = bool(record) and not bool(record.get("roster_changed"))
                recorded = record.get("previous_results") if not matches_roster else None
                recorded = recorded or record
                export_row = {
                    **meta,
                    "roster_basis": output_basis,
                    "matches_roster": matches_roster,
                    "recorded_pool": recorded.get("pool"),
                    "recorded_clan_tag": recorded.get("assigned_clan_tag"),
                    "recorded_clan_name": recorded.get("assigned_clan_name"),
                    **identity,
                    "in_latest_publication": True,
                    **{key: record.get(key) for key in value_fields},
                }
                if not matches_roster:
                    for key in value_fields:
                        export_row[key] = None
                    export_row["roster_changed"] = bool(record)
                rows.append(export_row)
        else:
            for row in bonus["accounts"]:
                if kind == "participation-history" and row["tag"] not in saved_tags:
                    continue
                matches_roster = not bool(row.get("roster_changed"))
                recorded = row.get("previous_results") if not matches_roster else None
                recorded = recorded or row
                export_row = {
                    **meta,
                    "roster_basis": output_basis,
                    "matches_roster": matches_roster,
                    "recorded_pool": recorded.get("pool"),
                    "recorded_clan_tag": recorded.get("assigned_clan_tag"),
                    "recorded_clan_name": recorded.get("assigned_clan_name"),
                    **row,
                }
                if not matches_roster and kind == "participation":
                    for key in ("attacks", "stars", "notes", "source_attacks", "source_stars", "source_status", "source_complete", "source_checked_at", "source_warning", "attacks_override", "stars_override", "updated_by", "updated_at"):
                        export_row[key] = None
                rows.append(export_row)
    else:
        output_basis = basis
        base_rows = (
            [dict(row) for row in db.execute(
                "SELECT * FROM publication_accounts WHERE publication_id=? ORDER BY tag",
                (latest["id"],),
            ).fetchall()]
            if basis == "published"
            else _roster_rows(db, season_id)
        )
        names = {
            row["tag"]: row["name"]
            for row in db.execute("SELECT tag,name FROM clans").fetchall()
        }
        participation = {row["tag"]: row for row in bonus["accounts"]}
        active = {}
        for item in bonus["history"]:
            if not item["voided_at"]:
                active.setdefault(item["tag"], []).append(item["cycle"])

        fields = [
            "tag", "user_id", "player_name", "town_hall", "pool",
            "signup_clan_tag", "signup_clan_name", "assigned_clan_tag",
            "assigned_clan_name", "source_weight", "manual_weight",
            "effective_weight", "source_status", "source_checked_at",
            "source_modified_at", "kept",
        ]
        participation_fields = [
            "attacks", "stars", "notes", "source_status", "source_complete",
            "source_warning", "source_checked_at", "attacks_origin", "stars_origin",
            "attacks_override", "stars_override", "assigned_clan_tag",
            "assigned_clan_name", "pool", "recorded_publication_version",
            "roster_changed", "in_latest_publication",
        ]
        columns = list(meta) + ["roster_basis", "roster_revision", "published_version"] + fields + [
            "participation_" + key for key in participation_fields
        ] + ["participation_matches_roster", "participation_recorded_pool", "participation_recorded_clan_tag", "participation_recorded_clan_name", "bonus_draft_selected", "bonus_draft_reason", "bonus_confirmed_months", "bonus_record_type"]
        for account in base_rows:
            part = participation.get(account["tag"], {})
            row = {
                **meta,
                "roster_basis": basis,
                "roster_revision": latest["revision"] if basis == "published" else _revision(db, season_id),
                "published_version": latest["version"] if latest else None,
                **{key: account.get(key) for key in fields},
            }
            if basis == "current":
                row["assigned_clan_name"] = names.get(account.get("assigned_clan_tag"))
            row.update({"participation_" + key: part.get(key) for key in participation_fields})
            matches_roster = bool(part) and not bool(part.get("roster_changed"))
            recorded = part.get("previous_results") if not matches_roster else None
            recorded = recorded or part
            row.update(
                participation_matches_roster=matches_roster,
                participation_recorded_pool=recorded.get("pool"),
                participation_recorded_clan_tag=recorded.get("assigned_clan_tag"),
                participation_recorded_clan_name=recorded.get("assigned_clan_name"),
            )
            if not matches_roster:
                for key in ("attacks", "stars", "notes", "source_status", "source_complete", "source_warning", "source_checked_at", "attacks_origin", "stars_origin", "source_attacks", "source_stars", "attacks_override", "stars_override", "recorded_publication_version", "updated_by", "updated_at"):
                    row["participation_" + key] = None
            row.update(
                bonus_draft_selected=part.get("selected", False) if basis == "current" else False,
                bonus_draft_reason=part.get("reason", "") if basis == "current" else "",
                bonus_confirmed_months="; ".join(active.get(account["tag"], [])),
                bonus_record_type="dashboard_selection_not_game_award",
            )
            rows.append(row)

    summary["row_count"] = len(rows)
    summary["roster_basis"] = output_basis
    return {
        "kind": kind,
        "basis": basis,
        "summary": summary,
        "columns": columns,
        "rows": rows,
        "counts": {"rows": len(rows)},
    }


def _query(request):
    kind = request.query.get("kind", "accounts")
    basis = request.query.get("basis", "current")
    if kind not in EXPORT_KINDS or basis not in EXPORT_BASES:
        raise web.HTTPBadRequest(text="Choose a supported export type and roster version")
    return kind, basis


async def export_preview(request):
    from .app import _require, _sid, _store

    _require(request, "editor")
    season_id = _sid(request)
    kind, basis = _query(request)
    with _store(request).tx() as db:
        result = _export_snapshot(db, season_id, kind, basis, datetime.now(timezone.utc).isoformat())
    return web.json_response(result, headers={"Cache-Control": "no-store"})


async def export_csv(request):
    from .app import _require, _sid, _store

    _require(request, "editor")
    season_id = _sid(request)
    kind, basis = _query(request)
    with _store(request).tx() as db:
        snapshot = _export_snapshot(db, season_id, kind, basis, datetime.now(timezone.utc).isoformat())

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(snapshot["columns"])
    for row in snapshot["rows"]:
        writer.writerow([
            csv_cell(row.get(key))
            if key not in {"user_id", "confirmed_by", "voided_by", "updated_by"} or not row.get(key)
            else "'" + str(row[key])
            for key in snapshot["columns"]
        ])
    return web.Response(
        body=("\ufeff" + output.getvalue()).encode("utf-8"),
        content_type="text/csv",
        charset="utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="cwl-season-{season_id}-{kind}-{basis}.csv"',
            "Cache-Control": "no-store",
        },
    )

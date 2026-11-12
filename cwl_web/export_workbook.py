"""Read-only CWL Excel snapshots, WU block layout and authorized HTTP downloads."""

import calendar
from io import BytesIO
import math
import re
from urllib.parse import quote

from aiohttp import web
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

from .exports import _export_snapshot, csv_cell, _require_bonus_history
from .participation_sync import resolved_cwl_months
from utils.cwl_bonus_allowance import AllowanceStore

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CLAN_TAG = re.compile(r"^#[0289PYLQGRJCUV]{3,15}$")
TITLE, GOLD, HEADER = "19191D", "F2B62A", "242429"
WHITE, ZEBRA, WINNER, EDGE = "FFFFFF", "F7F6F2", "FCEFCB", "D9D7D0"


def month_label(cycle):
    return f"{calendar.month_name[int(cycle[5:7])]} {cycle[:4]}"


def calendar_months(start, end):
    if (
        not isinstance(start, str)
        or not isinstance(end, str)
        or not MONTH.fullmatch(start)
        or not MONTH.fullmatch(end)
    ):
        raise web.HTTPBadRequest(text="Select From and To months in YYYY-MM format")
    first = int(start[:4]) * 12 + int(start[5:7]) - 1
    last = int(end[:4]) * 12 + int(end[5:7]) - 1
    if last < first or last - first >= 12:
        raise web.HTTPBadRequest(
            text="Select an inclusive range of 1–12 months, with To on or after From"
        )
    return [
        f"{year:04d}-{month + 1:02d}"
        for year, month in (divmod(value, 12) for value in range(first, last + 1))
    ]


def _cycle(season, bindings):
    value = bindings.get(season["id"])
    if isinstance(value, str) and MONTH.fullmatch(value):
        return value
    label = season["label"]
    return label if MONTH.fullmatch(label) else None


def season_snapshot(db, sid, basis="published", season=None, bindings=None):
    """Capture only allowed workbook values. No provider or network work here."""
    from .app import _season, _latest_publication

    season = season or dict(_season(db, sid))
    bindings = bindings if bindings is not None else resolved_cwl_months(db, [sid])
    cycle = _cycle(season, bindings)
    if not cycle:
        raise web.HTTPBadRequest(
            text=f"Set the CWL month for season {season['label']} before downloading Excel"
        )
    label = month_label(cycle)
    publication = _latest_publication(db, sid)
    has_roster = bool(publication) or (
        season["status"] != "archived" and not season.get("history_only")
    )
    chosen = "published" if season["status"] == "archived" else basis
    if not publication:
        chosen = "current"
    roster = (
        _export_snapshot(db, sid, "accounts", chosen, "")["rows"] if has_roster else []
    )
    history = _export_snapshot(db, sid, "bonus-history", "current", "")["rows"]
    # A season's older confirmations remain history, but this workbook names one CWL month.
    winners = [
        row for row in history if not row.get("voided_at") and row.get("cycle") == cycle
    ]
    return {
        "month": cycle,
        "label": label,
        "roster": roster,
        "winners": winners,
        "has_roster": has_roster,
        "leagues": AllowanceStore(db, sid, cycle).saved_leagues() if cycle else {},
    }


def range_snapshots(db, start, end):
    wanted = calendar_months(start, end)
    seasons = [
        dict(row) for row in db.execute("SELECT * FROM seasons ORDER BY id DESC")
    ]
    bindings = resolved_cwl_months(db, [row["id"] for row in seasons])
    by_month = {}
    for season in seasons:
        cycle = _cycle(season, bindings)
        if cycle in wanted:
            by_month.setdefault(cycle, []).append(season)
    duplicates = [
        (cycle, by_month[cycle]) for cycle in wanted if len(by_month.get(cycle, [])) > 1
    ]
    if duplicates:
        detail = "; ".join(
            f"{month_label(cycle)}: " + ", ".join(row["label"] for row in rows)
            for cycle, rows in duplicates
        )
        raise web.HTTPConflict(text="Multiple saved seasons for " + detail)
    missing = [month_label(cycle) for cycle in wanted if cycle not in by_month]
    if missing:
        raise web.HTTPNotFound(text="No saved season for " + ", ".join(missing))
    return [
        season_snapshot(
            db, by_month[cycle][0]["id"], season=by_month[cycle][0], bindings=bindings
        )
        for cycle in reversed(wanted)
    ]


def _text(cell, value):
    value = "" if value is None else str(csv_cell(value))
    cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)[:32767]
    cell.data_type = "s"


def _number(value):
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and value >= 0
        else None
    )


def _groups(rows, winners=False):
    groups = {}
    for row in rows:
        tag = row.get("clan_tag" if winners else "assigned_clan_tag") or ""
        name = (
            row.get("clan_name" if winners else "assigned_clan_name")
            or tag
            or "Unplaced"
        )
        key = (row.get("pool") or "", tag, name)
        groups.setdefault(key, []).append(row)
    rank = {"main": 0, "lazy": 1}
    return sorted(
        groups.items(),
        key=lambda item: (
            rank.get(item[0][0], 2),
            str(item[0][2]).casefold(),
            str(item[0][1]),
        ),
    )


def _league_label(league):
    if not isinstance(league, str):
        return ""
    match = re.fullmatch(r"(.*?) League (I|II|III)", league)
    return f"{match[1]} {dict(I=1, II=2, III=3)[match[2]]}" if match else league


def _sheet(book, title):
    title = (
        ILLEGAL_CHARACTERS_RE.sub("", re.sub(r"[\\/*?:\[\]]", " ", title)).strip(" '")
        or "CWL"
    )
    title = title[:31]
    original, index = title, 2
    while title in book.sheetnames:
        suffix = f" {index}"
        title = original[: 31 - len(suffix)] + suffix
        index += 1
    sheet = book.create_sheet(title)
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A4"
    sheet.print_title_rows = "1:3"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.tabColor = GOLD
    sheet.sheet_properties.outlinePr.summaryRight = False
    for name in ("left", "right", "top", "bottom"):
        setattr(sheet.page_margins, name, 0.25)
    return sheet


def _style(cell, fill=WHITE, bold=False, title=False, numeric=False):
    cell.font = Font(
        name="Arial",
        size=14 if title else 10,
        bold=bold or title,
        color=GOLD if title else "F5F4F0" if fill == HEADER else "19191D",
    )
    cell.fill = PatternFill("solid", fgColor=fill)
    cell.alignment = Alignment(
        horizontal="right" if numeric else "left", vertical="center", wrap_text=True
    )
    edge = Side(style="thin", color=EDGE)
    cell.border = Border(left=edge, right=edge, top=edge, bottom=edge)
    if numeric:
        cell.number_format = "#,##0"


def _blocks(book, snapshot, winners=False):
    sheet = _sheet(book, snapshot["label"] + (" bonus winners" if winners else ""))
    columns = (
        ["Player", "Tag", "Pool", "Source"]
        if winners
        else ["★", "Player", "Tag", "TH", "War Weight"]
    )
    widths = [28, 18, 12, 14] if winners else [4, 27, 18, 6, 15]
    width = len(columns)
    winning_tags = {row.get("tag") for row in snapshot["winners"]}
    groups = _groups(snapshot["winners"] if winners else snapshot["roster"], winners)
    start_row = 1
    for offset in range(0, len(groups), 3):
        band_end = start_row
        for column_index, ((pool, tag, name), rows) in enumerate(
            groups[offset : offset + 3]
        ):
            start_col = 1 + column_index * (width + 1)
            end_col = start_col + width - 1
            for step, size in enumerate(widths):
                sheet.column_dimensions[get_column_letter(start_col + step)].width = (
                    size
                )
            sheet.column_dimensions[get_column_letter(end_col + 1)].width = 3
            league = _league_label(snapshot["leagues"].get(tag))
            heading = str(name) + (f" · {league}" if league else "")
            for r in (start_row, start_row + 1):
                sheet.merge_cells(
                    start_row=r, start_column=start_col, end_row=r, end_column=end_col
                )
            for c in range(start_col, end_col + 1):
                _style(sheet.cell(start_row, c), TITLE, title=True)
            _text(sheet.cell(start_row, start_col), heading)
            sheet.row_dimensions[start_row].height = max(
                sheet.row_dimensions[start_row].height or 0,
                30 if len(heading) < 52 else 50,
            )
            link = sheet.cell(start_row + 1, start_col)
            _text(
                link,
                (
                    "Open clan in Clash"
                    if CLAN_TAG.fullmatch(str(tag))
                    else "Clan link unavailable"
                ),
            )
            _style(link)
            if CLAN_TAG.fullmatch(str(tag)):
                link.hyperlink = (
                    "https://link.clashofclans.com/en?action=OpenClanProfile&tag="
                    + str(tag)[1:]
                )
                link.font = Font(
                    name="Arial", size=10, color="8A6100", underline="single"
                )
            sheet.row_dimensions[start_row + 1].height = 22
            for index, label in enumerate(columns):
                cell = sheet.cell(start_row + 2, start_col + index)
                _text(cell, label)
                _style(cell, HEADER, bold=True)
            sheet.row_dimensions[start_row + 2].height = 22
            if winners:
                rows = sorted(
                    rows,
                    key=lambda row: (
                        str(row.get("player_name") or "").casefold(),
                        str(row.get("tag") or ""),
                    ),
                )
            else:
                rows = sorted(
                    rows,
                    key=lambda row: (
                        -(_number(row.get("effective_weight")) or 0),
                        str(row.get("player_name") or "").casefold(),
                    ),
                )
            for index, row in enumerate(rows):
                r = start_row + 3 + index
                is_winner = row.get("tag") in winning_tags
                fill = WINNER if is_winner else ZEBRA if index % 2 else WHITE
                values = (
                    [
                        row.get("player_name"),
                        row.get("tag"),
                        (
                            "Main"
                            if pool == "main"
                            else "Lazy" if pool == "lazy" else "Unassigned"
                        ),
                        "Imported" if row.get("source") == "import" else "Drawn",
                    ]
                    if winners
                    else [
                        "★" if is_winner else "",
                        row.get("player_name"),
                        row.get("tag"),
                        _number(row.get("town_hall")),
                        _number(row.get("effective_weight")),
                    ]
                )
                for step, value in enumerate(values):
                    cell = sheet.cell(r, start_col + step)
                    numeric = not winners and step in (3, 4)
                    if numeric:
                        cell.value = value
                    else:
                        _text(cell, value)
                    _style(cell, fill, numeric=numeric)
                sheet.row_dimensions[r].height = max(
                    sheet.row_dimensions[r].height or 0,
                    32 if len(str(row.get("player_name") or "")) > 28 else 20,
                )
            last = start_row + 3 + len(rows)
            if not winners:
                sheet.merge_cells(
                    start_row=last,
                    start_column=start_col,
                    end_row=last,
                    end_column=end_col - 1,
                )
                missing = sum(
                    _number(row.get("effective_weight")) is None for row in rows
                )
                _text(
                    sheet.cell(last, start_col),
                    f"Total ({missing} weight missing)" if missing else "Total",
                )
                _style(sheet.cell(last, start_col), ZEBRA, bold=True)
                total = sheet.cell(last, end_col)
                total.value = (
                    f"=SUM({get_column_letter(end_col)}{start_row + 3}:{get_column_letter(end_col)}{last - 1})"
                    if not missing
                    else None
                )
                _style(total, ZEBRA, bold=True, numeric=True)
                if missing:
                    _text(total, "Unavailable")
                sheet.row_dimensions[last].height = 24
            band_end = max(band_end, last if not winners else last - 1)
        start_row = band_end + 3  # exactly two untouched rows between block bands
    if not groups:
        _text(
            sheet.cell(1, 1),
            (
                "No saved bonus winners for this month."
                if winners
                else "No saved roster accounts."
            ),
        )
        _style(sheet.cell(1, 1))
        sheet.column_dimensions["A"].width = 52
    sheet.print_area = sheet.dimensions
    return sheet


def workbook(snapshots, include_all=False):
    book = Workbook()
    book.remove(book.active)
    book.properties.creator = "Warriors United"
    book.calculation = CalcProperties(
        calcId=191029, fullCalcOnLoad=True, forceFullCalc=True
    )
    snapshots = sorted(snapshots, key=lambda row: row["month"] or "", reverse=True)
    if include_all:
        sheet = _sheet(book, "All winners")
        sheet.freeze_panes = "A2"
        sheet.print_title_rows = "1:1"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        for c, (label, width) in enumerate(
            zip(
                ["Month", "Clan", "Player", "Tag", "Pool", "Source"],
                [22, 32, 30, 18, 12, 14],
            ),
            1,
        ):
            _text(sheet.cell(1, c), label)
            _style(sheet.cell(1, c), HEADER, bold=True)
            sheet.column_dimensions[get_column_letter(c)].width = width
        r = 2
        for snapshot in snapshots:
            for (pool, tag, name), rows in _groups(snapshot["winners"], True):
                for row in sorted(
                    rows, key=lambda row: str(row.get("player_name") or "").casefold()
                ):
                    values = [
                        snapshot["label"],
                        name,
                        row.get("player_name"),
                        row.get("tag"),
                        (
                            "Main"
                            if pool == "main"
                            else "Lazy" if pool == "lazy" else "Unassigned"
                        ),
                        "Imported" if row.get("source") == "import" else "Drawn",
                    ]
                    for c, value in enumerate(values, 1):
                        _text(sheet.cell(r, c), value)
                        _style(sheet.cell(r, c), ZEBRA if r % 2 == 0 else WHITE)
                    sheet.row_dimensions[r].height = 30
                    r += 1
        sheet.auto_filter.ref = f"A1:F{max(1, r-1)}"
        sheet.print_area = sheet.dimensions
    for snapshot in snapshots:
        if snapshot["has_roster"]:
            _blocks(book, snapshot)
        _blocks(book, snapshot, winners=True)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def _authorize(request):
    from .app import _require

    session = _require(request, "editor")
    _require_bonus_history(request, "bonus-history", session)


def _response(data, filename):
    return web.Response(
        body=data,
        content_type=MIME,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(filename, safe=""),
        },
    )


async def export_season(request):
    from .app import _sid, _store

    _authorize(request)
    if set(request.query) - {"basis"} or request.query.get(
        "basis", "published"
    ) not in ("current", "published"):
        raise web.HTTPBadRequest(text="Select Published or Working roster")
    with _store(request).tx() as db:
        snapshot = season_snapshot(
            db, _sid(request), request.query.get("basis", "published")
        )
    return _response(workbook([snapshot]), "CWL " + snapshot["label"] + ".xlsx")


async def export_range(request):
    from .app import _store

    _authorize(request)
    if set(request.query) != {"from", "to"}:
        raise web.HTTPBadRequest(text="Select From and To months")
    with _store(request).tx() as db:
        snapshots = range_snapshots(db, request.query["from"], request.query["to"])
    start, end = request.query["from"], request.query["to"]
    label = (
        f"{calendar.month_abbr[int(start[5:7])]}–{calendar.month_abbr[int(end[5:7])]} {end[:4]}"
        if start[:4] == end[:4]
        else f"{calendar.month_abbr[int(start[5:7])]} {start[:4]}–{calendar.month_abbr[int(end[5:7])]} {end[:4]}"
    )
    return _response(workbook(snapshots, include_all=True), "CWL " + label + ".xlsx")

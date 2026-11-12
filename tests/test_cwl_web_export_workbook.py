"""Real XLSX contracts, read-only snapshots and authorization boundaries."""

from io import BytesIO
import json
import unittest
from unittest.mock import patch

from aiohttp import web
from openpyxl import load_workbook
import test_cwl_web_bonuses as fixtures
from cwl_web.export_workbook import calendar_months, workbook


def sample(month="2026-11"):
    roster = []
    for index, (pool, tag) in enumerate(
        [("main", "#C2Y"), ("main", "#R2Y"), ("main", "#J2Y"), ("lazy", "#Q2Y")]
    ):
        for n, weight in enumerate([174000, 179000]):
            roster.append(
                dict(
                    pool=pool,
                    assigned_clan_tag=tag,
                    assigned_clan_name=f"Clan {index}",
                    tag=f"#P{index}{n}",
                    player_name=(
                        "=SUM(1,2)" if index == n == 0 else f"Player {index}{n}"
                    ),
                    town_hall=16,
                    effective_weight=weight,
                    discord_id="SECRET123",
                )
            )
    return dict(
        month=month,
        label="November 2026" if month == "2026-11" else "October 2026",
        has_roster=True,
        roster=roster,
        winners=[
            dict(
                pool="main",
                clan_tag="#C2Y",
                clan_name="Clan 0",
                tag="#P00",
                player_name="=SUM(1,2)",
                source="import",
            )
        ],
        leagues={"#C2Y": "Master League II"},
    )


class WorkbookLayoutTests(unittest.TestCase):
    def test_real_workbook_layout_styles_numeric_values_links_and_text_safety(self):
        book = load_workbook(BytesIO(workbook([sample()])))
        self.assertEqual(
            book.sheetnames, ["November 2026", "November 2026 bonus winners"]
        )
        sheet = book.worksheets[0]
        self.assertEqual(
            [sheet.cell(1, c).value for c in (1, 7, 13)],
            ["Clan 0 · Master 2", "Clan 1", "Clan 2"],
        )
        self.assertEqual(sheet["A9"].value, "Clan 3")
        self.assertTrue(
            all(sheet.cell(r, c).value is None for r in (7, 8) for c in range(1, 18))
        )
        self.assertTrue(all(sheet.cell(r, 6).value is None for r in range(1, 7)))
        self.assertEqual(sheet["B4"].value, "Player 01")
        self.assertEqual(sheet["B5"].value, "'=SUM(1,2)")
        self.assertEqual(sheet["B5"].data_type, "s")
        self.assertEqual(sheet["E4"].value, 179000)
        self.assertEqual(sheet["E4"].data_type, "n")
        self.assertEqual(sheet["E6"].value, "=SUM(E4:E5)")
        self.assertEqual(sheet["A5"].value, "★")
        self.assertEqual(sheet["E5"].fill.fgColor.rgb[-6:], "FCEFCB")
        self.assertEqual(sheet["A1"].fill.fgColor.rgb[-6:], "19191D")
        self.assertEqual(sheet["A1"].font.color.rgb[-6:], "F2B62A")
        self.assertEqual(sheet["A1"].font.sz, 14)
        self.assertEqual(sheet["B3"].fill.fgColor.rgb[-6:], "242429")
        self.assertEqual(sheet["E4"].number_format, "#,##0")
        self.assertEqual(sheet["E4"].alignment.horizontal, "right")
        self.assertEqual(
            sheet["A2"].hyperlink.target,
            "https://link.clashofclans.com/en?action=OpenClanProfile&tag=C2Y",
        )
        self.assertEqual(sheet.freeze_panes, "A4")
        self.assertEqual(sheet.print_title_rows, "$1:$3")
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertEqual(sheet.page_setup.fitToWidth, 1)
        self.assertEqual(book.worksheets[1]["D4"].value, "Imported")
        self.assertNotIn(
            "SECRET123",
            str([[cell.value for cell in row] for ws in book for row in ws]),
        )

    def test_range_newest_first_filter_and_bonus_only_history(self):
        older = sample("2026-10")
        older["has_roster"] = False
        book = load_workbook(BytesIO(workbook([older, sample()], include_all=True)))
        self.assertEqual(
            book.sheetnames,
            [
                "All winners",
                "November 2026",
                "November 2026 bonus winners",
                "October 2026 bonus winners",
            ],
        )
        all_winners = book["All winners"]
        self.assertEqual(all_winners["A2"].value, "November 2026")
        self.assertEqual(all_winners["A3"].value, "October 2026")
        self.assertEqual(all_winners.auto_filter.ref, "A1:F3")
        self.assertEqual(all_winners.freeze_panes, "A2")

    def test_missing_weight_invalid_clan_and_untrusted_strings(self):
        data = sample()
        data["roster"][0].update(
            effective_weight=None,
            assigned_clan_tag='=HYPERLINK("evil")',
            assigned_clan_name="@evil",
        )
        data["winners"][0]["player_name"] = '\t=HYPERLINK("evil")'
        book = load_workbook(BytesIO(workbook([data])))
        values = [cell for row in book.worksheets[0] for cell in row]
        self.assertTrue(any(cell.value == "Unavailable" for cell in values))
        self.assertTrue(any(cell.value == "'@evil" for cell in values))
        self.assertTrue(
            all(
                not cell.hyperlink
                or cell.hyperlink.target.startswith(
                    "https://link.clashofclans.com/en?action=OpenClanProfile&tag="
                )
                for cell in values
            )
        )
        self.assertTrue(book.worksheets[1]["A4"].value.startswith("'"))

    def test_month_range_validation(self):
        self.assertEqual(
            calendar_months("2026-08", "2026-11"),
            ["2026-08", "2026-09", "2026-10", "2026-11"],
        )
        self.assertEqual(len(calendar_months("2025-12", "2026-11")), 12)
        for start, end in [
            ("2026-11", "2026-08"),
            ("2025-11", "2026-11"),
            ("2026-13", "2026-11"),
            ("bad", "2026-11"),
        ]:
            with self.subTest(start=start, end=end), self.assertRaises(
                web.HTTPBadRequest
            ):
                calendar_months(start, end)


class WorkbookEndpointTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.BonusTests.asyncSetUp
    asyncTearDown = fixtures.BonusTests.asyncTearDown
    auth = fixtures.BonusTests.auth
    call = fixtures.BonusTests.call
    revision = fixtures.BonusTests.revision
    signup = fixtures.BonusTests.signup
    setup_published = fixtures.BonusTests.setup_published
    seed_complete_source = fixtures.BonusTests.seed_complete_source
    settings = fixtures.BonusTests.settings
    select = fixtures.BonusTests.select
    preview = fixtures.BonusTests.preview
    base = fixtures.BonusTests.base

    async def read_book(self, url, who=None):
        response = await self.call("GET", url, who or self.owner)
        self.assertEqual(
            response.status,
            200,
            await response.text() if response.status != 200 else "",
        )
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertTrue(
            response.headers["Content-Type"].startswith(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        )
        return load_workbook(BytesIO(await response.read())), response

    async def test_permissions_on_both_routes_and_nonwinner_preview_unchanged(self):
        await self.setup_published()
        urls = [
            f"/seasons/{self.sid}/export.xlsx",
            "/exports/range.xlsx?from=2026-10&to=2026-10",
        ]
        for url in urls:
            self.assertEqual((await self.call("GET", url)).status, 401)
            self.assertEqual((await self.call("GET", url, self.member)).status, 403)
        staff = self.auth("200")
        for grant, expected in [
            ("cwl_results", 403),
            ("cwl_bonuses", 200),
            ("cwl_send", 200),
        ]:
            with self.app["store"].tx() as db:
                db.execute(
                    "INSERT INTO grants(user_id,granted_by,permissions) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET permissions=excluded.permissions",
                    ("200", "fixture", json.dumps([grant])),
                )
            for url in urls:
                response = await self.call("GET", url, staff)
                self.assertEqual(
                    response.status,
                    expected,
                    (grant, url, await response.text() if expected != 200 else ""),
                )
                self.assertEqual((await self.call("GET", url, self.owner)).status, 200)
            self.assertEqual(
                (
                    await self.call(
                        "GET",
                        f"/seasons/{self.sid}/export-preview?kind=accounts",
                        staff,
                    )
                ).status,
                200,
            )

    async def test_published_working_saved_league_and_no_application_writes(self):
        await self.setup_published()
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE roster_entries SET manual_weight=179000 WHERE season_id=?",
                (self.sid,),
            )
            db.execute(
                "INSERT INTO bonus_allowance_leagues VALUES (?,'2026-10','#C2Y','Master League II','fixture')",
                (self.sid,),
            )
            db.execute(
                "INSERT INTO bonus_imported_winners VALUES (?,'2026-10','lazy','#P2Y','Imported','#C2Y','Clan','import','fixture','now')",
                (self.sid,),
            )
            db.execute(
                "INSERT INTO bonus_imported_winners VALUES (?,'2026-09','lazy','#Q2Y','Old month','#C2Y','Clan','import','fixture','now')",
                (self.sid,),
            )
            before = list(db.iterdump())
        working, response = await self.read_book(
            f"/seasons/{self.sid}/export.xlsx?basis=current"
        )
        self.assertIn(
            "CWL%20October%202026.xlsx", response.headers["Content-Disposition"]
        )
        self.assertEqual(working.worksheets[0]["E4"].value, 179000)
        self.assertTrue(working.worksheets[0]["A1"].value.endswith("Master 2"))
        self.assertEqual(working.worksheets[0]["A4"].value, "★")
        self.assertEqual(working.worksheets[1].max_row, 4)
        published, _ = await self.read_book(f"/seasons/{self.sid}/export.xlsx")
        self.assertNotEqual(published.worksheets[0]["E4"].value, 179000)
        with self.app["store"].tx() as db:
            self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(
            (
                await self.call("GET", f"/seasons/{self.sid}/export.csv", self.owner)
            ).status,
            404,
        )

    async def test_range_all_duplicates_all_gaps_and_clean_august_november(self):
        await self.setup_published()
        base = "/exports/range.xlsx?from=2026-08&to=2026-11"
        response = await self.call("GET", base, self.owner)
        self.assertEqual(response.status, 404)
        message = (await response.json())["error"]
        for month in ("August 2026", "September 2026", "November 2026"):
            self.assertIn(month, message)
        with self.app["store"].tx() as db:
            for month in ("2026-08", "2026-09", "2026-11"):
                db.execute(
                    "INSERT INTO seasons(label,status,signup_open,history_only) VALUES (?,'archived',0,1)",
                    (month,),
                )
            duplicate = db.execute(
                "INSERT INTO seasons(label) VALUES ('Second October staff')"
            ).lastrowid
            db.execute(
                "INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES (?,'2026-10')",
                (duplicate,),
            )
        response = await self.call("GET", base, self.owner)
        self.assertEqual(response.status, 409)
        message = (await response.json())["error"]
        self.assertIn("October 2026", message)
        self.assertIn("Second October staff", message)
        self.assertIn(
            self.app["store"].one("SELECT label FROM seasons WHERE id=?", (self.sid,))[
                "label"
            ],
            message,
        )
        with self.app["store"].tx() as db:
            db.execute(
                "DELETE FROM manage_campaign_bindings WHERE season_id=?", (duplicate,)
            )
            db.execute("DELETE FROM seasons WHERE id=?", (duplicate,))
        book, response = await self.read_book(base)
        self.assertEqual(
            book.sheetnames,
            [
                "All winners",
                "November 2026 bonus winners",
                "October 2026",
                "October 2026 bonus winners",
                "September 2026 bonus winners",
                "August 2026 bonus winners",
            ],
        )
        self.assertIn(
            "CWL%20Aug%E2%80%93Nov%202026.xlsx", response.headers["Content-Disposition"]
        )
        response = await self.call(
            "GET", "/exports/range.xlsx?from=2026-07&to=2026-08", self.owner
        )
        self.assertEqual(response.status, 404)
        self.assertIn("July 2026", (await response.json())["error"])
        response = await self.call(
            "GET", "/exports/range.xlsx?from=2026-06&to=2026-08", self.owner
        )
        self.assertEqual(response.status, 404)
        self.assertIn("June 2026", (await response.json())["error"])
        self.assertIn("July 2026", (await response.json())["error"])

    async def test_unbound_free_label_fails_without_inventing_month_or_winners(self):
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE seasons SET label='Staff archive without month' WHERE id=?",
                (self.sid,),
            )
            before = list(db.iterdump())
        response = await self.call(
            "GET", f"/seasons/{self.sid}/export.xlsx", self.owner
        )
        self.assertEqual(response.status, 400)
        message = (await response.json())["error"]
        self.assertIn("Staff archive without month", message)
        self.assertIn("Set the CWL month", message)
        with self.app["store"].tx() as db:
            self.assertEqual(list(db.iterdump()), before)

    async def test_archived_without_publication_omits_working_roster(self):
        await self.signup("main", "#P2Y")
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE seasons SET label='2026-08',status='archived' WHERE id=?",
                (self.sid,),
            )
        book, _ = await self.read_book(f"/seasons/{self.sid}/export.xlsx?basis=current")
        self.assertEqual(book.sheetnames, ["August 2026 bonus winners"])
        self.assertNotIn(
            "Main", str([[c.value for c in row] for row in book.worksheets[0]])
        )

    async def test_voided_confirmation_is_not_a_winner_in_either_sheet(self):
        await self.setup_published()
        await self.seed_complete_source()
        self.assertEqual((await self.settings(0)).status, 200)
        self.assertEqual((await self.select(1)).status, 200)
        preview = await self.preview()
        response = await self.call(
            "POST",
            self.base + "/confirm",
            self.owner,
            json={
                "revision": 2,
                "fingerprint": preview["fingerprint"],
                "acknowledge_warnings": True,
            },
        )
        self.assertIn(response.status, (200, 201), await response.text())
        before, _ = await self.read_book(f"/seasons/{self.sid}/export.xlsx")
        self.assertEqual(before.worksheets[0]["A4"].value, "★")
        history = self.app["store"].one(
            "SELECT id FROM bonus_confirmations WHERE season_id=?", (self.sid,)
        )
        response = await self.call(
            "POST",
            self.base + "/" + str(history["id"]) + "/void",
            self.owner,
            json={"revision": 3, "reason": "Fixture correction"},
        )
        self.assertEqual(response.status, 200, await response.text())
        after, _ = await self.read_book(f"/seasons/{self.sid}/export.xlsx")
        self.assertIsNone(after.worksheets[0]["A4"].value)
        self.assertEqual(
            after.worksheets[1]["A1"].value, "No saved bonus winners for this month."
        )

    async def test_endpoint_malformed_ranges_and_basis_fail_before_download(self):
        for suffix in ["?basis=bad", "?kind=accounts"]:
            self.assertEqual(
                (
                    await self.call(
                        "GET", f"/seasons/{self.sid}/export.xlsx" + suffix, self.owner
                    )
                ).status,
                400,
            )
        for query in [
            "from=2026-11&to=2026-08",
            "from=2025-11&to=2026-11",
            "from=2026-08",
            "from=bad&to=2026-11",
            "from=2026-08&to=2026-11&basis=current",
        ]:
            response = await self.call(
                "GET", "/exports/range.xlsx?" + query, self.owner
            )
            self.assertEqual(response.status, 400, (query, await response.text()))

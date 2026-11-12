# Exports & history

The `/cwl/exports` page shows Roster (`accounts`), Signups (`participation`),
Results history (`participation-history`) and Bonus winners (`bonus-history`).
Lists group by hosting clan, Main before Lazy, without search or paging. Month
labels use the nullable `cwl_month` supplied by the Results settings owner, then
an exact YYYY-MM season label; otherwise the original label remains unchanged
and sorts last. This read-only metadata was authorized by Shaka1020.

Roster defaults Published. Non-archived seasons offer Published/Working;
unpublished seasons show Working and “Not published yet.” Archived seasons
without a publication never expose working accounts. Reactivating the selected
mode performs no read and preserves records. Bonus winners excludes voided
confirmations and labels imported rows Imported. These are saved staff selections,
not proof of in-game awards. Names and notes render as text.

Download season (Excel) reads `GET /api/cwl/seasons/{id}/export.xlsx`; the existing
switch supplies `basis=published|current`. Filename: `CWL November 2026.xlsx`.
Both this route and `GET /api/cwl/exports/range.xlsx?from=YYYY-MM&to=YYYY-MM` require
existing editor access AND owner, `cwl_bonuses` or `cwl_send` (Shaka1025). Plain
editors retain nonwinner previews. The earlier Shaka1016 winner-preview gate is
unchanged. The former CSV route/UI and obsolete CSV browser harness were removed;
ExportWorkspace was their only runtime caller. `export-preview` remains available
to its existing callers.

Each download takes one store transaction snapshot, makes no network calls, and
renders XLSX after that transaction closes. Responses are `Cache-Control: no-store`.
The roster sheet has three clan blocks across, Main before Lazy, one blank column
between blocks and two blank rows between bands. Each block has a merged dark/gold
title, saved seasonal league if available (never the current clan profile), an
Open clan in Clash link, and ★ / Player / Tag / TH / War Weight. Weights are full
numeric values sorted highest first, with a SUM total. Missing weights stay blank
and their total says Unavailable. Current-month nonvoided winners have a star and
soft gold fill. The second sheet contains Player / Tag / Pool / Source
(Drawn or Imported). History-only or archived months without publication have
only that bonus-winner sheet. Text cells apply the existing formula protection;
Discord IDs are excluded. Sheets freeze top rows, print landscape one page wide,
and repeat the first title rows. WU colors, 14pt title, 10pt body, zebra rows and
thin borders match the approved layout.

Download a range… opens From/To controls without fetching. The inclusive span is
1–12 calendar months, with To on or after From. `CWL Aug–Nov 2026.xlsx` begins with
All winners: Month / Clan / Player / Tag / Pool / Source, newest month first,
filter on every column and frozen header. Month sheets follow newest first.
Shaka1026 requires duplicate resolved months to fail409 naming the month and all
season labels; missing months fail404 naming every gap. The message appears below
the range controls and no file is offered. Unparsed labels are never invented as
range months. Deliberate retry, duplicate fencing, stale-response suppression and
abort on season/basis change, unmount or closing an active range remain read-only.
Denied reads clear protected preview content and offer no automatic retry.

`web/cwl/tests/fixtures/exports_dashboard.py` uses synthetic SQLite and fixture
providers with external sockets blocked. It supplies six hosting clans for
multiple block bands, saved leagues, published/working weights, imports and
history-only months. Native 360×800 and1440×1000 review and LibreOffice renders
are recorded in the batch artifact. Checks cover affected 44px controls, reflow,
loading, denied/retry, cancellation and exact fixture counts; they are scoped
usability checks, not assistive-technology certification or live Excel/Discord
proof. No production endpoints or application data writes are used.

Shaka1027: a season without a bound CWL month or exact YYYY-MM label fails400
for its Excel download. The message names the season and asks staff to set its
CWL month first; preview labels remain unchanged. No month or winner scope is
invented. The error stays next to the download control.

# Exports & history (231)

The existing `/cwl/exports` route now answers who was on a roster and who won a
bonus. Navigation and page title read Exports & history. The existing seasons response now includes nullable `cwl_month`, resolved by
`participation_sync` with the same settings-before-manage-binding precedence as
Results. The complete list resolves in one query, without per-season reads.
Exports names/sorts by bound month first; otherwise an exact YYYY-MM label;
otherwise the original label unchanged. Bound/parsed months sort newest first;
unparsed free labels sort last by descending season id. No month is invented.
History-only months remain available. This read-only metadata field is authorized
by Shaka1020 and must be disclosed in READY.

Show keeps the existing API values: Roster (`accounts`), Signups
(`participation`), Results history (`participation-history`) and Bonus winners
(`bonus-history`). All lists group by hosting clan, Main before Lazy, without
search, paging or duplicate bottom history disclosures. Roster uses shared
read-only account cards with player, tag, TH and compact weight. Signups and
saved results retain their saved result/capture details and closed notes.

Roster defaults to the latest publication. Non-archived seasons have a
Published/Working switch; an unpublished current season shows Working and
“Not published yet.” Archived seasons never expose working accounts when no
publication exists: “No roster saved for this month.” The initial existing
current read supplies publication availability; working rows remain hidden
while a requested publication loads. No new endpoint or write is introduced.

Bonus winners hides voided rows, groups Main before Lazy and labels imported
rows Imported. The existing history read includes `bonus_imported_winners`
through its raffle storage owner and returns `source=import`; dashboard
confirmations return `source=dashboard`. No batches or receipts are fabricated.
Existing CSV columns are retained until232; imported history joins the existing
bonus-history CSV rows without introducing an Excel implementation. The UI
retains the existing Bonuses OR Send grant rule. Actual Shaka1016 authorizes the matching server permission tightening for
bonus-history preview and CSV only: owner, Bonuses or Send may read; a plain
editor lacking both gets403. Every other export kind keeps its prior check.
READY must disclose this permission tightening.

Loading/retry, denied401/403 clearing, request-generation guards, cancellation
and duplicate-download fencing remain. Download CSV passes the original Blob
through and is disabled for no displayed saved accounts. Names and notes render
as React text; raw Discord IDs are not displayed. No action writes domain data.

The isolated `web/cwl/tests/fixtures/exports_dashboard.py` fixture supplies
published/working/unpublished/archived/imported states and loopback-only denied
and retry scenarios (`/_exports/scenario/denied`, `/retry`, `/normal`). It uses
actual backend export handlers and synthetic SQLite data. No browser clock or
DOM injection, production data, live API or Discord delivery is used. Final
native360×800/1440×1000 review covers grouping, labels, 44px controls, reflow,
empty/denied/retry states and CSV transport. Automated and native evidence are
recorded in the batch review artifact; these are scoped usability checks, not
assistive-technology certification.


Reactivating the already-selected Published/Working mode is a no-op: it neither
clears the displayed records nor starts a read, including unpublished Working.

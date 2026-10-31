# Prompt 54 PR B: merged activity page

The sidebar has one **Strikes & replacements** destination. `/strikes` opens the
family roster; `/replacements` opens the same roster with the replacement filter.
Old `/clans/strikes` and `/clans/replacements` links remain readable aliases.
The backend serves both canonical paths, and sign-in preserves bounded, allowlisted
filters and the selected account while rejecting arbitrary redirect parameters.
Leave and Settings remain tabs. Account detail keeps strike history, manual
add/remove actions and the revision-protected priority editor. The old standalone
workspace, group renderer, bulk-only helpers and styles are retired. Recruit
weight matching remains behind a disclosure and reads only after an explicit
request. Its results open the same account detail.

## Data and permissions

`GET /api/cwl/strikes/accounts?activity=true` uses the existing strikes-read grant;
regular strike/priority writes retain their existing routes. Prompt 56 adds an
explicit quarantine-resolution action through PR A, with the manage grant, reason,
revision check and audit receipt; PR B supplies its confirmation UI and a read-only
review refresh. Its one response contains every current family
account and recently departed tracked accounts, including accounts without
strikes. The activity owner projects page fields and the town-hall scalar, excluding the
large per-unit baseline from this read; the strike ledger supplies
retained records, profiles and its public replacement eligibility, preserving
original-clan departure grace. Current weights use the existing public weight
service and saved-weight overlay. An upstream outage preserves the roster and
shows a warning. The saved-weight overlay still applies during an outage, so
an intentionally blank saved weight never revives an older profile value. Missing Discord names retain ID search and an explicit notice;
this page does not fan out into one live Discord request per account.

Signals count the last 14 observed regular lineup wars, exclude CWL and manual
records, and require consecutive most-recent no-attack wars and raid skips.
Unknown activity never becomes Quiet. Seeded timestamps retain the ClashKing
attribution and its observed-attack limitation. Retained counts are labeled
**last 90 days**, not lifetime. Dates, names and other upstream strings are rendered
as text. No live notification test or Discord write is part of this review.

The 1000-row fixture is asserted below 300 KB gzipped. Sorting, searching,
filtering and 25-row pagination are client-side; typing does not refetch the
family. Filters and sort live in the URL. Back restores them, scroll and row
focus. In-flight reads are ignored after unmount, manual refresh does not overlap,
and 401/403 clears protected rows. Read failures are distinguished from an empty
family and from no matching filters.

## Interaction and evidence

The scope follows `docs/dashboard-interaction-standard.md`: searchable overview,
one account editor, labeled native controls and disclosures for occasional
matching/history. Current summary and refresh time stay visible. Errors are
visible outside disclosures; priority and manual edits retain their existing
revision/conflict and discard guards. Bulk selection restores the existing current-clan marking route. Displayed revisions are checked before any write and at each account CAS; existing marks are skipped. A partial group or conflict locks submission until explicit refresh, and no write automatically retries.

Browser-only fixtures cover 26, 65 and 125 accounts at 360×800 and 1440×1000.
Checks measure overflow, strike-count alignment, wrapped chips, 44px control
heights, text at least 12px, default and clan-filtered lists, the replacement deep
link, every-chip and healthy rows, unknown activity, and external request blocking.
Screenshots were visually inspected; final review paths and suite counts are in
the handoff. The existing detail/settings/import browser checks remain in the
layout gate. Automated checks do not constitute an assistive-technology audit.

Required mutations: unknown shows Quiet; CWL contributes to no-attack streak;
nonconsecutive raid skips count; replacement alias drops its filter. Each must
fail its targeted regression and source must be restored afterward. Final evidence
is under `.local/p54b-evidence`, with full validation reported only after all gates
pass. No production release is implied by these fixtures.


## Quarantine review (prompt 56)

Find war always shows a quarantined incident, including saved partial rows. Open
it to read the held-review reason. Only staff with `strikes` manage can resolve:
a reason and confirmation are required, a pending request cannot duplicate, and
409 retains the reason until an explicit revision refresh. The read endpoint is
guild-scoped with the existing read grant. Resolving releases the streak hold and
preserves the audit receipt; it never creates the missing strike. Draft navigation
uses the same Keep editing/Discard guard as the other editors.


## Prompt 58 corrections

The first row is measured at or above420px at360px width and360px at1440px.
Tabs and compact tracking share a row; search/sort stay together. Help, Add strike
and Find war form a compact action row; Refresh and Select accounts are in the
labeled Activity actions disclosure. Selection is off by default, manage-only,
limited to50 current-clan accounts; Select all covers the entire current filter,
including later pages. Read-only notes are visible on rows and details.

A war contributes only when that player's complete outcome is known. Miss-only
import rows cannot establish a streak. The bounded historical backfill reads full
lineups through the existing60-day ClashKing import reader and stores fourteen
war summaries in the existing player document. Monitored captures win duplicate
keys; mismatch, exempt and no-attack observations neither count nor break the
chain. No-plan FWA wars count normally; mismatch plans are neutral. Non-regular wars are ignored. No strike ledger,
streak or replacement mark is written by this backfill. Per-clan retries preserve healthy caches; canceled runs consume no attempts.
Three failures expose a stuck clan tag and retry after six hours. Unusable observations stop only their own clan members’ chains at that point. Three concurrent clans, 120 seconds
per clan and 600 seconds per run bound the job.

The newest daily tracker timestamp controls freshness. Older than36hours pauses
Quiet and its badge contribution. An unavailable activity collection retains
strike/profile rows with an explicit warning and suppresses activity chips. One
cached Discord directory read supplies names; missing names get an ID-search
notice. Over limit uses the configured strike limit; New this week counts recent
active, unrevoked strikes. Recruit matching explicitly uses all FWA clans/Town
Halls rather than list filters, and shows Gap. Oversized login numbers are rejected
before integer conversion.

Additional required mutations cover invented imported streaks, mismatch penalties,
stale Quiet, backfill writes to streaks, and a blank page on activity failure.
The real Mongo lane covers concurrent bounded recent_wars writes with unchanged
strike records and permanent profile/streak state. Browser checks include manager
wiring and Select all across pages. No mocked notification test proves delivery.

### Prompt59 follow-up review

Production-shaped profiles without a Discord ID resolve through one cached public
bulk link lookup, followed by the existing cached member directory. Link or name
outages remain visible and cannot remove strike rows. The release check must report
how many production accounts resolve; fixture lookup tests do not establish that
live count.

Bulk selections clear on externally supplied filter changes and Discard. The panel
lists every selected name/tag/clan, including later pages. Partial errors preserve
server counts, name unresolved accounts and keep only those selections, requiring
an explicit revision refresh before another submission. No fixture result proves
live Discord delivery.

Clan-history retries, cancellation, recovery, cache reuse, cache retirement and
exemptions after ledger purge have direct regressions. Revoked wars are neutral;
left players do not acquire Quiet or its risk badge; unavailable tracking retains
priority, strike and departure chips. Clan metadata is isolated from player rows
and retires through the existing TTL. Prompt60 removes obsolete completion flags.

Follow-up validation: 1,178 frontend tests, TypeScript and production build pass;
all seven integrated build/layout stages pass. The activity fixture records 79
measurements across 26/65/125 accounts, 320/360/390/1440 widths and a short mobile
viewport. First rows measure about 375px at 360 and 320px at 1440. Confirmation
screenshots at 360/1440 were visually inspected; the browser asserts all 26
selected accounts, including the next page, are listed. Five isolated real-Mongo
checks and 76 focused backend regressions pass. The network-isolated full backend
result is recorded in the final handoff and evidence directory.


### Prompt60 simplification

Daily clan refresh replaces permanent completion and page-wide flags. No-plan FWA
wars count; friendly/CWL wars are ignored. Failed reads and malformed lineups add
local chain stops, which a later daily refresh removes. The only page warning
names affected clans; healthy rows retain their own known history. Page reads
project failed clan tags without fetching cached lineups. Old completion/status
fields are retired on the version-3 write. UTC normalization prevents unchanged
BSON-naive rows from acquiring new revisions hourly.

Identity rows return from cache immediately. One background refresh updates bulk
links and Discord names, with an eight-second budget and a two-minute failure
cooldown; requests never queue behind it. A warm cache stays usable during an
outage. Empty names cache shows a warning. Select all is disabled above fifty
accounts with a visible filter instruction; Vitest checks all twenty-six names
and the Left clan chip. Scheduler tests pin the clock away from month boundaries.

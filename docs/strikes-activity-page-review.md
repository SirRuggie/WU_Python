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
revision/conflict and discard guards. No new write or retry semantics were added.

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

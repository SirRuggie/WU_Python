# Hosting locations and member assignment checks

Prompts 100, 101 and 102 are bundled for one backend/frontend release after
Claude's ACCEPT. Incoming handoff 329 quotes Ruggie's explicit approval for all
three and replaces the earlier holds. No bot restart or migration is expected;
a fresh no-queued-run gate and the usual backup, test restore, protected-state,
readiness, rollback and public-hash checks are still required.

The shared pure rules live in utils/cwl_location_rules.py. Outside family requires
current known location, an available family directory, and a clan outside both
family and all configured non-archived hosting clans. Store owns hosting-clan
selection. Roster, Declaration and Compare use that one rule. A player in another
hosting clan remains missing from the assigned clan, without an Outside family
badge. Unknown/stale/directory-unavailable data cannot establish outside status.
The existing comparisonLocation carry-over behavior is unchanged.

Member assignments retain their existing ownership/publication/pool filtering.
Only already filtered, published placements enter the existing shared background
location cache. Reads return immediately; cached current values use the same
arrival rule as Declaration. Alongside arrival_status, verified own-account
observations project current clan tag/name/status and their checked timestamp.
Lookup jobs, other users' accounts and unrelated provider records are not exposed.
No new polling or per-row browser requests were added; existing visible-view
refresh obtains later results. A cold unknown or a confirmed missing result
never produces a check. A previous verified location survives stale/unavailable
refreshes until a newer verified observation replaces it. Each arrived row
has an image-semantic green check with accessible name In clan. Clan headings
show N of M in clan or All M in clan. Main now precedes Lazy in the existing pool
role settings, without mutating the received array or changing save behavior.

Before prompt 102, the final guarded backend had 5,840 passed/71 skipped/253 subtests; frontend
1,409 passed/251 files; TypeScript/isolated build pass. Four focused HTTP/pure-rule
cases (eight subtests), the inherited publication/privacy cases, and seventeen
focused UI cases pass. Required war-reminder validation passed213 backend cases
(one skipped),35 frontend cases and build. Dropping the hosting rule and allowing
unknown checks both fail genuine existing assertions; no collection failures
were counted as kills. That initial full run's four inherited response-contract
failures were corrected by keeping the response minimal and updating the new
status expectation; the final frozen backend run passed. An intermediate run
was intentionally stopped before the domain/storage boundary cleanup.

Disconnected full-app fixtures cover member assignments, Compare and Declaration
at320/360/390/1440. Checks assert two owned clans, accessible checks/counts,
current non-family hosting locations without an Outside family badge, true
outside badges, no page overflow/JS errors and no feature writes. Long names,
symbols and escaped angle brackets are included. Narrow/wide screenshots are
visually reviewed. Existing Refresh/Open Clan controls and selection/navigation
are reused; this is a scoped status/reflow review under the dashboard interaction
standard, not a complete assistive-technology or real-phone certification.

The staff fixture intentionally includes unavailable location/profile/bridge
services, with visible unavailable/cached warnings. Its figures do not certify
live provider freshness or healthy production integrations. Its original supposed
outside sample was itself configured as a host; a genuinely external tag was
seeded for the positive badge check. No real role, nickname, signup, message,
DM link or external clan link was changed or opened. No activation occurred.

## Declaration rows

The published roster still determines readiness, in-clan counts and ping targets.
A member present in a clan that the draft assigns them to, but the publication
does not, is listed as “Moved here · not published yet.” These neutral rows have
a separate unpublished count; the existing intruder count remains equal to its
extras array length. Moving an account out in the draft does not invalidate its
published placement. No notification path or published basis changed.

One existing DeclarationMemberMarks renderer groups resolved linked members
across low-TH, filler, intruder and unpublished lists within a clan. Each person
has one shared DiscordIdentity and one DM link; each account retains its context
and independent Filler control. Unlinked accounts stay individual. The existing
optional, bounded identity batch now includes unpublished rows; unavailable or
nonmember directory entries retain the existing no-guessed-identity behavior.
No additional per-account provider requests were added. Obsolete category-only
disclosures and styles were removed.

Copy mentions had been hidden when a clan met its war-size threshold. Prompt
102's removal of the page-wide unavailable guard also exposed a pre-existing
classification error: `!arrived` included unknown/checking accounts. Prompt 103
corrects this to the shared location helper's `missing` state. Only accounts
verified elsewhere (including confirmed clanless accounts) enter Copy mentions
or “Can't mention.” The actual clipboard text is asserted for mixed verified,
unknown, linked and unlinked rows. An all-unknown or entirely unlinked late list
keeps Copy disabled. The war-ready gate stays removed. Native sending and the
published roster basis are unchanged. The offline bridge message says: “The bot
is restarting or offline. Refresh status in a minute.”

Prompt 102 checks: 46 focused UI cases and 19 focused backend cases pass. Full
frontend: 1,416 passed across 251 files; TypeScript and isolated production build
pass. The draft-moved-as-intruder mutant fails the HTTP assertion (3 versus 2),
with no collection or fixture error counted as a kill. Required war reminders:
213 backend passed, one skipped; 35 frontend passed and build. Full combined backend: 5,841 passed, 71 skipped and 253 subtests. All 5,912
collected nodes across 399 files ran exactly once in three disjoint file groups.
The earlier single-process attempt ended with SIGTERM at 41% without a failure
report, so it was not counted as a pass. The initial sandbox attempt was also
interrupted; final groups permitted isolated loopback HTTP while blocking
external networking. The final identity-batch assertion was additionally rerun
in the 19 focused backend cases.

Disconnected row fixtures at 320/360/390/1440 assert one identity/DM for three
accounts, individual unlinked rows, escaped text, neutral moved styling, separate
counts, same-line DM/Filler controls, 44px targets and no overflow or JS errors.
Each fake PATCH targets only its selected account and updates on its receipt;
this is not evidence of a production write. Phone and desktop screenshots were
visually reviewed. The inherited global DM margin was overridden locally after
the initial alignment measurement exposed it. No real DM link was opened.

## Prompt 103 review corrections

MemberAssignments reuses mergeComparisonLocations, with per-season records and
pruning to the currently returned accounts. Equal/older timestamps cannot erase
a newer observation; missing timestamps cannot replace verified locations. A
newer confirmed move clears the check, including when the backend status string
alone would be misleading. Changing seasons clears prior records. Cold unknown
headings show “11 accounts,” then “8 of 11 in clan” once eight arrivals are known;
zero in-clan counts appear only with confirmed results rather than unknowns.

Unpublished moved rows omit the redundant “Assigned to” line. The filler browser
harness now targets the combined disclosure, keeps it open and checks neutral
zero-intruder summaries while low-TH/filler rows remain visible. New survivor
assertions cover the separate top-line unpublished count, unpublished-only
assigned and extra-only hosts in the extras filter, and rostered low-TH/marked
filler rows staying unflagged.

The dedicated final member preview fixes its fixture season to 4 and supports
isolated arrived/stale/elsewhere/unknown transitions. The browser demonstrated
retained checks across expiry, clearing after a confirmed move, and cold unknown
account headings without overflow. It was reset to arrived for review. No live
provider freshness, message delivery or production write is certified.

Final prompt 103 validation: backend 5,842 passed/71 skipped/253 subtests across
all 5,913 nodes in 399 files; frontend 1,421 passed/251 files; TypeScript, build
and required war reminders (213 backend/one skipped, 35 frontend/build) pass.
Three new genuine mutants fail their assertions: unknown locations in copied
mentions, forgetting verified locations on refresh, and falsely flagging a
rostered low-TH/filler row. The prior false-arrival-check mutant was also rerun
and killed after the merge change. Source was not mutated on disk. Four-width
grouped/integrated layouts and all twelve filler size/width states pass. Narrow
and wide final screenshots were visually reviewed. Served hashes accompany READY.
Initial full checks exposed four inherited exact-response assertions that needed
to validate the deliberate verified-location projection, plus an inherited
frontend assertion that incorrectly treated unavailable data as late. Those
contracts now retain exact core/privacy checks and explicitly validate the new
fields. The initial helper return type needed a TypeScript union correction.
These initial failures are retained in evidence and not called passing gates.

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
arrival rule as Declaration. The response adds only arrival_status, rather than
exposing the working lookup records or other users' accounts. No new polling or
per-row browser requests were added; existing visible-view refresh obtains later
results. Unknown/stale/missing statuses never produce a check. Each arrived row
has an image-semantic green check with accessible name In clan. Clan headings
show N of M in clan or All M in clan. Main now precedes Lazy in the existing pool
role settings, without mutating the received array or changing save behavior.

Validation: final guarded backend5,840 passed/71 skipped/253 subtests; frontend
1,409 passed/251 files; TypeScript/isolated build pass. Four focused HTTP/pure-rule
cases (eight subtests), the inherited publication/privacy cases, and seventeen
focused UI cases pass. Required war-reminder validation passed213 backend cases
(one skipped),35 frontend cases and build. Dropping the hosting rule and allowing
unknown checks both fail genuine existing assertions; no collection failures
were counted as kills. The initial full run's four inherited response-contract
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

Copy mentions had been hidden when a clan met its war-size threshold and disabled
when another location was unavailable, even with known linked late members. It
now remains available whenever the published clan has linked late mentions. A
confirmed-empty or entirely unlinked late list disables it. This changes copying,
not sending, and does not infer a mention for an unknown location. The offline
bridge message now says: “The bot is restarting or offline. Refresh status in a
minute.”

Prompt 102 checks: 46 focused UI cases and 19 focused backend cases pass. Full
frontend: 1,416 passed across 251 files; TypeScript and isolated production build
pass. The draft-moved-as-intruder mutant fails the HTTP assertion (3 versus 2),
with no collection or fixture error counted as a kill. Required war reminders:
213 backend passed, one skipped; 35 frontend passed and build. Full combined
backend completion is recorded with the READY handoff.

Disconnected row fixtures at 320/360/390/1440 assert one identity/DM for three
accounts, individual unlinked rows, escaped text, neutral moved styling, separate
counts, same-line DM/Filler controls, 44px targets and no overflow or JS errors.
Each fake PATCH targets only its selected account and updates on its receipt;
this is not evidence of a production write. Phone and desktop screenshots were
visually reviewed. The inherited global DM margin was overridden locally after
the initial alignment measurement exposed it. No real DM link was opened.

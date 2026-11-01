# Hosting locations and member assignment checks

Prompts100/101 are development scope. Merge/release is held until Ruggie's
explicit approval; PR140's approval does not authorize this separate release.
There is no bot change or migration.

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

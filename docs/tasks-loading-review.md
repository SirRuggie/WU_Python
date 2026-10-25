# Tasks loading review — 2026-10-25

The Tasks page previously waited for a complete snapshot before rendering any
activity. Account reads and history preceded several activity reads; the blocked
war view ran after the other views. Slow official API calls could therefore hold
the request beyond the reverse proxy deadline. A stalled account batch also
discarded successful player reads.

## Change

- Authenticated background polling returns promptly and shares one in-flight job
  per user, with a global active-job limit. The original endpoint response remains
  supported for existing clients.
- War, CWL, Raids, private-war checks and Games publish independently. Unknown or
  failed sections remain explicitly unavailable, never an all-clear result.
- Player reads preserve completed accounts after a 20-second batch budget and
  cancel unfinished work. Incomplete results identify missing account checks.
- Polling stops on completion, failure or unmount; hidden pages pause polling.
  Only completed snapshots enter the existing browser cache, without Games scores.
- No notification delivery, permissions, roster writes or stored player links change.

## Verification

- 129 targeted backend tests passed: Tasks, Games, FWA, shared dashboard/history,
  and push regressions. New cases cover early section delivery, shared jobs,
  terminal errors, unauthenticated access and partial-account cancellation.
- 333 frontend tests passed; production build passed. New tests cover incremental
  results, terminal failure and ignoring late responses after unmount.
- Isolated browser sample at 390px showed War results while CWL remained pending,
  and the refresh control recovered after completion. Desktop 1280px and narrow
  320px layouts were inspected; no page horizontal overflow at 320px. Activity
  tabs intentionally scroll within their own container.
- Read-only live owner check: Games returned around 20.6 seconds with five completed
  accounts; official API activity sections timed out around 55.4 seconds. A separate
  direct official player request also exceeded its 12-second timeout. This is real
  upstream latency in addition to the former whole-page loading problem; this
  change does not guarantee fresh results during an upstream outage.
- No live messages or test notifications were sent. Browser tests used isolated
  sample data and do not prove live notification delivery.

## Deployment

Implementation `9be3cdc` pushed to main and deployed to the dashboard service.
Runtime import passed; service active with zero restarts. Public Tasks and other
checked dashboard routes returned 200; served entry JS, CSS and Tasks chunk matched
the build. Unauthenticated Tasks requests returned 401; invalid login callback
returned 403. Production fixtures remain disabled.

## Follow-up: unavailable activities after first fix

The first deployment did not resolve live activity availability. Further review
found a shared request queue could allow stalled War reads to block CWL and Raids;
the remaining whole-clan gather also discarded completed clans at its timeout.

The follow-up gives each of four activity builders two concurrent request slots
(eight total), preserves finished clan results within an eight-second batch budget,
and cancels unfinished requests, including queued work. Player batches have an
eight-second limit and individual player requests release their slot after three
seconds. These limits apply to interactive Tasks; other callers retain their
existing behavior. Failed snapshots expire after 15 seconds instead of 60.
A failed or incomplete check no longer shows the green successful-check status.

Verification includes 134 targeted backend tests, 334 frontend tests, the war
reminder validation gate (186 backend passed, one skipped; 32 frontend passed),
and the production build. Additional tests exercise real view builders with a
stalled clan, queue starvation, cancellation and partial rows. Isolated mobile
390px and desktop 1280px previews retained War results while Raids failed and
showed the incomplete global status.

Live read-only testing used authenticated HTTP requests against an isolated app
with the real providers and owner's linked accounts, without writing production
sessions or data. Requests returned progress in milliseconds; full checks took
about 16–17 seconds, including usable War rows and Games scores in some runs.
Coverage remained partial. Direct authenticated curl and aiohttp probes outside
the app confirmed player/clan/raid endpoint timeouts (one player exceeded 25s),
while locations returned 200 around 0.15s and a war read intermittently succeeded.
Both DNS-resolved official API addresses were tested; no alternate provider or
credential destination was introduced. This proves a live-data dependency problem
in addition to the fixed application bugs, not complete live recovery. Do not mark
Tasks fully resolved until all expected linked accounts and activities load.

Follow-up deployed revision `2191a2a`: runtime imports passed, web service active
with zero restarts, public routes 200 and served entry/Tasks assets matched the
build. Protected endpoints remained 401 and invalid OAuth callback 403. An
additional 163 shared Tasks/account/maintenance tests passed. Live browser reached
the correct sign-in destination; no signed-in browser session was available, so
real account checks used the isolated authenticated HTTP app described above.

## Failure-screen cleanup

The subsequent screenshot exposed duplicate error output from four render paths.
A single activity-status component now owns that notice, with deduplicated details
behind a native disclosure. Empty failed results do not also render an empty-state
card or misleading zero-count badge. Search/sort are omitted when there are no
results to filter; existing searches remain editable. Regular-war diagnostics no
longer appear as a separate warning in CWL. Actual partial rows remain visible.

336 frontend tests and the build passed. The screenshot's repeated messages were
reproduced in an isolated mobile fixture; the notice rendered once, details opened
and each diagnostic appeared once. Direct player requests still timed out with a
50-second allowance while a current-war request returned 200 in 0.18s. Compression,
a cache-busting query, and smaller TCP segments did not restore the failed player
lookup. No host networking settings or API provider were changed. These UI fixes
are not evidence of live data recovery; the unresolved dependency remains recorded.

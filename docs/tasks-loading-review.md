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

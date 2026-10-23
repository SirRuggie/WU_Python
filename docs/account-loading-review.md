# Progressive account loading — October 23, 2026

## Problem and scope

Account screens waited for every linked player's live lookup before showing the
account list. Home also waited for all account, signup, assignment and season reads;
Search waited for both accounts and family clans. One slow player could delay all
visible accounts. This follow-up covers Home, Search and member Signups. The earlier
staff roster fix is documented separately in `roster-loading-review.md`.

## Behavior and safety boundaries

The frontend opts into a progressive read using `background=1`. The existing URLs
and synchronous responses remain compatible for older clients. Each authenticated
member has one shared background job across the progressive linked-account and
dashboard-account endpoints. Ready player records appear while other lookups run;
completed reads are reused for 30 seconds. Explicit refresh rechecks links. Requests
never accept an arbitrary member ID, and cached display data is never used by
`_accounts` or signup mutation authorization.

Reads have a 120-second job deadline, per-member concurrency of five and shared
concurrency of ten. One member's large account collection cannot occupy every slot.
Client polling is sequential, pauses after its initial read while hidden, and has a
135-second deadline. Abandoned views reject late responses. Application shutdown
cancels and drains provider children. Completed snapshots expire and are capped at
1024 entries; active jobs are retained until their bounded completion. Failures use
short-lived results and explicit retry, not repeated automatic job restarts. Partial
refreshes log loaded/expected counts without logging credentials or account data.

A failure preserves available information and shows an error; it never becomes a
successful empty account list. The Home display cache is written only after a
complete successful load. During refresh, existing visible selections remain until
a complete successful link check permits removing absent accounts. Account selection
and signup writes remain disabled while reads are incomplete or failed. All signup
writes still refresh links and current game data through the existing validation
path, including Main/FWA rules, pool conflicts and season availability. No persistent
schema, signup records, placement data or permission model changed.

## Red-team checks

111 backend tests passed, covering progressive reads, existing dashboard-account
compatibility, signup foundation/policy/entry, roster behavior, access scopes,
transport retries and architecture boundaries. Added cases cover:

- Fast accounts returned while another player is blocked; duplicate/forced reads
  share the active job across endpoints.
- A member with 30 blocked player reads does not prevent another member loading.
- Partial provider failure, unavailable link discovery, mismatched player identity,
  explicit refresh recovery, unlink removal, and member-cache isolation.
- Unauthenticated access cannot initialize a job; an old display cache cannot
  authorize signup after the live link has been removed.
- Shutdown cancels the job and its pending player requests.

327 frontend tests passed and the TypeScript/Vite build passed. New tests cover
progressive callbacks, one-time forced refresh, incomplete-read errors, navigation
cancellation, denied access, hidden-page polling/deadline, and retention/removal of
visible account selections at the correct completion boundary.

Isolated browser checks used fictional accounts at desktop, 320px and 390px.
Home displayed the fast account while loading, then enabled selection on completion.
Signups displayed partial account details with selection/Continue disabled and
restored controls after completion. Search displayed completed results while still
loading and retained results with a retry notice on a simulated failure. The final
build retained saved Home rows during refresh. Narrow layouts had no horizontal
document overflow. Browser checks identified a transient disappearing selected row;
the final merge helper fixes it, with a dedicated regression test. No live signups,
links, Discord messages or permissions were changed as tests.

These are controlled slow/failing-provider checks, not an assurance of instantaneous
live API responses or a measured speed guarantee on the owner's phone. Link discovery
itself must finish before previously unknown accounts can be shown. Existing aiohttp
application-key warnings remain.

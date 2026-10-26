# Wars clarity and membership review — 2026-10-26

## Behavior

Wars defaults to the current clans of linked accounts. Staff can explicitly select
Show all clans (the existing authorized family directory), then Show my clans.
This does not grant access to arbitrary clans or change dashboard permissions.
The previous data path already used current membership, but reused player data for
ten minutes. Wars now rechecks membership after 60 seconds; the one-minute endpoint
cache and upstream game cache can still add delay. Other task/raid callers retain
their existing cache defaults. No live account-level reproduction established that
cache age was the sole cause of the reported unrelated clan.

Recent CWL clans use existing clan-history candidates, and are displayed only when
an active/preparation/awaiting-result war confirms a linked account on that clan's
side. Opponent membership never qualifies. Such clans appear only under CWL, with
an explicit hosting-clan explanation. Failed history/verification produces a warning;
unknown data is not treated as a completed war. Discovery remains limited by the
existing history tracker; a never-observed hosting clan cannot be inferred.

Compact cards put matchups, official clan badges when supplied, scores, countdowns,
and personal remaining attacks together. Exact dates, clan links and task handoff
remain under Details. No-current-war and ended cards start collapsed; private and
failed lookups remain visible. Events and signup/roster workflows were not redesigned.

## Implementation and adversarial review

Shared game projections remain in utils; HTTP scope authorization stays in cwl_web.
No storage migration, notification sends, or roster writes. Personal account rows
are request-specific projections and are never stored in shared game-object caches.
The recent-clan loader is now public and its Tasks/push callers were updated. A
missed push import was caught by regression tests and corrected before deployment.
Regular and CWL overview reads now run concurrently with separate 10-second limits.

154 affected backend tests passed: membership, cache freshness without changing
Tasks defaults, current-user isolation, unauthenticated/member/staff boundaries,
parallel read coalescing, unrelated and opponent-only recent clans, CWL participants
who changed clans, partial reads, task budgets, push behavior and architecture.
342 frontend tests passed; TypeScript/Vite production build passed. Existing aiohttp
AppKey/deprecation warnings remain.

Isolated rendered browser checks used fictional data at 1280, 390 and 320px:
long names, score/timing hierarchy, no horizontal document overflow, staff scope
round-trip, member control exclusion, inactive disclosure, Details and task handoff.
A failed refresh retained labeled last-known results. Native buttons and disclosures
retain keyboard behavior and 44px controls. Screenshot inspection is not a full
screen-reader certification or a physical-phone test. No live Discord messages or
member records were modified. Live provider success is not proven by fixture tests.

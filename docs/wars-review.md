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

## Owner follow-up: private war logs

Private-war-log cards are now excluded from both war tabs, including staff family
view, at the owner's request. This supersedes the private-card visibility rule
above; failed lookups remain visible. Empty-state wording acknowledges hidden logs
without claiming their wars have ended. 343 frontend tests and production build
passed. A read-only account-link investigation confirmed the reported unexpected
account is returned for the owner by both upstream providers; no links were edited.

## Optional lineups and attack log — October 26

Added a read-only, scope-checked current-war detail endpoint through a public shared
provider helper. No database schema, signup, roster, assignment, or notification
write behavior changed. Access is checked per request; own clans require current
linked membership, or recent CWL hosting plus verified own-side participation.
Family scope requires staff permission and the family directory allowlist.

Details fetch only while expanded. The panel uses twenty-row pages, separate lineup
and attack views, clan/opponent selectors and side labels, and linked-account
markers. Existing compact matchup, private-log exclusion, dates, clan link, and
Tasks handoff remain. War identity prevents details attaching to a replacement war.
Slow/cancelled responses cannot repopulate a closed panel, and access denial clears
the protected overview. Unknown statistics stay unknown; incomplete or capped data
is labeled partial. Shared game caches contain no per-user attribution.

Sol implemented the backend, Luna the UI, and a separate Sol reviewed adversarially.
Review caught and corrected clock-driven refetching, stale war IDs, incomplete data
presented as complete, invalid statistics, duplicate attack keys, and opponent-side
ownership attribution. Final automated checks: 64 relevant backend tests, 367
frontend tests, TypeScript and isolated Vite build. Existing aiohttp warnings remain.

Isolated browser fixtures at 320, 390, and 1280px covered closed-state zero detail
requests, opening/closing during a slow read, both lineup sides, paging, regular/CWL
switching, staff scope switching, private-clan exclusion, partial logs, stale-war
refresh messaging, and clearing data on 403. Long/multilingual names wrap without
horizontal document overflow. These checks use fictional data, not live member
writes, real Discord delivery, a physical phone, or full screen-reader certification.
Provider outages and cache freshness still apply; this is current-war detail, not
historical war storage. No live messages were sent.

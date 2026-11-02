# Participation no-group follow-up release

PR #151 addresses Claude entry 341 under owner approval 337; Claude accepted it
in entries 342–343. The merged revision is
`c46097b9404ab785744493a27c41cb5498cf1ac8`, tag `participation-no-group-1`.
See [the review](participation-no-group-review.md) for the conservative 404-only
wait rule, private-war negative-cache backoff and limits of the earlier evidence.

## Validation

71 focused integration tests and five strengthened final cases passed. The full
guarded backend matrix passed 5,861 tests with 71 optional skips and 253 subtests.
Four genuine mutations failed behavior tests. Required war-reminder checks
passed 213 backend tests, one optional skip, 35 frontend tests and build. The
unchanged frontend build matches the existing entry and hash. No production
Check Clash, provider probe, notification, role, nickname or DM action was used.

## Activation

The backend-only release completed November 2 at 03:53:25 UTC. Backend PID 1837499,
invocation `b5cc6e708cb449d69fc8350b79b3e94c`, runs the immutable tagged archive.
Exactly one backend restart occurred in this activation. At that point the
frontend stayed at immutable `0f86e9f` and the bot stayed PID 1672182 at `1af386e`. No bot restart, frontend switch, rollback
or database restore occurred.

Fresh SQLite and Mongo backups passed isolated test restore, canonical recovery
and local role-progress reconciliation. Startup rehearsal preserved the SQLite
copy. Exact protected counts remained 3,715 active strikes, 306 accounts, 584
strike profiles, 279 eligible and 479 member profiles, with exact digests and
streaks. Staff transitions and departure exceptions were empty before/during.
The no-queued gate, imports with network blocked, immutable 1,996-file archive,
mocked rollback, readiness, startup journal and unrelated configuration passed.

The public entry remains `index-BzHhELG4.js`, SHA256
`ead29373187f63adbd9c0fcc7be098bbab5346655b19a9860c431ff97cef2177`.
Affected feature hashes and the unchanged frontend target were checked publicly.
The prior backend and the existing frontend remain available for code rollback;
no data restore is part of rollback.

## Ordinary capture and production smoke

The first naturally scheduled capture at 04:07:27 UTC logged three `no_group`
HTTP404 results and seven other `unavailable` results without an HTTP status.
The persisted status stayed `unavailable` with its cached-results warning. The
new wait line was not observed live; the seven unclassified failures were not
assumed normal and no zero-count success was fabricated. Claude346 reviewed
those categories and confirmed that this conservative result closed the gate.
The initial helper reported REVIEW; that result is preserved, not relabeled PASS.

The two private current-war endpoints each logged one403 across the observed
15-minute interval, rather than the earlier roughly55-second repetition. This
supports the negative-cache backoff; it does not establish a cause for the
previous isolated Push TimeoutError, whose stage was not logged.

Claude347 independently confirmed site200 and healthy runtime after a later
Mongo-lifecycle attempt rolled back to this backend revision. No live visual
wait-line, real member view, role action, nickname action or notification was
verified here. Later lifecycle forward/rollback restarts are separate from this
release's one backend restart and are recorded in that release audit. Accepted
PR154 adds safe reason codes for a future ordinary capture; it is not part of
this tag and has not been activated by this document.

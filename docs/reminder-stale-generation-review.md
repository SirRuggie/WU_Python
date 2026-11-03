# A due reminder always leaves an outcome after a settings save

This follow-up starts from deployed PR195 (`a5d59a5f`). A roster-copy or other
revision-raising save can happen after a scheduled callback was cached but before
it fires. Previously the callback detected its stale generation, reinstalled the
schedule, and deleted the now-past job without sending or recording history.
The unchanged baseline reproduces zero sends and zero records; the no-save
control sends once, and the existing restart path already records a visible skip.

The live installer now offers only persisted, due, ordinary scheduled reminders
with an old generation to the existing PR189 recovery decision. It retains the
generation fence: a settings change is conservatively recorded as
`Skipped: settings changed`, matching restart behavior. It never substitutes new
copy or a new generation into an old callback. Current-generation ordinary
callbacks, manual jobs and roster sends retain their scheduling rules. A retry
from an old generation is retired with a visible settings-changed skip; it is
never sent with the new generation, even if its retry time is still ahead.
PR189's six-hour eligibility, claims, ledger, uncertainty and snapshot-bound
history/deletion remain the storage owner. An old scheduled skip does not consume
a later ordinary occurrence whose time was moved into the future.

Every local campaign send invocation registers an opaque ownership token before
its first await and removes only that token in `finally`. These tokens cover
manual and staff-request owners of the same occurrence claim as well as scheduled
callbacks. Recovery defers matching active rows, checks again after campaign/state
reads yield, and retains the old row until the send finishes. It does not report
uncertainty beside a still-running POST. Tokens remain visible across in-process
runtime-ID changes; an old callback's cleanup cannot remove a new callback's
ownership. No global lock is held over Discord transport. A real process restart
has no local activity and continues to use the durable PR189 uncertainty policy.
Lease expiry alone is never treated as proof that a POST stopped.

The second requested investigation is test-only. Sixteen defaults-materialization
interleavings exercise both sides of the roster metadata read, marked/unmarked
copy, missing/receipt-only cycle rows and current-only/future-month saves. They
compare subsequent defaults and opposite-pool saves with a valid serial-operation
reference, pinning current/future text, unrelated fields and delivery receipts.
They preserve the existing roster-copy materialization behavior, so that save
path and its CAS are unchanged. The catch-up report ledger changes below.
This is evidence for this window, not a general distributed-concurrency proof.

## Due-specific skip reports (review 156)

Review found that an initial skip consumed the whole occurrence in the catch-up
ledger. A move from noon to 13:00 therefore installed normally but vanished if the
bot restarted at 13:05, or if another save made that second callback stale. Both
cases were reproduced as genuine failing tests before this correction.

The existing campaign storage owner now records a skipped due time as an
occurrence plus a canonical UTC due-time key in the existing
`catchup_reported_occurrences` array. Its history entry carries `catchup_scope:
"due"`. The same due time is atomically deduplicated; a different time can send
late under the existing six-hour policy or receive its own visible skip. Receipt
history pruning does not forget a reported due time. A move back to an already
skipped original time retains that report without adding a duplicate or sending
it again. Sent, failed and uncertain outcomes keep their occurrence-wide fence.
Legacy unscoped receipt markers remain conservative; no backfill or inference
from missing history changes old state. No collection or schema migration is
needed, and saved copy is unaffected.

Retiring an old-generation retry uses the existing snapshot deletion owner, with
an explicit validated retry snapshot and failure count in its delete condition.
A replacement generation, due time, count, status or job kind survives. This does
not make retries eligible for catch-up sending. A manual POST held across a move
and then failing leaves a recoverable old snapshot; the next sync installs the
moved job. The redundant activity check before awaited state reads was removed;
the check after those reads covers both catch-up and local send owners.

Current delta checks include the A/B regressions, moving back, equivalent UTC
keys, history pruning, concurrent duplicate reports, legacy/unknown outcome
fences, retired retry replacement snapshots and failed manual-owner repair.
Twelve in-memory mutants (seven activity/fence and five due-report/retry cases)
fail genuine assertions. An owned real Mongo run passes 15 catch-up/storage
checks, including twelve simultaneous same-due report attempts with one winner.
The delta focused suite passes 140 cases; broader regressions pass 245 cases
and three subtests. The unchanged war check passes 213 backend cases/one skip,
35 frontend cases, TypeScript and build. The frozen rework passes 6,809 backend
cases, 123 skips and 270 subtests in 592.46 seconds. Its exact artifact boots
successfully with all 51 production route mappings on an owned Mongo URI, the
real owner, retained SQLite copy, native pool ping and twelve bound module
origins; config returns 200 and unauthenticated auth returns 401. External
transport is blocked before application imports and Healthchecks values are
empty. Owned Mongo, data and artifact export are removed afterward. These are
isolated startup and fake-delivery checks, not live Discord delivery evidence.

## Original validation before review 156 (historical)


The focused recovery/race suite passes 119 cases. The broader unchanged PR177,
PR183 and PR189 regressions pass 224 cases and three subtests, including isolated
HTTP authorization/ownership tests. Seven in-memory behavior mutants fail genuine
assertions: silent retirement, live-owner deferral, the post-read activity check,
token ownership, runtime-ID isolation, generation fencing and retained-row handling.
No mutant changes tracked source on disk.

Regressions cover duplicate callbacks with reconcile/restart, ordinary and manual
POSTs held across a save, a manual owner entering during a state read, cancellation
with an unknown durable claim, overlapping tokens and an in-process runtime
change. A changed/disabled/paused/too-old due job has history; a moved future job
and a concurrently replaced persisted/scheduler job remain usable without a
second old-due report. Current-generation sends retain their pre-existing path.

The frozen full backend passes 6,788 cases with 122 skips and 270 subtests in
582.41 seconds. The required war-reminder check passes 213 backend cases/one skip,
35 frontend cases, TypeScript and build. The exact frozen artifact boots with all
51 production route mappings on a new owned Mongo URI, the real durability owner,
a retained SQLite copy and production flags. Its native async pool ping succeeds;
config returns 200 and unauthenticated auth returns 401. Twelve module origins,
including the changed reminder task and its source hash, bind to that artifact.
DNS, connect and datagrams are guarded before app imports, and Healthchecks values
are disabled. Owned Mongo, temporary data and the export are removed afterward.

Frontend source equals the deployed PR195 frontend; the boot borrows its immutable
assets read-only. No new full frontend or layout campaign is claimed for this
backend-only change. Routes, permissions, storage schema and production
configuration do not change. All sends are fake: no live Discord acceptance or
delivery is proven. Fresh operational gates and reviewer acceptance remain
required before deployment.

Two earlier full runs failed due to the private test guard: it removed an explicit
empty Mongo URI sentinel, then blocked offline numeric-IP parsing. Shaka530/531
reviewed the corrections; 22 unchanged targeted checks pass, followed by the clean
full run. Product assertions and timeouts were not weakened. Failed runs and guard
proposals remain in local evidence. The earliest child guard blocked connections
but did not block DNS, so DNS attempts cannot be ruled out for that failed attempt.

The original red reproduction, the invalid literal future-copy oracle and its
serial-reference correction, and an overly strict current-generation row-retention
assertion are retained locally. The latter fails on unchanged deployed source too;
the corrected assertion checks the relevant no-uncertainty/one-Sent behavior.
An initial broader sandbox run stopped after 209 passes because socket creation
was denied before isolated HTTP fixtures could run. The unchanged guarded host run
then passed all 224. No code change was made to hide that environment restriction.

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
callbacks, manual jobs, retries and roster sends retain their scheduling rules.
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
They preserve the existing behavior, so campaign storage and its CAS are unchanged.
This is evidence for this window, not a general distributed-concurrency proof.

## Validation

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

Full backend, the required war-reminder check and production-shaped boot are still
pending before READY. No frontend source, routes, permissions, storage schema or
production configuration changes. All sends are fake; these tests do not prove
Discord acceptance or live delivery. No notification, provider probe, forced job,
production database operation or deployment is performed by this local work.

The original red reproduction, the invalid literal future-copy oracle and its
serial-reference correction, and an overly strict current-generation row-retention
assertion are retained locally. The latter fails on unchanged deployed source too;
the corrected assertion checks the relevant no-uncertainty/one-Sent behavior.
An initial broader sandbox run stopped after 209 passes because socket creation
was denied before isolated HTTP fixtures could run. The unchanged guarded host run
then passed all 224. No code change was made to hide that environment restriction.

# Background Filler ticks (145)

Frontend only. Release is held for Ruggie's preview approval. This batch has not
pressed a production Filler tick or changed any backend endpoint/revision rule.

## Reproduction

The baseline frontend at fe67907b was built unchanged into a private fixture.
Two fast row ticks reached the actual existing mark endpoint on an owned SQLite
copy with the same supplied revision: 10 and 10. The responses were 200 and 409;
the maximum number of outstanding writes was two. Before/after table hashes
changed only roster marks, their audits, global revisions and Undo receipts.
No unrelated table changed. The old per-row error could disappear after the
first saved mark regrouped the list. Earlier failed visual assertions and the
successful direct wire/count proof are retained under `.local/p145-baseline-*`.
An independent React/CAS regression also reproduces revisions 9/9 and one 409.

## Behavior

One queue belongs to the Declaration page. List and Details use the same
RosterFillerCheckbox and queue object, passed through the existing staff-details
request. Mutable queue state holds the newest confirmed global revision and each
row's saved state, desired state and mark revision. React render revisions do not
drive queued requests. New authoritative observations cannot replace a newer
confirmed mark revision.

Ticks show immediately; pending rows say Saving while other rows remain enabled.
Only one request runs at a time. Unsent same-row intents coalesce at the latest
tap position. A tick followed by an untick before any send needs no request;
a reversal during an active save waits for its confirmation and uses the new
mark revision. Every mutation comes from an explicit tick or existing Undo.

Confirmed marks are applied to Declaration data in one flush. Grouping/order
stays unchanged while the queue runs, then `patchDeclarationMarks` regroups once.
The last confirmed mark remains the only available Undo in both page and Details.
Undo, location Refresh and Details Reload wait while marks are queued; an explicit
Undo also blocks new ticks until it finishes. Undo uses the newest queue revision.
A confirmed Undo remains confirmed even if its follow-up read fails.

A failure halts the queue, discards unsent intents and restores each affected row
to its last confirmed state. Confirmed rows remain saved. The page lists every
unsaved row and shows a short count; raw server Reference text is omitted here.
There is no automatic retry. A network failure or the bounded 45-second write
deadline may have an unknown outcome: refresh to learn what reached the server.
Only a successful explicit Refresh clears the halted queue; background reads
cannot hide its failure. Queued work never starts after the page unmounts. An
already-started request can still have committed before its connection is aborted.

Existing onWorking/onDirty guards include the queue. Closing Details does not
throw away the page's queue; leaving the page disposes it and aborts the active
client request without replaying it. Other staff or another tab may legitimately
cause a 409; the client keeps the server's concurrency check intact.

## Other controls inspected (report only)

- `RosterFillerCheckbox.tsx`: standalone mode still uses a per-row lock and its
  supplied revision. Current standalone use is the single RosterPlayerDialog,
  not a second multi-row list. Independently embedding several standalone
  instances would retain the baseline risk; no broader conversion was made.
- `RosterPlayerDialog.tsx`: the Keep placement checkbox saves immediately, but
  it is in one Details panel and StaffDetailsPanel's shared pending/busy guard
  blocks overlapping writes. No second same-page row control was found.
- `RosterAccountCard.tsx` / `RosterWorkspace.tsx`: account ticks select local
  rows for one explicit bulk action; they do not PATCH a revision per tick.
- `members/MemberRow.tsx`, `BonusCandidateReview.tsx`, and signup selection rows:
  local selection precedes an explicit action rather than one roster write per tick.
- `ModerationCategoryCard.tsx`: switches edit the local draft and are saved by the
  existing page-level Save action; these protected feature files were not edited.

This is a scoped source inspection, not a claim that every dashboard control or
cross-tab interaction has been tested.

## Browser transport limitation

A post-commit socket close was tested without Playwright routing. JavaScript made
two fetch calls, but Chromium made three HTTP attempts: 200, 200, 409. The browser
resent the second request with the identical CAS revision; the backend refused
that duplicate and no extra state change occurred. There is no application retry,
including after 409. A frontend-only queue cannot promise one physical HTTP attempt
under transport retransmission. Refresh is authoritative after an unknown outcome;
the socket-close case can surface as a conflict after the first attempt committed.
The healthy ten-row case has exactly ten HTTP attempts and maximum one outstanding.
No backend check, endpoint or retry mechanism was changed for this limitation.

## Navigation cleanup regression

The actual browser unmount test found a stale guard: PingPanel cleanup observed
the disposed queue's still-settling promise as working. An actual PingPanel/page-
hook regression fails before the fix and passes after it. A disposed queue now
reports no active page work immediately, while its already-started request may
still settle. No queued request starts after disposal.

## Final validation

Frozen runtime source `1a77140391bfbede22b124dd8e93b0e29fcb63f7` passes
1576 frontend tests across 270 files, 60 affected tests, TypeScript, the main
build, and the isolated preview build/typecheck. Five genuine mutants fail
behavior assertions: stale revision, one automatic retry, parallel sends,
continuing after failure, and sending after unmount. An initial unbounded-retry
mutant timed out and is not counted.

Actual browser checks against owned SQLite cover ten rapid serial saves,
list/Details reversals, Undo, and 409/401/403/504 refusals. Confirmed rows stay
saved; the remaining queue stops. Unrelated table hashes remain unchanged.
The actual 45-second held-ack deadline finished in 45.347 seconds: Refresh learned
two committed marks, the third remained unsent, and nothing replayed. Navigation
cleanup clears the guard and starts no later queued write. At 360 and 1440 pixels,
layout, readable pending states, 44-pixel controls and keyboard Space/focus checks
pass; pending-row screenshots were visually reviewed at both widths.

Adversarial checks cover stale global/per-row revisions, same-row coalescing,
malformed acknowledgements, concurrent observations, mixed Details/list intents,
partial and unknown outcomes, authentication/permission refusals, reciprocal
Undo/Refresh locks, and unmount/deadline races. Existing HTTP ownership and CAS
checks remain authoritative. These isolated tests do not prove production writes
or Discord delivery. The browser retransmission limitation above remains explicit.

Evidence is retained in `.local/p145-*`, including final suite/build logs,
`p145-mutants.json`, `p145-browser/success.json`, `p145-failures/known-proof.json`,
`p145-deadline/proof.json`, `p145-layout/proof.json`, and the no-routing socket probe.
Earlier failed harness/reproduction logs are retained rather than relabeled pass.

## Review fixture

Open `http://127.0.0.1:32793/` and choose **Open local test session**. This runs the
real existing mark/Undo handlers on owned persistent SQLite with synthetic read
fixtures; external network access is blocked. Saves persist locally. PID 3300970
and `.local/p145-preview/fixture.sqlite` are intentionally retained for review.
Entry `filler-queue-preview-D7Z7rwB_.js` has SHA256
`ca0892821682585fb654f78453a13ba7d2be49640e2a77be716d87b3d859e6fa`.
Fixture controls exercise refusals and lost acknowledgements without production
requests. Existing QA marks are retained; the database has not been reseeded.
Release remains held for Ruggie's preview approval.

## Prompt148 delta review

Details now offers a filler Undo only for a save to that account made while its
panel is open. Opening another account, reopening the same account, or dismissing
its receipt cannot revive an earlier page-level Undo. Saved notices name the
account. The page-level latest receipt remains available separately.

Background location reads keep ticks available. An explicit Refresh still locks
marks, and Refresh stays disabled while marks are saving. A halted queue recovers
only after both reads in a new explicit Refresh succeed; a later background read
cannot turn a failed Refresh into recovery. Explicit read outcomes have matching
request IDs, rather than inferring success from replaced data objects.

Before changing runtime code, two new assertions reproduced the wrong-account
Undo and dropped background-read tap. Final checks:72 focused tests,1588 frontend
tests across270 files, TypeScript and production build passed. Six genuine
assertion mutants were killed: lower revision replacing a newer one, missing
abort, refresh during a write, background disabling, automatic read recovering a
failed Refresh, and offering a receipt from before the panel opened. Tests also
cover latest-revision list Undo, disabled Undo/Refresh while running, guard cleanup
and late acknowledgements after disposal. No backend or policy changes were made.

The actual SQLite fixture reproduced the earlier wrong-account Undo at360/1440;
the corrected build passes320/360/390/1440 with no horizontal overflow. Narrow
Details and wide overview were visually inspected. Browser evidence and failed
harness attempts remain in `.local/p148`. The HTTP/browser retransmission limit
above still applies; these checks make no production or Discord delivery claim.

The same32793 server and SQLite remain intact. A read-only SQLite backup and
all-table counts/digests before and after the static asset refresh prove it did
not reseed or alter existing marks/revisions. All old assets were retained. New
entry `filler-queue-preview-TDbNT1E1.js` SHA256
`4ce914a851b2715750973a7bf04a1bc823ff3b474fe4915cf6a395e4ebf65704`.
Release remains held.

A real copied-SQLite held-ack/held-background-read browser regression also passed:
the second row stayed enabled and retained its tap, Refresh was disabled during
the queue, both PATCHes succeeded in order (94→95→96), and observed maximum
parallel writes was1. Evidence: `.local/p148/browser-after/background-race.json`.
This used a separate copy, not the retained32793 database. The new32793 served
entry was fetched and hash-verified after the asset-only refresh.

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

## Checkpoint validation

The full frontend at the preceding source passes 1575 checks across 270 files.
Focused queue and integration tests cover ten serial writes, latest revisions,
same-row changes, mixed list/Details controls, failure halting, unknown outcomes,
explicit refresh, disposal and Undo. Actual owned SQLite/browser checks prove the
healthy ten-row wire trace, Details/list reversals, Undo, keyboard focus and four
known refusals (409/401/403/504), with every unrelated table hash unchanged.
Five meaningful mutants are killed. An initial unbounded-retry mutant timed out
and is not counted; the one-retry mutant fails actual assertions. The corrected
disposal source still needs its final full suite/build and repeated unmount gate.
The 45-second held-ack case has exercised a committed unknown outcome and learned
it through Refresh; final structured evidence is being completed. Release remains
held. No mock or fixture is evidence of production behavior or Discord delivery.

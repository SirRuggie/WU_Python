# Missed campaign reminder catch-up

A persisted scheduled campaign message due during a bot restart is decided before normal restore/sync can replace or delete its original due time. The newest eligible message per Main/Lazy pool sends once, late, within the single `MAX_CATCHUP_AGE` six-hour window. Equality is eligible at dispatch; preparation crossing the window is refused. Older eligible rows receive a skipped receipt. Original destination, role mentions, text and occurrence identity are retained.

Eligibility requires the current cycle in the campaign's configured timezone, matching generation, activated automation, no pause and an enabled message/audience. A missing pending job is not derived from schedule calculations. Signup/reminder closure uses the campaign deadline only, not SQL signup state. The native sequence-spacing guard remains authoritative: it can record `Skipped: too close to another send`, without falling back to an older message or producing a burst. Existing delivery records exclude automatic catch-up. Manual/retry delivery rules outside the explicit busy outcome below and roster rules retain their existing behavior. The future-only meaning of `schedule_synced` is unchanged; idle acknowledged reconciliation does not fetch catch-up state.

## Staff Send now and Retry during preparation

Prompt150's first fix releases only the exact unattempted catch-up claim when its pending row has been replaced. It also preserves a later worker's claim when an older preparation fails. If this finishes before the staff timer fires, the staff request sends normally once.

A separate native reproduction found the opposite ordering: the staff timer could fire while the catch-up still awaited its channel, yielding zero POSTs and zero history even though the orphaned claim was later released. Entry485 explicitly chooses the small record-only outcome rather than a durable delivery handoff fence. A queued non-roster staff request blocked by another send records one plain failed history row:

> Not sent: another send was running. Send again.

That request makes no POST and does not automatically retry or reschedule. Staff decide whether to make another request later. Nothing in this outcome clears or transfers another send's claim, removes accepted-POST uncertainty, reopens a Sent occurrence or overrides a deadline. Already known Sent state remains authoritative. Both timer orderings finish with one visible outcome: either one Sent receipt/one fake POST, or one explicit no-send receipt/zero POSTs.

A small `staff_request_id` associates a queued callback, pending row and history receipt. This is receipt ownership/deduplication metadata, not an atomic delivery handoff. Compare-and-swap cleanup preserves a newer queued request. The existing `ledger_pending` status retains a known-no-POST accounting receipt before history is written; a lost acknowledgement or restart finishes accounting without sending the notification. Duplicate callbacks and lost cleanup acknowledgements leave one history row. Malformed or wrong-scope receipts fail closed with durable state retained.

## Storage, crash boundaries and scope

`utils/cwl_campaign.py` owns new accounting queries and compare-and-swap operations. Existing scheduled pending rows are tagged with catch-up protocol 1 and `original_due_at`; original occurrence IDs remain unchanged. A durable uncertainty marker is written before entering Discord's POST. Confirmed late receipts retain actual delivery time, original time and lateness. Confirmed receipt fallback and cleanup match the observed generation, job kind, original time and status; recovery also matches the confirmed message ID. They cannot overwrite/delete a newer manual/future job or a different confirmed receipt. If fallback ownership changed, uncertainty and a review receipt/journal alert remain rather than an automatic replay.

A protocol 1 pre-effect claim can safely resume when its durable POST marker was never added. An old unversioned claim, malformed claim, lost marker acknowledgement, exception after entering POST or response without a usable message ID fails closed. The record-only busy path never clears that protection.

Additive runtime metadata includes `catchup_reported_occurrences`, `catchup_legacy_reported_jobs`, bounded `staff_not_sent_requests`, pending catch-up context and optional staff receipt IDs. Existing unfinished non-roster Manual/Retry rows with zero failures receive receipt metadata during normal restore; positive-failure automatic retries and roster jobs do not acquire this protocol. There is no SQL/bulk migration, campaign-copy rewrite, new collection, alert transport or polling loop. Skipped catch-up accounting is separate from explicit staff skip state, so it does not disable a later ordinary future schedule.

Known owned combined Main/Lazy legacy scheduled rows were separately reproduced as silently deleted by startup/sync. They now receive one idempotent plain skipped history entry before exact observed-row cleanup, including direct sync. That entry has no per-pool occurrence ID: it does not consume a valid canonical occurrence or derive/send replacement jobs. Failed history writes retain the legacy row; concurrent replacements survive cleanup. Unknown/forged scopes remain fail-closed.

New storage-owner operations use indexed `_id` point queries. The owned Mongo explain uses `_id_` and examines at most one document. **Inherited limits remain:** native restore/install still scan pending jobs, and reused `load_campaign` still scans per-guild cycle/recurring history. This is not a claim that the complete existing callgraph is bounded or that Atlas quota was measured. Delivery history and no-send receipt markers use the existing history limit.

## History and accessibility

The existing disclosure uses the actual shared history renderer: Main/Lazy, `Sent late` with actual/original time, plain skipped reasons, `Post deleted`, and neutral unavailable labels. Existing `Skipped an overdue reminder…` wording appears once. React text rendering escapes external content; no raw IDs or internal status enums are used as labels. The component does not fetch, send or edit anything.

The newest read-only synthetic preview is `http://127.0.0.1:45973/`, entry `index-CmeKNbEe.js`, SHA256 `73619f01a60c26ae5b3e6d00deb0e90cd96c1fde941ffdf56e9481b3b934bb65`. At 360/1440 the exact no-send text appears once, nine rows/eight valid timestamps have no overflow, keyboard focus is visible and Enter toggles the disclosure. Requests are same-origin GET assets only. Both screenshots were visually reviewed. Earlier 40937/43207 previews and assets remain preserved.

## Validation

Frozen runtime: `b5527a3452467bc4a6119fe97d191d5f3ec599cd`.

| Gate | Result |
| --- | --- |
| Full guarded backend | 6510 passed, 120 skipped, 267 subtests; 565.39s |
| Focused native/integration/ack/scheduler/sequence/footprint | 162 passed |
| Owned real Mongo | 14 passed; BSON snowflake IDs, independent callbacks, accepted-POST crash, receipt ownership, busy deduplication/lost ACK, uncertainty and newer requests |
| Genuine backend assertion mutants | 18 killed, including double/burst/window/pause, roster exclusion, mid-POST uncertainty gate, orphaned claim, no-history/double-history, claim/uncertainty clearing and no-send callback/recovery replay |
| Frontend | Unchanged from passing d7ca source: 1560 tests/270 files, TypeScript/build and one legacy-prefix mutation kill |
| Required war check on final runtime | 213 backend passed/1 skipped; 35 frontend and build passed |
| Exact production-shaped boot | All 51 configured routes, production flags, native pool and bot imports, real durability owner on copied SQLite/owned Mongo, external I/O blocked, config200/auth401;cleanup passed |

Boot evidence/source manifests are in `.local/p485-boot`; boot script SHA256 `462501b756c11c9c6bcf63ac681d25bf33fe65933f652bf9d3edd65b9b0ebb92`. The source export, copied SQLite and owned database were cleaned and Mongo27171 stopped. Consolidated evidence is `.local/p485-ready-evidence.json`. Earlier 6480/6485/6494 full runs and failed counterexamples are retained as earlier-source evidence, not proof of the final delta. The timer-first gap was reported despite a passing 6494 suite and was not called ready. Initial fixture/connection/socket/assertion-shape failures are retained separately from final passing results.

## Remaining limits and release

The busy request may intentionally end with zero POSTs and an explicit no-send row. There is no stronger atomic delivery handoff guarantee or automatic later attempt. The original conservative crash limit also remains: a crash after a confirmed Sent ledger commit but before cleanup can retain an internal uncertain marker after restart, with one POST/one Sent/no replay and a possible later explicit reopening impact. This was reported for review rather than changing ordinary manual/retry behavior.

All sender observations use fake Discord; none proves live notification delivery or physical wire-attempt counts. This agent performed no production API/provider probe, notification, role change, service restart or application activation during implementation/QA. The tested branch is based on fe679 plus PR175; integration with current main remains required, preserving PR175's heartbeat and PR177's marker, with review on any behavior conflict.

Entries 481/482 approve release after final ACCEPT without a second owner ask, in serial order after PR183, with coordinator review before any stop, full 210-second drain, clear near-due window and fresh release gates. The new runtime accounting fields are explicitly identified for that review; this document grants no production guard exception.

# CWL pool roles release

PR #140 was accepted by Claude in handoff319 after the prompt99 delta review;
owner approval is quoted in handoff291. Release tag `cwl-pool-roles-1` points to
`1af386eb01c15b8fa1ac2980a3edf195b364924c`.

Activation completed at 2026-11-01T22:57:21.066194+00:00. Claude's read-only smoke327 passed. Both configured roles remain
blank. Ruggie will perform the first real Save; no agent role change or test send
is part of this release.

The final source passed 5,826 guarded backend tests (71 skipped, 227 subtests),
1,405 frontend tests, TypeScript/build, 120 focused backend cases (one skipped,
three subtests), 12 owned Mongo tests and an authenticated local recovery drill.
All 11 prompt99 gap mutants failed their targeted regressions. War reminder
checks passed 213 backend cases (one skipped), 35 frontend cases and build.
Prior isolated narrow/wide UI checks remain applicable; prompt99 changed saved
metadata handling and a frontend regression, not the application UI layout.

The four additive SQLite pool-role tables preserve existing roster/signup data.
Role intent and local durable progress have separate ownership and backup
receipts; recovery ambiguity pauses work instead of replaying it. The committed
protected-state comparator rejects incomplete captures and permits only exact,
contemporaneously proven roster-sync departure transitions.

Rollback retains bot `6c36e1cbfe2d0049c580669247919da6f734a0b4` and backend/frontend
`b63c0c95f5433fc7f3933cdc88c64abff849b3c0`. Code rollback keeps the additive tables
and durable data; it never restores the database over legitimate staff edits.

The first pre-switch guard stopped without a restart after legitimate owner filler
edits. A later attempt switched code, then rolled back when the strict SQLite
check saw the owner's new publication (five to six rows). The code rollback
retained all data and restored a healthy bot/dashboard. One forward and one
rollback bot/backend restart occurred in that failed attempt, each with the
required bot drain; no database was restored.

The coordinator was then updated under handoffs323–325 and Ruggie's renewed
"I'm done, be sure to continue now" approval. Accepted release-tool PR #144,
`bceed62788a76d24cdb3295f65c27b31e8de0dca` (merged `d93c017`), supplies a
hash-bound same-transaction SQLite audit proof. It reports exactly proven staff
publications/marks while rejecting removals, missing/forged receipts, designated
release actors, changed grants and unrelated tables. Forty focused tests plus
18 subtests and seven genuine mutation failures verify this seam. Image jobs
remain strict; role-only staff without separate proof fail closed. See
[the proof contract](release-staff-write-proof.md) in that tool revision.

The final authorized retry succeeded without rollback. Claude's read-only smoke327 passed.


Successful activation: bot PID `1672182`, invocation
`a2175e62d29d4e419f0888e35942f2d9`; backend PID `1672628`, invocation
`2d670bce8365490b97d30cc88d6cba29`. Backend/frontend run the isolated tagged revision.
Public `assets/index-B_W1sD8n.js` SHA256 `c4f751a29f0ad885fbf319b441886cdc69c52779ac6f93fbf582d05f08d7000d` matches the manifest; affected role selector
and roster assets also match. Startup journals contain zero warnings/tracebacks.
Both role settings remain blank at revision zero, with zero role jobs/audits.

Fresh SQLite/Mongo backup plus isolated test restore, additive migration preserving
every old row, runtime imports, readiness, exact protected counts/digests and
210-second bot drain passed. Counts: 3,715 active strikes, 306 accounts, 583 strike
profiles, 279 eligible replacement accounts and 479 member profiles. Six existing
publications are retained. The accepted staff-proof comparator reported zero
events before and during this final attempt; no table was broadly ignored.

The final retry added one bot and one backend restart. Counting the earlier
failed forward attempt and its rollback, the full release involved three bot
starts and three backend restarts, with the required drain on each bot stop.
The earlier pre-switch guard added no restart. No production database restore,
role Save, message send or real expiry test was performed by the agent.


Claude smoke327 verified the current release, backend PID/cwd, bot PID and public
entry hash. Since 17:58 EST the web journal had no warnings/tracebacks and the bot
had zero skips/errors. Seasons at 360px showed Main and Lazy both Off, a successful
GET /pool-roles and no overflow; 1440px had no overflow or failed requests. Save
was untouched. Live role Save/add/remove and the 16th expiry remain untested.
Lazy preceding Main is a minor UI follow-up for the next UI batch.

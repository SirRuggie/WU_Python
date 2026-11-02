# Member status and season loading: release audit

PR172 accepted head `4a621894a5869487e072b3a4eb3533a07b1899ad` was integrated
with current main as candidate4877d2a and merged as
`c55c7f0347773784b3556ff248a16ef1b7004d79`, tag `member-trust-1`.
The resulting tree `3dac97d9355b0e88d8a6794ac89e462bbaa07175` matches the
validated candidate. The only conflict was an additive documentation append;
Shaka432 approved preserving both complete sections verbatim. No application
source conflict or new runtime edit occurred. Owner395/ACCEPT427 and Shaka437
authorized this frontend release after Return reminders smoke.

The first season read runs even in a hidden tab; repeat refreshes can skip a
hidden document and visibility changes refresh it. Home waits for a known season
before showing signup state. Member views share season/status wording, display
one small refresh note after a completed season read, and reserve the urgent
loading block for data never loaded. Link help follows a completed read.
Existing roles, reminders and notification policy are unchanged.

## Validation

The exact combined application source passed 1546 frontend tests across 266
files, TypeScript/build, 48 focused tests and one isolated closed-signup HTTP
case. Application hashes equal tested c638166; later weights audit documentation
is the only subsequent tree difference. Backend application directories remain
byte-identical to weights e919, whose 6365 backend tests, 103 skipped and 267
subtests plus war reminders (213 backend, one skipped, 35 frontend/build) are
reused with that explicit scope. No new full combined backend run is claimed.
Accepted preview/browser evidence is separate from any live smoke observation.

Fresh gates after the ordinary 21:18 UTC capture passed backup/test restore,
canonical recovery, protected state, staff and no-queued proofs, narrow reviewed
automatic-field comparisons, timestamp and quiet-maintenance regressions,
imports, readiness and rollback rehearsals. Exact tagged-artifact boot used all
51 configured routes, native pool, real durability owner, copied SQLite and
owned Mongo with external networking blocked, config 200/auth 401 and verified
cleanup. The staged backend is for boot proof only and must not replace the live
backend in this frontend release.

All 73 existing tables, schema objects, typed rows and counts matched through
owned restore→Store→publish→canonical decode; no added table is permitted. Live
raw predecessor rows and exact sqlite_master schema remain protected. Actual
frontend switch/rollback mocks, four failure/control-flow cases and schema/row
negative checks passed. Code rollback restores only the retained frontend and
never restores a production database.

## Activation and smoke

The first attempt failed postflight because one profile changed Town Hall and
presence metadata between captures. The unchanged strict guard rejected it and
restored b387; public hashes/config200/auth401 verified healthy, zero service
restarts or production DB restore. Full failure evidence remains in
`.local/member-trust-release-1`. Shaka442/443 authorized a fresh ordinary-gap
retry with the guard unchanged; no Town Hall exception was installed.

The retry completed **2026-11-02T21:55:14.046271+00:00**, coordinator exit 0. Frontend is
`c55c7f0347773784b3556ff248a16ef1b7004d79`. Backend PID2841287/invocation
`90169425cd2d420aaeca171f1b781ef0` remains e919 and bot PID2047531/invocation
`25c8bea0ebc54016a1b6bcc78f38f104` remains343. Across both attempts there were
two frontend forwards and one frontend rollback, zero service restarts and zero
production database restores. Fresh protected counts for the retry were 3712
active strikes,303 accounts,587 strike profiles,274 eligible and479 member
profiles; these are observed counts, not reused historical values. Staff and
forbidden departure transitions were empty, unrelated configuration matched,
all 73 existing tables and raw predecessor rows remained protected.

Public entry `assets/index-c-Nv-MzQ.js` matched SHA256
`fc1afdbec59c0753a6abd1fa2e7188e07893dc4e5bc14a7cf39a279e206b5a63`; affected Member/Return/Weight/Export and preserved
feature assets matched the immutable manifest. Successful evidence is in
`.local/member-trust-release-1-retry/live.json` and the fresh backup, canonical,
boot, schema and guard proofs.

Shaka445's read-only live smoke passed using Ruggie's actual session. My clan
assignments showed `✅ = in the right clan`, real `Not in clan yet` rows and
`4 of 11 in clan`. Exports opened on its own season. Runtime and the public entry
matched the recorded release, and Shaka observed zero warnings since 16:50 EST
at that check.

Failed refresh, hidden first load and new-member link help were not tested live;
the smoke tab was visible. Their failure/recovery/initial-loading claims remain
supported by the isolated frontend and browser evidence above. Basic health,
asset hashes and this read-only smoke are not proof of notification delivery.
No agent role, nickname, reminder control, Discord message or provider probe is
part of this release.

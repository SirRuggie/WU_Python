# Return reminders: release audit

PR169 accepted head `9b5f38bf873901541f053e783d39c155bcec007c` was merged as
`b387045f42f68ef6bf7ebbddfb170205414d1a6b`, tagged
`return-reminders-simple-1`. The clean merge tree
`a3a698b91554e2ef69c93ddbce3ce54ba8cfbc0c` matches tested integration aeb354f
exactly. Owner425 approved this frontend release after weights, and Shaka434
confirmed the weights smoke and authorized proceeding.

The overview keeps current Return reminder status and routine controls visible,
with shared selection controls for multiple rows. The accepted preview was
reviewed at narrow and wide widths. This changes dashboard presentation; existing
reminder services, schedules and Discord delivery policy remain unchanged.

## Validation

The exact combined frontend source passed 1527 tests across 265 files, 23 focused
frontend tests, TypeScript/build and three Return service backend regressions.
Backend application directories are byte-identical to live weights e919; its
6365 backend tests, 103 skipped and 267 subtests, and war reminders (213 backend,
one skipped, 35 frontend/build) are reused with that scope stated explicitly.
A new full combined backend suite was not claimed. Source trees and original log
hashes are recorded in `.local/return-reminders-release-1/merged-suite-proof.json`.

Fresh release gates after the ordinary 20:51 UTC capture passed SQLite/Mongo
backup and isolated restore, canonical recovery, exact protected state and narrow
approved automatic-field proofs, staff proof, no queued work, timestamp and quiet
maintenance regressions, imports, readiness and rollback rehearsals. Production-
shaped boot used the exact staged artifact, all 51 configured routes, native pool,
real durability owner, copied SQLite and owned Mongo, blocked external networking,
config 200/auth 401 and verified cleanup. The staged backend is for this rehearsal
only; activation left the live backend and bot unchanged.

All 73 existing SQLite tables, schemas, typed rows and counts matched through
copied restore→Store→publish→canonical decode. The predecessor table must already
exist; no added table is permitted in this frontend release. Live raw predecessor
rows and exact sqlite_master schema remain protected. Rollback switches only the
frontend and never restores a production database. Actual frontend switch/order
mocks, four injected control-flow cases and schema/row rejection seams passed.

## Activation and smoke

Activation completed **2026-11-02T20:59:44.400720+00:00**, coordinator exit 0. Frontend is immutable
`b387045f42f68ef6bf7ebbddfb170205414d1a6b`; backend PID 2841287/invocation
`90169425cd2d420aaeca171f1b781ef0` remains e919, and bot PID 2047531/invocation
`25c8bea0ebc54016a1b6bcc78f38f104` remains 343. Zero backend or bot restarts,
zero rollback and zero production DB restore. Protected state, staff/departures
(empty) and unrelated configuration matched. Public entry `assets/index-iDpXMGpx.js`
matched SHA256 `b638a920c58eb1090e7d1d564bdc2543ddcf42dd96f0768e3fc19229226d0c2c`; affected Reminder/Return/Weight/Export
and preserved feature assets matched their immutable manifest. Read-only release observation found no repeated warnings after 20:20 UTC;
Shaka437 subsequently reported zero warnings since 15:55 EST (20:55 UTC).
The earlier three weights startup warnings remain documented separately.

Shaka437 reported **SMOKE PASS** on 2026-11-02 at 16:06 EST. The immutable
frontend, backend PID 2841287, bot PID 2047531 and public entry matched the release.
The read-only live page showed FWA 7 and Main 18; real clan rows showed Running,
Every 2 hours, stop date and last sent. No controls were clicked and no selection
was made. Actions and Change frequency were not tested live. This smoke does not
prove notification delivery. No agent reminder control, Discord message, role or
nickname write was performed for this release.

# Family follow-up162/167

Add clan closes the current editor before navigating to the directory; dirty
changes still require the existing in-app discard confirmation. The FWA impact
warning uses the exact stored FWA type, matching backend consumers, so legacy
Farming does not falsely claim FWA effects. Disabled reminder summaries explicitly
say the times are saved. History labels failed/unconfirmed reminder writes
"Not confirmed", since a timeout may occur after the database accepted the write.
No automatic retry or new write behavior was added.

Regressions cover route/editor agreement, exact-FWA warning, singular/plural
reminder summaries, endpoint confirmation labels, real nested snapshot field
matching, and Discord mention formatting with escaped external text and mentions
disabled. Five mutations (plural, exact-FWA, endpoint label, snapshot path and
show_clan formatter) were killed. Focused backend33 and frontend14 pass; full
frontend1110 passed, and final TypeScript/build passed. Full backend: 5095 passed, 21 skipped, 162 subtests. Isolated
320/360/390/1440 browser checks passed, including Add after an open editor,
Back/Forward, dirty guards, confirmations and history, with no errors or writes.

No production or live Discord testing is part of these checks. Existing artwork,
reminder CAS, permission, data-retention and delivery behavior remains unchanged.

## Release family-polish-1

Released tag `family-polish-1`, revision
`d1c670877b03ae8bf19f4ca1fa675af3edaa1cd0`, through PR #96. The integrated
revision passed 5,116 backend tests (21 skipped, 162 subtests), 1,114 frontend
tests, TypeScript, build and isolated narrow/wide browser checks.

Frontend and dashboard backend were activated together; the bot stayed at
`5d09708b8cdc6ac0349a20c75293bd8eae9153fc` without a restart. The served entry
`index-BE6LmK3c.js` has SHA-256
`2497e153587c17242e9cfd2ed31e6f41ed29be05d1c3ec4ec13a4429ff350015`.
Imports, readiness, public asset hashes and the service journal passed.

The initial protected-data gate stopped before activation because a staff roster
assignment changed during verification. Claude verified the corresponding audit
row and authorized a fresh baseline in handoff entry 172. Fresh SQLite and Mongo
backups passed readback/hash checks; post-activation protected SQLite data and all
25 clan metadata records matched that baseline. Evidence is retained in
`.local/family-polish-release-evidence/`, including the original gate failure.
Rollback assets retain revision `5d09708` for frontend and backend; rollback does
not restore databases or restart the bot.

Claude's entry 173 confirmed production smoke at 360px: frontend and backend
revision match, the public entry hash matches, no tracebacks, no failed requests,
no overflow, and Warriors United shows "War reminders · Off · 3 times saved"
and "0 unsaved changes". This was read-only; no live Discord delivery was tested.

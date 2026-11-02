# CWL date diagnostics and per-clan waiting

Release tag `cwl-date-month-1` identifies merge
`3f983454457aeb45e008caaf6ff66d04fb388599`. The merge tree is identical to
reviewed head `9868975a676f65ec6bc146adf9f9d66b3a4c5c47`; there were no source
edits or conflicts. Ruggie's quoted approval in handoff 376 and Claude's direct
ACCEPT 392/393 authorize a backend-only release.

Only valid `YYYY-MM` values are explicit cycle evidence. Date-shaped strings
retain the deployed no-month decisions at all group and war sites. Diagnostics
alone expose their masked `YYYY-MM-dd` month and `season_kind=date`. A date never
rejects an active inferred group or bypasses ENDED stored-tag containment.

An unusable NOT_IN_WAR group is per-clan `no_group`, irrespective of its season.
Own cycle evidence still keeps a warning, including a preparation observation
without war tags. The provider retains its failure boundary; its season metadata
is retained solely for masked diagnostics. Other malformed states still warn.

## Validation

The reviewed tree passed 6,238 guarded backend tests, 99 skipped and 267
subtests; 256 focused capture/provider tests and 14 subtests; four genuine
mutations; 1,484 frontend tests in 261 files; TypeScript/build; and the war
reminder check (213 backend, one skipped, 35 frontend and build). Claude
independently confirmed the full backend result.

The exact reviewed artifact passed a production-shaped isolated boot with all
51 configured routes, native pool, the real storage owner on copied SQLite and
owned Mongo, external networking blocked, config 200/auth 401 and cleanup/hash
proof. The first harness attempt started before its frontend build existed and
stopped on missing index.html. Its fixtures were removed and evidence retained;
the completed-build retry passed. No production service was touched by it.

A clean tagged frontend build is byte-identical to every file in immutable
frontend `343d9611213d1feb722d4cf72250d4e8a4e751be`. Its entry remains
`index-DODYu6Hv.js`, SHA256
`70ae891fce6403a70c8cbcee48863357a4a281615c93c9d461ac02762e009b1d`.
The bot also remains at 343; neither layer requires a switch or restart.

## Activation audit

The first activation preflight stopped before switching because two protected
replacement `departed` flags changed from true to false after backup. All other
protected fields matched. The old backend PID and invocation remained unchanged;
there was no restart, rollback or database restore. The guard was not relaxed.
Its proofs, logs and backup references are retained under
`.local/cwl-date-month-release/attempt1-preflight-stop/`.

A second preflight stopped before switching because an ordinary capture changed
only observation timestamps:124 source rows, six group rows, six war rows and
24 fetch rows. A third fresh backup stopped on one returning `departed` flag.
The second attempt is retained under `attempt2-preflight-stop`; the third gate
log and captures remain in the release folder. No attempt restarted or switched
a service, rolled back code, or restored production data.

The three stops above all happened before service changes. Their counts are
historical snapshots. Ruggie then approved only the exact automatic presence
update pattern and four named capture timestamp columns. Claude reviewed and
accepted PR168 at `bca0be8`; Ruggie directly authorized its merge in Stella's
chat, producing `343fbf043c5e0f9b6df8f45a4f5f4776f9b5c45a`.

A new coordinator pinned the reviewed guard and validation dependency hashes.
Its integration rehearsal accepted two exact presence changes and 160 capture
timestamps, and rejected a publication edit. Row additions/removals, staff
changes, weights, publications and neighbouring fields remain strict. Each
allowed change has a private per-field proof. The existing single local-reader
timestamp normalization remains separately tested; no wildcard was added.

After an ordinary capture, fresh backup/test restore, canonical recovery,
protected-state and staff proofs, no-queued check, isolated native 51-route boot,
imports, readiness, actual rollback-order and control-flow rehearsals passed.
The approved coordinator completed at **2026-11-02 17:52:13 UTC**. Backend PID
2309002, invocation `978583816fc54891b8c1266488f547d5`, runs the immutable 3f
artifact. There was **one backend restart**, zero bot restarts, no rollback or
production database restore. Bot PID2047531/invocation
`25c8bea0ebc54016a1b6bcc78f38f104` and immutable frontend343 stayed unchanged.
Staff-before, staff-during and forbidden departure transitions were empty;
unrelated configuration and affected public asset hashes matched. Evidence is
in `.local/cwl-date-month-release-approved/live.json` and its gate/proof logs.

Claude's read-only smoke413 confirmed runtime, unchanged public entry, auth401
and zero tracebacks. The first ordinary capture completed18:06:15 UTC: eight
PREPARATION groups inferred current with date shape `2026-11-dd`; one ENDED group
with `2026-10-dd` remained waiting; one clan returned404. All32 war season values
were absent, with zero mismatches. Claude independently confirmed the group
result in416. No forced capture or provider probe was used.

A second ordinary capture completed18:21:21 UTC. Sync was partial, warning null,
and last-success equalled last-checked. Stored source rows were137 preparation,
27 waiting, five no_data, two stale and four unassigned, with eight group and
eight war observations. These counts include historical stored membership and
are not a claim that all rows are currently working accounts. Both read-only
observations are retained alongside live evidence.

Dates remain log-only. No finished November group, live role change, notification
or Discord edit was tested. The later proposed direct roster-post edit was
withdrawn; it is not part of this release or its validation.

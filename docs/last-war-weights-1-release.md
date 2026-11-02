# Two retained war lineups: release audit

Tag `last-war-weights-1` identifies PR170 merge
`e91982d92632193c476adde34a8ec133495ff750`. Accepted feature head 36bbc5a was
integrated with current main without conflicts. The resulting tree is
`adb00613c417f8bff0eaa92f010fc943a9c737a5`; application source matches tested
integration 703968b exactly. Later changes were reviewed migration tooling/docs.
Owner 425 approved backend/frontend release after Exports; no bot restart was
needed because the bot's effective_weights consumer remained unchanged.

The feature retains up to two usable captured lineups, defaults newest and lets
staff edit eligible departed players. Existing saved weights remain the shared
per-player ledger. Missing history is not invented or backfilled. Known player
metadata is preserved; unknown Town Hall stays unknown. Existing latest-lineup
storage remains four columns and code rollback preserves the additive table.

## Validation and migration

The combined application passed 6365 guarded backend tests, 103 skipped and 267
subtests; 1509 frontend tests, TypeScript/build and war reminders (213 backend,
one skipped, 35 frontend and build). The reviewed delta also passed 78 focused
backend/64 frontend, four owned Mongo cases, eight genuine mutants and four-width
browser checks with narrow/wide review. Later tooling passed 40 focused cases,
seven public-owner/compatibility Mongo cases and a wildcard-table mutant.

The schema change is exactly one initially empty table,
`clan_weight_war_lineup_previous`, with clan_tag TEXT PRIMARY KEY and non-null
end_time, captured_at and lineup_json TEXT columns. The copied-DB startup gate
used public restore→actual Store→public publish→canonical decode. It proved all 72
existing tables, schema objects, typed rows and counts unchanged and canonical
publication before workers. Full raw-row comparison is confined to owned copies;
live reads retain the original protected reader plus raw predecessor rows, the
existing narrow automatic-field proof, and exact full sqlite_master equality
against validated pre/post startup captures. No arbitrary empty table or field
allowance was added. Existing predecessor rows remain strict on later releases.

Fresh SQLite/Mongo backup and isolated restore, canonical recovery, protected and
staff proofs, no-queued gate, 13 timestamp/8 maintenance regressions, exact staged
51-route native production boot with blocked networking, imports, readiness,
actual rollback order and public hashes passed. Forward order is backend then
frontend; rollback is frontend then backend. Rollback never drops the new table
or restores a production database. A separate old-local-backup rehearsal was a
preliminary diagnostic, not the fresh release backup proof.

## Observed activation

The release completed **2026-11-02 20:19:36 UTC**. Backend PID 2841287/invocation
`90169425cd2d420aaeca171f1b781ef0` runs immutable e919. Frontend also points to
e919; bot PID 2047531/invocation `25c8bea0ebc54016a1b6bcc78f38f104` remains 343.
One backend restart, zero bot restarts, no rollback or production DB restore.
Protected state, exact schemas, raw predecessor rows and unrelated configuration
matched; staff-before/during and forbidden departure transitions were empty.
Final host state matched the recorded invocation; config 200/auth 401 passed.

Public entry `index-1pJQfKwi.js` matched SHA256
`40dbbfaeb755445a4c9b49c32e1ed38e2ca4a1b037e32ff39ac24c2c93b4eec2`.
Affected Weight/Export and preserved feature hashes matched. Evidence is in
`.local/last-war-weights-release-1/live.json`, final-runtime-health.json and the
migration/backup/boot/guard proofs. Root made no Weight page request or Save and
no Discord write.

Three upstream warning lines were observed: Todo clan history WaitQueueTimeoutError,
Todo history NetworkTimeout, and lineup capture unavailable with saved lineups
retained. There were no tracebacks or critical startup errors; basic health and
protected state passed. These warnings are not hidden as a zero-warning result.
Claude's read-only smoke 434 passed: current frontend and backend matched e919,
the bot stayed unchanged, and the public entry hash matched. GETs returned seven
clans; the first clan had 44 members, 50 players in war order and a lineup source.
Claude made no saves. The three single startup warnings had not repeated since
15:20 EST at that observation. Similar low-rate Mongo timeouts existed on earlier
days; Claude classified these as transient Atlas rather than a release regression
**as an inference**, not a proved root cause. Watch for recurrence. No rollback
criterion was observed.

This smoke establishes read-only runtime/data availability. It does not establish
live save, departed-player edits, concurrent updates or Discord delivery; those
behavioral claims remain supported by the isolated regressions above. The local
four-width browser evidence covers layout; smoke 434 does not add a live browser
layout claim. PR169 proceeds separately under the approved serial release order.

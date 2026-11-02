# Audited staff writes during a release

The release SQLite gate retains strict equality for all protected state except
precisely proven publication additions and filler marks. Existing publication,
audit and snapshot rows cannot be deleted or changed. Withdrawals, signup edits,
image jobs and other unrelated changes still fail closed.

The coordinator captures protected tables and their audit evidence in one
read-only SQLite transaction, before and after switching. Captures include
`roster_audit`, `publication_accounts`, `roster_meta`, seasons and direct grants.
The application owner policy and unchanged direct grants provide trusted actor
scopes; an actor mentioned in a new audit row cannot authorize itself. Role-only
staff without separate authorization evidence fail closed. No production session
or application actor belongs to the release; designated release actor IDs are
explicitly denied even if they otherwise have owner privileges.

A new publication must have the next season version, a matching `roster_publish`
receipt by the same authorized actor, exact prior/current metadata, timestamps in
the observation window, and its own complete account snapshot with matching
counts. Old snapshots remain exact. A mark needs every intermediate audit step:
old value, new value, next revision, authorized actor and exact final mark row.
Global mark increments and season publication increments must explain roster
revision counters exactly. Audit IDs must append, and earlier receipts cannot
be altered or removed. The report lists only accepted events; it never mutates
or restores application data. Private reports contain actor IDs and must not be
copied into public release notes.

Existing audit rows are trusted application receipts, not cryptographic proof
against a privileged database attacker. Actor authority is not inferred from a
request body. Invalid/missing evidence remains a failed gate, not permission to
ignore a whole table. SQLite audit timestamps have second precision; the first
capture's same second is accepted, with no wider stale-receipt grace period.
A mark's final timestamp must exactly match its last audit timestamp; a rare
cross-second write may therefore require investigation rather than automatic
acceptance.

Validation uses actual isolated HTTP publication handlers and the real mark
storage owner, a query-only capture/comparison seam, multi-season revisions,
interleaved publication/mark chains, release/untrusted actors, missing/stale or
forged receipts, old-row removal/modification, missing snapshots, unrelated
signup changes and malformed/time-reversed captures. Seven targeted mutations
fail these regressions. This is release-tool verification; it sends no live
Discord message, changes no real role and proves no live role delivery.

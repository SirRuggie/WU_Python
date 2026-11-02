# Two-war migration release comparison

This tooling is proposed for review before coordinator use. It does not initialize,
publish, restore, deploy, or modify a database. No existing release coordinator or
application storage owner is changed by this PR.

`tools.weights_release_migration.capture(connection)` captures every SQLite table's
schema, declared columns, typed row multiset and count, including internal SQLite
state. `compare(before, after)` permits only the exact accepted
`clan_weight_war_lineup_previous` schema and its implicit primary-key index to
appear, with zero rows on first creation. Every old table/object and every old row
remains exact. If the predecessor already exists, its rows are strict too. No
staff-edit, arbitrary empty-table, column, metadata or neighbouring-field exception
is introduced. The result contains both capture hashes and explicit verification
facts; keep the captures as evidence, rather than keeping only the result boolean.
Physical row ordering and undeclared implicit rowids are not compared. Typed values
preserve integer/real and text/blob distinctions and duplicate declared rows.

`capture_protected(connection, existing_reader)` invokes an existing public
protected-state reader inside the same SQLite read transaction and adds raw
predecessor rows under `clan_weight_war_lineup_previous`. A missing legacy table
normalizes only that key to `[]`. A pre-existing conflicting key fails. It does not
mutate the reader's dictionary or weaken its other fields. `previous_rows` is the
standalone public raw-row accessor. Existing caller transactions remain open;
otherwise these readers roll back only their own read transaction.

The release integration must still independently verify a fresh backup/test restore,
canonical Mongo ownership/lease/CAS and uncertain-write fencing, protected state,
no queued jobs, staged startup, readiness, rollback assets and public hashes. This
comparison does not authorize a release or replace those gates. Compare independent
captures across the migration boundary before serving workers; do not use an API
request that can remember/rotate lineups as a read-only startup check.

The actual candidate entrypoint is `cwl_web.__main__`: owner restore, Store schema
initialization, explicit public `owner.publish(db)`, then `web.run_app`. Store
initialization alone is not canonical publication. A failed publish exits before
serving. A code rollback preserves the additive table and all rows; the old latest
lineup table keeps its original four columns. Never restore/drop tables to roll back
this schema.

## Validation

Forty focused unit cases cover exact first creation, repeated startup and existing
predecessor rows, unrelated empty tables, wrong DDL, added schema objects, changed
old rows/counts/types/actors, malformed captures and read-only transaction behavior.
A genuine mutant replacing the exact table allowlist with “all added tables empty”
is killed by six functional cases (three names, before/after first migration).

The optional owned-Mongo test requires `WU_WEIGHTS_GUARD_MONGO_URI` to equal
`mongodb://127.0.0.1:27165`. Run it with the accepted candidate's Store imported
before pytest, not with a synthetic migration. The local rehearsal used accepted
PR170 revision `36bbc5ac280ea103e3eb18d78c0999caa7fbb1f0`: fictional legacy image,
public owner seed/restore, actual Store initialization, public publish, canonical
decode, exact comparison, restart and old four-column positional INSERT. It also
covers lost acknowledgement before and after canonical schema acceptance. Together
with the candidate's four existing owned-Mongo regressions, seven tests passed.
External network was blocked; only owned loopback Mongo was used and its process,
databases and temporary data directory were cleaned. No production rehearsal,
provider query, release or coordinator use is claimed. Full backend was not rerun
while another agent held the serialized suite slot; there are no runtime edits.

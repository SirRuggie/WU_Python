# Participation capture clocks in release proofs

Owner decision489 approves the small Option A exception proposed in488:
`participation_sync_settings.last_checked_at` and `last_success_at` may advance
without weakening any other protected state. This tooling change does not alter
application code, storage/schema, timers, provider calls or production services.
Old approved guard44ee and failed-attempt evidence remain unchanged. The new guard
must be reviewed and accepted before a coordinator uses its new hash.

The table's row count, positive integer season identity, column set and every
nonclock value remain exact, including value types. Clock-only comparisons require
both clock keys in both captured rows. Operational readers must preserve the raw
SQLite values; they must not strip `last_checked_at`, fill missing clocks, or
normalize other fields before comparison. The comparator reports changed clock
fields and includes an additive `participation_sync_settings` table change count.

Non-null clocks must use the source's ISO UTC string format: `YYYY-MM-DDTHH:MM:SS`
with optional microseconds, followed by `Z` or `+00:00`. Naive/non-UTC/malformed
values and type changes reject. Each changed new clock must be at least its prior
value and lie inside the existing observed interval, inclusive from
`before.started` through `after.ended`; it cannot be after the post-capture end.
Unchanged non-null historical clocks can predate that interval but must remain
valid and not be future values. Unchanged NULL is allowed. NULL-to-time or
time-to-NULL transitions reject rather than inventing monotonic evidence.

All neighboring columns—including cycle, enabled, status, warning, updated_by and
updated_at—stay strict. Added/removed/duplicate rows, missing clock keys or any
clock-plus-neighbor edit reject. Unknown neighboring fields are also exact.
Other protected tables, the prior four automatic observation clocks, Mongo
presence proofs and staff/publication evidence retain their existing rules.

Focused regression checks cover clock-only updates to either/both fields,
unchanged clocks/NULLs, every neighboring column, numeric type equality traps,
row identity/membership, invalid timestamps, interval endpoints and backwards
movement even when both values are within the interval. Six assertion-killed
mutants remove neighboring-field, row-membership, monotonic, UTC, lower-interval
and post-end protections. Real isolated HTTP/SQLite receipt regressions remain
part of the targeted checks; no live Discord or production capture was exercised.

The historical971 protected images stripped `last_checked_at`. Complete actual
pre/post pairs cannot be recovered from them, and this change makes no actual971
replay claim. A clearly labeled complete synthetic971-shaped regression exercises
the four existing observation clocks plus both settings clocks with every other
value unchanged. Stripped images reject; no missing historical value is inferred.
Root separately verifies the corrected operational reader against owned SQLite
before any approved use. This PR neither edits nor installs that reader.

Final targeted validation:168 tests and18 subtests across four guard/receipt files
passed; six meaningful assertion mutants were killed and source restored. The
AST of every existing function except the SQLite comparator is unchanged,
including all Mongo and original timestamp validators. No application-wide or
frontend suite is needed for this isolated tooling change; no application or UI
source changed. Review evidence is retained in the worktree's `.local` folder.

# Campaign reconciliation read footprint

The ten-second management poll previously fetched every `bot_config` document for
the guild and then selected active campaign records in Python. Unrelated profile
manifests and child receipts were transferred on every tick. The read now filters
by the same guild, the same two campaign kinds and `activated: true` in Mongo,
and returns only the fields consumed by reconciliation.

| Field | Why it is retained |
|---|---|
| `_id` | Stable sorted fingerprint identity |
| `revision` | Revision changes invalidate the saved fingerprint |
| `updated_at` | Campaign edit timestamp remains part of the fingerprint |
| `recurring_updated_at` | Recurring changes remain part of the fingerprint |
| `cycle` | Load each full native campaign generation before synchronization |

No campaign body is needed for this discovery read. `load_campaign` still loads
full native state for generation checks, and `sync_all` still owns scheduling.
All active defaults and cycles are included, including future cycles. Inactive,
other-guild and unrelated records were excluded by the original Python filter
and remain excluded. Activation and deactivation change the same fingerprint.
A failed sync does not acknowledge anything, and an edit during sync is detected
on the next tick using the original pre-sync generation behavior. The poll
interval, scheduling limits, delivery, authorization, destinations, retention,
Mongo client lifetime and general dashboard recovery-copy design are unchanged.
No index or migration is introduced.

## Evidence and limits

Approved read-only production sampling on November 1 returned 354 guild records:
793,011 BSON reply bytes, 794,197 received TCP payload bytes, 8.322 seconds in one
warmed-client sample. The filtered/projected read returned two records: 602 BSON
bytes, 645 TCP bytes, 0.048 seconds. Socket deltas include TLS and connection
monitor overhead. These are query measurements, not a deployed full-job result
or an Atlas contractual billing meter. No documents, member IDs or credentials
were exported.

At the nominal ten-second cadence, response payload alone models 47.961 GB/week
before versus 0.036 GB/week after this query substitution. Actual invocation
frequency and document sizes vary. This does not include all application traffic.
The separate hourly backup change was naturally verified at 20:02–20:03 UTC,
about 19.24 MB received per dump and 3.23 GB/week at hourly cadence. Full audit:
`/home/ruggie/wu-handoff/mongo-audit-numbers.md`.

A fresh twenty-minute bot-journal baseline had 97 paired successful poll runs,
median 9.183 seconds, p95 11.947, maximum 12.872, and 22 skipped runs. It spans one
process/invocation. No failed paired runs; one start was outside the paired
window. This is a baseline, not causal attribution of every unlogged await.
Post-release duration/skips and served/runtime verification remain required; do
not manufacture a PASS before the observation window has elapsed.

Focused checks pass: 63 campaign, native reminder, web bridge and HTTP cases;
one owned real Mongo test covers exact boolean/filter/projection behavior,
response size and full native generation loading; six behavioral mutants fail
for full-response loading, missing revision/edit/recurring/cycle fields and
inactive-campaign selection. Required war-reminder checks pass (213 backend,
one skip, 35 frontend, TypeScript and isolated build). Full guarded backend passes: 5,718 tests, 59 skipped and 224 subtests. No live notification was sent.

Only the bot needs the new shared function loaded. Release requires Claude
ACCEPT under owner approval303/314, a fresh backup and isolated test restore,
protected-state/readiness/rollback checks, no queued Standardize or other active
management write, a 210-second drain and one bot restart. Backend/frontend
revisions stay unchanged; verify their public assets and runtime rather than
switching them. Retain Claude's read-only smoke and post-release poll observation.

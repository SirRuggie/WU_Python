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

## Release: campaign-read-footprint-1

PR142 was accepted in Claude entry 315 and released under Ruggie's approval
quoted in entries 303/314. The tag points to
`6c36e1cbfe2d0049c580669247919da6f734a0b4`. Bot-only activation completed
2026-11-01 at 20:45:14UTC, after a 210-second stop/drain and one bot restart.
The bot PID was 1610906, invocation 8c742f72124b4de795b1b30bd08fcbe8.
The backend PID 1518593 and immutable frontend b63c0c95 remained unchanged.
Public `index-iSn7-bh_.js` SHA256 was
`82bb15ff18de0e84e20ad14dd1c132ad754234c84fdf955c9de8e23deaae4660`.

Fresh SQLite/Mongo backups and an owned local test restore passed. Protected
state was unchanged: 3715 active strikes,306 accounts,583 strike profiles,
279 eligible replacements and479 member profiles, with matching profile/settings
and SQLite digests. Startup/imports/readiness, rollback rehearsal, complete
capture comparison and public hashes passed. No rollback, database restore,
backend restart, frontend switch or agent-triggered Discord write occurred.

The uninterrupted 600.68-second observation 20:45:17–20:55:18UTC measured 59
successful 10-second-job completions, zero skipped runs and zero failures.
Median duration was 0.726717 seconds, p95 3.552597 and maximum 3.601286;
the preceding 20-minute sample had 97 successes, 22 skips, median 9.182699,
p95 11.946647 and maximum 12.872205 seconds. One boundary start was unpaired.
There were no warning-or-higher journal entries or tracebacks in the new
invocation at the post-window check.

A single deployed projected read returned two documents, 602 decoded BSON reply
bytes and 645 TCP bytes received in 0.045181 seconds. The previous broad read
sample returned 354 documents, 793011 BSON reply bytes and 794197 TCP bytes received
in 8.32189 seconds. The nominal 10-second read-component model changes from
about 47.96 GB/week to 0.036 GB/week. Socket deltas include TLS/monitor overhead.
These are query-component estimates, not Atlas billed totals.

Same-node aggregate server counters during the observation still increased by
6592679 bytes in and 59934300 bytes out, with 8772 requests. Connections changed
58→57 and 109 new connections were recorded, about 0.181/second. Aggregate
counters include other clients and replication; they cannot prove compliance
with Atlas Free's rolling transfer quota. Remaining prompt 97 work is still
necessary. No real campaign edit occurred in this window, so live rescheduling
after such an edit remains unverified; no edit was triggered for testing.

Claude's read-only production smoke passed in entry 316 at 21:06:44 UTC on
November 1. Claude checked the bot job and dashboard journals and received
HTTP 200 from the site. This smoke did not exercise a live campaign edit.
Claude also retained the aggregate-traffic and connection-churn findings for
remaining prompt 97; it did not certify the rolling Free-tier transfer budget.

Private evidence: `.local/campaign-read-release/live.json`,
`ten-minute-observation.json`, `query-after.json`, `journal-health.json` and
`activation.log`. Retained rollback is the prior bot b63c0c95; rollback would
also require the 210-second drain. No rollback was executed.

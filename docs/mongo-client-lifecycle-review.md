# Mongo client and idle-work review

Prompt 97 reduces idle work and connection churn while preserving authorization,
notification receipts and the existing SQLite recovery-copy design. It has not
been activated. The campaign projection/read fix was released separately as
campaign-read-footprint-1. No repeat activation is needed.

## HTTP pool ownership

The dashboard now owns one async Mongo client from its first cleanup context.
Its consumers stop before that context closes the pool. Todo clan history and
FWA outcomes, family-clan lookup, the Manage bridge and server-management
adapters reuse it. Request authorization remains per request. Existing explicit
adapter test injections are retained, and unavailable Todo messages are
unchanged. Constructing a routed client creates collection handles, not indexes.

The async pool has appName `wu-dashboard-http`, maxPoolSize 20, server selection
budget 5 seconds and default operation budget 15 seconds. Todo and family lookup helpers retain 5-second CSOT bounds. Manage bridge
collection operations and cursor consumption each get a fresh 10-second budget;
server-management uses the driver’s 15-second per-operation default. Neither
adapter holds CSOT across a workflow, Discord wait or background-task creation. Existing outer Todo seven-second bounds
also remain. Parallel requests share a client, not their timeout contexts.

The synchronous durability client stays separate because publishing is inside
synchronous SQLite transactions. Incoming 330 explicitly approves these two
intentional pools and rejects a copy redesign here. Its existing selection
5 seconds/operation 10 seconds/majority write concern remain; it now has appName
`wu-dashboard-durability` and maxPoolSize 10. The shared-pool increment left publishing and poison recovery unchanged; the
subsequent recovery checkpoint is described below.

A standalone LiveProviders instance caches its own async client and exposes an
explicit close method. HTTP startup instead binds the app-owned pool through a
public method. Provider cleanup never closes a pool owned by the application.
Disconnected fixture startup does not create a client from ambient credentials.

The first pool checkpoint used fake adapters and isolated HTTP fixtures.
Real-Mongo and final validation are recorded below; no live Discord was tested. Tests cover all five async paths sharing one startup pool, operation
budgets, parallel avatar requests still authorizing individually, unavailable
messages, app cleanup once and standalone provider cleanup once. These pool contracts remain part of the final regression checks.

## Worker cadence and recovery

The bot pool is named `wu-bot`, limited to 20 connections per server, with a
3-second serverSelectionTimeoutMS setting and 30-second default Mongo operation
budget. CSOT can override that selection setting: a dead server may consume
the full 30 seconds, so this is not a three-second failure guarantee. The
30-second choice leaves more maintenance headroom than the first 10-second
prototype; it does not change Discord edit/worker/lease budgets (150/200 seconds).
Index bootstrap, clan-history bulk writes, legacy full CWL cursors, full profile
reads and hourly activity reconciliation need explicit long-operation review and
real-Mongo checks before completion. Standalone backup/migration clients are not
changed. No unbounded operation is claimed safe merely from fake timings.

The one-second scheduler still fires, but confirmed empty management work is
checked at most every two seconds. Active-work scheduling is unchanged. Heartbeat
maintenance remains every ten seconds with successful writes at most every 30
seconds, preserving the 60-second readiness window. Failed writes never advance
the cache clock. Band status writes on change or after a minute. Base-image data
is projected and validated atomically, then cached for a minute; failures are not
cached. Only confirmed-empty expiry sweeps have a minute cache; pending or unknown work
sweeps immediately. Bulk activation retains its minute cadence. The ten-second
CWL admission tick owns one background delivery task, preventing slow delivery
from blocking that ticker or admitting duplicate drivers; the shared side-effect
lane is retained. Per-step timing distinguishes queue wait from actual work.

A 600-virtual-second complete idle fixture (management plus campaign reconciliation
and pending-send scans) measured 1,412 commands before and 642 after: 141.2 versus
64.2 per minute, 54.5% fewer. This is command-count evidence, not wire bytes, live
latency, a pacing fix or an Atlas quota result. Production traffic and connection
rate must be observed separately after an accepted release. The existing hourly
activity change detector and confirmed 90-day `left_at` TTL are retained.

Recovery now keeps a bounded set of known writer receipts. Every normal publish
adds an opaque receipt token. After an ambiguous result, only the exact last
confirmed image or one of this writer's uncertain receipts can be reconciled.
Recovery first increments the Mongo revision without changing its validated image;
that fence prevents an old timed-out CAS from arriving later and overwriting the
recovered truth. A lost recovery acknowledgement remains fenced and can be checked
again. A foreign owner, unrecognized newer revision or corrupt image is never
replaced. The format-1 SQLite copy design is unchanged; receipt metadata is additive.

The existing SQLite file is reconciled inside one FULL transaction, preserving
schema and monotonic sequences. Exact current trigger definitions are suspended
transactionally while restored rows are inserted, then recreated before commit,
so revision/audit triggers do not replay recovery data. Schema or trigger changes
fail closed. Matching local role progress is merged through its existing storage
owner; confirmed terminal receipts survive, and newly accepted intents without
local proof stay paused. Mongo ownership is confirmed before the local commit;
only after commit is the fence cleared. No notification or role action is retried
by recovery. Transient outages keep retrying recovery instead of requiring restart. Permanent
foreign-owner, corrupt-image or schema fences log once at CRITICAL and retain a
separate needs-attention state for staff. A later transient error cannot downgrade
that notice. While transiently fenced, the API says storage is recovering, with a reminder
to check saved results before retry. A storage-only response header also shows
staff one short line at the top of the existing shell. It does not sign staff out,
change authorization, add polling or retry a possibly accepted write. Only a
successful authenticated session read clears that line; a successful public
configuration read does not. Ordinary provider failures do not set it.

Checkpoint validation: 91 integrated fake/fixture tests passed, one optional Mongo
skip. These include late original CAS after fencing, original CAS winning during
fencing, lost recovery acknowledgement, foreign owner/newer revision, corrupt
image, failed local commit and subsequent recovery, preserved sending/sent
notification receipts, preserved terminal role receipts, paused unproven role
intent, and lifecycle retry/heartbeat resumption. The thread cases stalled inside
the restricted process sandbox; native local runs passed. No production provider
probe, role, nickname, message or settings write was performed.

## Real Mongo and long-operation review

Twenty-one checks passed against a dedicated loopback-only Mongo server: seven new
majority-CAS/core recovery cases, twelve existing role-progress/restart cases,
and two pool/maintenance cases. These are real database tests with injected
acknowledgement failures; they do not simulate Atlas network latency or Discord.
The fixture was stopped afterward, and only its generated databases were removed.

For twenty identical full-document reads, the actual app-owned pool opened three
connections versus sixty with per-call clients. Raw fixture server deltas were
480,205 → 458,554 bytes out and 29,575 → 5,364 bytes in. They include observer and
handshake overhead, use no wire compression, and are not a claim that response
payload shrinks simply because a pool is shared. No production post-release
connection rate exists yet; the accepted-release observation must measure it.

The operation inventory covers bot index bootstrap, clan-history candidate/watch/
roster bulk writes (`utils/clan_history.py`), startup CWL pending-reminder scans,
member-profile cursors and hourly activity reconciliation. None intentionally
requires an unlimited operation deadline. Existing explicit profile/Discord
budgets remain independent. The real fixture exercised index creation, 500
unordered updates and a 584-row full cursor under the actual 30-second bot Mongo
budget. This proves those shapes work locally, not that every Atlas operation
will finish in 30 seconds. Large/slow commands now fail within the explicit
budget and retain their owner's existing failure/retry rules. Standalone dump,
restore and migration clients keep their own limits. No background index or
production Mongo schema was changed by this batch.

## Transfer estimates and remaining production observation

The read-only audit in `wu-handoff/mongo-audit-numbers.md` is the source for these
historical figures. Its 642.5-second sample saw 145 new server connections
(0.226/s), dashboard sockets 18–25 in a separate kernel sample, and unknown bot
PID attribution. After the separately released campaign query fix, the ten-minute
observation still saw 109 new connections and 59.9 MB aggregate server outbound.
Those shared-server counters cannot be assigned wholly to one process or treated
as Atlas billed transfer. Prompt 97 has not been activated, so an actual before/
after production comparison remains a post-release gate, not a fabricated result.

The one-minute base-image cache changes a 17,135-byte historical full-config read
from sixty to ten reads per ten minutes. At that fixed document size and nominal
cadence, this avoids about 0.864 GB/week of uncompressed document payload before
projection savings, headers or compression. It does not imply that half the idle
commands means half the wire bytes. The existing hourly activity query cannot
explain sustained multi-MB-per-minute transfer by itself.

Other historical scenarios are unchanged: the measured natural hourly dump's
19.24 MB received TCP lower bound models about 3.233 GB/week outbound; `--gzip`
compresses its files, not necessarily its Mongo wire traffic. The main-image
141,821-byte compressed payload at one publish per minute models 1.430 GB/week
inbound; the audit's observed 22 publishes/642.5 seconds models 2.937 GB/week.
This batch retains full-image publishing and does not claim those writes went
away. An hourly full-activity-collection equivalent models 0.646 GB/week each
direction before overhead; actual per-player traffic differs. These overlapping
scenarios are not a total upper bound and do not prove the owner's 10 GB/rolling
week limits safe. Manual release backups, retries, growth and unmeasured clients
remain outside the model. Post-release timing, skips, connections and traffic
must be reported honestly; a remaining large component may require a separately
reviewed change rather than a copy redesign slipped into this batch.


## Final validation and deployment limits

The full backend matrix covers every file exactly once in three disjoint groups.
It passed 5,873 tests, with 80 optional/fixture skips and 253 subtests. Final review
also added and passed the immediate post-recovery role-write handoff regression
inside a 35-test fenced/role regression run; this last focused result is separate
from the full-matrix total. The complete frontend suite passed 1,424 tests in 252
files, with TypeScript and production builds. Required war-reminder validation
passed 213 backend tests (one skip), 35 frontend tests and build. Eight unique
behavioral mutants were killed: per-call pools, accepting an unknown newer head,
missing checked_at, unconditional unchanged band writes, missing revision fence,
lost terminal role progress, unbounded uncertain receipts and a bypassed staff
storage notice. Mutation runs used disposable exports with bytecode disabled to
avoid cross-mutant cache contamination; final failures were genuine assertions.

The actual App shell was checked at 360 and 1440 pixels with detached GET-only API
fixtures. The warning appeared once after a storage failure, left the session and
page usable, and cleared on authenticated recovery. Screenshots were visually
reviewed; there was no horizontal overflow or page error. No new focusable
controls or focus changes are introduced by the status line. The persistent
review preview has separate explicitly local outage/recovery controls.

The last review also covered indefinitely lost recovery replies and a read trying
to regress behind a majority-observed revision. Receipts stay bounded; local role
backup flags are published before unfencing so work accepted immediately after
recovery cannot lose its pending-backup flag. Initial sandbox thread hangs,
fixture ID corrections, mutation harness exact-match/bytecode fixes and final
assertion evidence remain in private logs; they are not reported as live results.

No production database index/schema change is required. The opaque write_token
field is additive Mongo head metadata; format-1 payloads and old readers remain
compatible for code rollback. The existing copy/role storage owners retain their
boundaries. This batch has no live role, nickname, notification or settings test.
After Claude ACCEPT and scoped owner approval, activation needs fresh backup/test
restore, protected state and staff-write proof, no queued Standardize/bulk work,
readiness, rollback and public hashes. A necessary bot restart requires the
210-second drain. Ordinary post-release timing, skips, connection/transfer rates
and Claude read-only smoke remain required; a local build is not deployment.


## Prompt 105 rework checkpoint

The earlier whole-workflow CSOT contexts were incorrect: Mongo’s absolute block
deadline included non-Mongo waits and was inherited by spawned tasks. The shared
driver’s timeoutMS is per operation; the bridge applies its shorter bound only
inside collection/cursor calls. See [MongoDB CSOT documentation](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/csot/).

Fast aggregate worker timings now use DEBUG; slow steps retain INFO. SQLite-open
failures are inside the guarded recovery path. The uncertain-save message asks
staff to wait for recovery and check the result. Formatter-only changes in four
legacy files were restored using AST-identical statement replacements, preserving
all semantic changes. Final real-Mongo, mutation and full regression evidence is
still pending; this checkpoint is not READY.

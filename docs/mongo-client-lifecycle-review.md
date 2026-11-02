# Mongo client and idle-work review

This is an in-progress prompt 97 batch, not a release checklist or READY verdict.
The campaign projection/read fix was already released separately as
campaign-read-footprint-1. No repeat activation is needed.

## HTTP pool ownership

The dashboard now owns one async Mongo client from its first cleanup context.
Its consumers stop before that context closes the pool. Todo clan history and
FWA outcomes, family-clan lookup, the Manage bridge and server-management
adapters reuse it. Request authorization remains per request. Existing explicit
adapter test injections are retained, and unavailable Todo messages are
unchanged. Constructing a routed client creates collection handles, not indexes.

The async pool has appName `wu-dashboard-http`, maxPoolSize 20, server selection
budget 5 seconds and default operation budget 15 seconds. Per-operation CSOT
contexts retain Todo and family reads at 5 seconds, Manage bridge at 10 seconds
and server-management at 15 seconds. Existing outer Todo seven-second bounds
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

Validation so far uses fake adapters and isolated HTTP fixtures, not live Mongo
or Discord. Tests cover all five async paths sharing one startup pool, operation
budgets, parallel avatar requests still authorizing individually, unavailable
messages, app cleanup once and standalone provider cleanup once. Full prompt 97
regressions, real Mongo and required mutants remain before READY.

## Worker and recovery checkpoint (not READY)

The bot pool is named `wu-bot`, limited to 20 connections per server, with a
3-second selection budget and 30-second default Mongo operation budget. The
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
cached. Expiry sweeps and bulk activation have a minute cadence. The ten-second
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
by recovery. The lifecycle keeps retrying recovery instead of requiring restart.
While fenced, the existing API error surface says storage is recovering and saves
are temporarily unavailable, with a reminder to check saved results before retry.

Checkpoint validation: 91 integrated fake/fixture tests passed, one optional Mongo
skip. These include late original CAS after fencing, original CAS winning during
fencing, lost recovery acknowledgement, foreign owner/newer revision, corrupt
image, failed local commit and subsequent recovery, preserved sending/sent
notification receipts, preserved terminal role receipts, paused unproven role
intent, and lifecycle retry/heartbeat resumption. The thread cases stalled inside
the restricted process sandbox; native local runs passed. No production provider
probe, role, nickname, message or settings write was performed.

Remaining before READY: real-Mongo pool/recovery and long-operation checks, required
mutants, full backend/frontend/TypeScript/build/war-reminder gates, explicit transfer
and connection estimates, and final end-to-end review. This checkpoint is not
permission to activate and is not a claim of live delivery or quota compliance.

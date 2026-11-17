# Dashboard writer transactions

Decision 239 A1 (D1, D6, 1071 and 1072): async handlers use
`await store.run_tx(operation)` or `await store.run_role_tx(operation)`. Each
operation receives its SQLite connection on the dedicated single-thread writer.
The complete synchronous body, `BEGIN IMMEDIATE`, revision/receipt checks,
durable publish, commit or rollback execute together. The synchronous `tx()` and
`role_tx()` entry points remain available for synchronous tools and worker jobs.
A callback must not return a live cursor/connection or perform asynchronous work.
Upstream awaits must complete before entering the writer, with freshness and
revision checks retained inside the transaction.

Heartbeat and recovery use the same writer ordering. Role progress backups must
also use that writer. Shutdown drains accepted jobs before closing the executor.
Queued cancellation prevents the job from starting; a started job drains to its
terminal result before cancellation propagates;
a cancelled HTTP request does not authorize retrying a notification or undo a
committed receipt. Publish failure retains the existing rollback and poisoned
owner behavior. No durable lease, schema or receipt migration is introduced.

OAuth state is process-local, one-use, hashed, expires after five minutes and is
bounded to 10,000 outstanding entries. The callback still requires a constant-time
comparison with the HttpOnly state cookie. Restarting expires outstanding login
attempts. Authentication start no longer writes or publishes SQLite. Existing
`oauth_states` schema/old rows are retained for compatibility; they are unused.
Login deletes expired sessions in the same transaction that creates the existing
30-day session (D6's explicitly approved future login-time cleanup).

Authentication routes allow 20 requests per rolling minute per validated
`X-WU-Client-IP`. That header is accepted only from TCP peers `127.0.0.1` and
`::1`; Caddy's separately approved configuration overwrites it from the Cloudflare
edge header. Forwarded headers and direct Cloudflare headers are ignored. Missing,
empty, malformed and untrusted headers create no bucket and receive no limit;
local bot traffic never shares a loopback bucket. Buckets expire after a minute
and the map is bounded at 10,000 active clients. At capacity a new trusted client
receives 429 rather than evicting an active client's limit.

This is backend-only work; no page layout, frontend build or browser preview is
required. Fixture regressions cover authorization and revision behavior alongside
writer serialization, rollback/poison, cancellation, responsiveness and OAuth/IP
boundary cases. Tests do not establish live Mongo or Discord delivery.


### Rework 20: constructed publisher receivers

The first 239 builder pass missed the shared announcement test-channel save:
`RosterImageStore(...).configure_test_channel(...)` was constructed inline and
bypassed a guard that only recognized three receiver spellings. Independent
Terra review measured a 0.503-second event-loop stall during a fixture publish.
The save now submits the complete existing service method to `run_writer`;
its transaction, authorization, request validation, revision check and HTTP
response contract are unchanged. No nested transaction is introduced.

The regression exercises this actual authenticated HTTP handler with a slow
publish, checks a 20-ms timer and a concurrent authenticated read, and verifies
the final channel/revision plus rejection of a stale revision. The architecture
audit now follows qualified imported symbols, constructors, import/local/bound
aliases, module aliases, factory/tuple returns, class attributes and arguments
between tracked functions. Publisher identities are derived from the existing
SQLite service owners; an unrelated async Mongo `configure` is distinguished by
its owner. A mutation removing the actual handler adapter must be rejected.
Synchronous helper summaries catch a nested callback invoked directly on the
async thread, while properly submitted writer callbacks remain allowed.

This is bounded source analysis, not an exhaustive Python call graph. Dynamic
`getattr`, container dispatch, star imports/re-exports and externally injected
service implementations still require review. The exact resolved publisher and
caller inventory accompanies the rework artifact; no allowlist hides a known
synchronous publisher in an async handler.

The rework resweep also found two false positives in the old receiver-name
adapter inventory: declaration-ping `claim` and `finish` belong to the async
Mongo owner, not the SQLite image store. Their original plain awaits are
restored. Always-run fake-backed HTTP checks cover live-mode claim, receipt
replay, interrupted finalization, conflicts, permissions and confirmation without
a Mongo opt-in or notification task. The guard separately rejects known async
service methods handed to synchronous writer callbacks, including a purported
`storage.store.run_writer` on a Mongo owner with no such field. The old count of
54 indirect adapters therefore included two unrelated async calls and omitted
one real SQLite publisher; it is historical, not the corrected inventory.


### Cancellation outcomes (audit 239, rework 31)

`run_writer` submits a concurrent future so cancellation can atomically cancel a
not-yet-started job. That path performs no body or receipt cleanup. Once a job
starts, it still drains through commit or rollback before the original
`CancelledError` propagates, including repeated cancellation. No `uncancel` or
transport retry is used.

Image/test/closing claims capture their result only after the complete existing
synchronous service method returns. A cancelled committed claim is closed as
uncertain only if that caller actually acquired it. A replacement captures its
new receipt identity before cancellation cleanup; the deleted original receipt
remains intact. Storage-owned cancellation guards atomically require the exact
actor/receipt/destination and an in-flight state. Confirmed, reused, foreign or
superseded receipts are not downgraded.

An already-known transport result is different from an unstarted claim.
`persist_delivery_result` keeps that existing writer operation queued/running
until it finishes, then re-raises the original caller cancellation. Posted
finishes run outside transport cancellation handlers, so they cannot receive a
second uncertain finish. The same protection covers classified rejection/unknown
results, raffle page acknowledgements and terminal announcement audit writes.
A persistence error still rolls back/poisons normally; cancellation remains the
caller outcome and no additional notification is attempted.

Existing announcement, Lazy bonus, infractions, raffle and push reservation
policies are retained: cancellation can leave an intentionally unresolved
reservation that prevents replay. It is not converted into a retryable failure.
Tests distinguish that existing policy from a newly lost image receipt identity.
Push delivery still retains its claim when a transport result is ambiguous;
confirmed expired-subscription cleanup retains its original deletion semantics.
Pool progress and participation drivers still let cancellation propagate rather
than reporting it as an ordinary failure.

The cancellation artifact records the full boundary matrix and fixture tests
using real SQLite, fake transports and instrumented publish/service-return gates.
These tests prove storage/control-flow behavior, not live Discord or push delivery.

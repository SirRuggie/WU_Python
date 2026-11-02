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
`wu-dashboard-durability` and maxPoolSize 10. This does not change publishing or
poison recovery yet.

A standalone LiveProviders instance caches its own async client and exposes an
explicit close method. HTTP startup instead binds the app-owned pool through a
public method. Provider cleanup never closes a pool owned by the application.
Disconnected fixture startup does not create a client from ambient credentials.

Validation so far uses fake adapters and isolated HTTP fixtures, not live Mongo
or Discord. Tests cover all five async paths sharing one startup pool, operation
budgets, parallel avatar requests still authorizing individually, unavailable
messages, app cleanup once and standalone provider cleanup once. Full prompt 97
regressions, real Mongo and required mutants remain before READY.

## Remaining work

Bot client limits and long-operation inventory; management tick timings and
isolation; idle write/read reductions with readiness preserved; automatic safe
poison recovery without overwriting a newer head; activity boundary/write
regressions and existing TTL confirmation; routine scheduler/Todo log noise;
fixture idle-call comparison, full checks and before/after release observation.
The existing unchanged-hourly activity regression and production TTL evidence
must be retained rather than implemented twice. No quota result is claimed.

# Background job observation

`utils/background.py` keeps process-local successful completion times for named
jobs. `job_health()` returns a detached in-memory observation; there is no HTTP
endpoint, Mongo heartbeat or cross-process health transport. Public health
exposure remains a later item.

`run_periodic(name, job, interval)` runs its first iteration immediately and
waits one interval after completion, preserving the war reminder worker's
60-second cadence. One job name has one active owner. Iterations remain serial;
there is no catch-up burst or retry inside a failed iteration. Cancellation
propagates, and the owned health-monitor task is cancelled and awaited.

The CWL roster bridge uses `once=True` under its existing ten-second APScheduler
admission job. APScheduler remains its only timer. The single in-flight driver,
shared queue lock and heartbeat cleanup remain intact. The management fast poll
continues on its existing one-second schedule and idle admission policy.

A successful iteration updates its UTC completion time and monotonic health
clock. Exceptions and an explicit `False` result do not. CWL reconciliation,
post-readiness, management and heartbeat failures, and partial war-clan failures,
therefore do not report a fully successful pass. After three intervals without a
success, one warning is logged for the outage, including while work is stuck at
an await. The next successful completion logs one recovery message. Wall-clock
changes do not advance health; this monitor cannot run during an event-loop
stall and does not prove production latency.

Failures retain their stack frames but replace exception values and chains with
the exception class, because provider exceptions may contain credentials or
payloads. Signatures use the internal job name, error class and final traceback
location, never raw exception text. The first occurrence gets a traceback; one
repeated-failure warning follows within the five-minute window. Repeats are
suppressed until that window expires. Signature storage is bounded. A successful
job clears its error signatures.

Reminder delivery claims, uncertain outcomes and existing persisted D7 status
clocks are unchanged. A partially accepted Discord message is never retried by
this helper. The in-memory job clock is separate from each clan's stored status.
Optional reaction, emoji, category-name and clan-provider fallbacks catch their
expected transport/parse error families. Cancellation escapes; unexpected errors
are logged and propagated rather than hidden by a bare catch.

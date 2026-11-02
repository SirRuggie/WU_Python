# Mongo client lifecycle release audit

Source PR148 was accepted in Claude 344, with owner approval 303 and proceed 346.
The production-shaped startup correction PR153 was accepted 347 and merged as
`de39a2a4352b727d4fe539d2e5ac7b96faa8c298`, tag `mongo-client-lifecycle-2`.
The failed `mongo-client-lifecycle-1` tag is retained unchanged. No Members-page
or later attention/participation-diagnostics change is part of this tag.

## Failed attempts and recovery

| Attempt | Outcome | Bot starts | Backend startup invocations |
| --- | --- | ---: | ---: |
| Tag1 d3b8cb0 | Native HTTP constructor rejected normalized routes; automatic code rollback verified healthy | 2, forward and rollback | 21 failed starts including 20 automatic restarts, plus 1 healthy rollback start |
| Tag2 first attempt | Startup/public/Mongo gates passed; final SQLite guard rejected only the routine participation last_checked_at timestamp; automatic rollback verified healthy | 2, forward and rollback | 2; no automatic restarts |
| Tag2 guarded retry | LIVE November 2 05:21:57 UTC; full observation and smoke passed | 1 | 1 |

Every bot stop included the full 210-second drain. The two failed attempts each
had a forward and rollback drain. No database was restored, no legitimate staff
edit was erased, and no agent role, nickname, import or notification was sent.
Both failed coordinator/evidence folders are retained. The first attempt's true
restart counts are not summarized as one backend restart.

The first failure exposed a real code/test gap: LiveProviders owns a frozen
mapping of Namespace objects, but the HTTP pool passed it to a raw-settings
constructor. PR153 serializes that public boundary while retaining validation.
Its real constructor/lifecycle and owned Mongo tests catch the original bug.

The second failure exposed a release-helper omission: Claude 340 already allowed
only participation_sync_settings.last_checked_at to vary, but the copied helper
did not carry that exception. The new reader excludes exactly that column.
Thirteen replay/real-copied-SQLite cases reject every other setting column and
row addition/deletion. An automatic timestamp audit found source freshness,
role backup/expiry/prune/progress, lineup and delivery times; all stay strict.
Eight tests cover the new backed-up/quiet role-maintenance gate. No blanket
updated_at exception was added.

## Required safeguards

Fresh SQLite/Mongo backups and isolated restore, canonical/role-progress replay,
exact protected state and staff-audit comparison, no-queued/active-lease checks,
immutable tagged artifacts, real bot interpreter imports, rollback rehearsal and
public asset hashes are required for the successful retry. The successful retry retained exact 3,715 active strikes, 306 accounts, 585 strike
profiles, 279 eligible and 479 member profiles, with exact digests/streaks; no
staff transitions or departure exceptions. It runs backend 1889185 invocation
2992ea253ae847f485a097570d714a21 and bot 1888957 invocation
f19ebca80c514ac399fd8de6b97bc8c7 at de39. Public index-CU02PFMc.js SHA256
07c52ac0e73e68554e7abe8647af1cf8e7f64a4b2453c02b669e06e04fd8270a and affected
feature hashes match the immutable frontend. No rollback occurred on this final
attempt. Across the three attempts there were 5 bot starts/drains and 25 backend
startup invocations (5 explicit restart requests plus 20 automatic restarts).

Before services are touched, the exact staged backend now boots with production
flags, all 51 configured routes and its actual native HTTP pool. Durable storage
uses the real owner on owned loopback Mongo and a copied SQLite database. All
external networking is blocked; isolated config returns 200 and unauthenticated
auth/me 401. Fixture cleanup must complete before proof is written. The same gate
rejects the failed old artifact with its original route error. This tests staged
startup, not live Atlas failover or live Discord delivery.

## Ordinary observation and smoke

The first two observers exited before sampling because activation failed. They
do not count as 30-minute observations. The successful retry received a full
30-minute ordinary observation and Claude read-only smoke before completion.
No forced provider call or artificial campaign edit is part of that window.

Claude 352's read-only smoke passed: runtime/cwd/public hashes matched, web journal
had no warning/error/traceback since 00:22, and bot had zero skips/errors. Signed-in
GET timings were auth/me 41 ms, seasons 49, participation 65, bases 240, Past runs 328
(previously 3,000), Strikes accounts 2,730 and roster 3,165; all 200. The host had 69
TCP connections to 27017 at that point. These are individual smoke observations,
not the 30-minute result or client attribution. Live sends, roles and visual UI
rendering by Claude were not tested.

The full ordinary window lasted 1,800.713 seconds. The selected node's comparable
counters increased 16,501,703 bytes in, 110,029,225 bytes out and 13,991 requests,
with two new connections (0.0666/min). Runtime PIDs/invocations and frontend
remained unchanged; final config was 200 and the public entry hash still matched.
Protected metrics exactly matched the successful activation. Bot/web journals
had zero warnings, exceptions, tracebacks and skipped-job lines in this window.
Both observation and final health are recorded as OBSERVED.

Only slow INFO stages were logged: 26 management_poll samples had median
2,998.79 ms, p95 3,480.85 and maximum 4,724.84; one campaign reconciliation was
1,817.1 ms and one bridge stage 1,897.92 ms. These are censored slow-stage samples,
not the distribution of every job. The roughly 3 second Roster/Strikes smoke
requests remain unattributed; no optional provider/timing probe was run.

Counters are node/server aggregates including other clients, replication and
the observer. They are not cluster totals, isolated client traffic or billed
weekly quota proof. Health checks were initial/final plus full invocation
journals, not continuous endpoint sampling. No real role/send/import or
production outage was induced to test recovery.

PR 154 and PR 155 were bundled after this window as `mongo-followups-1`; see
[mongo-followups-1-release.md](mongo-followups-1-release.md). That release fixes
the generic auth/me attention-clear behavior. No live role or message action
was tested.

# Signup reminder acknowledgement release

`signup-reminders-ack-1` is live at
`e4f9574ca6243fa4a6c3bf33c70acfb662c0f61f` since
2026-11-03 00:20:38 UTC. PR175 was released under owner approval 438 and
Shaka's exact coordinator review 463. Independent read-only smoke passed in Shaka466.

## Source and validation

The clean tagged tree `8998fdc5f929e7a1440bc67a798cde0b5ad89fbd` matches the
accepted integration. Application files match tested source `5a25af21`;
subsequent differences were release documentation. Validation recorded:

- Backend: 6,426 passed, 106 skipped, 267 subtests; frontend: 1,554 passed
  across 268 files, TypeScript and production build.
- Focused acknowledgement checks: 29 frontend and 40 backend, one skipped.
- War reminder checks: 213 backend, one skipped, 35 frontend and build.
- 36 isolated browser cases, including narrow and wide review.
- Exact production-shaped boot: 51 routes, configured native pool, real owner,
  copied SQLite and owned Mongo, external networking blocked, config200/auth401,
  source hash and cleanup proof.
- Actual bot interpreter: 13 exact archived modules, Hikari 2.6.0, networking
  blocked, structured source/interpreter/module/log/attempt/cleanup receipt.

The bot also advances from 343d961 to the reviewed main ancestry, including
weight storage, Warrior core, bridge and reminder changes already live on web.

## Fresh release gates and actual runtime

One watcher waited for an ordinary capture, then completed fresh backup,
isolated restore, canonical recovery, protected-state and staff proofs,
no-queued-work checks, native boot, imports and rollback rehearsals. The owned
restore Mongo was stopped and removed. No provider capture was forced.
The pre-activation protected snapshot contained 3,712 active strikes across 303
accounts, 587 strike profiles, 274 eligible replacement rows and479 member
profiles. All73 existing SQLite tables and raw predecessor rows stayed protected.

One fresh bounded Mongo stored-time observation at 00:11:50 UTC passed the
00:14:49–00:29:49 UTC persisted window with no stop/wait reasons or new family.
The old23:07 observation was retained and never reused. This is a snapshot of
named persisted schedules, not a guarantee of world quiescence.

The single coordinator run, foreground session93426, exited0:

- Bot PID 3524544, invocation `db050af374d249dda5a121db81dc0206`, revision e4f9574.
- Backend PID 3524716, invocation `b5da1c7cf0114c868f2bfc1752b675df`, immutable
  backend directory e4f9574. Frontend also uses immutable release e4f9574.
- One bot start and one backend restart, with the full 210-second inactive lease
  drain. No rollback or database restore occurred.
- The unchanged 44ee guard accepted 153 exact presence-row updates; no unexplained
  category hold was used. SQLite/configuration and captured staff proofs passed.

Both enabled war callbacks produced successful post-start fetch observations:
220.278691 seconds after the actual stop request, with readiness at 223.011442
seconds. Two of two succeeded; first/current errors, missing successes, invalid
metadata and settings changes were zero. This is fetch metadata written before
due handling, not evidence of reminder delivery. No possibly-missed flag resulted.
No numeric full-strike-pass line had been observed at postflight.

The source-reviewed category response remains available: an unexplained
strike/member-only difference keeps the release running for human review, writes
BLOCKED with no live receipt, and preserves the original guard rejection. Mixed
or other protected categories, SQLite, schema, runtime, health or journal failures
still trigger rollback. This response did not activate in this release.

## Public verification and limits

At00:22 UTC, actual invocations, bot HEAD, immutable frontend and affected asset
hashes matched the live receipt. Public entry `assets/index-D02YxgsX.js` has SHA256
`148b291208a6107542a24080bad93172c1e0e7b4570a935a4bc2a2bd2dff9b7e`.
Config returned 200; `/api/cwl/auth/me` returned 401 without authentication.
Bot and web invocation journals had zero warnings, errors, tracebacks or critical
lines in that observation. An initial independent probe used the wrong auth URL;
the corrected route passed. That probe changed no application state.

Acknowledgement means that the future schedule for the current policy is loaded.
Overdue catch-up remains a separate 144 change. No live Save, notification,
Discord edit, role change or delivery test was performed by the agent.

Shaka466 read-only smoke passed in Ruggie's session: actual frontend/backend/bot
revision matched, and warning-level journal lines since 00:16 UTC were zero.
Signup reminders opened at 375 and 716 pixels without overflow, showing On,
real destination/role names, no waiting warning and the first send on November 22
at 1:00 AM. Schedule and Delivery history opened; the last 25 API calls returned 200.
Four older 502 console entries remained: restart timing is an inference, not a
confirmed cause, and they were not observed again after the check.

Live limits: 1440 pixels was not available in the review pane; no Save, Pause,
Edit or actual send was tested. Raw delivery-history labels and overdue catch-up
are queued for 144. No notification delivery or changed schedule is claimed.

Private evidence is retained under `.local/signup-reminders-release-1`, including
`live.json`, `activation.log`, `first-scan-proof.json`,
`post-live-verification.json`, fresh backup/restore references and source-bound
schedule proofs. Old bot 343, backend e919 and frontend c55 rollback assets remain.

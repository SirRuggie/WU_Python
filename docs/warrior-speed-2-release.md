# Warrior speed and confirmed partial results

Accepted PR122 (`cb9c5e6`) and PR126 (`eae0454`) released together as
`warrior-speed-2`, revision `4b421818a77fd937ba2e1f67d8c1ff140d6fce8e`.
The earlier `warrior-speed-1` tag was staged only. Combining the accepted follow-up
before activation preserved Strikes usability and identity recovery from main.

Display reads reuse cache, while real writes retain fresh guild, actor, target,
bot and role authorization. The nickname step opens promptly; Quick Setup and
Town Hall results retain confirmed role changes after a later phase fails and
provide Return without offering an automatic repeat. Zone-picker labels use
familiar abbreviations and country filtering without changing nickname syntax.
Existing two-hour New Recruit cleanup and one-hour failed-cleanup retry remain.

The release used fresh SQLite backup/integrity, Mongo backup and isolated test
restore, exact protected-state checks, actual bot-interpreter imports with network
blocked, a clean tagged archive/frontend build and a mocked rollback rehearsal.
Validation included 114 merged guarded Warrior/identity cases. Prior full feature
checks and approximate isolated wizard layouts are recorded in the PR review docs;
mock panels do not prove live Discord role or nickname delivery.

At activation the bot was PID1120961/invocation
fed0c6ff23f448958327cba70a846786 and backend PID1121090/invocation
5eb72f9919b04d5bb396377a1fb7dcd1, with frontend4b. Public
`index-BVlLredv.js` SHA256
`3d2a7df8d4fa0e4abe2ec67d6f106a3b7104d4af52a5bd8363f391c84ee641a5`
and affected feature assets matched. Two-sample service readiness and startup
journals passed. Protected state remained 3,560 active strikes across301 accounts,
581 strike profiles and274 eligible replacement accounts, including exact
streak/replacement, member-profile/settings and SQLite digests.

The first attempt used an unnecessarily privileged process-cwd read and failed
when sudo root required interactive authentication. Automatic rollback restored
the prior revisions and healthy services, although that same verification failed
after restoration. Independent inspection confirmed the rollback. The check was
corrected to read the process as its botrunner owner, and the guarded retry passed.
Extra restarts occurred; this was not a one-restart rollout. No database restore
or agent-run role, nickname or message test occurred.

Ruggie separately reported a real successful Set nickname. A read-only check found
one Warrior profile and a matching saved timezone/country nickname suffix, without
publishing the member's identity or performing another rename. Claude SMOKE258
passed the runtime/assets and identity page read-only. Claude did not exercise
Warrior panels; real click timings remain an observation from ordinary staff use,
not a claimed performance result from mocked tests.

Evidence: `.local/warrior-speed-release/{live.json,activation.log,
activation-retry.log,failure.json,rollback.json,rollback-rehearsal.json,
human-warrior-readonly.json}` and the immutable release manifest. Rollback retains
bot ea8e238 and backend/frontend63c999b with code/assets only, never data. The
later accepted Member time zones worker/Declaration release preserves the Warrior
changes and uses the newly required 210-second lease drain; its separate rollback
and restart history is recorded in its own release evidence.

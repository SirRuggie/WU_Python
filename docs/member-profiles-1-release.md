# Member profiles 1 — October 31, 2026

PR [#117](https://github.com/SirRuggie/WU_Python/pull/117), tag
`member-profiles-1`, revision `ea8e238ccac9861d37b7a25a758a09aa12987289`.
Claude ACCEPT230 verified source `9d1c52f`; deployment used its clean merge/tag.
Live at 22:26:03 EDT across bot, backend and immutable external frontend.

Warrior nickname setup suggests the highest-TH name, asks on ties/partial data,
and previews the canonical name, standard GMT offset and country flag before
one authorized edit. Revision checks and consumed receipts prevent stale or
repeated edits. Definite Discord refusals retain real field reasons; confirmed
Discord success remains distinguishable from uncertain profile storage, including
when Return abandons a wizard. Compare uses saved profile zones with nickname
fallback. Existing roles, hierarchy and other setup steps remain.

The bot runs PID869140, invocation27d616ab20c1432a9b59b8bf7cb5fd81, from
/home/botrunner/wu-bot at the tag. Backend PID869273, invocation
72ba5761744345bca9acc2a828099eb5, runs the immutable backend/ea8e238 directory.
One bot restart followed a 210-second identity lease drain. Both actual virtual
environments passed network-blocked import checks, two readiness samples passed,
and startup journals had no tracebacks. The Warrior extension loaded and the
retention scan reported zero profiles. Unrelated service configuration was kept.

Fresh SQLite/Mongo backup and isolated restore passed. Protected state stayed
exactly 3,560 active strikes across 301 accounts, 581 strike profiles and 274
eligible replacement rows, with identical streaks before/stopped/after bot/after
activation. SQLite protected state passed before activation and its final lineup
guard passed. The separate settings.member_profiles namespace was absent before
activation and is intentionally created empty, with the standard _id index and
member_profile_left_90d on left_at (7,776,000 seconds). No existing profile data
was migrated, no import or Standardize ran, and no live nickname test was sent.

Public entry assets/index-CPKPp8Ay.js SHA-256
`a5439f12282e65fac4968c50eb3a114697ae7544da52a938e5beeaccf5400856` matched the
immutable manifest, as did selected Roster/Compare/Strikes JS and CSS. Source and
archive bytes were checked; workspace dist was not used as a deployment target.

Validation: 36 focused cases; 5,532 guarded backend cases plus 221 subtests (29
skipped); 1,248 frontend cases across 230 files. Earlier three real-Mongo cases, seven killed mutants, build and eight integrated
layout stages passed before the final wording delta. Review232 later found one
stale real-Mongo assertion expecting the old storage-outcome text; that current
lane is not claimed green and is being corrected on PR119. The prior run must
not be represented as a pass for the changed assertion. Narrow
and wide fixture UI uses simulated transport and is not evidence of live Discord
delivery. Claude's final isolated delta check passed 77 cases.

Rollback retains 8087c6917da80b989d619ef34f819085f1af25f8 for bot/backend/frontend,
checks boundaries and readiness, preserves documents and never restores a live
DB. Only a TTL index created by this release may be removed during an actual
rollback, after verifying its exact key/options. The coordinator passed a mocked
rehearsal; an isolated Mongo rehearsal proved index rollback preserves a profile
document. Production rollback was not executed.

Evidence /tmp/wu-member-profiles-release includes live.json, activation.log,
backup-result.json, backup-folder, protected snapshots, profile-index-before.json,
profile-index-after.json, backend-file-hashes.json and both rollback rehearsals.

Claude read-only SMOKE231 passed: correct revision/hash/PIDs, no tracebacks,
Warrior extension and retention worker ready, 563 Strikes accounts, roster
owner_timezones plus 93 nicknames, no overflow at360. The previously unidentified
503 appeared once; it remains closed as non-blocking per228. The wizard itself
was not exercised. WAIT425 gives Ruggie exact command/target/preview/verification
and restoration steps. His real Warrior result remains required before PR2
release; Codex will not perform that nickname edit. PR119 is also in rework232.

# Warrior display latency

Prompt 68 uses gateway guild/role/member objects for display. The configured
GUILDS and GUILD_MEMBERS intents are enabled in main.py. No cache_settings override
is passed: installed Hikari CacheSettings defaults to ALL components and
only_my_member=False. A missing guild/member, or incomplete role view, falls back
to REST. Remaining context reads run concurrently with the recruitment-config
Mongo read. Hikari's existing rate limiter and max_rate_limit are unchanged.

Every role mutation obtains a new REST context immediately before that member's
individual operation, rechecking recruiter authorization, actor/bot hierarchy,
managed/privileged roles, and the actual target's current roles. Nickname commit
still obtains fresh context inside the profile lease, after consuming the
one-shot target-bound preview. Display cache cannot authorize either write.
Role changes refresh only the target for the following display. Administrator
setting submission also refreshes context rather than trusting the display cache.

Nickname opening renders Checking linked accounts… and Type a name before the
linked-account lookup starts. Background completion edits the same private
response; lookup failure leaves manual entry available. Nonce/step CAS and a
per-session update lock prevent a late result from replacing a newer step or
Return screen. Opening a typed-name modal marks manual entry without changing its
nonce: the lookup may populate choices but cannot auto-advance or invalidate the
form. Background tasks are cancelled and awaited on bot shutdown.

## Measured fixtures

`tools/measure_warrior_speed.py --baseline 4309652` and the same command without
--baseline run fake transport/storage only. The baseline source is loaded from
that exact git revision without installing its component handlers. REST reads
sleep 20ms, the config read sleeps 10ms, and linked lookup sleeps
20ms + 5ms/account, returning 1, 10 or 47 synthetic account rows.

| Phase until display can render | Before ms | After ms |
| --- | ---: | ---: |
| Open panel authorization/read phase | 111.24 | 10.38 |
| Open step authorization/read phase | 111.49 | 10.31 |
| Nickname step after context, 1 account | 26.11 | 0.34 |
| Nickname step after context, 10 accounts | 71.15 | 0.33 |
| Nickname step after context, 47 accounts | 256.42 | 0.37 |

These are synthetic read/render phases, not complete Discord interaction delivery
latencies. Panel/home rendering and actual response delivery are not timed by
this fixture. A separately measured fresh parallel context took 22.23ms with the
same delayed fake transport. The lookup itself still takes the simulated time;
it no longer blocks opening. Production click totals and individual REST/Mongo
read timings are logged at INFO (`warrior timing`, operation, interaction ID,
guild/actor/target IDs, elapsed_ms); no nicknames/account names are logged.
Real after-release timings remain to be collected after an authorized release
and normal human interaction. No live test message or rename was performed.

## Validation and limits

Focused checks cover cache hits, missing members/roles and 404 fallback, stale
cached recruiter/bot permissions, authorization loss between two role writes,
immediate lookup display, late results, manual entry, background failure,
Return invalidation, and ID-only timing output. Mutation tests replace final
fresh authorization with cached reads and remove both background nonce guards;
both must be killed. The two independent nonce barriers are tested together for
the latter behavioral mutation; deleting only the early check is still guarded
by the storage CAS.

The inherited real-Mongo assertion expected the pre-66 phrase “profile not saved”.
It now expects “profile save not confirmed”, matching the deployed behavior;
this is a test correction, not a change to rename/save outcome semantics.

This branch does not contain prompt 65 or dashboard PR119 changes. No schema or
index migration is needed. Deployment requires Claude ACCEPT, the usual fresh
backup/test restore/protected-state gates, one bot restart, readiness, journal
and public asset verification, rollback to the previous immutable release and
Claude's post-release smoke. Ruggie's required real nickname test remains a
separate human gate for PR119; record the revision that test actually covers.

Final checks: 5542 guarded backend passed, 29 skipped, 221 subtests; 1248 frontend
in 230 files; tsc/build; 72 focused Warrior cases; three actual isolated Mongo
cases; both behavioral mutants killed. The first full backend run had one source
scan failure because the owned mutant export was nested under .local; moving it
outside the checkout and rerunning the complete frozen-source suite passed.
All Mongo daemons owned by these checks were stopped. No migration or live rename.

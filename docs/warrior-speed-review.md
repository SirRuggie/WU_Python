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
Restart, paused-run retry and public walkthrough preparation likewise refresh
write authorization before changing progress or granting thread access. Even an
empty role batch checks the current actor and target. Display cache never
licenses those writes.

Nickname opening renders Checking linked accounts… and Type a name before the
linked-account lookup starts. Background completion edits the same private
response; lookup failure leaves manual entry available. Nonce/step CAS and a
per-session update lock prevent a late result from replacing a newer step or
Return screen. Opening a typed-name modal marks manual entry without changing its
nonce: the lookup may populate choices but cannot auto-advance or invalidate the
form. Non-modal interactions acknowledge before waiting for that lock; modal
openers respond immediately without waiting. The background CAS preserves a
concurrent manual-name choice. Background tasks are cancelled and awaited on
bot shutdown.

Role batches retain and audit confirmed partial results when authorization is
lost after an earlier successful operation. Cancellation records an interrupted
outcome before propagating. Audit-storage failures log an explicit warning and
return confirmed Discord results without retrying the writes. Failure text is
rendered first so a large result list cannot truncate the interruption warning.

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

Prompt 70 validation: 84 focused Warrior cases and three actual isolated Mongo
cases passed. The earlier report claimed six killed behavioral mutants. Claude's
entry251 refuter found that the between-role read mutant survived, so that claim
is corrected: it was not established by the old aliased REST/cache fixture. The
other reported cases were cached final rename guard, missing interaction lock,
missing background load lock, cached settings authorization and omitted shutdown
cancellation. The follow-up below adds detached-object role-definition evidence.
The final combined70/73 guarded backend result is5556passed,29skipped and221subtests; all owned Mongo fixtures stopped.
Combined73frontend validation is1249tests/230files,tsc/build;20wizard scenarios at360/1440 include visible AU/US/all-zone menus.
All owned Mongo daemons stopped. No migration or live rename was performed.

Prompt73 is included before READY so the zone picker shares the same bot restart.
Its country maps and regional alias labels are shared data; country options page
at24 plusOther, and full zone choices remain within25. Display abbreviations
never enter a nickname. Dashboard editor integration is carried on PR119 before
that feature's release. Full combined validation is recorded in the handoff.

## Partial role results and no-op reads (entry251 follow-up)

Quick Set-up and Town Hall changes have an addition phase followed by a removal
phase. If authorization is lost between them, or a later display read fails, the
panel now keeps confirmed additions/removals and their counts beside the reason
the operation stopped. The same protection covers individual and clan-role
actions. A partial panel offers Return only; it never retries the role writes.
Mention parsing remains disabled. Text is bounded in UTF-16 within Components V2
limits. Audit behavior is unchanged: the storage owner retains confirmed partial
results and warns if the audit itself cannot be saved.

Known no-op roles share the batch's initial fresh authorization context. The
two-item no-op fixture now makes five REST reads total instead of ten (one guild,
one role directory and three members), plus its normal config read and audit.
Every actual write after an earlier attempt still obtains all five fresh REST
inputs and re-evaluates actor/bot hierarchy, permissions, role definitions and
the target's roles. Avoiding fresh metadata for real writes would miss changed
role privileges or guild ownership, so this optimization deliberately reduces
no-op reads rather than reusing authorization for writes. Role changes remain
incremental PUT/DELETE operations; a full role-list PATCH could overwrite unrelated
concurrent edits and is not used.

The new role-definition regression keeps gateway and REST objects detached, makes
the second role privileged after the first write, and verifies that the second
write is refused. This is the required protection against a surviving fresh-read
mutant, rather than mutating a shared fake object that also changes the cache.

The existing cleanup at `extensions/warrior/walkthrough.py` removes the run's
configured New Recruit role two hours after a successful tour completes. It
marks `cleanup_done` only after Discord accepts removal; failure leaves it pending
with a one-hour next-attempt time. The legacy cleanup is separate. This follow-up
documents that behavior and does not alter cleanup, tour scheduling, persistent
schema or delivery retries.

Tests and approximate Discord previews use isolated fake data. No role edit,
nickname write, live message or human Warrior test was performed by the agent.

# CWL groups without a season

Prompts 107/108/110 follow ordinary capture diagnostics in handoff 671. At
06:23:52 UTC on November 2, seven normalized groups had no season value:
four `ENDED`, three `PREPARATION`. Three other clans returned leaguegroup 404.
No agent provider probe or Check Clash request was made.

## Month attribution and completion

A valid missing-season `PREPARATION`, `INWAR` or `WAR` group is attributed only
to a selection equal to the current UTC month. This is the explicit inference
requested in prompt 107, not a verified provider contract. Explicit month values
always win. The state restriction applies only to the missing-month path;
explicit-season responses keep their existing validation behavior.

Missing-season `ENDED` is captured only if its nonempty set of real war tags
contains all of that clan's nonempty stored real tags for this season and
cycle. Prompt 110 changes the earlier equality rule: final groups may add
previously unobserved later rounds. Containment is proof, so it also permits
finishing a past, nonarchived selected month after UTC rollover. Mere overlap,
empty stored tags or another season's records do not qualify. Archived seasons remain read-only. Explicitly mismatching war
months still fail closed, and an inferred group referencing such a war is not
stored or exposed to Results/Bonus allowance readers.

Seven ended wars followed by a matching missing-season final group now set
`source_complete=True` and satisfy the existing Bonus completeness gate. The
original immutable-ended-war cache policy remains: reused observations keep
their old checked timestamp and can be labeled stale; they are not presented
as newly fetched wars. Source completeness and cached freshness are distinct.

## Waiting is per clan

The predicate is keyed by season ID, selected cycle and clan. A clan's own
stored group with real, non-`#0` tags is month evidence. Fetches/observations
belong to that clan only through those group tags; another hosting clan's
response or global scanned-clan list cannot end its wait.

A valid older group, leaguegroup 404, or missing-season group that is not
attributed to the selection can wait only for the current or upcoming month
and without that clan's own month evidence. Missing-season active groups for
next month wait without being captured into the future. Past selections never
guess. Shape, ownership, roster and round validation still precede a wait.

One predicate supplies both row and overall behavior. Waiting rows retain
unknown counts and the month-specific hasn't-started text. Fresh active groups
plus only waiting clans produce partial progress without an outage warning.
No fresh groups produces waiting. Healthy mixed captures advance last-success
time; real outages, 403, timeout, malformed data and conflicting own-month
evidence keep warnings. Nothing is marked complete early.

Two older expectations changed deliberately under prompt 108: an old clan
alongside another clan's current war now yields neutral partial progress while
keeping scores; prior-war warning tests seed the affected clan's own group tags
rather than unrelated global fetch evidence.

## Boundaries and evidence

Group diagnostics log a validated clan tag, whitelisted state and boolean season
presence/inference/tag-proof values, never response bodies. Results and Bonus
consume cycle-keyed observations rather than independently guessing raw group
months. The strict group validator receives a local effective copy; normalized
provider evidence remains unchanged. No schema migration or polling was added.

The official [API documentation](https://developer.clashofclans.com/#/documentation)
was checked read-only. Its JavaScript shell exposed no readable specification
of when season is omitted. Existing normalization preserves absent/null season
as `None`; safe recorded diagnostics establish those seven values, not a general
API omission rule. Isolated tests are not evidence of live November delivery.

Checks include consecutive mixed captures with real war tags for missing-season
ENDED, 404 and explicit older groups; own evidence, per-season scope, next-month
waiting, seven-war completion and Bonus eligibility, contained versus overlapping
tags, rollover, archives, mismatching-war rejection and unchanged outage/cache
freshness. Mutation evidence and final suite counts accompany the READY entry.
Release remains held pending Ruggie's approval and Claude's review.

Prompt 110 checks also cover every unreadable state on first and later captures,
neutral mixed captures with cached ended wars, a lagging sixth-round group
finishing with seven rounds, and separate guards on fresh-group success stamps,
failure-free stamps and rejected-clan freshness.

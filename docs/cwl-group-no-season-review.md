# CWL groups with an unreadable month

Prompts 107/108/110/114 follow ordinary capture diagnostics in handoff 671. At
06:23:52 UTC on November 2, seven groups were logged with reason `missing_month`:
four `ENDED`, three `PREPARATION`. This was misread as an absent season.
The first live capture after PR158 still failed. Provider validation and capture
control flow prove that these responses contain a string failing the month
pattern, not None. The exact value is unknown and is not proven empty. Three other clans returned leaguegroup 404.
No agent provider probe or Check Clash request was made.

## Prompt 114 correction

An unreadable month string now follows the same no-month rules as an absent or
null season. This includes empty, whitespace, malformed dates, words and invalid
month numbers. No raw value is logged. Group diagnostics classify season_kind as
none, empty, invalid or valid; invalid values have a shape capped at 12 characters
using d for digits, a for letters and x for everything else. Explicit valid months
remain authoritative, and war-month conflicts still reject inferred groups.
Provider-level regressions pass raw stubbed HTTP bodies through the real public
league_group parser before capture. No live API probe or forced capture is used.
Release of this correction is held for Ruggie. The next ordinary post-release
capture is required before claiming the production issue works.

In the rules below, "missing-season" means None or an unreadable string under
prompt 114. It is a capture classification, not a claim that the provider omitted
the season key.

## Month attribution and completion

A valid missing-season `PREPARATION`, `INWAR` or `WAR` group is attributed only
to a selection equal to the current UTC month. This is the explicit inference
requested in prompt 107, not a verified provider contract. Explicit valid month values
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

Group diagnostics log a validated clan tag, whitelisted state, boolean season
presence/inference/tag-proof values, season_kind and a masked shape capped at
12 characters, never a raw season value or response body. Results and Bonus
consume cycle-keyed observations rather than independently guessing raw group
months. The strict group validator receives a local effective copy; normalized
provider evidence remains unchanged. No schema migration or polling was added.

The official [API documentation](https://developer.clashofclans.com/#/documentation)
was checked read-only. Its JavaScript shell exposed no readable specification
of when season is omitted. Normalization preserves absent/null as `None`, but
the seven production failures are invalid month strings, not None. The original
reason code did not reveal their exact value or shape; no general API omission
rule was established. Isolated tests are not evidence of live November delivery.

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

### Group-season reader audit (114)

The public provider rejects non-string/non-null season values but deliberately
preserves the raw string. `_fetch_groups` is the only normalized group-season
consumer: it classifies the value, validates a local effective copy, and applies
explicit valid month comparison. `_valid_group` retains its strict supplied-month
check. Stored group/war readers use the season/cycle keys, not an independent
raw-season inference. The separate Todo coc.py group reader uses state and rounds,
not the group season. War-season validation and explicit-war mismatch rejection
remain unchanged. No provider method was called live for this audit.

## War month correction (prompt 115)

Groups and wars now share one no-month predicate: null or a string failing the
strict cycle pattern carries no month evidence. A valid different war month
still rejects an inferred group, prevents group storage and never captures an
allowance. This applies at rejection, war filtering and allowance capture.
Non-string malformed values remain rejected by the public provider parser.

Each capture logs one war summary: counts of none/empty/invalid/valid month kinds,
at most five distinct masked shapes (each at most twelve d/a/x characters), and
the month mismatch count. No raw month value or response body is logged.

Regressions use the real league_war parser over stubbed HTTP bodies. An active
inferred group captures seven wars, then a matching ENDED group proves complete
counts. Absent/null/empty/date/word/same-month values are covered; an older valid
month leaves no group row or allowance capture. These are isolated fixtures,
not proof that production capture works. After an approved release, the next
ordinary capture must establish the production result without a forced probe.

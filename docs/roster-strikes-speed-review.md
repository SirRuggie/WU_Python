# Roster and Strikes speed investigation (prompt 113)

The local Roster **UI** read is already below one second. Its legacy plain API
read deliberately waits about three seconds for slow live metadata. The current
Strikes UI uses a different route from the ledger read: the activity overview
was about 0.36 seconds locally, while the ledger was about 0.08 seconds. Neither
local UI fixture reproduces the reported production delay. No live API or
production timing was performed, so production authentication, Atlas, provider,
transfer and browser contributions remain unattributed.

The one runtime change is a bounded, projected profile read in
`StrikeService.account_list`. This reduces the **ledger** route's data and RPCs;
it is not a claimed fix for the activity overview or for production's 2.73 seconds.
There is no schema, index, permission, route, response, cache or polling change.

## Routes and method

The original report timed `/seasons/1/roster` and `/strikes/accounts`. Their query
strings were not established by that report. Source audit makes these distinctions
necessary:

| Path | What the current page requests |
| --- | --- |
| Roster | `/seasons/:id/roster?background=1` for initial read, refresh and metadata retries |
| Legacy Roster API | Plain `/seasons/:id/roster`, which waits for metadata |
| Strikes overview | `/strikes/accounts?activity=true`, not `account_list` |
| Strikes ledger | Plain `/strikes/accounts`, also used with an exact tag when opening account details |

Tests used local HTTP servers, copied application code, owned Mongo on 27164,
an isolated SQLite database and fixture providers. Authorization was replaced
by a neutral fixture; its transport cost is excluded. Activity identity was a
warm snapshot, so no real link or Discord lookup occurred. Roster cold clan and
player providers slept four seconds to test the existing three-second response
budget; weights and family metadata were fixture results. External networking
was blocked, and all fixture servers/databases were removed afterward.

The expanded fixture has 3,715 active strikes across 306 accounts, 7,300 retained
records, 586 strike profiles and 587 activity documents (581 players plus six
clan history rows), with fourteen saved wars and thirteen raid weekends per
player. Its activity documents total 3,661,047 BSON bytes before projection.
These counts approximate the historical audit's 7,300 records, 583 profiles and
587 activity documents; they are sample data, not exported production rows.
Roster has 125 signup accounts. Response bytes below are uncompressed JSON.
Mongo bytes are sums of returned BSON documents, **not TLS bytes or billed quota**.

## Measured results

Current-code old-cursor/final-cursor ledger measurements alternate five times on
the same database. Other routes have three samples. The legacy cursor is restored
only at the public profile `find` boundary; all data, filters and response code
remain identical. Ledger and activity response bodies were byte-identical
between cursor variants and samples within each seeded fixture.

| Read | Median HTTP time | Response bytes | Concurrent `/seasons`, sampled maximum |
| --- | ---: | ---: | ---: |
| Ledger, old cursor | 77.823 ms | 11,057 | 13.241 ms |
| Ledger, projected/bounded cursor | 67.947 ms | 11,057 | 15.199 ms |
| Activity overview, unchanged | 356.995 ms | 583,651 | 28.573 ms |
| Roster UI, cold metadata | 16.091 ms | 136,198 | 7.567 ms |
| Roster plain API, cold metadata | 3,029.435 ms | 132,823 | 22.999 ms |
| Roster UI, warm metadata | 15.653 ms | 144,039 | 8.055 ms |

A second unchanged activity sample set had median 372.432 ms and maximum
concurrent-season latency 42.903 ms. This variation is not attributed to the
ledger-only optimization. Concurrent requests were repeatedly issued during
each measured request, rather than relying on a single probe to hit a CPU loop.
The activity row assembly itself is synchronous for about 80 ms: it briefly
blocks the event loop, but does not reproduce a multi-second CPU stall. Roster's
metadata wait yields to the event loop. Neither route uses the per-member role
permission loop found in prompt 112, so no second copy of that fix was added.

### Stages

Stage measurements are local wall time around the named operation. Nested stages
are **not additive**: `activity_context` includes its Mongo reads, and Roster's
`_auto_plan` calls `_roster_rows` and `_rule_rows` again.

| Activity overview stage | Median | What it includes |
| --- | ---: | --- |
| Activity overview read | 44.720 ms | Projected activity documents, driver decode and await |
| Strike context | 188.343 ms | Profiles, projected retained records, replacement reads and settings |
| Failed-clan history read | 7.198 ms | Projected failed clan tags, not saved lineups |
| Row assembly | 80.909 ms | `family_activity_rows`, synchronous calculation over saved snapshots |
| Weights | 6.396 ms | Saved SQLite lookup and immediate fixture provider |
| Weight overlay | 4.291 ms | Current saved/legacy weight precedence |
| JSON | 3.499 ms | Existing response serialization |

Activity context reads all 7,300 matching **projected retained record documents**
in this fixture. Across the whole route, fourteen Mongo query/cursor operations
return 2,825,660 BSON document bytes. Profiles are read twice: once for context
and again by the existing replacement calculation. Clans are also queried twice.
The already-deployed activity projection excludes the large per-unit baseline;
this is not a newly discovered missing baseline projection. Warm identity lookup
has no transport wait in this fixture, and a real missing-weight provider can
wait up to the existing eight-second budget. Those omitted external costs must
not be inferred from the local time.

Roster's two `_roster_rows` calls total about 5.0–5.5 ms, its two `_rule_rows`
calls about 1.8 ms, `_auto_plan` about 3.2–3.7 ms including those nested reads,
and JSON about 0.7–0.9 ms. SQLite trace records 284 route queries, including 250
individual player-weight reads: the 125 rows are assembled twice. This duplicate
work is real, but these measurements do not make it the cause of three seconds.
The plain route's dominant wait is the parallel bounded live clan/location read;
the UI's background route returns cached/unknown metadata immediately instead.

## Ledger fix and indexes

| Resource per ledger request | Old cursor | Final cursor |
| --- | ---: | ---: |
| Mongo query/cursor operations | 8 | 6 |
| Profile reads | 2 finds + 2 getMore | 2 finds |
| Returned profile BSON bytes | 84,232 | 39,154 |
| All returned BSON document bytes | 141,548 | 96,470 |
| Records aggregated on server | 3,715 | 3,715 |
| Grouped account rows returned | 306 | 306 |

Only the five profile fields actually consumed by the account list are returned:
player tag/name, member ID, current clan tag and roster timestamp. `_id` is
excluded. Each existing batch remains at most 200 tags, with `batch_size` and
server `limit` equal to that batch length. The pre-existing `to_list` already
capped results at the same length; the server limit does not truncate an
additional result. The unique guild/player index also enforces one profile per
requested tag.

The first draft set only `batch_size`. An adversarial command trace caught that
an exactly full first batch could leave a server cursor open, moving saved
getMore calls into delayed killCursors cleanup. The final server limit closes
both cursors immediately (`cursor.id == 0`), verified on real owned Mongo. No
background cleanup RPCs replace the saved reads.

The ledger aggregates all matching strikes **on Mongo**, rather than downloading
3,715 raw records to Python. Its existing winning index in this fixture is
`guild_id_1_kind_1_occurred_at_-1__id_1`: 3,715 keys/documents examined, 306 grouped
rows returned. Existing player/member/clan/date and war-key indexes remain.
Profile indexes already include guild/player, guild/current-clan and
guild/departed-last-seen. No index is added or hinted. Exact bounded profile-plan
and activity-plan summaries are recorded with the final evidence; optimizer
choices on a local sample are not promises about Atlas's cached plan.

## Refetch and regression audit

Roster reads on season change, explicit refresh and relevant successful edits.
While metadata is pending it checks after 1.5 seconds, then every two seconds
for at most 90 seconds; hidden pages skip the read. It stops when metadata is
complete or revision/error/authorization handling requires it. No timer is added.

The Strikes activity list reads on mount/reload. Its ordinary filters and paging
are local. Identity recovery currently refetches the **whole activity overview**:
two-second retries for six attempts, then 120 seconds, while visible and idle.
Opening an account detail also requests full `activity=true` alongside the
exact-tag ledger read; the activity route does not narrow by that query. These
existing repeated large reads are potential design work, not changes in this fix.
Tracking status has a separate bounded visibility/focus-aware refresh and is not
the measured account-list request.

The earlier `8c6a65f` tag was exported and run on the same fixture shape with an
import-root assertion and source-file hashes. Its activity median was 356.004 ms,
Roster UI cold 15.951 ms and plain Roster 3,033.301 ms; all response sizes match.
Its unmodified ledger samples were 75.690–82.313 ms. The local plain Roster wait
is therefore pre-existing, and no activity-overview regression was reproduced.
These comparisons do not establish whether production transport performance
changed between releases.

## Limits and next decisions

Both actual local UI paths meet the one-second target in this fixture. Production
2.73-second Strikes attribution remains open. The ledger change removes two read
round trips and about 31.8% of returned document bytes in this sample; it is a
resource improvement, not a production latency or Atlas-quota claim.

If owner-approved natural-request timing is wanted next, separate authorization,
activity/context reads, weight-provider wait, row CPU and serialization before
choosing a larger change. Candidate work includes request-local reuse of already
read replacement inputs, an identity-only recovery payload, or selected-account
activity reads. Each needs freshness, authorization and result-equivalence design;
none is silently bundled here. No general cache or pagination change is proposed
without that evidence.

## Validation and evidence

Validation is in progress. The focused ledger suites pass 86 cases, the real
owned-Mongo equivalence/cursor test passes, all three genuine mutations are
killed (unbounded cursor, default first batch, unprojected private fields), and
frontend 1,484 tests/261 files plus TypeScript/build and war-reminder validation
pass. Full guarded backend and final artifact checks are pending. The runtime
consumer audit finds `cwl_web.strikes.accounts` is the sole production caller of
`account_list`; the shared storage owner remains in `utils`.

The real-Mongo test covers missing optional profile fields, fresh/stale clan
observations, member/name fallback, exact-tag/name/clan/action/status searches,
late pagination, unchanged summary/rows and unchanged stored-record counts.
HTTP authorization and malformed input behavior remain covered by the existing
Strikes suites. No Discord notification test or live delivery claim is made.
Release is held for Ruggie. No services, production data, indexes or live API
calls were changed by this investigation.

Evidence under this worktree's `.local`: `p113-paired-bounded-ledger`,
`p113-paired-current-final`, `p113-paired-old-final`, `p113-mutants`, focused/full
logs and the checked-in owned-Mongo regression. The initial benchmark clock
replacement caused a fixture-only 400; that failure log is retained. One earlier
comparison launcher used the wrong working directory; its output is explicitly
marked `INVALID_COMPARISON` and excluded. The corrected earlier-tag run verifies
its import root and records source hashes. Initial sample counts and bytes differ
from the expanded fixture; they are retained but are not mixed into these tables.

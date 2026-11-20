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
| Activity overview, unchanged | 357.218 ms | 583,651 | 120.341 ms |
| Roster UI, cold metadata | 16.196 ms | 136,198 | 7.799 ms |
| Roster plain API, cold metadata | 3,029.385 ms | 132,823 | 23.045 ms |
| Roster UI, warm metadata | 16.492 ms | 144,039 | 8.179 ms |

The ledger rows above use the final five-pair resource benchmark; the other
rows use the final detailed-stage run. That run separately measured ledger
95.904 → 72.906 ms and unchanged activity 357.218/373.987 ms in the two cursor
variants. An earlier same-shape activity sample was 356.995 ms. This variation
is not attributed to the ledger-only optimization. Concurrent requests were repeatedly issued during
each measured request, rather than relying on a single probe to hit a CPU loop.
The activity row assembly itself is synchronous for about 83 ms: it briefly
blocks the event loop, but does not reproduce a multi-second CPU stall. Roster's
metadata wait yields to the event loop. Neither route uses the per-member role
permission loop found in prompt 112, so no second copy of that fix was added.

### Stages

Stage measurements are local wall time around the named operation. Nested stages
are **not additive**: `activity_context` includes its Mongo reads, and Roster's
`_auto_plan` calls `_roster_rows` and `_rule_rows` again.

| Activity overview stage | Median | What it includes |
| --- | ---: | --- |
| Activity overview read | 40.061 ms | Projected activity documents, driver decode and await |
| Strike context | 190.392 ms | Profiles, projected retained records, replacement reads and settings |
| Failed-clan history read | 7.819 ms | Projected failed clan tags, not saved lineups |
| Row assembly | 83.338 ms | `family_activity_rows`, synchronous calculation over saved snapshots |
| Weights | 6.527 ms | Saved SQLite lookup and immediate fixture provider |
| Weight overlay | 4.205 ms | Current saved/legacy weight precedence |
| JSON | 3.443 ms | Existing response serialization |

Activity context reads all 7,300 matching **projected retained record documents**
in this fixture. Across the whole route, fourteen Mongo query/cursor operations
return 2,825,660 BSON document bytes. Profiles are read twice: once for context
and again by the existing replacement calculation. Clans are also queried twice.
The already-deployed activity projection excludes the large per-unit baseline;
this is not a newly discovered missing baseline projection. Warm identity lookup
has no transport wait in this fixture, and a real missing-weight provider can
wait up to the existing eight-second budget. Those omitted external costs must
not be inferred from the local time.

The public weight provider has an existing fifteen-minute cache. On a miss it
reads and synchronously validates a full FWA Stats feed, capped at 8 MiB and
100,000 rows; the activity route has its separate eight-second wait budget.
A second measurement used only an injected HTTP body with **all socket
connections forbidden**, not a provider probe:

| Synthetic feed | Payload bytes | Cold method median | Parse/validation callback lag | Warm median |
| --- | ---: | ---: | ---: | ---: |
| 586 rows | 41,397 | 2.019 ms | 1.604 ms | 0.522 ms |
| 10,000 rows | 717,047 | 24.379 ms | 23.707 ms | 0.583 ms |
| 100,000 rows | 7,258,631 | 255.521 ms | 250.588 ms | 0.635 ms |

The callback was queued after the last fixture chunk, immediately before JSON
parsing/validation. Its lag demonstrates a separate brief cold-cache event-loop
stall. Transfer delay was zero; production feed size, cache state, lock wait and
network time were not observed. This is not an attribution of production's
three seconds, and no weight-provider change is included.

The separately instrumented ledger run measured its profile awaits at
39.707 → 19.820 ms, its synchronous per-row loop at 0.953/1.192 ms and JSON at
0.101/0.099 ms. These clocks wrap the same function locally; the full response
is checked unchanged. Query and BSON instrumentation runs in both variants.
The row loop is not a multi-second CPU source. The two per-row/profile-await clocks are inserted into a local in-memory copy
of the same function; response equivalence is checked. These clocks are not
production instrumentation.

| Roster stage | Median | Scope |
| --- | ---: | --- |
| `_roster_rows`, two calls | 5.344 ms | Saved account assembly, cold UI fixture |
| `_rule_rows`, two calls | 1.767 ms | Saved clan/rule assembly |
| `_auto_plan`, one call | 3.897 ms | Includes its second account/rule reads |
| Background metadata | 0.482 ms | Cached/unknown snapshot and job scheduling |
| Plain API clan metadata | 3,001.753 ms | Existing bounded wait for four-second fixture provider |
| Plain API location metadata | 3,011.028 ms | Parallel existing bounded wait |
| Plain API family lookup | 0.014 ms | Immediate fixture family result |
| Plain API weight-family lookup | 0.011 ms | Immediate fixture family result |
| JSON | 0.769 ms cold UI / 0.778 ms plain | Existing response serialization |

SQLite trace records 284 route queries, including 250 individual player-weight
reads: the 125 rows are assembled twice. This duplicate work is real, but these
measurements do not make it the cause of three seconds. The plain route's two
three-second metadata waits run concurrently, not sequentially. The UI's
background route returns cached/unknown metadata immediately instead.

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
guild/departed-last-seen. No index is added or hinted. Exact bounded query plans
include the actual projection, limit and batch size:

| Query | Rows returned | Documents / keys examined | Winning access |
| --- | ---: | ---: | --- |
| Ledger strike aggregation | 306 | 3,715 / 3,715 | guild/kind/date/id |
| Ledger profile batch 200 | 200 | 200 / 200 | guild/departed-last-seen prefix |
| Ledger profile batch 106 | 106 | 106 / 116 | guild/player |
| Activity player overview | 581 | 587 / 0 | Collection scan, already projected |
| Activity context profiles | 586 | 586 / 1,169 | Existing guild/player and clan/departure OR indexes |
| Activity retained records | 7,300 | 11,015 / 11,015 | Existing guild/player/date and guild/kind/date/id OR indexes |
| Replacement profiles | 586 | 586 / 586 | Existing current/departed clan indexes |
| Replacement active count aggregation | 306 | 3,715 / 3,715 | guild/kind/date/id |
| Failed-clan history | 1 | 587 / 0 | Collection scan with tag-only projection |

The retained-record OR can examine the same candidate through both branches;
its returned record count is still 7,300. Clan scans each examine six documents.
Optimizer choices on a local sample are not promises about Atlas's cached plan.

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
Its two unmodified-cursor ledger sample sets had medians 75.690 and 82.313 ms.
AST comparison also confirms the roster helpers, both HTTP routes and activity
context/replacement logic match between that tag and main `3f98345`; only the
ledger profile read changes in this branch. The local plain Roster wait
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

The final guarded backend run passes **6,238 tests, 100 skipped and 267
subtests**, in 584.88 seconds. Its clean export is bound to runtime commit
`75925fd954c9f5f0b2f4878e52a3bb9d7cb069c7`, with all source hashes unchanged.
The focused ledger suites pass 86 cases; the real owned-Mongo
response/filter/cursor test passes; all three genuine mutations are killed
(unbounded cursor, default first batch, unprojected private fields). Frontend
1,484 tests/261 files, TypeScript/build and war-reminder validation (213 backend,
one skipped; 35 frontend plus build) pass.

The initial full run had 6,237 passes and one architecture failure: its repository
ownership grep correctly found the completed earlier-tag source export under
`.local`. That owned export was preserved as a full source tarball and hash
manifest, then removed. The unchanged architecture test passed, followed by the
complete clean-export rerun above, with no exclusions or weakened guard.

The exact runtime commit passed the production-shaped staged boot: 51 configured
routes, native pool, real storage owner on copied SQLite and owned Mongo,
external networking blocked, config 200/auth 401, artifact hash manifest and
cleanup complete. Later report edits are docs-only; runtime source remains the
same. The runtime consumer audit finds `cwl_web.strikes.accounts` is the sole
production caller of `account_list`; the shared storage owner remains in `utils`.

The real-Mongo test covers missing optional profile fields, fresh/stale clan
observations, member/name fallback, exact-tag/name/clan/action/status searches,
late pagination, unchanged summary/rows and unchanged stored-record counts.
HTTP authorization and malformed input behavior remain covered by the existing
Strikes suites. No Discord notification test or live delivery claim is made.
Release is held for Ruggie. No services, production data, indexes or live API
calls were changed by this investigation.

Evidence under this worktree's `.local`: `p113-paired-bounded-ledger`,
`p113-paired-current-final`, `p113-paired-old-final`, `p113-detailed-final`,
`p113-mutants`, focused/full
logs and the checked-in owned-Mongo regression. The initial benchmark clock
replacement caused a fixture-only 400; that failure log is retained. One earlier
comparison launcher used the wrong working directory; its output is explicitly
marked `INVALID_COMPARISON` and excluded. The corrected earlier-tag run verifies
its import root and records source hashes. Initial sample counts and bytes differ
from the expanded fixture; they are retained but are not mixed into these tables.


The unchanged frontend fixture is available at
`http://127.0.0.1:39719/strikes-preview.html?count=560` (existing 560-row visual
fixture), PID 2205378. Served entry `assets/strikes-preview-BAOs7mYY.js` SHA256:
`91b5445338b70e5417fdc28322dedf69ccf0512fcbf17ec7696f5866e9f64b3a`.
No UI source changed and no new layout pass is claimed. The normal built entry
`assets/index-DODYu6Hv.js` matches the fetched public static asset, SHA256
`70ae891fce6403a70c8cbcee48863357a4a281615c93c9d461ac02762e009b1d`.
Only static HTML/assets were fetched; no application API or production timing
request was made. Temporary preview config/dependency symlink and owned
Mongo/SQLite/export fixtures were removed. The static review preview remains.

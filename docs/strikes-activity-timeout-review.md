# Strikes activity timeout: review evidence

Task 159 rework 162 is ready for review. Release remains held for Ruggie. No indexes,
production write jobs, notifications or service changes were performed.
Private numeric reports and original failure logs are retained under
`.local/read159`. BSON sizes below describe decoded documents, not wire traffic.

The accepted background policy now has a current-data read-adaptation measurement:
core rows arrived in 2.086 seconds, the single refresh completed at 5.223 seconds,
and a subsequent fresh-core read assembled filled activity at 6.522 seconds from
the first request. Cold output contained 620 rows / 3,712 active strikes with
unknown activity and updating true; filled output contained 576 rows / 3,475
active strikes with known activity, updating false and an as-of label. Cold
fallback uses the broad known-core scope; filled output reapplies the original
family/activity scope. The observed difference is not a same-scope count
comparison, and no production data was changed. That initial measurement preceded the scope correction below; per-account
identifiers were not persisted.

Review 567 required this scope difference to be resolved before READY. A new
numeric-only classification reproduced all 44 rows: 28 were known strike totals
without a profile (160 active strikes), and 16 were profiles outside the active
family without a family departure (77 active strikes). No account identifiers
or raw rows were retained.

The first 567 fix retained those core-known rows even when optional clan metadata
contradicted the profile. Review 162 found that bypass added rows the old filled
view hid. It has been removed: the filled view now uses the exact old eligibility
rule. Review 572 approved a fresh, projected header read (`tag`,
`current_clan_tag`, `left_at`) in parallel with the core reads. Headers filter the
cold profile cohort using that same eligibility, including the old departure
cutoff. They are never cached or used for signals. A header failure is a core
503, never a false empty view. Clan-label failure still retains known profiles
with tag labels.

On that same classification read, both new cold and filled cohorts contained
576 rows. Cold tags were a subset of filled tags; active and total strike counts
were equal for every cold row, and the filled account set matched the old filled
set. Owned 125-account equality and the subset/count invariants passed; a separate
fixture covers current members, recent/old departures, unrelated profiles,
profile-less activity and contradictory optional clan metadata. Historical
620-to-576 measurements above are retained as the pre-fix evidence.

These are read adaptation plus row assembly timings, including initial connection
in the cold measurement. They exclude HTTP authorization, identity lookup,
weights and browser rendering; they are not complete authenticated page latency.
The background policy and new value dictionaries passed the owned 125-account
full-output equality and stored missing/null/zero/order tests (10 passed).
The additional value dictionaries reduced packed observations from 231,124 to
158,790 BSON bytes. The changed observation aggregate completed in 2.577 seconds
while sharing the pool with the cold core and raw activity refresh. This is a
different workload from the earlier standalone diagnostic; it is not an isolated
latency comparison. No observation read is awaited in the request path.

As-of metadata is rendered as a neutral notice, separately from real activity
warnings. A regression verifies that an as-of label does not suppress the
existing tracking-behind warning or invent a quiet-days value.

## Measurements

The old activity context was measured twice, at least one minute apart. The
overview returned 566 documents / 919,061 BSON bytes in about 10.2 seconds;
profiles returned 576 / 168,300 bytes in about 2 seconds. Both original records
reads reached the 15-second network timeout. Initial connection establishment
was included in the first overview read.

Server execution statistics were much smaller: profiles returned 576 documents
in 4 ms, examining 1,182 keys / 618 documents; records returned 6,695 in 49 ms,
examining 11,433 keys and documents. Transfer/reader overhead is an inference;
Atlas throttling has not been established as the cause. Existing index specs
are recorded in `metadata.json`; no measured index gain or index build is claimed.

The selected parallel core read completed in 1.919 seconds, including initial
connection establishment: 592 profiles / 79,280 bytes; 503 complete count groups /
60,187 bytes; 25 clans / 1,173 bytes; settings / 115 bytes. This measures owner
reads, not complete authenticated HTTP latency or provider enrichment.

Native nested activity projection saved only 13 bytes and took 11.2 seconds.
Lossless present-key shortening and war/weekend dictionaries reduced the activity
snapshot to 403,688 bytes, a 56.1% reduction, but still took 4.515 seconds. The
earlier cursor-only microsecond metric excluded the aggregate first batch and
must not be used as complete latency.

The request-driven raw activity cache follows review 559: fresh through 30
seconds; stale through 10 minutes with an as-of line and one refresh; expired
or absent data has unavailable/unknown activity. Counts, profiles, settings,
authorization remain fresh per request. The initial ledger-observation
requirement was also per-request, before the 564 decision below.

That last observation policy was superseded by review 564: the same single
on-demand background refresh now fetches raw activity and observations. Core
counts, profiles, settings and authorization still remain fresh per request.
Observations are usable for at most 30 seconds from the fetch start, labelled
with an as-of time. Cold/expired observations leave signals unknown while the
page polls; bot-side changes may lag by up to 30 seconds, an accepted limit.

Dashboard manual strikes, revokes and import workers invalidate observations
before and after the write, including partial failure. The generation fence
prevents an earlier refresh from repopulating invalidated observations. There
is no dashboard no-attack-correction route today; a future handler must use
`changing_observations` around its write. Existing durable write semantics are
unchanged.

Review 565 additionally requires a refresh that reaches its 12-second bound to
leave unknown activity with the existing warning and `activity_updating=false`,
so polling does not leave a perpetual spinner. The response now reports only
actual refresh work as updating. A fixture exercises the same bound mechanism
with a short timeout, verifies both children are drained, preserves known strike
counts and confirms that the failure cooldown prevents an immediate retry.

### Fixture adjustments under reviews 565 and 566

No count, status, write-count or known-output assertion was removed or weakened.
The as-of label and background readiness follow the explicit 564 policy change.

| Current location | Before → after |
| --- | --- |
| `tests/test_strike_activity_background.py:87` | Raw-only `get` → explicitly request combined observations |
| `tests/test_strike_activity_background.py:88` | Assert before the refresh finishes → await its task, retain both before/after-write assertions |
| `tests/test_strike_activity_background.py:100` | Zero-argument mock → accept and assert guild 123 |
| `tests/test_player_activity_overview.py:20` | Implicit synchronous activity setup → explicit warm background fixture for warm-output checks |
| `tests/test_player_activity_overview.py:213` | Extra warm-up request accidentally completed identity lookup → retain the original single cold request before testing pending identity; assertions unchanged |
| `tests/test_strike_activity_reads.py:39` | Synchronous first observations → explicit combined-payload warm setup |
| `tests/test_strike_activity_reads.py:47` | Old per-request observation fetch → dashboard invalidation, then explicit completed background refresh |
| `tests/test_player_activity_compact_mongo.py:206` | Raw-only warm setup → combined raw/observations payload and explicit completion |
| `tests/test_player_activity_compact_mongo.py:209` | No activity warning expected → require the accepted as-of label; full row equality remains exact |
| `tests/test_player_activity_store.py:15` | Generic strike-count aggregation mock → query-driven tag-only activity snapshot wire adapter; every retirement/cache/data/write assertion stays intact |

The first selected read adaptation measured 2.080 seconds cold and 1.569 seconds
warm, retaining 620 rows and 3,712 known active strikes. Both observations reads
missed the 1.5-second optional budget, so both views had unavailable activity.
These timings do **not** establish the completed warm activity performance goal.

Review 562 authorized one standalone compact-observation diagnostic, without
changing the product budget. It returned 1,942 decoded observations, packed in
one aggregate document: 231,124 BSON bytes versus 435,013 decoded bytes. Aggregate
first batch took 3.290048 seconds, cursor completion 3.290103 seconds and total
including decode/breakdown 3.368789 seconds. Initial connection was included.
At that diagnostic checkpoint the request budget was 1.5 seconds and
observations were not cached. Review 564 subsequently replaced that path with
the bounded background policy described above.

Packed components were records 211,993 bytes, player dictionary 7,884 and war
dictionary 11,257. Standalone per-field BSON sums identify repeated import IDs
(52,920), kinds (37,801), source (31,072), occurrence dates (31,072), exemptions
(29,124), capture source (16,852) and player/war references (23,304 each).
Each per-field sum repeats BSON document framing; those sums cannot be added or
subtracted directly to predict a new complete payload.

## Freshness token audit: proposal only

There is no existing ledger-wide revision or universal `updated_at` field.
A maximum `occurred_at` token does not move when an older war is imported,
corrected or revoked. A maximum `revoked_at` also fails to detect new older imports
and kind-only corrections. Current index metadata contains player/member/clan
occurrence indexes, a kind occurrence index, war-key index and retention index;
no general update/revocation revision index is present. Token cost has not been
measured because no correct candidate is established. No freshness-token code or durable revision has been built. The accepted
background observation cache uses the explicit 30-second limit instead.

| Storage-owner path | Change relevant to freshness |
| --- | --- |
| `StrikeService.add_manual` | Inserts a record; counts always remain fresh separately |
| `revoke` | Sets `revoked_at` on the existing record; preserves its occurrence date |
| `no_attack_correction` | Revokes strikes or changes old missed rows to `no_attack` |
| `process_war` | Inserts monitored regular-war observations and exemptions |
| `process_cwl_war` | Inserts CWL records; excluded from regular-war observations |
| `_finish_streak_receipt` | Revokes frozen strike IDs and updates a receipt on an old row |
| `apply_import` | Inserts old-dated regular-war and CWL rows with import metadata |
| Retention tooling / TTL | Sets retention metadata; eventual deletion does not advance a newest-row token |

Dashboard manual/revoke/import routes and bot commands in
`extensions/commands/strikes.py` use these owner methods. Bot monitored-war
processing reaches `process_war`; dashboard-only invalidation would miss it.
The moving 90-day selection window also changes without a ledger write.
A correct token must cover all relevant changes and time-dependent selection.
Adding a durable universal revision would change write semantics and requires
separate review; task 159 currently preserves the write paths.

The alternative under review is further transient, lossless value dictionaries
for repeated import IDs and string-valued categories, or reconstruction of query
constants with stored-presence guarantees. No implementation or performance gain
for this alternative is claimed.

## Scheduled readers

From local git history, this activity polling feature first appeared in
`2421e079` on October 31, 2026 at 13:55 EDT; history backfill was added in
`13579cdd` later that day. Thus this feature's scheduled read contribution was
absent before its introduction. This does not quantify other bot traffic.

The hourly path calls membership reconciliation, history, raid capture and
conditional seed work. The history daily gate occurs after its initial player
read. These initial inputs previously read complete documents; official player
record replacement intentionally still reads the complete previous document.
History cache lineups and other scheduled features remain potential contributors.

On the measured current data, 566 full documents total 3,479,909 BSON bytes;
the bounded war/raid arrays account for 796,481 bytes (22.89%). A single pure full
read timed out after 15 seconds. Actual production write jobs were not run.

| Initial player read | Projected bytes | Measured seconds |
| --- | ---: | ---: |
| Membership | 160,153 | 2.443, including initial connection |
| History | 46,603 | 0.579 |
| Raids | 315,137 | 3.436 |
| Seed | 59,238 | 0.705 |

Four full inputs on this same data would total 13,919,636 bytes; their projections
total 581,131, a 95.8% reduction. All-player-equivalent war and raid merge inputs
are 818,290 and 212,415 bytes. Four initial reads plus one merge read of each kind
would fall from 20,879,454 to 1,611,836 bytes, a 92.3% reduction. Conditional seed,
pending raids and CAS retries vary, so this is an illustrative upper-run volume,
not a measured hourly total or historical Atlas traffic. This path is a large
identified contributor; the largest sender across the whole application has not
been proven.

Owned 125-account fixtures compare full versus projected reads through the real
job writers, using fake providers: results, every stored document, revisions and
unrelated data remain equal. Production schedules, predicates, writes and retries
are unchanged.

## Validation

The production-shaped owned 125-account HTTP fixture uses real HTTP transport,
SQLite sessions and unchanged permission adapters, with GET-only fake Discord
and fixture weights. It checks unauthenticated 401 and nonprivileged 403 before
any cache touch, known cold rows without waiting for observations, exact 955
filled-row equality and a required-core timeout returning 503. Measured fixture
HTTP times were 28.4 ms cold and 49.7 ms filled. The 35.9 ms old serial reference
is read-plus-assembly timing, not an old full-HTTP measurement. These fixture
times do not measure live Discord authorization or production end-to-end latency.

Review 568 approved the precise error-side-effect contract: healthy GETs leave
every owned Mongo collection exactly unchanged; after an injected 503, every
original collection remains exact and only one expected `dashboard-issues-v1`
entry may appear. Its kind, status, action, method, error type and returned
issue reference are checked exactly. Existing diagnostics are not suppressed.
The refined owned HTTP test passed; the earlier blanket all-collection failure
is retained as evidence of the pre-existing diagnostic write, not a strike-data
mutation.

Eight isolated component screenshots cover cold, ready, timeout and automatic
fill states at 360 and 1440 pixels. The All account view is explicit, with 25
visible rows per page; document overflow and page errors are zero, keyboard
focus is reachable, and cold unknown signals never display zero-day quiet or
"No activity yet". Nonfixture origins are blocked, all API responses are fake
GETs, and no production calls or writes occur. The narrow cold and wide filled
screenshots were visually inspected. Two private harness setup errors (root
403 before resolving the fixture index; implicit Not attacking filter on cold
unknown data) were corrected under 566 without changing product or assertions;
both failed outputs are retained.

A retained browser-only component preview uses this isolated sample build. It
is not a full backend preview or a tagged deployment artifact. The production
bundle and actual component source are separately bound in the evidence.

### End-to-end review

| Concern | Evidence and limit |
| --- | --- |
| Authorization | Real fixture sessions exercise 401/403 before cache access; auth and core are never cached |
| Required data failure | Core errors produce 503 rather than empty success; exact incident receipt is visible |
| Optional data failure | Unknown signals retain known strike counts; 12-second bound stops updating and drains work |
| Concurrent readers/writes | One refresh; generation invalidation before/finally dashboard writes; no stale repopulation |
| Cancellation/restart | Request cancellation preserves shared work; app cleanup cancels/drains; a new process begins cold |
| Stored values | Missing/null/zero, ordering, full 125-row equality and all original Mongo documents are pinned |
| Scheduled writers | Projected versus full inputs produce identical results, revisions and unrelated saved fields |
| External rendering | Existing React text rendering retained; browser fixtures block external origins and perform no writes |
| Delivery | No live notification, Discord delivery or push-delivery proof is claimed |

The intentional original timeout regression now passes. Owned Mongo tests cover
125-account old/new row equivalence, imports, exemptions, manual/revoked/expired
strikes, replacements, input order, missing/null/zero and document nonmutation.
After review 561, every changed/new Python module is compiled before an owned or
production run. The earlier codec syntax failure and failed prototype are retained
with hashes; neither is counted as passing evidence.

Frontend refresh checks include pending activity without pending identities,
post-fetch busy state, completed-mutation epochs, generation changes and permission
loss. Full frontend: 1,780 tests in 296 files passed; TypeScript and the private
build passed. The isolated layouts and retained component preview described
above passed; they use sample data and fake API responses.

Shaka's signed-in Members measurement was 5,074 ms / 133 KB for the overview,
437 ms for role runs and 344 ms for timezone runs. This is Shaka's measurement;
no new signed-in Members request was made by this task. A narrowly scoped read of
the existing numeric timing log found the matching November 4 05:37:05 UTC
request: directory 2,386.1 ms, hierarchy 0.6 ms, profiles 1,719.6 ms, row work
238.7 ms, JSON 19.2 ms, total 5,028.0 ms; 1,448 members, 245 roles, two directory
pages and six Discord requests. The server JSON body was 1,086,645 bytes; that is
a different byte layer from Shaka's browser transfer measurement, not a measured
wire-byte equality. The private numeric journal receipt is retained without
member identifiers. Directory work and profile reads dominate this request;
neither uses the scheduled `player_activity` readers changed here. No small
shared-owner fix is demonstrated, so no standalone Members change is claimed.

The obsolete product overview modes and serial/summarized context prototype have
been removed. The selected overview has one dictionary read path. Exact baseline
955 overview/context method bodies, apart from their test-only names and
indentation, are frozen in `tests/fixtures/strike_activity_955_reference.py` with
hash provenance. The owned equality tests compare the selected path against that
reference; product code never imports the reference.

After consolidation, focused checks passed 44 tests and the owned Mongo suite
passed 10. Broader strike/activity regressions passed 393 tests with 15 opt-in
skips. The required unchanged war validation passed 213 backend tests with one
skip, 35 frontend tests, TypeScript and its temporary build. These are local
regression checks, not notification delivery or deployment evidence.

The single full backend run on clean frozen commit
`049c27c17830d5d670ed9aad21020a1dff8e5e54` passed 6,877 tests, with 134
skips and 270 passing subtests in 586.60 seconds. The reviewed c02 startup
network guard, explicit empty Mongo/Healthcheck settings and private temporary
folder were active. No source edits or other suites ran during collection.

The exact-commit archive then passed the owned production-shaped boot: 51
configured routes, native async pool and an owned ping, real durability owner
with a retained copied SQLite database, config 200 and unauthenticated auth 401.
All 18 checked module origins, including the new cache/read/projection modules,
were inside the archive. External network access was blocked before application
imports; Healthchecks were empty. Mongo executable, working directory, database
path and listener ownership were checked before any client. The owned process,
data, database and archive export were cleaned; manifests remain private.

The freeze launcher initially used unavailable `python` and failed before any
interpreter or script started. Review 569 approved the same action with the
absolute verified virtualenv interpreter; that one correction succeeded. No
source or test assertion changed for this launcher correction.

Final documentation is the only change after that tested revision. Runtime,
tests and frontend source remain byte-identical. Private READY provenance binds
the validation logs, original failures, archive sources, cleanup and previews.
Production end-to-end authenticated latency remains unmeasured by the
read-adaptation or fake-provider HTTP fixture. There is no deployment or live
notification proof for task 159, and release still needs Ruggie's approval.


## Rework 162

The normal backend suite now includes nine deterministic 450-player fixture
adapters comparing every filled output field with the frozen 955 row assembler,
with nonzero active/expired/revoked/manual strike counts and input nonmutation.
Each seed also checks cold tags are a subset of filled tags with equal per-row
counts. The two conflicting activity-clan trigger cases stay hidden exactly as
before. The owned Mongo equivalence suite remains an additional check.

Validation of profile identities and malformed strike dates is restricted to
the old selected scope. An unrelated malformed profile or date does not fail the
family page; malformed selected data still fails. Duplicate war dispositions are
resolved independently of record order: an exemption/revocation vetoes its war
after all monitored rows are considered. Both orders are tested. This is the
explicit correction requested by 162; other signal rules remain unchanged.

The existing weights timeout is restored to eight seconds. The earlier half-second
change was outside the approved scope. The response can therefore still wait for
that existing weight lookup; the core timing is not a complete HTTP latency claim.
While activity is updating, one neutral “Loading activity…” line replaces the cold
error. Failure/timeout retains the red unavailable warning. A missing history
status now says “Could not check recent war reads.”, a deliberate plain-word change.

Two actual isolated source mutations are killed by new ordinary tests. Counting
observation expiry from completion incorrectly serves a 20-second loader's result
at 30.5 seconds after its start. Dropping the generation fence incorrectly stores
a result from a loader that ignores write cancellation. Both mutated runs fail at
the intended data assertions; the unmodified tests pass. No production source
file is replaced for mutation execution, and this is not delivery evidence.

The transient codecs do not promise preservation of every BSON numeric subtype:
Mongo grouping can equate numerically equal dictionary values of different types.
Current identifiers are strings and disposition values are consumed by truthiness,
so no visible change is established for this edge. A stored `recent_wars: null`
remains null and the old and new signal paths can both reject that malformed
shape. These are documented limits, not newly supported stored shapes.

One approved 572 current-data read measured 566 fresh headers, 36,414 decoded BSON
bytes in 1.583170 seconds. The new parallel core plus cold row assembly took
1.858704 seconds including initial connection, with 576 rows and 3,475 known
active strikes. No raw player rows were retained; no writes, jobs or indexes were
run. This is not authenticated HTTP/provider/weights/browser latency.

Rework checks so far: 33 targeted tests, 11 owned Mongo tests, 410 broad tests
with 16 skips, 1,781 frontend tests in 296 files and 30 focused UI tests passed.
The first broad run was mistakenly started in the socket-restricted sandbox and
stopped at TestServer socket creation after 211 passes. Review 573 approved the
same guarded host run once; it passed without source or assertion changes. The
failed log remains. The final frozen backend and owned boot receipts below supersede the earlier
049c validation. The full local checks and preview do not prove deployment.


Rework frontend, TypeScript, private build and required war checks passed:
1,781 tests / 296 frontend files; 213 backend war tests with one skip and 35
frontend war tests. Eight new isolated 360/1440 screenshots cover cold, filled,
timeout and filling states. The narrow cold loading line and wide filled as-of
line were visually inspected; document overflow and page errors are zero.
The fresh retained preview is an actual component with sample GET responses,
not a full backend or deployment artifact. Its first bootstrap used the wrong
Node path; review 574 approved changing only the executable to the verified
absolute path. The corrected bootstrap succeeded, with the failure retained.

The 162 fixture change in `tests/test_strike_activity_core.py` replaces the
incorrect requirement that a conflicting activity clan retain a family profile
with the reviewed exact955 hidden-row behavior. Fresh headers exclude it from
cold too; subset and per-row active/total count assertions are retained. The
parallel-read fixture now requires five children including mandatory headers,
and the header failure has its own error test. No HTTP status, count or durable
write assertion was removed for these changes.


### Final 162 validation

The single full backend run on clean frozen
`edba131198776511793fddf3e143da790a68b68e` passed **6,894 tests**, with 134
skips and 270 passing subtests in 581.05 seconds. The startup c02 network guard,
explicit empty Mongo/Healthcheck settings and private temporary folder were
active. No source edits, exports, boot or other suites ran during collection.

The new exact-archive owned boot then passed all 51 production routes, native
async pool and owned ping, retained copied SQLite with the real durability
owner, config 200, unauthenticated auth 401 and 18 archive module origins.
Network restrictions preceded application imports; Healthchecks were empty.
Owned Mongo PID 786317, executable, working directory, database path and listener
were verified before clients. The process, database, data and archive export
were cleaned; source hashes and cleanup receipts remain private.

The current private main build entry is `index-BkBhL6gP.js`, SHA256
`122066a18b8e444a2e7bbbde11518505add59960027cb7dc70ff65b7f6a84dc5`.
The separately retained component fixture is served on port 45201, with fake GET
responses and a static CSP. Its PID/executable and index 200 were verified after
the bootstrap had exited. It is not a backend preview or deployable artifact.
The main build and fixture bundles have separate bindings.

The exact955 overview, context and row-assembler reference functions were checked
again by normalized AST (test-only function name changes). The two requested
cache mutants fail the new assertions while the unmodified tests pass. Ordinary
no-Mongo randomized equality runs in the full suite; the owned Mongo tests remain
an additional opt-in check.

Final changes after the tested revision are documentation only. Runtime, tests
and frontend remain byte-identical to the full-tested and booted revision.
All original RED/failure logs, rejected prototypes, harness errors and their
corrections remain in the private provenance. There were no live messages,
notification delivery claims, production writes, index builds or service changes.
Release remains held for Ruggie's approval.

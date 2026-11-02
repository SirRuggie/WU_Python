# Members performance investigation

Prompt 112 is a local investigation. No production API request, timing probe or
Discord write was made. Release of this change remains held for Ruggie.

## Findings and limits

Repeated linear membership checks in `extensions/warrior/core.py` are a measured
CPU cost. `permissions` and `top` scan the guild roles and previously searched the
member's role tuple for each role. The same actor and bot are checked for every
inventory row. Converting that tuple to a set for each helper invocation preserves
the result and reduces this cost. The server continues to evaluate authorization
on writes; no permission, directory caching, polling or response rule changed.

This cost predates Members. The pre-Members `8c6a65f` inventory has the same helper
calls. On the same generated fixture, the old endpoint is in the same latency range
and returns fewer fields. The small added row and role-editability projection does
not explain the observed production 6.9–9.8 seconds by itself.

The production time remains only partly attributed. Actual Discord round trips,
TLS setup and Atlas latency were not timed: doing that requires Ruggie's approval.
Local measurements must not be presented as production latency or a promise that
the deployed endpoint will finish within two seconds.

## Fixture and method

Generated data has 1,450 members and 245 guild roles. A separate owned local Mongo
instance contains 479 profiles; it is stopped and removed after measurement.
The fixture contains bots, the guild owner, members above/equal/below the actor
and bot, protected roles and ordinary/admin/owner/no-role actor cases. No member
identity is copied from production. The JSON payload is smaller than production's
1.09 MB because the generated names and profiles differ.

Three samples per case use the real inventory and response adapter with stubbed
Discord responses. The HTTP experiment uses the actual local `/seasons` handler,
an owned SQLite store and a second client thread issuing a concurrent request.
Directory and hierarchy external latency is excluded. Helper timings nest inside
the inventory stage and must not be added together.

### CPU sensitivity before and after the membership change

Each member normally has one role; this table varies the actor and bot role
counts together. Times include instrumented response assembly, with Discord and
profile reads stubbed. These are medians of three samples, taken before full-suite
CPU contention.

| Actor and bot roles each | Before seconds | After seconds |
| --- | ---: | ---: |
| 1 | 0.280 | 0.219 |
| 25 | 0.627 | 0.286 |
| 100 | 1.476 | 0.475 |
| 220 | 2.277 | 0.773 |

The generated high-role case meets the local target of two seconds. The actual
actor/bot role counts in production were not fetched, so this is a sensitivity
measurement rather than a claim that production has 220 roles per member.

### Final paired HTTP stage measurements

Final paired measurements below use three samples per case, after full-suite
and release-gate CPU work ended. Both baseline variants install the prior helper
implementations; the optimized variant uses the new helpers. No live API was
called. Directory/hierarchy responses and authorization are stubbed, so their
external costs are excluded rather than measured as fast production calls.

| Local HTTP case | Total median seconds | Response bytes | Concurrent `/seasons` seconds |
| --- | ---: | ---: | ---: |
| Current baseline, one actor/bot role | 0.295 | 746,167 | 0.288 |
| Pre-Members `8c6a65f`, same fixture | 0.302 | 606,882 | 0.297 |
| Optimized, one actor/bot role | 0.235 | 746,167 | 0.228 |
| Current baseline, 220 actor/bot roles | 2.355 | 755,803 | 2.348 |
| Optimized, 220 actor/bot roles | 0.806 | 755,803 | 0.799 |

`/seasons` alone is 0.009–0.011 s in this local experiment. The high-role old
endpoint comparison is 2.068 seconds and 606,882 bytes: most of this CPU
cost already existed, while the new per-row role-editability projection adds
work for a high-role actor. The measured one-role old/current difference is
within ordinary run variation and does not establish a production regression.

| Stage, current one-role fixture | Before median seconds | After median seconds | What it counts |
| --- | ---: | ---: | --- |
| Directory | 0.00035 | external cost excluded | Two stubbed pages and a stubbed self lookup |
| Hierarchy | 0.000003 | external cost excluded | Injected role map and actor/bot context |
| Profiles | 0.0061 | 0.0061 | Actual one-query owned Mongo read of 479 profiles |
| Inventory inclusive | 0.278 | 0.217 | Profiles plus 1,450 row projections |
| `core.permissions`, nested | 0.119 | 0.098 | 2,768 helper calls |
| `manageable_target`, nested | 0.135 | 0.095 | 1,449 helper calls |
| `core.top`, nested inside target checks | 0.131 | 0.091 | 5,534 helper calls |
| Role-editability checks | 0.0056 | 0.0058 | 1,449 `actor_can_manage_member` calls |
| JSON serialization | 0.0047 | 0.0052 | Actual response serialization |

These nested times are diagnostic and must not be summed. Building 1,450 member
objects separately costs a median 0.00137 s over eleven samples; it is not the
dominant CPU cost here. For the high-role baseline, permission helpers cost about
1.137 s and hierarchy helpers about 0.919 s; after the change these are about
0.362 and 0.150 s. The additional `actor_can_manage_member` pass remains unchanged.

The local profile query returned 479 documents / 91,968 BSON bytes, examining 479
documents and 479 keys. This is document serialization size, not network bytes or
an Atlas quota estimate. The default `_id` index supports the member-ID lookup;
no index is added. Local database behavior does not establish production latency.

Evidence remains in `.local/members-speed/.local/final-measurements.json`,
`old-many-measurements.json`, `role-sensitivity-before.json`,
`role-sensitivity.json` and `member-object-cost.json`. All generated Mongo/SQLite
fixtures and local HTTP servers were stopped/removed after measurement.

## Request and refresh inventory

The uncached Members path does three fresh identity GETs concurrently, then the
complete directory needs two pages plus `/users/@me`; hierarchy then repeats
`/users/@me` and fetches the bot member. That is eight Discord GETs in six latency
waves at this fixture size, plus authorization/profile Mongo reads and protected-role reads for non-owners.
`server_management.discord` creates a new HTTP session per call. The helper's
separate 60-second searchable-member cache is not used by this inventory. These
are source observations, not timings or a verified attribution of the remaining
production delay.

`useMembersDirectory` loads on page mount or permission enable, manual Refresh,
successful profile/import changes and completed/recovered role work. Closing an
unchanged person panel returns to the existing list without reloading it. The
two-second poll reads active run status, not the full overview on every tick;
completion triggers a directory refresh. No polling is added here.

## Review and next decisions

The equivalence regressions compare both permission helpers with the prior
implementation for 280 combinations and compare all 1,450 rows, role options and
role-editability outputs for four actor modes. The owner, bot and protected-role
restrictions are asserted explicitly. Full checks passed: 6,148 backend tests, 99 skipped and 266 subtests; 1,484 frontend tests in 261 files; TypeScript/build; war-reminder checks (213 backend, one skipped; 35 frontend/build). Two genuine mutants (dropping everyone permissions and ignoring the target highest role) were killed. The exact a675b1b artifact passed the isolated production-shaped 51-route boot, native pool, real durability owner, copied SQLite/owned Mongo, blocked external networking, config 200/auth 401 and cleanup. Source hash: c02d7316c0673455a0abe3b8408fc125cd84065dfe52e3219257bacb2551ff1d. The owned QA dependency symlink was removed; its shared target was retained.

Frontend code is unchanged. Existing review preview 37493 `/server/members` remains available with `index-DODYu6Hv.js`, SHA256 70ae891fce6403a70c8cbcee48863357a4a281615c93c9d461ac02762e009b1d; the built entry and fetched preview/public entry match. No new UI layout claim is made for this backend change.

If the approved CPU fix leaves a slow production overview, the next useful step
is owner-approved stage timing on a naturally opened request. That would separate
fresh identity, paged directory, hierarchy, profile query, row CPU and JSON before
choosing connection reuse, request-local duplicate-read removal or a directory
cache. A cache needs a separate freshness and authorization design; it is not
included in this change. No production timing instrumentation is deployed here.

## Log-only production attribution (prompt 117)

One best-effort INFO line is emitted for each Members overview handler request:
`Members overview timing directory_ms= hierarchy_ms= profiles_ms= rows_ms=
json_ms= total_ms= members= roles= discord_pages= discord_requests= bytes=`.
Only numeric values are supplied. No member ID, name, token, exception text or
response body is logged. Failed requests may have partial/zero counts and zero
bytes; they are not successful page-load measurements.

Directory includes paging and its self lookup; hierarchy includes its two
existing Discord reads; profiles includes the one existing profile query; rows
includes inventory and role-editability projection; JSON includes the unchanged
response construction. Total measures the handler, including authorization invoked inside it and
protected-role work; middleware before the handler, logging and client/network
transfer time are excluded.
Role count includes the guild's everyone role. Pages count page attempts; the
Discord counter tracks existing request dispatches, including auth when it runs
inside the handler. Bytes count the uncompressed JSON body, not billed quota.

The recorder is bound only to this request and removed afterward. The shared
Discord adapter increments a counter around its existing dispatch; it performs
no extra call and is a no-op on other requests. Clock, constructor, counter and
logger failures are best-effort and cannot change authorization or response
outcomes. There is no flag, setting, cache change or new polling.

Focused tests verify one numeric line without identities, exact response bytes
with/without timing, unchanged IO counts, actual injected-dispatch counting,
constructor/clock/logger failure (including a clock failing after request start)
and unchanged authorization denial. Combined with current capture main3f, the
backend passed 6,250 tests, 99 skipped and 267 subtests in560.71s; focused
checks passed45. Frontend1484/261files, TypeScript/build and war reminders
(213 backend/one skipped,35 frontend/build) passed without web source changes.
Three adversarial mutations were killed: missing dispatch counting, raw response
logging and a clock exception after request start. The initial global-clock
mutation survived because the constructor fallback safely disabled timing;
the new mid-request regression catches the meaningful failure. Its initial
overall log is retained; final rerun overwrote per-case files, recorded honestly
in the local evidence summary. Exact final-commit boot proof is recorded
separately; these are isolated checks, not live timing or delivery evidence.

Approval 376 applies only after Claude accepts the new delta; capture 116 goes
first. The dashboard needs the optimized helper in its new backend archive,
but the bot does not need that performance-only implementation changed live: its
permission results are identical, so no bot restart is required for this batch.
After approved release, nobody probes Members. Observe a real successful page
load's timing line, then report its stage values and limits before attributing
the production delay.

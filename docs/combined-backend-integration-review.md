# Combined PR180, PR183 and PR189 integration

This integrates the three accepted feature deltas in Shaka513 order on
`4fd68b584658d71d8a7110f21e9a2ab0203810ec`, preserving the completed frontend
batch, PR175's heartbeat/acknowledgement and PR177's saved-copy provenance.
No stacked branch tree was checked out wholesale.

| Feature | Accepted revision | Delta predecessor | Local commit |
| --- | --- | --- | --- |
| PR180 Members reads | `277b5d0ff8022599101c4b94f4816c2dd19644e8` | `e91982d92632193c476adde34a8ec133495ff750` | `bebf37df` |
| PR183 post editor | `a4d1595262466508082475057a938168584f818e` | `a51cc433b1058fcf1dcf85c5edac66b0b0f8bd2e` | `52dbc3c7` |
| PR189 catch-up | `3f674871a0832a5ace046c76245f80aaa1bc0cce` | `fe67907beb09c5638e4a0b873be0b60f2bdfffc5` | `f61b9eb5` |

Exact path lists, patch hashes, unchanged source references, conflict proposals,
approval mappings and logs are retained in `.local/integration` in the isolated
combined checkout. PR180 and PR189 applied cleanly. Integration stopped at PR183's
shared behavior conflicts before applying the specific Shaka520 union proposal.

## Reviewed resolutions and regressions

The single heartbeat write retains epoch/schedule acknowledgement plus post-editor
readiness. Native polling passes all three arguments; shutdown clears both scan
completion and the post-editor worker. PR177's marker-aware saved baseline remains,
as do PR183's field-scoped future copy and recurring pause precedence. Existing
previous-cycle reads are reused, without a duplicate read. Additive imports and
document sections preserve both predecessors.

Combined tests found a real receipt-only-cycle interaction: creating a partial
roster copy made PR177's unmarked-override rule discard the inherited defaults
marker and alter unrelated text. The unchanged accepted PR183 test caught it.
Shaka521 approved the narrow exception using PR183's existing validated edit stamps,
strict `base_campaign_missing is True`, and absence of a whole recurring override.
There is no backfill, extra read or write-on-read. Thirteen new cases cover marked
and unmarked inheritance, stale/malformed proof, flags and whole-template override.
The original failing test remains unchanged.

The original 177 suite missed sparse schema-versioned legacy snapshots. Two
additional test-only cases now preserve their old fallback and optional saved title
against newer defaults. The original survivor log is retained. Nine in-memory
behavior mutants are killed, including removal of the receipt-only exception by the
original failing assertion. The pause-cutoff mutation initially survived the new
selected cases but fails the existing accepted explicit-future-cycle regressions;
both outcomes are retained. No mutant changed tracked runtime source bytes.

## Native Mongo fixture correction

An expanded owned-Mongo gate exposed two older fixture failures: a test waited
12 seconds for Mongo's default 60-second TTL monitor, and a global terminal count
included a separately retained guild's uncertain-work receipt. Before changing any
fixture, Shaka522 required an actual plain-main baseline. Both unchanged selectors
failed at the same assertions on a fresh default-TTL server and exact main4fd.
Source origins, PID/executable/cwd/dbpath/listening-inode binding and cleanup proof
are retained. This was not inferred solely from matching file hashes.

Under that conditional approval, only the newly owned profile test server uses
`ttlMonitorSleepSecs=1`. The 90-day TTL index and lease/CAS checks remain unchanged.
The cap still requires 20 of the 25 explicitly seeded legacy history rows, while
additional assertions protect the separate guild's parent and uncertain child.
The oldest child-removal assertion remains. No production setting changed.

All three owned phases then passed: 18 native profile cases, five named post-store
protocol checks, and 14 native catch-up cases. The post-store checks include native
partial/TTL indexes, idempotence, concurrent single claim, restart uncertainty and
stale completion fencing, plus zero examined documents/keys across 2,000 archived
rows. Every phase proves its fresh URI/data path and exact listening PID before
any Mongo client; only its new process/data are cleaned up. No old fixture is reused.

## Validation and limits

At source freeze, combined focused backend validation passed 380 cases and three
subtests; focused frontend passed79. Full frontend passed1,771 cases in296 files,
TypeScript/build passed, and the required war-reminder tool passed213 backend
cases/one skip,35 frontend cases and build. The existing large-entry build advisory
remains. Final full-backend, exact production-shaped boot, bot-import and isolated
layout results are bound to the frozen source in the final local gate manifest
submitted for direct integration review.

The boot uses an owned Mongo database and a copied retained SQLite backup, all
configured production routes and flags, native pool and real durability owner,
blocked external network, config200/auth401, and complete cleanup/hash proof.
Existing hardcoded feature boot wrappers are not executed unchanged. No source
export is created during full-backend architecture collection.

These are local tests and synthetic Discord transport checks, not proof of live
message edits, sends, role changes or delivery. The earlier production same-shape
profile explain is not repeated, nor is any production load campaign. There is no
connection-policy or performance-target claim beyond the individual accepted
reports. All prior previews, data and shared dependencies remain intact.

Shaka's independent refuter must review the whole frozen integration before the
parent's combined coordinator review. This task performs no production gates,
near-due reads, main publication, tags, service actions or deployment.

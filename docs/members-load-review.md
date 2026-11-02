# Members directory load review

Source-only review draft. Release is held. No production API request, database query, provider probe, service change or role change was made for this work.

The supplied November 2 timing lines came from Claude's three signed-in read-only probes, not natural traffic. They showed 1,451 members, 245 roles and about 479 profiles: directory 1.7–2.3 seconds, hierarchy 0.3–2.3 seconds, profiles 2.2 seconds, rows 0.64 seconds and 8 Discord requests. These coarse stages do not identify every network, pool or server wait.

## Findings and changes

The profile query is `_id: {$in: member_ids}, left_at: null`. A new isolated native Mongo fixture with 479 active and 17 departed records used an existing TTL index (`member_profile_left_90d`, IXSCAN → FETCH), examined 479 keys/documents and returned 479 records. No new index was justified or added. This local plan is not proof of production's selected plan. Production explain was not performed.

The old query returned full profile documents in a 101-document initial batch and a 378-document getMore. The display-only projection removes edit/audit-only fields, requests a bounded batch and applies a matching limit so the cursor closes in the find response. This fixture reduced two commands to one and returned BSON document bytes from 147,532 to 102,027. Those are document bytes, not wire or Atlas billing measurements. Edit/import callers retain complete reads. A second native fixture covers 1,451 active profiles.

The hierarchy stage does not fetch guild roles: it fetches `/users/@me` and the bot member sequentially. Roles already come from live request authorization. Thus the observed hierarchy spike cannot be attributed to a roles request in that stage; its exact unlogged cause is unresolved. The read path now reuses the bot identity and bot member already validated by the full directory read, eliminating these duplicate calls. Write paths retain fresh hierarchy reads.

Only the raw Members overview directory/bot snapshot is cached, in one backend process, for at most 60 seconds from fetch start. Initial reads may reuse it; concurrent readers share one in-flight read. Manual Refresh and existing post-write reloads bypass it. Existing live authorization and role data are read on every request; editable flags are rebuilt per request. No permission result is shared between requests. A stale displayed target still encounters the existing fresh write preview, confirmation and worker validations.

Accepted role/profile requests invalidate this read cache. Existing job/run receipt reads invalidate it when completed, failed or uncertain work may have changed the member. These are existing polls, not new queries or timers. A fresh stored profile `updated_at` also invalidates an older raw nickname snapshot, covering Warrior changes without adding a recurring Mongo read. If the refreshed directory has simultaneously gained a member, only those newly encountered IDs require one extra bounded profile query. Other external Discord changes are bounded by the 60-second TTL or manual Refresh.

Per-request role positions and shared actor/bot permission values are computed once. The accepted intermediate local benchmark still measured 161–189 ms of row work, so both pure response-building phases now run off the HTTP event loop. They receive only private materialized data and local hierarchy objects; no request, provider, database client, cursor or writing callback enters the thread. A per-application gate permits one such computation at a time, remains held if a reader cancels while computation finishes, and drains active pure work during application cleanup. HTTP failures propagate and a later read can recover without poisoning the worker. The position index is request-local and is not passed to mutating callers. Existing permission equivalence cases include owners, administrators, unknown/duplicate role IDs and negative positions.

## Response and interface

Existing response fields remain. Members overview adds optional `directory_cache` with `cached`, ISO `checked_at` and `max_age_seconds: 60`. Older consumers may ignore it. The Members page validates it, retains existing content during Refresh, displays a small updating line, and labels a reused recent list. No new polling, eager preview or unrelated page change was added. A denied read still clears protected data.

## Validation remaining

Paired local stage measurements, mutation checks, full regression suites, narrow/wide interface verification and exact production-shaped artifact boot are pending. The target under two seconds must be evaluated after an approved release using naturally occurring loads; local mocked transport measurements cannot establish it. Cold reads and manual Refresh still depend on Discord and Mongo latency. This change does not establish the precise production cause of the 2.2-second profile stage.

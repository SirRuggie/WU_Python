# Tasks official API transport

Prompt 24 (`tasks-official-api-1`) verifies an existing transport migration;
this batch does not replace a second client or change Tasks output. The shared
factory in `utils/startup.py` constructs coc.py with
`https://api.clashofclans.com/v1`, requires a nonblank private `COC_API_TOKEN`,
and awaits authentication. Bot startup and `cwl_web/todo.py` use that factory.
The dashboard serializes client initialization and reuses its lifecycle-managed
client. `utils/todo_data.py` passes player, current-war, CWL group/war-tag and
raid reads to this client. No direct proxy URL or cache-busting query remains.

Ruggie's policy: use the official game API when it supplies the needed data.
Community ownership links and historical observations remain separate sources;
there is no fallback to archived data for an unreadable current Tasks section.

## Preserved behavior

Payload parsing and serialized Tasks rows are unchanged. The application limits
remain eight concurrent account fetches, two concurrent section clan reads and
the shared coc.py request throttler. Player lookups have a 3s timeout, section
loads 35s and clan batches an 8s budget. Dashboard initialization waits at most
10s. Existing per-key coalescing locks and rate-limit/error handling remain.

| Cached answer | Existing TTL |
| --- | --- |
| Ownership links | 6 hours |
| Player-to-clan membership | 600 seconds |
| Active regular war | 120 seconds |
| Idle, private or not-found regular war | 900 seconds |
| Absent CWL / active CWL | 3,600 / 600 seconds |
| Ended CWL war-tag payload | 24 hours |
| War/CWL errors | 60 seconds |
| Active raid or missing raid during the weekend | 300 seconds |
| Negative raid outside the weekend | Until Friday 07:00 UTC |
| Completed / partial dashboard snapshot | 60 / 15 seconds |

Raid gateway/timeout exceptions retain their existing uncached behavior;
private/auth-denied raid reads remain errors, not an invented “not started”.
A private current-war response remains explicitly private. An unreadable
section must never become a successful empty section.

Clan Games remains the existing ClashPerk score provider through
`utils/clan_games.py` and `cwl_web/todo_games.py`; missing scores stay unknown,
not zero. This batch does not invent an official monthly-score endpoint.
The repository has no official equivalent for the per-account seasonal scores
required by Tasks; that is a source-capability assessment from this codebase,
not a new exhaustive audit of the official developer API. See
[Clan Games Tasks](clan-games-tasks.md).

## Remaining ClashKing request inventory

A source scan of executable Python request owners (`utils/`, `extensions/`,
`cwl_web/` and `main.py`) found the following calls. Their feature consumers
reuse these owners; tests, UI labels and historical documentation are not
additional transports.

| Request owner | Remaining request | Reason to retain |
| --- | --- | --- |
| `utils/clash_links.py` | POST `/v2/links/shared` | Community Discord-to-player ownership, not game state. Official game data cannot manage ClashKing's linking records. |
| `utils/link_management.py` | GET/POST `/v2/links/{discord_id}`; DELETE `/v2/links/{discord_id}/{player_tag}` | Lists, transfers and deletes that service's own ownership links using its separate credential. |
| `utils/gold_loot.py` | GET `/v2/player/{tag}/battlelog/history` with `time[after]` | Stored farming/ranked/legend gold observations for historical leaderboards. Current snapshots cannot reconstruct missed historical events. |
| `utils/strike_wars.py` (`fetch_history_report`) | GET `/v2/clan/{tag}/wars` with date bounds/limit; fallback GET `/war/{tag}/previous` with timestamp bounds | Explicit historical strike import needs ended rosters and attacks that were never captured locally. Automatic current-war tracking uses the official API separately. |
| `utils/strike_wars.py` (`fetch_saved_wars`, `fetch_family_wars`) | GET `/war/{tag}/previous` | Older archival helper for the same historical data. No external production caller found during this review; retained without unrelated cleanup. |

No other current player/clan/war/raid ClashKing request owner was found. If a
later inventory finds an official-equivalent call, record a separate migration
follow-up rather than widening this batch. Historical payload evidence in
`docs/clashking-war-endpoints.md` and `docs/official-api-rollback.md` stays intact.

## Verification and release gates

`tests/test_tasks_official_api.py` runs real coc.py model parsing against fake
HTTP methods with socket connections prohibited. It checks the established
Tasks DTO values, group-to-war-tag calls, raid limits, error classifications,
cache/coalescing contracts, shared dashboard authentication and the separate
Clan Games source. A host-ban test rejects any `clashk.ing` text in
`utils/todo_data.py`, including accidental reintroduction in comments. These
fixtures establish local behavior, not live upstream freshness or delivery.

On 2026-10-30, the release coordinator made an authorized read-only request
using the dashboard environment's official token: `GET /v1/locations?limit=1`
returned 200 with valid items. Evidence is
`/tmp/wu-tasks-official-qa/key-check.json`; no credential is included. This
confirms that dashboard credential was accepted from the tested host at that
time. It does not establish a different bot credential's allowlist, endpoint
coverage or future validity.

Implementation is not deployment evidence. Full integration checks, detached
360/1440 Tasks fixture review, Claude acceptance and Ruggie's direct backend
release approval remain release gates. No real messages or application writes
are required for the read-only smoke.

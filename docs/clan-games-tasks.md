# Personal Clan Games points

Tasks → Clan Games shows provider-reported points for the current UTC calendar
month's event, independently of CWL signup season. There is no family goal, minimum,
completion bar or per-member target. An explicit provider zero is zero; an absent,
malformed or conflicting score is **Not available**, never assumed to be zero.
The summary shows event month, start/end countdown, source and last checked time.
After the event ends its scores remain visible until the next calendar month.

## Source and speed assessment — 2026-10-22

Use ClashPerk's authenticated `GET /v1/clans/{tag}/clan-games?season=YYYY-MM`.
One request handles all linked accounts in the same current clan. Fetch only distinct
current clans represented by the authenticated user's resolved linked accounts;
filter returned rows to those accounts by exact player tag. A player who moved clans
or has no current clan can be absent; the current clan is not proof of which clan
hosted their event. Missing scores are not disciplinary evidence.

Read-only sample for Edrag Rush, September: ClashPerk returned 17 player records.
Three warm requests measured 25/18/8 ms (median 18 ms); ClashKing's public
`/v2/player/{tag}/history/stats?type=clan_games` for one of those players measured
135/58/58 ms (median 58 ms) and returned no events. Perk authentication measured
152 ms. This is a small response-latency sample, not an upstream polling-speed SLA.
ClashPerk's FAQ describes periodic tracking (10–15 minutes). Neither provider offers
proof of an instantaneous in-game score. Provider coverage can be incomplete.

Primary sources:
- https://github.com/clashperk/service-backend/blob/main/apps/api/src/clans/clans.controller.ts
- https://github.com/clashperk/service-backend/blob/main/apps/api/src/clans/clans.service.ts
- https://docs.clashperk.com/faq#how-does-the-clan-games-scoreboard-work
- https://api.clashk.ing/docs

## Boundaries and failures

`utils/clan_games.py` owns read-only provider access and score validation;
`cwl_web/todo_games.py` adapts that result to the existing authenticated Tasks feed.
Authentication reuses the existing public `get_access_token` helper and memory-only
JWT cache. No token enters browser responses. At most five clan reads run concurrently,
each with an eight-second deadline; the existing Tasks section deadline still applies.
Redirects are disabled, response bytes bounded and requested event month verified.
Only a rejected token gets one refresh/retry. No game action, enrollment, Discord
message or provider-side tracking setup is performed.

No new Mongo/SQLite collection, baseline, scheduled tracker or score history. Existing
Tasks memory caching lasts 60 seconds. Browser snapshots retain other task views but
strip all Clan Games scores, including when reading older snapshots. Account/view
preferences remain browser-local. The replaced ClashKing activity-summing code and
family-goal behavior have been removed rather than left as a parallel implementation.

The timer uses the standard event window (22nd 08:00–28th 08:00 UTC), consistent with
Events and the source API's schedule. Special schedule changes require an update;
the in-game schedule takes precedence. No provider score call runs before the start.

## Review

Backend checks cover batching, linked-account isolation, missing vs explicit zero,
wrong season, month/year rollover, post-event scores, partial outages, cancellation,
malformed/conflicting records, response-size limits, rejected credentials, rate limits,
redirects and shared account-link authentication regressions. Frontend checks cover
escaped names, no goals, states, monthly timer and stripping persisted scores while
preserving other tasks. War attack/preparation rendering remains covered.

Isolated sample layout reviewed at 320, 390 and 1280 pixels: no page overflow,
long player names wrap, unknown and earned-score rows remain readable, source and
check time visible. Provider calls during research were read-only; no live messages,
account changes or signup changes were made.

Final start-boundary review: verified one second before opening does not contact the
provider and returns no scores, while exactly 08:00 UTC begins score lookup. The
same instant expressed in Eastern time produces the same event month and boundary.
If the short Tasks cache spans opening, the row changes to “Waiting for update”
instead of contradicting the live countdown with “Not started.” Focused backend
suite: 49 passed; full frontend suite: 213 passed; production build passed.

# Activity: personal tasks, clan wars, and game events

- Tasks uses the existing personal feed. It shows linked accounts and unfinished
  activity, not a full-clan score.
- Wars uses `/api/cwl/clan-activity?kind=war`. Members see clans containing their
  currently linked accounts. Existing editors can select the family directory.
  Regular wars and CWL rounds retain separate states. Scores and attacks come
  from the full WarClan objects, with the requested clan correctly oriented even
  when the CWL API returns it as the opponent. Unknown numbers remain unknown.
- Events is a recurring calendar plus full-clan raid status from the same scoped
  endpoint with `kind=raid`. It does not sum partial linked-account data into a
  supposed clan total. Clan Games totals are not invented: the game API does not
  provide them here.

## Calendar sources and scope (reviewed October 21, 2026)

[Clash Ninja's recurring event guide](https://www.clash.ninja/guides/when-are-the-next-ingame-events)
records Clan Games on the 22nd–28th at 08:00 UTC, CWL signup on the 1st–3rd at
08:00 UTC, and the trophy season's 28-day cycle anchored November 3, 2025 at
05:00 UTC. [War Report's event reference](https://warreport.app/about/blog/events/)
also lists the Friday 07:00–Monday 07:00 UTC raid window, matching the existing
shared raid service.

[Supercell's raid description](https://supercell.com/en/games/clashofclans/blog/game-updates/clan-capital-raids/)
confirms Friday–Monday raids, and [Supercell's CWL guidance](https://sc-clashofclans.zendesk.com/hc/en-us/articles/49529097029659-About-Clan-War-Leagues)
confirms a two-day signup period. Clock times are recurring schedule references,
not a live official event feed. The UI explains that special events and maintenance
can alter them, links sources, and gives the in-game timer precedence.

Do not give CWL a universally fixed battle-end date. Individual rounds use API
start/end times in Wars. Calendar calculations use UTC; each timestamp is then
formatted in the viewer's timezone, including that date's DST offset. The optional
UTC switch affects both calendar cards and clan raid dates. Do not copy a screenshot's
local clock times directly into UTC schedule rules.

## Ownership and safeguards

`utils/todo_data.fetch_clan_overview` reuses existing coalesced game lookups.
`utils/clan_activity.py` projects game objects without web or Discord dependencies.
`cwl_web/clan_activity.py` owns HTTP access, per-user/scope/kind cache keys, and
inflight reads. Permission is checked before every cache lookup. There are no
arbitrary player/clan lookup inputs, write endpoints, Discord sends, or new storage.
The shared Clash client remains lifecycle-managed by the personal-activity service.

Read concurrency is eight clans; each game call has a ten-second bound. A snapshot
has a sixty-second bound. One failed clan stays visibly unavailable while other
clans render. Empty links do not call the game API. More than 100 linked accounts
or clans is explicitly reported as partial. Frontend requests ignore abandoned
responses, clear results after 401/403, and poll only while visible. Calendar cards
remain usable if clan reads fail. Expired live wars await a result instead of
silently being declared final.

## Verification

Calendar tests cover Friday/Monday boundaries, month/year rollover, leap years,
28-day season rollover, nonnegative countdowns, and dates on opposite sides of DST.
Backend tests cover unauthenticated reads, forbidden family scope, invalid scope,
ignored arbitrary tags, user cache isolation, coalesced requests, directory failure,
full-clan totals, reversed sides, missing scores, private logs, and expired battles.
UI verification uses isolated game data; it is not proof of live Discord delivery.

Rendered browser checks: desktop 1440px and mobile 320/390px settings; four event
cards, timezone switch across DST, whole-clan score cards, long/escaped names,
25-clan family scope and search, member-only scope, private/absent war states,
calendar availability during clan-service failure, Retry recovery, denied access
with no score cards, and correct Events → CWL → personal CWL task handoffs. Mobile
pages do not overflow horizontally; war-type tabs scroll within their own rail.

# CWL bonus allowance

Reviewed October 21, 2026. The dashboard calculates the **number of recipients**,
not medals per player and not bonuses already awarded inside Clash. Staff still
approve the equal-chance draw and explicitly send its announcement.

## Research and rule scope

- [Supercell reward rules](https://support.supercell.com/clash-of-clans/en/articles/clan-war-leagues-rewards-2.html): allowance depends on the league during War Week; every win adds one recipient; awards expire after 21 days.
- [February 2026 update](https://supercell.com/en/games/clashofclans/blog/release-notes/the-february-update-has-escaped/): war-size-dependent rewards changed. Do not use the pre-update 30-player table.
- [April 2026 update](https://supercell.com/en/games/clashofclans/blog/release-notes/the-sound-of-clash-update/): Titan/Legend added and reward allowances rebalanced.
- [Versioned ClashKing league data](https://github.com/ClashKingInc/ClashKingAssets/blob/b8f42a707fe92d5293d46088bf536450ae422e7b/assets/static_data/war_leagues.json): explicit `minimum_bonus_amount` and `15v15_only` fields for every league. This is ClashKing-maintained static data, **not an allowance field in the official API**. Supercell's prose does not publish a complete numeric table.
- [Current game-mechanics table](https://clashofclans.fandom.com/wiki/Clan_War_Leagues): corroborates the 30-player base multiplier (twice the 15-player base). This community-maintained table supplements the official update notes; it is not an official API response.
- [Supercell February 2024 exception](https://supercell.com/en/games/clashofclans/blog/news/february-clan-war-leagues/): shortened season plus two extra awards. This demonstrates why special seasons need an override.

The versioned rule used from May 2026 onward is:

| League | 15-player base | 30-player base |
| --- | ---: | ---: |
| Bronze / Silver | 1 | 2 |
| Gold / Crystal | 2 | 4 |
| Master | 3 | 6 |
| Champion | 4 | Unsupported |
| Titan | 5 | Unsupported |
| Legend | 6 | Unsupported |

Add one per final war win. Stars decide first, then destruction percentage; a
complete tie adds nothing. Do not sum individual attack stars to determine wins.
Only supported formats and five/seven-round groups calculate automatically.
Older seasons, unsupported formats, unknown leagues, and incomplete scores need
staff confirmation. This is a versioned calculation, not a promise to discover
unannounced future rule changes. The staff-confirmed total remains available for
special events and is labeled separately in review and saved history.

## Data and concurrency

The existing participation refresh fetches official league groups and league wars.
It now retains final side stars/destruction and team size. It backfills old cached
wars missing this evidence. Invalid or in-progress replies cannot overwrite saved
final allowance evidence. A supplied mismatching war season/tag is rejected.

`utils/cwl_bonus_allowance.py` owns two additive SQLite tables, scoped by dashboard
season and CWL month, and included in the existing Mongo durable checkpoint and
backup. No roster, weights, participation records, or saved winners are migrated
or deleted. Final evidence is reused across restarts/API outages.

The first league snapshot is saved only for the current month while the group is
active and a matching current/preparation war has a future end time. Never infer
an old season's league from the current (possibly promoted) clan profile. Existing
completed seasons with no snapshot therefore require staff confirmation. Enable
participation automatic checks, or refresh during CWL, to capture the league.

Automatic preview/draw requests use `slots: null`; the server calculates the
count. An explicit integer retains the existing staff-confirmed API contract.
The calculation is part of the preview fingerprint and immutable draw snapshot.
Approval rechecks automatic evidence; changes block approval without rerolling.
Confirmed selections and unapproved reserved winners across both pools are
subtracted before drawing. An override does not bypass account/result eligibility,
authorization, CSRF, archived-season guards, or delivery receipts.

The UI keeps the automatic breakdown visible and places the optional staff count
behind a disclosure. Main/Lazy minimum attacks, equal account chances, review,
approval and manual announcement workflow remain intact.

## Verification

The affected backend suite and full frontend suite passed, together with the war
reminder gate and production build. Tests include every supported league/size,
ties, destruction tiebreaks, zero wins, shortened groups, missing/duplicate rounds,
malformed/nonfinite scores, final-result caching, season isolation, stale league
capture, preview/draw/approval races, and explicit manual fallback. The isolated
real Mongo restart drill restores both a saved league and a final war score onto
a replacement SQLite database. No live notifications were sent.

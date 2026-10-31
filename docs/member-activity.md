# Member activity tracking

Prompt54 PR A uses the official API for family accounts. One successful first
observation initializes a baseline; it does not claim the player was active.
Subsequent increases in attack wins, donations, experience, town hall, unit levels
(heroes, equipment, troops, spells) or the achievements below mark activity.
Name, war preference and builder-base trophy changes also count. Trophy increases
count only when the new value is at least5000, including crossing that threshold. Decreases, season resets,
donations received and war achievements do not count. Failed/partial reads do not
clear baselines, and stale responses cannot replace a newer observation.

The achievement allowlist follows
[ClashPerk's player tracker](https://github.com/ClashPerk/clashperk-backend/blob/main/apps/worker/src/tracker/players.service.ts)
`didAchievementChange(..., forLastSeen=true)` and its
[achievement constants](https://github.com/ClashPerk/clashperk-backend/blob/main/libs/constants/app.constants.ts):
Aggressive Capitalism, Most Valuable Clanmate, Games Champion, Heroic Heist,
Gold Grab, Elixir Escapade, Well Seasoned, Union Buster, Wall Buster,
Nice and Tidy, Superb Work, Monolith Masher, Get those Goblins!, Anti-Artillery,
Shattered and Scattered, Counterspell, X-Bow Exterminator, Mortar Mauler,
Multi-Archer Tower Terminator, Ricochet Cannon Crusher, Firespitter Finisher,
Multi-Gear Tower Trampler and Firefighter. War Hero, War League Legend,
Siege Sharer, Friend in Need and Sharing is Caring are excluded.

## Rate and lifecycle

The bot task takes a complete family roster sweep, then spreads player reads
across an hour.125 players mean125 player calls/hour, one every28.8seconds;
1000 mean1000/hour, one every3.6seconds. Catch-up is capped at one player request
per second. Clan roster and raid reads add one each per family clan per sweep. A shared
pacer caps this feature at one logical official API call/second, including clan
reads; SDK transport retries retain the existing client retry/throttle policy.
For125accounts in3fixture clans the budget is131logical calls/hour; for
1000accounts and25estimated clans it is1050/hour, with the same1/second peak.
The player schedule uses the remainder of the hour after clan reads, about
28.8seconds or3.55seconds per player respectively. Worker cancellation propagates, and stopping awaits cleanup.
Duplicate lifecycle starts do not create a second worker. No activity notification
is sent. A failed clan roster sweep never marks anyone as having left.

## Storage and raids

`PlayerActivityStore` owns `player_activity`, one `_id` per normalized player tag.
It overwrites the baseline, keeps at most30 active UTC day strings and8 raid
weekends, and stores current clan, departure time, last-seen/source and revision.
Optimistic comparisons protect concurrent updates and delayed responses. A seed
cannot replace an official reading. Membership observations use bounded timestamp
fields rather than a growing membership-event history. Leaving sets `left_at`;
returning clears it. Backup-gated migration enables expiry90days after departure.

Recent ended raid logs are merged across family clans. A raid attack in any family
clan wins over a skip, including a move between clans. Historical logs can prove
attacks only. Skips require a complete clan read and observed membership on both
sides of the weekend end, no more than90minutes apart. Outages or new tracking
therefore leave unknown weekends unknown. Eight retained observations are bounded.

For N players and400 simulated days, document count stays N. Day/weekend arrays
are capped; the unit/achievement baseline has a fixed field set. Actual BSON size
is reported by the fixture size check; production storage is measured at release.
A player who only collects resources, chats, watches attacks or does actions with
no changing exposed counter can look quiet. This is an activity estimate, not an
online-presence guarantee.

## Strike retention rollout

Strike profiles already persist `streak_count`, the latest war watermark and
pending delivery receipts. Retention never recomputes those values from history.
Records expire90days after `occurred_at` (war end or manual creation); snapshots
expire30days after war end. Strike active expiry remains60days. Imports already
reject wars older than60days; direct ingestion also rejects outside90days.
Replacement marks, notes, leave/settings data and exempt roles receive no TTL.

Before enabling TTLs, run the explicit maintenance module with the approved
production environment and a fresh local output path:

```
python -m tools.maintenance.strike_retention --output .local/strike-retention-backup-UTC --apply
```

Without `--apply` it only backs up and verifies. Three collection dumps include
counts, file/content SHA256 and collStats. Each is restored into a uniquely named
throwaway database, compared and removed. Any failure or pending streak receipt
prevents TTL creation. The original local dumps and manifest remain. The release
must independently verify active counts, streaks, expiry and replacement eligibility
before/after, retain rollback code, and record first-hour worker logs. Removing
indexes can stop future purges; rollback cannot recreate deleted audit history
without the separately reviewed backup. Never restore data over ongoing live writes.

## One-time ClashKing seed

The approved source correction is the public
`GET /v2/player/{tag}/battlelog/history?time[after]=<90-days-ago ISO>` endpoint,
already used by the gold-loot tool. It needs no DeveloperToken and uses no limit
parameter. The newest valid `battleTime` becomes `last_seen_at` only when no
existing last-seen value exists. Source is explicitly `clashking_seed`.
This is the last attack ClashKing observed (farming/ranked/legend), not last login;
it may be older than the player's actual activity. PR B labels seeded values.
Empty data, non-200, malformed data and timeouts never create a guessed date.

After the first official sweep the bot launches a background seed with at most
five concurrent reads, a30second request timeout and a120second overall deadline.
Results are logged as seeded, existing/official, unavailable, non-200, timeout and
failed counts. Attempt version/status are bounded fields on each player document.
Completed attempts are not automatically repeated; the coordinator supports an
explicit safe rerun. A canceled deadline leaves unattempted players eligible; pending batches resume
after the next hourly sweep or on restart, while completed attempts remain skipped; every write is conditional and cannot override official activity.
Bot shutdown cancels and awaits the seed and closes the HTTP session.

Fixture evidence:125players over400days retained125documents (110250 BSON bytes,
max882bytes with the minimal fixture counters; full unit baselines are larger).
Real isolated Mongo7 checks passed for backup/restore, exact TTL metadata,
purge invariance and official/seed concurrency. These are synthetic fixture
results, not evidence of production activity or a production restore.

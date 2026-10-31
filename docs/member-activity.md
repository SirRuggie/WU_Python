# Member activity tracking

Prompt 54 PR A uses the official API for family accounts. One successful first
observation initializes a baseline; it does not claim the player was active.
Subsequent increases in attack wins, donations, experience, town hall, unit levels
(heroes, equipment, troops, spells) or the achievements below mark activity.
Name and war preference changes also count. Builder-base trophy increases count; decreases do not. Trophy increases
count only when the new value is at least 5000, including crossing that threshold. Decreases, season resets,
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
across an hour. 125 players mean 125 player calls/hour, one every 28.8 seconds;
1000 mean 1000/hour, one every 3.6 seconds. Catch-up is capped at one player request
per second. Clan roster and raid reads add one each per family clan per sweep. A shared
pacer caps this feature at one logical official API call/second, including clan
reads; SDK transport retries retain the existing client retry/throttle policy.
For 125 accounts in 3 fixture clans the budget is 131 logical calls/hour; for
1000 accounts and 25 estimated clans it is 1050/hour, with the same 1/second peak.
The player schedule uses the remainder of the hour after clan reads, about
28.8 seconds or 3.55 seconds per player respectively. Worker cancellation propagates, and stopping awaits cleanup.
Duplicate lifecycle starts do not create a second worker. No activity notification
is sent. Archived/removed clans are excluded. Failed clans are logged by tag while healthy
clans keep polling. Empty family results or missing member lists never mark anyone
as having left; departures require a complete successful sweep.

## Storage and raids

`PlayerActivityStore` owns `player_activity`, one `_id` per normalized player tag.
It overwrites the baseline, keeps at most 30 active UTC day strings and 8 raid
weekends, and stores current clan, departure time, last-seen/source and revision.
Optimistic comparisons protect concurrent updates and delayed responses. A seed
cannot replace an official reading. Membership observations use bounded timestamp
fields rather than a growing membership-event history. Leaving sets `left_at`;
returning clears it. Backup-gated migration enables expiry 90 days after departure.

Recent ended raid logs are merged across every active family clan, including
clans with no current members. Any unread clan makes the sweep incomplete. Ended
weekends are marked checked only after a complete read plus an observed membership bracket,
or a positive attack; partial reads retry and unchanged rows are not rewritten. The UTC Monday 07:00
weekend-end calendar also handles a family with no raid log entries at all; it
supplies only the weekend identity, while the same membership/read gates apply. A raid attack in any family
clan wins over a skip, including a move between clans. Historical logs can prove
attacks only. Skips require a complete clan read and observed membership on both
sides of the weekend end, no more than 90 minutes apart. Outages or new tracking
therefore leave unknown weekends unknown. Eight retained observations are bounded.

For N players and 400 simulated days, document count stays N. Day/weekend arrays
are capped; the unit/achievement baseline has a fixed field set. Actual BSON size
is reported by the fixture size check; production storage is measured at release.
A player who only collects resources, chats, watches attacks or does actions with
no changing exposed counter can look quiet. This is an activity estimate, not an
online-presence guarantee.

## Strike retention rollout

Strike profiles already persist `streak_count`, the latest war watermark and
pending delivery receipts. Retention never recomputes those values from history.
Records expire 90 days after `occurred_at` (war end or manual creation). Only finalized
snapshots expire after 30 days. Incomplete/abandoned placeholders remain for 90
days, beyond the 60-day import window. Unresolved observing snapshots and old-war
staff-review quarantines never receive a TTL date. The gate reports unresolved
snapshots older than 30 days; staff review remains visible until resolved. Strike active expiry remains 60 days. Imports already
reject wars older than 60 days; direct ingestion also rejects outside 90 days.
Replacement marks, notes, leave/settings data and exempt roles receive no TTL.

Before enabling TTLs, start a **separate local throwaway mongod** on port 27155
with its own empty data directory. Source credentials stay in the approved
production environment. The restore URI must be explicitly local, non-default,
and a different server/process from the source. Run a dry gate first:

```bash
python -m tools.maintenance.strike_retention --output .local/strike-retention-backup-UTC --restore-uri mongodb://127.0.0.1:27155
```

Add `--apply` only after review and release authorization. An empty source
collection aborts unless `--allow-empty` is explicitly supplied after checking the
route. The dry run never writes to the source. Three private collection dumps
include counts, file/content SHA256 and collStats. Each is restored into a fresh
database on the separate local server, compared and removed. Explicit verification
exceptions remain effective under optimized Python. Any failure or pending streak
receipt prevents TTL creation. The manifest reports each index independently if
creation fails partway through; a false overall flag does not mean no index exists.

Rollback stops future purges with these exact index names, using the configured
collection routes (default names shown). Retain the immutable code rollback too:

```javascript
db.strike_records.dropIndex("retention_purge_after")
db.strike_war_snapshots.dropIndex("retention_purge_after")
db.player_activity.dropIndex("activity_departure_retention")
```

A real recovery command verifies the retained file hashes, content hashes and
counts, then restores to a fresh `wu_retention_recovery_<uuid>` database on the
local server. It never overwrites live collections, and prints the recovery DB:

```bash
python -m tools.maintenance.strike_retention --restore-backup .local/strike-retention-backup-UTC --restore-uri mongodb://127.0.0.1:27155
```

The local recovery database remains for inspection; remove it after the approved
recovery assessment. Dropping TTL indexes cannot recreate deleted history.
Restoring audit history to production requires a separately reviewed procedure
that accounts for ongoing writes. The release must independently compare active
counts, streaks, expiries, replacement eligibility and protected collection sizes,
and record readiness and first-hour worker logs. No production TTL is enabled by
this development batch.

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
five concurrent reads, a 30 second request timeout and a 120 second overall deadline.
Results are logged as seeded, existing/official, unavailable, non-200, timeout and
failed counts. Attempt version/status are bounded fields on each player document.
Transient non-200, timeout and failure outcomes retry on later runs, capped at
three attempts. Completed empty/successful attempts are not repeated. A canceled deadline leaves unattempted players eligible; pending batches resume
after the next hourly sweep or on restart, while completed attempts remain skipped; every write is conditional and cannot override official activity.
Bot shutdown cancels and awaits the seed and closes the HTTP session.

Fixture evidence: 125 players over 400 days retained 125 documents (110250 BSON bytes,
max 882 bytes with the minimal fixture counters; full unit baselines are larger).
Real isolated Mongo 7.0.41 checks passed for backup/restore, exact TTL metadata,
purge invariance and official/seed concurrency. These are synthetic fixture
results, not evidence of production activity or a production restore.


Capacity planning: at roughly one regular war every two days, 90 days retains
about 45 N per-player war rows for N lineup accounts, plus manual/CWL rows in
that window; 30 days retains about 15 C clan-war snapshots for C clans. TTL deletion
is asynchronous, so allow a background-sweep margin and index/storage overhead.
The activity collection adds only one bounded document per current or recently
departed player. A representative full baseline is about 7.8 KB (174 keys), so 1000 players
add roughly 8 MB before indexes/storage overhead. Actual collStats before/after
govern rollout size; the 882-byte minimal fixture is not a capacity estimate.


### Raid evidence and low-churn polling (prompt 56)

A successful roster sweep records a compact bracket around the Monday 07:00 UTC
weekend end. This evidence persists even if raid logs fail until a later sweep.
Reading an empty log before the bracket exists never finalizes a skip. Completed
log reads and checked attack/skip evidence are separate bounded lists: historical
unknowns remain unknown without causing repeated backfill requests. Clan-history
metadata keeps at most nine week identities (eight ended plus the upcoming end)
and includes previously observed, subsequently archived clans in raid reads. An
unread clan keeps the result incomplete. Failures log clan/weekend at most hourly.

During complete sweeps, the store keeps the latest roster observation in bounded
process memory and persists membership daily, on actual moves/departures/returns,
and when a raid-end bracket is first proven. Restarting without a sufficiently
recent observation leaves that weekend unknown. Unchanged player baselines write
`updated_at` at most daily; real counter changes still persist promptly. Failed
clan reads poll last-known active members through the independent player endpoint,
without authorizing departures. No per-hour history documents are introduced.

Codex's real lane uses MongoDB **7.0.41**, confirmed by `buildInfo` and the local
binary. Claude's independent refuter used **8.0.32** (handoff 201). Production's
version has not been read for this development proof; record it during the approved
release before enabling any migration. The full baseline plus bounded raid/clan
metadata remains roughly 8–10 MB per 1000 players before storage/index overhead;
actual release collStats governs sizing.

Quiet rows may retain older `active_days` values until the next daily write. Any reader
that counts active days must filter by its current UTC date (today through 29 days
ago), never use the stored list length. The unified page does not expose or count
`active_days`; its activity signals use last-seen timestamps and raid/war evidence.


### Bounded historical war activity (PR B)

The tracker re-reads each active clan's last 60 days once a day, with at most
three concurrent reads, 120 seconds per clan and 600 seconds per job. The activity
storage owner retains one player document with fourteen recent observations and
one clan cache of at most sixty wars. Player readers exclude clan metadata;
inactive caches use the existing 90-day departure TTL. No new collection or index
is required. Version 3 replaces old completion/status fields on the next write.

No-plan FWA wars count normally; only a matching Mismatch plan is neutral.
Friendly and CWL wars are ignored. Failed reads and malformed lineups stop only
the affected current clan members' consecutive chains at their observation time;
they never count as misses. A daily refresh heals these markers. Known wars still
contribute totals, and monitored records win duplicate war keys. Exempt and
revoked observations remain neutral after ledger retention.

Failures retry after five and ten minutes, then every six hours, without charging
canceled jobs. Healthy caches are reused during another clan's outage. A new
account may refresh its own older clan cache. One small clan receipt records the
next read time; unchanged player observations do not write, including when the
Mongo client returns naive UTC datetimes. Live tracker timestamps, strikes,
streaks and replacement marks are never refreshed by historical reads. Page
metadata reads project only failed clan tags. Measure collStats during rollout.

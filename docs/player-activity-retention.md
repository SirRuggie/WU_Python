# Player activity retention

Decision D19 (backend audit 239, approved by Ruggie on 2026-11-17): delete
departed-player activity 180 days after `left_at`. The storage owner is
`utils/player_activity_store.py`; the collection route remains
`settings.player_activity`. No document migration or application write is added.

`tools/maintenance/strike_retention.py` owns only strike retention. Its former
unfiltered 90-day player-activity index step and activity manifest entry are
removed by the Shaka 1074 rework. That tool cannot create, change or drop an
activity index. Strike-record and war-snapshot policies and backup/restore gates
are unchanged.

`PlayerActivityStore.ensure_indexes()` preserves `activity_family_clan` and adds
the single-field TTL index `activity_departed_player_180d` on `left_at`, with
`expireAfterSeconds=15552000`. Its partial filter is:

```json
{
  "kind": null,
  "tag": {"$type": "string"},
  "left_at": {"$exists": true, "$type": "date"}
}
```

Player records created by `record()` have a string `tag` and no `kind`.
MongoDB equality to null includes a missing field, so these existing records
need no new discriminator. Requiring a player tag provides a positive identity
condition. `history_clan` rows have `kind: "history_clan"`; they are excluded
even when retirement adds a BSON date `left_at`, or an extra tag is present.
Active players (`left_at: null`), absent dates and scalar non-date values are
excluded. Returning players have `left_at` cleared by the existing membership
and observation paths. MongoDB TTL deletion is asynchronous, not an exact
180-day timer. MongoDB date-array matching/TTL semantics still apply to
externally malformed array-valued dates; the owned write paths only write
scalar dates or null. This change neither validates nor repairs foreign data.

Only supported partial-index equality, `$exists: true` and `$type` operators
are used; `$ne` and `$exists: false` are not supported partial-filter choices.
See [MongoDB partial indexes](https://www.mongodb.com/docs/manual/core/index-partial/)
and [TTL indexes](https://www.mongodb.com/docs/manual/core/index-ttl/).

## Release gate

After taking and verifying the backup, inventory `player_activity` indexes
**read-only** with `listIndexes` (or `index_information()`), using the configured
collection route. Record each index name, key, `expireAfterSeconds` and partial
filter in READY, including an explicit UNKNOWN if inventory cannot be completed.
If `activity_departure_retention` **or any TTL on `left_at`** already exists,
**STOP and report to Ruggie before release/index bootstrap**. Creating another
index does not disable the old retention policy. No index drop, replacement,
`collMod`, migration or production repair is authorized by D19; obtain a separate
decision for any such change. An unknown inventory also leaves this gate blocked.

Known observation (2026-11-17, coordinator's read-only inventory):
`activity_departure_retention` exists on `left_at`, `expireAfterSeconds=7776000`
(90 days), with no partial filter. **Release gate: BLOCKED.** The observation used
the documented backup tooling's configuration source; the current runtime
configuration was not independently compared. No index change was performed.
This records the blocker; it does not satisfy a later backup-verified release
inventory or authorize removing that index.

Do not run index bootstrap against production as a development check. Index
creation begins deletion eligibility for already-old player rows. Before the
release starts the bot/index bootstrap, take and **verify** a Mongo backup and
record counts for player activity, history-clan rows and protected collections,
plus protected roster counts per season/pool. Follow
`docs/dashboard-backend-releases.md` and `docs/release-history.md` for the normal
release switch, readiness, read-only smoke and count evidence. Account for only
the D19-authorized departed-player deletion; all unrelated/protected counts
must match exactly. Record eligible departed-player counts before and after
index creation and any TTL deletions separately.

D19 authorizes this specific 180-day deletion after the backup/count gate.
It does not authorize any migration, backfill, repair, extra retention policy,
or changes to tickets, strikes, `member_events`, or history-clan retention.
Rolling back code does not remove a created TTL index or restore deleted rows;
retain the verified backup, and treat index removal or data restoration as a
separate explicitly authorized production action. No live index or database
operation is part of the implementation checks.

## Index bootstrap failure

The store returns readiness from `ensure_indexes()`. A failed `create_index`
logs a traceback and the exact index name, returns false, and leaves readiness
false. The hourly worker still performs that same sweep's family-membership
read, complete-roster reconciliation, player poll and raid capture; it retries
index bootstrap on the next hourly sweep. Successful bootstrap stops retries.
Cancellation propagates; unrelated sweep failures retain their existing error
handling. Continuing observations does not waive the blocked release gate or
prove that the intended TTL is active.

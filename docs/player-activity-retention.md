# Player activity retention

Decision D19 (backend audit 239, approved by Ruggie on 2026-11-17): delete
departed-player activity 180 days after `left_at`. The storage owner is
`utils/player_activity_store.py`; the collection route remains
`settings.player_activity`. No document migration or application write is added.

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

# Narrow automatic-field release proofs

This tooling implements Ruggie's approval in handoff 400. It is an explicit new
comparison mode, not a blanket normalization of timestamps or Mongo documents.
It does not run a provider, write a database, restore production data or activate
a service. Existing comparison APIs retain their previous behavior.

## Mongo presence updates

The logical route is exactly `strike_profiles`. The permitted stored fields are:

- `current_clan_tag`
- `roster_seen_at`
- `roster_observed_at`
- `departed_clan_tag`
- `departed_last_seen_at`

The replacement row's `departed` boolean is derived, not a stored field. Its
before and after values must agree with both raw profile observations. Every
other captured replacement field and every other metrics field stays exact,
including active strike counts, streaks, membership, member-profile digest and
Warrior settings digest. Profile row keys cannot appear or disappear. All raw
profile fields outside the five named fields stay exact: names, town halls,
weights, staff actors, notes, priorities, links and manual filler state are not
excused merely because a presence update happened too.

The source audit corrects the initial writer attribution: these fields are
written by `StrikeService.sync_roster`, called by the automatic scanner in
`extensions/commands/strikes.py`. The separately named `clan_history_tracker`
was an inference in the handoff. The observed return snapshots match the exact
`sync_roster` return branch. The guard validates that branch, the corresponding
departure/transfer branch and ordinary same-clan clock refreshes; it does not
accept an arbitrary toggle. It requires a monotone, contemporaneous observation
and the writer's paired seen/observed clocks. A name or weight update made by
the same automatic scan still stops the release.

Each permitted profile row has a private proof listing its exact key, changed
field names, old/new values and presence/unset markers. Replacement totals list
row counts, departed counts and the proven number of flag changes. Row counts
must remain identical. A changed active count or other total does not pass on
this evidence.

## Ordinary capture observations

Only these four additional columns can vary:

| Table | Primary key | Column |
| --- | --- | --- |
| `participation_source_results` | season_id, cycle, tag | `checked_at` |
| `participation_group_observations` | season_id, cycle, clan_tag | `observed_at` |
| `participation_war_observations` | season_id, cycle, war_tag, clan_tag | `observed_at` |
| `participation_war_fetches` | season_id, cycle, war_tag | `observed_at` |

Keys, row sets and all neighbouring columns must remain exact. Timestamps must
move forward inside the observation interval. Every changed row and old/new
timestamp is recorded, with counts per table. Other protected tables and staff
proof tables remain exact, including weights, roster entries, signups and
publications. This mode rejects even a receipted concurrent staff change; it
does not inherit the older proof mode's publication/mark allowance.

The coordinator's previously approved normalization of
`participation_sync_settings.last_checked_at` is outside this new module and is
not widened here. Its existing 13-case reader regression remains required. The
new module itself does not ignore that column if it is present in a capture.
Other role, expiry, delivery and maintenance fields remain strict.

## Integration and validation

`compare_mongo_files` consumes two independent metrics files and their typed,
contemporaneous BSON profile proofs. `compare_sqlite_files` consumes two
independent protected SQLite captures. Both write a private 0600 proof with input
SHA256 hashes. A proof path cannot overwrite an input. The API returns evidence
only after all captured comparisons pass.

Before any use, Claude must review this committed diff. The 125/117 coordinator
must pin the approved tooling revision and file hashes, invoke this mode at the
backup, pre-switch and post-switch comparisons, retain each proof, and run its
actual control-flow/rollback rehearsals. It must not disable a guard after a
failure. No activation or guard change has been made in production for this
source implementation.

The new and existing guard suites pass 98 cases and 18 subtests. Three wildcard
mutations are killed: accepting arbitrary profile fields, skipping other SQL
tables, and accepting neighbouring capture columns. These are tooling tests;
the application suites are separate, and this change does not claim a new full
application run or live capture success.

Offline evaluation of the preserved stopped attempts passes without another
production read: the first snapshot pair records 32 changed presence rows and
two return flags; the third records 39 rows and one return flag. The ordinary
capture pair records 124 source timestamps, six group timestamps, six war
timestamps and 24 fetch timestamps. Raw proofs stay private and are not committed.
The initial combined test launch lacked loopback access for existing HTTP
fixtures; it was stopped and its log retained. The final external-network-blocked
run with isolated loopback fixtures passed.

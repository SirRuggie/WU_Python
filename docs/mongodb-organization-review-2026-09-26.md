# MongoDB organization review — 2026-09-26

> Follow-up: [live inventory and complete naming proposal](mongodb-naming-proposal-2026-09-26.md).
> This section records the earlier source-only review; the linked follow-up has newer evidence.

Initial source audit at `66fda6f` on `main`. No production database connection,
data mutation, configuration change, or deployment was performed. Live sizes,
indexes, grants, backups, and deployed revision remain unverified.

## Current boundaries

| Database | Purpose | Source |
| --- | --- | --- |
| `settings` | Production bot data | `utils/mongo.py` |
| `ticket_testing` | Discord ticket exercises and TEST counters | `extensions/commands/tickets/testing_service.py` |
| `wubot_test` | Automated regression tests with dedicated credentials | `tests/mongo_test_support.py` |
| `database` | Historical stray CWL migration source; existence unverified | `tools/migrate_cwl_reminders.py` |

The wrapper hard-codes `settings`; changing only the URI database name will not
redirect its collections. Preserve both test boundaries.

## Old backlog findings already addressed in source

- Inspected ticket audit writes in store, flag store, and account sync use
  bounded `$slice` updates.
- Ticket store reads have normalization helpers and normalized return paths.
- Ticket index setup caches failures with a retry deadline.
- The wrapper documents independent ticket collection schema versions.
- New `lazy_cwl_lists` storage has a `purge_at` TTL and unique active-list guard
  by section and clan. Legacy snapshots remain for migration.

These observations do not prove live indexes exist or old records were compacted.
Other old checklist entries still need individual verification.

## Confirmed remaining source work

- `main.py` constructs the client without explicit pool, operation-timeout,
  timezone, or application-name settings. Missing-URI validation and shutdown
  already exist. Review timeout and datetime consumers before global changes.
- Production routing is also hard-coded in `band_sync_ical.py` (legacy config
  source), and tools `migrate_media_to_r2.py`, `find_duplicate_clans.py`,
  `trade_diagnose.py`, `reset_thread_ticket_test_data.py`, and
  `rename_ticket_threads.py`. Keep historical CWL migration sources explicit.
- FWA points mixes config and per-clan rows, with several ISO-string timestamps.
  Changes require compatible reads and a feature-specific migration.
- Poll creation posts to Discord before persisting the poll, leaving a
  process-failure window for an orphan message.
- Startup FWA image loading awaits Mongo outside the later exception handler.
  Autocomplete preloading is imported but not called in `main.py`.
- PyMongo is unpinned; select a version using runtime evidence and regression
  coverage, not the older document's version suggestion.
- No Mongo backup implementation was found in `tools/` or `deploy/`.
  Host-managed backups outside the repository may still exist.

## Proposed organization

The destination database name is undecided. The earlier `wubot` suggestion
was a project preference, not a MongoDB best practice. Verify the actual Atlas
project/cluster/database hierarchy before selecting or creating a destination.
Retain collection names unless a specific rename improves their meaning. Create a feature-grouped registry of collection owners, purpose, keys,
retention, schema/index owners, and migration dependencies.

| Group | Collections declared in the wrapper |
| --- | --- |
| Shared | `bot_config`, `button_store`, `component_state`, `emoji_registry` |
| Clans | `clan_data` |
| Tickets | `ticket_setup`, `tickets`, `ticket_flags`, `ticket_migrations`, `ticket_migration_batches`, `ticket_creation_state`, `ticket_automation_state`, `ticket_rollout`, `ticket_open_slots` |
| Recruitment | `recruit_onboarding`, `recruit_challenges` |
| FWA/CWL | `fwa_data`, `fwa_band_data`, `fwa_points`, `fwa_blacklist`, `lazy_cwl_snapshots`, `lazy_cwl_lists`, `cwl_reminder`, `cwl_pending_reminders`, `fwa_sync_config`, `fwa_sync_events`, `fwa_sync_responses`, `fwa_sync_deliveries` |
| Todo/history | `player_clan_candidates`, `player_clan_watches`, `clan_roster_snapshots`, `todo_sessions` |
| Cards | `card_inventories`, `card_trades` |
| Polls | `wu_discord_polls` |

This is a source inventory, not an Atlas ownership inventory. The wrapper
distinguishes WU polls from Arcane's `discord_polls`: check shared ownership
before moving anything. Also inventory legacy `fwa_sync_alerts`, read outside
the wrapper, and document kinds within shared collections. Do not assume all
collections in `settings` belong to this bot.

## Recommended sequence

1. Inventory live metadata, counts, sizes, validators, TTL/unique indexes, grants,
   and other writers using read-only access. Confirm backups and rehearse
   restoration into an isolated destination. Compare permanent data separately
   from expiring runtime rows.
2. Centralize production database selection with `settings` as the default.
   Route the wrapper and tools through it; preserve explicit historical sources.
   Reject reserved test databases as production targets. Test default/override
   routing, collection aliases, and isolation.
3. Harden one feature at a time: connection/startup policy, then poll creation
   and FWA points separately. Preserve ticket history, counters, and migration
   checkpoints. Decide retention before cleanup.
4. Rehearse the move with an ownership allowlist and capacity check. Pause all
   relevant writers, back up, restore to the selected destination, compare durable documents,
   indexes/options, counters and checkpoints, then switch configuration and
   verify behavior. Preserve collection names and document IDs.
5. Retain the source until acceptance. Before new writes, rollback can restore
   the old setting. After new writes, stop writers and reconcile changes first;
   switching back alone would lose tickets/counter changes. Document and test
   that recovery path before cutover.

MongoDB supports namespace remapping using `mongorestore --nsFrom/--nsTo):
[official examples](https://www.mongodb.com/docs/database-tools/mongorestore/mongorestore-examples/).
The inventory, freeze, verification, and rollback sequence above is proposed
project policy. Exact commands depend on the inventory and restore rehearsal.

First implementation slice: centralized database selection with routing and
isolation tests, continuing to use `settings` by default. Activating the destination
follows verified restoration and grants. Collection renames, clan-key migration,
legacy deletion, and retention changes are separate work.


## Official guidance checked 2026-09-26

MongoDB distinguishes deployment/cluster, database, collection, and document.
A database contains collections; collections contain documents. Naming the
database after an application is a project convention, not a mandatory rule.
The code selects `settings`; this review has not established what other database
or cluster names already exist in Atlas.

- [Databases and collections](https://www.mongodb.com/docs/manual/core/databases-and-collections/)
- [Data modeling best practices](https://www.mongodb.com/docs/manual/data-modeling/best-practices/): organize around access patterns, index common queries, and validate important schema constraints.
- [Naming restrictions](https://www.mongodb.com/docs/manual/reference/limits/#naming-restrictions): legal names are distinct from stylistic conventions.
- [Connection pools](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/connection-pools/): pool settings are workload-dependent; the earlier pool-size suggestion is not a universal vendor recommendation.

Project recommendation: choose database boundaries for ownership, access, and
environment isolation; choose collection names for the entities they contain.
Lowercase snake_case and plural entity names are proposed consistency rules,
not MongoDB requirements. Keep related bot features together unless a distinct
access or lifecycle need justifies separate databases. A config/settings
collection should contain configuration, not unrelated tickets and inventories.

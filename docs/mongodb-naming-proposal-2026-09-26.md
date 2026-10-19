# MongoDB names and migration preparation — 2026-09-26

> Phase 1 recovery rehearsal passed: [backup and restore evidence](mongodb-phase1-recovery-2026-09-26.md).

Status: proposal for review. Inventory queries were read-only. No databases or
collections were created, renamed, copied, or deleted. Bot routing is unchanged.

## Observed deployment

The configured connection could list these non-system databases. Visibility is
limited to this credential; Atlas project and cluster display names were not
queried. No database named `wubot` appeared.

| Current database | Collections | Documents at inspection |
| --- | ---: | ---: |
| `database` | 2 | 1 |
| `settings` | 37 | 9,015 |
| `ticket_testing` | 8 | 14 |
| `wubot_test` | 1 | 0 |

Counts are a live observation, not a consistent backup snapshot. Metadata,
indexes, validators, and storage sizes are saved in
[mongodb-inventory-2026-09-26.json](mongodb-inventory-2026-09-26.json).
No user documents or connection credentials are included.

## Proposed database names

| Current | Proposed | Purpose and timing |
| --- | --- | --- |
| `settings` | `warriors_united` | Production application data. Describes the owning community without repeating “bot”. |
| `ticket_testing` | `warriors_united_sandbox` | Interactive Discord exercises. A separate later move; do not combine with production cutover. |
| `wubot_test` | `warriors_united_test` | Automated tests. A separate later move requiring the test credential, URI validation, runner, and documentation to change together. |
| `database` | No destination by default | Historical CWL data. Compare against current state and prove it is unused before eventual retirement. Do not merge blindly. |

Leave Atlas project/cluster names unchanged. These database names are project
conventions, not MongoDB requirements. One production database keeps related
features together; separate sandbox/test databases preserve environment and
credential boundaries.

## Every production collection

All destination names below are inside `warriors_united`. Keep names that
already explain the contents; rename ambiguous names or mark compatibility
collections explicitly. This is a namespace move only: no simultaneous field,
document-ID, retention, or schema changes.

| Current collection | Proposed collection | Documents | Ownership / migration note |
| --- | --- | ---: | --- |
| `bot_config` | `bot_config` | 26 | Keep for the naming pass; separate campaign data in a later schema change. |
| `button_store` | `legacy_button_store` | 390 | Mixed legacy state; move whole collection without reclassifying records. |
| `card_inventories` | `card_inventories` | 63 | Keep descriptive existing name; preserve current data and index behavior. |
| `card_trades` | `card_trades` | 92 | Keep descriptive existing name; preserve current data and index behavior. |
| `clan_data` | `clans` | 25 | Clan records; preserve document IDs in the naming move. |
| `clan_roster_snapshots` | `clan_roster_snapshots` | 25 | Keep descriptive existing name; preserve current data and index behavior. |
| `component_state` | `component_state` | 0 | Keep descriptive existing name; preserve current data and index behavior. |
| `cwl_pending_reminders` | `cwl_pending_reminders` | 18 | Active jobs include current campaigns; retain and migrate with CWL state. |
| `cwl_reminder` | `legacy_cwl_schedules` | 1 | Old schedule source still referenced by CWL compatibility code. |
| `emoji_registry` | `emoji_registry` | 60 | Ownership records, not disposable cached emoji data. |
| `fwa_band_data` | `band_monitor_state` | 186 | Mixed BAND checkpoint and response state; no document split in this pass. |
| `fwa_blacklist` | `fwa_blacklist` | 1,957 | Keep descriptive existing name; preserve current data and index behavior. |
| `fwa_data` | `fwa_config` | 1 | FWA configuration and base content. |
| `fwa_points` | `fwa_points` | 8 | Config and points rows are mixed; split only in a separate schema migration. |
| `fwa_sync_alerts` | `legacy_fwa_sync_alerts` | 34 | Historical sync source; retain until compatibility reads are retired. |
| `fwa_sync_config` | `fwa_sync_config` | 1 | Keep descriptive existing name; preserve current data and index behavior. |
| `fwa_sync_deliveries` | `fwa_sync_deliveries` | 0 | Keep descriptive existing name; preserve current data and index behavior. |
| `fwa_sync_events` | `fwa_sync_events` | 0 | Keep descriptive existing name; preserve current data and index behavior. |
| `fwa_sync_responses` | `fwa_sync_responses` | 0 | Keep descriptive existing name; preserve current data and index behavior. |
| `lazy_cwl_lists` | `lazy_cwl_lists` | 7 | Preserve validator, unique partial indexes, TTL, and majority write concern. |
| `lazy_cwl_snapshots` | `legacy_lazy_cwl_snapshots` | 94 | Historical migration source; retain until migration dependencies are retired. |
| `player_clan_candidates` | `player_clan_candidates` | 1,137 | Keep descriptive existing name; preserve current data and index behavior. |
| `player_clan_watches` | `player_clan_watches` | 145 | Keep descriptive existing name; preserve current data and index behavior. |
| `recruit_challenges` | `recruit_challenges` | 0 | Keep descriptive existing name; preserve current data and index behavior. |
| `recruit_onboarding` | `recruit_onboarding` | 80 | Preserve role-cleanup state. |
| `ticket_automation_state` | `ticket_automation_state` | 1,576 | Durable workflow/side-effect state; do not add blanket TTL. |
| `ticket_creation_state` | `ticket_creation_state` | 16 | Keep descriptive existing name; preserve current data and index behavior. |
| `ticket_flags` | `ticket_flags` | 230 | Preserve inactive flags and bounded audit history. |
| `ticket_migration_batches` | `ticket_migration_batches` | 4 | Preserve bulk migration checkpoints. |
| `ticket_migrations` | `ticket_migrations` | 1,206 | Preserve resumable checkpoints and IDs. |
| `ticket_open_slots` | `ticket_open_slots` | 27 | Keep descriptive existing name; preserve current data and index behavior. |
| `ticket_rollout` | `ticket_rollout` | 2 | Keep counters and rollout state together unchanged for this pass. |
| `ticket_setup` | `ticket_config` | 3 | Ticket configuration; preserve every existing row. |
| `ticket_thread_rename_runs` | `ticket_thread_rename_runs` | 3 | Tool-owned checkpoints; not declared in the main client wrapper. |
| `tickets` | `tickets` | 1,596 | Permanent ticket history; no blanket TTL. |
| `todo_sessions` | `todo_sessions` | 2 | Keep descriptive existing name; preserve current data and index behavior. |
| `wu_discord_polls` | `discord_polls` | 0 | WU-owned polls only; destination must not contain another bot’s polls. |

## Sandbox and automated test collections

For the proposed `warriors_united_sandbox`, mirror production collection names:

| Existing sandbox collection | Proposed name |
| --- | --- |
| `component_state` | `component_state` |
| `ticket_automation_state` | `ticket_automation_state` |
| `ticket_creation_state` | `ticket_creation_state` |
| `ticket_flags` | `ticket_flags` |
| `ticket_open_slots` | `ticket_open_slots` |
| `ticket_rollout` | `ticket_rollout` |
| `ticket_setup` | `ticket_config` |
| `tickets` | `tickets` |

The sandbox facade also declares `ticket_migrations`, `button_store`,
`bot_config`, and `ticket_setup`, although some are not currently materialized.
Apply the same mapping to every declared alias, including
`button_store → legacy_button_store` and `ticket_setup → ticket_config`.
Keep TEST-number allocation separate throughout.

The existing empty `wubot_test.wubot_test` starter collection is not a domain
collection. Leave it untouched during production migration. The eventual
`warriors_united_test` database needs no equivalent permanent starter
collection: regression tests already create uniquely named temporary
collections. Adjust credential grants and test guards as their own change.

## Findings to resolve before moving

- `settings.clan_data` has 25 records and only its `_id_` index. The
  `uniq_clan_tag` guard expected by source code is absent. Run a projected
  duplicate-tag check and inspect the live startup path before repairing it.
  This inventory does not establish whether duplicate tags exist.
- `settings.lazy_cwl_lists` does have a strict validator and five indexes.
  Capture and preserve these rather than relying on copying documents alone.
- The legacy `database` contains one CWL schedule record and an empty pending
  collection. Empty does not prove abandoned; determine writer/reader usage.
- `bot_config` stores CWL campaigns and defaults; changing it to simply
  `settings` would still disguise mixed-purpose data. Keep its current name
  during migration; later extract `cwl_campaigns` and `cwl_config` using
  explicit document-kind rules after auditing every consumer.
- `fwa_points` mixes configuration and per-clan rows. A later split can retain
  `fwa_points` for clan results and introduce `fwa_points_config`.
- `fwa_band_data` mixes a permanent processing checkpoint and expiring response
  records. `band_monitor_state` describes both without changing behavior.
- No `discord_polls` collection was visible in this inventory. The source's
  Arcane warning still requires checking ownership of any destination collision.
- `mongodump`, `mongorestore`, and `mongosh` were not found on this shell's PATH.
  Verify or provision compatible Database Tools before recovery rehearsal.
- Database grants, other clients/writers, backup jobs, and available destination
  capacity have not been verified. Database metadata is not an Atlas cluster
  capacity report.

## Concrete preparation and migration sequence

1. Review the naming map. Treat the accompanying
   [JSON map](mongodb-naming-map-2026-09-26.json) as data for a future migration
   tool, not an executable migration.
2. Add central explicit mappings from stable Python aliases to database and
   collection names. Support feature-scoped routing so a moved feature cannot
   fall back silently to its old destination. Keep historical source lookups
   explicit. Preserve collection-specific write concerns.
3. Update hard-coded maintenance tools and BAND legacy lookups. Include
   `ticket_thread_rename_runs` in ownership/backup scope. Test both source and
   destination mappings and the sandbox facade, including absent collections.
4. Establish an ownership allowlist, backup job and isolated restore rehearsal.
   Verify destination grants, capacity and collision handling. Refuse to merge
   into a nonempty destination without an explicit reconciliation plan.
5. Start with the clans slice once the tag-index finding is resolved. Briefly
   pause its writers, capture a backup, copy documents/indexes/options to
   `warriors_united.clans`, compare IDs and content, switch the shared alias
   and direct tools, then verify clan reads/updates across all consumers.
6. Handle ticket collections as a coupled group: tickets, slots, creation state,
   counters, flags, automation, configuration and migration checkpoints.
   Stop corresponding background writers too. Move CWL campaigns/jobs and
   shared configuration only after defining their routing dependencies.
7. Before writes resume, source-based rollback is straightforward. After writes
   resume, returning to the old database requires stopping writers and
   reconciling new data/counters first. Retain the source until accepted;
   deletion is a separate operation.
8. Repeat for the remaining features. Sandbox and automated-test renames follow
   as independent changes, preserving their credentials and isolation rules.

## Basis

The hierarchy and schema principles follow MongoDB's
[databases and collections](https://www.mongodb.com/docs/manual/core/databases-and-collections/)
and [data-modeling guidance](https://www.mongodb.com/docs/manual/data-modeling/best-practices/).
The exact names and feature migration batches above are project recommendations.

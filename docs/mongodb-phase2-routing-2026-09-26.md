# MongoDB Phase 2 — routing preparation

Implemented locally on 2026-09-26. No production data, indexes, environment
settings, or service state changed. No database was migrated.

## Implementation

utils/mongo_routes.py owns all 37 production collection routes, keyed by stable
Python aliases. Defaults preserve existing physical namespaces. The bot wrapper
and the RoutedCollections maintenance-tool facade use the same mapping.

Updated tools: find_duplicate_clans.py, trade_diagnose.py, migrate_media_to_r2.py,
reset_thread_ticket_test_data.py, and rename_ticket_threads.py.

The BAND compatibility reader has its own legacy_fwa_sync_alerts route. The
CWL migration source remains explicitly database.<collection>; its destination
follows bot routing. The thread-renaming tool's checkpoint collection is also
registered. Existing clients retain frozen route snapshots; an empty or
unavailable destination never triggers fallback to the source. LazyCWL majority
write concern is preserved for bot and tool access.

## Configuration — activate only after a verified migration

Leave MONGODB_ROUTES unset or set to {} to preserve all current destinations.
After the future clan copy passes verification, the proposed .env entry is:

    MONGODB_ROUTES='{"clans":{"database":"warriors_united","collection":"clans"}}'

This was NOT added to the real .env file. It moves only the clans alias, with no
ID, schema, or retention change. Restart affected clients after configuration
changes. Bot and maintenance tools must use the same configuration.

Validation rejects malformed JSON, duplicate keys, unknown aliases, missing/extra
fields, duplicate destinations, invalid names, and production routes into system,
historical, or test databases. Names deliberately follow lowercase letters,
digits and underscores, with the configured Atlas Free namespace/name limits.
load_routes(overrides) validates a full map without connecting to MongoDB.

Discord testing retains its independent ticket_testing facade and TEST counters.
Automated real-Mongo tests retain their wubot_test guard and dedicated credential.
Neither inherits production overrides. Current and proposed test/sandbox
database names are reserved against production routing.

The registry does not infer cross-collection business dependencies or prove the
destination contains correct data. Coupled feature moves still require a
coordinated migration plan.

## Read-only clan audit

25 records; zero exact duplicates; zero duplicates after tag normalization;
zero missing, invalid, or noncanonical tags under the audit's Clash tag check.
Only the _id_ index exists: uniq_clan_tag is absent.
[Audit metadata](mongodb-clan-audit-2026-09-26.json) contains counts only.

Source tracing found ensure_clan_tag_index is called only by the clan-add
handler in extensions/commands/clan/dashboard/update_clan_info.py, not startup.
The old documentation's startup claim was wrong. A fresh process therefore
does not guarantee the index exists before a clan is added. This explains the
coverage gap, but does not establish whether an earlier attempt failed or
whether deployed code differs.

No index was created in Phase 2. Repeat the tag audit during the future write
pause and build/verify the destination's unique index before cutover. Startup
index reconciliation should be an explicit subsequent fix.

## Prepared clan migration — not executed

1. Deploy routing code with MONGODB_ROUTES absent and confirm clans still
   resolves to settings.clan_data.
2. Identify all clan writers, stop the bot, and coordinate maintenance tools.
   Stopping the whole bot avoids assuming every clan writer is gated.
3. Repeat the projected tag audit while writes are stopped. Abort for invalid
   tags, duplicates, or unexplained source changes.
4. Take a fresh dump of settings.clan_data and its metadata using Phase 1
   tooling; record its checksum and document count.
5. Verify warriors_united.clans has no existing data. Do not merge blindly
   or drop an unexpected destination collection.
6. Restore only that namespace with --nsInclude=settings.clan_data,
   --nsFrom=settings.clan_data, and --nsTo=warriors_united.clans. Use a protected
   tool configuration file for credentials.
7. Compare every document's BSON content/ID, count, options, and restored
   indexes. Create/verify uniq_clan_tag on tag with unique=True. This is the
   one intentional index addition; preserve the current document IDs.
8. Apply the clan-only route override to the service and tools, start the bot,
   and check clan dashboards/list, recruitment selection, and autocomplete.
   Verify an approved reversible clan update reaches the destination.
9. Preserve the source. Before new writes, revert the override if needed.
   After new writes, stop writers and reconcile changes back before reverting,
   or repair forward; never discard new clan edits by blindly switching back.
10. Record acceptance; retire the source separately.

The Phase 1 dump proves recovery, but the cutover requires a fresh write-paused
copy.

## Verification

Focused regressions: **199 passed, 18 skipped**. Optional real-Mongo cases were
skipped; production was not used for tests.

Coverage includes all live/default routes, the full proposed naming map, async
bot/sync tool agreement, configuration errors before bot client construction,
destination collisions, frozen routes, no fallback, majority write concern,
sandbox isolation, BAND compatibility reads, media tools, startup, and clan
permissions.

Python compilation, encoding checks and git diff --check passed. A search of
utils, extensions and tools found no remaining direct hard-coded production
settings access; namespace definitions are centralized in the registry.

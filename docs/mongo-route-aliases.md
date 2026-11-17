# Mongo collection alias ownership

Decision 239 F (D8 and D5): collection selection belongs to
`utils.mongo_routes`. Feature code uses `collection_for(client, alias)` for
root aliases and `collection_from(parent_collection, alias, **options)` for
collections historically placed beside another configured collection. The alias
name and default collection name match the former direct selection. No collection
is renamed, copied, indexed or migrated by this refactor.

`PARENT_ALIASES` records the original database inheritance. For example,
`war_reminder_settings` follows `bot_config`'s database, and `war_weight_settings`
follows `fwa_data`'s database. A parent database override propagates to children;
a child's explicit route override takes precedence. A parent collection-name
override never renames its child. All routes retain uniqueness and existing
production namespace validation. Each resolved collection handle carries its own immutable route context, so
equal parent handles from two facades on the same client cannot redirect each
other’s child collections. Plain collection facades retain their parent database. Write concern options remain attached at the original call sites.
Dead `wtimeout` options are removed; majority/journal options remain unchanged,
and the existing client CSOT governs operation timeouts.

The isolated Discord ticket exercise facade uses `ticket_test_collection`.
Its allowlisted aliases always resolve in the fixed `ticket_testing` database
and cannot inherit production route overrides. It is intentionally separate from
production alias validation and cannot select arbitrary collection names.

A tracked-source architecture regression rejects direct `get_collection` calls
outside this owner. Fixture tests establish route/default/override parity without
opening a Mongo connection or reading production data.

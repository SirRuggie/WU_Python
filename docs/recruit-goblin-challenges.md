# Goblin challenge storage and recovery

Goblin prompts use `settings.recruit_challenges`, alongside the independently
namespaced family-code challenges. They no longer read or write runtime state
in `button_store`.

Each schema-version-1 document has the natural key
`goblin_ping:<channel_id>:<user_id>`, a unique session ID, recruiter ID, channel
and recruit IDs, UTC creation/expiry dates, and a pending/processing/completed
status. New records also include the guild ID; legacy records do not contain it.
Channel IDs are globally unique, so legacy isolation does not require guessing a
guild ID.

The existing `family_code_expiry` TTL index covers both challenge types. Every
reader also checks `expires_at`, so an expired prompt stops working immediately
even before Mongo's TTL sweep. Lifetime remains 24 hours from prompt creation.
Completed records retain the confirmation message ID until that expiry.

A valid reply atomically claims its exact session for two minutes. Concurrent
replies cannot both claim it. Confirmation delivery has a 60-second timeout;
failed delivery releases the claim for another reply instead of deleting it.
A stopped process leaves a durable claim that can be reclaimed by the next valid
reply after its lease expires. This recovery does not require an in-memory timer
or a bot restart. A replacement prompt cannot be cleared by an older completion.

Discord delivery and Mongo writes are not one transaction: a crash after Discord
accepts a message but before completion is recorded can result in a repeated
confirmation on a subsequent valid reply. The design preserves the recruit's
ability to finish instead of silently losing their challenge.

On startup, create/check the TTL index before migration. Copy valid legacy
`challenge_type: goblin_ping` records using `$setOnInsert`, newest first, before
deleting each exact source record. Preserve existing new-system sessions and
all unrelated legacy documents. Malformed rows are preserved and logged for
review. Original expiry dates are retained, including expired legacy records.
Migration is safe to rerun after an interrupted copy/delete. Storage/index errors
are logged and leave unprocessed source records intact for a subsequent startup.

The Shield button is removed only after storage and the follow-up prompt succeed.
“How to ping” only responds for the recruit's own active challenge. Message text,
component layouts, colors, GIFs, and footer artwork remain unchanged.

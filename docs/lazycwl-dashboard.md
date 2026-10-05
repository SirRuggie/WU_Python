# CWL Return Pings

Open this workspace from `/manage` by choosing **CWL Return Pings**, or select it
in the command's optional `section` choice. See [Server Management](manage-dashboard.md).

`/manage section:CWL Return Pings` is the administrator dashboard for CWL saved player lists. It
replaces `/lazycwl` and the nine retired `/fwa lazycwl-*` commands. Those
old command names are no longer registered; use `/manage section:CWL Return Pings` directly.

## Dashboard flow

Open `/manage` → **CWL Return Pings**. It starts on **FWA → All FWA clans**; select one clan when needed. Main is available separately and defaults to All Main clans. The existing internal `cwl-rosters` route remains compatible.

- **Save Current Members** saves current membership for clans without a saved list. Existing lists are retained.
- **Replace Saved Members** appears for an individual saved clan and reviews the replacement before applying it. The old tracking and reminders stop; current members form the replacement. Failed replacements keep the original list.
- **Send Ping Now** immediately checks current recipients and sends only for clans with players away. It does not start automatic pings or reset the timer. The existing public ping format is unchanged.
- FWA offers **Start Return Pings**, **Pause Return Pings**, and **Resume Return Pings**. Frequency choices are 30 minutes, 1 hour, and 2 hours and save automatically. Paused pings stay paused when frequency changes.
- Automatic checks end seven days after the original start, or at saved-list expiry on the 16th at 00:00 UTC, whichever comes first. Pause/resume and frequency changes never extend that deadline. Everyone home skips one ping but keeps future checks running.
- Bulk failures show the affected clans and offer **Retry Failed Clans** without restarting successful clans.
- Main has manual return pings only. Saved-member editing remains a secondary tool; no extra player browser is required for routine pinging.

The panel shows scope, saved-list status, away counts, frequency, next check, and stop time. Destructive Clear/Replace operations retain review. Private panels remain bound to the opening administrator/server and expire after 20 minutes. Reopen `/manage` after expiry or a restart; saved members and timer state persist.

## Storage and lifecycle

`utils/lazy_cwl_store.py` owns the `lazy_cwl_lists` collection. Active lists
are unique by section and clan tag. Section and CWL season are captured on
the roster and do not change when a clan is reclassified. Finished and expired lists remain available until
MongoDB removes them 90 days after their expiry date.

On startup, the service creates its indexes, imports active records from the
retired `lazy_cwl_snapshots` collection, expires due lists, and restores
enabled reminder jobs. Each migrated list records its legacy snapshot id, so
repeating startup never creates a second list. The legacy row is retired only
after its destination is present, preserving existing active rosters and
their reminder configuration through the transition.

All lists, including imported legacy snapshots, expire at midnight UTC on
the 16th of their original saved month. A list saved on or after the 16th
expires on the 16th of the following month. Importing never renews that
deadline: overdue snapshots are imported as expired with reminders disabled.
Startup also idempotently corrects imported records whose expiry was
previously calculated from the migration date instead of the capture date.
The clan dropdown shows saved and expiry dates in UTC for active rosters.

Section policies independently specify expiry day and reminder destination.
Both sections initially retain the 16th-day expiry rule. CWL season is the
expiry month, so captures on/after the 16th belong to the next season.
Main sends manual return reminders to the Main CWL channel and has no
scheduled reminder jobs.

## Reminders

An enabled FWA reminder runs at its chosen interval for up to seven days. The
scheduler records successful sends and restores the next future run after a
restart, without replaying missed intervals. A scheduler registration failure
is retried by the startup reconciler; the database never claims that a newly
enabled reminder is running when its job could not be registered.

Manual reminders in both sections and scheduled FWA reminders recompute the
current away players from the Clash API. Main also refreshes Discord links before sending, so older Main captures can mention linked players.
If nobody is away, no Discord message is sent.

## Safe dashboard actions

Reviewed actions carry the saved-list ID from their review. Immediate ping
actions resolve the selected clan scope and bind its current saved-list IDs
before applying changes. The service includes
that id in the database write query. If the list was finished and replaced
while a confirmation was open, the action returns a stale-list result and
does not change the replacement roster or its reminder configuration.

This applies to finishing a list, removing players, adding a player, turning
reminders on or off, and sending a manual reminder. Refresh the dashboard
after a stale result, then make the intended change from the current list.

## Data shape

An active list has a normalized `#UPPERCASE` clan tag, a UTC save time,
normalized players, and this reminder state:

```
reminders: {
  enabled: bool,
  every_minutes: int | null,
  started_at: datetime | null,
  last_sent_at: datetime | null,
  sent_count: int
}
```

Each player records tag, name, Town Hall, optional Discord id, whether it was
added manually, and its UTC add time. A failed Discord-link lookup is kept
distinct from a successful lookup with no linked players. FWA capture stops
when the lookup fails. Main capture remains available during a link-service
outage; its manual reminder waits for a successful lookup before sending.

## MongoDB contract and deployment

The schema is versioned in `utils/lazy_cwl_schema.py`. New captures and legacy
imports write the current schema version, including `section` and
`cwl_season`. Existing records are backfilled as FWA. Strict database validation rejects malformed
field types, invalid statuses, repeated player tags, invalid expiry ordering,
and enabled reminders without a valid start time/interval. The existing
partial unique index still enforces one active roster per section and clan; validation
additionally enforces uniqueness *inside* each roster's player array.

The feature's collection uses `w="majority"` with a 10-second write-concern
wait bound. A write-concern timeout is an uncertain acknowledgement, not proof
that the write did not occur; refresh before retrying. The unique active-roster
index and conditional player updates remain the duplicate-write safeguards.

Apply schema changes as a deployment operation, not inside button handlers.
Run the first command from the development checkout. After stopping the bot,
run the migration and final audit from the production checkout
(`/home/botrunner/wu-bot`), where the Python environment is `venv`:

1. Run `.venv/bin/python tools/lazycwl_mongo.py` for a read-only audit.
2. Stop the bot and deploy code that writes the new schema version.
3. Run `venv/bin/python tools/lazycwl_mongo.py --apply-schema`.
4. Restart the bot and run `venv/bin/python tools/lazycwl_mongo.py`.

The tool uses `MONGODB_URI`
from the environment or the checkout's `.env`; it does not print credentials
or player records. It adds a version field to compatible existing documents
and installs the validator without deleting rosters or changing player data.
Unknown versions or validators require explicit review instead of downgrade.

Real database tests are in `tests/test_lazy_cwl_mongo.py`. Set
`LAZYCWL_TEST_MONGODB_URI` to a test-capable connection and run that file. Tests
always select `wubot_test`, use unique collection names, and remove only their
own temporary collections. They never use the `settings` database.

Audit on 2026-09-23: MongoDB 8.0.32, replica-set deployment, seven rosters,
maximum 50 players and 6,390 BSON bytes per roster before version backfill.
All four application indexes were installed. An active-clan lookup examined
one index key and one document. The prior collection had no validator; all
seven records passed the proposed additive schema preflight. Embedded players
fit this access pattern: the dashboard loads the roster together, and its
updates can remain atomic within a single document. No sharding or roster /
player collection split is warranted by the measured workload.

TTL remains retention cleanup, not a backup or an exact expiry timer. The
service's logical expiry job remains separate. Backup schedule, retention,
restore drills, and account-wide least-privilege settings require a separate
hosting/account audit; this application-level audit does not verify them.

References checked against current MongoDB documentation:

- [Single-document atomicity and conditional updates](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/)
- [Schema validation](https://www.mongodb.com/docs/manual/core/schema-validation/)
- [Unique indexes versus uniqueness within arrays](https://www.mongodb.com/docs/manual/tutorial/unique-indexes-schema-validation/)
- [TTL behavior and limitations](https://www.mongodb.com/docs/manual/core/index-ttl/)
- [Write concern](https://www.mongodb.com/docs/manual/reference/write-concern/)

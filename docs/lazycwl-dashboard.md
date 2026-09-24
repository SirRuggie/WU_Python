# CWL rosters dashboard

Open this workspace from `/manage` by choosing **CWL Rosters**, or select it
in the command's optional `section` choice. See [Server Management](manage-dashboard.md).

`/cwl rosters` is the administrator dashboard for CWL saved player lists. It
replaces `/lazycwl` and the nine retired `/fwa lazycwl-*` commands. Those
old command names are no longer registered; use `/cwl rosters` directly.

## Dashboard flow

Open `/cwl rosters` to the FWA overview, then choose a clan. Use the
**FWA** and **Main** buttons at the top to switch sections. The selected
section stays visible in the heading. FWA uses clan type `FWA`;
Main uses `Tactical` and `Flexible Fun` war clans, plus the legacy
`Competitive` category. Dedicated `CWL` hosting clans are not treated as
home rosters. Each section has its own
clan selector and an explicit **All FWA clans** or **All Main clans** choice.
Bulk capture, close, and reminder operations are confined to that section.
Clan menus show up to 24 clans plus the bulk option per page; additional
clans remain reachable with the clan navigation buttons.

- **Overview** shows capture time, CWL season, player count, and expiry.
  FWA additionally shows players away and scheduled return reminder status.
  Main offers **Send Reminders Now** for a reviewed manual send.
- **Capture current roster** reviews the selected clan first. Bulk capture
  names only clans without a saved roster in that section.
- **Replace roster…** appears for a selected saved roster. Its review explains
  that the existing roster closes, reminders stop, and current clan members
  form the replacement. Manual roster edits are not copied. Fetching happens
  before replacing; an atomic database transaction keeps the old roster if
  the replacement cannot be saved.
- **Clear roster** or **Clear all FWA Rosters** / **Clear all Main Rosters** reviews the affected rosters, removes them from active tracking, and stops their reminders. Their records remain until the retention deadline.
- **Players** displays 20 players per page, with reviewed add/remove actions.
  Only FWA shows Away/Returned status.
- **Return reminders** is available only for FWA. It shows the configured
  destination, on/off state, frequency, and next run. Enabling, disabling,
  and sending require review; recipients are checked again before sending.
  Main has no reminder schedule or Return reminders tab. Its manual send
  reviews saved players still away, refreshes their Discord links, and posts
  to the Main CWL channel after confirmation.

Confirmation buttons apply changes immediately; there is no separate Save
step. Discord timestamps use the viewer's timezone; dropdown dates use UTC.

Panels are private, expire after 20 minutes, and belong to the opening user
and server. Every interaction rechecks Administrator permission. Confirmations
are bound to section, operation, and roster ids and consumed once. Switching
sections invalidates the previous panel and its pending confirmations. A bot
restart also expires open panels; reopen `/cwl rosters` to continue.

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
current away players from the Clash API. Main also refreshes Discord links at
review and again at send, so older Main captures can mention linked players.
If nobody is away, no Discord message is sent.

## Safe dashboard actions

Every destructive or state-changing action from a rendered list carries the
saved-list id that was displayed to the administrator. The service includes
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

# MongoDB Phase 1 — recovery preparation

Completed 2026-09-26: a fresh local logical backup was restored and verified
against the dump. Production data, indexes, routing, and service state were not
changed. This is a recovery-rehearsal result, not authorization to migrate.

## Evidence

| Check | Result |
| --- | --- |
| Source MongoDB | 8.0.32 |
| Database Tools | 100.19.0; official download SHA-256 verified |
| Local restore server | Community 8.0.32; official download SHA-256 verified |
| Backup window | 2026-09-26 21:57:43–21:57:56 UTC includes dump, restore, verification |
| Databases backed up | `settings`, `database`, `ticket_testing`, `wubot_test` |
| Restore verification | 48 collections, 9,030 documents, 145 indexes |
| Document comparison | Multisets of SHA-256 hashes of raw BSON bytes matched for every collection |
| Schema/index comparison | Every dumped collection option and validator matched; index definitions matched after ignoring namespace/background metadata |
| Backup size | 1,116,273 bytes compressed, including collection metadata |
| File integrity | Every backup file has a SHA-256 manifest; all checksums reverified |
| Scratch isolation | Fresh authenticated server bound to loopback; TTL monitor disabled only locally so expiring rows remain available for comparison |
| Cleanup | Scratch server stopped, port checked closed, temporary credential files removed, scratch database files removed |

The backup remains in the Git-ignored, owner-only directory:

`.local-backups/mongodb-20260926T215743Z/`

The workspace's physical path is
`/nvme0n1-disk/Projects/Bot - Warriors United`, also reached through
`/home/ruggie/Projects/Bot - Warriors United`.

Contents retained:
- `dump/`: compressed BSON and collection metadata for all four databases.
- `backup-manifest.json`: dump file sizes/checksums, source sizes and access checks.
- `rehearsal-report.json`: collection-by-collection restore verification.
- `downloads.json`: official binary URLs and expected SHA-256 values.
- `rehearsal.py`: exact procedure used, with no embedded credentials.
- Private dump/restore logs.

The checked-in [results summary](mongodb-phase1-results-2026-09-26.json)
contains metadata only. Backup documents and logs must remain outside Git.

## Existing backups and limits of inspection

No Mongo backup job was found in system timers, user timers, the current user's
crontab (none exists), or readable cron/systemd definitions checked. Root's
crontab could not be inspected without elevated authentication. Atlas backup
configuration and external hosts/services were not queried; no claim is made
that every possible backup location was ruled out.

This new backup is local to this machine. No off-machine copy, public media
upload, or recurring backup job was created. A private remote backup destination
and recurrence remain follow-up work. The existing public media bucket is not a
suitable default destination for database backups.

## Access and capacity

The configured database credential reports `atlasAdmin`. Its effective grants
include finding/inserting records, creating collections/indexes, listing
collections/indexes, and changing collection options for the proposed
`warriors_united` database. That destination did not exist at inspection.
No production write probe was needed or performed. Before running the migration
with a different credential, repeat the access check for that identity.

| Capacity measure | Bytes |
| --- | ---: |
| Current application data plus indexes | 14,543,841 |
| Estimated additional full copy of production | 13,642,661 |
| Estimated total while keeping the source | 28,186,502 |
| Published Free-tier comparison limit | 500,000,000 |

The estimate uses `dbStats.dataSize + indexSize` across visible application
databases. It is about 5.6% of the published 0.5 GB Free-tier limit with a full
production copy retained. Actual Atlas subscription/quota was not queried;
this is a planning estimate, not a storage reservation. Index rebuild size and
ongoing writes can change the result. The local workspace filesystem reported
834 GiB available before the rehearsal.

MongoDB documents that Free-tier storage accounts for uncompressed BSON plus
indexes: [Atlas Free limits](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/).

## What this proves, and what cutover still requires

The dump is recoverable: every document byte, index definition, and collection
option in it survived restoration. Authentication accounts, Atlas networking,
project settings, and secrets are not part of this application-data backup.

The bot remained online. Without an oplog-backed consistency mechanism, writes
during a dump can produce different collection states from different moments.
Therefore this backup is not a cross-collection point-in-time snapshot.
MongoDB documents that limitation in
[mongodump](https://www.mongodb.com/docs/database-tools/mongodump/).
Free/Flex tools also restrict oplog dump/replay options; see the limits above.

Before a migration cutover:
1. Confirm all relevant writers and pause them for the final copy.
2. Take a fresh backup of the coupled feature collections and preserve metadata.
3. Verify the destination is empty or follow an explicit reconciliation plan.
4. Restore and compare IDs, document content, indexes, validators, counters,
   and migration checkpoints before routing writes to it.
5. Resume only after verification; reconcile new writes before any rollback
   once destination writes have begun.

No bot restart or production pause occurred in this phase.

## Repeat or recover

The procedure is preserved in the private backup directory. It obtains the
source URI at runtime from the environment or ignored `.env`, uses temporary
owner-only tool configuration files, and deletes those files after use.
It creates a unique new backup directory on each run.

The binaries used are currently under `/tmp/wu-mongo-phase1-tools/`; they are
not globally installed and may disappear after a reboot. Re-download the
official packages listed in `downloads.json` and verify their hashes before
repeating the procedure. The exact Ubuntu 24.04 binaries executed successfully
on this Ubuntu 26.04 host; that observation is not a claim of vendor platform
support.

For a manual recovery rehearsal, use those tools to restore `dump/` with
`--gzip --stopOnError` into a new authenticated local server, never the
production connection. Disable its TTL monitor during verification. Preserve
the BSON files and metadata together, compare every collection, then shut down
the scratch server. The saved procedure performs these steps automatically and
always supplies a locally generated URI to `mongorestore`.

Backup/restore commands and metadata behavior:
[mongodump](https://www.mongodb.com/docs/database-tools/mongodump/) and
[mongorestore](https://www.mongodb.com/docs/database-tools/mongorestore/).

Next phase: prepare database routing and the clan tag/index audit. The missing
clan-tag index identified earlier was deliberately not changed during recovery
preparation.

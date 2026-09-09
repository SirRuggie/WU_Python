# Database options for the bot (September 2026)

Question from the owner: is MongoDB still the right store, or is something
better, given the move to Cloudflare R2 for images? Constraints: free or a
few dollars a month; the bot runs on Ruggie's Zone (home Linux box); the
owner already pays Cloudflare for a domain; a full data-layer rewrite was
acceptable if clearly worth it.

Four researchers checked vendor pages in September 2026; a scout inventoried
the code. Facts below carry their source; anything marked UNVERIFIED was not
confirmed on a vendor page.

## What the bot actually needs from a database

From `utils/mongo.py` and the extensions (main plus the ticket branch):

- 24 collections on main, 33 with thread tickets; total data well under the
  Atlas M0 cap of 512 MB.
- Async `pymongo` (`AsyncMongoClient`). No aggregation pipelines, no change
  streams, no transactions.
- Constructs that matter: atomic compare-and-swap via `find_one_and_update`
  on a revision field (15 sites), `update_one(upsert=True)` (55),
  `$addToSet`/`$push`/`$pull` on arrays, 34 index definitions of which 11 are
  TTL indexes and several are unique or partial (`partialFilterExpression`),
  and on the ticket branch unique multikey indexes (no two active flags may
  share any tag in an array).
- 176 `update_one` call sites in total. Every command touches Mongo directly;
  there is no repository layer to swap.
- No backup script exists anywhere in the repo.

## Verdict

Keep MongoDB. Its document model is a near-exact fit for the four constructs
above; every alternative either lacks one of them natively (TTL, unique across
an array) or forces a rewrite of roughly 50k lines for no functional gain.
The one real weakness is that Atlas M0 has no backups. Fix that; do not
migrate.

## Recommended actions

1. **Nightly backup to R2 (do this week, free).** On Ruggie's Zone, a cron
   job runs `mongodump --uri=... --archive --gzip` and uploads the archive to
   an R2 bucket with `rclone` (R2 is S3-compatible; region `auto`). Keep 30
   daily copies. Test one `mongorestore` into a scratch database so the
   restore path is known to work. Atlas documents that M0 cannot enable
   backups and that `mongodump`/`mongorestore` is the supported route
   (mongodb.com/docs/atlas/reference/free-shared-limitations).
2. **Optional: run MongoDB Community Edition on Ruggie's Zone** instead of
   Atlas. Same driver, same code, no vendor free-tier dependency, and the
   backup job from step 1 covers it. SSPL does not affect a private bot
   (mongodb.com/legal/licensing/server-side-public-license/faq). Downside: you
   patch and monitor it yourself, and the box is a single point of failure
   for both bot and data (the R2 backups are the recovery path).
3. **Stay on Atlas M0 otherwise.** An always-on bot never triggers the
   30-day zero-connection pause. Watch the 512 MB cap. If it is ever exceeded,
   Atlas Flex is $8 to $30 a month.

## Options considered and rejected

| Option | Why not |
|---|---|
| Cloudflare D1 (SQLite) | Free limits are ample (5 GB, 5M reads/day, 100k writes/day), but a Python process at home reaches it only through the account REST API (documented as "administrative use") or a Worker you write and run in front of it. Every query becomes an HTTP round trip. No interactive transactions, only batches. Needs the full SQL rewrite. Cloudflare docs, April 2026. |
| Cloudflare Durable Objects / KV | Workers-only; KV has no compare-and-swap or uniqueness. Same rewrite plus a Worker. |
| Neon (Postgres) free | Compute suspends after 5 minutes idle and the free plan includes about 400 compute hours a month; an always-on bot needs 730. Poor fit by design. |
| Supabase (Postgres) free | 500 MB, no backups on free, pauses after 7 idle days (harmless for a bot), plus the rewrite. No better than M0. |
| Turso (libSQL) | Best of the SQL free tiers (5 GB, no suspend found, $4.99 first paid step) but SQLite semantics: TTL and array uniqueness become application code. Python client is beta. Rewrite required. |
| SQLite + Litestream to R2 | Cleanest self-hosted backup story (Litestream 0.5.x auto-configures R2). Still the rewrite, and single-writer locking under an async bot. Worth it only if you were starting from scratch. |
| Postgres + pgBackRest to R2 | Most capable long term, heaviest to run for a sub-1 GB workload, and unique-across-array needs a child table. Rewrite required. |
| FerretDB (Mongo API on Postgres) | Keeps the driver, Apache 2.0, but change streams are unsupported and unique-plus-partial-plus-multikey together is UNVERIFIED. It solves a problem the bot does not have. |
| Microsoft DocumentDB extension | Engine under FerretDB; not a drop-in for pymongo on its own. |

## Free-tier churn

PlanetScale removed its free tier in 2024 and CockroachDB retired free
self-hosted Core the same year. Treat any free tier as revocable. The nightly
R2 backup is what makes a forced move survivable; with a current dump, moving
Mongo between Atlas, a local Community server, or FerretDB is a restore, not
a rewrite.

## Related

- docs/handoff-r2-migration.md (R2 setup and credentials handling)
- docs/handoff-ticket-console-review.md (the ticket branch that adds the
  unique multikey indexes)

# MongoDB refactor: standing reference

Bot runs on Ruggie's Zone (home Linux box) against MongoDB Atlas M0 (512 MB,
no continuous backups). Driver is pymongo's `AsyncMongoClient`. The
thread-ticket system on branch `feature/ticket-console` is being built to
the house standard first (`extensions/commands/tickets/store.py`,
`schema.py`); the rest of the bot is refactored gradually afterward. The
legacy channel-ticket system on `main` must not be touched beyond the two
narrow bug fixes named in section 4. The decision to keep MongoDB (vs.
alternatives) is recorded in `docs/database-options-2026.md` and is not
repeated here.

## 1. How to use this file

Consult section 2 before writing any Mongo code — it's the review checklist.
Section 3 is the ticket branch's punch list; clear it before merging.
Section 4 is `main` bugs, fix opportunistically. Section 5 is the gradual
backlog — pull one module at a time, never batch it into one PR. Section 6
is unstarted. Findings are attributed exactly as the source audits wrote
them (`connection-lifecycle.md`, `schema-modelling.md`, `queries-indexes.md`,
`write-patterns.md`, `references.md`); nothing here is invented.

## 2. House rules

1. **Build one client with explicit `timeoutMS`, `maxPoolSize`, `appName`; never accept driver defaults on a home box.** `main.py:80` currently passes none. — [mongo_client (async) API](https://pymongo.readthedocs.io/en/stable/api/pymongo/asynchronous/mongo_client.html)
2. **Fail fast and loudly on missing connection config at import**, the way `main.py:29` already does for the interpreter.
3. **Store and read UTC-aware datetimes; construct the client with `tz_aware=True`. Never store timestamps as ISO strings.** — [Datetimes and Timezones](https://pymongo.readthedocs.io/en/stable/examples/datetimes.html)
4. **Every index is created at startup, named, idempotent, and guarded by a process flag with a timed retry — never inside an admin command, never fatal.** Good: `utils/clan_history.py:75-110`, `utils/todo_sessions.py:53-88`.
5. **One `schema.py` per subject owns `SCHEMA_VERSION`, the constructor, and `normalize_*`; normalise on read as well as on write.** Good: `extensions/commands/tickets/schema.py:17,42,52,81,186` (branch).
6. **Shared canonical primitives for the three identities**: snowflake → int, tag → one form, datetime → tz-aware UTC BSON date.
7. **`_id` is the natural key — never an ObjectId sitting beside an unindexed logical key**, and no singleton config document sharing a collection with data rows.
8. **Every `$push` on a growing array carries `$slice` at the push site**; unbounded per-action history belongs in its own collection. Good: `schema.py:342`, `store.py:788` (answers capped at 50).
9. **Any upsert whose filter is not `_id` needs a unique index on exactly that filter, created individually, with `DuplicateKeyError` handled as a lost race.** Good: `utils/todo_sessions.py:192`. — [Unique Indexes](https://www.mongodb.com/docs/manual/core/index-unique/)
10. **Never `$set` a value computed from a prior `find_one`; put the old value in the filter and let `find_one_and_update` arbitrate, returning a three-way WON/LOST/MISSING outcome.** Good: `extensions/commands/tickets/store.py:207` (`transition`/`claim`/`release`); `extensions/commands/cards.py:2468,10090,17546` (`inventory_revision` CAS). — [findAndModify](https://www.mongodb.com/docs/manual/reference/command/findAndModify/)
11. **TTL fields must be a genuine BSON Date and cannot be built on `_id`; a collection that never deletes needs a TTL anchor or an index on its sweeper's predicate.** — [TTL Indexes](https://www.mongodb.com/docs/manual/core/index-ttl/)
12. **Compound indexes follow ESR (Equality, Sort, Range); a partial index only helps a query that repeats its whole `partialFilterExpression`; every per-interaction `find()` carries a projection and an explicit limit, never `to_list(length=None)`.** — [ESR Guideline](https://www.mongodb.com/docs/manual/tutorial/equality-sort-range-guideline/), [Partial Indexes](https://docs.mongodb.com/manual/core/index-partial/)
13. **Durable write first, Discord/external side effect second, compensate on failure; every user-visible Mongo await is deferred first and answered by one global error hook on outage (none exists today).** Good: `extensions/commands/tickets/handlers.py:98,157,210`.
14. **Every collection is declared in `utils/mongo.py` with an owner, its TTL field (or "permanent"), and its `_id` scheme — no `mongo.database.X`, no ad hoc `get_database()`.**
15. **Watch growth against the 512 MB M0 cap; an unbounded collection with no TTL and no purge is a standing risk, not a someday problem.**

## 3. Fix now on the ticket branch (`feature/ticket-console`)

Index note first: the two audits disagree only because they looked at different refs. On
`main`, `tickets` indexes are created solely inside the removed
`migrate-store` admin command (`extensions/commands/tickets/migrate.py:188,194`
in the `queries-indexes.md` snapshot) — never at startup. On the branch,
`tickets/store.py:829,889-963` already creates unique **partial** indexes at
startup with an `index_conflicts()` preflight, which is rule 4 done right.
That part of the branch does not need a fix; the items below do.

- [ ] **HIGH** — `store.py:606,610` (and worktree `flag_store.py:314,408,453`, `account_sync.py:202,275`) push `audit`/`account_identity_audit` with no `$slice`, in the one collection that may never carry a TTL. Fix: `$slice: -200` (rule 8).
- [ ] **MEDIUM** — `store.py:186-209`: `location.id`/`channel_id`, `staff_space_id`/`thread_id`, `player_tags[0]`/`player_tag`, `location.guild_id`/`guild_id` are each stored twice; `transition()` (`:509`) guards them but `store.update_one` (`:346`) is an unguarded passthrough that can set only one half. Fix: route all writes through `transition()`/dedicated setters (rule 5).
- [ ] **MEDIUM** — reads are not normalised (`:110-219` return raw docs): `schema_version` is written but never enforced on read, so consumers still special-case `_mixed_id` (`:120`). Fix: normalise in the read path too (rule 5).
- [ ] **MEDIUM** — `extensions/commands/tickets/thread_service.py:478-489` + `store.py:878,894`: `_creation_index_ready` is set only on success, and `ensure_indexes` first runs `find(RUNTIME_FILTER).to_list(length=None)` over every ticket; one conflicting document makes each ticket creation re-scan the whole collection plus 13 `create_index` round trips inside a live interaction. Fix: cache the failure with a retry window like `clan_history.py:75` (rules 4, 12).
- [ ] **LOW** — `ticket_runtime.py:1927` `insert_thread_ticket` bypasses normalisation and is called only from `tests/test_ticket_runtime.py:1134`. Fix: route through `schema.py` construction or delete if genuinely dead (rule 5).
- [ ] **LOW** — `store.py:196`: the case-insensitive `$regex` username fallback cannot use `thread_v2_username_created` (no collation-backed index). Fix: add a collation index or drop the fallback (rule 12).
- [ ] **LOW** — `ticket_open_slots` uses `schema_version: 1` (`ticket_runtime.py:777`) while `tickets` uses 3; the convention is undocumented. Fix: document per-collection schema versions in `utils/mongo.py` (rule 14).

## 4. Fix now on main (bugs, not refactors)

- [ ] **HIGH** — CWL reminders write to a stray database literally named `database`. `utils/mongo.py:39-40` declares `settings.cwl_pending_reminders`, but every write goes through `mongo_client.database.cwl_reminder` (pymongo's `__getattr__` resolves `.database` to a second, undeclared DB named `database`). Sites: `extensions/tasks/cwl_reminder.py:285,362,404,424,537,726,886,1181`. Fix: route through the declared attribute, delete the unused `settings.cwl_pending_reminders`. Test: `mongo.settings.cwl_pending_reminders.find_one({...})` returns a freshly written reminder; `mongo.database` is never touched (grep confirms).
- [ ] **HIGH** — `clans` (`settings.clan_data`) has no unique index on `tag`. `extensions/commands/clan/dashboard/update_clan_info.py:225` inserts with an ObjectId `_id`, no dedupe; reads/writes at lines 300/442/589/681/702/919/993/1268/1539 then pick one of possibly several docs at random. Fix: `update_one({"tag":tag},{"$setOnInsert":doc},upsert=True)` plus a unique index on `tag` (rules 7, 9). Test: add the same tag twice, assert `clan_data.count_documents({"tag": tag}) == 1`.
- [ ] **HIGH** — swallowed index creation in `cards.py`. All fourteen `create_index` calls at `:11071-11131` run inside one `try`/`except Exception`; if `uniq_open_card_proposal` (`:11098`) fails to build, the rest — including the lease TTL — are silently never created. Fix: one try per index, log-and-continue, assert presence on startup (rule 4). Test: make one call raise, assert the remaining thirteen still fire.
- [ ] **MEDIUM** — poll sync can lose a vote. `extensions/commands/poll.py:474` → `utils/poll_store.py:308` `mark_message_synced` clears `message_sync_pending` unconditionally after rendering; a vote landing between `edit_message` and this write gets its `pending=True` wiped, leaving the tally permanently stale. Fix: add `"updated_at": document["updated_at"]` to the filter (rule 10). Test: call `record_vote` between render and sync, assert `message_sync_pending` stays `True`.
- [ ] **HIGH** — `main.py:80` `MONGODB_URI` unset silently falls back to `localhost:27017`; the bot boots "fine" and every query fails only after the 30s selection timeout. Fix: raise at import if empty, mirroring `main.py:29` (rule 2). Test: unset the var, assert import raises.

### Found but skipped on purpose: legacy ticket system

The owner decided on 2026-09-08 that the channel-per-ticket system
(`extensions/commands/tickets/` on main, `tickets_legacy/` on the branch, and
`extensions/events/channel/ticket_channel_monitor.py`) gets no fixes, indexes,
or refactors. It is removed outright once the thread ticket system is live.
Findings that belong to it are recorded here so nobody re-discovers them:

- **HIGH (skipped)** — unindexed per-interaction `button_store` lookup.
  `extensions/commands/tickets/claim.py:35` and `close.py:86` call
  `store.find_one(mongo, {"type":"ticket","channel_id":X})` against
  `button_store`, whose only index is a goblin-scoped partial index this query
  cannot use, so every claim/close is a collection scan. The fix would have
  been a `(type, channel_id)` index named `ticket_channel`. Not done: the
  lookup disappears with legacy, and `button_store` stops holding tickets.
- **MEDIUM (skipped)** — main's ticket dual-write mirrors each legacy ticket
  into `tickets` best-effort, so the mirror drifts (see section 5 schema
  notes). Not done for the same reason; the thread system owns `tickets`
  going forward and normalises legacy-shaped rows on read.

## 5. Gradual refactor backlog by module

**cards** (`extensions/commands/cards.py`)
- [ ] `:4673-4680` four unbounded `count_documents` over `{guild_id, kind:"trade"}` — cache the panel or maintain a counter doc (rule 15).
- [ ] `idx_card_inventories_guild_confirmed` reachable only via `:3865`; `:4692` sorts `created_at` not `confirmed_at` — sort uncovered, drop or re-scope (rule 12).
- [ ] `cards_deadlines.py:137,234,346,417` only prefix-covered by `(kind,status)` — full scan each tick; add a `checkin_sent_at` index / extend the compound (rule 12).
- [ ] `card_trades` keeps completed rows forever; TTL only on `lease_expires_at` — needs a purge or archive path (rules 11, 15).

**fwa** (`extensions/commands/fwa/`, `utils/fwa_points_parser.py`)
- [ ] `lazy_cwl.py:1144` `_id=uuid4()`, embeds full rosters, no `purge_at`; `ensure_snapshot_invariants` (`:102`) repairs duplicates/mixed case on every startup instead of the index preventing them at write time (rules 6, 11).
- [ ] `lazy_cwl.py:341,426,497,576,665,758,846,981` filter on `{"active": True}` alone, which can't use the partial index at `:145` (needs `clan_tag:{"$type":"string"}`, as `:115` already does) — COLLSCAN plus blocking sort (rule 12).
- [ ] `fwa_points_monitor.py:231,234,253` store timestamps as ISO strings (no TTL, no range index); `:485` `_id="config"` shares the collection with per-clan rows — BSON datetimes, split config into `bot_config` (rules 3, 7).
- [ ] `band_sync_ical.py:109` writes to `fwa_sync_alerts`, a collection `utils/mongo.py` never declares — declare owner/TTL (rule 14).
- [ ] `lazy_cwl.py:428` and ~30 other sites: `to_list(length=None)` on a growing collection — `find_one(sort=...)` or `.limit()` (rule 12).

**clan** (`extensions/commands/clan/dashboard/`)
- [ ] Make the clan tag the document `_id` (owner, 2026-09-08: no duplicate
  clans exist, so the natural key is safe). One-off migration: insert each
  clan with `_id = tag`, delete the ObjectId twin, then drop the interim
  unique index on `tag` and update every read/write that keys on `_id`
  (`update_clan_info.py` lines 300/442/589/681/702/919/993/1268/1539). Do it
  as its own commit when this module is refactored, not before (rule 7).
- [ ] Shape verdict (2026-09-08): one flat document per clan with bot config
  embedded is correct; keep it. Fix the hygiene below, not the shape.
- [ ] Dead fields: `status` and `th_attribute` are read
  (`clan/info_hub/helpers.py:75`, `info_hub/handlers.py:120,261,322`) but
  never written anywhere; `profile` and `thread_message_id` are insert-only
  defaults (`update_clan_info.py:236,239`) never used. Remove them or give
  them a writer (rule 5).
- [ ] `name` is copied from the Clash API at insert (`update_clan_info.py:235`)
  and never re-synced. Refresh it on the existing scheduler or on
  `/clan info` reads (rule 8).
- [ ] Every clan loaded per interaction: `clan/list.py:48`,
  `clan/dashboard/dashboard.py:36`, `info_hub/helpers.py:12,75`,
  `fwa/links.py:114,168`, `family_links.py:442-608`, four `recruit/dashboard`
  sites. Use one shared cached loader; `autocomplete.py:59-121` already has a
  300 s cache to extend (rule 12).
- [ ] `fwa_points` `config.watch_list` (`tasks/fwa_points_monitor.py:292-296`)
  duplicates tag+name from `clans`; derive it from `clans` where `type` is
  FWA (rule 8).
- [ ] Add `schema_version` and a `normalize_clan_document` on read, as
  `extensions/commands/tickets/schema.py` does (rule 5).
- [ ] `update_clan_info.py:1440` creates the Discord emoji before `clans.update_one`, and deletes the emoji before `delete_one` — either failure leaves a clan row pointing at a nonexistent emoji. Persist the mention first, delete after (rule 13).

**recruit** (`extensions/commands/recruit/`, `extensions/tasks/recruit_role_cleanup.py`)
- [ ] `questions.py:640-658` + `goblin_challenge.py:62`: `delete_many`/`insert_one` into `button_store`, no unique index, reader filter omits `user_id` — two challenges in one channel and the second recruit can never complete. Fix: `update_one({channel_id,user_id,challenge_type}, upsert=True)` + unique index on that triple, add `user_id` to the reader (rules 5, 9). Test: two challenges same channel, both readers resolve their own doc.
- [ ] `questions.py:658` also has no `_id`/TTL, hand-swept at `goblin_challenge.py:47` — move to its own `recruit_challenges` collection out of `button_store` (rules 7, 11).
- [ ] `recruit_role_cleanup.py:311` index violates ESR (`walkthrough_started_at` sorts behind the range key); `cleanup_lease_until` (`:185`) unindexed. Reorder to `[(removed,1),(terminal,1),(walkthrough_started_at,1)]` under a new name (rule 12).
- [ ] `recruit_role_cleanup_due`, an older same-name index, confirmed dead per the comment at `:313-319` — drop it (rule 15).
- [ ] `server_walkthrough.py:570` `$set`s the whole onboarding doc on upsert, clobbering `cleanup_*` fields owned by `recruit_role_cleanup.py:164,210` — split the write per owner (rule 5).

**todo / shared identity**
- [ ] Three canonical tag forms: `cards.py:326` → `#ABC`, `fwa_points_parser.py:16` → `ABC`, `clan_history.py:59` → upper-only-whatever-prefix. `commands/todo.py:1350` hand-converts on every join; a tagless caller into `_tag()` creates a duplicate row. Pick one canonical form, normalise at the write boundary (rule 6).

**polls** (`extensions/commands/poll.py`)
- [ ] `:900-910` posts the Discord message before `create_poll` inserts the document — a process death in that window leaves an orphan poll with live vote buttons and no row. Insert with `message_id: None` first, post, then `$set message_id` (rule 13).

**tasks / shared utils**
- [ ] No global error handler exists for a `ServerSelectionTimeoutError` mid-interaction — a deferred command hangs on "thinking…" forever if Mongo is down. Add one hook that edits the deferred response on failure (rule 13).
- [ ] `main.py:153` startup `fwa_data.find_one` sits outside the `try` at `:178`; if Mongo is unreachable at boot, `FWA_WAR_BASE` stays empty for the process lifetime. Wrap and retry, or abort boot (rule 2).
- [ ] `main.py:46` imports `preload_autocomplete_cache` and never calls it, so the first autocomplete keystroke every 5 minutes pays a live `clans.find()` under Discord's 3s deadline (`extensions/autocomplete.py:60`). Call it from `on_bot_start` (rule 12).
- [ ] `component_state.py:224` iterates `button_store.find({})` while writing per document — page by `_id` with `.limit()` (rule 12).
- [ ] `requirements.txt` pins nothing for pymongo and calls it "synchronous"; pin `pymongo==4.17.0`, fix the comment (rule 1).
- [ ] `main.py:80` has no `maxPoolSize` — up to 100 conns/host × 3 nodes from this process alone, and the Hetzner rollback box points at the same cluster; cap at 20 (rules 1, 15).
- [ ] Legacy channel-tickets (`main`, do not deep-refactor — being replaced by the thread-console): `store.py:72` `active_store()` re-queries `ticket_setup` per read/write (cache ~5s); `migrate.py:194`'s `channel_unique` index has no `partialFilterExpression`, so a doc missing `channel_id` raises `DuplicateKeyError` on insert; `store.py:53` `as_int()` exists because `channel_id` has been stored as both int and str — normalise on write (rules 4, 6, 9).

**Unused or redundant indexes**

| Index | Where | Status |
|---|---|---|
| `recruit_role_cleanup_due` (old 3-field, name collision) | Atlas, per comment at `recruit_role_cleanup.py:313-319` | Dead — drop |
| `tickets.status_created` | `migrate.py:194` | Unused on `main` until the store flag flips to `tickets` |
| `card_inventories.idx_card_inventories_guild_confirmed` | `cards.py:11075` | Sort it should cover (`created_at`) isn't the field it's built on |
| `fwa_sync_alerts` sorts | `band_sync_ical.py:875,893` | No supporting index, but diagnostic-command-only and TTL-bounded — acceptable |

**Growth risks vs. the 512 MB cap**

| Collection | Grows how | Bound? |
|---|---|---|
| `tickets` | 1/ticket forever + unbounded `audit` | No |
| `button_store` | legacy state + challenges + ticket mirror, no TTL | No |
| `lazy_cwl_snapshots` | 1/clan/CWL month, never purged | No |
| `card_trades` | completed rows kept; TTL only on `lease_expires_at` | No |
| `[branch] ticket_flags` | 1/identity + unbounded `audit` | No |
| `clans` | duplicates per repeat `/clan add` | No |
| `card_inventories` | 1/tag, `cards` map bounded by catalogue | Yes (slow) |
| `recruit_onboarding` | 1/(user,guild), no TTL | Yes (slow) |
| `fwa_points` | 1/watched clan, overwritten in place | Yes |
| `player_clan_*`, `clan_roster_snapshots` | `purge_at` TTL | Yes |
| `component_state`, `recruit_challenges`, `fwa_band_data`, `fwa_sync_alerts`, `discord_polls`, `todo_sessions`, `ticket_creation_state` | TTL | Yes |
| `database.*` (the stray second DB) | deleted once section 4's fix lands | Yes, off-inventory |

## 6. Backups, for a later date

No backup script exists in the repo today. Recommended pattern, per
`docs/database-options-2026.md` and `references.md`: a nightly cron job on
Ruggie's Zone runs `mongodump --uri=... --archive --gzip` and streams the
archive to a Cloudflare R2 bucket via `rclone` (R2 is S3-compatible). Keep
~30 daily copies; periodically restore one into a scratch database to prove
the path works. `mongodump --archive --gzip` to stdout/a file is an
official, confirmed flag; piping it to an S3-compatible target like R2 is a
**community pattern, not documented by MongoDB itself**. Retention length
and restore-test cadence are **project policy, not vendor guidance — no
official MongoDB page found**.

Paid alternative: Atlas Flex/Dedicated tiers add continuous cloud backup,
but only M10+ Dedicated gets it — Flex is excluded, same as Free. A
community-forum figure of roughly $0.14/GB-month of snapshots plus
retention/PITR fees is **UNVERIFIED** (a forum thread, not an official
billing page).

Self-hosted alternative: run MongoDB Community Edition on Ruggie's Zone
instead of Atlas — same driver and code, no vendor free-tier dependency,
covered by the same R2 job; downside is self-patching, and the box becomes
a single point of failure for both bot and data.

Index-build cost specific to the M0 tier (vs. the general write-path index
cost that applies at any tier) is **not found in official docs — UNVERIFIED**.

## 7. References

**pymongo async / datetimes**
- https://pymongo.readthedocs.io/en/stable/api/pymongo/asynchronous/mongo_client.html
- https://pymongo.readthedocs.io/en/stable/examples/timeouts.html
- https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/
- https://pymongo.readthedocs.io/en/stable/examples/datetimes.html

**Schema and indexes**
- https://www.mongodb.com/docs/manual/data-modeling/design-antipatterns/
- https://www.mongodb.com/docs/manual/data-modeling/design-patterns/
- https://www.mongodb.com/docs/manual/core/index-case-insensitive/
- https://www.mongodb.com/docs/manual/tutorial/equality-sort-range-guideline/
- https://docs.mongodb.com/manual/core/index-partial/
- https://www.mongodb.com/docs/manual/core/index-ttl/
- https://www.mongodb.com/docs/manual/core/index-unique/
- https://www.mongodb.com/docs/manual/core/index-sparse/
- https://www.mongodb.com/developer/products/mongodb/schema-design-anti-pattern-unnecessary-indexes/

**Atomicity and transactions**
- https://www.mongodb.com/docs/manual/core/write-operations-atomicity/
- https://www.mongodb.com/docs/manual/reference/command/findAndModify/
- https://www.mongodb.com/docs/manual/faq/concurrency/
- https://www.mongodb.com/docs/manual/core/transactions-production-consideration/
- https://www.mongodb.com/docs/manual/core/transactions/
- https://www.mongodb.com/docs/manual/reference/operator/update/push/
- https://www.mongodb.com/docs/manual/reference/operator/update/slice/

**Atlas M0 / backups**
- https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/
- https://www.mongodb.com/docs/atlas/backup/restore-free-tier-cluster/
- https://www.mongodb.com/community/forums/t/continuous-backup-billing-calculation/272197 (forum, unofficial)
- https://www.mongodb.com/docs/database-tools/mongodump/
- https://www.mongodb.com/docs/database-tools/mongodump/mongodump-examples/

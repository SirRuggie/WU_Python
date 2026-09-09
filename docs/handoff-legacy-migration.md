# Handoff: bulk legacy ticket migration (written 2026-09-09, evening)

Read this first if you are picking up the ticket work cold (Codex, a new
Claude session, or a human). Everything here was verified on the day.

## Where things stand

- Branch `feature/ticket-console` is the new thread ticket system. Tip at the
  time of writing: `42da9f6` plus one uncommitted builder run for the bulk
  driver (see below). It is deployed on Ruggie's Zone (this machine) as the
  `botrunner` user: `/home/botrunner/wu-bot`, service `wu-bot.service`.
  Deploy = `sudo -n -u botrunner git -C /home/botrunner/wu-bot pull --ff-only`
  then `sudo -n systemctl restart wu-bot.service`.
- Tests: `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_card_board.py --ignore=tests/test_card_scan.py`
  from the branch checkout. Last green: 1813 passed, 2 skipped.
- The full smoke-test history and every owner rule is in
  `docs/handoff-ticket-console-review.md` (on `main`, "Overnight run" and
  "Live smoke test" paragraphs) and `docs/ticket-console-operations.md`.
- Legacy (channel-per-ticket) code on the branch equals `main` verbatim except
  one guard in `tickets_legacy/migrate.py`. Never edit legacy.

## The migration job

Copy every legacy ticket, read-only, into the new system as thread tickets.
Legacy channels are never modified, renamed, archived, or deleted.

Servers, in migration order (bot is in all four):

| # | Guild id | Era | Ticket channels | Notes |
|---|---|---|---|---|
| 1 | 1024958361306927124 | 2022-23, Ticket Tool + a deleted bot | ~160 | names have NO numbers: `main-<name>`, `fwa-<name>`, `mainclan-…`, `closed-0005`; categories "Main Clan Tickets", "FWA Tickets", "… Archived", "Mainclan Tickets 2" |
| 2 | 1115678309389434901 | WU Bot, old format | 309 | 71 with no ✅/❌ prefix (abandoned) |
| 3 | 1194706934926946457 | WU Bot | 457 | 154 have `button_store` rows; 56 open; 31 no prefix |
| 4 | 1078723854303756298 | live legacy | 100 | all have rows; 24 open |

Target: guild 644963518025826315, candidate parent 1547242779711766528
(`apply-here`), staff parent 1547243827436191774 (`recruiter-hq`), console
channel 1547244294757425212 (`recruiter-desk`).

## Owner rules (final)

1. No outcome found (no ✅/❌ prefix, no decision message) → import with
   status **closed** labelled "Closed, no decision recorded".
2. Open tickets in server 3 → import as closed, no decision (same as 1).
3. Server 4: import approved and denied exactly as they are. Open tickets in
   server 4 stay in legacy until decided; do not import them.
4. Skip any ticket whose applicant is the owner (username `sirruggie`, user id
   505227988229554179) in servers 3 and 4: those are test tickets.
5. Abandoned tickets (applicant never wrote) → not yet decided by the owner;
   default to skipping them and report the count in the dry run.
6. Imported tickets take fresh numbers in import order (oldest channel first),
   Main and FWA each from 1. Run `tools/reset_thread_ticket_test_data.py`
   (dry run, then `--confirm`) BEFORE the first real import to wipe the
   smoke-test tickets and reset the counters. Original legacy numbers are
   kept only as a note in the record.
7. Numbering, statuses and everything else must never read or write
   legacy-owned Mongo fields (`button_store`, `ticket_setup.config.*_ticket_counter`).

## How a channel is read (rules that work across all four eras)

- Ticket detection: GUILD_TEXT channel in a category whose name contains
  "ticket", "main clan", "mainclan" or "fwa", or whose name starts with
  `main`, `fwa`, `mainclan`, `closed` after stripping emoji and dashes.
  Exclude names containing "log".
- Type: name prefix (`main`/`mainclan` → main, `fwa` → fwa), else category.
- Applicant: channel permission overwrites (legacy adds the user), else the
  first user mention in the channel's first message (posted by "WU Bot",
  "Ticket Tool" or a now-"Deleted User" bot: `<@id> Welcome! …`). Resolve
  the username with REST `fetch_user`; on 404 use the channel-name suffix.
- Outcome: ✅ → approved, ❌ → denied; else an approval embed in history
  ("Welcome to the Family!", "Congratulations on being accepted"); else a
  denial embed ("regret to inform", "Denied"); else closed/no decision.
- Dates: created = channel snowflake; decided = decision message time.
- Tags: `#[0289PYLQGRJCVUO]{3,9}` in the applicant's messages.

## What exists in code

- `extensions/commands/tickets/legacy_migration.py`: per-ticket engine.
  `preview_legacy_ticket(request)` (read-only) then
  `migrate_legacy_ticket(preview)`; checkpointed in `ticket_migrations`
  (unique `legacy_source_unique` on source guild+channel); resumable via
  `recover_pending_legacy_migrations`. It refuses open tickets and refuses
  when no applicant id is found; it has a 5-ticket cap while the rollout
  phase is `pilot`.
- `/tickets migrate-legacy`: one channel per command. Unusable for 900+
  tickets; kept for one-offs.
- Bulk driver: a builder was writing `extensions/commands/tickets/legacy_bulk.py`
  with `/tickets migrate-all source-guild category attachments limit confirm`
  (dry run → plan doc in `ticket_migration_batches`; confirm → resumable
  sequential run with a progress message in the console channel, 10
  consecutive failures pause it, admin bulk runs bypass the pilot cap with a
  log line). Check `git status` on the branch checkout for its state; run the
  suite; if it is unfinished, finish it to that spec, then apply the
  follow-up below.

## Follow-up still to do (in order)

1. Bulk driver follow-up: detection by category+prefix (server 1 names have
   no numbers), applicant fallback from the first message's mention, outcome
   inference from embeds, "closed, no decision" status, skip-owner rule, skip
   abandoned by default, and a "Closed" entry in the Browse status filter.
2. Refuter pass on the driver, commit, push, deploy.
3. Reset numbering (`tools/reset_thread_ticket_test_data.py --confirm`).
4. Dry run server 1, fix what it flags, run; then 2, 3, 4.
5. After all four: legacy removal a few weeks after go-live; nightly Mongo
   backup to R2 (see `docs/database-options-2026.md`).

## Agent usage

Owner asked for cheap agents from here on: sonnet for building and for
review passes, haiku for searches. See `docs/working-with-claude-code.md`
and `.claude/rules/orchestration.md`. Never use Ultracode. Commit messages
never mention AI and carry no Co-Authored-By trailer.

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
   505227988229554179) in every server: those are test tickets.
5. Abandoned tickets (applicant never wrote) → not yet decided by the owner;
   default to skipping them and report the count in the dry run.
6. Imported tickets take fresh numbers in import order (oldest channel first),
   Main and FWA each from 1. Run `tools/reset_thread_ticket_test_data.py`
   (dry run, then `--confirm`) BEFORE the first real import to wipe the
   smoke-test tickets and reset the counters. Original legacy numbers are
   kept only as a note in the record.
7. Numbering, statuses and everything else must never read or write
   legacy-owned Mongo fields (`button_store`, `ticket_setup.config.*_ticket_counter`).
8. If the APPLICANT's Discord account no longer exists (REST `fetch_user` on
   the resolved applicant id returns 404 / `NotFoundError`), skip the ticket
   -- never import it. A deleted WELCOME-POSTER account is irrelevant: those
   tickets still import when the applicant exists.
   Always verify the applicant, even with a saved username/display name or
   an admin override. If the applicant disappears after planning, the
   confirmed run reclassifies the entry as skipped, not failed.

## How a channel is read (rules that work across all four eras)

- Ticket detection: GUILD_TEXT channel in a category whose name contains
  "ticket", "main clan", "mainclan" or "fwa", or whose name starts with
  `main`, `fwa`, `mainclan`, `closed` after stripping emoji and dashes.
  Exclude only exact type-prefixed `*-log` support roles (for example,
  `main-log` or `fwa-log`); an applicant suffix such as `fwa-7-catalog`
  remains a candidate.
- Type: name prefix (`main`/`mainclan` → main, `fwa` → fwa), else category.
- Applicant: channel permission overwrites (legacy adds the user), else the
  first message (any first 20 messages, any author -- not just a bot; server
  1's welcome is often a now-deleted *user* account) that opens with a user
  mention and mentions "welcome" (`<@id> Welcome! …` / `<@id> Welcome to
  your 🛡 WARRIOR'S UNITED🛡 Entry Ticket!!`, sometimes with the
  questionnaire in an embed on the same message), else the first message of
  any kind that opens with a user mention. The applicant ID always comes from
  that raw leading mention; `user_mentions_ids` is unordered and may put a
  later mention first. Resolve the username with REST `fetch_member`, falling back to
  `fetch_user`; if both 404 the applicant's account no longer exists --
  raise `DeletedApplicant` and skip the ticket (Owner rule 8), never fall
  back to the channel name. A channel with no permission-overwrite applicant
  and no mention message at all is `not_a_ticket`, never migrated -- likewise
  only these exact observed support names: `mainclan-commands`,
  `fwa-background-check`, `mainclan-recruitment-process`, `fwa-commands`;
  or an exact type-prefixed role name such as `main-notes`, `fwa-log`,
  `main-rules`, `fwa-info`, `mainclan-general` or `fwa-chat`. This uses
  full-name matches, so applicant names such as `main-42-chatty` and
  `fwa-7-catalog` remain candidates.
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
- Bulk driver: DONE and committed as `6913fb9` on the branch (not yet
  deployed): `extensions/commands/tickets/legacy_bulk.py`,
  `/tickets migrate-all source-guild category attachments limit confirm`
  (dry run → plan doc in `ticket_migration_batches`; confirm → resumable
  sequential run with a progress message in the console channel, 10
  consecutive failures pause it, admin bulk runs bypass the pilot cap with a
  log line); applicant fallback from the welcome mention and channel name
  is in `legacy_migration.py`. Tests: `tests/test_ticket_legacy_bulk.py`.
  Suite at that commit: 1826 passed, 2 skipped.

Checkpoint log (newest first):
- 2026-09-09: migration fixes independently reviewed; full regression suite
  passed (1871 passed, 2 skipped; card-board/card-scan excluded as usual).
  Not deployed; run a fresh server-1 dry run after deployment so the saved
  plan reflects the corrected applicant and support-channel classifications.
- 2026-09-09: log review confirmed the server-1 dry run finished scanning
  451 channels (261 ready, 190 problems), then summary delivery failed:
  Discord rejected content over 2000 characters, followed by an expired
  interaction token (401 / 50027). Summary delivery now splits long text
  into bounded messages and handles expired tokens. Deleted-applicant
  checks now also cover saved identities and confirmed-run rechecks.
  These changes require deployment before another migration run.
- 2026-09-09 final migration hardening: applicant selection now parses the
  raw leading mention because hikari's parsed mention IDs are unordered;
  non-ticket support-channel filtering uses only observed full names, so
  applicant suffixes such as `main-42-chatty` remain eligible. A failed
  `ready` batch entry is retryable and keeps the batch incomplete until it
  succeeds, rather than allowing a premature `complete` state.
- 2026-09-09 later: a live server-1 dry run showed two misclassifications.
  Real tickets whose welcome was posted by a now-deleted *user* account or
  by "Ticket Tool" (not the current bot) fell through to `no_applicant`;
  fixed by accepting any author for the welcome/mention message
  (`legacy_migration._welcome_message_applicant_id` /
  `_leading_mention_id`, parsing the raw leading mention because hikari's
  `user_mentions_ids` order is not reliable). Non-ticket channels swept up by the category/prefix
  match (`mainclan-commands`, `fwa-background-check`, etc., or any channel
  with no overwrite applicant and no mention message at all) also fell
  through to `no_applicant`; added the `not_a_ticket` classification
  (`legacy_migration._looks_like_non_ticket_channel_name`,
  `legacy_migration.NotALegacyTicketChannel`) so they are counted
  separately in the dry-run summary and never migrated.
- 2026-09-09 night: first server-1 dry run spun silently (no logs, plan
  written only at the end, 15-min token risk). Fixed and DEPLOYED as
  `a8ef3fb`: bounded history (20 oldest + 20 newest) for the dry run,
  `[Tickets] migrate_all_plan_*` / `migrate_all_run_*` journal lines,
  incremental plan checkpoints, summary also posted to the console
  channel. Also `16360d5`: id options accept an autocomplete label.
  Next: owner re-runs the server-1 dry run and watches
  `journalctl -u wu-bot.service -f`.
- 2026-09-09 evening: numbering reset DONE with `--confirm` (4 smoke
  tickets, 1 creation row, 4 automation rows deleted; counters 0). Bot
  restarted. Follow-up item 3 done. Next: owner runs the server 1 dry run.
- 2026-09-09 evening: review passed with one fix (1 s pause between copied
  tickets); DEPLOYED as `5dced26` on the box. Follow-up items 1 and 2 done.
  Next: owner confirms the numbering reset (tool dry run shows what goes),
  then owner runs `/tickets migrate-all source-guild:<Server 1> confirm:false`
  in the new server and pastes the summary.
- 2026-09-09 evening: owner-rules follow-up committed `e56a35d` (detection
  by category+prefix, outcome inference, closed/no-decision status, server
  3/4 open-ticket policy, owner-test skip, abandoned skip + `include-abandoned`,
  Browse Closed filter). Suite 1846 passed / 2 skipped. Sonnet review pass
  running; NOT deployed yet. Next: review verdict, deploy, reset numbering,
  dry run server 1.
- 2026-09-09 evening: bulk driver committed `6913fb9`; follow-up item 1
  (owner rules) handed to a sonnet builder.

## Follow-up still to do (in order)

1. Bulk driver follow-up: detection by category+prefix (server 1 names have
   no numbers), applicant fallback from the first message's mention, outcome
   inference from embeds, "closed, no decision" status, skip-owner rule, skip
   abandoned by default, and a "Closed" entry in the Browse status filter.
2. ~~Refuter pass on the driver, commit, push, deploy.~~ Done, `5dced26`.
3. ~~Reset numbering.~~ Done 2026-09-09 evening.
4. Dry run server 1, fix what it flags, run; then 2, 3, 4.
5. After all four: legacy removal a few weeks after go-live; nightly Mongo
   backup to R2 (see `docs/database-options-2026.md`).

## Agent usage

Owner asked for cheap agents from here on: sonnet for building and for
review passes, haiku for searches. See `docs/working-with-claude-code.md`
and `.claude/rules/orchestration.md`. Never use Ultracode. Commit messages
never mention AI and carry no Co-Authored-By trailer.

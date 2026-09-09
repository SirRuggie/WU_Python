# Handoff: review of `feature/ticket-console`

Written 2026-09-04 from a multi-agent review of the branch at commit `9533f68`
(8 commits, 72 files, +48,725 / -3,318 against `main`). Every finding below was
reported by one reviewer and then independently re-checked by two or three
verifiers who tried to disprove it; 24 candidate findings were rejected that way
and are not listed. Full test suite on the branch: 1525 passed, 8 skipped (the
skips need `TICKET_TEST_MONGODB_URI`), 37 s.

## Verdict

Good architecture, strong tests, clean staged rollout with rollback. Not ready
to merge until the P0 items are done. After P0 and P1, fit to pilot.

## How to use this file

Work top to bottom. P0 blocks merge. P1 should land before the pilot starts.
P2 before promoting to `thread_default`. P3 is cleanup for later. Each item
names the file and line on the branch, what goes wrong, and the fix the
reviewers proposed. Line numbers drift after edits; search the function name.

## Standing constraints (owner, 2026-09-08)

- Why threads: channel-per-ticket keeps hitting Discord's 500-channel cap.
  Four servers hold legacy ticket channels: three archives and the live
  legacy server where the old panel still runs.
- Legacy keeps running exactly as it does today until the thread system is
  fully implemented. Nothing may change its behaviour, and the thread system
  must never interfere with it.
- The new thread ticket system lives forever in a fifth server,
  `644963518025826315`. Migration sources come from all four legacy servers.
- Copying old tickets into the new system is wanted, but it must only read
  legacy data. It must never write to, rename, archive, or delete anything the
  legacy system owns.
- Command naming (decided 2026-09-08): legacy keeps `/ticket` unchanged. The
  new system's group is **`/tickets`** (permanent, not `/ticket-pilot`), and it
  is registered only in guild `644963518025826315` so the legacy servers never
  see it. When legacy is retired, delete the `/ticket` group; do not rename
  `/tickets`. Update docs/ticket-console/README.md and help_catalog.py to
  match.
- Cloudinary is gone. Images are on Cloudflare R2; the bot runs on Ruggie's
  Zone. Anything on the branch that still references Cloudinary is dead code.

## Mongo house-standard pass (2026-09-08 evening): done, verified

After P0, the seven section-3 items from `docs/mongodb-refactor.md` were
applied on `feature/ticket-console` (audit arrays capped, guarded identity
writes, normalised reads, index-failure caching that ignores transient
errors, dead insert path removed, regex username fallback dropped, schema
versions documented), plus the fixes two refuter rounds demanded. Branch tip
after that pass: see the commit "treat pymongo retryable codes as transient".
Suite: 1700 passed, 8 skipped. Not pushed.

## P0 status (2026-09-08): all done, verified by refuters

Local branch `feature/ticket-console` is at `648cb3b`, eight commits ahead of
`origin` (fast-forward; nothing rewritten below the pushed tip). Not pushed.
Commits, oldest first: merge of `main`; Cloudinary images replaced with local
assets; stuck ticket no longer gates intake (with bounded delivery retry and
legacy kept out of creation state); only verified tags count as identity;
legacy thread-system hooks removed; migrate-store and extra denial checks
dropped; docs line cleanup. Full suite: 1676 passed, 8 skipped.

Deferred from the legacy work (P2): the delivery/recovery engine differences
in `tickets_legacy/` (resolution_delivery, opening-post-intent, busy-transition
in store.py) and the `ticket_channel_monitor.py` rewrite. `/ticket diagnostics`
no longer prints the `tickets` count.

## P0 — blocks merge (original items, kept for reference)

### Rule for all work: build the new system, do not work on legacy

Legacy is not being fixed, improved, or refactored. Legacy code changes only
if the new system cannot be built without it. Every item below that mentions
legacy means "revert the branch's own unrequired edits to legacy so it is the
same as `main`", not "fix legacy".

### The branch reroutes legacy clicks through new code and makes legacy setup write a binding

- Where: `extensions/commands/ticket_runtime.py:680-808`
  (`route_public_intake`), `extensions/commands/tickets_legacy/setup.py:126`,
  `tickets_legacy/perms.py:56`, and the branch's edits to
  `extensions/events/channel/ticket_channel_monitor.py`.
- What happens: every legacy `create_ticket` click now passes through the
  new router before reaching the legacy handler, so a missing, invalid, or
  mis-phased rollout document answers real legacy clicks with "This ticket
  panel has been retired" (`ticket_runtime.py:711-720`). Legacy `/ticket
  setup` writes `legacy_ticket_guild_id` on first run in whatever server it
  is run in, with no unbind.
- Scope found 2026-09-08: every file in `tickets_legacy/` has behaviour
  changes beyond the rename (guild gates on claim/config/close/manage/
  resolve, `guild_id` added to queries and state, a rollout check before
  every `create_ticket` click, `ResetCounter` and the legacy `migrate`
  command no longer registered, a new recovery/reconciler block in
  `__init__.py`), and `ticket_channel_monitor.py` grew from 8 to 33
  functions with a lease/checkpoint/recovery rewrite. About 70 branch tests
  in six files cover those changes.
- Fix now (P0): remove the interference points only. Delete the
  `route_public_intake` gate and cross-route checks from the legacy
  `create_ticket` handler; stop legacy `/ticket setup` writing
  `legacy_ticket_guild_id` or calling `configure_rollout`; remove
  `is_legacy_control_guild` and its gates; re-register `ResetCounter` and
  the legacy `migrate` command as on `main`. Drop or rewrite the tests that
  asserted the removed behaviour. The thread system claims only
  `ticket_v2_create:*` in `644963518025826315`; if it needs the legacy guild
  id, `/tickets setup` sets it itself.
- Dropped (owner, 2026-09-08): no further work on legacy at all. It will be
  removed outright once the thread system is live, so the deferred monitor
  and recovery-engine differences stay as they are.

### Migration from four legacy servers: verified OK, no code change

- Checked 2026-09-08 in `extensions/commands/tickets/legacy_migration.py`:
  the `source-guild` option lists every server the bot is in, the only guild
  check is that the chosen channel belongs to the chosen source server, and
  nothing compares against `legacy_ticket_guild_id`. Source rows and channels
  are read-only (only `button_store.find`; the one `edit_channel` call
  quarantines a destination thread). The command must be run from the new
  server by someone who is owner/Administrator of the chosen source server.
- Operational requirement: keep the bot in all four legacy servers with View
  Channel and Read Message History until copying is finished.

### Migration must stay read-only on legacy data (currently true; keep it that way)

- Where: `extensions/commands/tickets/legacy_migration.py`.
- What happens: as written, the cloner reads `button_store` (legacy tickets)
  and `tickets`, and writes only `ticket_migrations`, `ticket_setup`
  (counters), and the new thread-ticket rows. That matches the constraint.
- Fix: none now. Add a test that asserts no write ever targets
  `button_store`, so a later change cannot break the promise silently. Note
  the P2 items on migration resumability still apply.

### Rebase onto `main`; delete every Cloudinary reference on the branch

- Where: `extensions/commands/tickets/thread_service.py:1079-1111` (candidate
  welcome + questionnaire cards, every new ticket), `extensions/commands/tickets/resolve.py:53`
  (denial card), `extensions/commands/tickets_legacy/resolve.py:42`,
  `extensions/events/channel/ticket_channel_monitor.py:494,515`, plus the
  pre-R2 `CloudinaryClient` code the branch still carries from its old base.
- What happens: the branch forked before `74efd85` and before the R2 move. Its
  cards hard-code `res.cloudinary.com` URLs that no longer resolve, so Discord
  fails to post them, and (see next item) failed card delivery gates all
  intake off.
- Fix: rebase onto current `main`, then point every image in the files above
  at a local `assets/branding/` attachment or the R2 media helper. A test in
  the branch pins the Cloudinary URL; update it.

### One stuck ticket switches all v2 intake off, permanently

- Where: `extensions/commands/tickets/thread_service.py:1795`
- What happens: A recruiter (required to hold MANAGE_THREADS in the candidate parent, thread_service.py:307-311) deletes one open ticket's candidate thread. On the next restart the recovery pass fails that row forever; every applicant in the guild sees "Thread ticketing is still completing its safety checks" indefinitely, even after the ticket is denied.
- Fix: Treat delivery_pending/orphaned committed tickets as non-blocking (log + surface in rollout-status), or mark creation state complete when the ticket becomes terminal, so one stuck ticket cannot gate global intake.
- Note: The same gate fires when a card fails to deliver (for example an image URL that no longer resolves).

### Tags the applicant types in chat become their identity and can bind them to someone else's ban

- Where: `extensions/commands/tickets/account_sync.py:533`
- What happens: Applicant B writes "my friend #2P0LYQU8 referred me" in their ticket thread. #2P0LYQU8 belongs to a blacklisted player. B's next account sync sets flag_refresh_required, reconcile runs, and B's Discord ID is added to that blacklist flag. B's approval is blocked, and every future ticket B opens is blacklisted forever.
- Fix: Key flags and blacklist checks on verified linked tags (`linked_accounts.current_tags`/`linked_account_identities`), not the unverified scraped `player_tags` set.
- Note: Related location: `extensions/commands/tickets/resolve.py:1063`, where the approval blacklist gate reads the same scraped `player_tags` set. Half of this (blacklist keyed on observed tags) is documented as intentional in docs/ticket-console.md; the flag-extension half is not and there is no undo.

## P1 decisions (owner, 2026-09-09)

- All eleven P1 items go ahead, in three builder batches, each refuted
  before the next: A = Back-button emoji, vendored chart font, applicant
  text escaping, bounded FWA staff-thread read, dead-end applicant copy;
  B = applicant messages no longer bump the ticket revision, Approve
  confirmation and two-way overturn, overlapping-flag conflict surfaced;
  C = candidate re-add and "My ticket" panel button plus best-effort DM,
  deleted-thread handling, restore bot-wide REST retries.
- Approve/deny flow: Approve asks once ("Approve this applicant?"). Deny on
  an approved ticket asks "This person was approved. Deny anyway?" and one
  more confirm flips it and removes the granted role; the reverse works the
  same way. Any recruiter may overturn; every overturn is logged on the
  ticket.
- Finding the thread, either/or: the intake panel gains a "My ticket"
  button that shows the applicant their open ticket link and earlier
  tickets (ephemeral), and the bot DMs the thread link at creation as a
  best effort. Nothing depends on the DM arriving.
- Nothing may block on anyone typing, recruiter or applicant. The only
  conflict check that stays is on the Approve/Deny buttons: if the ticket
  was already approved or denied by someone else, show "Already approved
  by X" instead of acting twice. No other revision checks in the console.

## P1 — before the pilot starts

### Flag-manager Back button uses a non-emoji arrow; Discord may reject the whole flag panel

- Where: `extensions/commands/tickets/console.py:1817`
- What happens: Recruiter clicks 'Manage flags' on a detail panel -> ticket_console_manage_flags returns build_flag_manager -> dispatcher ctx.respond(edit=True) -> Discord 400 invalid emoji -> component_handler logs and replies 'Something went wrong (ref ...)'. Flag add/remove is unreachable from the console (only /ticket-pilot flag-add remains).
- Fix: Use a real emoji ("⬅️") or drop the emoji and keep the label; verify once against a live guild since fakes cannot catch this.
- Note: Tests use fakes and never serialise to Discord. Verify once against a live guild.

### Chart needs the DejaVu system font; a host without it can never post the console

- Where: `extensions/commands/tickets/console_render.py:70`
- What happens: Bot deployed to a fresh container/VM without fonts-dejavu: /ticket console passes validate_console_channel, then render raises OSError inside _publish_hub -> 4 retries -> worker loops every 60s forever; command reports 'The console could not be posted. Check the bot log'.
- Fix: Document/install fonts-dejavu in deployment (or vendor the .ttf under assets/), and fail fast with a clear ConsoleConfigurationError naming the missing font.

### Applicant messages bump the ticket revision, so Approve/Deny fails with a false 'another recruiter changed this'

- Where: `extensions/commands/tickets/store.py:769`
- What happens: Recruiter opens a ticket's detail panel (rev=3) while the applicant is still answering the questionnaire. The applicant posts one more answer (rev→4). Recruiter clicks Approve: nothing is saved and they are told another recruiter changed the ticket, which is false. Repeats for every answer.
- Fix: Do not `$inc` `rev` in append_candidate_activity; use a separate `activity_revision` counter, mirroring compare_and_swap_linked_accounts.
- Note: Also reported at `console.py:1682`.

### Approve is one click with no confirm and no undo from the console

- Where: `extensions/commands/tickets/console.py:1635`
- What happens: Recruiter picks the wrong open ticket from the hub select and clicks Approve. The applicant is congratulated, threads lock, and the reopened detail panel shows no Approve/Deny, while /deny cannot be run in the locked thread.
- Fix: Add a confirm step to Approve (modal or two-step button), and expose the overturn action on terminal tickets in the detail panel.

### A candidate who leaves the thread or the server is never re-added; the ticket stays open and blocked

- Where: `extensions/commands/tickets/thread_service.py:892`
- What happens: Applicant opens a ticket, leaves the guild, rejoins two days later and clicks the panel again. Handler replies with a <#thread> mention that renders as an unknown/inaccessible private thread; the applicant cannot see or post in it, and recruiters see a still-open ticket with no activity.
- Fix: On every resume/re-click path (and on MemberCreate for users with open tickets) call add_thread_member idempotently; optionally watch ThreadMembersUpdate to re-add or flag the ticket.
- Note: Also reported at `thread_service.py:1682`. This is the 'candidate loses their thread' case. Fix on the panel re-click path at minimum, and send the thread link by DM at creation so the candidate has a permanent pointer.

### A deleted ticket thread locks the applicant out and makes resolution effects retry every 60 s forever

- Where: `extensions/commands/tickets/thread_service.py:1692`
- What happens: Recruiter deletes a candidate thread by mistake. Applicant clicks the panel: "already open: <#deleted>" forever. Recruiter finds it in the console and denies it: status flips, but notification/archive effects fail and are retried every minute indefinitely, and the creation row still blocks intake (see finding 1).
- Fix: Handle GuildThreadDeleteEvent for known ticket threads (mark ticket needs-cleanup or auto-deny with audit); make reconcile/archive tolerate NotFoundError by marking the pair missing instead of raising.

### Two overlapping flags of the same kind raise an uncaught DuplicateKeyError and block approval forever

- Where: `extensions/commands/tickets/flag_store.py:305`
- What happens: Flag A = blacklisted on Discord ID D only; flag B = blacklisted on tag #T only. Applicant D links #T. reconcile_flag_identities tries to add #T to flag A, hits the unique index, throws. The ticket is stuck at "linked-account flag identities are still refreshing; approval is blocked" forever; the 60s reconciler retries and fails forever. Only manual DB surgery fixes it.
- Fix: Catch DuplicateKeyError here and surface it as an operator-actionable overlapping-flags conflict (as `_set_flag_unlocked:378` already does with FlagConflictError), rather than leaving a silent permanent block.
- Note: Also: extending a flag merges the applicant's whole identity set into every matching flag (contagion).

### `max_retries=0` removes Discord REST retries for the whole bot, not just tickets

- Where: `main.py:72`
- What happens: extensions/tasks/cards_deadlines.py posts a deadline reminder while Discord returns a transient 502. On main hikari backed off and retried once and the post succeeded; now InternalServerError propagates, the scheduled job aborts and that reminder is never sent. The same single 502/timeout now fails any /clan, /cards or /cwl interaction outright.
- Fix: Restore the global max_retries and make only the ambiguous ticket message POSTs non-retrying (own REST call or idempotency reconciliation), rather than disabling retries process-wide.

### Applicant text can inject headings and masked links into the recruiter's detail panel

- Where: `extensions/commands/tickets/console.py:151`
- What happens: Applicant posts in their own thread: "IGN Bob\n## ✅ Verified by staff\n[Open staff thread](https://evil.example/phish)". The recruiter's private detail panel renders a real H2 heading and a clickable link that looks like the console's own "Open staff thread" button, next to the genuine Approve control.
- Fix: Add `[`, `]`, `(`, `)` and `#` to `_clean`'s escape set (matching `_chocolate_link_label`), and neutralise line-leading `#`/`-#` by collapsing newlines or escaping them.

### Every applicant message on an FWA ticket re-reads the entire staff thread

- Where: `extensions/commands/tickets/console.py:2755`
- What happens: An applicant with an open FWA ticket posts 200 short messages in their candidate thread. Each one drives a full pagination of the staff thread (which is itself growing), consuming hundreds of REST calls and starving the bot's shared rate-limit buckets for other guilds.
- Fix: Bound `_message_history` (e.g. `.limit(100)`), and skip the marker recovery scan entirely when every expected chocolate message id is already checkpointed in `chocolate_message_ids`.

### Quarantined-slot reply gives the applicant no next step

- Where: `extensions/commands/tickets/handlers.py:252`
- What happens: An applicant whose earlier ticket left a cleanup_required slot clicks the panel button, reads the message, has no one named to ask, retries daily and never gets a ticket; no recruiter is notified.
- Fix: Name the recruiter role or channel to contact (or ping staff automatically) and include the earlier ticket link when one exists.

## P2 — before promoting to `thread_default`

### Permanent console-config failures retry forever with 4 tracebacks a minute

- Where: `extensions/commands/tickets/console.py:741`
- What happens: An admin grants a new 'Trial Recruiter' role View Channel on the console channel. Next candidate message marks the hub dirty; every attempt raises ConsoleConfigurationError('non-recruiter role ... can view'). Logs fill with ~5,760 tracebacks/day and the bot spends REST budget on the same 4 GETs until someone notices.
- Fix: Treat ConsoleConfigurationError (and font/asset errors) as non-retryable: back off exponentially to e.g. 15 min, log once per state change, and surface `refresh_error` in /ticket console output.

### Dropdown shows only the 25 newest open tickets; the longest-waiting applicants fall off with no hint

- Where: `extensions/commands/tickets/console.py:428`
- What happens: 30 open tickets after a recruiting drive: chart tile says NEW/OPEN 30, picker lists the 25 newest. The 5 oldest applicants are only reachable if a recruiter happens to /ticket find them by name; they can sit unnoticed until their 7-day thread auto-archive.
- Fix: When list_open is truncated, show the overflow in the placeholder/description (e.g. '25 of 30 shown — use Find for older') and/or order oldest-first so the longest-waiting tickets are visible.
- Note: Also reported at `console.py:431`. Consider oldest-first ordering or an overflow note.

### Migration resume wedges permanently after any write to the legacy source row

- Where: `extensions/commands/tickets/legacy_migration.py:1732`
- What happens: A denied legacy ticket has a stuck `resolution_delivery` in state `retry`. Mid-clone the 5s recovery loop touches `resolution_delivery.updated_at`. The clone aborts after copying 200 messages; the destination threads are quarantined with no `tickets` row, and every re-run and every startup recovery raises "a migration for this source already exists with different source, destination, or applicant details". Only a manual Mongo edit unblocks it.
- Fix: Fingerprint a narrow identity subset (status, ticket_type, user_id, channel_id, rev) instead of the whole document, or let a claim re-bind the fingerprint when that narrow identity is unchanged.

### Any drift in a legacy ticket's `tickets` mirror blocks migrating it, and the repair command was removed

- Where: `extensions/commands/tickets/legacy_migration.py:760`
- What happens: On main, one `update_one` mirror write to `tickets` failed and was only logged. On this branch every dry run of that ticket stops at "a conflicting divergent or thread-runtime source row exists in tickets"; the operator has no command to inspect or repair the stale mirror because `migrate-store` is no longer registered.
- Fix: Compare only the fields `_channel_mirror_identity` cares about (identity/location/status), or offer an explicit operator override that ignores a stale read mirror.

### The acknowledged attachment-loss fallback is unreachable for the errors hikari actually raises

- Where: `extensions/commands/tickets/legacy_migration.py:1509`
- What happens: Operator migrates a 2024 denied ticket whose screenshot URL now 404s, pastes the LOSS token, confirms. hikari raises NotFoundError; `_execute_clone_part` re-raises; `_cleanup_interrupted_migration` archives+locks the half-copied threads and sets state=retry. Every retry fails identically; the ticket can never be migrated.
- Fix: Catch `hikari.ClientHTTPResponseError` (covering 401/403/404/410/413/415/422) alongside the existing types, and add a test that raises `hikari.NotFoundError`.

### Identity audit array grows without bound on every retry

- Where: `extensions/commands/tickets/account_sync.py:203`
- What happens: An open ticket's applicant has no resolvable Clash link (left the guild, link service rejects them). retry_required stays true, the reconciler retries every 60s, and after roughly 45 days the ticket document passes 16MB. Every subsequent update — including the recruiter's Deny — fails with a BSON size error, and the document can no longer be closed.
- Fix: Add `{"$each": [audit], "$slice": -N}` to every account_identity_audit push, and back off the retry cadence for repeatedly failing tickets.

### `find_by_location` runs an unindexed collection scan on every guild message

- Where: `extensions/commands/tickets/store.py:131`
- What happens: A busy community guild produces 10 messages/second. Each one scans the whole tickets collection, whose documents carry unbounded audit/answers arrays (see the account_identity_audit finding), so scan cost grows with ticket history and stalls the gateway loop.
- Fix: Index channel_id and thread_id (partial on RUNTIME_FILTER), or drop those legacy-alias branches, and gate the listener on the configured candidate/staff parent channels first.

### Approval message says 'stand by for further instructions' in a thread that is then locked, with nowhere to go

- Where: `extensions/commands/tickets/resolve.py:181`
- What happens: Recruiter clicks Approve. The applicant gets one congratulation ping, the thread locks, and it vanishes from their sidebar. They cannot reply, were given no channel and no role, so they wait indefinitely or DM a random member.
- Fix: Name the next step and its location in the approval text (channel mention or "a recruiter will DM you"), and post it before archiving.

### Deny modal label differs between console and slash command

- Where: `extensions/commands/tickets/close.py:354`
- What happens: A recruiter using /ticket deny in the thread types "Chocolate shows an old FWA ban, and Steve says he ninja-leaves" expecting a staff record. The text is posted into the applicant's thread with an @mention, exposing an internal accusation and a named staff member.
- Fix: Change the label to "Reason shown to the applicant" and the placeholder to match console.py:4262-4270 so both denial entry points warn identically.

### Operator docs never mention the 7-day thread auto-archive

- Where: `docs/ticket-console-operations.md:372`
- What happens: A candidate opens an FWA ticket and goes quiet. On day 8 both threads auto-archive and drop out of every sidebar. A recruiter picks the still-open ticket from the console, clicks "Open the thread" (a jump link that by design never un-archives, console.py:301), types `/ticket-pilot approve` and Discord rejects it; the guide gives no recovery step.
- Fix: Document the 7-day archive of open tickets, state that the console Approve/Deny buttons are the reliable path, and add the un-archive step (or a keep-alive/ensure-unarchived wrapper) the proposal already prescribes.

### No test connects real ticket/flag documents to the console chart

- Where: `tests/test_ticket_console.py:2386`
- What happens: Someone renames `console_counts`'s return key from "status" to "state". `_coerce_counts` falls through both `raw.get("statuses")` and `raw.get("status")` to `{}`, the chart renders APPROVED 0 / NEW-OPEN 0 / DENIED 0 with 361 live tickets, and all 1525 tests still pass.
- Fix: Add one test that drives the real `_hub_payload` against a fake `tickets`/`ticket_flags` collection and asserts the resulting `OverviewCounts` matches the seeded documents.

### No test pins the search filter to the fields the schema writes

- Where: `extensions/commands/tickets/store.py:195`
- What happens: A schema tweak stops writing `username_search` (or `player_tags` gains a nested shape). `_search_identity` still returns a `$or` that matches nothing, every recruiter search returns "No tickets match those filters", and the suite is green because `build_search_panel` is only ever tested with hand-built result lists.
- Fix: Add tests driving `store.search` against a fake collection for each of the four query kinds plus the statuses/ticket_types filters, asserting the emitted filter and the returned documents.

## P3 — later cleanup

- `extensions/commands/tickets/account_sync.py:382` — Concurrent account syncs: the revision CAS orders writes but not fetches, so an older lookup can revert linked_accounts.current_tags and move last_success_at backward. Fix: Include the fetch timestamp in the CAS filter (e.g. require `linked_accounts.last_success_at` <= this attempt's `at`) and abandon the write when a newer successful snapshot already landed.
- `extensions/commands/tickets/store.py:643` — replace_legacy_location and its live-called resume detector are unreachable dead code; its stated search-duplication rationale is wrong. Fix: Delete it, or wire it into legacy_migration.py and cover it with tests; either way reconcile the docstring with what the migration actually does.
- `extensions/commands/tickets/account_sync.py:625` — Account recovery sweep reads unbounded and lets repeatedly-failing tickets re-occupy the head of every batch, starving the rest. Fix: Push the sort and limit into Mongo (`.sort(...).limit(amount)`), coerce a missing timestamp to datetime.min, and de-prioritize tickets that failed on the previous pass.
- `extensions/commands/tickets/handlers.py:247` — Panel re-click on an existing open ticket never re-delivers a failed opening message, despite promising automatic retry. Fix: When the slot loses to an existing open thread ticket, call _reconcile_existing_ticket (or at least reconcile_ticket_pair + add_thread_member) before replying.
- `extensions/events/channel/ticket_channel_monitor.py:1255` — One malformed open legacy row aborts the startup sweep and permanently wedges all ticket workflow recovery. Fix: Wrap the per-row identity check in try/except, skip and log the bad row (count it), and let the sweep continue.
- `extensions/commands/tickets/thread_service.py:1471` — Global _creation_lock serializes every applicant's Discord REST, uncached link/CoC lookup, and delivery work. Fix: Scope the lock per applicant (keyed by creation_id) or move post-commit work (sync, delivery, console) outside the lock.
- `extensions/commands/tickets/console.py:402` — Markdown escaping leaks literal backslashes into the hub picker's select option label and the flag-remove description. Fix: Use a plain-text sanitiser (strip control chars, cap length) for select labels/descriptions and keep `_clean` for Text Display content only.
- `extensions/commands/tickets/console.py:4090` — Filter select handlers return None after a deferred edit, blanking the search panel (recruiter-check branch only). Fix: Return the `_notice(...)` panel from those branches (as ticket_console_view does) instead of None, or register the actions with no_return=True and respond explicitly.
- `extensions/commands/tickets/console.py:612` — Each applicant message triggers a full hub redraw: 4+ permission GETs, a 330 ms Pillow render and a 133 KB PNG re-upload for a payload whose content is unchanged. Fix: Only mark the hub dirty on status/flag/open-ticket-set changes (not raw candidate activity), cache the permission audit (re-run on ChannelUpdate/RoleUpdate or every N minutes), and skip the edit when the rendered payload fingerprint is unchanged.
- `extensions/commands/tickets/console.py:568` — Hub publish crawls the console channel's entire history unbounded — on first setup as well as after the hub message 404s. Fix: Bound the scan (e.g. fetch_messages(...).limit(200) or stop at the first bot message with the hub custom_ids) and document that the console channel should be dedicated.
- `extensions/commands/tickets/console.py:1160` — Search heading hard-codes "newest 10 matches" regardless of how many results rendered. Fix: Render the actual count ("3 matches" / "showing the newest 10 matches") and use one label for the modal everywhere.
- `tests/test_ticket_channel_monitor.py:101` — Eight real-Mongo tests are gated on an undocumented TICKET_TEST_MONGODB_URI that nothing in the repo sets, so they always skip. Fix: Document the variable in docs/ and wire a Mongo service into CI, or convert the gate to xfail-on-missing so the skips are visible as an unmet obligation.
- `tests/test_ticket_pilot_rollout.py:709` — Sole RolloutRollback test covers only the failure path; its dead transition stub references an unbound `kwargs` (NameError if reached). Fix: Fix the stub to append `_kwargs`, and add a success-path test asserting the to_phase/expected_phase/expected_revision passed for a rollback from `prepared` and from `pilot`.
- `extensions/commands/tickets/console.py:4215` — ticket_console_approve has no behavioural test, but its uncovered logic is a 4-line owner gate plus two pass-throughs already backstopped elsewhere. Fix: Add a handler test asserting the owner gate, that expected_status/expected_rev are passed through unchanged, and that WON/EFFECT_FAILED trigger the hub refresh.
- `extensions/components.py:296` — requires_state=True is a silent no-op whenever preload_state=False (3 live ticket registrations, incl. console deny). Fix: Raise at registration when requires_state and not preload_state, or move the existence check out of the preload branch so the dispatcher verifies state regardless of who loads it.
- `extensions/commands/fwa/chocolate_links.py:25` — /fwa chocolate now rejects doubled-hash and internally-spaced tags that main accepted. Fix: Strip all '#' and internal whitespace in normalize_tag before applying the regex, so the new validation rejects only genuinely unsafe characters.
- `extensions/commands/tickets/setup.py:460` — Pilot panel is posted to raw ctx.channel_id with no fetch or type check, so a thread or world-readable channel is silently accepted. Fix: fetch_channel(ctx.channel_id) alongside the other two; require GUILD_TEXT in the target guild and reject threads; warn if @everyone can VIEW_CHANNEL.
- `extensions/commands/tickets_legacy/handlers.py:1464` — Legacy handler carries an unreachable 'promoted' thread-route path (dead helper plus two dead branches). Fix: Delete _create_thread_runtime_ticket, _thread_intake_is_ready and the two thread-route branches; assert route.route == ROUTE_LEGACY after the router call.
- `extensions/commands/tickets/setup.py:322` — setup.py's old_single_guild_binding tolerance is unreachable: the same configure-threads write that creates it also plants old-guild candidate parents that block setup, with no command-level repair. Fix: When old_single_guild_binding is true, treat the stale parent/role fields as unset (ignore or $unset them in the same CAS write) instead of validating against them.
- `docs/ticket-console.md:339` — ticket-console.md §7 asserts a mockup-only string as shipped console copy (§6 blockquote also diverges). Fix: Replace both quoted blocks with the strings the runtime actually emits (console.py:104-108, :2066-2068), or mark them explicitly as mockup copy that was not implemented.
- `extensions/commands/tickets/handlers.py:248` — Duplicate-ticket guard points at the other server's channel with a bare <#id> (v2 handlers.py:250; legacy 1651, 1747, 1875). Fix: Compare slot.guild_id with ctx.guild_id and, when different, say the ticket is open in the other server and link with a full https://discord.com/channels/<guild>/<channel> URL.
- `extensions/commands/tickets/legacy_migration.py:225` — Ticket-wide loss acceptance can drop unwarned live attachments, but only on a hikari 400 — the cited 404/413 paths re-raise instead. Fix: Restrict the accepted-loss manifest to `_attachment_risk_manifest` entries, and append `progress.*.losses` to the completion reply.
- `extensions/commands/tickets_legacy/perms.py:56` — is_legacy_control_guild fails open before first bind, letting any guild's admin claim the global legacy binding via /ticket setup. Fix: Return False when no binding exists and require an explicit first-run bootstrap command, or scope the fallback to the guild that already owns `main_ticket_category`/`fwa_ticket_category`.

## Candidate-experience gaps (design, not bugs)

- No DM or permanent link to the thread. The only pointer is the one-time
  ephemeral reply; re-clicking the panel shows it again but nothing says so.
  Label the panel button as the way back to an open ticket, and DM the link.
- Threads auto-archive after 7 days of silence. They stay reachable by link and
  re-open on a new post, but no doc or message tells recruiters or candidates.
- Copy for non-native speakers is mostly good (one verb per button, short
  capitalised status words, real icons). Fix the three strings named in P1/P2.

## Channel layout to create on the target server

| Channel | Visibility | Purpose |
|---|---|---|
| Candidate parent | public | intake panel + every candidate thread (Main and FWA share it) |
| Staff parent | recruiters only | every staff thread |
| Console channel | recruiters only | the console message; setup refuses it if anyone else can view |

Plus the untouched legacy panel on the old server and a pilot panel on the
target server (may live in the console channel). Readiness code enforces only
the shared candidate parent; check staff-parent sharing and console separation
by hand before pilot and before promotion (docs/ticket-console-operations.md).

## Related

- docs/ticket-console.md, docs/ticket-console-operations.md,
  docs/ticket-console/README.md (design and command reference on the branch)
- docs/handoff-r2-migration.md (the R2 work this branch must rebase over)

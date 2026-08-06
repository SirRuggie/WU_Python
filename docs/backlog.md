# Engineering backlog

Ideas and known rough edges that should survive between work sessions. Items in
this file are notes for later investigation, not authorization to implement.

Ask for an item by its ID (for example, "pick up `AUTH-001`"). Keep the ID in
the commit message when the item is completed so the fix remains traceable.

## Active priorities

### P0 — credentials and commands that can change other users' data

- **`SECRET-001` — Rotate the BAND API token and load it from the environment.**
  A live token is hard-coded in `extensions/tasks/band_monitor.py` and exists in
  Git history. Revoke/rotate it first; deleting the source text is not enough.
- **`SECRET-002` — Rotate the Kawaii API token and load it from the environment.**
  A live token is hard-coded in `extensions/commands/slap.py` and exists in Git
  history. Revoke/rotate it before removing it from source.
- **`AUTH-001` — Restrict `/recruit dashboard`.** The command is currently open
  to every member and lets the caller target another member. Several component
  paths can change that member's nickname, Town Hall roles, and clan roles or
  post onboarding messages. Add both command visibility permissions and a
  runtime recruiter/admin check shared by every mutating component.
- **`AUTH-002` — Restrict `/clan upload-images`.** It can replace Clan
  Cloudinary assets and MongoDB references. Require the clan-management role at
  invocation time.
- **`AUTH-003` — Restrict `/fwa upload-images`.** It can replace shared FWA base
  images and MongoDB references. Require the FWA-management role at invocation
  time.

### P1 — unrestricted operational commands

These are the security-sensitive commands found without a default permission or
runtime authorization guard. They are deliberately listed one by one so each
can be fixed and closed independently. A Discord default permission controls
discoverability, but every mutating component must also enforce the same role at
click time.

1. **`AUTH-004` — `/fwa lazycwl-snapshot`:** creates operational snapshots.
2. **`AUTH-005` — `/fwa lazycwl-ping`:** can ping members from active snapshots.
3. **`AUTH-006` — `/fwa lazycwl-reset`:** deactivates one or all snapshots.
4. **`AUTH-007` — `/fwa lazycwl-autopings-start`:** starts recurring pings.
5. **`AUTH-008` — `/fwa lazycwl-autopings-stop`:** stops recurring pings.
6. **`AUTH-009` — `/fwa lazycwl-remove-player`:** removes tracked players.
7. **`AUTH-010` — `/clan dashboard`:** posts a standalone persistent dashboard
   into the channel. Its mutation controls do additional checks, but invocation
   is open and can be used to spam public dashboards.
8. **`AUTH-011` — `/ticket dashboard`:** describes itself as recruiter-only but
   has no guard. The current menu is mostly a placeholder; enforce the stated
   role before functionality grows.
9. **`AUTH-012` — `/fwa lazycwl-status`:** reads snapshot/member coverage data.
10. **`AUTH-013` — `/fwa lazycwl-roster`:** reads complete snapshot rosters.
11. **`AUTH-014` — `/fwa lazycwl-autopings-status`:** reads auto-ping state.

Items `AUTH-012` through `AUTH-014` are read-only. Decide explicitly whether
family-wide visibility is intended; document that choice even if they remain
public.

### P1 — reliability and silent failure

- **`BUG-001` — Repair `/test-band-api` and `/test-war-sync`.** Both admin
  diagnostics call the nonexistent `ctx.edit_last_response`, so their response
  handling fails on multiple branches.
- **`BUG-002` — Make ticket creation transactional/idempotent.** The ticket's
  primary record and Discord channel can be created before a mirror write
  fails. The user then sees failure, and retrying can create a duplicate.

### P2 — bounded retries, interaction gaps, and deferred validation

- **`REL-003` — Bound and back off BAND calendar DM retries.** Failed DMs remain
  open and are attempted every poll for up to 30 days. Classify permanent Discord
  errors and use capped backoff with an operator-visible terminal state.
- **`REL-004` — Bound recruit role-cleanup retries.** Permanent member-fetch or
  role-removal failures currently retry hourly forever.
- **`UI-001` — Fix the clan-list missing-clan component response.** The
  `clan_select_menu` action is registered as `no_return=True` but returns error
  UI, so that error is discarded and the click appears silent.
- **`UI-002` — Fix the Cloudinary emoji component response.** The
  `emoji_from_cloudinary` action has the same `no_return=True`/returned-UI
  mismatch and can fail silently.
- **`DEAD-001` — Decide whether to restore or remove the message task manager.**
  Its module is not loaded, its Mongo accessor is commented out, it has no
  restart restoration, and two reminder component IDs have no registered
  handlers. Treat it as unavailable until intentionally rebuilt.
- **`TODO-001` — Validate `/todo` Raid Weekend data during a live weekend.** The
  non-raid paths and clan-history war discovery have automated coverage, but
  live raid data needs event-time verification.

## Completed hardening

### `REL-002` / `OBS-001` — BAND post monitor recovery and visibility

**Status:** Implemented and tested locally on 2026-08-05; deployment pending.

The BAND post monitor now resolves its BAND key and starts through the shared
startup reconciler. A temporary BAND API or network failure retries after 5,
15, 30, and 60 seconds, then every five minutes without blocking the rest of
the bot. Repeated startup events cannot create duplicate polling tasks.

Once running, the existing ten-minute polling cadence and notification and
checkpoint behavior are unchanged. A BAND `-102` invalid-key response clears
the cached key and resolves it again on the next normal poll. Poll failures log
on the first failure or a changed failure, repeat hourly during an unchanged
outage, and emit a recovery marker after the next successful poll. Shutdown
cancels and awaits both startup recovery and the poll task.

Administrators can inspect actual task, startup, key, and poll state with
`/band-monitor-status`. Search the bot journal with:

```bash
sudo journalctl -u wu-bot -o cat --since "24 hours ago" | grep -E "band_post_monitor|monitor_started|monitor_poll_failed|monitor_poll_recovered|monitor_stopped"
```

`SECRET-001` remains open intentionally: moving the current token to an
environment variable before the server is provisioned and the token is rotated
would stop a working deployment. `BUG-001` also remains separate because it
changes admin diagnostic response handling rather than monitor reliability.

### `REL-001` — Self-healing monitor startup reconciliation

**Status:** Implemented and tested locally on 2026-08-05; deployment pending.

CWL reminders, LazyCWL auto-pings, BAND calendar polling, and FWA points now
start through an idempotent background reconciler. A brief MongoDB or scheduler
failure no longer requires a process restart: setup retries after 5, 15, 30,
and 60 seconds, then every five minutes until it succeeds. Duplicate startup
events cannot create duplicate loops or schedulers, partial scheduler recovery
does not replace already-healthy LazyCWL jobs, and shutdown cancels and awaits
the reconciliation tasks. BAND calendar poller cancellation is now awaited as
part of the same lifecycle fix, completing `REL-005` as well.

Relevant status commands now show actual runtime state in addition to stored
configuration:

- `/cwl-reminder status`
- `/fwa lazycwl-autopings-status`
- `/fwasync status`
- `/fwapoints status`

Startup error details are single-line, length-bounded, and redact URL
credentials and token-like query parameters. Search the bot journal with:

```bash
sudo journalctl -u wu-bot -o cat --since "24 hours ago" | grep -E "startup_reconcile_retry|startup_reconcile_recovered|startup_reconcile_healthy"
```

### `CWL-RETRY-001` — Monthly CWL reminder delivery

**Status:** Implemented and tested locally on 2026-08-05; deployment pending.

The normal send path, monthly schedule, follow-up ownership, and first retry at
five minutes are unchanged. Failed deliveries now persist their attempt count
and original failure time, use 5/15/30/60/180-minute backoff, and stop after six
failures or 24 hours. Discord bad-request, unauthorized, forbidden, and
not-found responses stop immediately because operator action is required.
Terminal state is removed from the pending queue so a restart cannot revive it;
one bounded diagnostic per reminder number remains in the schedule document and
is shown by `/cwl-reminder status`. A later successful delivery clears it.

Search the bot journal with:

```bash
sudo journalctl -u wu-bot -o cat --since "24 hours ago" | grep -E "delivery_failed|delivery_retry_scheduled|delivery_retry_setup_failed|delivery_retry_unavailable|delivery_state_unavailable|delivery_abandoned"
```

Log markers, from least to most urgent:

- `delivery_failed` — channel ID, exception type, retryability, and bounded
  one-line detail.
- `delivery_retry_scheduled` — failure count, backoff, channels, and next time.
- `ALERT delivery_retry_setup_failed` — MongoDB or scheduler could not register
  the retry; inspect both services.
- `ALERT delivery_retry_unavailable` — MongoDB was unavailable, so no durable
  retry could be created.
- `ALERT delivery_state_unavailable` — Discord delivery succeeded while MongoDB
  was unavailable, so accounting/follow-ups could not be updated.
- `ALERT delivery_abandoned` — permanent Discord error, age limit, or failure
  cap; check channel IDs, bot channel access, and Send Messages permission.

## Recruitment questions: unreliable family-code response

**Status:** Completed on 2026-08-05 — committed as `b70d78f`, deployed, and
verified in Discord by the operator.

This is the **Keeping it in the Family** choice in
`extensions/commands/recruit/questions.py`. It asks the recruit to send one of:

- `⚔️⚔️⚔️`
- `⚔️🍻⚔️`
- `⚔️☠️⚔️`

The flow does not spawn a waiting asyncio task. Selecting the question inserts
an incomplete `type: family_codes` record into `recruit_onboarding`; the
`GuildMessageCreateEvent` listener queries that collection for every message
from the selected recruit in that channel.

Confirmed problems:

- Matching is a raw substring check against exact Unicode strings. A visually
  identical sword without variation selector U+FE0F does not match.
- Spaces between symbols do not match. Invalid attempts receive no feedback, so
  a recruit cannot tell whether the listener is running or their input was
  rejected.
- Every selection inserts a new uniquely keyed open record. It does not replace
  or close an earlier attempt for the same recruit and channel; `find_one()` can
  therefore choose an arbitrary old attempt.
- The completion update is not an atomic claim, so two near-simultaneous valid
  messages can both produce confirmations.
- Open and completed family-code records have no expiry or cleanup. The only
  index on this collection supports walkthrough role cleanup, not the listener's
  user/channel/type/completed lookup.
- The record is inserted before the prompt message is sent, leaving an orphaned
  active listener if sending the prompt fails.

Implemented design:

- The parser ignores emoji presentation selectors, zero-width formatting, and
  harmless whitespace while preserving the three-code allowlist.
- `recruit_challenges` is a dedicated TTL-backed collection. Its deterministic
  channel/recruit key replaces repeated attempts, expires abandoned challenges
  after 24 hours, and deletes completed challenges immediately. Durable
  walkthrough rows remain in `recruit_onboarding` without TTL exposure.
- Startup migrates only the newest recent open legacy attempt per
  channel/recruit, removes completed/expired duplicates, and performs no legacy
  deletion if the new TTL index cannot be installed.
- A valid response is atomically claimed before confirmation. A Discord send
  failure restores that exact claim; a successful response deletes the state so
  later messages cannot trigger again.
- Code-like invalid input receives a funny Components V2 correction that pings
  the recruit, deletes after 30 seconds (with retries and restart cleanup), and
  is atomically limited to once every two minutes. Ordinary conversation is
  ignored and a correct response bypasses the warning cooldown.
- Focused automated coverage exercises normalization, replacement, cooldown,
  completion, rollback, migration, TTL failure safety, and message cleanup.

Live smoke result: the operator confirmed the repaired flow works after
deployment. The focused automated suite had already verified the malformed-code
cooldown/deletion and normalized success paths locally.

Production record counts were not checked: the local workspace has no
`MONGODB_URI`, and deployment access was deliberately not used.

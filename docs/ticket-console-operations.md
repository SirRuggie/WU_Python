# Ticket pilot and console operations

This is the operator source of truth for the implemented thread-ticket runtime. It
supersedes rollout and operating notes in the
[console design](ticket-console.md),
[thread proposal](thread-ticketing-proposal.md), and
[legacy migration design](legacy-ticket-migration.md).

For a plain-English explanation of every registered new-system command, use
the [thread ticket command README](ticket-console/README.md).

## Current delivery status

As of 2026-08-24, the cross-server implementation is pushed on the feature
branch but is **not deployed or configured live**. Production remains on the
existing legacy runtime. Deploying the code does not switch intake by itself:
the old panel stays authoritative until setup, preparation, pilot testing, and
an explicit confirmed promotion are completed.

## Coexistence contract

- `/ticket` is the legacy channel-ticket runtime. Its authority remains
  `button_store`.
- `/ticket-pilot` is the thread-ticket v2 runtime. Its authority is `tickets`.
- Do not copy, merge, or repoint those stores. Existing legacy tickets remain
  live under `/ticket` while v2 is prepared, piloted, promoted, or rolled back.
- Legacy recruiter claim/release remains only for operating channel tickets
  during coexistence. Thread v2 has no recruiter claim, release, close, or
  reopen action; its only terminal decisions are approved and denied.
- The runtimes share one-open-ticket slots and ticket-number counters. An
  applicant cannot bypass the guard, and the two runtimes cannot allocate the
  same number, by racing the other intake path.
- Legacy recruiter-role settings remain old-server-only. The target server has
  separate Main and FWA thread-recruiter settings; neither runtime falls back to
  the other server's role IDs.
- A missing or invalid rollout configuration fails safely to legacy intake.
- Rollout changes only where a **new** ticket opens. It never converts, closes,
  or deletes an existing ticket.

The command ownership is permanent during coexistence:

| Command group | Runtime | Storage | Purpose |
|---|---|---|---|
| `/ticket` | Legacy channel tickets | `button_store` | Existing tickets and old-server intake |
| `/ticket-pilot` | V2 thread tickets | `tickets` | Target-server setup, pilot, console, decisions, flags, and migration |

Applicants create tickets from panel buttons, not slash commands. The v2 group
has exactly 22 registered commands; the command README lists every one. V2 has
no claim, release, close, reopen, or candidate-history command. Legacy
claim/release remains registered only so legacy tickets keep their
current operating behavior during coexistence.

## Required two-server layout

Keep the existing legacy intake channel and exact panel message in the old
server. Do not move, replace, or delete either during setup or pilot.

The target server uses three long-lived channels:

1. A public candidate thread parent containing the separate public-v2 panel.
2. A private recruiter-only staff thread parent. It must differ from the
   candidate parent.
3. A private recruiter console channel, separate from both parents.

Main and FWA must share the public-v2 candidate parent and the recruiter-only
staff parent. Separate Main/FWA candidate parents are invalid. Deny public access
to the staff parent and console, and grant the bot and target-server
thread-recruiter role every permission reported by command validation.

Shared staff-parent use and console separation are operational release
requirements, but current readiness code enforces only shared candidate-parent
use. Manually compare both saved staff-parent IDs and verify console separation
before pilot and again before promotion.

The rollout binds three distinct intake messages: the old-server legacy panel,
the target-server private pilot panel, and the target-server public-v2 panel.
The pilot panel may share the private console channel only when every tester is
already a recruiter, server owner, or Administrator and console privacy
validation still passes. Otherwise use a temporary restricted target-server
channel. The pilot channel is not a thread parent.

## Rollout phases

| Phase | Old-server legacy panel | Target public-v2 panel | Target private pilot panel |
|---|---|---|---|
| `legacy_only` | Legacy intake active | Disabled | Disabled |
| `prepared` | Legacy intake active | Disabled | Disabled; validation has passed |
| `pilot` | Legacy intake active | Disabled | V2 for an exact allowlisted user or role |
| `thread_default` | Retired | V2 public intake active | Retired |
| `rollback_legacy` | Legacy intake active | Disabled | Disabled; existing v2 tickets remain manageable |
| `thread_only` | Retired | V2 public intake active | Retired; legacy drain is complete |

Every route is bound to an exact guild, channel, and message. Copied, stale, and
wrong-server panels are rejected. Promotion and rollback change only which
exact panel accepts new tickets; they do not move or convert existing tickets.

## Safe rollout sequence

Run `/ticket-pilot` commands in the target guild as an Administrator. Initial
setup establishes the target-guild binding and also verifies that the operator
owns or is an Administrator in the old legacy guild.

### 1. Bind all three exact intake panels

Run setup **in the restricted target pilot-panel channel**. Select the target
public-v2 channel that will also become the shared Main/FWA candidate parent:

```text
/ticket-pilot setup legacy-panel:<old message link or guild/channel/message IDs> public-channel:<target shared candidate-parent channel> tester:<user>
```

Use `tester-role:<role>` instead of, or in addition to, `tester:<user>`. First
setup requires `legacy-panel`, `public-channel`, and at least one allowlisted
user or role. It verifies the exact old-server legacy message, posts the
public-v2 panel in `public-channel`, posts the private pilot panel in the
invocation channel, and seeds the rollout in `legacy_only`. The operator and bot
must have the required access in both servers.

Target-panel movement is prohibited during `pilot`, `thread_default`, and
`thread_only`. In `legacy_only`, `prepared`, or `rollback_legacy`, move both
target panels in this order:

1. From the private pilot/control channel, replace the target public and pilot
   messages together:

   ```text
   /ticket-pilot setup replace:true public-channel:<new shared candidate-parent channel>
   ```

2. Reconfigure both types with that exact new public channel and the shared
   recruiter-only staff parent:

   ```text
   /ticket-pilot configure-threads type:Main candidate-parent:<new shared candidate-parent channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
   /ticket-pilot configure-threads type:FWA candidate-parent:<new shared candidate-parent channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
   ```

3. Re-run `rollout-prepare` readiness before enabling pilot or promotion:

   ```text
   /ticket-pilot rollout-prepare confirm:false
   /ticket-pilot rollout-prepare confirm:true
   ```

Target intake remains disabled in these safe phases, and readiness remains
blocked while either candidate-parent setting still points at the old channel.
Replacement never rebinds the old legacy panel or modifies legacy ticket data;
`/ticket setup` in the old server owns an intentional legacy-panel replacement.

### 2. Configure and inspect the thread parents

```text
/ticket-pilot configure-threads type:Main candidate-parent:<same bound public-v2 channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
/ticket-pilot configure-threads type:FWA candidate-parent:<same bound public-v2 channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
/ticket-pilot thread-config
/ticket-pilot config
```

Both Main and FWA must use the exact `public-channel` bound by setup as their
shared candidate parent and the same recruiter-only staff parent. The staff
parent must differ from the candidate channel. These commands save target-server
thread-recruiter roles and never overwrite old-server legacy recruiter roles.

### 3. Create the private console

```text
/ticket-pilot console channel:<private recruiter channel>
```

Verify the returned message link, chart, open-ticket picker, and **Find** action.
One console channel is durably bound. Re-running the command repairs or reuses
that hub; it does not relocate it. If the saved channel is missing, the command
reports its exact channel ID. A deleted channel cannot be restored by this
command; use the approved maintenance path to repair the saved binding before
retrying. If the channel still exists but the bot cannot access it, restore the
bot's access and retry there. Do not create a second console elsewhere.

Manage the allowlist and inspect all bindings with:

```text
/ticket-pilot pilot-user action:Allow member:<user>
/ticket-pilot pilot-user action:Remove member:<user>
/ticket-pilot pilot-role action:Allow role:<role>
/ticket-pilot pilot-role action:Remove role:<role>
/ticket-pilot rollout-status
```

### 4. Prepare without changing intake

```text
/ticket-pilot rollout-prepare confirm:false
/ticket-pilot rollout-prepare confirm:true
```

The first command validates startup readiness, the non-empty allowlist, all
three exact panel bindings, both target thread-parent configurations, separate
target recruiter roles, and runtime indexes. Fix every reported problem before
confirming. The confirmed command enters `prepared`; only the old-server legacy
panel accepts new tickets.

### 5. Enable the parallel pilot

```text
/ticket-pilot rollout-pilot confirm:false
/ticket-pilot rollout-pilot confirm:true
```

In `pilot`, allowlisted testers use the restricted target-server panel for v2.
Everyone using the old-server public panel still receives a legacy channel
ticket. The target public-v2 panel remains disabled. Verify at least the
following before promotion:

- An allowlisted click creates the correct candidate and staff threads.
- A non-allowlisted or copied-panel click is rejected.
- The exact old-server public panel still creates a legacy ticket.
- The target public-v2 panel remains disabled.
- The shared open-ticket guard blocks a duplicate across the two runtimes.
- The console, search, account context, flags, Chocolate links, approve, deny,
  and terminal thread archive all work as expected.

### 6. Promote the target public-v2 panel

```text
/ticket-pilot rollout-promote confirm:false
/ticket-pilot rollout-promote confirm:true
```

Promotion requires `pilot`. The dry run repeats readiness checks. Confirmation
enters `thread_default`, disables new intake from the old legacy and private
pilot panels, and enables the exact target public-v2 panel. Existing legacy
tickets remain authoritative and must still be completed in the old server with
`/ticket`.

### 7. Roll back new intake when needed

```text
/ticket-pilot rollout-rollback confirm:true
```

Rollback disables the target public-v2 and pilot panels and re-enables the exact
old-server legacy panel for **new** tickets. From `prepared` it returns to
`legacy_only`; from a live v2 phase it enters `rollback_legacy`. It does not
change existing thread tickets, which remain manageable through the target
console and `/ticket-pilot` commands. Retry only through prepare, pilot, and
promote with the same validation gates.

### 8. Drain legacy only after promotion

Resolve all remaining legacy tickets with `/ticket`. Preserve pending rows and
Discord artifacts so startup recovery can finish them safely. Inspect the drain
at any time with:

```text
/ticket-pilot rollout-status
/ticket-pilot rollout-drain confirm:false
```

The drain reports every blocker that must clear:

1. **Open legacy tickets** — approve or deny each authoritative `button_store`
   ticket with `/ticket`.
2. **Active legacy slots** — startup reconciliation releases a slot only after
   it proves the bound authoritative ticket is terminal. Do not delete a slot
   merely because its lease expired or its authority is temporarily missing.
3. **Pending legacy creation workflows** — keep the workflow row and any Discord
   resources; restart or allow recovery to resume the same workflow instead of
   starting another ticket.
4. **Pending legacy initial deliveries** — delivery checkpoints retry durably at
   startup, including takeover of an expired processing lease. `rollout-status`
   shows the pending count and reported delivery IDs. Preserve those rows and
   fix the underlying Discord access or delivery error.
5. **Unresolved shared open-ticket conflicts** — these are quarantined slots
   where more than one authoritative ticket was open. `rollout-status` shows the
   count and reported slot IDs. Review every referenced ticket and resolve the
   duplicate authority; reconciliation binds the sole remaining open ticket or
   releases the slot only after every recorded ticket is terminal.

The displayed pending-workflow total includes pending initial deliveries; the
dedicated delivery count is that actionable subset, so do not add the two
figures together. Pending deliveries and unresolved conflicts fail closed at
startup and prevent unsafe thread intake or promotion. Keep their IDs for the
incident record, correct the underlying condition, restart recovery, and repeat
both status commands. Never force the rollout phase or delete durable state to
make a count disappear.

Only from `thread_default`, and only when open tickets, active slots, creation
workflows, initial deliveries, and conflicts are all cleared, enter the fully
drained phase:

```text
/ticket-pilot rollout-drain confirm:true
```

## After legacy is disabled: remove the `-pilot` suffix

For this project, "remove the pilot key" means remove the user-visible
`-pilot` suffix so the new command group becomes `/ticket`. It does **not** mean
deleting Mongo's `ticket_rollout.pilot` field.

`rollout-drain confirm:true` enters `thread_only`, but it does not unload the
legacy extension, delete a panel, or rename a Discord command. Perform the
rename only in a separate atomic retirement release after the drain is proven
complete:

1. Before entering `thread_only`, ship a prerequisite safety change that adds
   pending embedded legacy `resolution_delivery` work to
   `legacy_drain_status`/`rollout-drain`, rejects every legacy approve, deny,
   and override mutation after `thread_only`, and keeps the legacy resolution
   recovery worker active until that count reaches zero. The current drain does
   not yet provide this final retirement fence.
2. Deploy that prerequisite change, then run and save the clean results from:

   ```text
   /ticket-pilot rollout-status
   /ticket-pilot rollout-drain confirm:false
   /ticket-pilot rollout-drain confirm:true
   /ticket-pilot rollout-status
   ```

3. Stop and fully drain the bot process for the retirement maintenance window.
   The final proof must run while no legacy command, worker, or other bot
   process can write.
4. Confirm every legacy resolution-delivery record is `complete` or
   `cancelled`. This read-only database check must return `0`:

   ```javascript
   db.button_store.countDocuments({
     type: "ticket",
     resolution_delivery: { $exists: true },
     "resolution_delivery.state": { $nin: ["complete", "cancelled"] }
   })
   ```

   If it is nonzero, restart the prerequisite build—not the retirement build—
   let recovery finish, re-run `rollout-status` and
   `rollout-drain confirm:false`, then fully stop and repeat the final proof.
   Do not rerun confirmed drain after `thread_only`. Permit no writer between
   the zero result and retirement deployment.
5. Build one retirement release that stops loading the legacy `/ticket`
   extension and legacy channel monitor, renames the v2 group from
   `/ticket-pilot` to `/ticket`, makes `thread_only` unable to roll back to an
   unloaded legacy runtime, and updates every command reference, help entry,
   registration test, and operations example together.
6. Replace or unregister the now-obsolete cross-server `setup`, tester-access,
   and rollout controls. Preserve `migrate-legacy` and
   `approve-migration-pilot` while historical cloning is still needed. Add a
   production-safe public-panel repair command because the current setup
   command cannot replace that panel in `thread_only`.
7. Deploy once, restart/synchronize Discord commands, and verify that `/ticket`
   contains only the intended v2 commands, `/ticket-pilot` is gone, the public
   panel creates a v2 ticket, and the console still finds existing v2 tickets.
8. After verification, delete only the inactive private pilot-panel message if
   desired. Keep the target public panel, console, candidate/staff threads,
   source channels, both ticket collections, audit history, open-slot state,
   component IDs, and migration checkpoints.

Do not remove the final tester with `pilot-user`/`pilot-role`, unset
`ticket_rollout.pilot`, unset `legacy_intake`, or unset
`legacy_ticket_guild_id` before that retirement release. The current parser
requires the stored pilot structure even in `thread_only`; deleting it makes
the rollout invalid and rejects public v2 intake.

## Daily recruiter workflow

Use `/ticket` for tickets that opened in the legacy runtime. Use the private
console and `/ticket-pilot` for v2 tickets. The v2 console does not list
un-cloned `button_store` tickets. Useful v2 fallbacks are:

```text
/ticket-pilot find query:<Discord ID, #player tag, or username>
/ticket-pilot history member:<user>
/ticket-pilot approve
/ticket-pilot deny
```

### Understand account identity

- At open, the bot force-refreshes every Clash account linked to the
  applicant's Discord ID. Pending, failed, and confirmed-zero results are
  distinct states; a failed lookup never means that the applicant has no
  accounts.
- **Currently linked** is the latest successful link-service snapshot. It
  drives the current account count and automatic FWA Chocolate checklist.
- **Observed** tags are permanent identity history: applicant-disclosed tags
  plus every linked tag seen in a successful snapshot. Search, prior-ticket
  matching, and flags use that history even after an account is unlinked.
- Approve and deny force-refresh all linked accounts immediately before the
  decision.

### Review Chocolate and manage flags

Each live FWA staff thread receives staff-only Chocolate pages after its linked-
account snapshot, with one link for each currently linked account. The bot
updates those pages when the current snapshot changes. Open each link and review
the site yourself: the bot does not fetch, infer, or record a Chocolate verdict.

In ticket detail, use **Manage flags** to add, update, or remove
**Blacklisted**, **Previously denied**, or **Not loyal to WU**. Only
**Blacklisted** blocks approval. Use these recruiter-only commands only when the
ticket-detail flow is unavailable:

```text
/ticket-pilot flags identity:<Discord ID or #player tag>
/ticket-pilot flag-add kind:<flag> reason:<reason> discord-ids:<IDs> player-tags:<tags>
/ticket-pilot flag-remove flag-id:<exact ID> reason:<reason>
```

`flag-add` needs at least one Discord ID or player tag. Copy the exact flag ID
from ticket detail or `flags` before removing it.

### Approve or deny

1. Read the staff account context, matching flags, earlier-ticket links, and,
   for FWA, every current-account Chocolate link.
2. Choose **Approve** or **Deny** in private ticket detail. The final linked
   account refresh runs before the decision write.
3. Approval stays blocked when the lookup fails, zero accounts are currently
   linked, or an active blacklist matches the Discord ID or an observed tag.
4. If an FWA approval refresh finds a newly linked account, the ticket remains
   open while the Chocolate pages update. Review the new link and approve
   again. Pending checklist delivery also keeps approval blocked and retries.
5. Denial is allowed after a failed or zero-account lookup. A failed denial
   lookup is recorded and retried so staff context and Chocolate pages can
   converge later.
6. The decision commits only if the expected status, ticket revision, and
   linked-account revision still match. A stale or missing attempt does not
   notify the applicant or apply terminal thread effects. Any offered override
   is owner-bound, rechecks recruiter access, waits for the prior effects to
   complete, and re-runs current approval gates before another conditional
   write.
7. Applicant notification, staff updates, archive, and console refresh are
   durable follow-up work. **Decision recorded; updates retrying** means the
   terminal decision is safe and the remaining work will retry.

Terminal candidate and staff threads remain locked, archived, and available
read-only from the console.

## Candidate return and follow-up status

Candidate follow-up is **not implemented**. A candidate cannot currently use
the console, find their archived ticket, or post into the locked candidate
thread a month later. Staff can open its details and archived links through the
private console, `/ticket-pilot find`, or `/ticket-pilot history`.

After approval or denial releases the shared open-ticket slot, the applicant
may create a later **new** ticket and receive a new thread pair. That is repeat
intake, not reopening or continuing the archived conversation.

The researched recommendation, pending explicit product approval and a future
implementation, is a candidate-facing **My Tickets / Ask Follow-Up** action on
the target public intake panel:

1. Authenticate the click by Discord ID and show only that applicant's eligible
   tickets.
2. Let the applicant select the original ticket and submit the question in a
   private modal.
3. Durably unlock and unarchive the same candidate/staff thread pair, restore
   candidate membership, post an attributed question, and alert recruiters
   once.
4. Preserve the original `approved` or `denied` decision, track the follow-up
   lifecycle separately, and relock/rearchive the pair after inactivity.

Do not tell candidates this exists and do not substitute a new ticket for the
same-ticket follow-up until that design is approved and implemented.

## Clone terminal legacy tickets

Legacy cloning is optional and is separate from rollout. Resolve an old-server
ticket there first; only terminal approved/denied tickets are eligible. Cloning
is available only in `pilot`, `thread_default`, or `thread_only`, processes one
source ticket at a time, and never alters or deletes the source channel, source
staff thread, messages, roles, or attachments.

Run a read-only preview in the destination guild:

```text
/ticket-pilot migrate-legacy source-guild:<server> source-channel:<ticket channel> target-guild:<destination server> candidate-parent:<channel> staff-parent:<channel> type:Auto status:Auto confirm:false
```

Choose `source-staff-thread` when detection is ambiguous. Use `type:Main` or
`type:FWA`, `status:Approved` or `status:Denied`, `user-id`, `username`, or
`player-tags` only as reviewed corrections. An override cannot make a source
proven `open` or `new` eligible; a stored `closed` value needs an explicit
approved or denied outcome. If the preview reports attachment risk, copy its
exact `LOSS-...` token into `attachment-ack` on the confirmed rerun.

When the preview is correct, rerun the same selections with `confirm:true`.
The command creates or resumes the same destination thread pair, copies both
histories, records the v2 ticket, and locks and archives the pair. Check message
order, visible original timestamps, attachments or loss notes, identity,
outcome, console search, and both archived links. Confirm again that every
source object is unchanged.

Select and verify between one and five pilot migrations. Further migrations
stay locked until every selected item is complete and an Administrator runs:

```text
/ticket-pilot approve-migration-pilot confirm:true
```

Migration is resumable. Re-run the same `migrate-legacy` selections with
`confirm:true`, or allow startup recovery to resume the durable checkpoints.
Keep partial destination threads, migration rows, and bot-authored markers;
deleting them can defeat safe recovery.

## Recovery boundaries

| Operation | What it changes | Safe recovery |
|---|---|---|
| Prepare, pilot, or promote with `confirm:false` | No phase or intake-routing change; readiness may idempotently ensure shared-runtime indexes | Correct the reported issue and repeat. |
| Rollback or drain with `confirm:false` | No phase or intake-routing change; drain reads open tickets, slots, creation workflows, initial deliveries, and conflicts | Preserve reported IDs, recover every blocker, and repeat the dry run. |
| Confirmed prepare, pilot, promote, rollback, or drain | Rollout phase, revision, and history; prepare, pilot, and promote may also idempotently ensure shared-runtime indexes | Inspect `rollout-status`; existing tickets stay with their original runtime. Drain confirmation fails closed unless every legacy blocker is clear. |
| `migrate-legacy confirm:false` | Nothing; attachment URLs may be read | Correct the selections or metadata and repeat. |
| `migrate-legacy confirm:true` | Destination threads/messages, ticket-number counter, migration checkpoints/markers, v2 ticket, pilot slot/index, staff-context outbox, and console-refresh state | Keep partial artifacts and repeat the same command or allow recovery to resume. Source Discord objects remain read-only. |

For interrupted live v2 work, preserve both ticket threads, bot-authored marker
messages, and automation-state rows. Startup recovery resumes setup messages,
account snapshots, Chocolate pages, decision notices, archive convergence, and
console refresh without creating a second ticket pair. Recovery may temporarily
make a terminal thread writable to repair pending bot-owned work; it then
relocks and rearchives the thread without reopening the ticket status.

Startup also retries pending legacy initial deliveries before enabling v2
intake and reconciles shared open-ticket slots. If delivery or conflict IDs
remain in `rollout-status`, intake stays fail-closed: preserve the named rows,
repair the source condition, and let the next startup recovery pass prove that
the blocker is safe to clear.

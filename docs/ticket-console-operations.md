# Ticket pilot and console operations

This is the operator source of truth for the shipped thread-ticket runtime. It
supersedes rollout and operating notes in the
[console design](ticket-console.md),
[thread proposal](thread-ticketing-proposal.md), and
[legacy migration design](legacy-ticket-migration.md).

## Coexistence contract

- `/ticket` is the legacy channel-ticket runtime. Its authority remains
  `button_store`.
- `/ticket-pilot` is the thread-ticket v2 runtime. Its authority is `tickets`.
- Do not copy, merge, or repoint those stores. Existing legacy tickets remain
  live under `/ticket` while v2 is prepared, piloted, promoted, or rolled back.
- Legacy recruiter claim/release remains only for completing channel tickets
  during coexistence. Thread v2 has no recruiter claim, release, close, or
  reopen action; its only terminal decisions are approved and denied.
- The runtimes share one-open-ticket slots and ticket-number counters. An
  applicant cannot bypass the guard, and the two runtimes cannot allocate the
  same number, by racing the other intake path.
- A missing or invalid rollout configuration fails safely to legacy intake.
- Rollout changes only where a **new** ticket opens. It never converts, closes,
  or deletes an existing ticket.

## Recommended channel layout

The recommended long-lived layout uses three channels total:

1. The existing public intake channel, which also serves as the candidate
   thread parent. Keep its existing ticket-panel message.
2. A new private staff thread parent. It must differ from the candidate parent.
3. A new private recruiter console channel, separate from both parents.

Main and FWA may share the same candidate parent and the same staff parent;
four parents are not required. Create a separate candidate parent only when
that separation is intentionally desired; doing so raises the long-lived total
to four. Deny public access to the staff parent and console, and grant the bot
and recruiter role every permission reported by command validation.

The restricted pilot panel must be in a channel other than the public intake
channel. It is not another thread parent. It can share the private console
channel only when every tester is already a recruiter, server owner, or
Administrator and console privacy validation still passes. Otherwise use a
temporary, restricted tester channel.

## Rollout phases

| Phase | New public-panel clicks | Restricted pilot panel |
|---|---|---|
| `legacy_only` | Legacy `/ticket` runtime | Disabled |
| `prepared` | Legacy `/ticket` runtime | Disabled; validation has passed |
| `pilot` | Legacy `/ticket` runtime | V2 for an exact allowlisted user or role |
| `thread_default` | V2 `/ticket-pilot` runtime | Retired |
| `rollback_legacy` | Legacy `/ticket` runtime | Disabled; existing v2 tickets remain manageable |
| `thread_only` | V2 `/ticket-pilot` runtime | Retired; legacy drain is complete |

The pilot route is bound to one exact guild, channel, and message. A copied or
stale panel is rejected. In `thread_default` and `thread_only`, the existing
public panel routes to v2 without being reposted.

## Safe rollout sequence

Run these commands in the target guild as an Administrator. The bot owner must
establish the target-guild binding with the first `configure-threads` command.

### 1. Configure and inspect the thread parents

```text
/ticket-pilot configure-threads type:Main candidate-parent:<channel> staff-parent:<channel> recruiter-role:<role>
/ticket-pilot configure-threads type:FWA candidate-parent:<channel> staff-parent:<channel> recruiter-role:<role>
/ticket-pilot thread-config
/ticket-pilot config
```

Reusing the Main parents for FWA is valid. Each candidate/staff pair must use
different channels.

### 2. Create the private console

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

### 3. Bind the existing public panel and post the pilot panel

Run setup **in the restricted pilot-panel channel**:

```text
/ticket-pilot setup public-channel:<existing public channel> public-message-id:<existing panel message ID> tester:<user>
```

Use `tester-role:<role>` instead of, or in addition to, `tester:<user>`. First
setup requires the public channel and message ID plus at least one allowlisted
user or role. Initial setup verifies the legacy panel, posts the separate pilot
panel, and seeds the rollout in `legacy_only`.

Use `replace:true` only when the bound pilot panel was deleted or must move.
Public-panel rebinding is allowed only in a legacy-safe phase.

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

The first command validates startup readiness, the non-empty allowlist, public
and pilot bindings, both thread-parent configurations, and runtime indexes. Fix
every reported problem before confirming. The confirmed command enters
`prepared`; public intake is still legacy-only.

### 5. Enable the parallel pilot

```text
/ticket-pilot rollout-pilot confirm:false
/ticket-pilot rollout-pilot confirm:true
```

In `pilot`, allowlisted testers use the restricted panel for v2. Everyone using
the existing public panel still receives a legacy channel ticket. Verify at
least the following before promotion:

- An allowlisted click creates the correct candidate and staff threads.
- A non-allowlisted or copied-panel click is rejected.
- The existing public panel still creates a legacy ticket.
- The shared open-ticket guard blocks a duplicate across the two runtimes.
- The console, search, account context, flags, Chocolate links, approve, deny,
  and terminal thread archive all work as expected.

### 6. Promote v2 on the existing public panel

```text
/ticket-pilot rollout-promote confirm:false
/ticket-pilot rollout-promote confirm:true
```

Promotion requires `pilot`. The dry run repeats readiness checks. Confirmation
enters `thread_default`, so new clicks on the existing public panel route to v2.
Do not replace the public message. Existing legacy tickets remain active and
must still be completed with `/ticket`.

### 7. Roll back new intake when needed

```text
/ticket-pilot rollout-rollback confirm:true
```

Rollback returns **new** public intake to legacy. From `prepared` it returns to
`legacy_only`; from a live v2 phase it enters `rollback_legacy`. It does not
change existing thread tickets, which remain manageable through the v2 console
and `/ticket-pilot` commands. To retry rollout, prepare, pilot, and promote
again through the same validation gates.

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

## Clone terminal legacy tickets

Legacy cloning is optional and is separate from rollout. It is available only
in `pilot`, `thread_default`, or `thread_only`. It accepts one terminal
approved/denied source ticket at a time and never alters or deletes the source
channel, source staff thread, messages, roles, or attachments.

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

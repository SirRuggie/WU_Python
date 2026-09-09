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
- `/tickets` is the thread-ticket v2 runtime. Its authority is `tickets`.
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
| `/tickets` | V2 thread tickets | `tickets` | Target-server setup, pilot, console, decisions, flags, and migration |

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

Run `/tickets` commands in the target guild as an Administrator. Initial
setup establishes the target-guild binding and also verifies that the operator
owns or is an Administrator in the old legacy guild.

### 1. Bind all three exact intake panels

Run setup **in the restricted target pilot-panel channel**. Select the target
public-v2 channel that will also become the shared Main/FWA candidate parent:

```text
/tickets setup legacy-panel:<old message link or guild/channel/message IDs> public-channel:<target shared candidate-parent channel> tester:<user>
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
   /tickets setup replace:true public-channel:<new shared candidate-parent channel>
   ```

2. Reconfigure both types with that exact new public channel and the shared
   recruiter-only staff parent:

   ```text
   /tickets configure-threads type:Main candidate-parent:<new shared candidate-parent channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
   /tickets configure-threads type:FWA candidate-parent:<new shared candidate-parent channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
   ```

3. Re-run `rollout-prepare` readiness before enabling pilot or promotion:

   ```text
   /tickets rollout-prepare confirm:false
   /tickets rollout-prepare confirm:true
   ```

Target intake remains disabled in these safe phases, and readiness remains
blocked while either candidate-parent setting still points at the old channel.
Replacement never rebinds the old legacy panel or modifies legacy ticket data;
`/ticket setup` in the old server owns an intentional legacy-panel replacement.

### 2. Configure and inspect the thread parents

```text
/tickets configure-threads type:Main candidate-parent:<same bound public-v2 channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
/tickets configure-threads type:FWA candidate-parent:<same bound public-v2 channel> staff-parent:<same recruiter-only staff channel> recruiter-role:<role>
/tickets thread-config
/tickets config
```

Both Main and FWA must use the exact `public-channel` bound by setup as their
shared candidate parent and the same recruiter-only staff parent. The staff
parent must differ from the candidate channel. These commands save target-server
thread-recruiter roles and never overwrite old-server legacy recruiter roles.

### 3. Create the private console

```text
/tickets console channel:<private recruiter channel>
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
/tickets pilot-user action:Allow member:<user>
/tickets pilot-user action:Remove member:<user>
/tickets pilot-role action:Allow role:<role>
/tickets pilot-role action:Remove role:<role>
/tickets rollout-status
```

### 4. Prepare without changing intake

```text
/tickets rollout-prepare confirm:false
/tickets rollout-prepare confirm:true
```

The first command validates startup readiness, the non-empty allowlist, all
three exact panel bindings, both target thread-parent configurations, separate
target recruiter roles, and runtime indexes. Fix every reported problem before
confirming. The confirmed command enters `prepared`; only the old-server legacy
panel accepts new tickets.

### 5. Enable the parallel pilot

```text
/tickets rollout-pilot confirm:false
/tickets rollout-pilot confirm:true
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
  and overturn all work as expected, leaving both threads open afterward.

### 6. Promote the target public-v2 panel

```text
/tickets rollout-promote confirm:false
/tickets rollout-promote confirm:true
```

Promotion requires `pilot`. The dry run repeats readiness checks. Confirmation
enters `thread_default`, disables new intake from the old legacy and private
pilot panels, and enables the exact target public-v2 panel. Existing legacy
tickets remain authoritative and must still be completed in the old server with
`/ticket`.

### 7. Roll back new intake when needed

```text
/tickets rollout-rollback confirm:true
```

Rollback disables the target public-v2 and pilot panels and re-enables the exact
old-server legacy panel for **new** tickets. From `prepared` it returns to
`legacy_only`; from a live v2 phase it enters `rollback_legacy`. It does not
change existing thread tickets, which remain manageable through the target
console and `/tickets` commands. Retry only through prepare, pilot, and
promote with the same validation gates.

### 8. Drain legacy only after promotion

Resolve all remaining legacy tickets with `/ticket`. Preserve pending rows and
Discord artifacts so startup recovery can finish them safely. Inspect the drain
at any time with:

```text
/tickets rollout-status
/tickets rollout-drain confirm:false
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
/tickets rollout-drain confirm:true
```

## After legacy retirement

`/tickets` is permanent and is never renamed to `/ticket`. Retiring legacy
means deleting the `/ticket` command group, its panels, and its channel
monitor once `rollout-drain confirm:true` is proven clean — not renaming or
otherwise touching `/tickets`. Stop loading the legacy `/ticket` extension,
unregister its setup panels, and remove its Discord command registration in
one reviewed retirement release; `/tickets` and its data keep running
unchanged before, during, and after that release.

## Daily recruiter workflow

Use `/ticket` for tickets that opened in the legacy runtime. Use the private
console and `/tickets` for v2 tickets. The v2 console does not list
un-cloned `button_store` tickets. Useful v2 fallbacks are:

```text
/tickets find query:<Discord ID, #player tag, or username>
/tickets history member:<user>
/tickets approve
/tickets deny
```

### Understand account identity

- At open, the bot force-refreshes every Clash account linked to the
  applicant's Discord ID. Pending, failed, and confirmed-zero results are
  distinct states; a failed lookup never means that the applicant has no
  accounts.
- **Currently linked** is the latest successful link-service snapshot. It
  drives the current account count and automatic FWA Chocolate checklist.
- **Verified** tags are permanent identity history: every linked tag seen in a
  successful account snapshot, plus any tag a recruiter records through
  **Manage flags**. Prior-ticket matching and flags use only this verified
  set, even after an account is unlinked.
- **Mentioned** tags are `#TAG`-shaped text the applicant typed in their
  thread. They help search find the ticket and show on ticket detail, but
  anyone can type any tag, so they never affect flags or the blacklist gate.
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
/tickets flags identity:<Discord ID or #player tag>
/tickets flag-add kind:<flag> reason:<reason> discord-ids:<IDs> player-tags:<tags>
/tickets flag-remove flag-id:<exact ID> reason:<reason>
```

`flag-add` needs at least one Discord ID or player tag. Copy the exact flag ID
from ticket detail or `flags` before removing it.

### Approve or deny

1. Read the staff account context, matching flags, earlier-ticket links, and,
   for FWA, every current-account Chocolate link. Applicant activity in the
   thread never bumps the ticket's resolution revision, so it cannot make an
   otherwise-valid Approve/Deny look like a race with another recruiter.
2. Choose **Approve** or **Deny** in private ticket detail. Approve opens a
   one-step confirm ("Approve X for Main/FWA?"); Deny's reason modal is its
   own confirm. The final linked account refresh runs before the decision
   write. Clicking the confirm button immediately swaps it for a buttonless
   "Saving the decision..." notice (best-effort; a stale interaction never
   blocks the decision itself) so the confirm control never sits there
   looking clickable while the decision and its follow-up work run.
3. Approval stays blocked when the lookup fails, zero accounts are currently
   linked, or an active blacklist matches the Discord ID or a verified player
   tag. A tag the applicant only mentioned in chat never triggers this block.
   Overlapping active flags on the same identity are surfaced as a yellow
   notice on the detail panel, not a block — approval is gated only by the
   blacklist check.
4. If an FWA approval refresh finds a newly linked account, the ticket remains
   open while the Chocolate pages update. Review the new link and approve
   again. Pending checklist delivery also keeps approval blocked and retries.
5. Denial is allowed after a failed or zero-account lookup. A failed denial
   lookup is recorded and retried so staff context and Chocolate pages can
   converge later.
6. The only conflict check left on Approve/Deny is status: if someone else
   already decided the ticket, the console shows who and when instead of
   acting, with a button back to the refreshed detail panel. A decided
   ticket's detail panel instead offers the opposite action (Deny on an
   approved ticket, Approve on a denied one); confirming it asks "already
   approved/denied by X, do the opposite anyway?" before continuing into the
   normal approve/deny path. Any recruiter may overturn a decision, it always
   runs the full normal effects (including, for deny-after-approve, removing
   any roles the approval granted), and it is logged on the ticket as an
   overturn. Before posting its fresh decision card, an overturn also deletes
   the earlier decision card it is replacing from the candidate thread (by
   the message id checkpointed on the resolution being overturned, or, for a
   ticket resolved before that checkpoint existed, by scanning the thread for
   the newest bot-authored card and deleting that instead) — the applicant
   only ever sees the current decision. `/tickets approve`/`deny` never
   offers an overturn — on a decided ticket it just names who decided it and
   points to the console. While the previous decision's own follow-up work
   (applicant notification, staff updates, console refresh) is still
   running — a few seconds — an overturn is refused with "Nothing was
   changed. Try this override again in a moment."
7. The decision write (status, revision, audit) is the only part of
   Approve/Deny/overturn on the click path. Applicant notification, staff
   updates, and console refresh — the previous decision card's deletion on
   an overturn included — are scheduled as a background task the instant the
   decision commits and are not waited on; the click gets its result back
   immediately. That follow-up work is idempotent and reconciled on its own
   at startup, so a crash mid-task loses nothing. **Decision recorded;
   updates retrying** means the terminal decision is safe and the remaining
   work will retry. The three steps (applicant notification, staff context,
   console/hub refresh) each checkpoint independently: a staff-context
   delivery that is still pending only defers that one step and leaves
   `resolution_effects.complete` false, it never holds back the applicant's
   decision card. Each step's `resolution_effects.<step>.at` records when
   that step itself actually delivered, even across retries — the pass that
   finally clears every step only flips `complete`/`completed_at`, it does
   not re-stamp the individual steps that already succeeded on an earlier
   pass.

The bot never archives or locks a ticket thread because of a decision.
Approve, deny, and overturn all leave both the candidate and staff threads
open and writable, so recruiters and applicants can keep talking in a
decided ticket. If Discord had already auto-archived a thread (see below),
delivering the decision notice or an overturn's fresh card briefly
unarchives it to post, then leaves it open rather than re-archiving it.

## Candidate return and follow-up status

A self-service **My Tickets / Ask Follow-Up** action is **not implemented**.
A candidate cannot currently use the console or search for their own past
tickets. Staff can open ticket details and thread links through the private
console, `/tickets find`, or `/tickets history`.

The bot never archives or locks a ticket thread because of a decision, so a
decided ticket's thread pair behaves like any other: Discord auto-archives it
after seven days of silence, but it is never locked, so the applicant's next
message (or a recruiter's) re-opens it on its own, and the thread stays
reachable by its link the whole time. A panel re-click or the **My ticket**
button on a still-**open** ticket also proactively restores full candidate
access on demand. Once a ticket is approved or denied, **My ticket** hands
back a jump link into the (never-locked) thread pair; posting in it is what
un-archives it if Discord had already auto-archived it. This is not the same
as the not-implemented follow-up flow below, which would proactively restore
access and alert recruiters instead of relying on the next message.

After approval or denial releases the shared open-ticket slot, the applicant
may create a later **new** ticket and receive a new thread pair. That is repeat
intake, not reopening or continuing the earlier conversation.

The researched recommendation, pending explicit product approval and a future
implementation, is a candidate-facing **My Tickets / Ask Follow-Up** action on
the target public intake panel:

1. Authenticate the click by Discord ID and show only that applicant's eligible
   tickets.
2. Let the applicant select the original ticket and submit the question in a
   private modal.
3. Durably unarchive the same candidate/staff thread pair if Discord had
   auto-archived it, restore candidate membership, post an attributed
   question, and alert recruiters once.
4. Preserve the original `approved` or `denied` decision and track the
   follow-up lifecycle separately. The pair is left open; Discord archives it
   again only after its own seven-day inactivity window, same as any other
   decided ticket.

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
/tickets migrate-legacy source-guild:<server> source-channel:<ticket channel> target-guild:<destination server> candidate-parent:<channel> staff-parent:<channel> type:Auto status:Auto confirm:false
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
/tickets approve-migration-pilot confirm:true
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
account snapshots, Chocolate pages, decision notices, and console refresh
without creating a second ticket pair. Recovery may temporarily unarchive a
terminal thread Discord had already auto-archived, to repair pending
bot-owned work; it leaves the thread open afterward rather than re-archiving
or re-locking it, without reopening the ticket status.

Startup reconciles shared open-ticket slots and reports legacy blockers
(pending legacy initial deliveries, legacy-vs-legacy open-ticket conflicts) in
`rollout-status`, but they never gate v2 intake: legacy state is read-only
source data and duplicate open channel tickets are normal legacy reality. When
such blockers exist the bot prints one `[Tickets] legacy_blockers_ignored ...`
line and continues recovery. The only blocker that still fails closed is an
open-ticket conflict where the thread runtime owns one side (`route: thread`
on the slot or inside `conflicting_tickets`); that raises
`shared ticket recovery remains blocked by a thread-route conflict` naming the
offending slot IDs, and the startup reconciler retries until it is repaired.
Legacy blockers still matter for `rollout-drain`, which fails closed on them.

# Thread ticket system command reference

This README explains the **registered, user-visible commands** for the new
thread ticket system. Use the
[operator runbook](../ticket-console-operations.md) for the exact setup,
pilot, promotion, rollback, drain, and migration order.

As of 2026-08-24, this implementation is pushed on the feature branch but is
**not deployed or configured live**. Production remains unchanged.

## Read this first

- `/ticket` belongs to the legacy channel-ticket system while both systems are
  installed.
- `/ticket-pilot` belongs to the new thread-ticket system. The name does not
  change automatically when the rollout is promoted.
- Applicants do not use slash commands. They open Main or FWA tickets from the
  exact intake-panel buttons.
- During `pilot`, the old public panel remains live and only approved testers
  can use the private v2 panel in the target server.
- Promotion changes only **future intake**. Every existing ticket stays with
  the runtime that created it.
- V2 has no claim, release, close, reopen, or candidate follow-up command.
  Its stored statuses are `open`, `approved`, and `denied`.
- `/ticket-pilot` reads and writes the `tickets` collection. Legacy `/ticket`
  remains bound to `button_store`; never merge or repoint the collections.

## Side-by-side phase map

| Phase | Old-server public panel | Target public-v2 panel | Target private pilot panel |
|---|---|---|---|
| `legacy_only` | Active | Disabled | Disabled |
| `prepared` | Active | Disabled | Disabled |
| `pilot` | Active | Disabled | Only exact approved testers |
| `thread_default` | Disabled | Active | Disabled |
| `rollback_legacy` | Active | Disabled | Disabled |
| `thread_only` | Disabled | Active | Disabled |

Existing legacy tickets always use `/ticket`; existing v2 tickets always use
the console or `/ticket-pilot`. A phase change never converts an existing
ticket. A shared user-and-ticket-type slot prevents the same applicant from
holding duplicate open Main or FWA tickets across the two servers.

## Who can run commands

| Access | Meaning |
|---|---|
| Administrator | An Administrator in the one configured target ticket server. Initial setup also verifies that operator in the old source server. |
| Recruiter | A member of either configured v2 Main/FWA recruiter role, or an Administrator, in the target server. |
| Applicant | No slash-command access is needed; applicants use ticket-panel buttons and their candidate thread. |

Every response containing applicant history, flags, or ticket controls is
private to the recruiter who opened it. Authorization is always rechecked
before private data is read or a mutation is committed; a few modal-launch
buttons can display their empty form before that recheck.

## Required target-server channels

1. **Candidate intake and threads** — public text channel containing the v2
   public panel and owning every private candidate thread.
2. **Recruiter ticket threads** — private recruiter-only text channel owning
   the paired staff threads.
3. **Ticket console** — private recruiter-only text channel containing the
   persistent console.

Main and FWA must use the same candidate parent and the same staff parent. The
private pilot panel may temporarily share the console channel when both
testers already have recruiter or Administrator access. Current readiness code
enforces candidate-parent equality but does not enforce staff-parent equality;
verify the two saved staff-parent IDs manually before pilot and promotion.

## Administrator commands

### `/ticket-pilot setup`

Bind the exact old-server panel and post two separate target-server panels:
the disabled public-v2 panel and the private pilot panel. Run it in the private
target pilot/control channel.

```text
/ticket-pilot setup legacy-panel:<old message link> public-channel:<candidate parent> tester:<you>
```

Options:

- `legacy-panel` — exact old Discord message link or
  `guild/channel/message` IDs; required on first setup.
- `public-channel` — target candidate parent/public-v2 panel channel; required
  on first setup.
- `tester` — one exact pilot user; use this for the owner/co-owner pilot.
- `tester-role` — optional pilot role instead of, or in addition to, a user.
- `replace` — replace both target panel messages in a legacy-safe phase. It
  never replaces the old-server panel.

Setup creates configuration in `legacy_only`; it does not enable v2 intake.

### `/ticket-pilot configure-threads`

Validate and save the candidate parent, recruiter-only staff parent, and v2
recruiter role for one ticket type.

```text
/ticket-pilot configure-threads type:Main candidate-parent:<candidate channel> staff-parent:<staff channel> recruiter-role:<role>
/ticket-pilot configure-threads type:FWA candidate-parent:<same candidate channel> staff-parent:<same staff channel> recruiter-role:<role>
```

Run it once for Main and once for FWA. The candidate parent must equal the
public-v2 channel bound by setup. Validation fails safely when channels,
permissions, or privacy are wrong.

### `/ticket-pilot thread-config`

Re-read and validate both Main and FWA parent/role configurations. Use it after
permissions or channel settings change.

```text
/ticket-pilot thread-config
```

### `/ticket-pilot config`

Display the saved v2 guild, parent channels, recruiter roles, and related
thread settings without changing them.

```text
/ticket-pilot config
```

### `/ticket-pilot console`

Create, inspect, or repair the one persistent recruiter console.

```text
/ticket-pilot console channel:<private recruiter console>
/ticket-pilot console
```

Supply `channel` for initial creation. Omit it later to inspect or repair the
saved console. The command will not silently relocate the console. If the
saved channel is missing, it reports the exact missing channel ID.

### `/ticket-pilot pilot-user`

Add or remove one exact Discord user from private-pilot access.

```text
/ticket-pilot pilot-user action:Allow member:<user>
/ticket-pilot pilot-user action:Remove member:<user>
```

For the planned two-person pilot, allow only the owner and co-owner IDs.

### `/ticket-pilot pilot-role`

Add or remove a role from private-pilot access.

```text
/ticket-pilot pilot-role action:Allow role:<role>
/ticket-pilot pilot-role action:Remove role:<role>
```

A role is unnecessary when the two testers are added individually.

### `/ticket-pilot rollout-status`

Show the current phase, exact old/public/pilot panel bindings, tester counts,
legacy drain totals, pending deliveries, and shared-ticket conflicts.

```text
/ticket-pilot rollout-status
```

This is the first diagnostic command before any phase change.

### `/ticket-pilot rollout-prepare`

Validate all bindings, parents, roles, permissions, startup recovery, and
indexes. `confirm:false` makes no phase or intake change but may idempotently
create required indexes. `confirm:true` moves `legacy_only` or a valid rollback
state to `prepared`. Only legacy intake remains active.

```text
/ticket-pilot rollout-prepare confirm:false
/ticket-pilot rollout-prepare confirm:true
```

### `/ticket-pilot rollout-pilot`

Validate again and enable only the private v2 panel for approved testers. The
old public panel remains active for everyone else; the target public-v2 panel
remains disabled.

```text
/ticket-pilot rollout-pilot confirm:false
/ticket-pilot rollout-pilot confirm:true
```

### `/ticket-pilot rollout-promote`

Switch **new public intake** from the exact old-server panel to the exact target
public-v2 panel. Existing legacy and v2 tickets do not move or change.

```text
/ticket-pilot rollout-promote confirm:false
/ticket-pilot rollout-promote confirm:true
```

Promotion requires a successful live pilot.

### `/ticket-pilot rollout-rollback`

Return new intake to the old public panel without changing existing tickets.

```text
/ticket-pilot rollout-rollback confirm:true
```

Existing v2 tickets remain searchable and manageable in the target server.

### `/ticket-pilot rollout-drain`

Report remaining legacy blockers or, after every blocker is cleared, enter
`thread_only`.

```text
/ticket-pilot rollout-drain confirm:false
/ticket-pilot rollout-drain confirm:true
```

The confirmed command is allowed only from `thread_default` with zero open
legacy tickets, active legacy slots, pending creation/initial-delivery work,
and shared conflicts. It does not delete old channels, disable code modules,
or rename commands.

### `/ticket-pilot migrate-legacy`

Preview or resumably clone one terminal legacy channel ticket into one archived
v2 candidate/staff thread pair. It never modifies or deletes the source.

```text
/ticket-pilot migrate-legacy source-guild:<old server> source-channel:<ticket channel> target-guild:<target server> candidate-parent:<candidate parent> staff-parent:<staff parent> type:Auto status:Auto confirm:false
```

Required selections:

- `source-guild`, `source-channel`, `target-guild`, `candidate-parent`, and
  `staff-parent`.
- `confirm:false` performs a read-only preview.
- `confirm:true` creates or resumes the exact migration after review.

Optional corrections:

- `source-staff-thread` when automatic staff-thread detection is ambiguous.
- `type` as `Auto`, `Main`, or `FWA`.
- `status` as `Auto`, `Approved`, or `Denied`.
- `user-id`, `username`, and comma-separated `player-tags` only when the
  previewed legacy metadata is wrong or missing.
- `attachment-ack` with the exact `LOSS-...` token produced by the latest
  preview when Discord history cannot preserve an attachment.

Open/new legacy tickets are refused. Resolve them in the old system first.
Both migration commands are available only in `pilot`, `thread_default`, or
`thread_only`. Run `migrate-legacy` in the selected/configured destination
server; the operator must also own or be an Administrator in the selected
source server.

### `/ticket-pilot approve-migration-pilot`

Unlock additional legacy migrations after manually verifying the required
one-to-five archived pilot migrations.

```text
/ticket-pilot approve-migration-pilot confirm:false
/ticket-pilot approve-migration-pilot confirm:true
```

The command changes only the migration pilot gate; it does not change ticket
intake or rollout phase. Run it in the bound target server.

## Recruiter commands

### `/ticket-pilot find`

Search v2 tickets by exact Discord ID, player tag, or username. Results and
ticket details are private to the recruiter.

```text
/ticket-pilot find query:<Discord ID, #player tag, or username>
/ticket-pilot find
```

Omit `query` to open the private search form. Search covers the `tickets`
collection only; an un-migrated legacy ticket will not appear.

### `/ticket-pilot history`

Open permanent v2 ticket history for one Discord member.

```text
/ticket-pilot history member:<user>
```

This is a recruiter view, not a candidate-facing history command.

### `/ticket-pilot flags`

Find active applicant flags matching one exact Discord ID or player tag.

```text
/ticket-pilot flags identity:<Discord ID or #player tag>
```

Flag reasons are private recruiter information.

### `/ticket-pilot flag-add`

Create or update an audited applicant flag. Supply at least one Discord ID or
player tag; comma-separate multiple identities.

```text
/ticket-pilot flag-add kind:<Blacklisted|Previously denied|Not loyal to WU> reason:<reason> discord-ids:<IDs> player-tags:<tags>
```

Only `Blacklisted` blocks approval. The other flags warn recruiters. Ticket
detail's **Manage flags** action automatically supplies the ticket's Discord ID
and every current/observed player tag and is preferred when available.

### `/ticket-pilot flag-remove`

Deactivate one exact flag while retaining its audit history.

```text
/ticket-pilot flag-remove flag-id:<exact ID> reason:<reason>
```

Copy the exact flag ID from ticket detail or `/ticket-pilot flags`.

### `/ticket-pilot approve`

Approve the v2 ticket linked to the current candidate or staff thread.

```text
/ticket-pilot approve
```

The command refreshes the applicant's linked accounts first. Approval is
blocked on account lookup failure, zero linked accounts, an active blacklist,
or newly discovered FWA accounts whose Chocolate pages still need review.
Successful completion notifies the applicant and locks/archives both threads;
unfinished Discord effects retry durably.

### `/ticket-pilot deny`

Start the private denial flow for the v2 ticket linked to the current candidate
or staff thread.

```text
/ticket-pilot deny
```

Choose the Main default, FWA default, or a custom reason in the private
controls. Denial refreshes account identity, records failures for retry,
notifies the applicant, and locks/archives both threads.

## Applicant panel actions

The target public and private pilot panels each contain only:

- **Main Clan Interest** — create or resume one Main v2 ticket attempt.
- **FWA Clan Interest** — create or resume one FWA v2 ticket attempt.

Creation produces one private candidate thread and one paired recruiter-only
staff thread. The bot captures Discord identity and linked Clash accounts at
opening, sends the candidate questionnaire, sends staff-only context, and adds
FWA Chocolate links for every currently linked account.

## Candidate follow-up boundary

Candidate return is **not implemented**. Approved and denied thread pairs are
locked and archived. A candidate currently has no supported `My Tickets`,
`Continue Ticket`, reopen, or follow-up action and cannot post into that old
thread one month later.

After approval or denial releases the shared open-ticket slot, that applicant
may create a later **new** Main or FWA ticket and receive a new thread pair.
That repeat-ticket behavior is not reopening and does not continue the old
conversation.

That boundary only applies once a ticket is decided: a still-**open** thread
auto-archives after 7 days of Discord silence but is never locked, so it stays
reachable by its link, re-opens on the applicant's next post, and `My ticket`
or a panel re-click already bring the applicant straight back into it.

The researched—but unapproved and unbuilt—design is:

1. Add **My Tickets / Ask Follow-Up** to the target public intake panel.
2. Authenticate from the clicker's Discord ID and show only that applicant's
   eligible tickets.
3. Let the applicant select the original ticket and submit a question privately.
4. Durably unlock/unarchive the same candidate and staff pair, restore candidate
   membership, post an attributed question, and notify recruiters once.
5. Keep the original approved/denied decision unchanged, track follow-up state
   separately, and relock/rearchive after inactivity.

Do not represent this flow as shipped until its behavior is approved and the
implementation, recovery, permissions, and tests are complete.

## Commands that do not exist in v2

Do not advertise these under `/ticket-pilot`:

```text
claim
release
close
reopen
list
dashboard
diagnostics
cleanup-ghosts
fix-mismatched
```

Some similarly named legacy commands remain under `/ticket` only while legacy
coexistence is installed.

## After legacy retirement: remove `-pilot`

Here, "remove the pilot key" means remove the user-visible `-pilot` command
suffix. It does not mean deleting a Mongo field.

`/ticket-pilot rollout-drain confirm:true` enters `thread_only`, but it does
**not** unload the legacy extension or rename the slash-command group. Remove
the temporary `-pilot` suffix only in a separate, reviewed code release after
legacy is proven safe to disable.

Required retirement release:

1. First ship a prerequisite safety change that includes pending embedded
   legacy `resolution_delivery` work in the drain result, blocks legacy
   approve/deny/override mutations after `thread_only`, and keeps recovery
   running until that outbox is empty. The current drain alone is not a safe
   retirement fence.
2. Confirm `thread_only` and zero blockers with `rollout-status` and
   `rollout-drain confirm:false`.
3. Stop and fully drain the bot so no legacy command or worker can race the
   final proof.
4. While the bot is stopped, independently confirm every embedded legacy
   resolution-delivery record is `complete` or `cancelled`. If any remain,
   restart the prerequisite build, let recovery finish, re-run
   `rollout-status` and `rollout-drain confirm:false`, then stop and repeat the
   proof; do not rerun confirmed drain after `thread_only` and do not deploy the
   retirement build.
5. Stop loading the legacy `/ticket` extension and legacy channel monitor.
6. Rename the v2 command group from `ticket-pilot` to `ticket` in code.
7. Make `thread_only` terminal so an unloaded legacy runtime cannot be
   re-enabled through rollback.
8. Update every user-facing slash-command reference, command-registration test,
   operations example, and help entry in the same release.
9. Replace the cross-server `setup` command with a production public-panel
   inspect/repair command. The current setup command cannot replace a deleted
   public panel in `thread_only`.
10. Deploy once, restart/synchronize Discord commands, and verify that `/ticket`
   exposes only the intended v2 commands and `/ticket-pilot` is gone.
11. Delete only the now-inactive private pilot panel after verification. There
   is no current bot command that deletes it.

The intended post-retirement command set is:

```text
/ticket configure-threads
/ticket thread-config
/ticket config
/ticket console
/ticket find
/ticket history
/ticket flags
/ticket flag-add
/ticket flag-remove
/ticket approve
/ticket deny
/ticket migrate-legacy              # keep while historical cloning is needed
/ticket approve-migration-pilot     # keep until migration pilot approval is complete
/ticket <public-panel-repair>       # implement as part of retirement
```

Retire the temporary `pilot-user`, `pilot-role`, `rollout-prepare`,
`rollout-pilot`, `rollout-promote`, `rollout-rollback`, and `rollout-drain`
surfaces after their audit value is no longer needed. Keep or replace
`rollout-status` with a production health/status command instead of losing its
useful diagnostics. Preserve the console, staff commands, v2 ticket data,
audit history, component IDs, open-slot state, migration checkpoints, and
source channels.

Do **not** manually delete the Mongo `ticket_rollout.pilot` field or remove the
last configured tester beforehand. The current runtime requires that stored
pilot structure even in `thread_only`; deleting it makes the rollout invalid
and disables public v2 intake. Removing that stored compatibility structure
requires an explicit schema/code migration in the same reviewed retirement
release.

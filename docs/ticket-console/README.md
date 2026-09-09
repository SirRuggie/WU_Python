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
- `/tickets` belongs to the new thread-ticket system. The name is permanent —
  it does not change when the rollout is promoted.
- Applicants do not use slash commands. They open Main or FWA tickets from the
  exact intake-panel buttons.
- During `pilot`, the old public panel remains live and only approved testers
  can use the private v2 panel in the target server.
- Promotion changes only **future intake**. Every existing ticket stays with
  the runtime that created it.
- V2 has no claim, release, close, reopen, or candidate follow-up command.
  Its stored statuses are `open`, `approved`, and `denied`.
- `/tickets` reads and writes the `tickets` collection. Legacy `/ticket`
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
the console or `/tickets`. A phase change never converts an existing
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

### `/tickets setup`

Bind the exact old-server panel and post two separate target-server panels:
the disabled public-v2 panel and the private pilot panel. Run it in the private
target pilot/control channel.

```text
/tickets setup legacy-panel:<old message link> public-channel:<candidate parent> tester:<you>
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

### `/tickets configure-threads`

Validate and save the candidate parent, recruiter-only staff parent, and v2
recruiter role for one ticket type.

```text
/tickets configure-threads type:Main candidate-parent:<candidate channel> staff-parent:<staff channel> recruiter-role:<role>
/tickets configure-threads type:FWA candidate-parent:<same candidate channel> staff-parent:<same staff channel> recruiter-role:<role>
```

Run it once for Main and once for FWA. The candidate parent must equal the
public-v2 channel bound by setup. Validation fails safely when channels,
permissions, or privacy are wrong.

### `/tickets thread-config`

Re-read and validate both Main and FWA parent/role configurations. Use it after
permissions or channel settings change.

```text
/tickets thread-config
```

### `/tickets config`

Display the saved v2 guild, parent channels, recruiter roles, and related
thread settings without changing them.

```text
/tickets config
```

### `/tickets console`

Create, inspect, or repair the one persistent recruiter console.

```text
/tickets console channel:<private recruiter console>
/tickets console
```

Supply `channel` for initial creation. Omit it later to inspect or repair the
saved console. The command will not silently relocate the console. If the
saved channel is missing, it reports the exact missing channel ID.

### `/tickets pilot-user`

Add or remove one exact Discord user from private-pilot access.

```text
/tickets pilot-user action:Allow member:<user>
/tickets pilot-user action:Remove member:<user>
```

For the planned two-person pilot, allow only the owner and co-owner IDs.

### `/tickets pilot-role`

Add or remove a role from private-pilot access.

```text
/tickets pilot-role action:Allow role:<role>
/tickets pilot-role action:Remove role:<role>
```

A role is unnecessary when the two testers are added individually.

### `/tickets rollout-status`

Show the current phase, exact old/public/pilot panel bindings, tester counts,
legacy drain totals, pending deliveries, and shared-ticket conflicts.

```text
/tickets rollout-status
```

This is the first diagnostic command before any phase change.

### `/tickets rollout-prepare`

Validate all bindings, parents, roles, permissions, startup recovery, and
indexes. `confirm:false` makes no phase or intake change but may idempotently
create required indexes. `confirm:true` moves `legacy_only` or a valid rollback
state to `prepared`. Only legacy intake remains active.

```text
/tickets rollout-prepare confirm:false
/tickets rollout-prepare confirm:true
```

### `/tickets rollout-pilot`

Validate again and enable only the private v2 panel for approved testers. The
old public panel remains active for everyone else; the target public-v2 panel
remains disabled.

```text
/tickets rollout-pilot confirm:false
/tickets rollout-pilot confirm:true
```

### `/tickets rollout-promote`

Switch **new public intake** from the exact old-server panel to the exact target
public-v2 panel. Existing legacy and v2 tickets do not move or change.

```text
/tickets rollout-promote confirm:false
/tickets rollout-promote confirm:true
```

Promotion requires a successful live pilot.

### `/tickets rollout-rollback`

Return new intake to the old public panel without changing existing tickets.

```text
/tickets rollout-rollback confirm:true
```

Existing v2 tickets remain searchable and manageable in the target server.

### `/tickets rollout-drain`

Report remaining legacy blockers or, after every blocker is cleared, enter
`thread_only`.

```text
/tickets rollout-drain confirm:false
/tickets rollout-drain confirm:true
```

The confirmed command is allowed only from `thread_default` with zero open
legacy tickets, active legacy slots, pending creation/initial-delivery work,
and shared conflicts. It does not delete old channels, disable code modules,
or rename commands.

### `/tickets migrate-legacy`

Preview or resumably clone one terminal legacy channel ticket into one archived
v2 candidate/staff thread pair. It never modifies or deletes the source.

```text
/tickets migrate-legacy source-guild:<old server> source-channel:<ticket channel> target-guild:<target server> candidate-parent:<candidate parent> staff-parent:<staff parent> type:Auto status:Auto confirm:false
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

### `/tickets approve-migration-pilot`

Unlock additional legacy migrations after manually verifying the required
one-to-five archived pilot migrations.

```text
/tickets approve-migration-pilot confirm:false
/tickets approve-migration-pilot confirm:true
```

The command changes only the migration pilot gate; it does not change ticket
intake or rollout phase. Run it in the bound target server.

## Recruiter commands

### `/tickets find`

Search v2 tickets by exact Discord ID, player tag, or username. Results and
ticket details are private to the recruiter.

```text
/tickets find query:<Discord ID, #player tag, or username>
/tickets find
```

Omit `query` to open the private search form. Search covers the `tickets`
collection only; an un-migrated legacy ticket will not appear.

### `/tickets history`

Open permanent v2 ticket history for one Discord member.

```text
/tickets history member:<user>
```

This is a recruiter view, not a candidate-facing history command.

### `/tickets flags`

Find active applicant flags matching one exact Discord ID or player tag.

```text
/tickets flags identity:<Discord ID or #player tag>
```

Flag reasons are private recruiter information.

### `/tickets flag-add`

Create or update an audited applicant flag. Supply at least one Discord ID or
player tag; comma-separate multiple identities.

```text
/tickets flag-add kind:<Blacklisted|Previously denied|Not loyal to WU> reason:<reason> discord-ids:<IDs> player-tags:<tags>
```

Only `Blacklisted` blocks approval. The other flags warn recruiters. Ticket
detail's **Manage flags** action automatically supplies the ticket's Discord ID
and every current/observed player tag and is preferred when available.

### `/tickets flag-remove`

Deactivate one exact flag while retaining its audit history.

```text
/tickets flag-remove flag-id:<exact ID> reason:<reason>
```

Copy the exact flag ID from ticket detail or `/tickets flags`.

### `/tickets approve`

Approve the v2 ticket linked to the current candidate or staff thread.

```text
/tickets approve
```

The command refreshes the applicant's linked accounts first. Approval is
blocked on account lookup failure, zero linked accounts, an active blacklist,
or newly discovered FWA accounts whose Chocolate pages still need review.
Successful completion notifies the applicant and locks/archives both threads;
unfinished Discord effects retry durably.

### `/tickets deny`

Start the private denial flow for the v2 ticket linked to the current candidate
or staff thread.

```text
/tickets deny
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

Do not advertise these under `/tickets`:

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

## After legacy retirement

`/tickets` is permanent — it is never renamed to `/ticket`. Retiring legacy
means deleting the `/ticket` command group and its panels once
`rollout-drain confirm:true` is proven clean, not renaming `/tickets`. Stop
loading the legacy `/ticket` extension and channel monitor, unregister its
setup panels, and remove its Discord command registration in one reviewed
release; `/tickets` and its data are untouched throughout.

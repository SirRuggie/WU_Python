# Ticket settings and command consolidation

Effective September 30, 2026. This supersedes the 20-command inventory in
`ticket-command-retirement-2026-09-30.md`.

## Five slash commands

- `/tickets approve`: approve the ticket in the current thread.
- `/tickets deny`: deny through the existing reason flow.
- `/tickets flag-add`: add/update an applicant flag and reason.
- `/tickets flag-remove`: deactivate a flag and record why.
- `/tickets console`: administrator entry for posting or repairing the recruiter console.

The recruiter console now includes Find Ticket, Browse Tickets, Member History,
Flags, Refresh, and Create for Recruit. History opens a private user selector;
Flags opens a Discord ID/player-tag search. Both recheck recruiter authorization.
Existing approve/deny/close, ticket links, detailed flag management, and reopen
controls remain available. Three tickets fit per page, with 39 components at the
maximum layout (Discord permits 40).

## Manage → Recruitment → Ticket Settings

Only administrators in the configured ticket guild can open or use settings.
Every action rechecks permission, session owner, server, and expiry. Drafts
expire after 30 minutes and have no authority outside that owner/server.

- Main and FWA: candidate channel, staff channel, and recruiter role selections.
- Staff Access: additional roles permitted to view the staff parent, without
  granting recruiter actions. Does not edit Discord role/channel permissions.
- Entry Panel and Console: show bound locations, repair the existing public
  entry post, recreate/rebind a deleted post, or post/repair the console.
- Inactivity Timing: review interval in minutes; 10080 means seven days.
- Check Permissions and Health: validate both ticket types and report startup
  storage-index errors.
- Isolated Testing: existing administrator/testing controls, with return navigation.

Existing location protections remain: candidate parents must match the bound
entry channel; a console already bound to one channel cannot be silently moved.
Relocation requires a coordinated operational migration, not a settings edit.
Repair uses saved content templates and keeps the current intake phase.

Testers use `/manage section:Ticket Testing`. An administrator or explicitly
allowlisted member/role in an active window can enter; being a tester does not
permit Ticket Settings access. Tests continue using isolated test storage.

## Storage and concurrency

- Persistent values: existing `ticket_setup` collection, `_id: config`.
- Private drafts: `component_state`, fixed 30-minute expiry.
- Audit: dedicated `ticket_settings_audit` collection in the same settings
  database as `ticket_setup`. Each record has operator, guild, UTC time,
  before/after changed fields, and pending/committed/conflict state.
- Saves compare the original values of all relevant settings and a revision;
  stale panels cannot silently overwrite newer admin changes.
- Permissions are validated before a config write. Main/FWA validators include
  the other configured recruiter role when they share a staff parent.
- The first message in a new Main or FWA candidate thread (the recruiter role
  ping) is pinned. This needs Pin Messages for the bot in the candidate parent.
  Pin Messages is not validated: a failed pin is logged as a warning, the
  ticket still opens, and the next opening-message retry tries the pin again.
  Test tickets send no ping, so they have no pin.
- Entry repair preserves pilot bindings and intake mode, uses revision-guarded
  rebinding, and removes only a newly created replacement if that rebind fails.
- No application decisions, role assignments, or source history are changed by
  this consolidation.

## Additional slash commands retired (15)

Moved to console: `find`, `history`, `flags`.
Moved to management: `config`, `configure-threads`, `thread-config`, `setup`, `testing`.
Retired rollout/pilot controls: `pilot-user`, `pilot-role`, `rollout-status`,
`rollout-prepare`, `rollout-pilot`, `rollout-promote`, `rollout-drain`.

Live pre-deployment inspection confirmed `thread_default`, valid bindings, and
10080-minute inactivity. Those values are preserved. Old open Recruit 4 tickets
and historical migration recovery are not deleted or implicitly resolved.

## Warrior Desk

The `desk` part edits `desk_channel_id`, `desk_staff_parent`,
`account_thread_recruiter_role` and `staff_thread_recruiter_role`; the staff parent
may fall back to Main's configured staff parent. Its status names every missing
saved prerequisite and focuses the corresponding field. Post is disabled with
an explanation and `aria-disabled` while incomplete or dirty. Save changes
remains separate. A live binding offers secondary **Repair panel**.

The existing `restore_desk_entry` action now lives beside these fields, retaining
confirmation/revision/idempotency guards. It refuses unless both roles, the
channel, effective staff parent and `thread_default`/`thread_only` are saved.
Native checks verify target ownership and bot/handler permissions before posts.
New Desk-enabled pairs use private per-type invitations; non-admin Manage
Threads would bypass that boundary and fails guided readiness. Extra viewer
roles read the parent, not every new private thread. Historical public pairs are
not converted or made a startup-wide failure.

Pure validation/history helpers belong to `utils/ticket_settings.py`, shared by
native and HTTP adapters. No live settings, roles, permissions or panel post was
changed during development. Ruggie's guided setup/release after Shaka approval
is still required; see [Warrior Desk](warrior-desk.md).

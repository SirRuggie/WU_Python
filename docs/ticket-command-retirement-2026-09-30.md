# Ticket command retirement — 2026-09-30

**Later consolidation:** [Ticket Settings](ticket-settings.md) records the additional
15 slash-command removals and the final five-command interface.

Owner request: remove old ticketing commands, record the removal, and audit current commands.

## Removed from slash registration and help (18)

The entire global `/ticket` group is retired:

- `/ticket setup` — old channel-ticket entry panel.
- `/ticket config` — old channel-ticket configuration.
- `/ticket change-category` — old ticket category routing.
- `/ticket reset-counter` — legacy counters.
- `/ticket list` — legacy open-ticket list.
- `/ticket dashboard` — legacy dashboard.
- `/ticket diagnostics` — legacy channel/record diagnostics.
- `/ticket cleanup-ghosts` — legacy missing-channel cleanup (not applicant Ghosted flags).
- `/ticket fix-mismatched` — legacy channel/status correction.
- `/ticket approve` — legacy approval.
- `/ticket deny` — legacy denial.
- `/ticket migrate-store` — old button_store copying command.
- `/ticket claim` — legacy recruiter claim.
- `/ticket release` — legacy claim release.

Also retired from the current `/tickets` group:

- `/tickets migrate-legacy` — single legacy-ticket import.
- `/tickets migrate-all` — legacy batch import.
- `/tickets approve-migration-pilot` — legacy import pilot approval.
- `/tickets rollout-rollback` — switch new intake back to the legacy runtime.

Command classes remain unregistered historical implementation. Importing them cannot register these commands. The legacy loader continues existing-ticket listeners and persistent controls because Recruit 4 still has open tickets. This change does not delete ticket data, Discord channels, threads, flags, history, or migration checkpoints; it does not change intake phase or permissions. Migration engines and durable recovery remain available for remaining history work. Current console controls are unchanged.

Discord command synchronization deletes unknown commands at startup. Registration tests verify the legacy group is empty and has no loader command entry, the current group contains exactly the 20 listed commands, and help matches registration. Live global and guild command inventories must be checked after deployment.

## Current command audit (20)

Registered only in Warriors United (configured TICKETS_GUILD_ID).

### Recruiter/admin operations

- `/tickets approve` — approve the ticket linked to the current thread.
- `/tickets deny` — deny the current ticket using the denial flow.
- `/tickets find` — search tickets by Discord ID, player tag, or username.
- `/tickets history` — show a selected member's ticket history.
- `/tickets flags` — look up active applicant flags.
- `/tickets flag-add` — add a flag or update its reason.
- `/tickets flag-remove` — deactivate a flag with a recorded reason.

### Administrator configuration and rollout

- `/tickets console` — post, bind, inspect, or repair the shared recruiter console.
- `/tickets config` — inspect ticket configuration.
- `/tickets configure-threads` — configure and validate candidate/staff parents and recruiter roles.
- `/tickets thread-config` — inspect and revalidate thread settings.
- `/tickets setup` — bind/repost public and pilot entry panels; initial setup still supports legacy panel binding.
- `/tickets pilot-user` — add/remove a pilot tester.
- `/tickets pilot-role` — add/remove a pilot tester role.
- `/tickets rollout-status` — inspect phase, panel bindings, and outstanding drain blockers.
- `/tickets rollout-prepare` — validate bindings and prepare the pilot.
- `/tickets rollout-pilot` — enable allowlisted pilot intake.
- `/tickets rollout-promote` — make thread intake public.
- `/tickets rollout-drain` — check legacy drain and optionally enable thread-only mode.

### Isolated testing

- `/tickets testing` — open isolated ticket testing; administrators manage test windows, and allowlisted testers can use an active window.

Close/reopen, Create for Recruit, ticket links, and inactivity review remain console/button actions, not separate slash commands. `/manage` remains the entry point for editable recruitment content.

## Verification completed

- Code deployment: `132fca7`; bot restarted successfully September 30, 2026 at 15:46 EDT.
- 341 targeted tests passed (registration, help, startup, console, rollout, legacy compatibility, migration/recovery).
- Discord REST confirmed no global `/ticket` or `/tickets` command.
- Warriors United exposes exactly the 20 `/tickets` subcommands above.
- All four legacy recruitment guilds expose no guild-local `/ticket` or `/tickets` command.
- Startup reported `thread_runtime_ready configured_fields=6/6 index_errors=0`.

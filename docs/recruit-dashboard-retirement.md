# AUTH-001 — Recruit dashboard retirement

Completed 2026-09-29. `/warrior setup discord-user:` replaces `/recruit dashboard`.

## Audit findings

The old command had no recruiter/admin gate before opening a dashboard for an
arbitrary target member. Nickname, Town Hall, and clan-role callbacks relied on
stored state without consistently rechecking the clicking actor's authorization,
session ownership, or guild. Some paths replaced cached full role lists. The
member-role tools had recruiter and hierarchy checks, but that did not protect
the other dashboard paths. Begin Walkthrough checked a hard-coded role, while
the earlier welcome/walkthrough controls did not provide uniform authorization.

The resolution is retirement, not patching a second onboarding implementation.
The entire seven-file dashboard package was removed, including its slash
registration, nickname modal, role/clan/Town Hall mutation handlers, walkthrough
sender, and in-memory walkthrough worker. The explicit startup loader was removed.

All 23 old action IDs resolve only to a retirement notice directing the user to
`/warrior setup`. This handler never loads old sessions, changes members, starts
walkthroughs, or writes MongoDB. An already-open legacy modal is retired too.

## Preserved boundaries

- `/recruit questions` remains registered and functional.
- `/warrior setup` remains the supported onboarding entry point. Its fresh
  authorization, session-owner/guild checks, hierarchy guards and incremental
  role mutation remain in place.
- Manage → Roles keeps its existing bot hierarchy helper, now in
  `utils/role_permissions.py`, without importing the retired dashboard.
- The already-unregistered `/role` compatibility module no longer imports or
  exposes the old bulk-role dashboard class.
- Existing onboarding records and the legacy recruit-role cleanup task remain;
  this retirement does not delete history or cancel durable cleanup obligations.

Regression checks cover command registration, all retired control responses,
Warrior authorization/ownership/hierarchy, current Roles management, startup
extension discovery, and component action registration.

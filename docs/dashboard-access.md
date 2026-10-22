# Dashboard access

Dashboard access is independent of native Discord command privileges. Only the
two existing owners (505227988229554179 and 644005027052126208) can read or edit
Access settings. Discord server ownership or Administrator does not create a
third dashboard owner. The owner list is not editable through grants.

Owners grant actions to a specific member or an explicitly selected Discord
role. Grants add together. All clans are in scope and CWL permissions cover both
Main and Lazy. CWL and Clan management remain separate permission groups.

CWL actions: manage signups, edit rosters, publish rosters, manage reminders,
manage results, manage bonuses, send roster/bonus announcements, and manage CWL
settings. CWL staff can read shared CWL context needed for these workflows;
mutation checks are action-specific and unknown CWL writes fail closed. Reminders
permission includes configuring automated schedules and manual return reminders.
Clan settings and official clan-weight editing have separate checkboxes. Other
existing tool areas retain their own grants and Discord hierarchy constraints.

## Storage and migration

`utils/dashboard_access.py` owns the `settings.bot_config` document with ID
`dashboard-access-v2` (respecting the configured bot_config collection route).
Grants, revision, and the latest 200 before/after history entries are saved in one
atomic majority+journaled Mongo write. Concurrent saves require the same revision;
conflicts require reloading. Uncertain saves are not automatically retried.
This collection is covered by the existing Mongo backups.

Before the first owner save, legacy SQLite grants and bot grant documents remain
readable. The first save atomically imports all existing SQLite grants, expands
legacy CWL access to the equivalent CWL actions, and preserves weight access for
legacy clan staff. Protected owners are not copied into editable entries. After
that, the single Mongo document is authoritative for web and workers; legacy
records remain for rollback/reference and are not written. Do not restore only
old SQLite grants to change current access. Rollback to old software requires an
explicit reviewed grant export; old grant records may no longer represent current
permissions.

## Enforcement and failure handling

Production requests read the shared policy. Role membership is fetched from
Discord when role grants exist; stale role membership is never used to authorize.
If Discord role lookup is unavailable, direct grants continue to work, role grants
fail closed, and the dashboard explains the missing role-based access. Public
login endpoints remain usable with an expired session cookie.

The shared management worker rereads grants and current role membership before
executing. Queued roster announcements recheck send access before attempting
Discord delivery. Revocation cannot undo already completed or in-flight actions.
Scheduled reminders are configuration owned by the server and are not cancelled
when the person who configured them loses access.

Nonowners cannot use member-role tools to add/remove a role that grants dashboard
access. Self-service text-command role controls also reject those roles. Native
Discord permissions outside dashboard tools remain separate.

The UI refreshes access on focus, every visible minute, and after denied requests.
A lost page permission returns the user to Home. Actual requests always enforce
current permissions even before the UI refreshes.

## Verification scope

Isolated API tests cover both owners, fake server-owner sessions, malformed
permissions, CSRF, legacy preservation, direct/role unions, removed roles,
conflicting revisions, failed writes, restart reads, action isolation, role lookup
outages and expired-session login. Worker tests cover revoked queued sends.
Frontend tests cover separate navigation groups and action visibility. Browser
checks used isolated sample data at 320px, 390px and 1280px: role edit/save,
selected-action counts, saved feedback, and no horizontal page overflow.
No live Discord messages or production grant changes were made during review.

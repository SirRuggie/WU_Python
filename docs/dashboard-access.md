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

**Save weights from Discord** (`discord_weights`, Clan management group) is the
one Discord-side permission on this page. It allows only the Save steps of
`/fwa weight`, including linking a typed player tag to the member in ClashPerk,
and does not open Clan weights on the dashboard. Edit clan weights
does not include it, and it does not include Edit clan weights. Grant it to a
member or a role. The dashboard service rechecks it on every bridge action; see
[War Weight management](war-weight-management.md#save-from-fwa-weight).

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

Production requests read the shared policy. The member is fetched from Discord
when the person has a direct grant or any role grant exists. Decision D11 (backend
audit 239, approved 2026-11-17) permits successful member-role IDs to be cached for
at most 30 seconds, using monotonic time. This is an approved maximum 30-second lag
for Discord role changes and successful membership checks, including departures.
The cache is local to one application process, keyed by guild and user, bounded
to 512 successful entries, and stores immutable role IDs with a copy returned to
each caller. Concurrent reads share a successful lookup; cancellation propagates,
and a cancelled fetch does not populate the cache.

Grants, revocations, permission decisions and request-specific scope intersections
are never cached. Each request rereads the policy even when role IDs are cached.
404s, failures and malformed responses are not cached; an expired success is
discarded before refreshing, with no stale-success fallback on failure. If role
lookup is unavailable, direct grants continue to work, role grants fail closed,
and the dashboard explains the missing role-based access. Native management
identity reads, worker authorization and signup membership checks keep their
existing independent freshness rules.

A person who is not in the Warriors United server has no staff access (Ruggie,
2026-11-13). When Discord answers 404 for the member, the request gets no
dashboard permissions, direct or role. Grants are not deleted: a person who
rejoins has their access again on the next request. Open pages lose staff pages
at the next access refresh (focus or the one-minute check). Owners are never
checked, so they cannot be locked out. A person with no grant causes no member
lookup unless role grants exist. Legacy SQLite grants (before the first owner
save) follow the same rule. The `/fwa weight` bridge is unchanged: it runs from a
slash command inside the server. Public
login endpoints remain usable with an expired session cookie.

Decision D18's dashboard `write` argument is forwarded explicitly to the shared
policy. Existing section grants are management rights and authorize their
section's reads and writes; no read/write grant field, representation or migration
is introduced. Native Discord role restrictions are not applied to explicit
dashboard grants. `strikes_read` is a read-only aggregate of the three strike
grants: it never authorizes a write, including for owners. Mutations continue to
use their explicit strike action scope. Unknown sections fail closed. Owners
retain full access to all valid management sections; legacy expansion and
per-request scope intersections are unchanged.

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

Audit239 fixture review inventories all current management scope mappings and
99 authorization call sites, with 47 scenarios / 2256 read/write matrix entries
covering every permission as both direct and role grants, owners, legacy grants,
grant unions and request-scope restrictions. Before/after valid UI writer rights
are identical. Only an invalid write through read-only `strikes_read` is newly
denied; its current endpoint/decorator paths are reads. No production grants were
read, and no claim is made about live Discord cache delivery or membership.

Role-cache responses accept only ASCII-decimal role ID strings whose numeric
value is in the positive uint64 range (`1..2**64-1`). Valid strings are retained
without coercion; malformed or out-of-range responses are not cached and the
next request refetches instead of reusing an expired success.

# Roles and clan links

The content document `family-links` is posted and updated through the existing
content dashboard and Discord `/manage` flow. It has editable text, one local WU
banner slot, a fixed gold footer and a posting channel. Link the existing post
1449196073405911121, then Update it in place. There is no separate publishing
command; `/family-links` is retired.

The public Components V2 panel opens private My roles and clan replies. Public
custom IDs survive restarts. Legacy role menus open My roles without applying
the old values. Each private menu route includes an opaque random instance token;
it contains no member or role data. The existing component-state owner binds that
instance to its actual ephemeral message, guild, member, menu kind, immutable
offered roles and held-when-shown baseline for 15 minutes. Missing, malformed or
expired state fails closed.

Selections express intent against that displayed baseline: add selected minus
held-when-shown, and remove held-when-shown minus selected, restricted to offered
roles still in the current list. Fresh authority and target-state checks precede
each single-role Discord call. Roles already at the intended target are no-ops;
staff additions and removals never become a new delta baseline. A durable atomic
per-menu claim prevents duplicate or restarted submissions from replaying writes.
Prior instance claims remain until expiry. A delayed old submit with a confirmed same-menu receipt receives “These roles
were already saved.” without replacing the current successor panel. An expired
instance or a menu retired by the other menu receives the stale reopen message,
never an unsupported success claim.

After a certain result, including a known partial failure, the same private reply
shows the C4 result first and fresh menus with a new instance and current holdings
as their baseline. An uncertain claim, Discord call or receipt produces “Your
roles may have changed. Select My roles again to check.” with no successor or
automatic retry. Provider exception details are never printed. Known failures and uncertain
results use the existing red error accent; successful and unchanged results stay
gold. Server-role labels are rendered as literal text in result messages: Markdown,
mentions, URL schemes and domain-shaped runs are neutralized at that Discord
text boundary. Stored labels and plain select-option labels are unchanged.

Cross-list assignments are rejected at save with “This role is already used for
a Town Hall.” or “This role is already a server role.” before any write. If legacy
stored data still overlaps, Town Hall alone controls that role, including
deselection; the Server roles menu hides it. The editor retains the stored server
row and shows “Also used for a Town Hall. Remove it from one list.” Nothing is
auto-deleted.

`utils/town_halls.py` owns both the existing schema 1/2 registry and the separate
routed `town_hall_roles` collection document (schema 1, guild `_id`, revision and role map).
The public joined reader hides removed levels while retaining their stored role
entries. Registry bytes and legacy `warrior_settings.townhalls` are not changed
by the roles migration. Warrior Desk and My roles use the joined owner API;
Warrior settings no longer edit TH mappings.

Server roles live in the guild's `bot_config` `server_roles:<guild>` document,
owned by `utils/server_roles.py`. Its ordered list holds at most 25 unique roles,
labels up to 40 characters and short lines up to 100. Dashboard Server roles is
beside Roles in Members settings. Add, remove and reorder remain drafts until
Save; navigation prompts before discarding a draft. Both owners use revision
CAS and never silently overwrite concurrent edits.

Every selected role must exist, be unmanaged, have no Discord permissions, sit
below the application's highest role and not be @everyone. Roles granting
existing dashboard access are also excluded. Save and grant both enforce these
rules. Dashboard choices and saves also retain the existing role tools’ actor hierarchy checks. A role which gains permissions after a menu opens is skipped.

Town Hall Save writes registry fields first and the role document second, each
with its own revision. A second-write failure reports the saved registry fields
and keeps the role draft. Unknown write outcome is reported as `role_saved: null` and `role_outcome: unknown`, never a confirmed failure, and disables Save until a fresh read before
retrying. Role changes use the existing Town Halls history with action `role`.

Clan links use the shared active-clan reader, opting into CWL only for this
panel. War clans retain Tactical then Flexible Fun order. Archived and removed
clans are excluded. Large lists use private selects and paging, without changing
About Us or WU FAQ behavior. Join buttons, including selected or legacy clan
replies, use the valid registry emoji or that clan’s type fallback (Tactical ⚔️,
Flexible Fun 🎮, FWA 🏳️, CWL 🏆).

## Release

Shaka's exact-head approval and the task's explicit `release 283` authorization
are required. Back up and verify protected counts first. Show production dry-run
reports for `tools/migrate_town_halls.py --roles --dry-run` and
`tools/seed_server_roles.py --dry-run`, then apply only if conflict-free. The
migration writes only the new roles document; the seed never replaces an
existing server-role list. Switch reviewed bot/backend/frontend releases, smoke
read-only and compare counts. Link the existing message and Update in place
through `/manage`. Rollback switches code; old code ignores the new collection
and continues using its existing registry and legacy lists. Never restore a DB.

Same-process saves share a per-guild reentrant guard across preflight and CAS, including the composite Town Hall Save. This prevents concurrent requests on the same event loop from passing opposing stale checks. It is not a cross-process transaction; direct database edits or separate processes can still introduce overlaps, which the runtime handles with Town Hall priority. Both migration dry-runs enumerate all cross-list conflicts and return a failing status; apply refuses before any write.

1394 takes precedence for removed levels: a retained TH role remains hidden from all menus, including a legacy duplicate server row. Active-level duplicates follow1399 and remain controllable only through the TH menu. Removing a level or resolving a duplicate never deletes the stored counterpart automatically.

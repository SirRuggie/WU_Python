# Warrior Setup

`/warrior setup discord-user:` opens a private, recruiter-owned onboarding checklist.
The existing `/recruit dashboard` and its action IDs remain unchanged. Warrior
uses separate action IDs, sessions, settings, walkthrough records, and worker.

## Workflow

1. **Nickname:** enter an IGN, time zone, and two-letter country code or flag.
   The combined nickname is validated against Discord's 32-character limit.
2. **Member Roles:** add/remove selected roles or Quick Set-up. Quick Set-up adds
   Family, New Recruit, and Strike System Accepted before removing Visitor; if
   any addition fails, Visitor stays. Every outcome is reported explicitly.
3. **Town Hall Roles:** select all applicable levels. Only configured TH roles
   change; additions must succeed before superseded TH roles are removed.
4. **Clan Roles:** add chosen clans, with pagination beyond 25 choices. Existing
   clan roles are preserved. Bulk add/remove lives in Advanced with a one-use
   confirmation.
5. **Server Walkthrough:** choose one assigned clan. The member must have exactly
   one open, live, new-system ticket in the command's server. The welcome and
   Begin Walkthrough button are posted to that candidate thread, never the old
   launchpad (`1128966424082255872`). The next start message also goes there.
   Any currently authorized recruiter can press Begin in that message.

The remaining destinations are unchanged: the clan's `announcement_id` and
`chat_channel_id`, Help Me Attack (`1005916813378465832`), and Family Lounge
(`671836698371424256`). Existing walkthrough copy, clan join link/banner and
red downstream footer images are carried over. The new dashboard is goldenrod.

No ticket is created or approved by this tool. Missing/ambiguous tickets fail
clearly before saving or posting a new walkthrough. Clan membership and channel
read access are checked before scheduling. The ticket must still be open when
the welcome/start messages are delivered; resolving it after those messages does
not interrupt the remaining clan-channel tour.

## Authorization and role safety

Recruitment Team, configured Main/FWA recruiter roles (including thread-specific
roles), or administrators can open the command. Every action re-fetches the
actor, target member, roles, and permissions from Discord. Private controls are
bound to their recruiter and guild. Nickname/member hierarchy and bot capability
checks run before changes. Managed roles, roles above the bot/actor, and roles
that exceed a non-admin actor's permissions cannot be assigned.

Role changes use individual add/remove endpoints, never full cached role-list
replacement. Partial failures are visible. Permission or membership changes after
the panel opened are respected. Isolated ticket testing cannot mutate live
members through this command.

## Settings and persistence

Server Settings is no longer offered in the dashboard. Existing configuration
is preserved. Settings live in `warrior_settings` as `warrior_settings:<guild_id>`:
standard roles, Town Hall roles, Help and Lounge channels. Defaults copy the old
recruit dashboard. These overrides never affect the old command. Clan roles and
clan announcement/chat IDs continue to come from existing clan configuration.
Settings are snapshotted for a walkthrough; changes apply to future runs.

Private sessions use the existing 24-hour component-state TTL. Durable runs use
`warrior_walkthroughs` with `_id=warrior:<guild_id>:<user_id>` and
`kind=warrior_walkthrough`, with no session TTL. A run records its selected clan,
ticket, initiating recruiter, destinations, next step, sent-message IDs, delivery
lease, errors, and completion. Role-change audit records live in `warrior_audit`, use
`warrior_audit:<guild_id>:<user_id>` and retain the latest 100 operations.

The worker resumes from the saved checkpoint after restart. Each message has a
stable component ID scoped to its run and step; recovery checks for an already
sent message before posting. Delivery is time-bounded within a durable lease.
Failed steps pause, display the failure in Warrior Setup, and support **Retry
unfinished steps**. Completed steps are never intentionally replayed. A completed
run can be explicitly restarted from Advanced; its prior record is archived in `warrior_history`.

The configured New Recruit role is removed two hours after successful walkthrough
completion. This new timer does not start for an interrupted tour. Cleanup errors
retry hourly. Legacy walkthroughs and their existing cleanup task are unchanged.

## Verification

`tests/test_warrior_setup.py` covers separate command/action registration, fresh
permission checks, hierarchy, incremental role updates and truthful partial
failures, nickname limits, session ownership/expiry, one-use bulk confirmations,
new-ticket routing, preserved tour destinations, component limits/pagination,
modal acknowledgement, checkpoint recovery, duplicate Begin clicks, and paused
walkthrough handling. No test sends messages or changes live Discord roles.

## MongoDB ownership and organization

This follows the house rules in [MongoDB refactor backlog](mongodb-refactor.md).
`extensions/warrior/schema.py` owns schema version 1 and initial normalization.
Collections are explicitly declared in `utils/mongo.py` and follow the database
of the configured ticket settings collection (currently `settings`). This does
not prematurely perform the proposed database rename or deploy the unrelated
routing work. The future production database move must include these four names.

- `warrior_settings`: one configuration record per guild.
- `warrior_walkthroughs`: one current resumable run per guild/member.
- `warrior_history`: completed runs keyed by original run key plus unique token.
- `warrior_audit`: one record per guild/member with at most 100 role operations.

All use deterministic keys, BSON UTC dates, integer Discord identities and
explicit schema versions. Active progress has named due-work and role-cleanup
indexes, and history has a guild/member/completion index. No durable records use
the component session TTL. Completed history is retained; no automatic purge is
introduced. Audit arrays are capped at the write site. Startup index failures
are logged and retried by the worker without disabling the bot.

The early-release migration selects only Warrior-prefixed records and matching
walkthrough kinds from the old shared collections. It copies, verifies content,
then conditionally removes the unchanged source. Conflicts stop migration and
preserve the source for review. It never moves legacy `/recruit` records.
Storage tests verify separation, version/date normalization, conflict preservation
and recovery after a partial migration.

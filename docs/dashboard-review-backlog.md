# Dashboard workflow review coverage

Updated 2026-10-23. These are review priorities, not confirmed defect severities.
The owner asked to finish the member journey first, explain the staff areas, and
return to the remaining list later. Do not silently mark deferred items complete
because a shared CSS change or unit test covers part of them.

## Current member-journey pass

Scope: Discord sign-in destinations (existing backend regressions), external
account-linking handoff, Home to signup, account selection, review/submission,
saved signups, changing pools, withdrawal enforcement, and published assignments.

- Existing provider combines ClashKing and ClashPerk lookup results; no new link
  store or account-ownership authority was added.
- Clear Discord linking instructions and return/refresh actions are shared by
  Home and signup, with hidden links, identity mismatch, and propagation guidance.
- Refresh preserves selections, with changed ownership/pool consent reconciled
  before another review. Filters and pagination retain selection across pages.
- Page/season changes and sign-out protect unsubmitted selections. Pending signup
  submissions block navigation and repeated local submission. Native beforeunload
  protects tab closing/reloading; it cannot preserve a draft after a confirmed exit.
- Season-list failure has its own Retry. Saved-signup failure is not presented as
  an empty signup list. Closed seasons explain the available next steps.
- Saved accounts have an explicit pool-change review, existing withdrawal, and
  confirmation links to signups/assignments. Existing backend transactions enforce
  ownership, source-pool consent, closed seasons, and assigned-account restrictions.
- Published joining instructions are displayed as escaped text. Assignment pages
  no longer promise a notification that this read-only page cannot guarantee.

## Account linking research

[ClashKing live API contract](https://api.clashk.ing/openapi.json), checked October 21:
POST `/v2/links/shared` uses DeveloperToken for visible-link lookup. Creating a link
uses POST `/v2/links/{userId}` with UserToken or BotToken, player_tag and optional
api_token. Our existing management adapter distinguishes CLASHKING_BOT_TOKEN from
the lookup token. The management credential was not present in the workspace
configuration checked for this pass. Do not treat our Discord OAuth session as a
ClashKing user token, or claim access to their write API from lookup access.

[ClashPerk linking guide](https://docs.clashperk.com/overview/link-account) documents
`/link create` and `/verify`. The existing WU adapter uses read-only `/links/query`.
No supported third-party account-creation API for ClashPerk was established in this
research. This does not prove no such API exists. Direct writes to either provider
were not attempted and no real accounts were linked or transferred during tests.

## Deferred list — return to these when requested

1. **Strikes and replacements: scoped cleanup completed October 23.** Account
   selection, manual-strike review, history return, leave confirmation, replacement
   editing and failed-save recovery were reviewed. See `strike-system.md` for
   evidence and remaining concurrency, device and live-integration limits.
2. **Permissions and member administration: scoped cleanup completed October 23.**
   Protected owner identities, permission disclosures, draft/change review, conflict
   recovery and member-role selection were reviewed. See `dashboard-access-review.md`
   for evidence and remaining live-integration/device limits.
3. **Tickets and applications: scoped workflow cleanup completed October 23.**
   Ticket index/reader, application settings discovery, editing, recovery and
   publishing draft protection were reviewed. Replies and decisions remain in
   Discord. See `ticket-dashboard-viewer.md` for tests and live-integration limits.
4. **Commands and image tools: scoped cleanup completed October 23.** Create/edit,
   preview, explicit tests, saved commands, image selection and gallery maintenance
   were reviewed. See `commands-images-review.md` for evidence and limits.
5. **Medium review priority: Server settings, FWA, and integrations.** Configuration
   dependencies, truthful state, save semantics, and recovery.
6. **Cross-cutting: Sign-in and staff deep links.** Approved member destinations
   have coverage; preserving staff destinations through OAuth remains outstanding.
7. **Cross-cutting: Accessibility and devices.** Full screen-reader, high-zoom,
   mobile-keyboard/landscape, and real-device testing remain outstanding.
8. **Cross-cutting: Performance.** Measure the existing bundle-size warning on
   slower devices/networks before claiming a measured performance defect.
9. **Cross-cutting: Live end-to-end integration.** Authenticated real clan/member
   data and actual notification delivery need separate checks. Simulated browser
   writes are not live Discord or provider verification.

Clan management, CWL staff workflows, and Activity/navigation already have substantial
scoped coverage recorded in `dashboard-interaction-standard.md`. The event calendar
is recurring reference data, not a live special-event feed. Search remains scoped
to the user's accounts/current clans and the authorized family directory.

Return reminders received a focused follow-up: FWA/Main separation, visible batch
controls, shared dates with per-clan overrides, and scheduling/restart safeguards.
See `dashboard-interaction-standard.md` for tests and browser limitations. This does
not complete the other deferred journeys.

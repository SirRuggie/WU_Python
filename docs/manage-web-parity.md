# Manage → web integration audit

Audited 2026-10-15 against current source, not only the older management guide. This is an inventory, not a claim that every feature is implemented on the web.

## Existing web coverage

`cwl_web/manage_bridge.py` and `manage_reminders.py` already share native CWL messages, scheduling, delivery receipts, and the bot-owned publishing queue. CWL assignment rosters in SQLite and native return-ping home-member snapshots in Mongo are intentionally different records. Do not merge them or replace existing signup URLs during this work.

## Feature and permission inventory

| Native workspace | Required web controls | Existing source / store | Native authorization |
|---|---|---|---|
| Roles | Member lookup; select up to 25 roles; add/remove; full paginated role membership | `role_management.py`, `recruit/perms.py`, `utils/role_permissions.py`; Discord | Configured recruiters or Administrator; recheck actor, target and bot hierarchy on every action |
| Recruit Gauntlet | Choose About Us/Strike System/Family Particulars; edit grouped text, artwork, channel; preview, save, load published copy, send/update | `content.py`; `bot_config` content/destination/published keys; MediaStore | Manage Server or Administrator |
| Recruitment Staff Thread | Main/FWA staff notices and talking points, preview/save/reset | `ticket_staff_content.load/save`; `ticket_staff_templates` | Manage Server or Administrator |
| Recruitment Questions | Primary/FWA/Explanation/Keep It Moving variants; grouped text, accent, media; preview/save/reset | `recruit_question_content.load_template/save_template/reset_template`; `bot_config` | Manage Server or Administrator |
| Ticket Settings | Main/FWA channels and recruiter roles; extra viewers; inactivity review and resolved archive timers; setup check; restore entry/console messages | `tickets/settings.py`, `thread_service.py`, `ticket_runtime`; `ticket_setup` config + settings audit | Target-server Administrator |
| Ticket Testing | Open/close isolated window; expiry and cleanup; tester members/roles/admin toggle; own access; Main/FWA test tickets; clear test tickets | `ticket_testing_control.py`, `tickets/testing_service.py`; isolated test namespace | Target-server Administrator controls; allowed testers can open test tickets |
| FWA Bases & Guidance | TH selection; base link; war/active image uploads or URLs; descriptions/guide | `clan/dashboard/fwa_data.py`; `fwa_data` `_id=fwa_config` | FWA Representative role `993015846442127420` |
| FWA War Message Templates | Four variants; grouped text, artwork, accent; preview/reset; submitted edits auto-save | `fwa_war_content.load_template/save_template/reset_template`; `bot_config` | FWA Clan Rep role `769130325460254740` (admin alone is not a bypass) |
| FWA Blacklist | Search/page; add tag/name/reason; remove with confirmation | `utils/fwa_blacklist.py`; `fwa_blacklist` | Server members read; FWA Clan Rep role writes |
| FWA Points Monitor | Status/results; enable/disable; add/remove manually watched extras | `tasks/fwa_points_monitor.py`; `fwa_points` and monitor config | Administrator |
| FWA Sync & Reminders | State/next sync/recent results; enable/disable; destination; fallback BAND link; check feed; test DM | `tasks/band_sync_ical.py`; `fwa_sync_config`, `fwa_sync_events`, `fwa_sync_deliveries` | Administrator |
| BAND Monitor | Runtime poll health/startup recovery/last error; debug enable/disable | `tasks/band_monitor.py` process globals | Administrator |
| War Weights | Minimum TH; TH ranges and emoji; add/edit entries | `utils/war_weight.py`; `fwa_data.database.war_weight_settings` | Administrator |
| CWL | Existing message/reminder controls plus native final-roster publish parity | `cwl_campaign`, `cwl_web_bridge`; bot config + queues | Native Administrator; existing web explicitly granted editor access must remain scoped to CWL |
| CWL Return Pings | Main/FWA/all/individual scope; save current members; replace/clear list; add/remove saved players; away status; send now; FWA start/pause/resume/frequency; failed-only retry | `lazy_cwl_service.py`, `lazy_cwl_store.py`; native saved snapshots | Administrator |

## Integration constraints

- Fetch current Discord membership/permissions for privileged actions. A long-lived web session or CWL editor flag does not authorize all server-management actions. Lock inaccessible sections and enforce the same check server-side.
- Route Mongo collections with `utils.mongo_routes.collection_for`; never assume one database. Existing `_mongo` facade maps only three CWL collections and must be expanded deliberately.
- Reuse template validators and optimistic revisions. Question, war, staff-thread, weight and ticket settings already reject stale saves. Return HTTP 409 with a refresh/review action, retaining the user's draft.
- Use a bot-owned operation bridge for runtime-dependent work. `lazy_cwl_service` depends on initialized bot/Coc/scheduler globals. Importing BAND/Points modules inside the web process gives the web process's globals, not the running bot's status. Never start a second monitor/scheduler to make web buttons work.
- Queue side effects with an operation identifier, actor/guild, validated arguments, current permission recheck, worker readiness, durable receipt and unambiguous result. A stale/expired actor or duplicate click must not send twice.
- Role changes must exclude @everyone, integration roles, roles above the bot/actor, and protected members. Use individual add/remove calls; do not replace a member's entire role list.
- Restore ticket entry/console, publish content, send return pings, test DMs, and test-ticket opening are real Discord effects. Do not exercise them against production during verification.
- Clear test tickets may delete test threads; restrict it to the isolated test namespace and preserve native explicit confirmation. Replacing a return snapshot stops the prior list's pings; bind confirmation to its list ID.
- Return pings expire at 00:00 UTC at the start of the 16th; automatic FWA pings also stop after seven days. Resume must not reset the start time. Main remains manual only.
- Ticket channel editing is constrained by the live entry binding. Native validation intentionally rejects arbitrary intake moves. Do not bypass it in the web UI.
- Media URL validation/upload checks must stay in place. Never let a preview fetch arbitrary private URLs.

## UX contract

One Server Management home with short grouped cards (Recruitment, War tools, Server). Each tool opens a focused page; editors show one selected template/section at a time. Show human labels, current values, destination and save state. Separate Save from Send. Put diagnostics under Details. Searchable Discord member/channel/role pickers need visible names, not mandatory copied IDs. Paginate long lists. Keep Back and current location visible; do not create one page of all settings.

## Existing Manage limitations worth fixing

1. `docs/manage-dashboard.md` omits newer staff-thread/ticket destinations, despite mentioning nine workspaces. Documentation needs reconciliation.
2. Permission rules are distributed between entry routing and action handlers; maintain a shared capability layer to prevent future Discord/web divergence.
3. Points monitor disabling cancels process-local retry tasks. A web Mongo-only flag update cannot claim those tasks were cancelled immediately.
4. BAND debug is runtime-only and resets from environment on restart; label this explicitly or persist intent through the actual bot worker.
5. FWA Bases & Guidance uses direct field updates without the template revision pattern; concurrent edits need field-aware CAS protection in both interfaces.
6. Some onboarding edits and channels are saved through different paths; a single generic JSON editor would obscure publication and unsaved-draft semantics.
7. Full role-member lists depend on Discord member lookup availability; failures must not appear as an empty role.
8. Native return pings and dashboard assignment rosters have different purposes; call the former Return reminders, not a second Roster builder.

## Red-team acceptance cases

- A CWL editor cannot alter roles, tickets, blacklist, or FWA templates by posting directly to an API.
- Revoking a Discord role after page load prevents the next privileged action.
- A cross-origin request, missing CSRF token, foreign guild ID, arbitrary collection/field or unknown action is rejected.
- Concurrent web and Discord saves conflict rather than overwrite; stale retry cannot substitute a replaced list.
- Duplicate or timed-out sends preserve delivery receipts; no blind retry when delivery is uncertain.
- Bot offline means unavailable controls, never success from a web-local module copy.
- Main/FWA test namespace checks hold across open, cleanup and clear operations.
- No user-provided text is interpreted as HTML; user-provided URLs cannot trigger SSRF.
- Production test runs send no messages, modify no roles, and change no settings.

## Web implementation and release — 2026-10-15

Server Management is now in the dashboard sidebar. Pages include member roles, recruitment text/artwork and posting channels, reviewed onboarding publication/update and published-copy loading, ticket settings and isolated testing, FWA templates/bases/weights/blacklist/points/sync, BAND status, existing CWL editors, and per-clan return reminders. Large record lists have name/tag search; pages show one category and one editor at a time. Long editors are split into short parts. Existing signup URLs are unchanged.

Web writes reuse native stores, validators and revision checks. Runtime operations use `utils/manage_web_worker.py` inside the existing bot. Requests carry an actor-bound idempotency key, a reviewed revision, an expiry and a durable receipt; authorization is checked again by the worker. Running requests with an uncertain outcome are not replayed. Existing CWL worker failures do not prevent the independent management poll. `cwl_web` initialization is lazy so imports do not start a second web app or scheduler.

Validation: 130 targeted backend tests and 66 frontend tests passed; desktop and 390px mobile fixture inspected. Live unauthenticated management requests return 401. Live worker heartbeat and all 36 shared content editor reads verified. Test runs did not send production messages, change roles, or alter live ticket settings. Bot and dashboard services remain systemd-managed; rollback copies are under `.local/pre-server-management-20261015-132013` in each checkout.

Research: [Carbon navigation](https://www.carbondesignsystem.com/building-blocks/core/patterns/global-header) for stable navigation; [GOV.UK check answers](https://design-system.service.gov.uk/patterns/check-answers/) for explicit review before sending; [GOV.UK question pages](https://design-system.service.gov.uk/patterns/question-pages/) for focused editing and reuse of existing values.

### Remaining native limitations / parity distinctions

- Return reminders are per clan in the web UI; native bulk scopes and failed-only batch retry remain in Discord. The native return destinations are still hard-coded in `lazy_cwl_service.py`; do not confuse these with editable CWL announcement channels.
- BAND debug intentionally remains runtime-only and resets after restart. Status is the bot's snapshot, not a web-process imitation.
- Some older Discord field editors (notably FWA bases) lack symmetric stale-draft protection. Web edits use actual-field comparisons, but a previously opened native editor may still replace the same field. Consolidating native writes behind the same compare-and-swap helper is recommended.
- Real Discord delivery and role mutations were tested with controlled doubles, not live recipients. Discord outage/permission changes can still reject an action; failures and uncertain results remain visible instead of being reported as success.

## Return workflow completion — 2026-10-15

- Shared Main/FWA return destinations are editable in Server management and read by native `/manage` and scheduled sends. Existing defaults remain unchanged until staff saves.
- Multi-clan actions use durable independent clan jobs, recover interrupted manifests, and show per-clan results. Failed-only retries exclude completed/uncertain jobs and converge across repeated clicks/tabs.
- Reviewed destinations are checked before web/native sends. Native partial/unknown outcomes require checking Discord instead of automatic retry.
- Native FWA edits and Gauntlet channel changes have stale-edit checks. Web FWA, weights, points, sync, and blacklist mutations use the exact reviewed database snapshot.
- Single jobs expire after two minutes; bulk jobs after fifteen minutes, without extending expiry during recovery. Busy workers refresh their heartbeat.
- External delivery cannot be made exactly-once across Discord and Mongo: uncertain outcomes deliberately require inspection. Old native modals must be reopened after restart; rejected image edits may leave unused uploads.

Deployment verified: public asset `index-BDUcQo15.js`; web and bot services active and enabled; worker heartbeat fresh; protected return settings endpoint returns401 without authentication. Live reads of36 content documents and current FWA configuration succeeded. Desktop and390px mobile bulk selector inspected using isolated fake data. No live test messages or settings changes. Rollback files saved under `.local/pre-return-completion-*` in workspace and bot repository.

## Visual message editors — 2026-10-15

Server management moved to Staff tools → Server settings; native Discord-role access remains available independently of CWL grants. Message editors now show safe, structured native previews with original artwork, Markdown, emoji, separators, accent colors and inert buttons/selectors. Draft previews refresh after typing, retain the last valid preview on errors, and never save or send. Mobile uses Edit/Preview tabs; desktop uses adjacent panels. Upload controls name the replaced artwork. CWL reminders and roster announcement edits share the visual renderer. Renderer libraries load only when a preview opens.

Verification:97management backend checks,78frontend checks; all32saved message templates rendered read-only with29native artwork assets. Desktop/mobile reviewed against isolated real default templates. Public release index-DQOvgBKf.js; rollback copies `.local/pre-visual-editors-20261015-140446`. Approximation limits: mention names may display IDs, dynamic placeholders may remain visible, and multi-stage base selection previews show the initial stage. No saved message content or signup links changed during deployment.

## Member selection and plain language — 2026-10-15

Member roles now opens a browsable member list (50 per page) with search, avatars, selected-member context and current role names. Search uses Discord's native member search (100-result cap, narrowing guidance); IDs fetch an exact member. Errors are visible with retry. Selection is draft-only; confirmation names the member and roles. Role choices use existing actor/bot hierarchy checks. Role update requests now accept the dashboard's UUID field; no permissions were weakened.

Copy reviewed across Home, Todo, signups/settings, member roles, message editors, reminders, roster building, publication, results, bonuses, exports and phone reminders. Short labels and direct actions replace repetitive explanations; necessary saving, delivery and data limitations remain. Sources: https://www.gov.uk/service-manual/design/writing-for-user-interfaces and https://design.homeoffice.gov.uk/design-system/patterns/help-users-to/long-lists . Existing native form controls were reused rather than introducing a custom combobox framework.

Verification:86frontend tests and92management backend tests passed. Isolated desktop/mobile browsing and selected-member persistence checked. Live Discord browse/search probes returned200; no roles were changed. Deployed index-DVmXXGby.js, webservice active, unauthenticated member endpoint401. Rollback copies `.local/pre-member-picker-20261015-141526` in workspace and bot repository.

### Dashboard access areas (2026-10-15)
Owners manage six explicit areas under Server settings → Access: CWL management, recruitment messages, tickets, member roles, FWA tools, and server tools (BAND). No area grants access-management rights. The Discord server owner and permanent owner retain all areas. Native Discord `/manage` authorization is unchanged; web authorization no longer inherits general Discord administrator access.

Legacy SQLite grants migrate to CWL-only permissions. Server-management grants are mirrored in the existing Mongo bot_config collection as dashboard-access:<user ID>; the web checks both local and shared grants, and the bot worker rereads shared grants before executing queued work. Revocation removes shared access before local access. Shared-store outages fail closed. Role edits retain the existing actor/bot hierarchy checks. Ticket testing uses a trusted worker context with a fresh scoped check; native interactions retain their original administrator checks.

Validation: 132 backend tests and 87 frontend tests passed; production build served, protected access endpoint returned 401 unauthenticated, dashboard and bot services active after restart. Rollback assets and SQLite snapshot: .local/pre-scoped-access-20261015-142820. No staff grants existed at migration; no users were automatically added.

### Text commands (2026-10-15)
Server settings → Text commands is a separate editor with its own `text_commands` access scope. Owners can delegate it without granting CWL or other server tools. Commands are exact, case-insensitive names beginning with `!`; replies support plain Discord text and an optional embed card with title, description, HTTPS image URL and color. Saving does not send a message. Commands can be enabled, disabled, edited or deleted, with revision checks for stale updates/deletes and `_id` uniqueness for duplicates.

Storage: `text_commands` in the configured bot_config database (currently settings), IDs `<guild>:<command>`, majority writes, no TTL. This database is included in existing whole-database Mongo backups. Bot and web share validation and collection routing through utils/text_commands.py. Guild-only handler ignores bots/webhooks, suppresses mentions and limits each channel/command to one reply per five seconds. It reads the saved definition on invocation; no restart is needed after editing. No scripting, argument substitution, aliases or wildcard triggers. Native /manage is unchanged.

Trigger cleanup (trigger-delete-1): **Delete the trigger message** defaults on for new and existing commands. The bot deletes a plain or recipient trigger only after its reply succeeds. Disabled, unknown, duplicate-suppressed and failed replies never delete the trigger. Turning the setting off keeps it. A missing message is harmless; other deletion failures are logged and exposed as read-only `last_delete_error` status. A later successful deletion clears that status. Status writes are revision-scoped and never resend a reply. The setting participates in save/history but does not invalidate existing interactive reply buttons. The bot needs Manage Messages in the trigger channel. Mocked tests do not establish live Discord delivery or permission behavior.

Validation: 135 backend tests and 88 frontend tests passed; desktop editor and 390px mobile preview checked in an isolated fixture. Public assets verified, command API denied unauthenticated access, bot and web services restarted. No sample commands or test Discord messages were created. Rollback assets: .local/pre-text-commands-20261015-143600.

Member search now matches case-insensitive substrings in server nicknames, global display names and usernames. A complete Discord member directory is fetched in 1,000-member pages and cached for 60 seconds, with concurrent loads serialized and incomplete loads discarded. Matching results are capped at 100 with a narrow-search indication. Exact ID lookup and ordinary browse pagination are unchanged; mutation authorization still reads live Discord data. Verified against 1,476 live members and 18 relevant passing tests (2026-10-15).

### Focused settings navigation (2026-10-15)
The sidebar replaces the generic Server management entry with Members & roles, Applications & tickets, FWA tools, Text commands, Connections, and owner-only Access. Visibility follows existing explicit scopes; Applications & tickets combines the recruitment and tickets scopes without granting either implicitly. CWL return reminders are now under CWL management. Existing editor endpoints, previews, mutation safeguards and native Discord commands are reused unchanged.

Application settings are grouped into Messages, Questions, Staff messages, Channels & access, and Testing. FWA settings separate War messages from Clan tools. Each workspace keeps scoped search and bounded page sizes, and resets editor state when switching areas after the unsaved-change check. Verified with 91 frontend tests, 5 access-boundary tests, production build, and isolated desktop/mobile catalog checks.

### Unified message editing and publishing (2026-10-15)
Public onboarding message editors now include publishing controls on the same screen. Saved previews load on opening; neither editing nor saving is required to preview. Draft previews remain separate from persistence. Publishing uses only saved content and retains existing queue idempotency, revision/live-post checks and native delivery gates. New-post and existing-post destinations are named separately. Posting channels can be changed inline with the existing optimistic destination editor. Apply can update its existing post; new Apply posts remain ticket-setup controlled. Private ticket/question/war templates continue through their normal bot flows.

Duplicate Publish catalog tiles were removed; their API routes remain supported. Copy from Discord and Reset to default live in a closed More options disclosure, with explicit reset confirmation. Pending publishing disables message edits and duplicate publishing controls while status is polled.

Validation: 93 frontend and 102 backend tests passed. Desktop and mobile fixture checks confirmed saved preview before edits, unsaved-edit publishing lock, and recovery grouping. Read-only live checks passed for all five public onboarding messages and their destinations. No live posts, resets or template edits were made during testing. Rollback: .local/pre-message-publish-20261015-145649.

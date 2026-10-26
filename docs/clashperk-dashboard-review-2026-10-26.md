# ClashPerk and ClashKing dashboard review — 26 October 2026

## Purpose and evidence

Read-only review requested by the owner: revisit ClashPerk, inventory its dashboard, and identify useful ideas for Warriors United without adding clutter or changing our workflows.

Reviewed the signed-in Warriors United server at https://app.clashperk.com in the Codex in-app browser. Visited all 19 main navigation destinations, plus representative player/clan detail pages, roster editors, groups, add-player picker, reminder creation forms, and every auto-role section. Inspected rendered page text, controls, and selected screenshots. No settings were saved, accounts linked/unlinked, rosters changed, roles refreshed, or Discord messages sent. Opening the roster add-player picker preselected an eligible player; the dialog was cancelled without adding anyone.

This is a feature and design inventory, **not** an end-to-end validation of ClashPerk's writes, permissions, exports, delivery, or every possible data state. Settings marked off/not set are observations for this server at review time, not judgments that they should be enabled. Counts and status can change. No secrets or full member exports are recorded here.

WU comparison was checked against the current local navigation, Home, Search, activity workspaces, and repository documentation. “Candidate gap” means no equivalent dashboard surface was found in this review; it does not prove the entire bot lacks the capability.

## Main navigation inventory

| Destination | Observed functionality | Relevance to WU |
| --- | --- | --- |
| [Home](https://app.clashperk.com/dashboard) | One selected account; switch account; TH/tag/clan; compact league/base/war/clan summary links; “To do today”; ranked week; current war; upgrade priorities; upcoming events | Their personal Home is distinct from server administration. Consider a small next-action summary; retain our multi-account CWL entry flow. |
| [Search](https://app.clashperk.com/search) | Any player/clan tag lookup; Ctrl/Cmd+K shortcut advertised | Ours searches linked accounts, their clans, and the allowed family directory by name/tag. Global tag lookup is a separate possible expansion, not a missing implementation of our existing scope. |
| [Server Overview](https://app.clashperk.com/overview) | Clan/category counts; open rosters and signup count; account verification count; roster shortcuts; category-filtered clan directory; current activities and personal clans | We already have Staff overview and personal Home. Borrow concise actionable summaries instead of duplicating pages. |
| [Manage Clans](https://app.clashperk.com/clans) | Categories and ordering; search; add/remove clan; category assignment; alias/short name; per-clan command channels; links to configured logs | We have family-clan management. Showing destination health alongside each clan may reduce troubleshooting. |
| [Manage Links](https://app.clashperk.com/links) | Clan selector; linked/unlinked filters and coverage percentage; Discord identity beside player; related-account count; link/unlink actions with visible permission restrictions | A focused staff “missing Discord links” view could help recruitment/readiness. Preserve our provider reconciliation and permission rules. |
| [Rosters](https://app.clashperk.com/rosters) | Selector, capacity, search/sort, war preference, groups, bulk changes, manual additions, CSV, requirements and scheduling | Much overlaps our richer CWL workflow. Details below; do not replace our Main/Lazy model with generic rosters. |
| [Reminders](https://app.clashperk.com/reminders) | War/raid/Clan Games; next run; sent/skipped/failed totals; scheduled/idle/failing filters; clan filter; collapsed run histories; targeted recipients | We already have war, CWL signup/return, and phone reminder workflows. Raid/Clan Games Discord reminders are candidates, not automatic additions. |
| [Clan Logs](https://app.clashperk.com/logs) | Organize by clan, log type, or destination channel; per-type setup; attention list; many event/log types | Useful operational grouping and destination-health pattern. Avoid a second bot sending duplicate logs. |
| [Server Logs](https://app.clashperk.com/server-logs) | Flag alerts, roster changelog, game maintenance notices, welcome/link-account panel | Existing WU audit and publication workflows overlap; distinguish staff history from public Discord posts. |
| [Buttons](https://app.clashperk.com/buttons) | Templates for Link account, Refresh roles, My rosters; text/artwork/colors; preview; post through Discord command | We have message/template previews and private CWL signup fallback. Keep the fallback unadvertised as requested. |
| [Auto-Roles](https://app.clashperk.com/auto-roles) | Membership, verification, TH/BH, leagues, trophies, season-end roles; nickname templates; update delays | Already actively used in ClashPerk. Avoid implementing a competing role automation owner. |
| [Flags](https://app.clashperk.com/flags) | Bans/strikes; search; bulk player tags; reason; expiry | WU strikes/replacements and bonus infractions are purpose-specific. Do not merge them into one ambiguous flag. |
| [Tickets](https://app.clashperk.com/tickets) | Beta ticket-panel setup; Discord posting; shared saved replies | WU tickets/applications already handle our recruitment workflow. Saved replies are an idea to compare carefully, not justification to replace it. |
| [Server Settings](https://app.clashperk.com/server-settings) | Subscription; default embed color; webhook-per-channel limit; delegated manager roles | WU already has scoped access and integration settings. Their save modes vary; ours should stay explicit and consistent. |
| [Tasks](https://app.clashperk.com/tasks) | Remaining work grouped by activity, account identity, deadline and direct destination link; incomplete-check warning/retry | Compact next-action rows are useful. Keep our account filters, selected-account state, and explicit unavailable-data treatment. |
| [Wars](https://app.clashperk.com/wars) | Intended personal-clan live wars/CWL overview | Our recently polished view already borrows this pattern, with staff all-clans scope and better explicit failure handling. See observed inconsistency below. |
| [Events](https://app.clashperk.com/events) | Local-time event list plus separate month calendar with day details | Our list/countdowns/UTC support already exists. Month view is a genuinely separate optional enhancement. |
| [Your Clans](https://app.clashperk.com/my-clans) | Linked-account clans, bookmarks, default command clan; quick member/war/capital/last-seen links | Potential personal clan landing page, preferably as drill-down from existing Home rather than a new required stop. |
| [Accounts](https://app.clashperk.com/accounts) | Linked/verified counts, default account, link/verify/unlink; hero levels and remaining upgrade costs/time | Our Home account inventory exists. Rich player details and an optional preferred account are candidates. Linking ownership must remain explicit. |

## Roster controls inspected

- Roster selector, open status, assigned clan/category, signup capacity, and short policy chips.
- Member rows: TH icon, name/tag, hero total, war preference, clan/role, Discord identity, relative signup time. This is a dense list with shared row separators rather than a large separate card and action buttons per account.
- Search; All/In war/Out filter; sort dropdown; export the shown members as CSV (control inspected, file generation not tested).
- Multi-select and group-select; Change roster, Change group, Remove. Controls are disabled until a selection exists.
- More menu: Clone, Close sign-ups, Refresh players, Delete roster. These actions were not executed.
- Edit form: name, clan, category, roster role, opens/closes, capacity (UI says 5–500), accounts per member, allow concurrent rosters of the same category, allow unlinked players, player-selectable/required group, group prompt, minimum/maximum TH, minimum combined hero levels, default sort, color/image, clan aliases, 3–5 ordered display columns.
- Column choices include row number, TH/icon, player name/tag, Discord name/username/ID, clan, heroes, clan role, war preference, trophies, league.
- Shared groups: Confirmed and Substitute observed. Each has ordering, optional role, pickable status, rename/delete. Their shared scope is clearly explained.
- Add players: pick from a list or paste tags; clan-member source; group destination; used capacity; eligible/all/ineligible tabs; select all eligible; search. In the inspected roster, 49/50 spots were occupied and one eligible player was preselected. We should **not** copy silent preselection for consequential bulk operations.

### WU-specific features to retain

Main/Lazy eligibility and explanations; manual placement locks; war-weight balancing across selected clans; unassign without cancelling signup; outside-family warnings; full comma-formatted clan totals; Discord grouping; compare clans; declaration readiness; working versus published assignments; publication review; season results; Lazy bonus exceptions/infractions and FWA Rep odds; signup/return reminders; existing permission boundaries. Generic roster requirements must not accidentally block Lazy participants with upgrading heroes.

## Reminder controls inspected

Overview shows next reminder, recent sent/skipped/failed counts, destination count, recipient policy, type tabs, status filters, search, and clan filter. Per-reminder run details stay collapsed.

- **War:** multiple clans, channel, hours/minutes before end, regular/CWL/friendly types, message-only/no-member-mentions option, attacks left, clan ranks, THs, linked-only, skip at 100% destruction, message text and role mention selector.
- **Raid:** clans/channel, timing, attack-count threshold, clan ranks, include members with no attacks, linked-only, message.
- **Clan Games:** clans/channel, timing, points threshold, clan ranks, include zero-point members, linked-only, message and role mentions.
- Channel picker can offer an alternative selection path through Discord. Refresh-channel and refresh-role controls are available.

WU implication: reuse our existing shared reminder service and durable delivery receipts for any expansion. Never implement a UI-only scheduler or retry uncertain sends. We already expose reminder history and status; compare the clarity of our overview before proposing another page.

## Logs, automation, and moderation

### Clan log catalog

Observed setup entries:

- Live clan embed.
- Clan achievements; instant/daily/weekly/monthly donations; Clan Games board; last-seen board; Legend daily summary.
- Capital weekly summary, contributions, raids.
- War attacks, CWL attacks, war board, war missed attacks, CWL board, CWL missed attacks, CWL lineup changes, CWL monthly summary.
- Joins/leaves, in-game role changes, name changes, TH upgrades, war preference changes, ranked-league changes.

Three alternate views—by clan, by type, by channel—organize the same records. The attention view explains an issue at its destination, rather than merely displaying a generic error.

### Auto-role sections

- Options: automatic updates, verified-only clan roles, include people without linked accounts, force refresh, addition/removal delays, exceptions to delays.
- Nicknames: different family/non-family templates; player/Discord/TH/clan/alias placeholders; account preference for multi-account users; custom in-game rank labels.
- Clan roles: per-clan Leader/Co-Leader/Elder/Member/Everyone/In war mappings.
- Family/accounts: family, exclusive family, guest, verified, account-linked, family leaders.
- TH and Builder Hall level mappings; optional outside-family accounts.
- League and Builder league mappings; optional outside-family accounts.
- Trophy threshold mappings; end-of-season role for selected clans' Legend players.

### Flags and tickets

Flags form supports Ban/Strike, up to 25 tags separated by spaces/commas, a reason (256-character counter), and expiry in days. No records were created.

Tickets is labeled beta. This server showed no panels or saved replies. A new panel starts with a name and a General type; further panel configuration requires creation, so it was not inspected. Posting requires beta access according to the page. Shared saved replies advertise a 25-reply limit. Do not claim the full ticket conversation/recruitment workflow was tested.

## Player and clan detail inventory

### Player

Inspected a linked player's Overview, Progress, Wars, Legends, and Ranked pages.

- Overview: trophies, war stars, seasonal donation/attack stats, TH progress, rushed indicator, hero levels, estimated remaining time/cost, clan membership history with dates/durations.
- Progress: heroes and equipped items, equipment catalog, pets, troops, siege machines and spells; current/max levels and locked items. A game-data paste control is offered for buildings/traps/walls, which the page says the Clash API does not provide. No game data was uploaded.
- Wars: last 10/25/50 sample; three-star hit rate; attacks/missed attacks; averages; recent result strip; CWL history for last 3/6/all seasons; per-season league/clan/attacks/stars/destruction; links to individual wars. UI explains its hit-rate denominator.
- Legends: historical season total, daily trophy chart, gains/losses, daily rows, best/worst days and season links. The inspected data was from an older season, not a claim of current participation.
- Ranked: current weekly group/rank, promotion/demotion zone, attack/defense counts, trophies, daily chart, battles, standings with expandable full list, previous weeks.

### Clan

Inspected Overview, Members, Wars/Current, Wars/Stats, Wars/CWL, Capital/Raids, Capital/Contributions, Activity/Events, and Activity/Last seen.

- Overview: description, entry requirements, member count, league, record/streak, live war, top donors, TH distribution, bookmark/open-in-game actions.
- Members: player/TH/tag, rank, last seen, trophies, donations given/received, links to profiles.
- Current war: matchup, score/destruction/attack totals; who has attacks left; open opponent bases. History and individual-war destinations are linked.
- War Stats: all/regular/CWL, last 10/25/50 wars, clan hit rate/missed attacks, member table sorting, same-or-higher-TH filter, optional former members.
- CWL: archive surface inspected but this particular clan returned no tracked seasons. Group standings/round controls were not verified on a populated season in this pass.
- Capital: hall/league/trophies/district count; dated raid summary; gold, attacks, destroyed districts, raiders; member contribution to each raid; older-week links.
- Contributions: last-ten-days total, contributor and contribution counts, average, per-player ranking, recent entries.
- Activity: last-30-days events, filtered into upgrades, joins/leaves, clan events.
- Last seen: search, Today/1–7 days/7+ days, sort, 24-hour and 30-day tracked activity counts.

A separate full History page, every unit-detail popover, each historical war/raid, and a populated CWL group were not exhaustively opened. Advertised website features such as army parsing or Sheets integration are not treated as verified dashboard features here.

## Current ClashPerk configuration observations

These are candidates for a separate operational review, not changes made by this task.

- 93 configured clans; two open rosters, one empty test-named roster and one with 49 signups.
- 51 war reminders across nine channels; 40 sent and zero failed/skipped shown for the last three days at first inspection. This is ClashPerk's report, not independently verified Discord delivery.
- Zero raid reminders and zero Clan Games reminders.
- Flag alerts and global roster changelog off; maintenance notices configured; welcome message off.
- No bans or strikes shown; no ticket panels/saved replies shown.
- Automatic roles on. Family/guest, TH2–18, and sampled clan rank roles already configured. Removal delay seven days, addition delay none, force refresh on. Automatic nickname updates off. Builder Hall/league/trophy/end-of-season options inspected were unset.
- Clan Logs reported **25 items needing attention**. Visible examples were archived Lazy CWL threads, with guidance that Discord normally reopens them on the next post. Do not call all 25 delivery failures. Manage Clans also displayed some deleted channel bindings and log destinations; these deserve a focused destination audit if the owner wants cleanup.
- Accounts page displayed 45 linked / one verified at review time. This is a provider-specific snapshot, not a reconciliation against our combined link sources.

## Reliability and design cautions observed

1. Accounts showed “Couldn't load this account's stats” and unavailable season statistics while retaining hero information.
2. Tasks showed only Clan Games tasks with a warning that some checks failed.
3. Wars overview showed “No wars running” even though a clan detail and Home had shown an active war during this session. Cause unknown; this could be a loading/provider inconsistency. It is **not** a reason to weaken our distinction between unknown and empty.
4. On returning to Home, “To do today” displayed “All done” alongside “Some checks didn’t load,” while the account summary still showed two war attacks left. Our completion indicators must never imply completion when checks fail.
5. Reminders later showed a Network Error in one overview area while retaining reminder records.
6. Temporary placeholder counts changed as clan members loaded. Avoid treating intermediate counts as final.
7. Dense rows are attractive, but tiny metadata and icon-only controls can be hard to read. Preserve readable text, focus indication, accessible labels, and usable touch targets.
8. Some settings save immediately; others require Save. Avoid importing that inconsistency into WU.
9. War weight, TH, hero level, and measured attack performance are different signals. None alone proves player skill. FWA/war type and sample size must remain visible in any future performance view.

## Recommended WU priorities

| Priority | Proposal | Why / scope guard |
| --- | --- | --- |
| 1 | Compact player details with optional war/CWL performance and clan history | Helps staff evaluate and helps members understand their accounts. Open from existing rows; don't add all statistics to roster cards. Load on demand, label dates/sample/provider gaps. |
| 2 | Small “What needs attention” / next-action summary | Reuse existing Tasks, signup and assignment status. A few contextual links, not another dashboard full of cards. Personal and staff actions remain separate. |
| 3 | Clearer destination-health summary in existing integrations/reminder views | Surface missing channels, permissions, next run and last outcome. Keep detailed history collapsed; reuse existing owners/receipts. |
| 4 | Clan detail drill-down for members, recent activity and capital history | Useful expansion if members request it. Start with reliable existing data; avoid slowing Home or Tasks with historical requests. |
| 5 | Optional Events month view | Keep current list as default, with correct local/UTC handling. Don't hard-code one CWL battle-end date for every clan. |
| Optional | Raid and Clan Games Discord reminders | Decide whether ClashPerk should remain the sender or WU should own them. Never enable duplicate schedules in both. |
| Later | Rich upgrade planner, ranked/Legend analytics, custom roster columns | Valuable for some users, but larger data/maintenance burden and less directly relevant to CWL operations. |

### Already covered: polish rather than rebuild

CWL signup/assignment flow; roster groups by Discord; compare clans; balancing and locks; member/Discord identity; published assignments; notification preferences; local-time events; scoped staff access; recruitment/tickets; strikes/replacements; message previews; delivery history. Use existing source and standards before adding parallel implementations.

### Design principles worth borrowing

- Put the action, deadline and account identity together.
- Use compact rows and subtle separators for repeated records.
- Keep advanced actions in a clearly labeled menu; keep the next routine action visible.
- Display small status chips, not whole cards full of colored labels.
- Put history, diagnostics and optional statistics behind focused details.
- Use the same player/clan identity consistently across linked pages.
- Preserve Back/Forward context and scope when following a detail link.
- Preserve WU's goldenrod accent and existing status colors; do not copy the competitor's branding wholesale.
- Extend `docs/dashboard-interaction-standard.md` only after an idea is accepted and implemented; this inventory does not change the design contract.

## Review limitations and completion

All main menu destinations were visited. Forms and subpages were inspected read-only using the active owner session; no alternate-role authorization testing was performed. Screenshots of personal Home, the populated roster and log attention view were inspected at the browser's current narrow layout. This was not a multi-device accessibility audit or a performance benchmark. Mutating controls, CSV generation, beta ticket delivery, reminder delivery and historical completeness remain untested.

Only this documentation file was added in the WU repository. No runtime code or deployment changed; therefore no application regression suite or production build was needed for this research task.

---

## ClashKing comparison — appended 26 October 2026

### Dashboard versus mobile app

ClashKing presents separate products with different purposes, rather than two interchangeable dashboards:

- **Web dashboard:** https://dash.clashk.ing — Discord server configuration, clans, rosters, automation, and moderation tools.
- **Mobile app:** player/account companion, with player, clan, war, rankings, upgrade tracking, widgets, and notifications advertised by its official site and store listing.
- **Discord bot:** statistics and operational tools inside Discord.

Sources: [official product overview](https://clashk.ing/), [official Android listing](https://play.google.com/store/apps/details?id=com.clashking.clashkingapp), and [dashboard source repository](https://github.com/ClashKingInc/ClashKingDashboard). Their [API documentation](https://api.clashk.ing/docs) exposes player history/statistics, but an API endpoint does not establish that a corresponding browser screen exists.

The signed-in dashboard menu contained server-management destinations, not a personal player-statistics home. Roster player popovers showed a small summary and an **in-game** profile link. No browser equivalent of the mobile app's full player screens was found in this review. This is a discovery limit, not proof that no unlinked or future web screen exists. Mobile-only features below are documented claims, not hands-on mobile testing.

### Evidence and scope

Reviewed the signed-in Warriors United server in the Codex in-app browser. Visited all 15 destinations in the main menu, plus Account settings; inspected representative forms and roster subpages. Read every Activity Logs category, Family settings, Roles overview/help, reminders overview and creation form, clan configuration, roster members/settings/automations/columns/missing-member/add-member dialogs, two-roster comparison, bonus entry, Links Accounts/Stats, strikes form, all four giveaway form tabs, and base/ticket/embed creation entries. Inspected screenshots of roster members and comparison at the existing browser viewport.

No settings, roles, links, rosters, bans, reminders, or subscriptions were changed. No players were dragged, records created, files uploaded, exports generated, messages sent, or bonus awards assigned. Dialogs were cancelled. This was not a permission penetration test, mutation test, delivery test, or full responsive/accessibility audit. Forms requiring creation of a persistent record before exposing later configuration were left at that boundary.

### Main navigation inventory

| Destination | Observed functionality | WU takeaway |
| --- | --- | --- |
| General Settings | Bot name/avatar/profile; embed color with preview; full-whitelist role; linking API-token requirement; section-specific dashboard access; Discord tenure roles | Keep permission scope explicit. Tenure roles are optional expansion, not an immediate dashboard need. |
| Family Settings | Automatic nickname toggle; separate family/non-family templates with example previews and placeholder help; family, non-family, elder, co-leader, leader roles and add/remove behavior | Preview templates next to the input. Preserve one automation owner so bots do not fight over nicknames/roles. |
| Logs | Server/clan selector; Clan, War, Capital, Player, Countdowns tabs; enabled/off state; hidden configuration for disabled logs; compact destination-issue summary with Review links | Strong pattern for focused configuration and actionable health checks. |
| Roles | Auto-evaluation and nickname toggles; configured-role counts; TH, league, builder hall/league, clan-category tabs; per-role behavior; explanatory help | Counts and selective disclosure reduce clutter. Current server has auto-evaluation off; do not infer it should be enabled. |
| Reminders | Clan filter; War, Capital, Clan Games, Inactivity tabs; time, destination, message and action menu; attention summary | Inactivity reminders are an additional candidate, with conservative data-quality rules. Avoid duplicate senders. |
| Autoboards | Refresh an existing board versus scheduled new posts; usage/limits; All/Refresh/Scheduled-send tabs; target/destination/runtime description | Useful distinction between editing one status message and sending repeated messages. Creation unavailable in this session. |
| Clans | Category-grouped directory, search, clan badge/member count, added-date disclosure, in-game link; category management; member/leader roles, role behavior, abbreviation | Small history disclosures and compact clan context are useful; WU already has family-clan management. |
| Rosters | Groups, search, member count/average TH/distribution; member management; configurable columns; automations/settings; comparison; CWL bonuses | See detailed findings below. Preserve WU-specific CWL rules and publication semantics. |
| Bases | Shared layout library; source messages/engagement history described; add channel, layout link, description and up to four images | Potential extension of existing base/image tools; do not create a second competing library by default. Empty library limited detail testing. |
| Links | Search members, player tags and roles; account filters; expandable Discord-member groups; linked/verified status; add account; CSV/JSON export; separate coverage statistics | A focused missing-link view and coverage summary could aid recruiting. Raw tags remain visible when player details are missing. |
| Bans & Strikes | Search/sort; player popovers; reason/date/server status; remove controls; strikes grouped by player or all records; weight, expiry, evidence URL | Existing WU moderation should remain the source of truth. Evidence and expiry should be easy to inspect without filling the default list with text. |
| Giveaways | Schedule, prize/channel/winner count; message/end-message previews; role restrictions; profile-picture/linked-account requirements; image and entry boosters | Separate feature, low priority unless requested. Do not merge generic giveaway rules into Lazy CWL bonuses. |
| Tickets | Panel list; new-panel name; subsequent buttons/channels configuration described | No existing panels; deeper setup would require creating one and was not tested. Our live ticket/application workflow remains the baseline. |
| Embeds | Reusable templates for ticket panels/buttons; unique identifier then content editing | No existing templates; stopped at initial dialog. Reuse WU's existing message/template tools rather than adding another editor. |
| Support Us | Subscription/perk descriptions, creator links | Not a workflow requirement for WU. Advertised perks do not establish current availability. |
| Account settings (header) | Profile, theme, language, subscription-server selection, AI usage and reset information | Language support is useful for the audience; full translation requires an intentional project rather than isolated translated labels. |

### Logs and reminder details

Clan log choices include joins/leaves, donations, achievements, requirements, description changes and ban alerts. War choices include attack/results logs, a live panel and CWL lineup changes. Capital choices include donations, attacks, live panel and weekly summary. Player choices include clan-role, name, TH, league, troop, spell, hero/equipment and super-troop changes, plus Legend attacks/defenses. Countdown controls describe voice-channel war score and time remaining. These were inspected as controls, not enabled or delivery-tested.

The reminder editor exposes type, time in hours, channel, clan and custom message; War additionally shows Random/Friendly/CWL choices. Inactivity changes the time label to an inactivity duration. The inspected server showed 64 War and 2 Capital reminders, with no Clan Games or Inactivity entries. Those counts are configuration inventory, not proof of successful delivery.

### Roster workflow details

- Overview separates roster selection from editing, with member count, average TH and Clan/Family/External distribution.
- Compare explicitly enters a selection mode, says **2 to 4 rosters**, displays a selection count and enables Compare only when enough are selected. The resulting columns contain TH art, player name/tag, current clan, relationship badge and linkage status. Dragging is advertised as moving a player; no move was attempted.
- Members has Refresh and Add Members, then Members/Automations/Settings tabs. Average hit rate was unavailable for the inspected roster, shown as a dash.
- Player popover supplies tag, current clan, TH, trophies, hero total and an in-game link. This does not offer the rich mobile player history screen.
- Columns can be selected/ordered: TH, name, hit rate and current clan were selected; tag, clan tag, Discord, heroes, trophies and war opt were available. Controls were inspected without changing preferences.
- Add Members supports pasted tags, Discord-server member search and clan-member selection. It began with zero selected.
- Missing Members compares current clan members with the roster, shows coverage, select-all and explicit Add controls. This is different from missing Discord links and must use a clear label in WU.
- Settings include name/group/description, roster type, signup scope/clan, event date with timezone, recurrence by N days or day of month, TH restrictions, minimum signups and maximum accounts per user. A Discord signup form reserves its first component for the account selector and permits up to four additional questions.
- Automations target one roster or its group. Choices: reminder, post roster, open/close signups, clear members, archive or delete roster. The page describes event-relative schedules; this inspected roster's form exposed an exact scheduled date/time. No automation was saved.
- CWL Bonuses starts with clan and stored season. The first automatic clan load showed **ClashKing API transport failed**. Dandelion was then selected and showed no stored seasons at observation time. Allocation rules, populated results and award writes could not be verified and must not be inferred from the page title.

### Observed issues and limits worth recording

1. **12 log destinations needed attention.** Expanded detail described enabled logs pointing to deleted or unavailable threads/forum posts. The list included old Lazy CWL destinations and one Warriors United donation log. Review individually before any cleanup; this task did not repair or disable them.
2. **16 reminders needed attention.** The summary was visible; individual reminder warning reasons were not investigated in depth. Some destination labels fell back to numeric IDs.
3. **Reminder text/time mismatch:** one Warriors United reminder displayed a one-hour trigger but custom text saying eight hours remain. This is a configuration inconsistency to review, not a verified delivery defect.
4. **Roster relationship mismatch:** Dandelion details counted its two accounts as Family, while Compare marked those same accounts External. Do not copy classification without consistent shared logic.
5. **Autoboard availability contradiction:** the page displayed 0/0 capacity and disabled Create while also saying every server includes 10. It referred to registry availability. Actual creation was not possible; cause unverified.
6. **Account/subscription mismatch:** Support advertises a plan, while loaded Account settings said subscriptions were not available yet. No purchase was attempted.
7. **Partial data is real:** Links reported 1,423 of 1,460 server members loaded and some linked accounts lacked player details. Keep coverage denominators honest; never treat a partial fetch as a complete zero result.
8. **Density still varies:** the roster screenshot at the existing viewport used tall, label-heavy cards and large summary blocks. Comparison was more compact. Neither should be copied wholesale into WU's mobile layout.
9. No native mobile inspection, mobile notifications, populated bonus workflow, deep ticket/embed configuration, export correctness, persisted column changes or live delivery was tested.

### Combined ideas list — ClashPerk + ClashKing

This supplements the earlier recommendations; it is a research shortlist, not authorization to build every feature.

| Priority | Idea | Keep it small / protect existing behavior |
| --- | --- | --- |
| First | Richer player details opened on demand | One compact identity header with Discord avatar; optional war/CWL performance and clan history below. Show sample size, season/date and unavailable states. Do not equate war weight with skill. |
| First | Contextual attention summary | Small count and direct Review links for broken destinations, missing links or incomplete setup. Distinguish confirmed failures from unavailable checks. Reuse existing issues/reminder surfaces. |
| First | Clear multi-clan selection and next action | Visible selected count, understandable scope and Preview before applying. Preserve compare clans, locks, current selection, working/published separation and explicit mobile Move. |
| Next | Reconciliation views | Distinguish “not signed up,” “not in assigned clan,” and “missing Discord link.” Reuse existing CWL declaration/readiness tools; do not add three more main menus. |
| Next | Better personal/clan drill-down | Compact activity, war history and capital detail reached from existing Home/Tasks/Wars. One coherent web experience, even though ClashKing splits admin and player apps. |
| Optional | Events month view | Keep the current readable list as default; optional calendar for planning. |
| Optional | Scheduled status boards / inactivity reminders | Only after a concrete staff need; use one delivery owner, receipt tracking, explicit timezone and conservative handling of missing activity data. |
| Later | Upgrade planner, ranked/Legend analytics, generic giveaways, custom roster forms/columns | Useful capabilities, but large scope and not needed to fix current navigation. Avoid making routine CWL work depend on them. |

Do not add a second player dashboard merely because ClashKing separates its products. WU can keep member tasks and staff management clearly separated within its current site, with deeper details available only when needed. Retain goldenrod accents, restrained status fills, readable spacing, short English and accessible touch targets.

---

## ClashKing player app — full recording review, 26 October 2026

### Evidence and limits

Source: owner-supplied **Adobe Express - 1000037064.mp4**, duration **3:13.87**, portrait **886 × 1920**, no audio stream reported. Reviewed sequential extracted frames at three-second intervals across the entire recording (65 frames), rather than the initial fifteen-second overview. Timestamps below are approximate navigation ranges. This covers the visible walkthrough from opening Home through the final Manage Accounts screen; it does not establish behavior of controls the recording does not open, writes, permissions, data accuracy, screen-reader support or native performance. Brief transitions between sampled frames may not be captured. No dashboard implementation was changed.

This updates the earlier statement that mobile had not been inspected: we now have **recording-based visual evidence**, but still no direct control or hands-on testing of the native app. The earlier web-only limitations remain valid.

### Walkthrough inventory

| Approximate time | What the recording shows | Ideas / distinctions for WU |
| --- | --- | --- |
| 0:00–0:09 | Home: player/clan search, refresh age, rotating event banner, To-do list, Ranked League and Upgrade Tracker cards. Each card has recognizable artwork, concise statistics and a chevron. Persistent Home / Players / Clans / War bottom navigation. | Make frequent destinations reachable with one tap. Home should answer what needs attention without becoming a wall of settings. Use game artwork for recognition, paired with text. |
| 0:09–0:13; 2:48–2:51 | To-do detail: one-account scope, remaining/completed count, progress ring, account search/filter, war attacks, Clan Games and Pass progress. The account has an untracked-data warning. | Account scope and freshness must be obvious. Our many-account users need all linked accounts readily available; do not infer that this app's one-account view is a limitation or its cause. Keep missing data separate from zero progress. |
| 0:15–0:18; 2:54–3:03 | Ranked League: player header, Season/History tabs, Details/Rankings switch, dated current period, group rank, attack/defense breakdown. History shows prior/best summaries and an end-of-season trophy graph. | Attractive optional player detail, not necessary for CWL signup. Date and sample context matter more than a decorative score. |
| 0:18–0:27 | Upgrade Tracker: selected player, update timestamp, completion metrics, searchable categories with small artwork and percentage badges. Mode selector exposes Home Village, Builder Base, Calendar, Plan and Collection. | One stable identity header with scoped detail beneath it. Advanced modes can live inside a detail view rather than adding more main navigation. |
| 0:27–0:33 | Upgrade Calendar: date range with previous/next; separate builder-slot, laboratory and pet timelines; individual upgrade blocks show image, level and duration. | A substantial planning feature, not a cosmetic improvement. The timeline concept is useful, but requires accurate editable planning data and clear estimated versus actual dates. |
| 0:33–0:42 | Plan: loot outlook, idle builders, seven-/thirty-day upcoming totals, Builders/Laboratory/Pets/Walls filters, status dropdown and dated upgrade rows with costs/durations. | Good summary-to-detail hierarchy. Do not promise a planner using live API data until data sources and manual update requirements are established. |
| 0:42–0:45 | Collection: searchable Skins, Sceneries, Decorations, Obstacles and House parts, each with owned/total and completion percentage. | Low-priority expansion unrelated to WU's main workflows. Borrow compact category rows, not the entire collection system. |
| 0:48–0:57 | Players: Linked/Bookmarked switch; name/tag, TH art, current clan, league/score, last-active status; Options disclosure. Bookmarked empty state explains how to populate it. | Compact account identity and useful empty-state instruction. A preferred/bookmarked account could be optional; it must not hide the rest of a user's linked accounts. |
| 0:57–1:00; 1:48–1:51 | Clans: badge/name, user's account count, membership count, league and join policy; row chevron. | Showing “your accounts in this clan” gives a reason for each clan being listed. Keep current membership and historical CWL participation distinct. |
| 1:00–1:15 | Clan detail: illustrated header with badge, tag/copy icon, league, membership/requirements. Members section includes search, sort and donation/average-TH summary above compact member rows. | Richer clan details can be reached from existing Home/Wars, without another mandatory navigation step. Keep the header short enough that useful rows remain visible. |
| Around 1:06–1:09 | Capital detail: Summary/Members/Breakdown/History tabs; dated raid weekend, ended status, rewards, raids completed, districts, attacks and loot. Only Summary is shown populated. | Good example of separating a short overview from deeper statistics. Other tab contents are unverified. |
| 1:15–1:30 | Clan section selector moves through War Log, Join/Leave and War Stats. Join/Leave lists player, direction and relative time. War Stats loads player summaries with war-count/star filters, total attacks and average results. | History and performance belong behind detail controls. Show sample size and period. Never replace war weight or manual judgment with a simplistic skill rating. |
| 1:30–1:48 | Clan Rankings, CWL History, Leaderboard History, Legend History, Records & History. Rankings have season and global/local ranks; Legends shows dated player results; records show best points/streak and dated clan-level changes. CWL and leaderboard history display empty states. | Distinguish no stored history from “never participated.” These are optional clan research tools, not required signup screens. |
| 1:51–2:00 | War overview: compact paired badges, score/destruction, battle/preparation countdown and chips for the user's accounts. Scrolling also reveals private-war-log and not-in-war clan cards. | Borrow the compact matchup and personal relevance; **do not copy private/no-war cards** into WU's normal war list, contrary to the owner's established preference. |
| 2:00–2:15 | War detail: matchup stays above Statistics / Events / Teams. Statistics compares stars, destruction, attacks and star distribution. Events provides searchable attack rows with attacker/defender, stars and destruction. Teams has own/opponent selector, search, map-position sort, player attacks and defense slots. | Strong candidate for deeper Wars drill-down: Overview / Attacks / Lineups in short plain English. Keep the overview fast and load deeper data only when opened. |
| 2:15–2:24 | Secondary drawer: Posts, Rankings, Stats, Calculators, To-do list, Ranked League, Upgrade Tracker, Game Assets, Manage Accounts and Settings. Rankings shows Players/Clans, village and location controls with ranked rows. | Bottom navigation handles frequent work; the drawer holds occasional tools. Avoid copying every menu item. Posts and Settings contents are not demonstrated. |
| 2:24–2:37 | Stats page: Battle/World and Meta/Armies/Item controls; content remains skeleton placeholders in the sampled interval. | Only navigation is observed, not working analytics. Skeletons must resolve into content or an honest recoverable state. |
| 2:39–2:45 | Calculators: Damage tab shows selectable levels and quantities for attack components; Farm goal has building selection and loot input with explanatory bonus assumptions. | Separate optional utilities. No completed calculation or correctness validation is shown. Do not make these prerequisites for existing workflows. |
| 3:06–3:09 | Game Assets opens a folder-oriented page that remains in a loading state before leaving. | No asset catalog or asset licensing was verified. Do not copy ClashKing-hosted assets on the assumption they are reusable. |
| 3:12–end | Manage Accounts: player-tag add field, list with verification status, reorder handles and delete icons; explanatory text says accounts can be added, removed, reordered and verified with a token. | Separate ownership management from routine viewing. Deletes need explicit safe handling; reorder needs a keyboard/mobile alternative. No mutation flow is demonstrated. |

### What makes this app feel more coherent

1. **Consistent navigation:** the same four bottom destinations remain identifiable on main pages. Detail screens use a predictable Back control. Staff tools are not mixed into the player's main task area.
2. **Recognition before reading:** TH images, clan badges and event illustrations identify objects before users read numbers. A small amount of art does more work than another explanation paragraph.
3. **Clear visual order:** identity first, primary status second, then selectable details. Most rows use one obvious destination rather than several competing outlined buttons.
4. **Repeated row patterns:** icon, short name, quiet metadata and a trailing value/action. Shared patterns make new sections easier to scan.
5. **Details stay local:** clan modes and war tabs change the content below the current identity. The user remains aware of which clan/player/war is open.
6. **Information has context:** refresh age, selected period, player count and account chips connect numbers to the object/time they describe. These patterns are worth retaining even when upstream data is unavailable.

These are visual/interaction observations from the recording, not proof of usability across all users.

### Patterns to adapt carefully or avoid

- Large illustrated headers occupy a substantial fraction of the phone screen. Use a restrained banner or small illustration and compact identity header in WU, not a tall header on every page.
- Rotating event banners can hide important deadlines. Keep the next important deadline/action stationary; do not make essential information dependent on waiting for a carousel.
- Low-contrast red text, tiny metadata and icon-only actions are visible in places. Retain our goldenrod accent, readable contrast, text labels and 44px target standard. Small-looking controls can still have generous hit areas.
- Some views show zero statistics during loading before values appear. Never present loading placeholders as authoritative zero results; retain known data with a stale marker where safe.
- The untracked-player warning is visibly truncated. Important limitations must remain readable without guessing the missing text.
- CWL empty-state copy claims no participation. A screen alone cannot establish whether historical coverage is complete. WU should say “No recorded CWL history” unless it can support the stronger claim.
- Stats stays in loading placeholders for roughly the visible 2:24–2:37 interval; Game Assets is left before completion. The clip cannot establish the cause or eventual outcome. Do not infer that skeletons alone solve slow loading.
- Private war logs and not-in-war cards clutter the demonstrated War list. Preserve our existing rule to omit them from the normal member overview; retain appropriate staff visibility and honest partial-data feedback.
- The recording shows an old Upgrade Tracker update timestamp. Manual/imported planning data must remain clearly distinguished from fresh game status.
- Bottom navigation must not cover controls, clash with Android browser/PWA safe areas, obscure keyboard focus or create a second inconsistent route model. It needs narrow, short-screen, keyboard and Back/Forward testing before shipping.

### Updated shortlist for WU after the mobile recording

| Order | Proposal | Scope boundary / acceptance goal |
| --- | --- | --- |
| 1 | Keep the compact mobile Menu; simplify its contents | Owner decision: no bottom navigation, to preserve screen space. Member destinations remain visible in the drawer; permission-filtered staff tools sit in one expandable group. Preserve existing routes and signup handling. |
| 2 | Improve Home's visual hierarchy | Small recognizable illustrations/badges, a concise next-action summary and compact account-aware cards. Keep goldenrod; do not add a carousel or fetch heavy statistics just to render Home. |
| 3 | Add richer details to existing player/clan entry points | Compact identity, Discord information and freshness first; war/CWL results and clan history on demand. Clear unavailable/partial states, no blocking on unrelated upstream calls. |
| 4 | Extend Wars detail only where useful | A compact matchup plus optional attack log and lineups. Preserve current “my clans” default, staff all-clans scope, personal attacks and private-war-log exclusions. |
| 5 | Consolidate attention and missing-link checks | Carry forward the web review's small actionable warnings. Do not spread duplicate warning cards across every page. |
| Later | Capital history, rankings, upgrade planning, calculators, collections and social features | Separate opt-in projects after member navigation is proven. No automatic feature parity project. |

### Review completion and implementation boundary

Documented every section reached in the supplied recording, including the final account-management screen, with timestamp ranges and uncertainty. Compared the patterns with `docs/dashboard-interaction-standard.md` and the owner's established preferences: less clutter, non-native-English clarity, goldenrod accents, full multi-account support, preserved CWL comparison/publication and correct partial-data handling.

The recording is sufficient to inform a focused member-experience prototype. It is not evidence that a redesign has been built, tested, deployed or proven to preserve workflows. Any implementation must still run the applicable regression/build checks and verify real rendered layouts at 320px, 390px and desktop, including failure states and navigation restoration.


## Home/menu implementation review — October 26

The owner selected the existing collapsible mobile Menu rather than a permanent bottom bar. Home now emphasizes the next CWL action, with a compact Tasks entry and quieter Search/Wars/Events links. Staff destinations remain available inside an expandable Staff tools group, automatically expanded on a staff route. No signup persistence, API routes, authorization, roster logic, or schema was changed.

Sol built Home, Luna built the menu, and a separate Sol review checked failure states, permission filtering, guarded navigation, stale snapshots, and signup handoff. Parent browser checks used a standalone localhost fixture with fictional accounts and rejected all API mutations. Checked 320px, 390px, and 1280px layouts; long names; member, owner, and limited-staff menus; keyboard staff expansion, focus containment, Escape/trigger focus restoration; roster navigation with active group expansion; search/no matches/reset; pagination; empty/closed/error/partial account states; and selecting an account through the existing Lazy signup review without submission. A closed-season instruction inconsistency found in browser review was corrected.

Validation: 83 frontend test files / 352 tests passed; TypeScript and isolated Vite production build passed; backend navigation regressions 2 passed; diff whitespace check passed. These checks do not prove live upstream availability, real-phone behavior, or a live signup write. No live signup or notification was sent.

Build safety incident: the default frontend build targets the same dist directory used by the local live web service. One builder ran it during validation, briefly exposing candidate assets. The parent restored the exact committed baseline assets and verified the original served index before continuing. Candidate assets were retained to avoid breaking already-open sessions. No backend/storage changes or migrations occurred. It is unknown whether a user loaded the brief candidate version. All subsequent validation builds used /tmp/wu-home-menu-build.


Release: implementation revision `3e32fec` was pushed to origin/main. The verified isolated frontend was installed by copying assets first and atomically replacing index.html; older hashed assets were retained for open sessions. The web service remained active without a restart. Local HTTP checks matched entry and Home chunks to the build. The public browser rendered the sign-in page and referenced `index-C8CxfDKP.js`. A direct non-browser public request returned 403, so public verification used the browser. Authenticated live signup submission was intentionally not performed.

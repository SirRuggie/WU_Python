# STE155 wording review

Implementation sweep of the owner-approved 86 items. Validation is incomplete until the full backend, required war check, exact-artifact boot, layout review and final review below are recorded. No production change is made by this document.

| Item | Implementation | Current source locations |
| --- | --- | --- |
| STE-1 | Done: Contractions: "Couldn't / couldn’t" · text. | `web/cwl/src/BaseBankCard.tsx:41`, `web/cwl/src/BaseBank.tsx:65`, `web/cwl/src/useComparisonLocations.ts:52`, `web/cwl/src/useDeclarationData.ts:109`, `web/cwl/src/useDeclarationExtras.ts:64`, `web/cwl/src/MemberAssignments.tsx:131`, `web/cwl/src/App.tsx:955`, `web/cwl/src/DashboardHome.tsx:562`, `web/cwl/src/RosterFillerCheckbox.tsx:75`, `web/cwl/src/SignupActivity.tsx:53`, `web/cwl/src/PublicationChanges.tsx:64`, `web/cwl/src/StaffDetailsPanel.tsx:144`, `web/cwl/src/DeclarationExtras.tsx:41`, `web/cwl/src/useSignupAction.tsx:131`, `web/cwl/src/ArrivalCheck.tsx:481`, `web/cwl/src/ArrivalCheck.tsx:490`, `web/cwl/src/AnnouncementSequenceStatus.tsx:240`, `web/cwl/src/RouteLoadBoundary.tsx:27`, `web/cwl/src/TodoActivityStatus.tsx:16`, `web/cwl/src/DiscordMessagePreview.tsx:16`, `cwl_web/app.py:547`, `cwl_web/providers.py:351` |
| STE-2 | Done: Contractions: can't, won't, don't, doesn't, isn't, hasn't, wasn't, haven't · text. | `web/cwl/src/seasonFlow.ts:29`, `web/cwl/src/seasonFlow.ts:31`, `web/cwl/src/publicationStatus.ts:26`, `web/cwl/src/ManageBridgeWorkspace.tsx:586`, `web/cwl/src/ClanRosterImages.tsx:359`, `web/cwl/src/ClanRosterImages.tsx:362`, `web/cwl/src/ClanRosterImages.tsx:365`, `web/cwl/src/HostingClanControls.tsx:338`, `web/cwl/src/ClanSettings.tsx:443`, `web/cwl/src/clanSettingsModel.ts:21`, `web/cwl/src/WeightQueue.tsx:127`, `web/cwl/src/WeightQueue.tsx:195`, `web/cwl/src/RosterPlayerDialog.tsx:129`, `web/cwl/src/RosterPlayerDialog.tsx:358`, `web/cwl/src/StrikeActivityDetail.tsx:75`, `web/cwl/src/DeclarationClan.tsx:132`, `web/cwl/src/App.tsx:194`, `web/cwl/src/PushReminders.tsx:401`, `web/cwl/src/MemberAssignments.tsx:146`, `web/cwl/src/MemberSignupStatus.tsx:137`, `web/cwl/src/participation.ts:160`, `web/cwl/src/SignupActivity.tsx:173`, `web/cwl/src/memberTimezones/NicknameReview.tsx:11` |
| STE-3 | Done: Contractions with a pronoun: you'll, you're, we've, we'll · text. | `web/cwl/src/MemberSignupStatus.tsx:50`, `web/cwl/src/MemberSignupStatus.tsx:53`, `web/cwl/src/MemberSignupStatus.tsx:58`, `web/cwl/src/MemberSignupStatus.tsx:60`, `web/cwl/src/MemberSignupStatus.tsx:135`, `web/cwl/src/SignupWalkthrough.tsx:41`, `web/cwl/src/StaffTagSignup.tsx:112` |
| STE-4 | Done: "Refresh" and "Reload" mean the same thing · button. | `web/cwl/src/StaffSignupControls.tsx:443`, `web/cwl/src/TestChannelDefault.tsx:29`, `web/cwl/src/DeclarationPingPanel.tsx:311`, `web/cwl/src/PushReminders.tsx:229`, `web/cwl/src/ServerManagement.tsx:697`, `web/cwl/src/ManageBridgeWorkspace.tsx:999`, `web/cwl/src/StrikesWorkspace.tsx:963`, `web/cwl/src/ModerationSettings.tsx:299`, `web/cwl/src/TextCommands.tsx:330`, `web/cwl/src/RouteLoadBoundary.tsx:27` |
| STE-5 | Done: "Choose", "Select" and "Pick" for the same action · text. | `web/cwl/src/App.tsx:1079`, `web/cwl/src/StaffSignupControls.tsx:347`, `web/cwl/src/StaffSignupControls.tsx:431`, `web/cwl/src/PushReminders.tsx:434`, `web/cwl/src/DashboardHome.tsx:697`, `web/cwl/src/SavedSignups.tsx:299`, `cwl_web/app.py:1268`, `cwl_web/app.py:1617` |
| STE-6 | Done: "Signup", "Sign-up" and "Sign up" · text. | `utils/cwl_campaign.py:311`, `utils/cwl_campaign.py:314` |
| STE-7 | Done: "dashboard" and "website" / "site" for the same thing · text. | `web/cwl/src/PushPermissionHelp.tsx:67`, `web/cwl/src/webPush.ts:5`, `web/cwl/src/ReminderWorkspace.tsx:539`, `web/cwl/src/ReminderWorkspace.tsx:877` |
| STE-8 | Skipped: keep & in section names. | `web/cwl/src/RosterHeader.tsx:60`, `web/cwl/src/RosterWorkspace.tsx:1011`, `web/cwl/src/RosterWorkspace.tsx:1212`, `web/cwl/src/ServerSettingsIndex.tsx:15`, `web/cwl/src/App.tsx:943`, `web/cwl/src/SidebarNavigation.tsx:239`, `web/cwl/src/StrikesWorkspace.tsx:892`, `web/cwl/src/SidebarNavigation.tsx:189`, `web/cwl/src/ParticipationWorkspace.tsx:429`, `web/cwl/src/applicationSteps.ts:20`, `web/cwl/src/applicationSteps.ts:21`, `web/cwl/src/managementAreas.ts:62`, `web/cwl/src/weightTrial/WeightTrial.tsx:770`, `web/cwl/src/ReturnReminderOverview.tsx:557`, `web/cwl/src/MemberDetailActivity.tsx:50`, `web/cwl/src/PushReminders.tsx:481`, `web/cwl/src/ReminderWorkspace.tsx:846`, `web/cwl/src/ExportWorkspace.tsx:587`, `web/cwl/src/RosterPlayerDialog.tsx:387`, `web/cwl/src/clanManagement/ReminderOverview.tsx:250`, `web/cwl/src/activity/WarsWorkspace.tsx:49` |
| STE-9 | Done: Semicolon joins two ideas in one sentence · text. | `web/cwl/src/CompareFilterPanel.tsx:61`, `web/cwl/src/DashboardIssues.tsx:56`, `web/cwl/src/activity/WarDetailPanel.tsx:117`, `web/cwl/src/activity/WarDetailPanel.tsx:123`, `web/cwl/src/activity/EventsWorkspace.tsx:33`, `web/cwl/src/ReminderWorkspace.tsx:1070`, `web/cwl/src/DeclarationPingPanel.tsx:419` |
| STE-10 | Done: "Try again shortly" and "Check back soon" are vague time words · text. | `web/cwl/src/api.ts:148`, `web/cwl/src/activity/WarDetailPanel.tsx:55`, `web/cwl/src/BaseBank.tsx:102`, `web/cwl/src/MemberSignupStatus.tsx:46`, `cwl_web/providers.py:351`, `cwl_web/manage_delivery.py:136`, `cwl_web/bonus_raffle.py:329` |
| STE-11 | Done: Idioms and phrasal verbs: "get started", "coming soon", "catch up" · text. | `web/cwl/src/AccessSettings.tsx:299`, `web/cwl/src/clanManagement/ClanDirectory.tsx:122`, `web/cwl/src/BaseBankCard.tsx:68`, `web/cwl/src/BaseBankCard.tsx:87`, `web/cwl/src/TodoWorkspace.tsx:107` |
| STE-12 | Done: Owner wording for Clan size and full-clan errors. | `web/cwl/src/RosterAccountCard.tsx:145`, `cwl_web/app.py:1201`, `cwl_web/app.py:1455` |
| STE-13 | Done: Strict max > min in Clan settings/API; filters allow max = min. Wording follows the existing comparison. | `web/cwl/src/ClanSettings.tsx:295`, `web/cwl/src/RosterFilters.tsx:70`, `cwl_web/app.py:1207` |
| STE-14 | Done: Same 2,000-character wording in editor, publication gate and API. | `web/cwl/src/publicationBlockingReason.ts:27`, `web/cwl/src/JoiningInstructionsEditor.tsx:44`, `cwl_web/app.py:1830` |
| STE-15 | Done: Select in current defaults/UI. Frozen legacy/version127 text remains exact per 541. | `utils/cwl_campaign.py:42`, `utils/cwl_campaign.py:286`, `utils/cwl_campaign.py:292`, `utils/cwl_campaign.py:216`, `web/cwl/src/PushPermissionHelp.tsx:45` |
| STE-16 | Done: Signup saved message · help line. | `web/cwl/src/MemberSignupStatus.tsx:177`, `web/cwl/src/DashboardHome.tsx:107` |
| STE-17 | Done: Signup completion card · help line. | `web/cwl/src/App.tsx:1064` |
| STE-18 | Done: Signup paused while links are checked · status text. | `web/cwl/src/App.tsx:1059` |
| STE-19 | Done: Move or withdraw a signup · help line. | `web/cwl/src/DashboardHome.tsx:960` |
| STE-20 | Done: Choose pool then review · help line. | `web/cwl/src/DashboardHome.tsx:114` |
| STE-21 | Done: Weight source line · help line. | `web/cwl/src/DashboardHome.tsx:835` |
| STE-22 | Done: Events: schedule note · help line. | `web/cwl/src/activity/EventsWorkspace.tsx:33` |
| STE-23 | Done: Events: signup window and schedule note · help line. | `web/cwl/src/activity/TaskEventTimer.tsx:15`, `web/cwl/src/activity/TaskEventTimer.tsx:18` |
| STE-24 | Done: War details error · error text. | `web/cwl/src/activity/WarDetailPanel.tsx:58` |
| STE-25 | Done: Todo: activity needs in-game check · help line. | `web/cwl/src/todo.ts:12` |
| STE-26 | Done: Todo: remembered selection note · help line. | `web/cwl/src/TodoWorkspace.tsx:107` |
| STE-27 | Done: Wars: refresh note · help line. | `web/cwl/src/activity/WarsWorkspace.tsx:79` |
| STE-28 | Done: Push permission help: Android steps · help list. | `web/cwl/src/PushPermissionHelp.tsx:15`, `web/cwl/src/PushPermissionHelp.tsx:31`, `web/cwl/src/PushPermissionHelp.tsx:40` |
| STE-29 | Done: Push permission help: footer note · help line. | `web/cwl/src/PushPermissionHelp.tsx:67` |
| STE-30 | Done: Notification errors · error text. | `web/cwl/src/webPush.ts:5`, `web/cwl/src/webPush.ts:30`, `web/cwl/src/webPush.ts:21` |
| STE-31 | Done: Account link help · help list. | `web/cwl/src/AccountLinkHelp.tsx:18` |
| STE-32 | Done: Pool change warning · confirm text. | `web/cwl/src/PoolChangeDialog.tsx:55` |
| STE-33 | Done: Saved signups: change note · help line. | `web/cwl/src/SavedSignups.tsx:211` |
| STE-34 | Done: Error screen · error text. | `web/cwl/src/RouteLoadBoundary.tsx:27` |
| STE-35 | Done: Dynamic browser-reference text updated; event.detail stays textContent. | `web/cwl/src/main.tsx:27` |
| STE-36 | Done: FWA dialog (owner voice - decide) · dialog text. | `web/cwl/src/FwaSignupDialog.tsx:31`, `web/cwl/src/FwaSignupDialog.tsx:37` |
| STE-37 | Done: Base bank: choose Town Hall · help line. | `web/cwl/src/BaseBank.tsx:93` |
| STE-38 | Done: Publish blocked reasons ("before publishing") · button hint. | `web/cwl/src/publicationBlockingReason.ts:16`, `web/cwl/src/publicationBlockingReason.ts:20`, `web/cwl/src/publicationBlockingReason.ts:23`, `web/cwl/src/publicationBlockingReason.ts:25`, `web/cwl/src/publicationBlockingReason.ts:34`, `web/cwl/src/PublicationWorkspace.tsx:232` |
| STE-39 | Done: Hide roster body text · confirm text. | `web/cwl/src/PublicationWorkspace.tsx:439` |
| STE-40 | Done: Bonus: eligibility rule (cooldown) · help text. | `web/cwl/src/BonusWorkspace.tsx:951`, `web/cwl/src/BonusCandidateReview.tsx:82`, `web/cwl/src/BonusCandidateReview.tsx:83`, `web/cwl/src/bonusRaffle.ts:66` |
| STE-41 | Done: Bonus: FWA Rep odds · help text. | `web/cwl/src/BonusWorkspace.tsx:1042` |
| STE-42 | Done: Bonus: reconcile / retain wording · status text. | `web/cwl/src/BonusWorkspace.tsx:1172`, `web/cwl/src/BonusWorkspace.tsx:1289`, `web/cwl/src/BonusWorkspace.tsx:1309`, `web/cwl/src/BonusWorkspace.tsx:1257` |
| STE-43 | Done: Bonus: announcement delivery · help text. | `web/cwl/src/BonusAnnouncement.tsx:38` |
| STE-44 | Done: Rate-limit progress keeps retryAfter numeric value; marked-post confirmation says Discord is unchanged. | `web/cwl/src/ClanRosterImages.tsx:251`, `web/cwl/src/rosterImagePosting.ts:279`, `web/cwl/src/ClanRosterImages.tsx:359` |
| STE-45 | Done: Announcement resend text · confirm text. | `web/cwl/src/AnnouncementSendReview.tsx:93`, `web/cwl/src/AnnouncementFullTest.tsx:160` |
| STE-46 | Done: Manage CWL settings binding · status text. | `web/cwl/src/ManageBridgeWorkspace.tsx:327`, `web/cwl/src/ManageBridgeWorkspace.tsx:904` |
| STE-47 | Done: Roster account card: kept unplaced · label. | `web/cwl/src/RosterAccountCard.tsx:149` |
| STE-48 | Done: Selection limit · help text. | `web/cwl/src/RosterSelectionBar.tsx:74` |
| STE-49 | Done: Both dynamic counts and zero-result copy use players not on the roster; counts unchanged. | `web/cwl/src/ArrivalCheck.tsx:516`, `web/cwl/src/ArrivalCheck.tsx:522`, `web/cwl/src/DeclarationExtras.tsx:67` |
| STE-50 | Done: Arrival check: save may have reached the server · error text. | `web/cwl/src/ArrivalCheck.tsx:407` |
| STE-51 | Done: Visible message wording only; chunks/chunk transport fields and uncertain-delivery rules unchanged. | `web/cwl/src/DeclarationPingPanel.tsx:231`, `web/cwl/src/DeclarationPingPanel.tsx:409`, `web/cwl/src/DeclarationPingReview.tsx:25`, `web/cwl/src/DeclarationPingReview.tsx:55` |
| STE-52 | Done: Reminder settings: long explanation · help text. | `web/cwl/src/clanManagement/ReminderOverview.tsx:398`, `web/cwl/src/clanManagement/ReminderOverview.tsx:392`, `web/cwl/src/clanManagement/ReminderOverview.tsx:124` |
| STE-53 | Done: Participation / correction wording · label. | `web/cwl/src/ParticipationRecord.tsx:211`, `web/cwl/src/ParticipationRecord.tsx:358` |
| STE-54 | Done: Saved channel missing from list · help text. | `web/cwl/src/clanManagement/reminderOverview.ts:46`, `web/cwl/src/clanManagement/reminderOverview.ts:34` |
| STE-55 | Done: Access: how grants combine · help text. | `web/cwl/src/AccessSettings.tsx:586`, `web/cwl/src/AccessSettings.tsx:624` |
| STE-56 | Done: Strike help: "goes away by itself" · help line. | `web/cwl/src/strikeHelp.ts:39` |
| STE-57 | Done: Strike tab hint: "predicate" · tooltip. | `web/cwl/src/StrikeActivityRoster.tsx:417` |
| STE-58 | Done: Strike activity: "seeded" · tooltip. | `web/cwl/src/StrikeActivityRows.tsx:189` |
| STE-59 | Done: Strike review hold · help text. | `web/cwl/src/StrikeReviewResolution.tsx:117`, `web/cwl/src/StrikeReviewResolution.tsx:135` |
| STE-60 | Skipped: keep Chopping Block. | `web/cwl/src/StrikeBulkMark.tsx:143`, `web/cwl/src/StrikeReplacementRow.tsx:9`, `web/cwl/src/StrikeActivityRows.tsx:32`, `web/cwl/src/strikeActivityFilters.ts:496`, `web/cwl/src/StrikeActivityFiltersPanel.tsx:161` |
| STE-61 | Skipped: keep Ghosted, Flew the Coop and Not loyal to WU. | `web/cwl/src/TicketBrowser.tsx:193`, `web/cwl/src/TicketBrowser.tsx:194`, `web/cwl/src/TicketBrowser.tsx:195` |
| STE-62 | Done: Dashboard status: "historical" · help text. | `web/cwl/src/BandStatusSummary.tsx:106` |
| STE-63 | Done: Visitor counts note · help line. | `web/cwl/src/VisitorSummary.tsx:47` |
| STE-64 | Done: Issues page notes · help text. | `web/cwl/src/DashboardIssues.tsx:82`, `web/cwl/src/DashboardIssues.tsx:81` |
| STE-65 | Done: War reminders: how reminders work · help text. | `web/cwl/src/warReminders/DeliveryHistory.tsx:89`, `web/cwl/src/warReminders/TestPanel.tsx:217` |
| STE-66 | Done: War reminder time example · placeholder. | `web/cwl/src/warReminders/ScheduleEditor.tsx:118` |
| STE-67 | Done: Return reminders: archive and retained · help text. | `web/cwl/src/returns/ReturnBatch.tsx:355`, `web/cwl/src/returns/ReturnBatch.tsx:326` |
| STE-68 | Done: Reminder paused / resume receipts · status text. | `web/cwl/src/ReminderWorkspace.tsx:1027` |
| STE-69 | Done: Current version128 defaults only. Saved version127/unversioned copy remains exact. | `utils/cwl_campaign.py:286` |
| STE-70 | Done: Current version128 defaults only. Same role/channel placeholders. | `utils/cwl_campaign.py:292` |
| STE-71 | Done: Current version128 defaults only. Per-version check lines preserve stored127 normalization. | `utils/cwl_campaign.py:301` |
| STE-72 | Done: Current version128 help/check lines; old127 and legacy constants remain exact. | `utils/cwl_campaign.py:52–54`, `utils/cwl_campaign.py:131–145` |
| STE-73 | Done: Roster closing message · message body. | `utils/cwl_roster_messages.py:28` |
| STE-74 | Done: Current version128 numbered steps; Main/Lazy owner rules unchanged. | `utils/cwl_campaign.py:218`, `utils/cwl_campaign.py:227` |
| STE-75 | Done: War reminder delivery receipt · status text. | `extensions/tasks/war_reminders.py:65`, `extensions/tasks/war_reminders.py:103` |
| STE-76 | Done: Bulk-return status labels only; machine status keys unchanged. | `utils/return_bulk.py:66` |
| STE-77 | Done: Legacy /cwl-reminder commands (staff only) · reply text. | `extensions/tasks/cwl_reminder.py:2964`, `extensions/tasks/cwl_reminder.py:2942` |
| STE-78 | Done: Conflict error prose only; revisions/CAS/status codes unchanged. | `cwl_web/app.py:180`, `cwl_web/app.py:1301`, `cwl_web/app.py:1630`, `cwl_web/app.py:1632`, `cwl_web/app.py:1670`, `cwl_web/app.py:1894`, `cwl_web/announcements.py:247`, `cwl_web/announcements.py:252`, `cwl_web/announcements.py:286`, `cwl_web/announcements.py:303`, `cwl_web/participation.py:260`, `cwl_web/participation.py:263`, `cwl_web/participation.py:345`, `cwl_web/participation.py:350`, `cwl_web/participation_sync.py:1140`, `cwl_web/roster_sequence_review.py:163`, `cwl_web/roster_sequence_review.py:17`, `cwl_web/bonuses.py:399`, `utils/cwl_campaign.py:2267`, `utils/cwl_campaign.py:2269`, `utils/cwl_campaign.py:2285` |
| STE-79 | Done: Malformed-request prose only; request validators/status codes unchanged. | `cwl_web/app.py:1422`, `cwl_web/app.py:1232`, `cwl_web/app.py:1265`, `cwl_web/app.py:1475`, `cwl_web/app.py:1823`, `cwl_web/app.py:1887`, `cwl_web/bonuses.py:296`, `cwl_web/bonuses.py:344`, `cwl_web/bonuses.py:380`, `cwl_web/bonuses.py:450`, `cwl_web/participation.py:325`, `cwl_web/announcements.py:228`, `cwl_web/participation_sync.py:1119` |
| STE-80 | Done: Only surfaced schedule/ambiguous-receipt errors changed. Internal exceptions retained; see visibility notes. | `cwl_web/store.py:655`, `cwl_web/providers.py:98`, `cwl_web/discord_member.py:50`, `cwl_web/discord_member.py:53`, `cwl_web/discord_member.py:56`, `utils/cwl_campaign.py:534`, `utils/cwl_campaign.py:1089`, `utils/cwl_campaign.py:1689`, `utils/cwl_campaign.py:2253`, `utils/cwl_campaign.py:2272` |
| STE-81 | Done: Role recovery messages: three commands in one sentence · error text. | `cwl_web/store.py:456`, `cwl_web/store.py:607`, `cwl_web/store.py:621` |
| STE-82 | Done: Delivery messages in announcements · error text. | `cwl_web/announcements.py:268`, `cwl_web/announcements.py:295`, `cwl_web/announcements.py:316`, `cwl_web/roster_image_posts.py:167` |
| STE-83 | Done: "Please" and "Please contact staff" · error text. | `cwl_web/issues.py:52`, `cwl_web/issues.py:116`, `cwl_web/todo.py:305`, `web/cwl/src/App.tsx:92`, `web/cwl/src/todoLoading.ts:7`, `web/cwl/src/webPush.ts:78` |
| STE-84 | Done: Reminder campaign time formats · error text. | `utils/cwl_campaign.py:438`, `utils/cwl_campaign.py:458`, `utils/cwl_campaign.py:465` |
| STE-85 | Done: All three exact diagnostic reason-map keys changed with their exception messages; category/reason codes preserved and tested. | `cwl_web/participation_sync.py:245`, `cwl_web/participation_sync.py:248`, `cwl_web/participation_sync.py:253`, `cwl_web/participation_sync.py:262` |
| STE-86 | Done: Other backend wording · error text. | `cwl_web/manage_operations.py:132`, `cwl_web/manage_reminders.py:81`, `cwl_web/strikes.py:837` |

| Owner542 addition | Done: no visible campaign term; use CWL month, automatic messages and time zone. Code/storage names unchanged. Syntax-position guards include positive machine cases and negative visible reply/embed/HTTP/label cases. | `web/cwl/src/ReminderWorkspace.tsx:848`, `utils/cwl_forms.py:60`, `utils/cwl_sequence.py:39`, `utils/cwl_campaign.py:548`, `utils/cwl_web_bridge.py:36`, `cwl_web/manage_bridge.py:51` |

## Saved-copy and visibility boundaries

Per Shaka541, the raw matching strings in `utils/cwl_campaign.py:103–110`, `_legacy_dashboard_signup_body`, and `new_copy=False` output stay exact. `your in` (103), `less then` (104,110) and `we got ya` (308) are **kept on purpose: legacy compatibility**. The fixture comes from deployed base3bc; old-body normalization and version127 sparse/full baselines match that fixture. Fresh128 defaults change only body/title/label and the version marker. No stored campaign is rewritten.

STE80 internal messages retained:

- `cwl_web/store.py:655`: role-backup CAS exception is caught immediately; staff receive the separate role_backup_error summary, not this exception.
- `cwl_web/providers.py:98`: standalone-pool binding invariant during application wiring; not a dashboard request message.
- `cwl_web/discord_member.py:50–56`: loopback bridge caller/token authentication errors; browser dashboard sessions do not call this internal transport endpoint.
- `utils/cwl_campaign.py`: roster pool/destination/message/actor guard in reopening a deleted roster receipt validates server-supplied transport arguments. It is not a staff form prompt.

The visible schedule error preserves both possible causes (a dependency loop or missing time reference). Multiple matching sent announcements require a Discord check. No retry policy, mention scope, auth check, destination, schema, request shape or timing changed.

## Validation record

- Frontend: 1775 passed in296 files; tsc and private Vite build passed. Output is `.local/wording155/build`, not workspace dist or deployed assets.
- Copy/participation contracts:132 passed, including exact exception prose, all three diagnostic reasons, unchanged unavailable status and nonmutation.
- Backend focused:996 passed,16 skipped,62 subtests. External DNS/connect/UDP/defaultports blocked by reviewed c02 guard.
- Source AST:125 frontend source files differ only in visible literals/JSX text and the paired saved-view copy regex; identifiers/numbers/operators/JSX structure remain unchanged.
- Initial FE assertion failures and the saved-view regex mismatch are retained. The latter was a real local wording regression: expanded you-will text no longer matched the old you’ll removal regex. Both sides now match, and the existing saved-view regression passes without weakening its no-duplicate-label assertion.
- Required unchanged war check:213 backend passed,1 skipped;35 frontend passed in8 files; tsc/private build passed. Fourteen360/1440 layout samples passed with no horizontal page overflow/page errors. Remaining before READY: clean frozen full backend, exact-artifact owned boot, final review/provenance and retained preview. No live notification delivery is claimed.

## Completion review scope

Authorization and destination ownership remain in the existing handlers. The
996 focused backend tests cover the current HTTP, campaign, participation and
return paths, including malformed requests and unavailable data. New participation
checks pin the exact visible errors and diagnostic categories without logging
remote prose. Frontend tests retain their write-count, cancellation, permission,
conflicting-edit, late-response and uncertain-send assertions; only text and text
selectors were aligned. No assertion was dropped or replaced with a weaker
transport check.

The source review found a saved-view text comparison that needed the same wording
change as its producer. Its existing regression detected a duplicated closed
signup label; the paired regex fix retains the original display behavior.
The fresh-default version change also required reconstructing the stored127
baseline; the first red compatibility cases and failed runs are retained locally.
No automatic retry is added for a message Discord may have accepted.

Layout samples cover signup, Build roster, Announcements, Signup reminders,
Declaration check, Results and Bonus medals at360 and1440. Fourteen isolated
screenshots have no horizontal page overflow or JavaScript page errors. The
reviewed narrow reminder page and wide announcement page keep actions and status
legible. Remote image origins were blocked in this fixture, so a missing remote
logo is expected. This is a wording review, not a claim of screen-reader testing
or live Discord delivery. Keyboard/focus/confirmation behavior remains covered by
the unchanged interaction assertions in the frontend suite.

## Follow-up542/543/544 validation

The exact initial542 inventory has42 source literal edits across8 files and33
distinct old messages (including4 Select producer sentences), plus8 test
wording/reference edits. `ReminderWorkspace` additionally changes only the
multiline label to Current CWL month, still displaying `state.cycle`.
The old full run stopped at7 failed/2026 passed/29 skipped; it is not full
validation. All seven were prose/reference mismatches. The approved targeted
resolution passed86 tests with3 subtests. The strengthened visible-sink guard
then passed19 tests, including a reply inside the internal-purpose branch.
The new full frontend passed1776 tests in296 files and the new private build
passed tsc/Vite. Fourteen new360/1440 layout samples include the Schedule view and its Current CWL month label; both widths were visually inspected. No page errors or horizontal overflow. Full backend and owned boot remain pending.

The first new guard run is retained: it detected a real multiline visible label
and also incorrectly classified22 machine expressions. The corrected guard
exempts syntax positions only, not matching prose strings. It checks visible
reply/embed/form/label/button/HTTP/error sinks before considering wire/storage
positions. Internal `new_draft` purpose-enum validation remains unchanged because
its purpose is supplied by code before data loading; internal print journals
remain unchanged. Both exceptions are distinguished by syntax. No Mongo kind,
query, field path or request shape changed.

Every changed existing assertion/control/fixture text is listed as old to new
with its current location in [ste155-assertion-wording.md](ste155-assertion-wording.md).
The original no-write, status, data, delivery ledger and stored127 assertions
remain exact. Fresh128 recurring-save expectations use CURRENT_SIGNUP_CHECK_LINE;
the side-by-side test also pins stored127 to its original line.

Final544 required unchanged war gate passed:213 backend,1 skipped;35 frontend in8 files; tsc/private build. No source change followed those checks apart from this review record.

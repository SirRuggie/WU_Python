# STE155 changed assertion and fixture text

Per Shaka543: this is the complete text-change inventory for existing tests against base3bc. It includes changed fixture text and control selectors as well as assertions, so the review does not omit an assertion hidden inside a helper. Existing test AST operators, numeric values, call structure and identifiers are unchanged. The only nonliteral substitutions are the three explicit current128 check-line references below. No write-count, HTTP status, data contract or stored127 assertion is weakened.

| Current location | Old string or reference | New string or reference |
| --- | --- | --- |
| `tests/test_cwl_post_copy_scope.py:184` | `Campaign changed` | `The automatic messages changed` |
| `tests/test_cwl_post_update_http.py:332` | `Choose Main or Lazy and which months` | `Select Main or Lazy and which months` |
| `tests/test_cwl_post_update_http.py:333` | `Choose the month` | `Select the month` |
| `tests/test_cwl_post_update_store.py:298` | `Choose Main or Lazy and which months` | `Select Main or Lazy and which months` |
| `tests/test_cwl_post_update_store.py:299` | `Choose Main or Lazy and which months` | `Select Main or Lazy and which months` |
| `tests/test_cwl_post_update_store.py:300` | `Choose the month` | `Select the month` |
| `tests/test_cwl_recurring_save.py:27` | `cwl_campaign.SIGNUP_CHECK_LINE` | `cwl_campaign.CURRENT_SIGNUP_CHECK_LINE` |
| `tests/test_cwl_recurring_save.py:67` | `cwl_campaign.SIGNUP_CHECK_LINE` | `cwl_campaign.CURRENT_SIGNUP_CHECK_LINE` |
| `tests/test_cwl_recurring_save.py:73` | `cwl_campaign.SIGNUP_CHECK_LINE` | `cwl_campaign.CURRENT_SIGNUP_CHECK_LINE` |
| `tests/test_cwl_review.py:14` | `Sign-up reminder 5** timing: <t:` | `Signup reminder 5** timing: <t:` |
| `tests/test_cwl_roster_image_channels.py:45` | `Select the matching Manage campaign month first` | `Select the matching Manage CWL month first` |
| `tests/test_cwl_roster_messages.py:30` | `Can't find your name? Check My clan assignments.` | `Your name is not on the list? Open My clan assignments.` |
| `tests/test_cwl_season_flow.py:78` | `Couldn't copy hosting clans; nothing was created.` | `Could not copy hosting clans; nothing was created.` |
| `web/cwl/src/AnnouncementDeletedRecovery.test.tsx:56` | `Earlier image posts stay` | `earlier image posts stay in Discord` |
| `web/cwl/src/AnnouncementSequenceStatus.test.tsx:149` | `requires an explicit no-ping review before continuing an unconfirmed sent announcement` | `requires an explicit no-ping review before continuing an not confirmed sent announcement` |
| `web/cwl/src/ArrivalCheck.test.tsx:164` | `1 not on roster` | `1 players not on the roster` |
| `web/cwl/src/ArrivalCheck.test.tsx:171` | `0 not on roster` | `0 players not on the roster` |
| `web/cwl/src/ArrivalCheck.test.tsx:301` | `Can't mention: Player 0` | `Cannot mention: Player 0` |
| `web/cwl/src/ArrivalCheck.test.tsx:312` | `Checking published version 1 · the draft has changes members can't see yet` | `Checking published version 1 · the draft has changes members cannot see yet` |
| `web/cwl/src/ArrivalCheck.test.tsx:811` | `Can't mention: Player 1` | `Cannot mention: Player 1` |
| `web/cwl/src/ArrivalCheck.test.tsx:823` | `Can't mention:` | `Cannot mention:` |
| `web/cwl/src/ArrivalCheck.test.tsx:864` | `0 not on roster · 3 not published yet` | `0 players not on the roster · 3 not published yet` |
| `web/cwl/src/BandStatusSummary.test.tsx:94` | `are historical` | `show past results` |
| `web/cwl/src/BaseBank.test.tsx:84` | `Base link coming soon` | `Base link not available yet` |
| `web/cwl/src/BaseBank.test.tsx:87` | `Base image coming soon` | `Base image not available yet` |
| `web/cwl/src/BaseBank.test.tsx:132` | `Couldn't load Base bank` | `Could not load Base bank` |
| `web/cwl/src/BaseBank.test.tsx:160` | `Base link coming soon` | `Base link not available yet` |
| `web/cwl/src/ClanManagement.test.tsx:283` | `Choose PNG, JPG, GIF or WEBP up to 10 MB.` | `Select PNG, JPG, GIF or WEBP up to 10 MB.` |
| `web/cwl/src/ClanRosterImages.test.tsx:142` | `Retry the edit on the same message with version 2? This won't create a new message.` | `Retry the edit on the same message with version 2? This will not create a new message.` |
| `web/cwl/src/ClanRosterImages.test.tsx:262` | `won't change anything in Discord` | `does not change anything in Discord` |
| `web/cwl/src/ClanRosterImages.test.tsx:263` | `Edit the existing message to say Old Clan is no longer hosting? This won't create a new message.` | `Edit the existing message to say Old Clan is no longer hosting? This will not create a new message.` |
| `web/cwl/src/ClanSettings.test.tsx:235` | `Can't move to Lazy CWL: 16 players are assigned here. Assign them elsewhere first.` | `Cannot move to Lazy CWL: 16 players are assigned here. Assign them elsewhere first.` |
| `web/cwl/src/ClanSettings.test.tsx:339` | `Maximum weight must be greater` | `The maximum weight must be more than` |
| `web/cwl/src/ClanSettings.test.tsx:442` | `Can't move to Lazy CWL: 16 players are assigned here.` | `Cannot move to Lazy CWL: 16 players are assigned here.` |
| `web/cwl/src/CompareClanPicker.interaction.test.tsx:102` | `Choose clans` | `Select clans` |
| `web/cwl/src/DashboardHome.test.ts:15` | `✓ You're signed up · 1 of 3 accounts` | `✓ You are signed up · 1 of 3 accounts` |
| `web/cwl/src/DashboardHome.test.ts:17` | `We've got your signup. Your clan will show here once staff finish the roster.` | `Your signup is saved. Your clan appears here after staff finish the roster.` |
| `web/cwl/src/DeclarationExtras.test.tsx:37` | `0 not on roster` | `0 players not on the roster` |
| `web/cwl/src/DeclarationExtras.test.tsx:48` | `Couldn't check` | `Could not check` |
| `web/cwl/src/DeclarationExtras.test.tsx:49` | `0 not on roster` | `0 players not on the roster` |
| `web/cwl/src/DeclarationExtras.test.tsx:79` | `⚠ 1 not on roster` | `⚠ 1 players not on the roster` |
| `web/cwl/src/DeclarationExtras.test.tsx:92` | `Couldn't check` | `Could not check` |
| `web/cwl/src/DeclarationExtras.test.tsx:94` | `0 not on roster` | `0 players not on the roster` |
| `web/cwl/src/DeclarationExtras.test.tsx:129` | `1 not on roster · 1 not published yet` | `1 players not on the roster · 1 not published yet` |
| `web/cwl/src/DeclarationExtras.test.tsx:149` | `0 not on roster · 1 not published yet` | `0 players not on the roster · 1 not published yet` |
| `web/cwl/src/DeclarationExtras.test.tsx:162` | `Couldn't check` | `Could not check` |
| `web/cwl/src/DeclarationExtras.test.tsx:163` | `0 not on roster` | `0 players not on the roster` |
| `web/cwl/src/DeclarationExtras.test.tsx:201` | `1 not on roster · 1 not published yet · 1 low TH in clan` | `1 players not on the roster · 1 not published yet · 1 low TH in clan` |
| `web/cwl/src/DeclarationPingPanel.test.tsx:201` | `Reload latest settings` | `Refresh latest settings` |
| `web/cwl/src/DeclarationPingPanel.test.tsx:202` | `Reload latest settings` | `Refresh latest settings` |
| `web/cwl/src/DiscordPreview.test.tsx:14` | `Choose a clan` | `Select a clan` |
| `web/cwl/src/Finalize.interaction.test.tsx:216` | `The working roster and signups are kept.` | `The working roster and signups stay saved.` |
| `web/cwl/src/Finalize.interaction.test.tsx:370` | `Reload failed` | `Refresh failed` |
| `web/cwl/src/Finalize.interaction.test.tsx:377` | `Reload failed` | `Refresh failed` |
| `web/cwl/src/ImageCollection.test.tsx:84` | `partial bulk move retains only unconfirmed selections and reports progress` | `partial bulk move retains only not confirmed selections and reports progress` |
| `web/cwl/src/MemberSignupStatus.test.tsx:120` | `✓ You're signed up · 2 of 5 accounts` | `✓ You are signed up · 2 of 5 accounts` |
| `web/cwl/src/MemberSignupStatus.test.tsx:163` | `You haven't signed up any accounts yet.` | `You have not signed up any accounts yet.` |
| `web/cwl/src/MemberSignupStatus.test.tsx:178` | `You're signed up · 2 accounts` | `You are signed up · 2 accounts` |
| `web/cwl/src/MemberSignupStatus.test.tsx:198` | `Clans are not ready yet. Check back soon.` | `Clans are not ready yet. Try again later.` |
| `web/cwl/src/MemberSignupStatus.test.tsx:297` | `You're signed up` | `You are signed up` |
| `web/cwl/src/MemberSignupStatus.test.tsx:310` | `You'll see your clan by` | `You will see your clan by` |
| `web/cwl/src/ModerationSettings.test.tsx:298` | `Choose a channel first` | `Select a channel first` |
| `web/cwl/src/ModerationSettings.test.tsx:299` | `Choose a channel first` | `Select a channel first` |
| `web/cwl/src/ParticipationWaiting.test.tsx:24` | `November CWL hasn't started in Clash yet` | `November CWL has not started in Clash yet` |
| `web/cwl/src/ParticipationWaiting.test.tsx:109` | `November CWL hasn't started in Clash yet` | `November CWL has not started in Clash yet` |
| `web/cwl/src/ParticipationWaiting.test.tsx:114` | `hasn't started in Clash yet` | `has not started in Clash yet` |
| `web/cwl/src/ParticipationWaiting.test.tsx:129` | `January CWL hasn't started in Clash yet` | `January CWL has not started in Clash yet` |
| `web/cwl/src/RosterAccountCard.test.tsx:101` | `Kept unplaced` | `Stays unplaced` |
| `web/cwl/src/RosterAccountCard.test.tsx:130` | `Hosting clans need a 15- or 30-player capacity in Clan settings.` | `Set Clan size to 15 or 30 in Clan settings.` |
| `web/cwl/src/RosterAccountCard.test.tsx:163` | `Kept unplaced` | `Stays unplaced` |
| `web/cwl/src/RosterPlayerDialog.sections.test.tsx:102` | `At a glance` | `Summary` |
| `web/cwl/src/RosterPlayerDialog.sections.test.tsx:208` | `View only · you don't have roster editing access` | `View only · you do not have roster editing access` |
| `web/cwl/src/RosterPlayerDialog.sections.test.tsx:221` | `View only · you don't have roster editing access` | `View only · you do not have roster editing access` |
| `web/cwl/src/RosterPlayerDialog.sections.test.tsx:399` | `Changed by someone else · Reload` | `Changed by someone else · Refresh` |
| `web/cwl/src/RosterPlayerDialog.sections.test.tsx:403` | `Changed by someone else · Reload` | `Changed by someone else · Refresh` |
| `web/cwl/src/RosterPlayerDialog.sections.test.tsx:419` | `Saved value isn't a whole thousand. Enter a new one to change it.` | `Saved value is not a whole thousand. Enter a new one to change it.` |
| `web/cwl/src/RosterSelectionBar.test.tsx:24` | `Max 50 per action` | `50 accounts at most for each action` |
| `web/cwl/src/RosterSelectionBar.test.tsx:25` | `Narrow your selection to 50 or fewer` | `Select 50 accounts or fewer` |
| `web/cwl/src/SavedSignupLoading.test.tsx:129` | `Clans are not ready yet. Check back soon.` | `Clans are not ready yet. Try again later.` |
| `web/cwl/src/SignupActivity.test.tsx:219` | `Couldn't check signup changes` | `Could not check signup changes` |
| `web/cwl/src/SignupCardsLocation.test.tsx:107` | `You'll see your clan by` | `You will see your clan by` |
| `web/cwl/src/SignupCardsLocation.test.tsx:120` | `You haven't signed up any accounts yet.` | `You have not signed up any accounts yet.` |
| `web/cwl/src/SignupCardsLocation.test.tsx:151` | `✓ You're signed up · 2 of 3 accounts` | `✓ You are signed up · 2 of 3 accounts` |
| `web/cwl/src/SignupCardsLocation.test.tsx:198` | `You're signed up · 2 accounts` | `You are signed up · 2 accounts` |
| `web/cwl/src/SignupCardsLocation.test.tsx:300` | `You'll see your clan by` | `You will see your clan by` |
| `web/cwl/src/SignupReviewFlow.test.tsx:355` | `Choose Lazy CWL` | `Select Lazy CWL` |
| `web/cwl/src/SignupVisibilityConsumers.test.tsx:19` | `\n        Couldn't check signup visibility ·` | `\n        Could not check signup visibility ·` |
| `web/cwl/src/SignupVisibilityConsumers.test.tsx:69` | `Couldn't check signup visibility` | `Could not check signup visibility` |
| `web/cwl/src/SignupVisibilityConsumers.test.tsx:75` | `Couldn't check signup visibility` | `Could not check signup visibility` |
| `web/cwl/src/StaffDetailsPanel.test.tsx:114` | `Saved. Couldn't refresh. Refresh the page to see the latest.` | `Saved. Could not refresh. Refresh the page to see the latest.` |
| `web/cwl/src/StaffDetailsPanel.test.tsx:181` | `keeps a conflicting weight editor mounted until explicit Reload and uses the fresh revision` | `keeps a conflicting weight editor mounted until explicit Refresh and uses the fresh revision` |
| `web/cwl/src/StaffDetailsPanel.test.tsx:195` | `Changed by someone else · Reload` | `Changed by someone else · Refresh` |
| `web/cwl/src/StrikeReplacementRow.test.tsx:69` | `Reload` | `Refresh` |
| `web/cwl/src/StrikesUx.test.tsx:124` | `Changed by someone else · Reload` | `Changed by someone else · Refresh` |
| `web/cwl/src/StrikesUx.test.tsx:129` | `Reload` | `Refresh` |
| `web/cwl/src/StrikesUx.test.tsx:137` | `Reload` | `Refresh` |
| `web/cwl/src/StrikesUx.test.tsx:138` | `Reload` | `Refresh` |
| `web/cwl/src/StrikesUx.test.tsx:517` | `Changed by someone else · Reload` | `Changed by someone else · Refresh` |
| `web/cwl/src/StrikesUx.test.tsx:524` | `Reload` | `Refresh` |
| `web/cwl/src/TodoActivityStatus.test.tsx:13` | `Couldn’t load this activity` | `Could not load this activity` |
| `web/cwl/src/WarReminders.test.tsx:81` | `Settings changed. Reload.` | `Settings changed. Refresh.` |
| `web/cwl/src/WeightQueue.test.tsx:146` | `Weight wasn't saved` | `Weight was not saved` |
| `web/cwl/src/WeightQueue.test.tsx:150` | `Weight wasn't saved` | `Weight was not saved` |
| `web/cwl/src/WeightQueue.test.tsx:259` | `Weight wasn't saved` | `Weight was not saved` |
| `web/cwl/src/activity/EventsWorkspace.test.tsx:24` | `not a fixed end date` | `do not show when each clan’s battles end` |
| `web/cwl/src/activity/TaskEventTimer.test.tsx:27` | `battle schedule is different` | `Each clan has its own battle times` |
| `web/cwl/src/activity/WarDetailPanel.test.ts:48` | `incomplete or malformed` | `The war details are not complete` |
| `web/cwl/src/activity/WarDetailPanel.test.ts:50` | `incomplete or malformed` | `The war details are not complete` |
| `web/cwl/src/bonusRaffle.test.ts:28` | `sit out this season` | `cannot enter this season` |
| `web/cwl/src/clanManagement/reminderOverview.test.ts:31` | `removed or become inaccessible` | `removed it, or the bot may not be able to use it` |
| `web/cwl/src/clanManagement/reminderOverview.test.ts:56` | `removed or become inaccessible` | `removed it, or the bot may not be able to use it` |
| `web/cwl/src/memberTimezones/MembersTimezoneFlow.test.tsx:221` | `Reload latest and keep draft` | `Refresh latest and keep draft` |
| `web/cwl/src/memberTimezones/MembersTimezoneFlow.test.tsx:258` | `retains the request identity after an unconfirmed transport failure` | `retains the request identity after an not confirmed transport failure` |
| `web/cwl/src/memberTimezones/Standardize.test.tsx:414` | `Choose a run` | `Select a run` |
| `web/cwl/src/memberTrust.test.tsx:131` | `Couldn't refresh. Showing last update.` | `Could not refresh. Showing last update.` |
| `web/cwl/src/memberTrust.test.tsx:137` | `Couldn't refresh` | `Could not refresh` |
| `web/cwl/src/memberTrust.test.tsx:299` | `Couldn't refresh. Showing last update.` | `Could not refresh. Showing last update.` |
| `web/cwl/src/memberTrust.test.tsx:303` | `Couldn't refresh` | `Could not refresh` |
| `web/cwl/src/memberTrust.test.tsx:335` | `Couldn't refresh. Showing last update.` | `Could not refresh. Showing last update.` |
| `web/cwl/src/memberTrust.test.tsx:340` | `Couldn't refresh` | `Could not refresh` |
| `web/cwl/src/memberTrust.test.tsx:363` | `Choose Main CWL` | `Select Main CWL` |
| `web/cwl/src/memberTrust.test.tsx:593` | `Choose Lazy CWL` | `Select Lazy CWL` |
| `web/cwl/src/memberTrust.test.tsx:682` | `Choose Lazy CWL` | `Select Lazy CWL` |
| `web/cwl/src/publicationBlockingReason.test.ts:17` | `Load the roster before publishing.` | `Load the roster. Then publish.` |
| `web/cwl/src/publicationBlockingReason.test.ts:19` | `Finish the current edit or operation before publishing.` | `Finish the current edit. Then publish.` |
| `web/cwl/src/publicationBlockingReason.test.ts:23` | `Refresh the draft and resolve the error before publishing.` | `Refresh the draft and fix the error. Then publish.` |
| `web/cwl/src/publicationBlockingReason.test.ts:25` | `Publishing is unavailable for an archived season.` | `You cannot publish an archived season.` |
| `web/cwl/src/publicationBlockingReason.test.ts:28` | `Joining instructions must be 2,000 characters or fewer.` | `Joining instructions must not be more than 2,000 characters.` |
| `web/cwl/src/publicationBlockingReason.test.ts:35` | `Acknowledge the unplaced accounts before publishing.` | `Confirm that you know about the unplaced accounts. Then publish.` |
| `web/cwl/src/publicationStatus.test.ts:21` | `Draft · members can't see placements yet` | `Draft · members cannot see placements yet` |
| `web/cwl/src/serverManagement.test.ts:13` | `Choose clans` | `Select clans` |
| `web/cwl/src/useComparisonLocations.interaction.test.tsx:213` | `Couldn't update locations · showing last results` | `Could not update locations · showing last results` |
| `web/cwl/src/useDeclarationData.test.tsx:72` | `Couldn't update · showing last results` | `Could not update · showing last results` |
| `web/cwl/src/useDeclarationData.test.tsx:199` | `Couldn't check locations` | `Could not check locations` |
| `web/cwl/src/useDeclarationExtras.test.tsx:60` | `Couldn't check clan members` | `Could not check clan members` |
| `web/cwl/src/useRosterPreferences.test.ts:65` | `s` | ` seconds` |
| `web/cwl/src/useRosterPreferences.test.ts:69` | `s` | ` seconds` |
| `web/cwl/src/useRosterPreferences.test.ts:80` | `s` | ` seconds` |
| `web/cwl/src/useRosterPreferences.test.ts:88` | `s` | ` seconds` |
| `web/cwl/src/useRosterPreferences.test.ts:90` | `s` | ` seconds` |
| `web/cwl/src/useSignupAction.test.tsx:224` | `Couldn't check signup visibility` | `Could not check signup visibility` |
| `web/cwl/src/warReminders/TestPanel.test.tsx:104` | `Delivery unconfirmed` | `Delivery not confirmed` |
| `web/cwl/src/weightTrial/WeightTrial.test.tsx:641` | `Town Hall unavailable · choose storages` | `Town Hall unavailable · select storages` |
| `web/cwl/src/weightTrial/model.test.ts:187` | `Choose storages` | `Select storages` |

| `tests/test_cwl_roster_full_test_http.py:60` | `'Can'` in `startswith` | `'Your name is not on the list?'` in the same `startswith` assertion |

Additional checks are new, not replacements for old behavior assertions:

- `tests/test_ste155_copy_contract.py`: frozen3bc/unversioned/127 normalization and sparse baseline,128-only text/version delta, and identical custom body with127 vs128 check lines side by side.
- `tests/test_ste155_participation_words.py`: exact prose, unchanged unavailable category and all three safe diagnostic reason codes; no remote prose in logs or provider-data mutation.
- `tests/test_ste155_visible_words.py`: visible backend literals/rendered fresh copy, syntax-position exemptions, positive machine examples and negative reply/embed/HTTP/standalone-label/error examples. Internal draft-purpose and worker-journal exceptions are documented.
- `web/cwl/src/plainWordsPolicy.test.ts`: four new canonical-word rows and the visible-word AST guard. Existing policy assertions remain in place.

Machine status names, numeric/status/write-count assertions, delivery-ledger checks, cancellation and no-retry assertions remain exact. Existing legacy127 expectations stay frozen; only tests creating fresh128 data reference CURRENT_SIGNUP_CHECK_LINE.

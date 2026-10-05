# War Operations UX decisions and implementation

Updated 5 October 2026 after the walkthrough with Ruggie. This document replaces the initial proposal with the agreed behavior. The changes are implemented locally; production restart and real Discord phone verification are separate from the automated checks.

The priority is fast routine work. Staff rarely change announcements or spreadsheet links, usually publish Main and Lazy together, and use the existing return ping to identify and contact missing players. Avoid compulsory previews, extra save steps, player browsers, or another alerts menu.

## Publish Final Roster

The CWL opening screen has a **Publish Final Roster** action. It opens with **Both** selected and offers **Main CWL**, **Lazy CWL**, and **Both**. Saved spreadsheet links are reused until explicitly changed.

Press **Publish to Both Channels**, or **Publish Final Roster** for one audience, to send immediately. There is no confirmation or required preview. Channels and named ping roles remain visible. Each audience has optional **Edit message**, **Change link**, and **Preview** actions. Submitted edits save automatically for future use; they do not publish or rewrite existing posts.

Publication uses the saved content. Each audience gets its own delivery result and a View post link when Discord confirms it. **Retry failed announcement** retries failures only; the delivery ledger prevents resending a successful audience. Publishing a saved final roster can be done while automatic signup reminders are paused. This does not resume the automatic schedule.

The implementation retains the existing once-per-audience-per-cycle delivery protection. Repeated clicks are not a repost feature. A receipt-storage outage is distinguished from a send failure so a confirmed post is not deliberately resent.

## Signup Reminders

Settings persist and repeat monthly until staff manually change them. There is no monthly reset. Keep the existing opening and closing forms, editable day/date choices, evenly spaced reminders, hourly interval option, and final reminder lead time.

Submitting a valid modal saves automatically. Dismissing a modal with X or Escape cancels: Discord does not provide the bot with those unsubmitted values. If reminders are running, saved timing changes update upcoming sends. If paused, they remain paused. New configurations stay paused until **Start Reminders**. **Pause Reminders** controls automatic delivery separately from editing.

The final reminder is included in the reminder count/pattern, not added as a duplicate. Choose Main CWL, Lazy CWL, or Both for signup reminders. The selected audience and settings carry forward.

The screen shows Running, Paused, or Needs attention, the next scheduled message with audience/channel/time, and the last delivery result. Failed reminder delivery has a contextual retry action. Runtime details are not another management workspace.

Invalid timing keeps the previous active schedule and retains the attempted edit with an explanation. A content edit applies its changed content without accidentally applying a previously rejected timing change. Revision checks prevent stale editors from overwriting newer settings. Date forms explain that saved dates repeat monthly.

## CWL Return Pings

The previous CWL Rosters entry is named **CWL Return Pings**. The existing internal route remains compatible with older buttons. This tool tracks saved home-clan members; it does not contain the public assignment spreadsheet.

Opening selects **FWA → All FWA clans**. Individual clans remain in the selector for occasional use. Switching to Main opens All Main clans. Bulk scope is plainly displayed above the actions.

**Save Current Members** saves members for clans without an existing saved list. Existing lists are preserved. Selecting an individual saved clan exposes **Replace Saved Members**, which retains a confirmation explaining that replacement stops the old pings and uses current membership. Clear operations also retain their destructive-action reviews.

The main panel remains compact: scope, saved-list status, away count when available, frequency, next check, and stop time. Existing saved-member editing remains secondary. No new player search, filter, or paginated player browser was added.

### Manual pings

**Send Ping Now** rechecks the selected clan(s) and sends immediately to those with players away. There is no extra confirmation. If everyone is home, it reports that no ping was needed. This action does not start automatic pings or reset their seven-day timer.

The existing public ping format is unchanged, including clickable Discord mentions and player details. Staff can continue opening the mentioned Discord account to DM a player.

### Automatic FWA pings

Keep **Every 30 minutes**, **Every 1 hour**, and **Every 2 hours**. Frequency selections save automatically. Running schedules update; paused schedules remain paused. Destinations stay as currently configured.

**Start Return Pings** begins the window. **Pause Return Pings** suspends checking. **Resume Return Pings** continues within the original window. Neither resuming nor changing frequency resets the original start timestamp.

Check for seven days from first start, or until saved-list expiry, whichever comes first. Expiry remains **00:00 UTC at the start of the 16th**, the evening of the 15th in Eastern time. Never extend expiry to complete seven days. No pings may be sent after expiry, including manual sends or requests whose player lookup crosses the cutoff.

When everyone is home, skip that ping and continue checking. If players leave again, include them in the next scheduled ping while the window is still open. Everyone being home does not mark the process complete or disable monitoring.

Bulk start/send results show successes and individual failures. **Retry Failed Clans** uses only the failed saved-list IDs. Successful clans keep running with their original timers. Replaced lists and stale confirmations cannot be silently substituted into a retry.

Main continues to support manual return pings only.

## Other FWA tools

**Sync & Reminders** leads with running/setup/problem status, signup-panel channel, and next recorded sync. Keep Check Feed and Send Me a Test DM easily accessible. Feed/poller/recovery information and BAND Monitor sit under Details. Member DM opt-ins and timing choices remain unchanged.

**War Message Templates** is the new label for War Messages. It explains that `/fwa war-plans` posts announcements. Submitted text, artwork, and accent changes save automatically for future posts. They do not send announcements or modify existing ones. Template revision protection remains in place.

**Points Monitor** leads with monitoring state, watched clans, latest results, timestamps, and problems needing attention. Detector/retry/recovery diagnostics sit under Details. Existing watch-list and permission behavior remains intact.

Each tool owns its status and failures. There is no separate Alerts & Delivery menu.

## Decisions rejected during the walkthrough

- Mandatory final preview or publication confirmation.
- Requiring a separate Save Changes button for normal submitted edits.
- Renaming the return tool Home Rosters & Returns.
- Adding a player search/filter browser to routine return tracking.
- Automatically stopping checks when everyone is home.
- Extending saved-list expiry to finish the seven-day window.
- Adding another top-level alerts menu.

## Verification and rollout

Focused tests cover saved-version publishing, both-audience delivery, partial failures and failure-only retry, duplicate-click protection, monthly persistence, autosaving, content/timing separation, return-ping pause/resume, exact expiry, and everyone-home checks followed by later departures. Existing campaign, roster, permission, template, scheduler, and component-limit tests are also exercised.

Validation: the affected suite, including Mongo routing checks and all 12 focused UX/lifecycle cases, passed 421 tests with 18 skipped integration cases. An isolated export of the staged change, using the tracked Mongo implementation without the separate routing work, passed 387 tests with 18 skipped integration cases. Syntax compilation and `git diff --check` passed.

Tests use fake Discord/Mongo/scheduler services and do not send live messages. Manual validation should use a test server: verify phone wrapping, native modal Submit versus dismiss, main/all-clan scope, paused-state persistence, public delivery links, and permission-denied feedback. No production restart or live publication is part of this local implementation.

The separate Mongo routing work is preserved outside this change. The architecture check permits the central namespace router to declare the roster collection while retaining the store boundary for application access. Read-only verification confirmed connectivity, the expected CWL collection destinations, and majority acknowledgement for roster writes. This change requires no database migration.

The separate local CWL website plan is unchanged. Final assignment data, external spreadsheets, and return-tracking snapshots remain separate systems.

## Research and implementation references

The original audit traced `/manage`, CWL editing/publishing, saved-list and reminder services, and the FWA status/template screens. These decisions apply [recognition and system-status principles](https://www.nngroup.com/articles/ten-usability-heuristics/) and [progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/), adapted to the user's frequent tasks. The user's explicit preference removes a compulsory publication review.

Discord screens remain subject to the [native component limits](https://docs.discord.com/developers/components/reference). Tests check component counts, unique IDs, and supported nesting; real Discord mobile rendering is not established by those tests alone.

Primary implementation files: `extensions/commands/manage.py`, `cwl_dashboard.py`, `lazycwl_dashboard.py`, `fwa_sync_dashboard.py`, `fwa_points_dashboard.py`, `fwa_war_messages.py`; `extensions/commands/fwa/lazy_cwl_service.py`; `extensions/tasks/cwl_reminder.py`; `utils/cwl_campaign.py`, `cwl_forms.py`, and `lazy_cwl_store.py`.

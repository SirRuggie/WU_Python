# War reminders

Open **Family clans → select a clan → War reminders**. Choose a text or announcement channel, select whether to notify players with any attacks remaining or only players with zero attacks, and add times before war end. Times support whole minutes from 1 minute to 24 hours; quick choices are optional shortcuts. War-start notices are independently selectable. Save and enable each clan separately.

The clan directory has name/tag search, type filtering, and a scrollable list instead of pagination. On mobile, use **Change clan** to reopen the list.

## Message and test delivery

A reminder is a standard Discord text message, with no embed or Components V2, so the phone notification shows its title. Part 1 starts with a `## ` heading: clan vs opponent and remaining time, for example **🔔 Edrag Rush vs ABCD GAMER · 12 hours left**. War Start uses **⚔️ Edrag Rush vs ABCD GAMER · War started**. The subline omits the opponent. It shows the end time (local time plus Discord's live relative time), total attacks left, and the legend "Attacks used / available".

Each Discord owner is mentioned once. An owner with one pending account gets a single line: mention, Town Hall emoji, game name, and attacks used / available. An owner with two or more accounts gets one line, "mention · N accounts", followed by one quoted row per account. Single-account owners come first, then grouped owners, then "Not linked · no ping", each in roster order. Linked rows omit the player tag; unlinked or ambiguously linked rows keep it in inline code so staff can link the account, and never ping. Counts use non-breaking spaces so they stay with their separator on narrow screens.

Messages split at Discord's 2,000-character limit, preserving complete rows and owner groups where they fit. Only the first message carries the subtext line; later messages start with the bold title plus "part N of M", and the first message also shows "part 1 of M". The last part of each set carries the gold footer image as an attachment, which marks the end of the set. No extra message is sent. Oversized groups continue under **Accounts continued** without a second mention, so an owner is pinged only once per reminder. Mentions are explicitly allowlisted; roles and everyone mentions are disabled. Every message keeps the My tasks and Wars link buttons. The dashboard preview renders the same text; it separates `-# ` subtext lines into their own paragraphs because Discord reads subtext per line.

**Send test to selected channel** sends sample data immediately, even with automatic reminders disabled and no active war. It uses the current form channel without saving. **Use my accounts in this clan** selects up to five linked accounts currently in the selected clan, with real names and Town Hall levels but explicitly simulated attack counts. Lookups are cached per user and clan for five minutes. If no linked accounts are in that clan, the form explains that instead of displaying accounts from elsewhere. **Mention me** is selected by default and pings only the signed-in dashboard user. The preview uses the same grouped message as delivery, including a fictional unlinked account in its own section with no mention. Recipient Discord settings still control push notifications.

## Runtime

Scheduled sends hold a process-local lock per channel from claim to last part, so two clans due in the same scan never interleave their parts. Test sends from the dashboard run in another process and are not ordered against scheduled sends.

`extensions.tasks.war_reminders` is registered in `main.py`. It checks enabled family clans every 60 seconds with at most four concurrent clan checks. The Clash client resolves regular wars and CWL; the live attack allowance controls eligibility. ClashKing and ClashPerk links use the shared `utils.account_links` service. The bot has no dependency on dashboard providers. Link-service failures leave a visible tracking error and retry on a subsequent scan, rather than treating an outage as an empty link list.

Settings, status, and delivery receipts use `war_reminder_settings`, `war_reminder_status`, and `war_reminder_deliveries` in the configured bot-config database with majority writes. Settings use optimistic version checks. Delivery claims use a unique Mongo `_id` per clan, war start, and reminder offset, so restart or concurrent workers do not replay the same occurrence. End-time changes do not change that identity.

Reminders up to five minutes late are eligible. Older reminders are skipped to avoid a burst after downtime; newly enabled clans likewise do not replay earlier times. Completed wars and fully attacked rosters do not send. A send that Discord does not confirm stays uncertain and is not automatically retried, since it may already have pinged recipients. A process interruption can leave a receipt at `sending`; the UI labels this delivery unconfirmed. Check the channel before manually sending another test.

## Deployment and validation

Deploy backend and frontend together through the existing manual deployment process. No data migration or new environment variable is required. Startup idempotently creates `clan_delivery_history` (clan tag + descending time) and `enabled_reminders` indexes; existing collections and receipt IDs remain unchanged. Existing clans start disabled. Build the dashboard with `npm --prefix web/cwl run build`; the bot must restart to load its new task and the web service must load the new routes.

Validated with reminder, clan-management, and war-operations backend tests; preview, channel-search, clan-filter, and Discord preview frontend tests; a production frontend build; and desktop/mobile inspection using mocked local clan data. Actual Discord notification delivery requires a test from the deployed dashboard.

## Code ownership

- `utils/war_reminders.py`: validation, war snapshots, timing, and the common message renderer. No database or HTTP access.
- `utils/account_links.py`: shared link-source normalization and unambiguous owner resolution. No dashboard dependency.
- `utils/war_reminder_store.py`: all reminder queries, settings compare-and-swap, durable claims, partial receipts, and index creation. Receipt IDs do not expire.
- `extensions/tasks/war_reminders.py`: bot task lifecycle, bounded polling, live-setting rechecks, and Discord transport.
- `cwl_web/war_reminders.py`: authorization, request validation, response adaptation, and test-message transport.
- `cwl_web/war_reminder_samples.py`: bounded, user-and-clan-scoped sample cache and public roster-provider access. Sample data never enters scheduled sends.
- `web/cwl/src/WarReminders.tsx`: settings load/save and orchestration. `warReminders/ScheduleEditor.tsx`, `TestPanel.tsx`, and `DeliveryHistory.tsx` own the three UI sections; `types.ts` holds their shared contracts and time-input validation.

## Repeatable quality gate and adversarial review

Run `./.venv/bin/python tools/check_war_reminders.py`. It checks the shared-service/storage boundaries, reminder behavior, HTTP and account-provider regressions, relevant frontend tests, the production build, and whitespace errors. `AGENTS.md` requires this review and cleanup for future changes; it does not claim that testing can prove the entire repository bug-free.

The October 21 cleanup checks malformed bodies and extreme reminder strings, foreign-channel rejection, unauthorized callers, forged mention IDs, conflicting/unavailable links, user/clan cache isolation, concurrent settings writes, concurrent delivery claims, changed/removed clans during lookup, time-window expiry, Unicode length limits, hostile names, cancellation, and partial Discord delivery. Test messages now send all rendered parts, store partial progress, and budget their complete labels before splitting. The UI preserves an uncertain submission ID on retry and ignores stale preview/history requests. A failed history refresh does not turn an already successful send into a retry prompt.

Visual verification uses isolated sample data and a mock ambiguous-delivery response at desktop and mobile widths; it never sends real Discord messages. Existing repository-wide aiohttp application-key/deprecation warnings and Vite bundle warnings are outside this feature cleanup. Live push delivery still depends on recipient settings and requires a separately authorized test.

## Clan navigation and workflow checks

Clan selection preserves the current settings section so staff can configure the
same feature across several clans. On mobile, Change clan focuses the directory
search; selecting a clan closes the picker and focuses its heading. Escape closes
the picker. Settings tabs support Left/Right, Home/End, and Enter/Space to activate.

General clan edits and reminder settings have separate save actions. If clan
edits are pending when opening reminders, a visible banner keeps Save clan details
available. Failed saves retain edits. Clan switching and section changes are
locked while reminder saves or test sends are in progress. Directory loading,
empty families, unmatched filters, and failed requests have distinct feedback;
failed role/channel lookups have their own retry. Multipart reminder previews
label each message boundary without adding those labels to Discord messages.

The clan UI is split between orchestration in ClanManagement, directory/search
in clanManagement/ClanDirectory, section navigation in ClanSettingsNavigation,
and field rendering in ClanFields. Channel selection continues to use the shared
ChannelCombobox. The quality gate includes directory-state regression tests.

For future navigation changes, verify at desktop and 390px mobile widths:
select and search clans; keep the active section across clans; edit Details then
open reminders; fail a save and retry; cancel leaving unsaved reminders; save then
switch; and verify navigation stays locked during a slow test send. Check keyboard
focus after selection and section navigation. Inspect a 50-player preview with
multiple owners and unlinked accounts, including all message parts. Use mocked
requests for this workflow review; live Discord delivery is a separate check.

The routine reminder view shows the Reminders switch, channel, "Who to remind",
configured times, save controls, and current status. The switch is the shared
`rosterUi/Switch`. It saves at once through the same `PUT` with the saved
settings and only `enabled` changed, so it never counts as an unsaved change and
never carries other edits. A failed save rolls it back with an inline error; a
409 keeps the draft and shows the server message with Refresh. It stays off and
disabled with "Select a channel first" until the saved settings have a channel.
Add time is a closed disclosure. One closed "Test & history" disclosure holds
Delivery history and Preview & send a test, then Copy reminder settings follows.
Preview requests only run while Test & history is open; closing it retains its
choices and send receipt. During a send it stays open. Uncertain or failed recent
deliveries remain flagged in its summary even when it is closed.

## Family overview

Family clans opens on Reminder overview: a list of clans, one row each, with
the clan name and type, one status line (channel name, schedule, last scheduled
delivery), the shared On/Off switch, and Edit ("Review" when the destination
needs review; "Set up" and no switch when no channel is saved). Off rows are dimmed
and end the schedule with "saved". A missing channel reads "Channel missing ·
select a new one"; raw channel IDs are never shown.

One tool row holds "Find a clan" (name, tag, type or channel name) and a Filters
button. Filters opens an ActionPanel with Type and Status (All, Needs attention,
On, Off, Not set up) with per-option counts, a draft state, and Apply/Reset.
Applied filters show as removable chips with Clear all. "Not set up" means no
saved channel; "Off" means a channel and disabled. Attention rows sort first.
Edit opens the existing clan editor; returning preserves filters and returns
focus to that clan. The view refreshes every 30 seconds while active, and a row
with a save in flight is not overwritten by that refresh.

The switch saves at once with `PUT /manage/clans/<tag>/war-reminders`, the saved
settings with only `enabled` changed, and the row `revision`. Success replaces
that row's settings and revision; failure rolls back with an error under the row;
409 reloads the overview and shows the server message. A row whose health is
"attention" shows a red switch, never green.

The read-only `/manage/war-reminders/overview` route uses the same clan-management
permission and storage owner. It batches clan/settings/status reads and aggregates
only the newest scheduled receipt per current clan; test receipts and removed
clans are excluded. Raw Mongo IDs and actor IDs are not exposed. Each row carries the reminder
`revision` of its settings, computed like the editor's GET revision, also for a
clan with no stored settings. Clan revisions are computed from the same full
stored row as the existing editor.

`utils/war_reminder_health.py` interprets stored checks. Enabled reminders whose
checks are over three minutes old are flagged; a recent settings update gets a
three-minute awaiting-check window. A check older than the settings update cannot
verify new settings. Unconfirmed last scheduled deliveries remain flagged even
if later polling succeeds. Disabled clans are explicitly off. A missing destination
in a successfully loaded channel list is flagged for review. This is monitoring
information, not proof of future notification delivery.

See `docs/dashboard-interaction-standard.md` for design comparisons, shared rules,
and the manual/adversarial checklist. No notification renderer or Discord payload
changed in this overview release.

## Audit 239 polling decision (D7, Shaka 1073)

The worker's membership checks use `clan_exists`, projecting only `_id`. Web
editors retain the complete clan read for names, revision/history and copying.
Status changes (including failures and recovery) write immediately. Identical
status skips the write except for a `checked_at` liveness refresh at most every
120 seconds. The existing 180-second stale-check threshold is unchanged; no
second liveness storage owner is introduced. A backwards or missing timestamp
forces a refresh rather than silently preserving stale health.

At a fixed 60-second scan cadence a quiet healthy clan previously produced 60
status writes/hour; the fixture now produces 30/hour and remains Monitoring at
each scan. Polling still reads current persisted status before deciding whether
to write; this changes writes and payload size, not every Mongo operation count.
The stored timestamp can lag an individual scan by less than 120 seconds.
A settings edit invalidates old checks using the existing updated-at comparison.
The first successful scan of that edited configuration writes immediately
(Shaka 1087), even inside the 120-second liveness interval. A same-status write
can skip only when the stored check covers the scanned configuration's
`updated_at` and is less than 120 seconds old. The worker passes the timestamp
from the configuration it actually scanned; it does not certify a later edit.
Status records persist `settings_updated_at` and `settings_version` for the
configuration actually scanned (audit239 stale48). Health requires that exact
UTC/BSON-millisecond timestamp and version identity, as well as a fresh check.
An old in-flight scan writing at t+120 cannot certify a t+1 settings edit; the
first actual new-settings scan at t+180 still writes immediately. A later result
for an older version cannot overwrite the newer identity, even if its status
changed or failed. The storage owner conditionally matches its observed marker
and check timestamp, rereads on a race, and rejects older results. Same-ms edits
remain distinct through the existing monotonic settings version.
Within the same scanned settings identity, an older `checked_at` result cannot
replace a newer receipt, even when success/error status differs (audit239 late68).
The exact observed check timestamp remains in the conditional write; a lost
update or competing insert is reread and the older result is rejected. Thus a
late success cannot hide a newer failure, and a late error cannot regress a newer
healthy check. Dates compare at existing UTC/BSON-millisecond precision; equal
millisecond timestamps retain the previous tie behavior.
Legacy rows without markers remain unverified until one honest worker refresh
records identity; no migration or backfill is needed. Unknown/unbound results
cannot replace a bound status. Existing permanent delivery receipts are untouched.
Both the backend health reader and bot worker use this contract and must be
included in the eventual backend/bot release; this work performs no release.
In the settings-edit fixture, an edit at t+1 second causes the t+60 scan to write
once and show Monitoring; the same-status t+120 scan skips. Rare settings edits
add this immediate write; unchanged settings retain the 60-to-30 writes/hour
reduction and the existing 180-second stale threshold.
Cancellation, permanent delivery receipts and uncertain-send non-retry behavior
are unchanged. Fixture delivery tests do not establish live Discord delivery.

Supplemental audit 239 check (brief 27): status-field datetime equality uses UTC
instants at BSON millisecond precision. Default Mongo reads return naive UTC and
truncate sub-millisecond detail, while fresh war snapshots are aware UTC. Those
representation differences do not constitute a status change. Real changed
milliseconds, a new war end, an error/recovery or changed non-date values still
write immediately. Values are compared only; no client-wide `tz_aware` setting,
stored date migration, endpoint or health-policy change is introduced. BSON
round-trip fixtures verify both active-war and no-war 60-second polling produces
30 status writes/hour and maintains the existing liveness window.

The worker's periodic scan uses the process-local observation helper described
in [background-jobs.md](background-jobs.md). A partial clan scan does not advance
the whole-job successful completion clock. This adds no persisted health writes
and does not change the 120-second D7 status refresh, 180-second health window,
claim/receipt semantics or the handling of possibly accepted Discord deliveries.

## Clash maintenance (242)

A dedicated `coc.Maintenance` branch records the first `maintenance_since` in
`war_reminder_status`, preserves it through repeated failures/restarts, and reports
"Clash maintenance — Reminders continue when it ends." Expected maintenance logs
one warning per observed window per process, without a traceback. Successful
current-war reads feed the shared observation log. No polling request or scan
cadence was added.

Successful scans also save `war_start` in this same status document (approved by
Shaka1141). Recovery reads the **prior** identity before writing the new snapshot.
Unknown legacy identity or a different war cannot catch up: no migration/backfill
is needed. For a matching war still in battle day, occurrences from
`maintenance_since - 60 seconds` through strictly more than five minutes ago are
considered. Only the latest missed occurrence can send, and only while players
still have pending attacks. Earlier occurrences do not write delivery receipts or reserve occurrence keys.
Earlier offsets with existing delivery claims are excluded from the skipped list
and count. The completed catch-up logs one INFO line listing the unclaimed earlier
offsets and records their count in its existing status detail, with no new stored
field (Shaka1156). The existing window-clear CAS owns that line, so concurrent
scans cannot duplicate it. Existing
occurrence keys for actual sends, unique claims, settings/destination rechecks and
uncertain-send non-retry rules are retained. If the newest missed occurrence already has a claim in **any** state (uncertain,
sending, sent or skipped), nothing is sent; older occurrences are only listed in the INFO log and counted
in scan status detail. No fallback to an older event is allowed (Shaka1149). Normal occurrences within five minutes keep their normal path.

A delayed message keeps the normal text layout, adds "delayed by Clash
maintenance" on its first line and uses the actual time left when sending. Catch-up waits for a successful scan with shared `in_maintenance()` false after
the existing 90-second grace. A cached success inside that grace preserves the
paused window and claims nothing; no request or cadence was added (Shaka1149). A
successful recovery scan clears only its original `maintenance_since` by a CAS
matching settings identity and war identity; interrupted/provider or
transport failures retain it for reconciliation without replaying claimed sends.
No completed/different war sends, and fully attacked rosters send nothing.

Maintenance is a gold notice with black text in the family overview and clan
editor. Off, destination and unconfirmed-delivery states keep priority; maintenance
is not counted by Needs attention. Stale/settings-identity checks remain intact.
The editor reads the latest scheduled delivery independently of its bounded
history page; all existing delivery health behavior is preserved.
No new UI action, save, permission or notification endpoint was added.

An earlier event can become normally due after a same-war end-time shift. Because
catch-up did not claim that event, the normal path can send it once using its
unchanged occurrence key. Concurrent scans still compete on the existing unique
claim; catch-up never sends an older missed event. Regressions cover the shifted
end, concurrent scans, and every existing claim state for the newest event. The
unreleased1153skip-claim method, owner checks, health filtering and race exception
were removed rather than promoted to a CAS transition. No migration, transaction,
claim deletion or new stored field was introduced. Original-window clearCAS and
BSON/status safety remain. An exact five-minute threshold boundary retains the
window for the next existing scan, without sending early or adding a poll.

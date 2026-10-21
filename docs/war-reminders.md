# War reminders

Open **Family clans → select a clan → War reminders**. Choose a text or announcement channel, select whether to notify players with any attacks remaining or only players with zero attacks, and add times before war end. Times support whole minutes from 1 minute to 24 hours; quick choices are optional shortcuts. War-start notices are independently selectable. Save and enable each clan separately.

The clan directory has name/tag search, type filtering, and a scrollable list instead of pagination. On mobile, use **Change clan** to reopen the list.

## Message and test delivery

A reminder is a standard Discord text message, with no embed or Components V2. Its first line identifies the clan and spells out the remaining time, for example **Edrag Rush war reminder · 12 hours left**. Each Discord owner is mentioned once, with their pending accounts grouped beneath that mention. Each account row shows the existing Town Hall emoji, game name, player tag in inline code, and attacks used / available. Unlinked or ambiguously linked accounts appear in a separate group without a ping.

Messages split at Discord's 2,000-character limit, preserving complete account rows and owner groups where they fit. Oversized groups continue without a second mention, so an owner is pinged only once per reminder. Mentions are explicitly allowlisted; roles and everyone mentions are disabled. The clan heading and remaining time are part of the same text that triggers the notification.

**Send test to selected channel** sends sample data immediately, even with automatic reminders disabled and no active war. It uses the current form channel without saving. **Use my accounts in this clan** selects up to five linked accounts currently in the selected clan, with real names and Town Hall levels but explicitly simulated attack counts. Lookups are cached per user and clan for five minutes. If no linked accounts are in that clan, the form explains that instead of displaying accounts from elsewhere. **Mention me** is selected by default and pings only the signed-in dashboard user. The preview uses the same grouped message as delivery, including a fictional unlinked account in its own section with no mention. Recipient Discord settings still control push notifications.

## Runtime

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

The routine reminder view shows configured times, channel, audience, save controls,
and current status. Add reminder times, Preview & send a test, Delivery history,
and How reminders work are closed disclosures by default. Preview requests only
run while the testing section is open; closing it retains its choices and send
receipt. During a send it stays open. Uncertain or failed recent deliveries remain
flagged in the history summary even when its details are collapsed.

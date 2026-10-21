# War reminders

Open **Family clans → select a clan → War reminders**. Choose a text or announcement channel, select whether to notify players with any attacks remaining or only players with zero attacks, and add times before war end. Times support whole minutes from 1 minute to 24 hours; quick choices are optional shortcuts. War-start notices are independently selectable. Save and enable each clan separately.

The clan directory has name/tag search, type filtering, and a scrollable list instead of pagination. On mobile, use **Change clan** to reopen the list.

## Message and test delivery

A reminder is a standard Discord message with mentions in `content` and one ordinary embed. It does not use Components V2. Mentions are explicitly allowlisted; roles and everyone mentions are disabled. The embed contains the clan name, opponent, end time, player map position, Town Hall, player name, and attacks used. Large rosters are split into groups of 15 to respect Discord limits. Only pending players appear; linked Discord IDs are deduplicated within each message. Unlinked or ambiguously linked players are shown by game name without a ping.

**Send test to selected channel** sends sample data immediately, even with automatic reminders disabled and no active war. It uses the current form channel without saving. **Mention me** pings only the dashboard user; test messages never ping the sample clan members. The dashboard returns a Discord message link and stores a receipt. Recipient Discord settings still control push notifications.

## Runtime

`extensions.tasks.war_reminders` is registered in `main.py`. It checks enabled family clans every 60 seconds with at most four concurrent clan checks. The Clash client resolves regular wars and CWL; the live attack allowance controls eligibility. ClashKing and ClashPerk links use the existing combined link provider. Link-service failures leave a visible tracking error and retry on a subsequent scan, rather than treating an outage as an empty link list.

Settings, status, and delivery receipts use `war_reminder_settings`, `war_reminder_status`, and `war_reminder_deliveries` in the configured bot-config database with majority writes. Settings use optimistic version checks. Delivery claims use a unique Mongo `_id` per clan, war start, and reminder offset, so restart or concurrent workers do not replay the same occurrence. End-time changes do not change that identity.

Reminders up to five minutes late are eligible. Older reminders are skipped to avoid a burst after downtime; newly enabled clans likewise do not replay earlier times. Completed wars and fully attacked rosters do not send. A send that Discord does not confirm stays uncertain and is not automatically retried, since it may already have pinged recipients. A process interruption can leave a receipt at `sending`; the UI labels this delivery unconfirmed. Check the channel before manually sending another test.

## Deployment and validation

Deploy backend and frontend together through the existing manual deployment process. No migration or new environment variable is required. Existing clans start disabled. Build the dashboard with `npm --prefix web/cwl run build`; the bot must restart to load its new task and the web service must load the new routes.

Validated with reminder, clan-management, and war-operations backend tests; preview, channel-search, clan-filter, and Discord preview frontend tests; a production frontend build; and desktop/mobile inspection using mocked local clan data. Actual Discord notification delivery requires a test from the deployed dashboard.

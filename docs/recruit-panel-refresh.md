# Durable Recruit Questions panel refresh

The first successful question selection schedules a refresh for ten minutes after
that interaction. Later selections on the same panel do not slide the countdown.
Each source message has its own job in `settings.recruit_panel_refreshes` (following
the configured component-state database). This is separate from button_store,
challenge data, ticket records, and temporary editor sessions.

Schema version 1 stores source/application/channel/guild IDs, actor/recruit IDs,
the existing panel session ID, original due time, status, and a short-lived
interaction token. The worker polls every five seconds, including after startup.
Jobs have a one-day `expires_at` TTL and an index on status/next_at. Tokens are
removed on completion, failure, or detected expiry. Do not log rows, webhook URLs,
or raw exceptions containing tokens.

Delivery order:

1. Atomically claim a due job for two minutes.
2. Verify its original interaction response still identifies the source panel.
3. Render the same panel and send a private Components V2 follow-up.
4. Persist the replacement message ID and switch the job to cleanup.
5. Verify the replacement exists before deleting the original response.
6. Record completion and remove the token.

A failed send leaves the original panel intact. A later selection can start a
new countdown. Failed cleanup retries every 15 seconds while the token remains
usable; those retries only delete the old panel and never send another replacement.
A worker cancellation/restart leaves the Mongo job intact. Due pending jobs resume
on startup. Claimed jobs wait for their lease to expire before another worker can
handle them. A crash during an uncheckpointed send is ambiguous: preserve the old
panel and mark the attempt failed rather than blindly creating another replacement.

Discord interaction tokens last 15 minutes. Reserve five seconds at the end of
that window. If downtime outlasts the response window, expire the job without
deleting either panel. The next selection supplies a fresh token and countdown.
The bot cannot extend Discord's token lifetime. Tokens already invalid after a
long outage remain unusable even though Mongo retained the job.

No visible wording, layout, colors, media, dropdowns, or ticket targeting changes.
Timers that were only in memory before this deployment cannot be recovered; new
selections create durable jobs.

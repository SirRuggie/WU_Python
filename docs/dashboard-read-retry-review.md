# Dashboard read recovery — October 23, 2026

Clash player/clan/league reads now make at most three attempts for transport,
timeout, invalid JSON and upstream 500/502/503/504 failures, with 0.4s then 1s
backoff. Each attempt retains its 10s timeout. Only the failed lookup repeats;
successful accounts are not fetched again. Cancellation propagates. Permanent
upstream statuses (including 403/404/429) are not retried.

The shared frontend read helper covers dashboard GET requests and both export
paths. It retries network failures and HTTP 500/502/503/504 at most twice. An
upstream-handled response header prevents multiplying server retries. Auth,
validation, conflict and rate-limit responses are not retried. POST/PATCH/PUT/
DELETE, uploads, notifications and browser incident reports are not replayed.
Existing request-sequence protection and permission handling remain in place.

Saved signups continue to load independently. A complete upstream outage still
produces a recoverable error after bounded attempts; it does not become an empty
saved-signup list. This does not make upstream availability guaranteed. No stale
account snapshot is used as authorization for a write.

Verification: 316 frontend tests; 30 selected backend regressions, followed by
five focused retry/diagnostic-header tests including the added header regression;
production TypeScript/build passed. Injected browser failures verified two failed
account reads then success, one saved-signup read, zero writes, and sustained
outage with saved records remaining visible. Existing aiohttp warnings remain.
No live signup changes or test notifications were sent.

Deployment: narrow frontend patch over the last published member release; the
separate server-settings/BAND rollout remains pending. Only the dashboard web
service needs restart for the backend read adapter; the bot is not restarted.

## Deployment interruption follow-up

The reported reference 20256e3148d5 occurred at 15:14:14 during the web service's
15:14:06–15:14:15 deployment shutdown. The screenshot's concurrent seasons 502
is consistent with that service interruption, though it has no issue reference
for independent request correlation. The original 0.4/1s browser backoff was too
short to bridge this nine-second interval.

Gateway (502/504) and network failures now wait 1.5s then 10s before retrying,
retaining the three-attempt limit. Other transient HTTP failures keep their short
backoff; upstream-handled failures still do not multiply retries. A fake-clock
regression verifies recovery across a nine-second interruption. The complete
frontend suite passed (319 tests), and the production build passed. A subsequent
read-only live check loaded all 47 linked accounts; one lookup recovered after
roughly 11 seconds. This is a point-in-time check, not an availability guarantee.

This correction deploys static assets only, without restarting the web service
or bot. Avoid restarting services for future frontend-only changes.

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

# Dashboard issues

Settings → Dashboard issues is restricted to the two dashboard owners, in both
navigation and the API. Search by reference or Discord user ID. Technical details
and history limits are collapsed; refresh never repeats a failed action.

`utils/dashboard_issues.py` owns one bounded Mongo bot_config document,
`dashboard-issues-v1`. Each atomic append keeps the latest 500 receipts; the UI
shows only receipts from the last 30 days. No schema migration or signup changes.
The list survives process restarts. Old entries are rotated out, not a permanent
audit trail. Successful roster/signup actions retain their existing audit history.

Recorded: HTTP 5xx responses, rejected API writes (4xx), unhandled server exceptions,
and authenticated browser error/unhandled rejection/network reports. Normal signed-out
session probes are excluded. Records contain a random reference, timestamp, verified
session user ID if available, router template, method, status, fixed category and
server exception class. Never request bodies, query strings, cookies, tokens,
raw exception messages, browser stacks or arbitrary client text.

Browser reporting requires session and CSRF. Only fixed categories are accepted;
one report per member per minute, with a bounded in-memory limiter. Restart resets
that limiter, not stored receipts. Unauthenticated reports are rejected. UI prints
references as text; it cannot send Discord messages or replay failed work.

Mongo writes have a two-second diagnostic budget and fall back to safe service-log
receipts. This avoids replacing the original error if diagnostics fail. Offline
browsers and failures before authentication cannot submit browser reports. A fatal
process crash cannot run middleware. Browser reports are unverified signals. There
are no automatic Discord alerts or guarantee that every user-visible issue is captured.

Validation: backend tests cover fixed-owner authorization, CSRF, safe error references,
query/body redaction, preserved rejection status, storage outage, bounded history and
repository recreation. Frontend tests cover reference feedback and report throttling.
Isolated sample UI inspected at 320px, 390px and 1280px: no horizontal overflow;
search empty state, labeled input, focus indicator and collapsed disclosures checked.
No production signup, grant or notification was created for verification.

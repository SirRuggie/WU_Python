# CWL signup policy and member change review — 2026-10-21

Current clan category controls pool eligibility: accounts currently in FWA may
choose Lazy only. Non-FWA accounts may choose either pool. Historical signup
clan labels do not prevent a player who has moved out of FWA from choosing Main.
The server rechecks current membership for member, staff-member and direct-tag
signup paths. Unavailable family categories fail closed for Main; Lazy remains
available. Mixed batches are rejected before writes.

Members may withdraw or switch pools despite a working assignment, subject to
existing season-open/archive rules. A switch clears the working placement and
kept flag atomically; withdrawal removes the working entry. Published snapshots
remain historical. Existing ownership, CSRF, source-pool confirmation and
transaction checks remain. No notification is sent automatically.

Staff see unreviewed withdrawals and pool changes on the roster, including former
pool and placement. Durable roster audit events own this history. An additive
`signup_activity_reviews` table stores acknowledgment only; no existing data is
rewritten. Historical withdrawal events also appear until reviewed. The latest
100 pending events are loaded; reviewing them exposes older pending events.

Validation: 117 backend tests passed across signup, roster, participation sync,
participation, bonuses and raffle suites; 190 frontend tests passed. Production
build and war-reminder validation passed (existing bundle-size warning remains).
Reviewed member/staff authorization, CSRF, ownership, atomic mixed batches,
upstream category failure, stale move confirmation, duplicate withdrawal,
season-scoped acknowledgment and current-vs-historical clan category.

Isolated browser checks covered the FWA dialog, animation controls and reduced
motion, assigned-account switch, withdrawal, staff alerts and acknowledgment.
Inspected 390px, 320px and 1440px layouts. The 320px roster had no horizontal
page overflow. Dialog restores focus and supports Escape. No real signups or
Discord messages were changed for testing.

The requested Google Sheet is readable but has no player-tag columns. Weight
source changes are deferred at the owner's explicit request; the existing
weight source remains unchanged.

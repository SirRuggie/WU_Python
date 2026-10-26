# Selected-account balancing — October 25, 2026

Roster filters now include inclusive minimum/maximum weight in thousands and a
hosting-clan filter. Select all matching accounts is available up to the existing
50-account mutation limit. Balance selected opens a focused destination picker
and a server-generated preview. No preliminary unassign is required.

Balancing processes highest weights first, favoring the destination with the
fewest accounts of that exact weight, then lowest total weight, then lowest
occupancy. Existing unselected and locked accounts count toward those totals.
Pool, configured 15/30 capacity, and existing hosting weight boundaries apply.
The hosting maximum remains exclusive, as in existing auto-placement rules;
the account list's maximum filter is inclusive. This is a deterministic greedy
balance, not a promise of a mathematically optimal allocation or minimum total.

Locks are excluded by default. Explicitly included locked accounts keep their
locks after moving. Missing/unavailable source weights are skipped unless a
manual weight exists. Accounts that cannot fit retain their old assignments;
replanning reserves their slots before applying any other moves. Full clans can
exchange selected players. Unknown weights remain visible in preview totals.

The existing preview/apply endpoints accept an optional balance mode; normal
auto-placement remains unchanged. Apply recomputes the plan inside the existing
revision-checked transaction and rejects stale or altered plans. Audit and undo
use existing storage; no migrations, signup withdrawals, publishing, messages,
or notifications are performed. Old bulk-assignment clients keep their contract;
the updated UI explicitly sends its lock choice for server enforcement.

Bulk unassign and Clear clan assignments preserve signups. Clear clan lives under
Clan actions after choosing a hosting filter, explicitly covers the entire clan
regardless of other filters, and confirms the count/name and excluded locks.
Both use the shared dashboard confirmation dialog instead of a browser prompt.

## Review evidence

- 84 backend tests passed, covering existing roster and permission behavior,
  equal-weight distribution, full-clan swaps, lock overrides, unavailable/missing
  weights, mixed pool/range eligibility, capacity, altered/stale/replayed requests,
  malformed tags/options, member denial, and 100 deterministic randomized cases.
- 338 existing frontend tests passed; TypeScript/Vite production build passed.
- Isolated local app, real handlers and disposable SQLite, 45 sample accounts:
  three 15-account clans each previewed 2,655,000, one locked account skipped;
  applied balance and undo succeeded with 45 signups retained.
- Clear-clan cancel and confirmation exercised: 14 placements cleared, one lock
  retained, all 45 signups retained, followed by successful undo.
- Minimum 179k filter showed nine accounts. Select all 45 matching accounts
  operated across three pages. Preview/disclosures, Escape and trigger focus
  restoration checked. 390px screenshot and 320/1280px layouts inspected;
  no document overflow, inspected dialog buttons were 44px tall.
- Native browser confirmation stalled the browser test, motivating replacement
  with the existing accessible dashboard confirmation component. The replacement
  was verified in a fresh tab. No production roster changes or live sends tested.

Existing aiohttp AppKey/deprecation and Vite bundle warnings remain. Exact totals
can differ with locks, unequal capacities, clan rules, or missing weights. This
review is scoped to these roster controls, not a certification of the entire app.

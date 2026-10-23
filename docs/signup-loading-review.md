# Member signup loading review — 2026-10-23

## Findings and changes

The access refresh replaces the session object on focus and every minute. Signup
and season effects depended on that object, restarting reads even for the same
member. The signup loader hid SavedSignups while loading, losing its local edits.
Both effects now depend on the member ID. Access checks and season polling remain
active. Switching member or season resets signup data; request generations still
reject responses after leaving the view or starting a newer load.

Saved signup reads now update the page before the linked-player lookup completes.
Only one contextual loading message is shown. Pool changes remain disabled until
the account lookup completes. Failed lookups appear in My signups with a retry,
rather than silently disabling controls. A successfully checked but missing link
has a per-account explanation; an upstream failure is not described as unlinked.
Explicit refresh still asks before discarding draft pool changes.

## Evidence

- 290 frontend tests passed, including missing-link/loading/failure rendering.
- 16 backend signup policy, signup anchor and account snapshot tests passed;
  existing aiohttp AppKey warnings remain.
- TypeScript and production build passed.
- Isolated browser fixture held the account response while returning signups:
  saved records rendered with one checking status and disabled actions.
- Staged a pool change, triggered focus/access refresh, and observed the draft
  retained. Across three auth/season reads, linked accounts and signups each had
  only one read. No mutation was submitted.
- Failed account lookup: saved records remained visible, provider error and retry
  appeared; retry restored eligible actions. Missing-link reason only appeared
  after a successful lookup.
- Confirmed explicit refresh discarded a staged change after confirmation.
- Inspected 320px, 390px and 1280px layouts, including failure and pending changes.
  Native buttons and status/alert semantics remain; no new modal or interaction.

## Limits

The uploaded recording shows taps on pool-change controls without feedback; it
cannot establish which live provider response disabled those particular records.
The duplicate-loading trigger is established from code and reproduced with local
requests. Initial lookup still depends on link providers and Clash player fetches
(five concurrent requests); this change does not promise a fixed live latency.
No live signups, Discord messages, permissions or roster data were changed in QA.
No storage, authorization, placement visibility or notification behavior changed.

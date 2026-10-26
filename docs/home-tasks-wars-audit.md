# Home → Tasks → Wars audit — October 26, 2026

## Findings and fixes

- Clan-specific task links previously kept filter/type only in React state. Browser
  Back/Forward could reuse another visit's context. History entries now carry a
  validated tag and war/CWL kind, scoped to their destination. URLs and OAuth
  destination rules are unchanged; this is browser-entry state, not shareable query
  parameters. The task component remounts when the handoff kind changes.
- Home and Tasks searches/sorts/pages, plus Wars search/type/scope, previously reset
  on leaving. View-only state is retained in this tab, keyed by user and destination;
  Wars distinguishes visits so a fresh explicit CWL link always opens CWL. Account
  selection in Tasks retains its existing preference rules. Home signup selections
  are deliberately not stored by this helper. Identity changes clear remembered state.
- These three pages now restore their last scroll position after data is ready.
  Native scroll restoration raced the initial implementation; the browser journey
  caught this, and restoration is now controlled only while these pages are mounted.
  A shorter updated list can naturally clamp a previous position.
- Tasks' instruction to open Wars is now a direct clan-score navigation action.
  A populated task search has an explicit Clear search action. Existing task cards,
  account selectors, notification settings and clan links remain intact.

## Scope and verification

Reviewed Home loading, cached and partial account display, signup entry safeguards;
Tasks loading/partial/unavailable state, selection, search, sort, paging and refresh;
Wars membership scope, private-log exclusion, CWL handoff and return navigation;
shared history cancellation and destination allowlists. No server queries, game
schedules, account links, permissions, signup mutations or notification delivery
logic changed.

348 frontend tests passed (including history context validation and round trips),
28 activity/task backend tests passed, TypeScript/Vite production build passed.
Existing aiohttp warnings remain. Automated history tests retain unsaved-edit
cancel/forward-stack guards. No new live signup or notification was sent.

Isolated real-browser fixture: 30 fictional accounts, Home search/page 2/scroll →
Tasks search/page 2/scroll → Wars search → clan-filtered Tasks → clear search →
Back through each page → Forward. All searches, pages and positions restored.
Repeated Events → CWL navigation after switching a previous visit to regular wars
still opened CWL. 390px/320px Tasks views had no horizontal document overflow;
320px screenshot inspected for new link/reset controls. Desktop checks used 1280px.

Limitations: view-only memory lasts for this loaded tab, not across reloads; existing
saved Tasks preferences still persist as before. Physical phones and full assistive
technology coverage were not tested. Fixture/API regression evidence does not prove
live game-provider availability or push delivery. Broad redesigns remain deferred
pending the user's navigation feedback.

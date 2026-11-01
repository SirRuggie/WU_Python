# Member time zones PR 2 review checkpoint

Scope: shared nickname parser/import, existing-permission member page, optional
profile/nickname edits and bounded restartable Standardize receipts. The backend
uses public provider methods and the existing dashboard-to-bot request path.
Discord transport remains in the Warrior extension; storage and receipts have
explicit owners. No production import or nickname change has been performed.

Current increment checks: 52 focused backend cases, 1,240 frontend cases,
TypeScript/build and four real-Mongo cases passed. The owned Mongo stopped.
The new browser stage passes 360×800 and 1440×1000 with no overflow, no page
errors, all scoped button/select/summary targets at least 44 px, and focus restored
to the edited row. Conflict input is retained; unticked members are excluded;
uncertain results have no automatic retry. Screenshots were inspected. Browser
writes were confined to the named isolated fixture's login/save/preview/confirm
routes. This is simulated UI transport, not live Discord proof.

Not READY: integrate PR 1 rework and released polish, then finish full guarded
backend and every layout stage, adversarial review and required mutations on the
final source. Release also waits for Ruggie's real Warrior test. Existing profile
rows and unrelated work are preserved throughout.

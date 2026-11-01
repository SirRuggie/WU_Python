# Member time zones PR 2 review checkpoint

Scope: shared nickname parser/import, existing-permission member page, optional
profile/nickname edits and bounded restartable Standardize receipts. The backend
uses public provider methods and the existing dashboard-to-bot request path.
Discord transport remains in the Warrior extension; storage and receipts have
explicit owners. No production import or nickname change has been performed.

Integrated checkpoint: 5,550 guarded backend cases (30 skips, 224 subtests),
1,262 frontend cases, TypeScript/build and four real-Mongo cases passed. The owned
Mongo stopped. All nine integrated layout stages passed. Seven required mutants
and an additional consumed-confirmation replay mutant were killed; the real-Mongo
baseline passed. Stronger regressions check an unticked manageable member and an
old nickname changing inside the lease callback.
The new browser stage passes 360×800 and 1440×1000 with no overflow, no page
errors, all scoped button/select/summary targets at least 44 px, and focus restored
to the edited row. Conflict input is retained; unticked members are excluded;
uncertain results have no automatic retry. Screenshots were inspected. Browser
writes were confined to the named isolated fixture's login/save/preview/confirm
routes. This is simulated UI transport, not live Discord proof.

Final integrated source includes PR 1 prompt 66. The matching dashboard rename
path now preserves real hikari nickname field errors too, with a real-error
regression proving no profile commit after Discord refusal. Final guarded backend:
5,564 passed, 30 skipped, 224 subtests. Fifty-five focused cases pass. Frontend
source is unchanged from the passing 1,262-case integrated run and build; the nine
layout stages and four real-Mongo cases remain applicable. Seven required mutants
and the additional real-Mongo consumed-confirmation replay mutant were killed.

Completion review checked existing member_roles authorization in HTTP and fresh
worker context, guild/actor/target binding, bots and hierarchy, malformed fields,
partial directory/player data, exact old nickname and revision inside the edit
lease, unticked members, consumed confirmation retries, one active run, restart
uncertainty and bounded receipt pruning. Only unattempted children resume; an
uncertain Discord edit is never replayed automatically. The preview is complete
rather than silently truncated, and unrelated profiles/receipts remain owned by
their existing storage classes.

Harness corrections: navigation expects Member time zones; signup-card route
callbacks finish before page close. Earlier Chrome socket-path, sandbox bind and
teardown failures were corrected before the passing nine-stage run. UI evidence
uses fake HTTP transport; real-Mongo cases use an owned local daemon that stopped.
No test proves live Discord delivery. Production import and Standardize have not
run. Release is gated on PR 1 LIVE plus Ruggie's real Warrior test and Claude's
verdict; only authorized staff will press Standardize in production.

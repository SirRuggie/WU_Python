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

## Rework67/233 checkpoint — not READY

The last recognized zone suffix is removed from a name; earlier pipes remain.
Unknown/no-zone suffixes retain the complete nickname and start unticked with
Needs review. The editor does not overwrite an existing nickname with a late
account suggestion. Import maps named daylight zones to standard profile offsets;
Compare keeps literal offset meaning. Both parsers now recognize the two approved
hand styles (tight pipe/flag and non-menu GMT+5:45), with shared vectors.

Recovered uncertain requests receive a completion timestamp. Legacy missing
completion times are established once before the twenty-receipt/thirty-day prune,
so a new uncertain receipt is not lost or continually renewed. The stale Mongo
assertion is corrected. Five actual Mongo cases pass, including lifetime repair;
the owned daemon stopped.84 focused backend and20 targeted frontend cases,
TypeScript/build pass. These are current runs, not applicability inferred from
an earlier revision.

Both nickname transports now journal attempted/confirmed/refused/unconfirmed
outcomes with source, actor, target and old/new values. Repr formatting prevents
newlines from becoming extra journal entries; no request is retried. Logging is
not proof of delivery unless Discord confirmed the call. No production code was
activated and no nickname edit was performed by Codex.

Still pending: Stop and complete skipped-result reporting, compact/paged top-action
UI, conflict reload/reapply and fresh explicit retry IDs, final regressions/layouts
and required rework mutations. PR119 remains unready and human-gated. Prompt68
starts on an independent branch now that prompt65 is READY.

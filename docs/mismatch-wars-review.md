# FWA mismatch wars review

Prompt 49 removes opponent-based strike exclusions. New wars against NO WAR count
normally. Existing no-attack history is retained and the 50 previously removed
strikes are not restored. Settings no longer expose/accept the old list; settings
writes clear it. No production settings have been changed during development.

## Confirmed war-plan source

Source verification found Tasks' scraper is unsuitable: it checks clan/end within
60 seconds, omits opponent identity, and maps mismatch to unknown. Claude handoff
175 approved a dedicated durable receipt owner instead. Tasks remains unchanged.

The existing `/war-plans` command reads the official current war before its
existing Discord post. Only preparation/inWar with the exact clan and a matching
typed opponent name can bind; notInWar, API failure or conflicting identity leaves
an unbound receipt. The receipt is inserted only after the existing message is
confirmed. Receipt failure reports that the message posted but recording failed;
it never sends again. Immutable guild/message identity handles duplicates, with
collection selection/indexing and receipt matching owned by WarPlanStore.

At finalization, lookup is exact guild + clan tag + war end, and every candidate
must have the same opponent tag and a consistent preparation start. Posts before
preparation or after the end, unbound candidates, conflicting opponents/start
windows and tied latest conflicting outcomes give normal strikes with an explicit
reason. Otherwise the latest confirmed correction wins. Renaming the opponent
after posting does not affect the tag match. Missing receipts use `War plan not
found`; unavailable/malformed reads use `War plan check failed`; ambiguity uses
`War plan unclear`. Historical wars without receipts count normally.

## Strike and UI behavior

Only exact family type FWA uses the rule. Mismatch is neutral for every participant:
the whole war neither advances nor breaks the streak, including participants who
attacked. Win/lose/blacklisted and non-FWA wars retain normal rules. Newly imported
wars use the same classification; stale import previews that would change a
mismatch to a normal outcome require a fresh preview. Already-finalized receipts
are never relabeled or reprocessed. CWL, expiry, leave/exemption behavior, thresholds,
permissions and request idempotency remain intact.

Find war and History show Mismatch war (no strike), an icon, and the plan reason.
The status filter supports mismatch without discarding pagination/search context.
Synthetic 360/1440 browser checks cover history and filtering; no live posts/DMs
were sent during validation. Existing command template tests preserve content and
no-ping behavior. This does not prove live Discord delivery.

## Release gates

After Claude acceptance, back up Mongo/SQLite and record active strikes and settings
before activation. Clear only the legacy no_attack_opponents list using the public
settings writer with the observed revision and unchanged exempt roles/threshold.
Report the list-entry count cleared plus the expected settings revision/audit
metadata change. Compare protected records and active strikes before/after; the
50 removed strikes must stay removed. Do not reprocess old wars. Retain the old
frontend/backend/bot revisions and rollback assets, verify imports/readiness/public
hashes, and wait for Claude's read-only smoke. No live Discord test sends.

## Validation

Full integrated backend/frontend, TypeScript/build/layout and the four required
mutations are recorded with the READY handoff. Before current-main integration,
5,343 backend tests passed (21 skipped, 221 subtests), 1,137 frontend tests passed,
and full layout passed. Review evidence is retained in `.local/mismatch-*` and
`/tmp/mismatch-*` on the review host. The standalone synthetic strikes preview is
served separately from production; its routes/data are fixtures only.

Current-main integration includes visitors-1 and its release documentation. The
integrated frontend has 1,142 passing tests and a successful TypeScript/Vite build.
The four policy mutations were rerun and killed. The refreshed standalone browser
at 360/1440 passed (12px minimum text and no undersized tested controls/overflow);
the receipt/template focused suite passed 41 tests. The final network-isolated
backend suite passed 5,357 tests and 221 subtests, with 21 skipped; full layout
passed. Two legacy sequence-delivery tests depended on the real month boundary;
their module now uses a fixed mid-month clock, and all six module tests pass.
No production behavior was changed for that fixture correction.

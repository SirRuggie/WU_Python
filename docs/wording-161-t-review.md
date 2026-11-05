# 161-T ticket wording review

This branch is based on `82400fbfafad39d003c85d64085b1473f5778c54` and isolates ticket wording from the integrated 161 draft. The 43 apply items are indexed in `wording-161-t-ledger.json`. The ledger records 38 applied, three skipped-unused, one skipped-unconfirmed and one item superseded by specific items. An independent source review recomputed the inventory, named exclusions and exact changed-string evidence. The separate declined ticket items TK-5, TK-16, TK-25 and TK-43 retain their 82400 text.

The six additional live Choose→Select substitutions are lexical-only under 170 §3.3 and §2(c); TK-1 records their complete before/after values and locations, together with the earlier settings-panel lexical substitutions. The held `_hub_picker_placeholder` is skipped-unused under `docs/unused-code.md` §B.

The ticket resolution recognizer preserves the exact current, previous, legacy and test notification markers under decision 608. Its tests retain the non-resend and delivery-guard checks. This does not prove live Discord delivery.

The ticket-focused suite passed 669 tests with one skip after the baseline title restoration. Earlier failed logs and the setup-only import correction are retained in the private worktree evidence. An independent matcher reviewed 153 non-resolution and 10 resolution changed strings with zero unexplained differences after 20 documented context/override cases. Five targeted mutations killed the old approval and denial marker, expired flag, invalid-action text, and foreign-author guards. Final backend, war and owned-boot results must be bound separately to the final commit before READY.

## 161-X follow-up: no exact approved copy

- TK-10 is superseded by the specific items listed in the ledger; the previously identified unused locations remain held.
- The Rite-of-Passage default text in `extensions/commands/tickets/rite.py:30,37` contains “the path you choose” and “Choose this path”. No exact replacement for those full sentences was approved. The separate declined TK-43 text remains unchanged.
- `extensions/commands/tickets/console.py:1758` contains a channel-access diagnostic using “the bot”; no exact replacement for that full diagnostic was approved. Channel ownership and relocation checks remain intact.
- TK-32's two result notices in `extensions/commands/tickets/close.py:288,356` retain “FWA default message” and “Main default message”. The four specified menu labels are updated; an optional wording-consistency decision has no exact approved result text.

This list describes deferred copy only; no production messages or settings were read or changed by this branch.

- `utils/ticket_staff_content.py:23` contains the validation message “Choose Main or FWA.” Its user-facing reachability and an exact replacement are not established in this ticket part; it remains unchanged for 161-X review.

- The separate console title `Approval not completed` is retained at 82400; TK-33 approves the slash-response template, not a replacement for this title. An alternative title is blocked on 161-X until an exact item exists.

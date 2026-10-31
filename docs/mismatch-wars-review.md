# Mismatch wars — development checkpoint

Prompt 49 replaces opponent-based exclusions with a forward-only FWA mismatch
rule. This first increment removes the old settings control and HTTP field,
ignores legacy opponent exclusions during war processing, and clears that legacy
list on settings writes. Existing no-attack history and removed strikes remain
untouched. Release will explicitly clear the remaining stored settings with
before/after evidence; no production data has changed during development.

Source verification found that Tasks' `load_fwa_records` reads the latest scraped
`fwa_points` document. `matching_outcome` checks only clan and end time within
60 seconds; it does not check the opponent and maps mismatch/unknown to unknown.
The `/war-plans` command posts the chosen outcome without saving an outcome
receipt. Only the Blacklisted path persists blacklist metadata. This source
cannot reliably establish staff-selected mismatch plans or historical plans.
Handoff QUESTION 253 proposes durable, confirmed-post war-plan receipts and
explicit identity/window matching; implementation of that source awaits review.

This checkpoint is not READY and must not be deployed. The FWA mismatch matcher,
streak-neutral history/filter rendering, final release migration, mutations and
full batch verification remain outstanding.

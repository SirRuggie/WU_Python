# Compare Clans time zones

Time zone is an optional Compare sort. It never moves an account or changes the
other sort modes. Known offsets sort west to east, unknown labels alphabetically,
then owners without a zone. Owner nickname and ID group their accounts before
weight descending. The parser uses the final spaced pipe, removes emoji flags and
preserves unknown labels; ambiguous abbreviations and literal offsets are listed
in roster-ui-patterns.md. Unknown and missing zones do not render a card label.

The existing editor-only roster read includes only its own owner IDs' cached
nicknames. It never waits for Discord: one bounded background task refreshes a
shared directory snapshot, with a two-minute failure cooldown and cancellation
on application cleanup. Existing bounded metadata polling merges names without
replacing assignments, weights or drafts, and rejects stale revisions. Unauthorized
requests do not receive the map. No nickname, signup, assignment or notification
write is added.

Validation: 1,225 frontend tests/228 files, TypeScript and build; 47 relevant
backend tests with external DNS/socket/default service-port guards; all seven
integrated build/layout stages passed. Three sort mutants were killed: blank
zones first, owner accounts split by weight, and unknown labels treated as blank.
The isolated browser fixture checks 360x800 and 1440x1000, including three desktop
columns, owner grouping, known/unknown/blank order, zero global overflow, and
single-line 16–17px metadata. External requests are blocked and there are zero
non-login API writes or console errors. Screenshots were visually inspected.
This is not an assistive-technology audit or proof of live directory coverage.

Private evidence is under .local/p61-final-evidence. Before release, count known,
unknown and missing zones for distinct roster owners through a read-only check.
The branch is stacked on PR109 and must be rebased/retargeted after that merges;
PR B's A-sweep gate and release take priority. No production deployment is implied.

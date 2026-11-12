# Lazy CWL bonus review

Lazy qualification is four or more attacks, or three or more attacks with at
least eight stars. Main retains its configured minimum-attack policy. These are
staff dashboard decisions; the bot does not award medals inside Clash of Clans.

## Evidence and review

Participation uses the recorded hosting clan's CWL group and war player tags,
not the player's current home clan. The existing participation worker checks every
15 minutes when enabled and retains validated observations. Returning home does
not erase that evidence. A result which disappears before any successful capture
cannot be reconstructed; unknown evidence is shown explicitly.

The three manual flags are Missed Sync, Lingering, and Left Family during CWL.
Each normally excludes the account for that dashboard season. Staff can include
an otherwise excluded account with a nonempty reason. The review records the
actor and timestamp and preserves append-only before/after history.

A Clash account confirmed for a Lazy bonus in any of the three preceding
calendar CWL months sits out the current month. Earlier Lazy bonuses only; a
Main bonus does not count. Example: a bonus in January makes the
account ineligible for February, March and April; it can enter the May lottery.
This uses non-voided dashboard confirmations across dashboard seasons, not
inferred in-game medal history. Earlier unrecorded awards cannot be inferred.
The three Lazy bonus rules: follow the Lazy CWL rules; play 60% of the event (4+
attacks, or 3 attacks with 8+ stars); no bonus in the previous three seasons.

A reason can override participation, infractions, or this sit-out. For an
account whose results were never captured ("Not checked"), a reason also covers
the missing results; the review audit logs it. Partial results stay blocked. It
cannot override malformed data, a mismatched/stale assignment, a non-Lazy host,
or a second bonus to the same account in the same month.

A hosting clan counts as Lazy for a season when its season pool (Build roster) is
Lazy. The directory pool is the fallback. A clan archived after the season still
counts for that season.

## Manual candidates and weighted draws

Add player by tag verifies the player and linked Discord owner through the
existing providers. An active Lazy hosting clan and reason are required. This
adds a bonus candidate only; it never creates or moves a signup or placement.
An existing signup must be reviewed at its actual assignment. Removing an extra
candidate preserves its audit; clearing its eligibility exception reinstates
normal exclusion rules.

FWA Rep accounts (2026-11-12) replace the earlier FWA Rep role rule. Staff keep
one family-wide list of player tags in the Settings sheet ("FWA Rep accounts").
The list is not saved per season; it stays until staff change it. Only listed
accounts receive two tickets in Lazy draws; every other Lazy account receives
one. This includes manual candidates (Add player by tag): a listed tag gets two
tickets there too. Main draws do not use the list. Odds need no Discord call, so a Discord
outage cannot block or change a draw.

Add verifies the tag with the official Clash API and stores the player name,
Town Hall and linked Discord owner (if any) at that time. Each row has an
optional note of up to 40 characters, for example "REP for Edrag Rush/420".
Rows are grouped by linked Discord user, as in Build roster; unlinked accounts
show last under "Not linked". Add, note edit and remove need the Bonuses grant,
a non-archived season and the current bonus revision; note edit and remove also
need the row revision. `bonus_raffle_rep_account_audit` logs every change with
the actor and before/after values. A note edit does not change odds, so it does
not make a saved draw stale. The list started empty at release; no data was
copied from the role.

Drawing samples tickets with a cryptographic system random source and removes
all of a winner's tickets. An account can win only once. If available slots meet
or exceed the candidate count, all eligible accounts win without random
selection. Two tickets are twice the selection weight, not a promise of exactly
twice the final inclusion probability when several winners are drawn.

## Persistence and safeguards

`utils/cwl_bonus_raffle_store.py` owns the additive tables for the FWA Rep
account list, account reviews, manual candidates and their audits, plus existing
draws and receipts. The older per-season role tables (`bonus_raffle_settings`
and its audit) stay in the schema to preserve their data; nothing reads them.
The dashboard Store transaction publishes the complete database to its existing
Mongo state owner before acknowledging mutations. No second weight/roster store
is introduced. Existing recovery and backup coverage includes these tables.

Writes use the bonus revision to reject stale edits. Preview fingerprints include
eligibility, identities and each account's FWA Rep odds. Approval revalidates the
saved draw; it never silently rerolls. Same-month account uniqueness and the
existing per-clan draw constraint prevent duplicate awards. Old Main snapshots
retain their approval behavior; pending old Lazy snapshots must be cancelled and
reviewed under the new rules. Lazy snapshots now carry `rules_version` 3; a
pending version 2 draw (role rule) must be cancelled and drawn again. Approval
fails when a listed account's odds changed since the draw. Approved historical snapshots remain readable.

Approval and announcement remain separate. Delivery retains durable receipts;
uncertain Discord sends are not automatically retried. No live messages or real
bonus draws are needed to test this workflow.

`GET /api/cwl/seasons/{season_id}/bonus-status` is a light read-only summary per pool and
hosting clan (candidates, rule counts, results, allowance and draw state). It makes no Discord
or Clash call; Lazy counts omit FWA Rep weighting, and it uses the bonus page's editor grant.

Did not join (2026-11-11): an assigned account with raw source status `no_data`
(`source_no_show`) is a hard Lazy exclusion, "Did not join the CWL clan", that a
staff reason cannot override. Main excludes it with the same reason without
blocking the draw, and the Bonus status counts it as captured.

## Staff flow (prompt 229)

The staff flow has five steps: Results, Rules & count, Draw, Approve, and
Announce & award. The draw preview loads when Draw opens. The FWA Rep accounts
and the capture settings are in the page ⋯ Settings. Saved histories are in
Exports. The rules above do not change.

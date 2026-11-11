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

A Clash account confirmed for a bonus in any of the three preceding calendar
CWL months sits out the current month. Example: a bonus in January makes the
account ineligible for February, March and April; it can enter the May lottery.
This uses non-voided dashboard confirmations across dashboard seasons, not
inferred in-game medal history. Earlier unrecorded awards cannot be inferred.
The three Lazy bonus rules: follow the Lazy CWL rules; play 60% of the event (4+
attacks, or 3 attacks with 8+ stars); no bonus in the previous three seasons.

A reason can override participation, infractions, or this sit-out. For an
account whose results were never captured ("Not checked"), a reason also covers
the missing results; the review audit logs it. Partial results stay blocked. It
cannot override malformed data, a mismatched/stale assignment, a non-Lazy host,
or a second bonus to the same account in the same month. Discord role evidence
must also be available before eligible accounts can enter the draw.

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

The selected representative role defaults to `769130325460254740`. Eligible
linked members with that role receive two tickets per account; others receive
one. Preview, draw, and approval resolve fresh guild role evidence outside the
DB transaction, then bind it to the exact role and user identities. Failure to
verify eligible accounts blocks the draw, rather than silently reducing odds.

Drawing samples tickets with a cryptographic system random source and removes
all of a winner's tickets. An account can win only once. If available slots meet
or exceed the candidate count, all eligible accounts win without random
selection. Two tickets are twice the selection weight, not a promise of exactly
twice the final inclusion probability when several winners are drawn.

## Persistence and safeguards

`utils/cwl_bonus_raffle_store.py` owns the additive tables for settings, account
reviews, manual candidates and their audits, plus existing draws and receipts.
The dashboard Store transaction publishes the complete database to its existing
Mongo state owner before acknowledging mutations. No second weight/roster store
is introduced. Existing recovery and backup coverage includes these tables.

Writes use the bonus revision to reject stale edits. Preview fingerprints include
eligibility, identities, settings and role evidence. Approval revalidates the
saved draw; it never silently rerolls. Same-month account uniqueness and the
existing per-clan draw constraint prevent duplicate awards. Old Main snapshots
retain their approval behavior; pending old Lazy snapshots must be cancelled and
reviewed under the new rules. Approved historical snapshots remain readable.

Approval and announcement remain separate. Delivery retains durable receipts;
uncertain Discord sends are not automatically retried. No live messages or real
bonus draws are needed to test this workflow.

`GET /api/cwl/seasons/{season_id}/bonus-status` is a light read-only summary per pool and
hosting clan (candidates, rule counts, results, allowance and draw state). It makes no Discord
or Clash call, so Lazy counts omit role weighting, and it uses the bonus page's editor grant.

Did not join (2026-11-11): an assigned account with raw source status `no_data`
(`source_no_show`) is a hard Lazy exclusion, "Did not join the CWL clan", that a
staff reason cannot override. Main excludes it with the same reason without
blocking the draw, and the Bonus status counts it as captured.

## Staff flow (prompt 229)

The staff flow has five steps: Results, Rules & count, Draw, Approve, and
Announce & award. The draw preview loads when Draw opens. The FWA Rep role and
the capture settings are in the page ⋯ Settings. Saved histories are in
Exports. The rules above do not change.

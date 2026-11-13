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

Staff call the flags and the reason "Infractions". They are edited in the player
Details sheet on Results & bonuses (Lazy players with a hosting clan, needs the
Bonuses grant) and in the Infractions panel in the clan steps (player name or
card ⋯ "Infractions"). Both use the same `account-review` PATCH and revision.
The list loads only `bonus-status`; Details reads the season's `bonus-raffle`
data once when it opens and replaces it after a save; a save also rereads
`bonus-status`, so the clan option's "x of y meet" updates. Details has one
footer Cancel and Save: Save writes the changed notes, then the changed
infractions, and names the part that failed ("Notes not saved", "Infractions not
saved"). After the clan's draw is saved, approved or sent, and in archived
seasons, the flags are read only. Main has no Infractions. The clan steps cards
show one chip per set flag and "Staff reason"; the overview cards show none.

A Lazy win from either a non-voided dashboard confirmation or the imported
winner history starts a sit-out. Each season's Lazy hosting clan has a saved
**Sit-out after a win** length: None, or 1–6 calendar CWL months, default 3.
The account's hosting clan in the new draw decides the length; the old winning
clan does not matter. Main never has a sit-out. An October win with length 2
sits out November and December; with length 3 it also sits out January, and
can enter in February. New seasons copy each hosting clan's length with its
season rules. Settings requires Bonuses access, a non-archived season and the
current bonus revision; every changed length records actor and before/after
values in `bonus_audit`.

Results & bonuses Lazy list, clan-step cards and Details show the shared neutral
**Prior winner · Oct 2026** chip only while the sit-out excludes the account.
Details also shows **Eligible again: February 2027** for the current hosting
clan's length. A staff exception removes the chip. Build roster has no chip.

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

1 per member and no sit-out (prompt 237, 2026-11-13): each Discord member can
have only 1 FWA Rep account. Adding a second tag for the same linked owner is
refused (409 "This member already has an FWA Rep account. Remove it first.");
an unlinked account counts alone. Rows added before this rule are kept: a
member with 2+ listed accounts shows "Keep 1 account" in Settings, and every
listed row keeps x2 and the exemption until staff remove the extras. A Lazy
account on the list at evaluation time does not sit out after a win
(`sit_out_exempt`, chip "FWA Rep · no sit-out"); removing it from the list
restores the normal sit-out from its last win. Infractions, the participation
rule, did-not-join and one bonus per account each month still apply. A list
change between draw and approve fails approval (`three_cycle_cooldown` and
`is_representative` are compared).

"Find Clan Rep (x2 odds)" (2026-11-12) helps staff find accounts: it lists
Discord members with the FWA Clan Rep role (`769130325460254740`, the same role
as the FWA war messages) through a read-only
`GET .../bonus-raffle/clan-rep-members`. Selecting a member loads their linked
accounts through the existing staff-signup accounts read. Each account shows
"Add for x2" (saved with the optional note box) or "x2 · Listed". Only the tag
is saved; the role never decides odds. "Or add by player tag" stays for
unlinked accounts.

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
reviewed under the new rules. Lazy snapshots now carry `rules_version` 4 and their hosting clan's sit-out length; a
pending version 2 draw (role rule) must be cancelled and drawn again. Pending version 3 draws retain their original three-month, non-voided confirmation-only rule. Version 4 approval blocks with “Rules changed · draw again” when a length or imported win changes sit-out eligibility; it never rerolls. Approval
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

## Imported history (Exports & history D2–D5, 2026-11-12)

`bonus_imported_winners`, owned by `utils/cwl_bonus_raffle_store.py`, stores
season/month, Lazy pool, verified player tag and official API name, old clan
tag/name, source `import`, actor and timestamp. `(cycle, player_tag)` is unique;
repeat wins in different months remain separate. No fake batch or publication
is made. The complete Mongo checkpoint and SQLite online backup include this
table and `lineup_rules.sit_out_months`. The additive column defaults to 3;
existing rules and data remain intact. No production history is imported by a
code release.

`tools/import_prior_lazy_winners.py FILE.tsv --database PATH` defaults to a
read-only dry run, using only the public official Clash player provider. It
prints month, clan, tag, pasted name, API name and status. Tags decide identity;
pasted names never match accounts. Invalid TSV/tag input, unavailable API data
and mismatched player identities stop the operation. A genuine not-found tag
stops apply unless `--skip-missing`; each skipped month/tag is listed.

`--apply --actor ACTOR` creates missing archived history months with closed
signups, no signups, roster or publication, and only the TSV's Lazy hosting
clans. New directory clans are archived; existing names are never changed.
Existing same-label months are reused and a conflicting existing month binding
aborts the entire transaction. Month binding uses participation sync settings;
no member-season selection changes. Reapply inserts zero duplicate winners.
All history/clan/month/winner writes share one Store transaction. There is no
Discord call and no UI import action.

For fixtures, `--fixture-players JSON` uses an explicit isolated tag/name map.
Without it, apply obtains the existing database lock and Mongo checkpoint lease,
restores authoritative state and publishes through the Store transaction. It
requires separately authorized maintenance coordination with the dashboard
writer. Do not run either production dry run or apply without Ruggie's own
words authorizing it and a verified DB backup; prompt 230 grants neither.


Prompt230 rework (Shaka1014): only seasons newly created by the importer receive
`seasons.history_only=1` (additive boolean, existing seasons default0). Reused
months are never marked. Normal new-season copies retain MAX-season ordering
among unmarked seasons, so importing August/September/October after November
does not replace November as December's source. The marker survives the same
whole-database checkpoint/backup as winners and sit-out settings. Repeat imports
filter already imported month/tag rows inside the transaction and make no
changes, including to hosting clans/rules removed or edited by staff. New import
rows preserve an existing Lazy season-clan rule and its other settings. Rules & count names the selected
clan's actual saved sit-out in CWL months, or “No sit-out after a win” for None.


Shaka1015 (reused-month pool conflicts): for NEW imported month/tag rows, an
existing non-Lazy `lineup_rule` blocks the entire import. Dry run lists every
conflicting month, clan name/tag and existing pool (including an unset pool).
Apply refuses all such conflicts and rechecks within its single transaction,
so a staff edit after asynchronous API preflight cannot slip through. Nothing
in any table changes on rejection. Staff must set the existing rule to Lazy and
rerun; the importer never rewrites it. Already imported rows remain strict
no-ops regardless of later edits. Player-provider awaits occur outside database
transactions. Production dry run/apply remain unapproved; state this conflict
rule and the `history_only` marker in READY.

Results & bonuses has a “How bonuses work” help sheet; update its text whenever rules in `utils/cwl_bonus_raffle.py` or the sit-out store change (prompt234).

## Lazy bonus announcement (2026-11-13)

The Lazy tab on Results & bonuses shows a "Bonus announcement" card under the
Hosting clan dropdown, in both the All clans list and a clan's steps, with
"x of y clans approved" and "Open announcement". It needs the Send CWL
announcements grant (`cwl_send`) and at least one approved Lazy clan. The sheet
has Clans (All Lazy clans or One clan), a preview, Channel, "Ping the Lazy CWL
role" (off by default), and a review check before "Send to #channel".

`GET /api/cwl/seasons/{id}/bonus-raffle/lazy-announcement?scope=all|one&clan_tag=&ping=0|1`
is read only. It uses approved draws, non-voided confirmations and imported
winners; it makes no Discord or Clash call. All Lazy clans blocks until every
Lazy clan with results has approved winners; a voided winner also blocks.
Preview mentions show cached Discord nicknames, never raw IDs.

`POST` with `scope, clan_tag, ping, channel_id, request_id, fingerprint`
re-renders, rejects a changed announcement (fingerprint) and archived seasons,
checks the channel is a text or announcement channel in this server, and writes
a `bonus_audit` row (`lazy_bonus_announcement`, status `sending`) before Discord
sees anything. A second row records `sent`, `failed` or `uncertain` with the
message links. The same `request_id` returns the first result and never posts
twice; an unresolved request answers 409. Nothing is retried automatically. No
schema change: the receipts use the existing `bonus_audit` table.

Format (`utils/cwl_bonus_announcement.py`): Components V2, WU_GOLD `#F2B62A` on
every container. Container 1: "<:CWL:1399013745598009375> Lazy CWL Bonus Medals",
the intro, three rules, then last month's Lazy winners as `Name · #TAG · @user` (no
clan names). Rule 3 follows the included clans' sit-out lengths ("last N
seasons"; none omits it; mixed lengths show each clan's sit-out). Then one
container per clan: name, tag, bonus medal count (the approved draw's slots) and
numbered winners. The gold footer image is attached to the last container. The
optional Lazy CWL role mention (`1080521665584308286`) opens message 1 and is the only
allowed mention; player mentions never notify. Messages split at 38 components
or 3,800 text characters (Discord limits 40 and 4,000).

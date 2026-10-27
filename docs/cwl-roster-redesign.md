# CWL roster redesign — spec and status

Staff-facing CWL roster page (Roster → Accounts & signups). Staff assign signed-up Clash of Clans accounts to hosting clans in two pools (Main CWL, Lazy CWL), balance the clans by count and weight, manage signups, and publish from the Finalize roster tab. Placements are a private draft until published. Signup changes save immediately and members can see them.

## Status (2026-10-27)
- **Release 1: LIVE** as `fea7e66` (roster `a72939f` + preserved moderation fixes). Branch `codex/roster-release-1` and tag `release-1` are pushed to `origin` (`https://github.com/SirRuggie/WU_Python.git`), verified on 2026-10-27. The release tag remains on `fea7e66`; later docs-only commits advance the branch only.
- Release 1 commit trail: `856b9f0` (panels + visual refresh) → `76fe46c` (header, chips, cards, filters) → `b0fd451` (Load more, select-all-matching, max-50, preferences, mobile polish) → `a68b386` (final polish) → `356d563` (wider clan cards, total weight) → `9dceb81` (chip/card states) → `a72939f` (state rules unified in primitives.css).
- Dirty-editor guard (Clan settings / Weights → leave → Cancel keeps the edit, Leave discards it): manually verified by Ruggie.
- Deploy pipeline rebuilt: `current` symlink → `releases/<sha>`; workspace builds isolated from production (tested); rollback tested.
- **Next stage:** Compare clans (see "Next stages").

## Terminology
- **Pool** = Main CWL / Lazy CWL. Never call these "league".
- **League** = CWL league tier (Master II, Crystal, …). The League filter was removed from the roster.
- **Assign** (not "Move"): covers first placement, reassignment and Unassign.
- **Assigned clan** = an account's placement field. **Hosting clan** = the configured clan itself.
- **Not in assigned clan** (Release 4): replaces "Not moved".

## Behavior contracts (apply to all releases)
- **Balance algorithm:** KEEP the current `cwl_balance.py` behavior (spreads identical weights across clans, then evens out lower total weight). Release 3 only adds an opt-in overflow step. Auto-place keeps `_auto_plan` (unassigned only, heaviest first, eligible non-full clan with the lowest assigned count, then lowest total weight, then tag).
- **Overfill (Release 3):**
  - Manual Assign may overfill, with a red warning (`15/15 → 17/15 (+2 over)`).
  - Balance and Auto-place fill to capacity first; leftovers appear in the preview with an opt-in "Allow overfill".
  - Finalize may publish over-capacity clans with a warning only, never a block.
  - Today the backend rejects overfill (both assignment endpoints).
- **Locks** protect only against automatic moves (Auto-place; Balance unless "Include locked"). Manual Assign sets a lock; Unassign clears it. Pool switch and signup removal ignore locks, but their confirmations list any locked accounts affected.
- **Missing weights:** excluded from Balance and Auto-place with a stated reason; manual assignment allowed. Never treated as 0. Totals and averages use known weights only, with an "N of M weighed" note.
- **Confirm vs. Undo:**
  - Assign/Unassign: instant + Undo toast. Undo is server revision-checked, so it can be invalidated by another staff edit → show "Undo no longer available".
  - Balance/Auto-place: preview → Apply.
  - Pool switch: confirm. Remove signup: red confirm.
  - "Include N locked" re-previews the WHOLE original selection, with an "Exclude locked" toggle.
- **Not in assigned clan (Release 4):** both pools. Compare the current in-game clan to the **published** assignment only; show only with fresh, verified location data, otherwise "Location unknown".
- **Weight editing** in Details keeps an explicit Save (validated; affects saved weights beyond this season).

## Decisions as implemented (Release 1)
1. **Sticky selection bar** at the bottom: `N selected · Assign · Balance · Signup · ✕`. Two rows below 400px; floating at bottom-center on desktop. Back closes panels but never clears the selection; ✕ clears it. The inline bulk panel was removed.
2. **Action panels** (shared `ActionPanel`): bottom sheet on mobile, centered dialog on desktop. Initial focus on Close. Sticky footer above the safe area.
   - Assign: clan search, clan rows as tap targets with a chevron, `before → after / cap`, and Unassign as the last row.
   - Signup: inapplicable options are disabled with a reason.
   - Balance: clan picker (none preselected, ≥2 targets, works with 1 account) → preview with moves, skipped and unchanged → `Apply N move(s)`.
3. **Clan capacity cards:** a horizontal row under the pool tabs, grouped Main/Lazy.
   - Full clan name (wraps, never truncated), `assigned / capacity`, **Total weight** (known weights only, `Total 2,579k`, `Total —` when empty), "N of M weighed" when incomplete, and a capacity bar pinned to the bottom.
   - Mobile width 78vw with the next card peeking in; desktop 240–360px. Scroll-snap. All cards share one height.
   - Tapping a card filters by that assigned clan.
4. **Cards and Details:**
   - Mobile: a 3-line card of about 94px (name with ellipsis + weight; tag · TH · pool; lock + assigned clan · current clan dimmed, "—" when unknown).
   - Desktop: a single row with labelled columns.
   - Left strip toggles selection; the body opens Details; in selection mode, a tap toggles. A `⋯` menu holds Assign, Change signup, DM (opens the Discord profile), Details. No swipe actions.
   - Details is still the existing modal; it moves to its own route in Release 2.
5. **Status visuals:** green background = assigned (keep). Selected = green + gold border + check. Red "No weight" tag. Lock icon + full clan name. The outside-family warning is a small amber badge that keeps the green.
6. **Header:**
   - Mobile: `Nov 2026 ▾ · Draft · Finalize · ⋯` on one line. Desktop: season box plus the Draft/Published status pill.
   - Stats are tappable filter chips in one scrolling row (signed, unplaced, Auto-place, no weight; "(all pools)" only on a pool tab).
   - Signups shown as `Signups open · Add signup · ⚙` (the gear holds window settings and Close signups). Refresh roster is in `⋯`.
   - The Weights count is global. Section tabs use a pill; pool tabs use an underline.
7. **Filters:** `[Search] [Filters (n)] [Sort]`. Filter sheet (side panel on desktop):
   - Status: Assigned / Unassigned / Missing weight / Over capacity / Locked. This merged the old "Show" and "Readiness check".
   - Weight min–max (missing weights never match), Town Hall, Assigned clan (searchable, multi-select).
   - Per-option counts, `Show N accounts`, Reset. OR within a section, AND across sections.
   - Active filters show as removable chips with Clear all. Stats, clan cards and the panel all share one filter state.
8. **List and selection:**
   - Renders 50, then Load more. Select-all selects ALL matching accounts (including ones not yet rendered).
   - Selection persists across filter changes (`N selected · X hidden by filters · Y not shown yet`). Actions list hidden selections.
   - Server limit of 50 per action: actions are disabled with "Max 50 per action · Narrow your selection to 50 or fewer".
9. **Sort:** default "Unassigned first" (then weight high → low). Also Weight, Name, TH, Assigned clan, Signup time, and a Group by Discord user toggle. Persisted in localStorage (validated, try/catch).
10. **Auto-place** is a stat chip (and in `⋯`), not a main button. Same preview flow; asks Main or Lazy on the All tab.

## Backend facts (from code discovery)
- Endpoints (prefix `/api/cwl`):
  - `PATCH /seasons/{id}/roster/{tag}` and `PATCH /seasons/{id}/roster/assignments` (both reject over-capacity)
  - `POST /seasons/{id}/staff-signup-changes`
  - `POST /seasons/{id}/roster/auto-preview` and `/auto-apply` (apply recomputes and rejects a changed preview)
  - `POST /seasons/{id}/roster/undo`
  - `GET /seasons/{id}/publication` (has `draft_changed`, no change count)
- Data:
  - Working: `signups`, `roster_entries`, `lineup_rules`
  - Published: versioned `roster_publications` + `publication_accounts`
  - Undo: `roster_undo` (placement + lock only; per acting user; requires the original revision still current). Pool changes are not undoable yet.
- Capacity: per season, per hosting clan, in `lineup_rules` (15 or 30). An unconfigured clan has an effective manual capacity of 50 and is excluded from automatic placement.
- Pool switch clears the working assignment, the lock, and `prefer_crystal_1_or_lower`.
- 50-account limit: application-enforced on the server (bulk assign, balance selection/targets, bulk signup changes) and duplicated in the UI. No external reason.
- Current clan: official player API via `providers.player`; `roster_locations.py` uses a 120s freshness window and bounded background lookups. The frontend polls enrichment for up to 90s.
- Refresh roster: reloads the roster, rules, revision and Undo; continues the location enrichment. Does not refresh weights.
- Permissions (`cwl_permissions.py`): `cwl_roster`, `cwl_signups`, `cwl_settings`, `cwl_publish`, plus send permissions. Keep these capabilities separate in the UI.
- Archived seasons are read-only; draft seasons are editable regardless of date.

## Release plan
- **Release 2 — Details as its own page:** route `/cwl/roster/account/{encodedTag}?season={id}` (the tag contains `#`). Back restores scroll, filters, tab and selection. Assigned clan via the Assign panel (instant + Undo). Weight keeps Save. Remove signup red + confirm. Weight shown once (source in a collapsible).
- **Release 3 — backend:**
  - Atomic larger selections: raise the 50 limit in one transaction; never sequential batches.
  - Overfill policy (contracts above), the Balance opt-in overflow step, and a Finalize publish warning.
- **Release 4:**
  - Pool-switch Undo (restore pool, league preference, assignment and lock atomically).
  - "Not in assigned clan" tag + filter (published-vs-fresh-location).
  - Unpublished change count (define first: changed accounts vs. fields vs. actions).

## Later
- Bulk bot DM reminder to "Not in assigned clan" accounts (needs deduplication, rate limits, delivery receipts, opt-outs, failed-DM handling).
- Desktop board view (a column per clan, drag to assign, with a keyboard/tap alternative, same APIs).

## Next stages
- **Compare clans** (existing `CompareClans.tsx`, side by side): Ruggie's next focus. Keep it initially; the board view is for moving accounts, comparison is for assessing balance. Start with a discovery pass (what it shows today, against which data) and then walk through it one item at a time.

## Open question
- The Assign panel and Balance preview still show **average** weight; the clan cards now show **total**. Recommendation: Balance preview shows total + average; the Assign panel shows total. Not yet decided by Ruggie.

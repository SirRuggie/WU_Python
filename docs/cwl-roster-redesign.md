# CWL roster redesign — spec and status

Staff-facing CWL roster page (Roster → Accounts & signups). Staff assign signed-up Clash of Clans accounts to hosting clans in two pools (Main CWL, Lazy CWL), balance the clans by count and weight, manage signups, and publish from the Finalize roster tab. Placements are a private draft until published. Signup changes save immediately and members can see them.

## Status (2026-10-27)

- **Release 1: LIVE** as `fea7e66` (roster `a72939f` + preserved moderation fixes). Branch `codex/roster-release-1` and tag `release-1` are pushed to `origin` (`https://github.com/SirRuggie/WU_Python.git`), verified on 2026-10-27. The release tag remains on `fea7e66`; later docs-only commits advance the branch only.
- Release 1 commit trail: `856b9f0` (panels + visual refresh) → `76fe46c` (header, chips, cards, filters) → `b0fd451` (Load more, select-all-matching, max-50, preferences, mobile polish) → `a68b386` (final polish) → `356d563` (wider clan cards, total weight) → `9dceb81` (chip/card states) → `a72939f` (state rules unified in primitives.css).
- Dirty-editor guard (Clan settings / Weights → leave → Cancel keeps the edit, Leave discards it): manually verified by Ruggie.
- Deploy pipeline rebuilt: `current` symlink → `releases/<sha>`; workspace builds isolated from production (tested); rollback tested.
- **Compare clans batch:** decisions 1–16 confirmed 2026-10-27 (see "Decisions — Compare clans"). Implementation on branch `codex/compare-clans`; not deployed.

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
- **Not in assigned clan:** Release 4's roster tag and filter, and any DM reminders, compare the current in-game clan to the **published** assignment only, using location data checked within 2 minutes; otherwise "Location unknown". **Exception — Compare clans** keeps red/green against the **draft** column (staff request), shows the published context on the card ("Moved since publish · members still see X", "Not published yet"), always shows the last known location with its age (never "Location unknown"; "Checking…" only before the first result), and re-checks every 5 minutes while visible.
- **Weight editing** in Details keeps an explicit Save (validated; affects saved weights beyond this season).

- **Publish awareness:** while unpublished changes exist, every roster tab shows "Members still see roster version N (published …). Placement changes made since then are draft only." Placement-edit toasts say "Draft only, not published". Finalize lists the placement changes publishing will make. Signup changes are live and never labelled draft. Publishing always requires explicit confirmation.

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

## Decisions — Compare clans (2026-10-27)

1. Re-check cached locations every 5 minutes only while Compare and the document are visible with at least one clan chosen; poll updating results every 2 seconds, capped at 90 seconds. Keep last-known per-tag results and age.
2. Show `Now in: <clan> · <age>` or `No clan · <age>`; `Checking…` only before the first result. Show an amber Outside family tag from the last verified result.
3. Clan tallies count all assigned accounts, ignoring TH filters: in clan, elsewhere, checking when nonzero, and amber outside family when nonzero.
4. Opening, season and pool changes use cache; only Refresh locations forces a lookup. Errors retain results with one quiet toolbar note.
5. Town Hall options come only from accounts assigned to the current pool's hosting clans; retain selected zero-match options, high-to-low order and Unknown TH.
6. Show configured weight ranges and an amber Outside weight range tag (minimum inclusive, maximum exclusive); exclude missing weights from range checks.
7. Red/green compares last-known location to the draft column in both pools. Fetch published context on open and roster refresh/revision change, not the timer; show Moved since publish or Not published yet where applicable.
8. Phones use page scrolling; desktop column height follows the viewport instead of a fixed 520px limit.
9. Compact Filters / Sort / Refresh-age toolbar; reuse ActionPanel and roster filter pieces with counts. Choose clans includes search, max-10 selection and ordering. Phones use swipeable clan cards, selected players and fallback arrows; column replacement moves to the header menu.
10. Compact player cards retain red/green backgrounds, name and weight, tag/TH/lock, current location, outlined readable tags and published context.
11. Clan headers use capacity-card styling: full name, count, league/tag/range, shared Total formatter, incomplete-weight note, location tally, average TH and a capacity bar.
12. Desktop navigation appears only on horizontal overflow, checked on resize/clan changes: arrows, Jump to clan, edge fades, scroll-snap and a visible scrollbar.
13. Publish awareness adds permission-aware pending-placement banners, draft-only placement toasts (never signup toasts), Finalize's placement change list, first-publish wording and retained explicit confirmation; no automatic publication.
14. Card body opens the existing Details modal; extract the roster menu without behavior changes. Compare offers only DM ↗ and Details; Escape restores focus and targets remain at least 44px.

15. Replace all roster and Compare ⋯ action menus with a shared React Aria popover: only one open, closing on outside tap, Escape, action selection, focus out, tab/pool/season changes and detached phone scrolling. Preserve items, permissions and Discord link behavior.
16. Accounts & signups and Compare Sort triggers show the ArrowDownWideNarrow icon and active option label, retaining “ · Grouped” where applicable. Accessible labels name the active sort and grouping. Labels stay single-line with ellipsis; toolbars fit 320, 360 and 1440 px. Options, persistence and sort panels stay unchanged.

Compare stays read-only; Details and DM only.

### Checkpoint A review fixes

A2 (F1–F10): viewport-stable desktop columns and three-line compact player cards on both devices; location records and per-pool check deadlines owned by the season's roster workspace; no-clan accounts excluded from Outside family, with flags cleared on clan changes; chosen-clan sorting preserves hidden choices. React Aria handles outside interaction for the shared non-modal action menus, covered by per-file happy-dom interaction tests. Phone headers include Avg TH and player menus name the player; Sort uses available width. Shared Discord contact metadata, one Checking pill, destination focus after column replacement, and safe-read transport complete the cleanup. C4/item 13 remains on hold pending A2 approval.

A3 readability + fixes: three text levels with a 12px minimum, softened location fills and 4px edges, primary clan headings/Total, and colored tally numbers. Completed reads alone advance Compare freshness; cancellation/reactivation immediately reissues an unfinished first read, with bounded follow-ups on initial failure. Published context is shared across pools. Action-menu outside interaction uses the whole sheet boundary. The league-filter regression now renders Compare and sorts while a chosen clan is hidden. Unknown Avg TH is omitted; safe-read authorization handling is shared. C4/item 13 remains on hold pending A3 approval.

A4 fixes: reset selected Compare rail text-fill to currentColor; queue one forced Refresh during an in-flight read; time out location reads after 20 seconds without advancing freshness. Hidden pages pause scheduling but allow pending reads to complete; dispose/season/pool changes still abort. Re-check 5 minutes after the last completed read (about 6.5 minutes between starts after a full follow-up cycle). Tally labels include accessible separators and red fills use a softer tint. C4 remains on hold.

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

- Compare clans loads locations from the cache (no forced lookup), re-checks every 5 min while visible with ≥1 clan chosen, and forces only via Refresh. Stale server entries still carry current_clan_checked_at; outside_family is only sent while current.

## Release plan

- **Release 2 — Details as its own page:** route `/cwl/roster/account/{encodedTag}?season={id}` (the tag contains `#`). Back restores scroll, filters, tab and selection. Assigned clan via the Assign panel (instant + Undo). Weight keeps Save. Remove signup red + confirm. Weight shown once (source in a collapsible).
- **Release 3 — backend:**
  - Atomic larger selections: raise the 50 limit in one transaction; never sequential batches.
  - Overfill policy (contracts above), the Balance opt-in overflow step, and a Finalize publish warning.
- **Release 4:**
  - Pool-switch Undo (restore pool, league preference, assignment and lock atomically).
  - "Not in assigned clan" tag + filter (published-vs-fresh-location).
  - Exact per-field unpublished change list/count (placement list shipped in the Compare batch).
  - Review the Declaration readiness check (defaults to source=draft, ArrivalCheck.tsx:29) against the Not in assigned clan contract.

## Later

- FilterPicker (ClanFilters.tsx, still used by App.tsx) is also a native <details> dropdown and likely shares the stays-open bug; review it outside the roster scope.
- Optional clan filter on arrival-check (visible clans only) — trigger: signups grow a lot or the API rate-limits.
- Tappable Compare tally counts to filter a column (pairs with the Release 4 filter).
- "N outside range" count in Compare clan headers.
- Revisit Lazy red in Compare if staff report false alarms from players returning home.
- Assign / Change signup from Compare (deferred to the board view).
- Bulk bot DM reminder to "Not in assigned clan" accounts (needs deduplication, rate limits, delivery receipts, opt-outs, failed-DM handling).
- Desktop board view (a column per clan, drag to assign, with a keyboard/tap alternative, same APIs).

## Next stages

- **Compare clans:** decisions confirmed (see above); implementation and review in progress. Board view still deferred.

## Open question

- The Assign panel and Balance preview still show **average** weight; the clan cards now show **total**. Recommendation: Balance preview shows total + average; the Assign panel shows total. Not yet decided by Ruggie.

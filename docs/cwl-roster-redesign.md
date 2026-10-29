# CWL roster redesign — spec and status

Staff-facing CWL roster page (Roster → Accounts & signups). Staff assign signed-up Clash of Clans accounts to hosting clans in two pools (Main CWL, Lazy CWL), balance the clans by count and weight, manage signups, and publish from the Finalize roster tab. Placements are a private draft until published. Signup changes save immediately and members can see them.

## Status (2026-10-28)

- **Declaration frontend released:** `declaration-1`, `190313b81f4c8373dc08f5a63fca966c6caffab2`, PR #34. Backend remains `73fe3fa` with no restart; rollback frontend `c767b55`. Public `index-B4f6VDw2.js` and 16 hashes verified. Backup `.local/declaration-backup-20261029T003303Z/dashboard.sqlite3`: integrity OK, all 54 tables matched. Main 19/18/18 and Lazy 93/92/73 protected counts/checksums unchanged. 736 frontend tests, TypeScript/build and layout passed. Claude read-only 360px smoke PASSED: hidden version 1 on Oct 15, 7:58 PM, Finalize link, no clan list and no errors; clans verified on preview. Batch complete.

- **Details frontend released:** `details-1`, `c767b55c010dd0de82416301a2c60057775a3662`, PR #33. Backend unchanged on `73fe3fa` without restart; previous frontend/rollback `73fe3fa`. Public `index-CsYgjk4R.js` and 15 asset hashes verified. Backup `.local/details-backup-20261028T232301Z/dashboard.sqlite3`: integrity OK, all 54 table counts matched. Protected counts and weight checksums identical. 719 tests, TypeScript/build and layout passed. Claude read-only 360px smoke PASSED: open/Next/focus/Back preserve account URLs, direct link opens Ace, clean Save disabled, no errors or writes. Batch complete; the pre-existing season Back mismatch remains in Later.

- **Announcements frontend + B1 backend released:** `announcements-1`, `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`, PR #32. Clean tagged frontend and isolated backend deployed; previous rollback frontend `4404c3672872ebff706519402efa4ee9940d3a60`, backend `61290a4ce2b87611119483d6376b879a675aeb81`. Public `index-Dn86Au-2.js` and feature hashes, backend cwd, readiness and 401 checks passed. Protected counts/publication/member season/Manage bindings unchanged; backup `.local/announcements-backup-20261028T205112Z/dashboard.sqlite3`. 681 frontend tests, 4,702 backend tests (21 skipped), TypeScript/build, layout and four guard mutations passed. Claude read-only 360px smoke PASSED: hidden status line, real channels/roles, Preview, Edit opened/closed with no unsaved change; zero write requests, no errors, clean journal. Batch complete.

- **Signup changes frontend released:** `signup-changes-1`, `4404c3672872ebff706519402efa4ee9940d3a60`, PR #31. Backend remains `61290a4` without restart; previous frontend/rollback `0017006`. Public `index-DptKfiRQ.js` and roster hashes match the manifest; protected deployment counts, publication/member season, and unreviewed signup changes (1) are unchanged. 657 frontend tests, TypeScript/build and layout 10/10 passed. Claude read-only 360px smoke passed: alert fits, panel opens/closes without review, “+21 clans with no players”, inline 22px emoji, 74px cards, no errors. Backup `.local/signup-changes-backup-20261028T191131Z/`. Batch complete; Announcements has since released as recorded above.

- **Player card 3 frontend released:** `player-card-3`, `00170063e15b7df43bd769f2c97b0a69bd0ebdf5`, PR #30. Backend remains `61290a4` without restart; previous frontend `374e099`. Scripted hashes/counts passed; Claude read-only smoke passed (release, entry, all 19 Main cards have single-line metadata, no errors). Signup changes has since released as recorded above.

- **CWL flow + shared player card released:** `cwl-flow-1`, `61290a4ce2b87611119483d6376b879a675aeb81`, PRs #27/#28. Frontend and isolated backend deployed; scripted hashes/cwd/counts and Claude read-only click smoke passed. Both rollback targets are `1a8b035`; verified backup `.local/cwl-flow-backup-20261028T145938Z/`.

- **Weights frontend released:** PR #25, `e6353fb9ef77244a6b366550f030d7fd8e75daf7`, tag `weights-1`. Public entry/roster hashes verified; backend stays `c19db57`. Rollback frontend with `switch-release.py c19db57523928f6fee9d6bc93d95d83fa5814bb0`. Backup `.local/weights-backup-20261028T022902Z/`; protected counts, publication and weights unchanged.

- **Release 1: previous production / rollback** as `fea7e66` (roster `a72939f` + preserved moderation fixes). Branch `codex/roster-release-1` and tag `release-1` are pushed to `origin` (`https://github.com/SirRuggie/WU_Python.git`), verified on 2026-10-27. The release tag remains on `fea7e66`; later docs-only commits advance the branch only.
- Release 1 commit trail: `856b9f0` (panels + visual refresh) → `76fe46c` (header, chips, cards, filters) → `b0fd451` (Load more, select-all-matching, max-50, preferences, mobile polish) → `a68b386` (final polish) → `356d563` (wider clan cards, total weight) → `9dceb81` (chip/card states) → `a72939f` (state rules unified in primitives.css).
- Dirty-editor guard (Clan settings / Weights → leave → Cancel keeps the edit, Leave discards it): manually verified by Ruggie.
- Deploy pipeline rebuilt: `current` symlink → `releases/<sha>`; workspace builds isolated from production (tested); rollback tested.
- **Compare clans batch:** decisions 1–16 confirmed 2026-10-27 (see "Decisions — Compare clans"). Initially released at `a65b98ecc5c8d58601ec69d3efd184419b649e73` (tag `compare-clans-1`, PR #23). A–B2 accepted; final polish verified with 498 frontend tests. Public hashes and read-only smoke passed; protected counts unchanged. Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8`.

- Clan settings released via PR #24: `c19db57523928f6fee9d6bc93d95d83fa5814bb0`, tag `clan-settings-1`. Frontend and isolated backend deployed; public hashes, read-only smoke, protected counts and lineup rules verified. CS2/X3/CS3 and final visible age-separator polish included. Backend rollback uses clean `2f7ae7a`, never the workspace.

## Decisions — Weights tab (2026-10-27)

Released frontend-only via PR #25 at `e6353fb9ef77244a6b366550f030d7fd8e75daf7`, tag `weights-1`. Backend remains the isolated `c19db57` release; no restart. 542 frontend tests, typecheck/build, three guard mutations and read-only live smoke passed; protected counts and weights unchanged.

- **1. Compact rows:** TownHallIcon and 15px bold name (opens Details), then 12px TH/tag/pool/source metadata. Desktop identity and controls share a row; phone rows target roughly 110px.
- **2. Loot-first field:** one input with Loot / Full switch, Loot default. Switching units retains typed text and re-evaluates through `parseManualWeight`.
- **3. Header:** Needs weight count, primitive Refresh weights button with Lucide icon, full-width account search, one muted preservation note.
- **4. Progressive rendering:** 50 rows plus Load more; search covers the whole queue. Hidden drafts remain dirty and survive filtering.
- **5. Concise copy:** remove the instructional paragraphs; retain “Saving doesn't move anyone. Refresh keeps manual weights.”
- **6. Navigation:** remove Back to roster; existing section tabs and unsaved-input guard remain.
- **7. Explicit Save:** decimal input mode and matching placeholder; valid full integer weight 1–500,000 only; successful save removes the row and focuses the next editable input. The existing revision-checked endpoint also saves the weight for future seasons.
- **8. Live feedback:** typed loot previews full weight ×5; Full previews the entered full weight. Inline validation replaces conversion text and disables Save. Details now reuses CompactWeightField (superseded by the Details panel decisions below).
- **9. Missing weights:** the tab stays focused on missing weights; correcting existing weights stays in Details. Later: a Manual / Source weight filter on Accounts & signups.
- **10. Clan-managed accounts:** no manual weight input or Save. Queue and Details share the permission-gated “Open Clan weights →” link through normal guarded app navigation; users without `clan_weights` see the access guidance.
- **11. Responsibilities:** WeightQueue owns filtering/drafts/progressive rendering, WeightQueueRow owns identity/source, CompactWeightField owns conversion feedback; formatted CSS and shared parser.
- **12. Readability:** 15px/700 primary names; 12px/400 secondary metadata, helper and preview; explicit currentColor text-fill reset. Gold indicates the selected unit and enabled primary Save.

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
   - Release 1 kept the modal; the approved Release 2 replacement is the linked hybrid panel described below.
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

- **B2 fixes:** full-width publication banner with retained status during refresh and short local dates; Finalize comparison loads only on Review. Changed publications always disclose “Also included: any weight or signup-detail changes not listed above.” because the published export omits some server comparison fields. Confirmation readiness, revision and toast/tab behavior have regression coverage.

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

C4 publish awareness: reuse the header publication response for a persistent placement-only banner with permission-based review actions. Placement-edit messages identify draft-only changes; signup messages remain unchanged. Finalize fetches the existing published account export only while its review is open, compares assignments/pools and available saved account fields, and includes Other changes for weight/details differences or otherwise unexplained changed status. A version mismatch requires refresh; publishing remains revision-checked and always requires an explicit confirmation.

- X3 (2026-10-27) supersedes the A3 R1 Compare player row layout: name/weight/menu; TownHallIcon + TH/tag/lock; location + age; location pill + other tags; optional publication note. Keep cards ≤86px without a note and use a 16px TH icon. Accepted density (CS3): phone ≥7 full cards with the list at the top / ≥4 with Compare at the top; desktop ≥8 per column with the list in view. Keep the existing headers and all rows.

## Decisions — Clan settings (2026-10-27)

1. Main/Lazy overview lists use the existing clan-card primitives; no-pool clans appear under Needs a pool in both tabs. Rows open ActionPanel, preserve dirty/stale guards, and pool changes offer a moved-to-pool toast with View.
2. The other pool is disabled with an assigned-player explanation while any players are assigned. No-pool setup remains allowed. This is a UI guard; the API still permits pool changes.
3. CWL war size is 15v15 or 30v30. Over-full counts show red +N over, full bars amber, room neutral. **B1, Ruggie-approved:** remove the capacity-below-assigned 409; existing assignments never move when rules save.
4. No Not set menu option. Incomplete clans start both fields empty and require pool + war size before Set up clan.
5. Minimum/Maximum weight inputs use an inline k suffix, digits and one decimal point, with 0.001k precision. Values must be above zero; blank means no limit. Zero disables Save with the approved inline explanation.
6. Live range preview shares Compare wording; minimum inclusive, maximum exclusive. No instructional paragraphs.
7. Clan name/count 15px bold; values 14–15px regular; supporting labels 12px muted. Check color and text-fill. Gold identifies selection/active state.
8. Archived settings remain visible as read-only text with no Save.
9. **B2, Ruggie-approved:** remove lower_league from application reads, responses, validation, writes and the frontend type. Requests containing it are rejected as unknown fields. Keep the database column and existing values untouched; no migration.
10. Changed settings show a live, expandable outside-range impact list (known weights only, inclusive min/exclusive max) and over-capacity count. Save changes rules only and its toast is not labelled Draft only.

Compare additions X1/X2: phone rail selection follows the snapped card only after scrolling settles, with reverse synchronization for arrows/taps/player swipes, reduced-motion support and a polite clan announcement. League/tag/range appears on each phone card; the duplicate subtitle below navigation is removed. No additional location requests.

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

- Compare clans loads locations from the cache (no forced lookup), re-checks 5 minutes after the last completed read while visible with ≥1 clan chosen, and forces only via Refresh. Stale server entries still carry current_clan_checked_at; outside_family is only sent while current.

## Release plan

- **Release 2 — Details as a linked hybrid panel:** desktop right-side panel / phone full-screen sheet, `?account=<encodedTag>` on the existing route. This replaces the own-page plan by Ruggie's choice, for fewer taps per player. Back closes; list, scroll, filters and selection stay mounted. Placement uses instant revision-checked saves + Undo; weight keeps its own Save; Remove signup stays confirmed.
- **Release 3 — backend:**
  - Swap or Undo into an over-full clan still returns 409 "Hosting clan exceeds capacity" (`cwl_web/app.py` swap/undo capacity guards). B1 makes this reachable; resolve with Release 3’s overfill policy, not in Clan settings CS2.
  - B1 (war size below assigned count) brought forward into Clan settings, Ruggie-approved and released in `clan-settings-1`. B2 removes the unused lower_league application field while retaining its stored column.
  - Atomic larger selections: raise the 50 limit in one transaction; never sequential batches.
  - Overfill policy (contracts above), the Balance opt-in overflow step, and a Finalize publish warning.
- **Release 4:**
  - Pool-switch Undo (restore pool, league preference, assignment and lock atomically).
  - "Not in assigned clan" tag + filter (published-vs-fresh-location).
  - Exact per-field unpublished change list/count (placement list shipped in the Compare batch).
  - Review the Declaration readiness check (defaults to source=draft, ArrivalCheck.tsx:29) against the Not in assigned clan contract.

## Later

- Pre-existing roster season-menu history issue: without Details, Back can show
  `season=1` in the URL while the page still displays the newer season.
- `mayLeaveEditor` still uses `window.confirm` for season and mode changes.
- Details: a successful save followed by a failed reload drops the Undo toast.
- `RosterWorkspace.tsx` restates the weight dirty rule separately from `dirty`;
  consolidate these rules in a later cleanup.

- Announcements review preview shows raw role IDs (`@role 3333…`) instead of role names.
- Announcements: opening Edit on an empty link marks the pool unsaved at once on HTTPS (by design); revisit if staff find it confusing.

- Player card CSS guards untested: Compare line-3 margin-top that clears the ⋯ menu (PlayerCard.css:258), glow stop at 44px, green token; the 360px test checks padding only (needs a real-browser layout test).

- Manual / Source weight filter on Accounts & signups to spot hand-entered weights.

- Optionally drop the unused lineup_rules.lower_league column (no longer read or written).
- Server-side guard against changing a hosting clan's pool while players are assigned (UI guard exists).

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

## Finalize read metadata (Ruggie-approved backend extension)

See the [approved Finalize read metadata extension](dashboard-backend-releases.md#finalize-read-metadata-ruggie-approved-backend-extension).

## Decisions — Finalize roster (2026-10-27)

Status: deployed as `finalize-1` (`1a8b035461ec46fba60f6ed4808111d3c67d87cf`), PR #26, 2026-10-28. Scripted release checks passed; authenticated read and click smoke remain with Claude.

1. Review order: status/Refresh draft, publishing changes (first four, expandable),
   checks, joining instructions and explicit Publish, collapsed full roster preview,
   then Hide roster. No sticky Publish.
2. Joining instructions are local edits, prefilled from the active publication or
   latest withdrawn publication; saved only with confirmed Publish. Limit 2,000,
   counter from 1,800, dirty navigation guard, shared member-card preview.
3. Informational check chips target roster mode `weights`, unassigned accounts,
   and Compare clans. Over-capacity counts clans and excess players, never blocks.
   Only unassigned accounts require acknowledgement.
4. Hide roster is permission-gated at the bottom. Existing ConfirmDialog starts
   on Cancel, with red Hide roster action; revision/version checked again. Working
   roster and signups remain; previously sent Discord messages remain.
5. Shared roster season menu and Button primitives; compact Finalize title.
   Announcements content and workflow remain out of scope.
6. Status distinguishes never published, current, changed and withdrawn. Reuses
   the banner's short local date formatter. Server `next_version` supplies version
   headings and confirmation, including after withdrawal.
7. Full preview starts collapsed, contains Main/Lazy tabs and searchable clan
   groups. Clan count/capacity and excess, TH icon, player identity, roster-styled
   Details; searching opens matching groups.
8. Three text levels: 15px bold primary, 13–14px regular values, 12px muted metadata.
   Gold for primary/active controls, red danger/errors, amber warnings. Inspect
   actual text-fill as well as color; minimum 12px.
9. One Refresh draft action; errors point to it. Change comparison is fetched only
   while Review is shown; `changesReady`, explicit confirmation and revision checks
   remain. No automatic publication or notification.

Later: Version history on Finalize (number, time, who, counts, hidden) via a new
read-only endpoint. The separate flow batch (step strip/sidebar/renames) is not
part of this implementation.


## Decisions — CWL flow (2026-10-27)

Released as `cwl-flow-1` on 2026-10-28; S1/S2/S3 and shared player cards included.

- S1 carries active hosting lineup rows and their pool/capacity/weight rules from the latest season with lineup rows, atomically. No signups, placements, locks or publications are copied.
- Create-season confirmation (Ruggie correction, 2026-10-28): before saving, “<Label> will start with the hosting clans and their settings from the previous season. Signups start empty.” For the first season: “<Label> will start with no hosting clans. Signups start empty.” After creation, use S1's actual response count: “<Label> created with N hosting clans and their settings. Signups start empty.” Do not add an inheritance-preview endpoint (S4 was declined).
- S2 (approved 2026-10-28): optional strict-boolean `expected_signup_open` compare-and-set; a mismatch returns 409 without writes. Show and open sets member visibility first, then opens signups. A second-call failure reports partial success without retry or rollback. Fix for an already-open hidden season only changes member visibility; no signup PATCH.
- S3 (approved 2026-10-28): `cwl_settings`-authorized read-only clan lookup validates with `tag()`, returns `{tag, name}`, 400 for invalid tags and 404 for missing clans. No database writes. Confirm still uses the existing add POST. S1/S2/S3 require one isolated backend release when approved for deployment.
- CWL sidebar order: Seasons, Signup reminders, Build roster, Finalize roster, Announcements, Declaration readiness check, Return reminders, Results. Other sidebar sections stay unchanged.
- Build / Finalize / Announce use a numbered step strip, existing routes and permission-gated destinations. Missing weights replaces Weights. Declaration remains a post-publish, read-only check against the published roster; rebuilding it is a later batch.

- N4 option B (approved 2026-10-28): Add hosting clan and Archive require Build roster access; settings-only staff see neither control and receive no partial roster access. Existing `cwl_settings` mutation authorization remains required by the unchanged backend. Seasons retains its own settings permissions.
- F5: Seasons keeps creation, member-season visibility, the direct signup link and guarded signup opening/closing; host/family directory sections move out. A per-user dismissible note links to Clan settings. Hosting clans may be outside the family directory. Add uses family selection or S3 lookup; Archive uses the existing global archive operation and preserves this season's assignments and history.
- F6/F7: Missing weights uses a global missing count. Pool tabs belong to Accounts & signups, Compare clans and Clan settings, not Finalize. Build sidebar entry resets to Accounts & signups; in-visit tabs retain their state. The header's redundant Finalize button is removed; the publication-awareness banner remains.
- F4/F9: “Readiness” names only the Declaration readiness check. The isolated member journey checks Home → CWL signups → My clan assignments before/after a deliberate fixture publication. No real Discord sends or production writes are part of the checkpoint.

### Later — CWL flow

- Seasons don't load when the dashboard opens in a background tab (document.hidden skip in App.tsx loadSeasons); loads on focus.
- Player card tests: prove the Accounts card uses the shared now prop; add a test for Compare's 30 s age tick.

- Regroup the rest of the staff sidebar (Ruggie dislikes everything under “Staff tools”).

### CWL flow review polish (2026-10-28)

- Build’s shared header keeps signup status and Fix available on every tab. Add signup still requires `cwl_signups`, matching the backend; hosting settings retain the separately approved gates.
- The Finalize step marks unpublished changes or a never-published draft with placements. A current publication has a checkmark. Desktop steps are compact; mobile layout is retained.
- A stale Fix re-reads visibility and writes nothing when already visible. Failed reads expose Retry; a lost signup PATCH response is uncertain and followed by read-only refresh, never a write retry.
- S3 lookup enforces `cwl_settings` on its GET, matching the add POST. S1 duplicate labels return 409; transactional carry-forward failures return a clear 500 after rollback.

## Shared player card (2026-10-27)

Accounts & signups / Compare: one shared rounded card shape, 4px colored left edge, small card gap and lighter tokenized fills. Row 1 starts with TownHallIcon, then bold name (ellipsis), bold weight right and the existing menu; row 2 is muted TH/tag and lock (plus Accounts' existing pool). Compare retains its location line, chips and publication note. Accounts row 3 uses bold assigned clan or `Not assigned`, followed by muted `· now in X`; existing warning/note lines remain below. Accounts keeps its checkbox and green-for-assigned meaning; Compare keeps green-in-clan/red-elsewhere/neutral-checking. Gold selection outline remains.

Frontend styling/markup only; behavior and location freshness rules unchanged. Shared source: `web/cwl/src/PlayerCard.css`; fills: `rosterUi/tokens.css`. Text levels retain the 12px minimum and measured 4.5:1 contrast, including text-fill colors. Accounts readability continues in a later audit. Branch checkpoint pending review; no merge, tag or deployment for this batch.

## Player card v2 (2026-10-28)

Branch `codex/player-card-v2` from `bf4cfe704747061aca1c3afecef76be374998c49`, following accepted cwl-flow-1 smoke. Preview-only checkpoint; release remains a separate approval.

1. State meaning retained: Accounts assigned green / unassigned neutral; Compare in-clan green / elsewhere red / checking neutral.
2. **Superseded by Signup-change alert Item 8 (inline 22/26px TH icon; no icon column).** Compact (≤700px Accounts and all Compare): 40px emoji, 16px bold name/weight, 13px metadata; lower rows span under the name. Wide Accounts: centered 56px emoji, 18px name, 22px centered right weight. Checkbox/menu remain 44px. Approximate 76px compact target is measured, with extra rows for tags/notes.
3. Shared lighter fills plus tokenized internal top-edge gradient and brighter rounded 5px left bar; no outer glow. Gold selection/focus and existing card gaps remain. Card text meets 4.5:1 on its rendered background including hover; the final polish below measures clan text on line 3 after the glow fades.
4. Accounts row 3 distinguishes assigned-in-clan, assigned-elsewhere, unassigned/clanless and not-checked states; full words in the accessible description. Current-clan suffix ellipsizes first. Ruggie's approved exception: an assigned name longer than the entire line ellipsizes too, hiding the suffix; full line in title and accessible description. No wrapping. **Superseded for Compare by the refinement below:** both pages now use the shared assigned-clan status line and inline In clan pill; redundant location chips are removed.
5. Existing checkbox, menu, lock, chips, real warning/note rules, ticking ages, actions and selection behavior retained; emoji size param unchanged by Ruggie's choice (`size=64`), current source unchanged.
6. Live follow-ups (separate commit): withdrawn roster with placements gets the step dot; withdrawn banner uses Finalize wording; background roster enrichment copies current_clan_checked_at with the other location fields. Frontend-only; no changed write endpoints or backend behavior.

### Player card v2 refinement (2026-10-28)

Ruggie approved one shared line 3 on Accounts and Compare: assigned clan first; inline nonshrinking In clan pill when checked in place; otherwise arrow to current clan, with only the current name red. Compare uses its column clan and removes redundant location chips; only range/family warnings retain a chip row. Tags determine equality, with name fallback when missing. The one-line long-name exception remains; full title and accessible hours/minutes remain available. Green/red top glow is 20%, neutral 8%; menu space is reserved. Hidden-publication wording has one shared formatter. No write behavior or backend change.

### Player card v2 final polish (2026-10-28)

Compact line 3 is below the 44px menu hit area and uses the full available width; common names Emerald Watch and W. U. Lazy .125 retain the inline age at 360px. Glow fades out at 44px, before line 3, so saturated clan text is measured against its actual lower-card background including hover. Assigned clanless players say red No clan; unassigned retain muted in no clan. Compare tint, header tally and line 3 share tag-first/name-fallback matching and require a completed location read. Checking is described as Checking location. No backend or write-path change.

## Decisions — Signup-change alert (2026-10-28)

Preview branch `codex/signup-changes` starts from origin/main `3168f68061cdcb8f395700d19e4217a59c07047d`, after the accepted player-card-3 smoke. Frontend only; no deployment, merge, tag, schema or endpoint changes.

1. Replace the inline signup-activity card with a single header alert below the summary chips on every Build tab. It opens a side ActionPanel on desktop and a full-screen phone sheet; the last review closes it. Loading is silent, failure has Retry, and 30-second polling pauses while hidden.
2. Amber is the default. Red requires the previous clan’s known 15/30 capacity and current assigned count below that capacity; unknown capacity stays amber.
3. Distinguish withdrawals, pool switches and mixed changes with singular/plural and 100+ wording. The panel says spots are open in the draft; only an active publication adds the version members still see.
4. Rows show the name/action, short local Finalize date with full timestamp title, player tag and previous clan/pool (no clan tag). Only a pool-switch account still on the roster opens Details. Message reuses DiscordContact; controls retain 44px targets.
5. Fill spot navigates through dirty/busy guards to Compare with the prior pool/clan selected through its existing preference state. Mark reviewed writes immediately with a synchronous duplicate guard and inline errors. Mark all confirms the names, calls existing review POSTs sequentially, stops on the first failure, and reports partial progress without retry. The cwl_signups visibility permission is unchanged.
6. Summary cards hide clans with no assigned accounts, recounted from this season’s roster. Each pool has a +N clans with no players reveal and an empty-pool message. Reveal state survives Build tab switches, and resets on season/page leave. Assignment/hosting settings, Compare choices and other counts remain unchanged.
7. Realistic player/clan names in card fixtures are at most 15 characters, with 8–9-character player tags. Ellipsis remains a safety net for untrusted input.
8. TownHallIcon is inline before the name: 22px compact / 26px wide, centered without increasing the name row’s height. Lines 2 and 3 start at the left content edge; checkbox, weight and menu behavior stays. `npm run test:layout` starts the repository fixture and runs the Chrome metadata/indent/long-clan checks; see `web/cwl/tests/README.md` for the installed Playwright runtime.

Signup-change review follow-up: preserve the saved Compare clan set when filling
a spot (prepend/dedupe, cap at the existing maximum, null tag leaves it alone);
lead red alerts with the shortage; uniform 44px row actions; unclipped inline TH
images. Layout tests use locked Playwright and frontend/backend from the same
checkout, with locally fulfilled images and an explicit skip when Chrome is absent.

## Decisions — Announcements (2026-10-27)

Released frontend + approved B1 backend as `announcements-1` at `73fe3fa92d8d0d89491be6e350c130b9d375aaaf` via PR #32 on 2026-10-28. Scripted verification and Claude read-only click smoke passed; see Status and rollback docs.

1. Derive an unlinked CWL month from the season label. Show the named month, Change, and an explicit Load button; never bind automatically. Unparseable labels show the picker. Changing a linked month has one Cancel-first confirmation, including any unsaved-edit warning.
2. Show Main CWL then Lazy CWL as compact pool cards, with status, destination, roles, roster-link description, Preview and Edit. Edit uses ActionPanel. Preserve template-disabled and delivery-lock rules.
3. One muted sending explanation, one Refresh status control, shared Cancel-first confirmations, and roster controls/text levels. Clan roster images are restyled only: select → preview → download → test; no production image posting was added.
4. Use plain queued/sending/sent/failed/stale/uncertain wording. Bot availability is shown only when unavailable. The existing declaration-readiness cue remains after confirmed delivery. The loading message explains that campaign settings can take up to 20 seconds; publication status renders independently.
5. Show announced versus current publication version, short local dates, and the shared hidden-publication wording. Republishing never resends an announcement.
6. One Review and send includes all currently ready pools; per-pool results remain separate. A lone eligible pool can show Send or Retry. Only failed/stale deliveries retry. Generation, version, destination, duplicate-submit and once-per-pool/month checks remain; polling is every five seconds only for pending/sending. Publication refreshes retain unsaved drafts.
7. On an HTTPS origin, opening an editable message with an empty saved link prefills My clan assignments for that season. It is an unsaved edit until Save. Custom saved links are retained; server HTTPS validation is unchanged.

**B1 (Ruggie approved):** the existing manage-bridge delivery response adds nullable `publication_version` from the existing send record. No schema, write path or endpoint changes. Deployed with the isolated backend restart in `announcements-1`; see `dashboard-backend-releases.md`.

### Next — Roster images (approved design; not implemented here)

Main/Lazy image channels are saved server-side and carried over. Post per pool sends one message per clan, with no pings, idempotent receipts and retry of failed messages only. Republish updates existing messages in place; a new clan gets a new post, and a dropped clan's post is edited to “<Clan> is no longer hosting · Roster vN”, never deleted. Test all sends to a chosen channel with a TEST label and is never recorded as production delivery. Preview and download remain. Ruggie approved the backend and schema work for that separate batch.


## Decisions — Details panel (2026-10-27)

Frontend-only implementation released as `details-1`; see Status for deployment and passed smoke evidence.

- **1. Linked hybrid panel:** every staff opener uses the same Details surface. At 768px and above the right panel leaves the list usable; below 768px it is a full-screen sheet. Previous/Next follow the current opener list, with disabled ends. Opening pushes an encoded `account` query; switching replaces it; direct links establish a list entry and Back closes through `actionPanelHistory`. Only unsaved weight text triggers the named ConfirmDialog discard prompt. Add signup's nested surface stays within its modal's active subtree.
- **2. Section order and saving:** header (TH/name, shared metadata, Discord/DM), At a glance, Placement, Weight, Source & history, Signup, Danger, signup timestamp. Change clan reuses RosterAssignPanel and the current manual-placement lock behavior. Lock saves independently. Placement changes offer the existing revision-checked Undo; Unassign, pool switch and Remove retain explicit confirmations. Weight has its own Save; there is no shared Save changes form. Pool changes are immediately visible to members; placement changes remain draft until publication.
- **3. Existing weight/location rules:** CompactWeightField defaults to Loot, uses parseManualWeight, previews full weight and validates inline. Details alone allows blank Save to clear the override to its source. Clan-managed weights use ClanWeightSource without an input. Effective weight appears at a glance; source/first saved values and short timestamps are under Source & history. PlayerClanStatus and the shared location records preserve the last result and age; opening Details does not force a refresh. A refresh cannot erase unsaved weight text.
- **4. View-only:** archived seasons, Declaration and missing roster access show their approved reason and hide placement/weight editing. Archived and Declaration also hide Signup and Danger. Signup-only staff keep Signup/Remove controls, without roster or weight editing. Server permissions and endpoints are unchanged.

Details rework: direct-link requests register with their hosting page before opening; same-page route refreshes preserve the account and overlay history marker, while season changes close Details. Finalize preview and Add-signup Details deliberately include the same confirmed pool-switch action as other Details openers.

## Decisions — Declaration readiness check (2026-10-27/28)

Frontend-only on `codex/declaration`, based on Details docs `e7254f2`; pending checkpoint review. No release, merge or tag.

1. **Published roster only:** arrival reads always request published source. Never-published and hidden seasons show no player list and link to Finalize; hidden copy uses `hiddenPublicationStatus`. Draft differences are a muted version notice and do not block readiness. Publication and arrival versions must agree before replacing the current results.
2. **No editing:** player names open view-only Details with the Build roster navigation reason; no Details button, mutation controls or Declaration dirty/busy guards. Ruggie-approved extension: the panel uses the published snapshot, including Previous/Next in the open clan's red-first/name order. Removed signups still open, with “No longer signed up · removed after version N”. The existing published accounts export supplies saved weights and locks; draft accounts are used only to identify removals, not to replace published placements. Panel write callbacks reject view-only requests.
3. **Shared cards and location engine:** reuse Compare's transport, scheduling/cancellation engine, location records, PlayerCard surface, TownHallIcon, PlayerCardMeta and PlayerClanStatus. Compare's defaults and tests remain unchanged. Declaration has only green (in assigned clan) and red (everything else, including before a result), DM links only on red, no weight/menu, no pool word, and Outside family only for a non-null current clan. Preserve last results and their age; failures say “Couldn't update · showing last results”. Non-forced checks run every five minutes while visible, forced checks only via Refresh; Declaration follows updating responses every two seconds only after first load or Refresh, for at most 60 seconds; routine five-minute reads never start that loop. Hiding pauses it; disposal cancels it. Last checked uses the newest displayed location timestamp, not request time.
4. **War-size readiness:** read capacity from existing roster clans. Ready means at least 15/30 fresh arrivals (checked within five minutes), not every assigned player. Overfilled ready clans retain late players. Old arrivals keep their location color/count and add Refresh to confirm when insufficient fresh arrivals remain. Null capacity is never ready and links to Clan settings. Awaiting placement stays separate and is excluded from ready-clan totals.
5. **Collapsed sections:** all clans start closed. Phones allow one open clan and scroll its header into view; desktop allows several. Open groups show all players, red first then name. Search opens and highlights the first matching clan. Summary, last check/Refresh, one help line, counted pool tabs and full-width search precede clans. The 360px fixture first-header offset improved 762→402px and total collapsed height 13,021→887px, but the ~250px target remains unmet; report this explicitly for review rather than claiming compliance.
6. **Copy mentions:** only an open, not-ready assigned clan offers Copy mentions. Deduplicate linked Discord IDs, omit and name unlinked players, show Copied N mentions, and expose selectable text if clipboard access fails. Copying never sends a Discord message.

Validation: 728 frontend tests, TypeScript/build and layout checks; 4,702 backend tests passed, 21 skipped, 116 subtests (isolated archive, no backend changes). Three mutations caught (war-size threshold, clanless Outside family, published-only source). Read-only fixture browser checks at 360×800 and 1440×1000 plus 320px overflow; counts/weights/publications unchanged, no application writes/errors. Text-fill and sampled contrast checked (minimum 4.95:1, 12px). External Discord images blocked in the browser fixture, exercising TownHallIcon fallback; this does not prove live CDN delivery or a full assistive-technology audit.

Declaration review fix: title/season share a phone row, readiness help is collapsed behind ⓘ, and DM hit areas do not enlarge card rows. Awaiting placement is neutral and excluded from late totals. First-load failures offer Retry without claiming previous results.

Declaration mobile target accepted in practice by Ruggie/Claude: 384px first header with fixture banner, approximately 335px without, all six Main headers on one screen. The original ~250px target is relaxed; 80px cards (103px with chip), 57×44 DM hit area accepted.

## Decisions — Roster images (2026-10-27/28)

Implementation checkpoint on `codex/roster-images`, based on Declaration docs `dd7b00c`. No merge, tag or deployment; production was verified on Declaration frontend `190313b` and backend `73fe3fa`.

- Global image channel per Main/Lazy pool, explicitly saved and audited; destinations must be text/announcement channels in this server.
- One durable post per season/pool/clan, tied to the immutable published version. Hidden/never-published rosters cannot post.
- Confirmation lists every clan and destination. Client runs sequentially, waits only on known 429 responses, stops on the first other error, and stops after the current request when closed. Both pools share a synchronous run guard.
- Resume selects missing current-version posts; Retry failed selects failed entries only. Failed edits retry the existing message except a confirmed 404, which offers Post again.
- Update PATCH replaces attachments and retains the clan link. Drop PATCH removes attachments/buttons and says the clan is no longer hosting. Never DELETE.
- Uncertain NEW posts require the duplicate-warning Post again anyway confirmation. Uncertain UPDATE/DROP requires “Retry the edit on the same message? This won't create a new message.” Retry PATCHes the same message; update 404 offers Post again, drop 404 is treated as dropped.
- Ruggie approved durable text-only request receipts: operation, season/pool/clan, target version, channel/message IDs, request ID and frozen payload/render metadata. PNGs regenerate from the immutable publication and frozen metadata after restart; no PNG bytes or base64 enter SQLite or audit logs. Regression compares decoded pixels.
- Test all uses an unsaved test channel and explicit confirmation. Main and Lazy copies use the existing test endpoint, TEST prefix and no mentions; they never become image-post records. Single-clan testing remains available.
- Without cwl_send the card exposes statuses only. Preview images mount only while their disclosure is open.
- Backend and schema approved. Release requires an isolated backend directory, restart and readiness gate; development/review use temporary SQLite plus fake Discord only.

Roster images review fix: explicit uncertain recovery always targets the current published version. New-post recovery retains the duplicate warning; update/drop retry PATCHes the same message with newly frozen metadata for the new version. A previously dropped clan returning in a newer publication recovers with update. Pool status includes the number needing checking. Older recovery versions still return 409.

A new POST cannot replace an existing active message, including a failed update. A confirmed update 404 clears only the active message reference (the durable receipt/audit retain the old ID), enabling the approved Post again path. Cancellation records uncertainty then propagates; post 404 describes the missing channel/message, and opt-in 5xx is uncertain. Individually tested replay/acquisition/wrong-action guards protect delivery.

Roster images fix 2: a removed clan's uncertain update recovers as a drop edit on the same message at the current version. A removed clan's uncertain new post has a confirmed “Mark as checked” action: only its local post row becomes `dismissed`, with an audit entry and no Discord call; the original uncertain receipt is retained. A checked row can be posted normally if the clan later returns. Server-side duplicate consent (`confirm_duplicate: true`) is required for a new POST over uncertainty, both before rendering and in the atomic claim; only the explicit duplicate-warning recovery sends it. Known-message protection uses one shared predicate at both boundaries.

The storage owner migrates the existing `roster_image_posts` CHECK constraint to allow `dismissed`, transactionally copying every existing row and preserving IDs, receipts and audit history. No additional permanent table or image bytes are introduced. Initialization is idempotent; migration/reopen integrity and foreign-key checks are covered by isolated tests. Release still requires the already-approved backend/schema rollout, not a frontend-only deployment.

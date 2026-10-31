# CWL roster redesign — spec and status

## Linked weights — review pending, October 30, 2026

Prompt 39 reverses the FWA popup link-only rule: roster Details and Clan weights
share explicit Save/Clear, parsing, history and revision checks. See
[the weight contract](clan-weight-trial.md). Backend release required for shared
write handling and the history source column; no production activation yet.
Read-only backup audit: 42 legacy / 350 clan rows, zero overlaps or changed
values, all timestamps reliable. Source and history rows are retained.


Staff-facing CWL roster page (Roster → Accounts & signups). Staff assign signed-up Clash of Clans accounts to hosting clans in two pools (Main CWL, Lazy CWL), balance the clans by count and weight, manage signups, and publish from the Finalize roster tab. Placements are a private draft until published. Signup changes save immediately and members can see them.

## Back to top and empty quick selection — October 30 release

`back-to-top-1`, PR #65/tag `a8031084eed09ee89b8063828d4bc2c5d40cc628`, released frontend only. Claude read-only smoke 93 passed at 360px: hidden at the top, shown after three viewports down and 200px up at (205, 740), 139×44px; tapping returned to scrollY 0 and focused Build roster. Backend `23235cc` and bot `b517afd` were unchanged, with no restart. See [release evidence and guarded rollback](dashboard-frontend-releases.md).

Prompt 28 adds a view-only `↑ Back to top` button only to Build roster → Accounts & signups on phones (≤800px). Reveal requires more than two viewport heights of scroll and 40px of upward travel, with an 80ms debounce. Downward travel hides it; reaching one viewport from the top hides it immediately. The stationary lower-right pill stays above the measured selection action bar, and bottom spacing keeps the final account's actions reachable. Details, dialogs and local panels suppress it; other roster tabs and desktop do not render it.

An explicit tap focuses Build roster without an incidental focus scroll and scrolls to zero smoothly, or instantly for reduced motion. Filters, selection, tab, URL and persistent data stay unchanged. The native button has an accessible label, visible keyboard focus, a 44px minimum target, gold text/boundary contrast and safe-area spacing.

The authorized prompt 32 follow-up preserves the current selection when Select 15 or Select 30 finds zero unlocked matches, including selections hidden by filters, and displays `Only 0 unlocked accounts match`. Nonempty quick selections retain their existing replacement behavior and order; save and permission contracts are unchanged.

Validation scope: 924 frontend tests, TypeScript/build and isolated layout passed. Focused component tests cover scroll thresholds, hysteresis, pending callbacks, desktop resizing, panel/dialog gating, bar offsets, focus and reduced motion. Workspace tests cover tab gating and preserving an existing selection when both quick-select controls encounter only locked matches. Fixture browser checks at 360×800 and 1440×1000 cover offsets, last-card hit testing and overflow; review 91 confirmed three required and five extra mutations killed, and measured 20px selection-bar clearance. These checks do not constitute a full assistive-technology or real-phone audit.

Later from review 91: hide Back to top while an undo toast is visible (about 12px overlap); confirm on a real phone whether browser-toolbar resize requires extra upward travel; add workspace-level vitest coverage for bar-height and open-panel hide gates. Passing smoke does not close these items.

## Weight-range release status — October 30, 2026

`weight-range-1`, PR #64/tag `23235ccf2671dfe5675f0bc98d38ab11a011ab09`, released frontend and backend with the bot unchanged at `b517afd`. Both range endpoints are inclusive (Ruggie, October 30), while validation still requires minimum < maximum. Compare defaults to Weight: high to low; Select 15/30 skips locked accounts in visible order and the selection cap blocks the 51st account. Claude's read-only 360px smoke (handoff 92) confirmed Jujupon at 179k no longer showed Outside weight range for Lazy.128's 172–179 range, quick picks were visible, and Compare used the new default.

Tagged checks passed: 4,844 backend tests / 21 skipped / 153 subtests, 914 frontend tests and TypeScript/build; fourteen accepted mutations were killed. Protected pre/post data matched; no assignments or locks were written by the evaluation change. Public hash/backup evidence and frontend/backend-only rollback to b517afd are in [backend releases](dashboard-backend-releases.md#weight-range-1--october-30-2026). Later frontend releases are recorded independently.

Later from review 87: remove the now-unreachable Max-50 action branch and reconcile older select-all/Max-50 prose; the shared-boundary `find` reports only one matching note when several boundaries overlap. The zero-unlocked selection-preservation correction belongs to the separate accepted back-to-top change, not the weight-range release.

## Earlier status (2026-10-29)

`weight-totals-1` released at `4f57d6e73941d3adc3b3223611927081bf794df9` (PR #59), frontend only. Assign and Balance now show totals of known effective weights; Avg TH remains. Empty clans say `Total: no weights yet`, and the duplicate Fill spot / Signup Details dirty dialog is fixed. 901 frontend tests, TypeScript/build and full isolated layout passed. Public `index-5dIAUgQj.js` SHA256 `b3f78cd7daba401cd67513e69fced2d6bf989e8a0b44b9e7f840d28a742d5c12` matched; backend `f95830b`/PID 2249061 stayed unchanged without restart. Backup integrity and counts matched (Main 22/18/18, Lazy 118/89/71); frontend rollback is `8c7b5a8c29c6dab65801879cf20226f94e7efc7c`. Claude's read-only owner 360px smoke PASSED (handoff 65): Assign current total 2,652k and no-weights state, Balance totals and no overflow; GETs only, no console errors. Detailed evidence is in CLAUDE.md.

Previous `roster-hotfix-1` released at `8c7b5a8c29c6dab65801879cf20226f94e7efc7c` (PR #57), frontend only. The capacity warning is one line for hosting clans with assigned accounts, dirty roster exits use an in-app Discard dialog, and Missing weights uses one top Loot/Full switch. The pool-filter selection regression in the first hotfix candidate was corrected before release. 899 frontend tests, TypeScript/build and isolated layout passed. Public `index-DKL_Envz.js` SHA256 `e077320fdc59a84311fba3c28069e3ea60f7b633fff9999063f8595164165b20` matched; backend `f95830b`/PID 2249061 was unchanged without restart. Backup integrity/counts matched (Main 22/18/18, Lazy 118/89/71); rollback frontend is `30676446e559cab33d108aeb68711e74c8b98a33`. Claude's read-only owner 360px smoke PASSED (handoff 62): one capacity warning, one unit switch, and the dirty-weight Discard path; no application writes or console errors. Detailed evidence and rollback command are in CLAUDE.md.

The preceding `roster-readability-1` release at `30676446e559cab33d108aeb68711e74c8b98a33` (PR #56) passed fixture review but **failed its initial real-phone smoke** (handoffs 55–56). Its 23 capacity-warning rows and the pre-existing native weight confirmation trap led directly to this hotfix; the per-row Loot/Full toggles were also replaced. Do not treat the initial readability smoke as passed. Readability backup integrity/counts matched its own release (Main 22/18/18, Lazy 118/92/74); these are deployment-local snapshots and differ from the later hotfix counts. Its public `index-DWX3fCZu.js` and asset hashes matched, with the same backend/PID and no restart. See CLAUDE.md for proof.

Previous `staff-nav-1` released at `95808221f85200c3f51a9a036a6fbb266b2eda57` (PR #54), frontend only. 865 tests, TypeScript/build and full isolated layout passed. Public index-Dd77bclu.js and 47 asset hashes match; backend/PID unchanged without restart; protected counts unchanged (Main22/18/18, Lazy118/92/73). Backup and rollback evidence are in CLAUDE.md. Claude read-only owner smoke PASSED (handoff52): correct flat menu and saved preferences, no dialogs or errors.

Previous `owner-prank-3` released at `ae511de81bde1a2220fa51f604125099a9caecee` (PR #52). Immediate optimistic cards with serialized confirmed writes and private-art preload; uncertain failures never automatically retry notifications. 865 frontend tests, TypeScript/build, and isolated layout passed. Claude infrastructure smoke PASSED (handoff 49); Ruggie will check replay speed separately. Public entry and 47 assets match; backend remains `f95830b`/PID 2249061 without restart. Backup integrity/all 58 table counts and protected records match (Main 22/18/18, Lazy 118/92/73). Frontend rollback: `b200c77d67f525a4a1afed515e2baed34dc31dd2`; evidence in CLAUDE.md. Moderation prompt 14 still requires direct approval before its backend/bot release.

Previous `tour-copy-1` released at `b200c77d67f525a4a1afed515e2baed34dc31dd2` (PR #50). Tour 5d has the requested two-line practice copy, and review actions visibly say “Change CWL” and “Change accounts”. 850 frontend tests, TypeScript/build, and full isolated layout passed; Claude's read-only smoke PASSED (handoff 47). Public entry and affected asset hashes matched. Backend remains `owner-prank-1` (`f95830b5b774ba34b29f4756a1cc9e3747148f1b`) at PID 2249061 without restart. Backup integrity and all 58 table counts matched; protected signups/assigned/locks stayed Main 22/18/18 and Lazy 118/92/73. Frontend rollback is `567cd2d37acdff6d27be62e42dfe8ceebb9df789`. The installed staging helper's nested-assets error was worked around in a scratch copy before production activation; the helper still needs repair. Release evidence and rollback command are in CLAUDE.md.

Previous `owner-prank-2` frontend (`567cd2d37acdff6d27be62e42dfe8ceebb9df789`) starts the prank on the first dashboard page, including Tasks, and defers for dirty editors or open dialogs. Claude's read-only infrastructure smoke passed (handoff 44); Ruggie reported that the prank looks good but pauses between cards; entry 45 tracks the speed fix, and live DM delivery has not been verified by Codex. Its release evidence is in CLAUDE.md.

- **Tour/deadline hotfix complete:** `tour-deadline-1`, `8e0ee01337db50da8f2f289d257449c46440a440`, PR #40. Frontend and isolated backend released; bot unchanged. Claude smoke PASSED (handoff 17), Ruggie verified the real-page tour. November uses the stored October campaign close, **Oct 30, 5 PM ET**, with placements by Oct 31, 5 PM ET. Wrong-month defect fixed. 782 frontend / 4,799 backend tests, typecheck/build and layout passed; 24 cleanup cases and seven mutations verified. Backup integrity/57 table counts and protected records unchanged (Main 21/18/18, Lazy 114/92/73). Runtime, public hashes and five-minute timing refresh verified. Next: prompt 11 red signup card and tour refinements, then prompt 10 signup polish; each requires review before release.

- `member-tour-1` released at `16cc79e7db39e3aaadf99c99117994b9103a47e8` (PRs #38/#39), frontend/backend/bot. 774 frontend / 4,797 backend checks passed. Claude smoke PASSED WITH DEFECTS; keep live. Missing-date timeout fixed; campaign-month and real-page tour corrections completed in tour-deadline-1; remaining refinements are queued under prompt 11. Ruggie confirmed Discord dates appear but show the wrong month.

- Member signup flow released as `member-signup-1`, `5539cba3c800d91372fd5c6adc62564a758ddff4` (PR #37, moderation PR #36 first). Frontend, isolated backend and bot verified; 761 frontend / 4,792 backend tests, typecheck/build/layout passed. Claude web smoke and Ruggie's private Discord check passed. The missing-date timeout was fixed in member-tour-1; wrong-month correction completed in tour-deadline-1.

## Decisions — Member signup flow (2026-10-28)

Hotfix review (handoff prompts 01/03): deadline reads are cache-only. A nonblocking startup task refreshes eligible seasons immediately and every five minutes, with one Mongo context, a separate 30-second timeout per season and a 120-second whole-pass cap. Eligibility additionally requires the current/next UTC cycle or the selected member season. Per-season errors preserve the last good value for six hours; changed bindings and closed published seasons cannot reuse inappropriate dates. A failed eligibility read or unexpected pass error is logged without terminating the worker; the next interval retries. Shutdown cancels cleanly after failures. Mutable lifecycle state is registered before startup. Each refresh logs counts and elapsed time; failed passes have exception diagnostics. Unsigned-account summaries show six names plus the remaining count on web and Discord; signup actions retain the full count.

From Luke's feedback; Ruggie approved items 1–5:

1. Home and My clan assignments share a green signup confirmation naming signed accounts and pools. Hidden rosters use unpublished wording. Partial published placements retain their clan sections. Remaining accounts are muted, with signup links only while open.
2. Approved read-only backend fields: linked campaign deadline and deadline plus 24 elapsed hours, converted to aware UTC ISO strings. Null/unavailable campaign data yields null fields. Five-minute per-season cache; local dates and minute-updated relative time in the browser. No schema or signup writes.
3. Approved bot change: Check my signups opens a private member panel through the existing loopback bridge. No shared-post edits or signup writes. The supported campaign UI has no active edit-existing-signup-post action; legacy update handlers are retired. Existing posts stay unchanged; the button appears on the next post.
4. Signup/reminder bodies add “Already signed up? Tap **Check my signups** anytime to see your accounts.” Exactly two buttons, including the website link.
5. My CWL starts expanded and remembers collapse. Sign up, My signups and My clan assignments have separate sidebar entries and a shared step strip. `/my-signups` and legacy `signupPanel=saved` work. Closed signup navigation remains available.

Member signup review fixes: signup and reminder posts 1–5 carry the same button and optional guidance sentence (skip the sentence when it would exceed the message limit). Navigation migrates other section preferences from `wu-navigation-v2:<user>` to `wu-navigation-v3:<user>`; My CWL defaults open and is saved only after an explicit toggle. The original request-bound timing budget was superseded by the background hotfix above. Closed published seasons skip the lookup. Discord published/partial confirmation matches the website. Ruggie dropped preselection: “Sign up the other N” still lists accounts with nothing ticked.

## Released batches

- **Roster images released:** `roster-images-1`, `2279c95c3bc62ac74447c4a66a0a924dde45bda4`, PR #35, frontend + isolated backend restart. Additive migration verified on backup copy; all 54 pre-existing counts unchanged after activation, three image tables empty. Main 19/18/18, Lazy 95/92/73. 753 frontend / 4,775 backend passed (21 skipped), M16 killed. Claude read-only 360px smoke PASSED: entry `index-DuQyJREr.js`, backend PID 1639904/cwd, Announcements and image reads verified; zero writes. Hidden November prevented live checks of channel pickers, statuses and Preview; those remain fixture-tested only. Rollback pair: frontend `190313b`, backend `73fe3fa`. Batch complete.

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
- **Weight ranges:** minimum and maximum inclusive (Ruggie, 2026-10-30): “maximum and minimum should INCLUDE those, not excluded.” Known 179,000 is inside 172,000–179,000; missing weights remain excluded. Validation still requires minimum < maximum. A shared maximum/minimum boundary within a pool produces a non-blocking Clan settings note, never a save block. This supersedes the earlier exclusive-maximum decision.

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
   - Renders 50, then Load more. Prompt 32 replaces select-all with Select 15 / Select 30: replace selection with the first unlocked matching accounts in the current filter/search/sort order, including rows not yet rendered. All N appears only for at most 50 matching accounts; Clear appears when selected.
   - Selection persists across filter changes (`N selected · X hidden by filters · Y not shown yet`). Actions list hidden selections.
   - The 50-per-action cap is enforced while selecting. A 51st selection is rejected with “50 is the most per action”; quick picks with fewer available accounts announce “Only N unlocked accounts match”. Hidden selections still count toward the cap.
9. **Sort:** default "Unassigned first" (then weight high → low). Also Weight, Name, TH, Assigned clan, Signup time, and a Group by Discord user toggle. Persisted in localStorage (validated, try/catch).
10. **Auto-place** is a stat chip (and in `⋯`), not a main button. Same preview flow; asks Main or Lazy on the All tab.

## Decisions — Compare clans (2026-10-27)

- **B2 fixes:** full-width publication banner with retained status during refresh and short local dates; Finalize comparison loads only on Review. Changed publications always disclose “Also included: any weight or signup-detail changes not listed above.” because the published export omits some server comparison fields. Confirmation readiness, revision and toast/tab behavior have regression coverage.

1. Re-check cached locations every 5 minutes only while Compare and the document are visible with at least one clan chosen; poll updating results every 2 seconds, capped at 90 seconds. Keep last-known per-tag results and age.
2. Show `Now in: <clan> · <age>` or `No clan · <age>`; `Checking…` only before the first result. Show an amber Outside family tag from the last verified result.
3. Clan tallies count all assigned accounts, ignoring TH filters: in clan, elsewhere, checking when nonzero, and amber outside family when nonzero.
4. Opening, season and pool changes use cache; only Refresh locations forces a lookup. Errors retain results with one quiet toolbar note.
5. Town Hall options come only from accounts assigned to the current pool's hosting clans; retain selected zero-match options, high-to-low order and Unknown TH.
6. Show configured weight ranges and an amber Outside weight range tag (minimum and maximum inclusive (Ruggie, 2026-10-30)); exclude missing weights from range checks.
7. Red/green compares last-known location to the draft column in both pools. Fetch published context on open and roster refresh/revision change, not the timer; show Moved since publish or Not published yet where applicable.
8. Phones use page scrolling; desktop column height follows the viewport instead of a fixed 520px limit.
9. Compact Filters / Sort / Refresh-age toolbar; reuse ActionPanel and roster filter pieces with counts. Choose clans includes search, max-10 selection and ordering. Phones use swipeable clan cards, selected players and fallback arrows; column replacement moves to the header menu.
10. Compact player cards retain red/green backgrounds, name and weight, tag/TH/lock, current location, outlined readable tags and published context.
11. Clan headers use capacity-card styling: full name, count, league/tag/range, shared Total formatter, incomplete-weight note, location tally, average TH and a capacity bar.
12. Desktop navigation appears only on horizontal overflow, checked on resize/clan changes: arrows, Jump to clan, edge fades, scroll-snap and a visible scrollbar.
13. Publish awareness adds permission-aware pending-placement banners, draft-only placement toasts (never signup toasts), Finalize's placement change list, first-publish wording and retained explicit confirmation; no automatic publication.
14. Card body opens the existing Details modal; extract the roster menu without behavior changes. Compare offers only DM ↗ and Details; Escape restores focus and targets remain at least 44px.

15. Replace all roster and Compare ⋯ action menus with a shared React Aria popover: only one open, closing on outside tap, Escape, action selection, focus out, tab/pool/season changes and detached phone scrolling. Preserve items, permissions and Discord link behavior.
16. Compare defaults to Weight: high to low, including on pool changes (Ruggie, 2026-10-30); known weights descend and missing weights come last in stable name order. Explicit choices persist until the pool changes. Accounts & signups and Compare Sort triggers show the ArrowDownWideNarrow icon and active option label, retaining “ · Grouped” where applicable. Accessible labels name the active sort and grouping. Labels stay single-line with ellipsis; toolbars fit 320, 360 and 1440 px. Options, persistence and sort panels stay unchanged.

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
6. Live range preview shares Compare wording; minimum and maximum inclusive (Ruggie, 2026-10-30). No instructional paragraphs.
7. Clan name/count 15px bold; values 14–15px regular; supporting labels 12px muted. Check color and text-fill. Gold identifies selection/active state.
8. Archived settings remain visible as read-only text with no Save.
9. **B2, Ruggie-approved:** remove lower_league from application reads, responses, validation, writes and the frontend type. Requests containing it are rejected as unknown fields. Keep the database column and existing values untouched; no migration.
10. Changed settings show a live, expandable outside-range impact list (known weights only, minimum and maximum inclusive (Ruggie, 2026-10-30)) and over-capacity count. Save changes rules only and its toast is not labelled Draft only.

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

- Linked-account request cadence predates Member signup: `accountDisplay.ts` already polls every 750 ms while updating (up to 135 seconds), with separate loads for each page visit. Home and Signup retained their original calls; MemberAssignments adds one necessary load for its new remaining-account summary. MemberSignupStatus makes zero fetches, and App's signup load is gated to the signup view, so there is no summary/page duplicate to combine. Consider shared page-transition snapshots separately.

- Wire `web/cwl/tests/member-signup.browser.cjs` into `npm run test:layout`; its member-specific checks currently run manually.
- Restore the closed-state helper: "Select another season or ask staff for help."
- Discord partial My signups pages count all signed accounts but list only waiting accounts, allowing empty final pages at 16+ accounts.
- Consolidate the campaign embed length rule; use a process-owned timing client rather than one per batch; strengthen surviving M3d/M4b mutation gaps.

- Resolved in Member signup polish: member pages use one local season/status/deadline line and omit the internal Draft chip; staff presentation is unchanged.

- Roster images: after Mark as checked, a returning clan gets a new post without a reminder; an accepted original post remains an orphan in Discord.
- Roster images: duplicate consent is checked in both `roster_image_posts.py` and storage `claim`; either check alone survives M11/M13. Keep both covered.
- Roster images: dismiss's “still published” check (any account) and `groups_for` (first account) can drift.
- Staff must select each pool's image channel before its first post.
- Investigate whether a reload loop can run uncapped: a Declaration readiness tab left open across the backend restart logged hundreds of repeated auth/me + seasons requests and four 502s; requests stopped after navigating away. Weight-totals-1 owner 360px smoke also logged about 25 back-to-back auth/me + seasons GET pairs, with no writes or console errors. Cause not yet established.
- Hidden roster limitation: the image section only shows the hidden line, so staff cannot pick an image channel until publication.

- Pre-existing roster season-menu history issue: without Details, Back can show
  `season=1` in the URL while the page still displays the newer season.
- Screen-reader browse mode may skip the MapPin's non-focusable `role="note"` accessible name; consider real visually hidden text with only the pin hidden.
- Add mutation coverage for clearing roster state on season change; the targeted mutation survived readability review.
- Unobserve removed horizontal-fade children before the ResizeObserver disconnects.
- Replace native `window.confirm` across the rest of the app. Roster exits use an in-app dialog, but other existing callers remain outside the hotfix scope.
- Details: a successful save followed by a failed reload drops the Undo toast.
- `RosterWorkspace.tsx` restates the weight dirty rule separately from `dirty`;
  consolidate these rules in a later cleanup.
- Signup guard tests do not yet pin `signupDirty` or `selectedTags`: removing either still passes those tests.
- The older layout runner can treat a child process killed by a signal as success (`run-layout.cjs:158,219,275`); make signal exits fail explicitly.

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
- CWL sidebar order: Seasons, Signup reminders, Build roster, Finalize roster, Announcements, Declaration check, Return reminders, Results & participation, Bonus medals, Exports & history. Other staff destinations use the flat Clans, Members, Bot and Admin groups.
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

Main/Lazy image channels are saved server-side and carried over. Post per pool sends one message per clan, with no pings, idempotent receipts and retry of failed messages only. Republish updates existing messages in place; a new clan gets a new post, and a dropped clan's post is edited to “<Clan> is no longer hosting · Roster vN”, never deleted. Test all sends to a chosen channel with production-identical content and no TEST label and is never recorded as production delivery. Preview and download remain. Ruggie approved the backend and schema work for that separate batch.


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
- Test all uses the shared saved test channel, supports a per-send override and explicit confirmation. Saving a new shared default is opt-in. Main and Lazy copies use the existing test endpoint, production-identical content without a TEST prefix and no mentions; they never become image-post records. Single-clan testing remains available.
- Without cwl_send the card exposes statuses only. Preview images mount only while their disclosure is open.
- Backend and schema approved. Release requires an isolated backend directory, restart and readiness gate; development/review use temporary SQLite plus fake Discord only.

Roster images review fix: explicit uncertain recovery always targets the current published version. New-post recovery retains the duplicate warning; update/drop retry PATCHes the same message with newly frozen metadata for the new version. A previously dropped clan returning in a newer publication recovers with update. Pool status includes the number needing checking. Older recovery versions still return 409.

A new POST cannot replace an existing active message, including a failed update. A confirmed update 404 clears only the active message reference (the durable receipt/audit retain the old ID), enabling the approved Post again path. Cancellation records uncertainty then propagates; post 404 describes the missing channel/message, and opt-in 5xx is uncertain. Individually tested replay/acquisition/wrong-action guards protect delivery.

Roster images fix 2: a removed clan's uncertain update recovers as a drop edit on the same message at the current version. A removed clan's uncertain new post has a confirmed “Mark as checked” action: only its local post row becomes `dismissed`, with an audit entry and no Discord call; the original uncertain receipt is retained. A checked row can be posted normally if the clan later returns. Server-side duplicate consent (`confirm_duplicate: true`) is required for a new POST over uncertainty, both before rendering and in the atomic claim; only the explicit duplicate-warning recovery sends it. Known-message protection uses one shared predicate at both boundaries.

The storage owner migrates the existing `roster_image_posts` CHECK constraint to allow `dismissed`, transactionally copying every existing row and preserving IDs, receipts and audit history. No additional permanent table or image bytes are introduced. Initialization is idempotent; migration/reopen integrity and foreign-key checks are covered by isolated tests. Release still requires the already-approved backend/schema rollout, not a frontend-only deployment.

## Decisions — New-member tour (2026-10-28)

1. Signed-in members and staff are invited on Home. Browser-only localStorage (not account-specific) caps automatic Skip at three browser sessions; sessionStorage prevents reloads or in-app navigation from asking again in the same session, including after X. Finish or Don't show again persists dismissal. Help & tour always replays and its Skip does not consume the automatic limit. Storage failures are harmless.
2. Eight numbered steps include the six practice substeps. Demo Barbarian and Demo Warriors are pure presentation, never API submissions. Targets advance without navigating the underlying page. Exit restores the original menu, scroll and focus.
3. A modal spotlight uses a gold ring, white SVG glove and two ripples; phones open the menu for navigation steps and reserve space above the bottom card. Focus is trapped, Escape exits, motion reduces to fades, and all controls have 44px targets. Confetti appears only in practice success and is hidden for reduced motion.
4. Ruggie's Fan Kit selections are cropped at alpha >60 and exported as 340px WebP assets, loaded per step from `/assets/tour/`. Non-wide art renders at 140px phone / 160px desktop height, with maximum width equal to that height (Claude handoff entry 7 clarification); padding follows the art width. Wide art sits across the top at 220px width and at least 90px height. Desktop placement tries right, left, below and above without clamping into a target. Phone menu follows breakpoint changes. SOURCES.md records provenance and the exact notice on Welcome/Help and Finish. No backend or dependency change.

## Later — Member tour release review

- Below roughly 450px viewport height, placement.ts can place Next off-screen; spotlight tap/Escape still work.
- Test gaps recorded at release: no art-height cap, no text/art overlap assertion, and no chevron assertion.

### Tour/deadline hotfix (prompts 07/08; released as tour-deadline-1)

Ruggie removed the Fan Content Policy notice from the tour on 2026-10-29;
Claude noted the policy asks for it where Supercell art is used.

The tour follows real Home, Tasks, Sign up, My signups and Assignments pages.
Practice drives only the form's existing React pool/account/review state. Sign up
is inert, and the API boundary rejects non-GET calls while the tour is open.
Exit restores the original page and signup draft in a finally-protected session.
Tour page moves replace history; Back closes the tour and restores the draft.
Only the target sidebar section is temporarily expanded. Account-load failures
remain visible and allow continuing; dirty staff editors show an explanation.
Navigation and Tasks preference
persistence are paused. Normal display-cache refreshes after returning to a page
are not signup drafts. Phone targets follow drawer transitions and remain above
the tour card. U35/U13/U18/U15 replace the mock practice art and controls.

Campaign timing research: `utils/cwl_campaign.py` `signup_deadline` resolves the
campaign's literal cycle month; `extensions/tasks/cwl_reminder.py` schedules the
current/following signup cycles and its legacy close is month-end minus two days.
`cwl_web/manage_bridge.py` stores the selected binding verbatim, while
`web/cwl/src/announcementMonth.ts` derives that selection from the CWL season
label. Member timing therefore loads the preceding signup cycle: November CWL
uses October, January uses December of the prior year. A missing earlier campaign
uses the bot's merged guild defaults for that signup month (prompt 08); unavailable
Mongo retains the existing last-good/null cache behavior. Eligibility, refresh interval,
timeout and last-good cache rules are unchanged. This requires a backend release
alongside the tour frontend; both shipped in tour-deadline-1. Live stored campaign overrides yield October 30, not the built-in October 29 default.

### Later — tour-deadline-1 smoke follow-ups

- Prompt 11: Back during the tour must preserve the previous history entry; clear the staff Save/discard notice when the editor becomes clean.
- Prompt 11: step 5b highlights the entire selectable account card; keep the glove off its text. Apply whole-block targets to all practice steps and restore the approved playful copy.
- Prompt 11: separate red remaining-signup card below the green confirmation, no account-name list; then prompt 10 signup polish, including Help/account-menu changes.

### Signup card + tour refinements (prompt 11; released)

Separate red remaining-account card immediately below the green confirmation on Home and Assignments. No remaining-account names; singular/plural action opens the existing unselected signup flow. Closed/all-signed states have no red card. The red card repeats the signup deadline even when the placement estimate is unavailable; the green card keeps its previous behavior.

Tour Back restores the original history entry before restoring its URL/draft; the previous Home entry and forward stack remain intact. The staff blocked-start notice clears as soon as the editor is clean. Practice highlights the whole pool card, account card and review block, with the glove below their text, and uses the approved playful copy. No backend, signup-write or Discord changes.

### Signup card release — 2026-10-29

Released `signup-card-1` (`539853e`, PR #42), frontend only. Separate red remaining-account card; zero signups keep the grey card action. Exact approved 13-step tour copy, whole-block highlight, Back history restoration and clean-editor notice clearing verified. Claude smoke passed (handoff 23); 788 frontend tests, build and full layout checks passed. Production counts and protected records unchanged; backend remains `8e0ee01`, no restart. Rollback and backup evidence are in CLAUDE.md. Signup-polish items 1–10 are the next approved batch, not yet implemented by this release.

### Member signup polish — released 2026-10-29

Items 1–10 implemented frontend-only: unique member/staff-CWL menu icons; bold current signup step with Fan Kit Villager 52545/52538/52543 art and compact other steps; unnumbered member strip; one local season/deadline line without Draft; Main CWL naming and whole-card pool selection; review Change links retaining eligible selections and listing removed accounts; "your CWL clans" copy; pinned Help menu row and profile/avatar account menu. Internal staff season state is unchanged. No backend, schema, endpoint, bot or signup-save contract changes. The duplicate member season/Draft Later item is resolved by this batch. Release docs for preceding signup-card-1 were merged through PR #43.

Released `signup-polish-1` (`ef90834`, PR #44), frontend only. Claude smoke passed (handoff 30): 360px signup steps, approved Villager art, copy, unique menu icons and account menu; GET only, no overflow. 804 frontend tests, TypeScript/build and isolated layout passed. Protected counts unchanged; backend `8e0ee01` unchanged with no restarts. Backup, public hashes and rollback targets are in CLAUDE.md.


## Decisions — Staff navigation (2026-10-29)

Approved prompt 13: keep member navigation, all routes/view IDs and item permissions unchanged. Replace the staff fold-out with a STAFF TOOLS label, direct Staff overview and Moderation links, and top-level CWL, Clans, Members, Bot and owner-only Admin groups. CWL results and Replacements are flat items. Empty groups and unauthorized direct links remain hidden.

Use unique Lucide meaning icons across rendered menu items and groups; TicketCheck is available, so no fallback is needed. Labels are Declaration check, Image gallery, Tickets and Ticket settings, including page titles. The current group opens on navigation/remount, while manual collapse works on the current page; other staff groups default closed; only explicit toggles persist validated booleans in wu-navigation-v3. Obsolete keys are discarded. My CWL and the tour's temporary expansion/restoration behavior stay unchanged.

Released as staff-nav-1 after Claude ACCEPT (handoff51); read-only owner click smoke PASSED (handoff52). No backend, route or permission changes. Role-based fixture checks cover member, cwl_roster-only staff, multi-permission staff and owner at 360×800 and 1440×1000. Four mutation checks cover nested groups, duplicate icons, missing current-group auto-open and bypassed permission filtering.

## Decisions — Build roster readability (approved 2026-10-29)

This frontend-only Accounts & signups presentation pass supersedes the older card, Draft pill, total-weight and combined signup-alert descriptions above. The shared current-clan line uses an outline `MapPin` with accessible “Now in” labeling across Accounts, Compare, Declaration and dialogs. Desktop Accounts rows at about 900px and above use aligned Name, Pool, Assigned clan, Now in, Weight and menu columns; phone cards keep their existing layout and actions.

The Build header retains its season and signup controls. A single slim gold-accent line reports Draft, Hidden or Published state and version/date, with Review navigation only where authorized. If draft placements differ from a published roster, it says members still see the previous version. Under it, the amber signup-change count opens review; a separate red line for an affected clan below its known war size names the worst shortage, adds `+N more` when needed and opens Compare. A clan card without known weights reads `Total: no weights yet`; other totals remain as before. The summary-chip and main-tab rows show edge fades only when content overflows. Existing permission checks, publication reads, saves, Undo, review behavior and HTTP contracts remain unchanged.

The card capacity-note suppression is coupled to the existing reason string in `cwl_web/placement_status.py:17`; update the match if that server wording changes.

## Decisions — Roster hotfix (approved 2026-10-29)

The first readability phone smoke failed: 23 per-clan missing-capacity warnings pushed the workspace down, and a pre-existing native confirmation silently trapped unsaved weights on Android. The hotfix shows **at most one** warning line, counting only non-archived hosting clans with at least one account assigned in the current season and no configured 15/30 capacity. The link focuses the first affected clan in list order. Zero affected clans show no line; one names the clan; two or more show the count. No assignment, capacity rule or API behavior changed.

Dirty roster tab, season, rules/Compare pool, sidebar and capacity-link navigation stores the requested action and opens the in-app dialog: `Unsaved changes`, `You have N unsaved weight(s).` when only weight drafts are dirty, otherwise `You have unsaved roster changes.`, with Discard and Keep editing. Keep editing, Escape and backdrop retain drafts and focus; Discard clears them and runs only the requested action. Saves in flight show `Wait for the save to finish.` with OK and refuse navigation. **Accounts & signups All/Main/Lazy pool filters keep selections without a discard prompt**, including hidden selections, as before. Native confirmations elsewhere are deferred to Later.

Missing weights has one `Enter weights as: Loot | Full` control above the queue, default Loot. Rows have only their input and Save; changing the unit reinterprets unsaved text and updates each full-weight hint, never saved weights. Explicit saves, units, conversion and API payloads remain unchanged. The hotfix is frontend only. Claude accepted the corrected pool-filter behavior (handoff61) and the read-only owner 360px release smoke passed (handoff62); the initial readability smoke remains recorded as failed.

## Decisions — Weight totals (approved 2026-10-29)

Ruggie decided that a clan weight is always a total. Assign current/projected and Balance current/preview display the sum of known effective weights, grouped in `k` (for example `4,512.5k`); no known weights displays `Total: no weights yet`. Keep the weighed-count hint when the total is partial and retain `Avg TH`, which measures Town Hall level rather than weight. Balance math, sorting, ties, API payloads and save behavior are unchanged. The frontend-only release also fixed the second `playerDirty` dialog after roster Discard on Fill spot / Signup Details. Claude accepted the fixture review (handoff 63) and the read-only owner 360px release smoke passed (handoff 65).

## Weight range and quick selection — prompt 32 (released October 30)

Both endpoints of a configured range are inclusive throughout status, impact, eligibility and automatic planning. Wording uses “Range: 172k–179k” and “Includes 172k to 179k.” No assignments or locks are changed by evaluation. Compare defaults to descending weight; quick picks and the selection cap follow the updated contracts above. Frontend/backend release and read-only smoke passed as recorded in the October 30 status above.

## Decisions — Announcement followed by roster images (prompt 45)

A reviewed pool send posts the existing role-pinging announcement, then one full-resolution
attachment message per hosting clan, then a closing note, all in the announcement
channel. Images and closing never allow mentions. Clan messages contain only the
bold clan name and an Open clan link; the closing says “Can't find your name? Check
My assignments.” and links to My assignments. Multi-page rosters stay in one message.

One shared order applies to review, delivery, image lists, tests and the carousel:
Lazy trailing clan numbers descend, then unnumbered names alphabetically; Main
capacity 30 first, then 15, then other/unset, alphabetically within each group.
Capacity and accounts come from the immutable published version. Review names the
channel, announcement pings, ordered clans and closing before staff confirms.

The durable server sequence starts images only after its matching announcement
receipt is confirmed, stops on the first failure, and resumes in order. Unknown
outcomes require explicit check-first recovery; they never trigger automatic retry.
Resume names the next clan and does not repeat the announcement. Tests use separate
receipts and the shared saved test channel (or local override), omit TEST labels and suppress all mentions.

Republishing does not resend an announcement: existing clan messages update in
place, added clans append after the closing, and dropped clans are edited as no
longer hosting. Existing legacy image posts retain their saved channels. New
sequence images use the announcement channel; no separate image-channel choice.

Addendum 1: only Discord 404/code 10008 proves an image or closing message was
deleted. Such updates repost once without pings, retain the old receipt and show
“Reposted (old message was deleted)”. Unknown Channel, forbidden access and uncertain
outcomes stop. An update confirmation includes the closing-note check.

Addendum 2 supersedes the announcement exclusion: a deleted announcement may be
sent again only after an explicit staff review warning that its roles ping again.
A read-only check runs on the sent pool's Announcements view, with a rate-limited
manual fallback. Confirm rechecks deletion, archives the old receipt and uses the
current publication for the new announcement/images/closing sequence. Merely opening
the page never posts. November is not automatically resent or migrated.

Recovery clarification (Claude entry 164): a native sent occurrence with an unknown
announcement message can be continued only through staff's explicit “Post clan
images now” review. It lists the saved channel and clans and says no pings. A
separate durable assumption receipt records the actor/time/native receipt; the
announcement message ID remains unknown. The guarded continuation permits only
images and closing, never queues another announcement, and rejects a second
confirmation. The assumption receipt is retained on rollback with other additive
sequence tables.

### Announcement rework47 verification

Current-publication review, automatic deleted-message detection and locked-channel
ambiguous full-test retry were inspected on the fake-Discord preview at360px;
normal review and the resulting fake sequence were also checked at1440px. Twelve
fake posts followed announcement → ordered clan images → closing for both pools,
with no mentions in image/closing payloads and no browser errors. Intercepted
10008-equivalent reads showed Send again automatically without opening a send
confirmation; intercepted500 tests kept the channel disabled and reused identical
request bodies. These are isolated transport/UI checks, not live delivery proof.
Backend5210 passed,21 skipped,221 subtests; frontend1084 passed; TypeScript/build
passed. Thirteen backend mutations and a current-clan-list UI mutation were killed.

# CWL roster Release 1 — commit 3 checkpoint

Date: 2026-10-27. Scope: selection and action flow on the existing backend.

## Completed for review

- Pure filter, sorting, grouping, selection, and plan-presentation models (commit 1).
- Shared responsive ActionPanel, browser Back handling, anchored desktop positioning,
  keyboard focus cycling/restoration, reduced motion, and Undo feedback (commit 2).
- Sticky permission-aware selection bar; Assign, Signup, Balance and Auto-place panels;
  All-pools Auto-place chooser; selected/hidden account reviews; current capacity and
  known-weight averages; immediate placement actions with existing revision/Undo API.
- Manual assignment still sets placement locks. Unassign clears them and keeps signups.
- Signup switching/removal retain confirmations and identify affected locked accounts.
- Removed superseded inline panel, preview, Undo markup and their unused styles.

## Verification

- TypeScript: `npx tsc -b` passed.
- Frontend: 97 test files, 423 tests passed. Coverage includes filter section semantics
  and facet counts, global missing-weight scope, hidden/select-all selection models,
  sort persistence fallback, known-weight averages, signup review warnings, Undo
  states, panel history, desktop placement and focus cycling.
- Backend: 78 tests passed across `test_cwl_web_roster.py`, `test_cwl_balance.py`,
  `test_cwl_staff_signup_changes.py`. Existing aiohttp AppKey warnings remain.
- Build: `npx vite build --outDir /tmp/wu-roster-release1-build` passed.
- No lint script/configured lint command exists in the frontend package.
- Browser: actual dashboard against isolated temporary SQLite + fixture providers,
  loopback port 8896; no live data or Discord messages involved in workflow tests.
- Checked 360x800, 412x915 and 1440x1000 layouts; no horizontal overflow at mobile
  widths. Selection actions remain reachable; panels scroll internally. Desktop
  panel stays inside viewport and anchors above its selection-bar trigger.
- Verified Back closes only panel, retains selection and returns focus; Tab and
  Shift+Tab cycle inside panel. Search does not autofocus and expands mobile panel
  to viewport height when focused. Signup panel sizes to its contents.
- Assign -> Undo, Unassign -> Undo, Balance preview -> Apply -> Undo passed using
  real fixture backend routes. Locked and missing-weight selections were skipped
  by Balance and listed separately. Placement totals returned to their prior values.
- Filter-hidden selections remained included and named in removal/switch review.
- Two-tab concurrent edit test: stale Undo was rejected, refreshed safely, and
  displayed 'Undo no longer available'; later edit remained intact.
- Permission-loss handling closes panels and clears selection; endpoint regression
  tests cover authorization. No runtime production permission grants changed.

## Production build incident

A delegated builder ran `npm run build` instead of the isolated build command,
writing to `web/cwl/dist`, which is served live. This briefly exposed unapproved
frontend assets. The exact pre-change `bad19e1` source was exported to /tmp and
rebuilt; its assets were restored with index.html last, retaining existing asset
files. The live HTTPS index was compared byte-for-byte with that baseline and
matched. No production database, signup, service or notification mutations were
performed. Further builds use an explicit /tmp output directory. This checkpoint
is not approved for deployment.

## Explicitly deferred until user approves screenshots

Commits 4–5: unified live filter UI and counts; remove League; merge Show/Readiness
into Status; clan chips; compact header/publication status from draft_changed;
GLOBAL missing-weight UI and listPool/poolFilter correction; card tap targets/menu
including Discord profile DM link; green selected card styling; progressive list;
full matching select-all; persisted sort/grouping UI; final regression/screenshots.
The current screenshots therefore still show the old surrounding header, filters
and card styling. The new models are tested, but those UI integrations are not done.

No backend policy, algorithm, database schema, published roster, Compare clans,
capacity/overfill policy, or selection limit was changed. Weight editing keeps Save.
Screenshots: /tmp/wu-roster-release1-checkpoint/{360,desktop}-{selection,assign,signup,balance}.png.
Real touch hardware and screen-reader testing are not claimed; browser checks and
source/test evidence cover the interaction standard scope above.

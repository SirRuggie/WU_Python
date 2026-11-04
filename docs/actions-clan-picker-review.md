# Return actions and clan picker — task 157 review

Prepared November 4, 2026 on `codex/actions-clan-picker-157`. The task started
from `9552757eae8ebb2c7bd5a779f058aab26cc75f97` and was fast-forwarded to released
main `a1a8b937` before final integrated checks. Task 159's released implementation
is preserved. Release remains held for the owner's release decision; this review
does not establish the current public deployment state.

## Result and boundaries

Return reminders reuse `SelectionActionBar` and the shared `ActionMenu`. Desktop
keeps the count, small selection links, Change frequency, and Pause visible;
Resume replaces Pause when every selected clan is paused. Other actions move to
More actions. Send now, Check away players, and Start return reminders precede
the separated destructive list actions. Existing capture and mixed-selection
Resume actions remain reachable when applicable. Phones retain one Actions menu.
The semantic separator is not actionable, and destructive items have a danger
style in addition to their explicit labels.

The overview's `openBatch` boundary and `returns/ReturnBatch.tsx` are unchanged.
The latter remains byte-identical to released main, SHA256
`9aa34fd3814c4ffdd92cb76387fddbac5cecedb33c478732cfe2da4406d9e9e4`.
Review, confirmation, hidden/inapplicable/unavailable clan exclusions, revisions,
request identity, uncertain-outcome recovery, and receipt handling retain their
existing owner. No notification retry, route, storage, authorization, mention,
destination, or backend implementation was added by task 157.

Clan weights reuse `CwlPageHeader` and the season picker `rosterUi/Menu`. The
picker already supported filtering; its public option model now also accepts a
status tone. The button shows only the clan name. Options show named progress
and a supporting green/amber dot. Unknown progress has no success dot. The list
holds roughly eight rows on desktop; narrow phones use the existing search
panel. The picker fills the width below the title on phones. The obsolete custom
picker, repeated clan heading, management eyebrow, and their obsolete styles were
removed. Find any player and the player editor retain their existing behavior.

The last successfully opened clan is stored under
`wu-clan-weights:last-clan:<viewer-id>`. Restoration requires membership in the
currently returned directory. Explicit clan/player deep links take precedence;
storage failures are nonfatal. `App` supplies the signed-in viewer ID and remounts
the feature on viewer change. Browser storage is a convenience, not an authority
or a source of permitted clans.

## Regression and failure evidence

Private evidence is retained below this worktree's `.local/actions157/`; it is
not deployment output. Nothing builds into `web/cwl/dist`.

| Check | Result | Evidence |
| --- | --- | --- |
| Initial full frontend | 1,789 tests / 296 files passed, 31.07s | `full-frontend-605.log` |
| Final integrated frontend | 1,794 tests / 296 files passed, 30.99s | `full-frontend-integrated-606.log` |
| Final TypeScript | exit 0 | `tsc-integrated-606.log` |
| Final private Vite build | exit 0, 10.40s | `build-integrated-606.log`, `build-integrated-606/` |
| Integrated Python syntax | all 26 Python files added/changed by released task 159 compiled | `compile-python-integrated-606.log`, file list beside it |
| Action/weights focused suite | 51 tests passed | `all-action-guards-added-605.log` |
| No-confirm mutation | killed by 9 intended zero-write-before-confirm assertions | `mutants-605/proof.json`, mutant source/config/log retained |
| Hidden-clan mutation | killed by 9 intended exclusion assertions | same proof, separate mutant source/config/log |
| Original layout fixture | 8 layouts / 12 screenshots passed | `layout-605c/proof.json` |
| Final GET-only preview layout | same unchanged assertions: 8 layouts / 12 screenshots passed | `layout-readonly-606b/proof.json` |
| Preview write denial | both pages reject before their fixture handler; static server POST returns 405 | `preview-smoke-606b.json` |

The nine action cases are frequency, pause, resume, send, away, start, replace,
clear, and capture. Each asserts zero writes before review, zero writes after
review, zero writes after cancellation, then exactly one confirmed write to the
existing route with the existing revision and permitted visible target. Hidden,
expired, and no-longer-available clans are named in the exclusion list. These
tests use mocked receipts; they do not establish live Discord or push delivery.

Actual mutants ran against isolated copies of the production batch component.
The no-confirm mutant injects a POST when Review action is clicked. The hidden
clan mutant disables the hidden-ID exclusion. Each failed its intended behavior
assertions, rather than failing to compile or import. Production source was not
mutated. The full mutation descriptions, hashes, failing logs, and source copies
remain in `mutants-605/`.

The full suite also covers the existing request identity, duplicate submission,
failed reads/saves, auth denial, partial results, access loss, stale responses,
bounded progress polling, discarded/canceled edits, and war selection behavior.
Task 157 introduces no worker, scheduler, persistence, or delivery changes; a new
live notification or restart experiment was outside this frontend review.

## Interaction and accessibility scope

Real headless Chrome checks covered both pages at 320, 360, 390, and 1440 pixels
with fictional sample data. All eight layouts had zero horizontal document
overflow, page errors, or network writes. Desktop assertions inspect visible
button geometry to establish a single selection row. The menu order, one semantic
separator, two danger entries, keyboard opening, Escape, and focus return were
verified. Picker checks cover 12 options, text filtering to one result, progress
in the option's accessible name, status dots, keyboard selection, a name-only
trigger, Escape focus return, and remembered selection after reload.

The retained screenshots were visually inspected at narrow and wide widths,
including the 320px action sheet, 1440px action popover, filtered picker and selected
editor. Long clan/player names remain bounded. The existing player table and
sticky editor save bar remain outside the layout change. The standard's existing
text/labels, native controls, 44px menu items, shared modal focus handling, and
disclosure behavior remain in use.

Screen-reader review here means accessible roles/names and keyboard/focus checks;
speech output with an actual screen reader was not exercised. This is not a WCAG
certification, physical-phone test, or complete audit of unrelated dashboard pages.

## End-to-end adversarial review

| Boundary | Review evidence and result |
| --- | --- |
| Authorization and destination ownership | No backend or destination changes. Batch retains provider-returned permitted options. Tests exclude a selected clan absent from those options; existing auth-denial tests clear protected rows/counts. |
| Hidden selections and malformed inputs | Hidden IDs retain explicit skip reasons. Existing batch validation/revision routes are unchanged. Invalid or inaccessible remembered values are ignored; optional browser storage does not grant access. |
| External text and mentions | Names/progress remain React text; no HTML injection or mention construction was introduced. Existing escaped-name tests remain green. No changes to Discord payloads or mention scope. |
| Unavailable/partial data | Unknown progress remains textual and has no success dot. Existing stale membership labels, read errors, retry bounds, and access loss behavior remain covered. |
| Concurrent edits and stale responses | Shared dirty/discard guard is retained when choosing a clan; cancel preserves values and edit focus. Existing revision/stale-response tests passed. |
| Duplicate submission, cancellation, uncertainty | Existing batch owner retained; action matrix verifies review/cancel/write counts. Receipt/request identity and partial-result tests passed. No automatic notification retry was added. |
| Reuse and cleanup | Shared action menu, picker, header, and batch used directly. Removed obsolete custom picker/state/styles; no abandoned replacement component or new backend/storage owner. |

## Bounded design audit

The Impeccable skill was used for a scoped review of these existing operational
interfaces. Its detector report is retained in `impeccable-detect-606.json`.
Implementation integrity passes: the changed surfaces reuse the dashboard's
actual header, menus, focus model, and editor rather than introducing another
component system.

| Dimension | Scoped score | Evidence/limit |
| --- | --- | --- |
| Accessibility | 3/4 | Named native/shared controls, semantic divider, keyboard/focus assertions; no speech-output audit |
| Performance | 3/4 | No new dependency or network fanout; existing Vite large-chunk/import warnings remain |
| Responsive layout | 3/4 | Eight asserted layouts, narrow/wide visual inspection; no physical-device or text-zoom audit |
| Theming | 2/4 | Existing dark theme retained; existing hard-coded colors remain outside this focused change |
| Implementation integrity | 4/4 | Shared owners/components preserved; no new changed-line detector finding |
| Total | 15/20 | Good within this stated scope; no claim about the whole dashboard |

Detector findings were one existing progress `transition: width 120ms ease` and
three existing weight row-state stripes. The latter identify unsaved edits,
explicit row warnings, and suspicious weight values; they are byte-identical to
released `a1a8b937`, as recorded in `preexisting-style-proof-606.json`. Parent
triage persisted a narrow `side-tab = *` waiver through the Impeccable CLI, scoped
only to `web/cwl/src/weightTrial/WeightTrial.css` in `.impeccable/config.json`.
Its reason explicitly records agent triage, unchanged released code, and functional
row-state purpose. No CSS was changed for the waiver, and no other rule was
ignored. The existing width-transition warning remains visible (P2 performance
follow-up); it is not introduced or amplified by this task. A future
`$impeccable optimize` / `$impeccable polish` pass may assess that separate progress
component. No new blocking task-157 design defect was identified.

## Fixture/setup corrections retained for review

These corrections were confined to private fixtures, build configuration, browser
setup, or a metadata command. Prior sources/configurations and failed logs remain;
product behavior and assertion strength were not relaxed.

| Observation | Correction and retained evidence |
| --- | --- |
| Vite could not resolve React from the private fixture root | Bound aliases to the existing exact dependency target; original and revised configurations and `layout-build*.log` retained. |
| Private HTML entries were outside Vite's root | Set root to the private fixture directory; old config/build logs retained. |
| Chrome socket path exceeded its platform limit | Used short `/tmp/q157-d7c24bc0` symlink to private disk browser-temp; `browser-tmp-binding.json` retained. |
| Layout waited for a nonexistent table selector | Used the actual unchanged `.weight-trial-editor`; old checker and failure log retained. |
| `display: contents` wrapper has a zero rectangle | Kept the same one-row assertion but measured visible buttons; old checker and failure log retained. |
| Inherited returns fixture allowed simulated POST receipts | Final retained preview adds a private GET-only wrapper; original fixture entry/build retained. Same assertions reran against separate `layout-dist-readonly-606`. No production code/assertion changed. |
| First preview safety smoke found the weights handler recorded an attempted POST before rejecting it | Preserved the failed `preview-smoke-606.log` and old source/build, added the same private pre-handler GET-only guard, then reran the unchanged safety/layout assertions once against fresh `layout-dist-readonly-606b`. Both passed. Parent authorized this fixture-only correction under 605/566. |
| Git worktree metadata was read-only in the sandbox | Fast-forward succeeded with scoped metadata escalation; no reset, pull, stash, or forced update. |
| Bare `python` was absent during a metadata proof command | Used the mandated absolute repository venv interpreter; no test or product change. |

The GET-only preview serves static files with CSP `connect-src 'none'`, no API
proxy, no backend import, and no Mongo/Discord/provider connection. Its server
accepts only GET/HEAD, and both page fetch shims reject attempted writes before
the fixture handler. `preview-smoke-606b.json` records the unchanged explicit denial check;
`preview.json` records its URL/PID. The preview is not an authentication or
production delivery test. The private build and screenshots remain review assets,
not a deployable clean-tagged release.

Retained preview: `http://127.0.0.1:38081/returns.html` and
`http://127.0.0.1:38081/weights.html`, PID 1109578. The static-only server runs
from `preview.cjs` with `layout-dist-readonly-606b` as its immutable input.

## Readiness

READY for review on the local frozen commit; `.local/actions157/final-provenance-606.json`
records its revision and retained evidence hashes. Owner-controlled release,
public asset comparison, clean tagged checkout,
backup/rollback evidence, pushed revision verification, and runtime health checks
remain separate release work. No PR merge, tag, push, service switch, production data
write, or live message was performed by this task.

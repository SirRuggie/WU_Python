# Color tokens 1a — review

Task 165 is in review; release is held for the owner's authorization. This workflow performed no deployment or production write; public deployment state was not assessed. Sol built task 165; a separate independent refuter is still required before final READY. The historical 646-bound comparison passed after the narrow owner-approved 631 fixture-origin correction. Current-main integration and final pixel acceptance remain pending.

## Scope and base

The original independent checkpoint `945e8b0f51ea63de163145602c5611fdef897503` is retained on `codex/color-tokens-165-checkpoint-945`. The branch was rebased onto separately verified accepted task 157 main `646266b680f2fbd51245dff16a23404eb30c0148`; checkpoint HEAD after rebase is `ebdc8a49d2b53e689f146c68047a353b85068a69`. No root checkout, main reset/pull, push, tag, or release was performed. Only the anticipated add/add Impeccable metadata conflict occurred; no source conflict occurred.

The implementation defines all 26 specified `--wu-*` colors in `src/tokens.css`, imports them first in main, and makes the 17 specified roster aliases. Other roster tokens keep their values. The 28 winning contrast rules moved to the end of style.css in the same order, with selectors/specificity/media/forced-colors preserved. The signup guide remains light and navy pool rules remain navy. Later workflow/accessibility imports retain priority. The deleted contrast stylesheet and its three imports are removed;13 standalone entries have the passive global-token bootstrap needed for their styles.

There are 101 reviewed shell bindings,17 roster aliases and 266 further semantic mechanical bindings across 59 CSS files: 384 total global token uses. The 291 sweep candidates were individually classified; 25 qualified colors were held where the selector/state did not match the token role. Pressed/selected tints use accent-soft; warning states use warning-surface even where accent-soft is numerically closer. Decorative count fills, warning-like danger surfaces, ambiguous image canvases, the generic brown menu border and the explicitly preserved signup-guide colors remain raw. No threshold was relaxed to approach 550.

Only three intended visible categories are permitted: roster gold, global focus ring, and success notice border, alongside distance-at-most12 role-matching shifts. CSS source proof records five explicit changed declarations/uses across those categories. Moderation, DiscordPreview, blue/navy, all 29 four-digit and 56 eight-digit values remain unchanged. No backend, authorization, destination, notification, storage, product copy, or interaction behavior changed. Prettier reformatted previously compressed source without changing the non-color CSS contract.

## Counts

Counts use every CSS source under web/cwl/src, including comments and token definitions. The regex is `#[0-9a-f]{3,8}\b`; distinct literal, lowercase, and expanded-three-digit counts are equal for these inputs. Literal `var(--` uses are counted separately from forms with whitespace. The prompt's 705 distinct estimate is not reproduced. Counts are against the actual accepted task 157 base, rather than the original a1a8 checkpoint.

| Measure                   | Exact646266 base | Candidate |
| ------------------------- | ---------------: | --------: |
| CSS files                 |              109 |       109 |
| Hex uses                  |            1,399 |     1,036 |
| Distinct hex values       |              739 |       608 |
| Eligible 3/6-digit uses   |            1,314 |       951 |
| Distinct 3/6-digit values |              701 |       570 |
| Literal var(-- uses       |              555 |       939 |
| Files with no var()       |               58 |        18 |
| 4-digit uses              |               29 |        29 |
| 8-digit uses              |               56 |        56 |

Per-token total bindings (including the 17 aliases and 101 foundation bindings):

| Token                  | Uses |
| ---------------------- | ---: |
| `--wu-border-subtle`   |   64 |
| `--wu-surface`         |   57 |
| `--wu-text-muted`      |   57 |
| `--wu-accent-soft`     |   16 |
| `--wu-surface-raised`  |   24 |
| `--wu-text`            |   37 |
| `--wu-surface-soft`    |    8 |
| `--wu-danger-surface`  |    3 |
| `--wu-border`          |   26 |
| `--wu-focus`           |    7 |
| `--wu-accent`          |   27 |
| `--wu-warning-surface` |   14 |
| `--wu-accent-ink`      |   17 |
| `--wu-success-surface` |    7 |
| `--wu-danger-border`   |    1 |
| `--wu-warning-border`  |    5 |
| `--wu-warning`         |    5 |
| `--wu-card`            |    1 |
| `--wu-danger`          |    1 |
| `--wu-success`         |    1 |
| `--wu-bg`              |    4 |
| `--wu-success-border`  |    1 |
| `--wu-accent-hover`    |    1 |

The private `reviewed-sweep.json` records all 291 decisions, old/new colors, RGB distances, selectors and properties; `counts-final.json` records the final inventory. Earlier ledgers and counts are retained as historical stages, not relabeled final.

## Verification

All evidence below is private under this worktree's `.local/color165/`.

| Check                        | Evidence and result                                                                                                                                                                                                                                              |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 646-bound full frontend      | `rebase-646/full-fe-626.log`: 1814 passed in 296 files, 27.37s                                                                                                                                                                                                   |
| TypeScript                   | `tsc-626-encoding-fixed.log`: exit 0; explicit fs encoding is the authorized 582 type-only correction                                                                                                                                                            |
| Private app build            | `build-626.log`: exit 0,10.62s; output `app-build-626/`                                                                                                                                                                                                          |
| Test-only asset parity       | `proof-626.json`:all 132 build asset files byte-equal to the preceding product-source build                                                                                                                                                                      |
| Existing/new contrast        | Seven preserved roster pairs plus 13 global pairs pass 4.5:1; two rollback guards bring the total to 22                                                                                                                                                          |
| CSS contract                 | `css-contract.json`:108 pre-existing files, 12,068 declarations, 17 aliases; selectors/order/contexts/important/non-color values preserved                                                                                                                       |
| Runtime import-only entries  | `runtime-js-contract.json`: 13 files pass separate parse/import/emitted-JS semantic checks; source unchanged by 626                                                                                                                                              |
| Old roster gold mutant       | Current isolated source mutation killed by intended gold assertion:1 failed / 21 passed                                                                                                                                                                          |
| Missing shell primary mutant | Current isolated source mutation killed by intended primary guard:1 failed / 21 passed                                                                                                                                                                           |
| Formatter                    | Initial scoped check covered 84 files; 631 formatted only ParticipationWorkspace.css, then its check passed. All 237 parsed declarations, tree/selector/order/comments/important/value semantics are preserved after quoted-value-safe whitespace normalization. |
| Pixel/layout                 | 312 captures passed at 320/360/390/1440; 631 comparator passed all 156 pairs, with raw images/percentages unchanged and RGB magnitudes retained.                                                                                                                 |

The JS verifier compares full ordered top-level CSS/JS import interleaving and multiplicity after only authorized first-token insertion/contrast removal. It fails parse diagnostics and retains source raw/cooked template values, identifiers/literals, operators/kinds, const/let and semantic flags, modifiers, child order, directives and raw comment order. Actual 13 input files contain no common bundler/TS/coverage pragmas. This is bounded emitted-JS/import evidence, not universal bundler semantics, arbitrary comment-attachment proof, or full TS semantics; tsc is separate.

## Preserved gold and1b inventory

Owner decision 610 confirms all existing live old gold stays as rendered; retirement means no new uses. In particular the signed-out `.login-card > a.button.primary` stays fill/border `#d9a628`, ink `#211b10`, hover `#e7b73f`. The folded shell primary remains `#f4cd64`/`#241b08`. No blanket recoloring exception applies.

Owner decision 621 resolves four otherwise conflicting raw values: divider `#ffffff2b` is excluded alpha8; danger text `#ffaaa5` is 25.08 from danger; selected/hover foreground `#f5d66e` is 13.45 from accent and focus is the wrong role; `#f3ca56` is 14.4 from the matching gold tokens. All remain raw, with no alias/threshold exception. The following complete source inventory includes all remaining old gold and all four 621 values. Conditional controls are source-reachable but are not all exercised by the initial GET-only captures. Incumbent selectors with no exact TSX reference are identified explicitly; no assertion that every selector wins or renders is made. The required root focus definition is distinguished from retired/mismatched uses.

All paths below are under `web/cwl/src/`. Machine-readable evidence: `retirement-1b-final.json`.

| File:line                         | Selector                                                               | Property/value                  | Live/cascade evidence or limit                                                                                                                               |
| --------------------------------- | ---------------------------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `MemberSeasonSettings.css:10`     | `.member-signup-link a`                                                | `color: #f3ca56`                | Live MemberSeasonSettings link; gold distance14.4 exceeds12                                                                                                  |
| `ParticipationWorkspace.css:109`  | `.participation-list-heading`                                          | `border-bottom: #ffffff2b`      | Live Participation list heading divider; alpha8 explicitly excluded                                                                                          |
| `RosterBalance.css:90`            | `.roster-plan-pools [aria-pressed="true"]`                             | `border-color: #edc64d`         | Live conditional pool selector in RosterBalance.tsx:296; plan editor is not opened by read-only initial-view capture                                         |
| `RosterBalance.css:91`            | `.roster-plan-pools [aria-pressed="true"]`                             | `color: #edc64d`                | Live conditional pool selector in RosterBalance.tsx:296; plan editor is not opened by read-only initial-view capture                                         |
| `rosterUi/ActionMenu.css:49`      | `.roster-action-item[data-focused], .roster-action-item[data-hovered]` | `color: #f5d66e`                | Live shared ActionMenu hover/focus or danger option; correct accent/danger distance exceeds12, ring token wrong role                                         |
| `rosterUi/ActionMenu.css:85`      | `.roster-action-separator`                                             | `background: #ffffff2b`         | Live shared ActionMenu divider, alpha8 explicitly excluded                                                                                                   |
| `rosterUi/ActionMenu.css:88`      | `.roster-action-item.roster-action-danger`                             | `color: #ffaaa5`                | Live shared ActionMenu hover/focus or danger option; correct accent/danger distance exceeds12, ring token wrong role                                         |
| `rosterUi/primitives.css:397`     | `.roster-menu-status-dot.is-warning`                                   | `background: #f3ca56`           | Live shared roster menu warning dot, current statusTone conditional                                                                                          |
| `rosterUi/tokens.css:20`          | `.roster-ui`                                                           | `--roster-gold-strong: #f5d66e` | Live primary hover alias --roster-gold-strong in primitives.css; other roster token unchanged per scope                                                      |
| `staffNavigation.css:16`          | `.staff-section-menu button[aria-pressed="true"]`                      | `background: #d9a628`           | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `staffNavigation.css:18`          | `.staff-section-menu button[aria-pressed="true"]`                      | `border-color: #d9a628`         | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:52`                    | `.primary`                                                             | `background: #d9a628`           | Confirmed live signed-out Discord CTA in App.tsx; inside shell overridden by preserved contrast winner                                                       |
| `style.css:53`                    | `.primary`                                                             | `border-color: #d9a628`         | Confirmed live signed-out Discord CTA in App.tsx; inside shell overridden by preserved contrast winner                                                       |
| `style.css:80`                    | `input[type="checkbox"], input[type="radio"]`                          | `accent-color: #d9a628`         | Live native form controls; browser accent color preserved                                                                                                    |
| `style.css:185`                   | `.emblem`                                                              | `background: #d9a628`           | Live Brand image class in App.tsx:1255; image covers background, retained raw value                                                                          |
| `style.css:977`                   | `.completion-mark`                                                     | `background: #d9a628`           | Live conditional signup completion in App.tsx:1066; submission excluded by GET-only proof                                                                    |
| `style.css:1066`                  | `.signup-panel-tabs button.active`                                     | `background: #d9a628`           | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1068`                  | `.signup-panel-tabs button.active`                                     | `border-color: #d9a628`         | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1095`                  | `.pool-choice-grid button.active`                                      | `border-color: #d9a628`         | Live signup pool selector in App.tsx:1081; shell winning rules preserved, no raw-value retirement in 1a                                                      |
| `style.css:1096`                  | `.pool-choice-grid button.active`                                      | `box-shadow: #d9a628`           | Live signup pool selector in App.tsx:1081; shell winning rules preserved, no raw-value retirement in 1a                                                      |
| `style.css:1157`                  | `.roster-source-note`                                                  | `border-left: #d9a628`          | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1256`                  | `.roster-select-all input, .roster-account-select input`               | `accent-color: #d9a628`         | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1297`                  | `.member-nav-tabs button.active`                                       | `background: #d9a628`           | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1298`                  | `.member-nav-tabs button.active`                                       | `border-color: #d9a628`         | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1653`                  | `.compare-player.selected`                                             | `border-color: #d9a628`         | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1732`                  | `.compare-mobile-toggle button.active`                                 | `background: #d9a628`           | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `style.css:1733`                  | `.compare-mobile-toggle button.active`                                 | `border-color: #d9a628`         | Retained incumbent selector; no exact current TSX class reference found in bounded rg scan, may be legacy/overridden. No reachability claim or removal in 1a |
| `tokens.css:16`                   | `:root`                                                                | `--wu-focus: #f5d66e`           | Required root focus palette definition, ring-only; not a retired use                                                                                         |
| `weightTrial/WeightTrial.css:2`   | `.weight-trial-note`                                                   | `color: #f3ca56`                | Live WeightTrial note or pressed filter state; gold distance14.4 exceeds12                                                                                   |
| `weightTrial/WeightTrial.css:171` | `.weight-trial-filters button[aria-pressed="true"]`                    | `border-color: #f3ca56`         | Live WeightTrial note or pressed filter state; gold distance14.4 exceeds12                                                                                   |
| `weightTrial/WeightTrial.css:172` | `.weight-trial-filters button[aria-pressed="true"]`                    | `color: #f3ca56`                | Live WeightTrial note or pressed filter state; gold distance14.4 exceeds12                                                                                   |

## Isolated visual fixture scope

The initial private baseline capture retained 21 unavailable/error-state routes at360 before the legacy manage title mismatch stopped it. Those screenshots,503 DTO receipts and failed log remain under `pixels/smoke-before-360/`; they are error-state evidence, not representative populated pixel proof.

Owner decision 628 approved preserving the legacy manage case while asserting its actual Home redirect and Dashboard title in both phases. The three actual management indexes (applications-settings, fwa-settings, connections-settings) remain separate cases with populated section catalogs. The populated stage uses 59 fictional GET DTO routes, including Terra's separately built 28-route catalog copied by SHA256 `b63490b78e129aa65c74c92b110515ba16264cb996c88f03f355b6d7a32e8690`. Source schemas/fixtures and consistency choices accompany every route. Terra independently checked the 28-entry integration, exact query precedence, decoded clan tags and strict transport guards. Search/filter semantics beyond the captured initial query are not simulated; unlisted queries retain the owned fixture/error path.

Both private builds apply the same exact one-literal App brand CDN URL replacement to owned `/icons/wu-logo.png`. Before/after transform and asset hashes match. This is an approved fixture substitution, not production media fidelity evidence. No product source, CSP or egress allowlist changed. Other remote media in fixture DTOs is replaced identically with local sample images. Browser requests and fetch attempts remain GET-only/same-origin; API data comes only from static fake GETs or the verified owned MemoryMongo/temporary-SQLite dev fixture. No Mongo server, Discord or real provider is used. Browser time, locale, timezone, storage, reduced motion, viewport and media are fixed identically.

The capture completed all 312 screenshots with zero page errors, external requests, non-GET requests/fetch attempts and horizontal overflow. The 156 paired comparisons preserve exact geometry/title/focus and all 242 computed paint changes satisfy the approved limits. Strict text comparison found only the staff page’s generated local signup URL: the two verified five-digit localhost ports differ at all four widths (MemberSeasonSettings.tsx:11,27). Owner decision 631 approved exactly one body occurrence and the corresponding exact anchor leaf per staff capture to normalize the verified owned origin. The supplemental eight-record DOM proof verifies both owned listeners, relative href /signup, absolute own-origin/signup, empty search/hash and one visible occurrence at every width. Every other comparison guard remains. The corrected comparator passed all 156 pairs. Raw screenshots and per-view percentages remain unchanged; RGB mean/RMS/max magnitudes are reported separately. Populated preview after35943/before33025 is frozen to static fake GET/cache data, and the original error companions remain separately frozen. The verified owned backend stopped, its listener closed and its temporary SQLite was removed. Pixel acceptance must use the populated pair, with error-state coverage reported separately.

## Corrections and adversarial checks

| Finding                                                       | Correction and retained evidence                                                                                                                                                                                            |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Original independent counts differ from post-157              | Rebased base remeasured; old counts remain historical                                                                                                                                                                       |
| Private CSS equality hit equivalent whitespace/leading zero   | Setup canonicalization kept selector/value/role/distance guards; original checker/logs retained                                                                                                                             |
| First JS verifier included SourceFile text/format punctuation | 623 reviewed semantic serializer and full import interleaving; earlier failed sources/logs retained; one cleared run passed                                                                                                 |
| Full FE first failed cold-navigation raw-literal guard        | 626 approved local token guard plus exact root value, first global import and no other accent definition. All other test statements/assertions preserved after common formatter comparison; old 1813 PASS / 1 FAIL retained |
| 626 fs overload compile error                                 | 582 explicit utf8 only; no runtime/policy/assertion change; failed compile log/source retained                                                                                                                              |
| Optional626 preservation helper compared formatter trivia     | Same established Prettier normalized both inputs, then preserved assertions matched. Later recursive asset enumeration fixed EISDIR; both helper sources/logs retained                                                      |
| New isolated mutant first ran with wrong process cwd          | 605 corrected cwd only; false 22 PASS log retained and never counted as a killed mutant. Correct isolated runs each fail exactly the intended guard                                                                         |
| Fixture missing backend env                                   | 605 added private env binding; no product change; old source/log retained                                                                                                                                                   |
| Legacy manage fixture expected nonexistent active page        | 628 preserved case/title guard with actual Home identity; all three real management indexes remain                                                                                                                          |
| Hardcoded private fixture brand URL was external              | 628 identical owned-asset literal substitution in both builds; zero egress retained                                                                                                                                         |
| Final count helper tried deleted contrast path                | 605 enumerated actual CSS files, including new tokens and excluding deleted contrast; prior helper retained                                                                                                                 |

Impeccable retained exactly two file-scoped `side-tab=*` waivers through the official CLI: WeightTrial's three pre-existing semantic row markers and style.css's source-note/signup-guide side borders. They preserve the explicitly scoped incumbent rendering; they do not claim a universal design exemption or individual owner confirmation of each border. The config add/add rebase conflict was resolved from accepted task 157 and the style waiver reapplied by CLI; both entries are present. No broad ignore was added.

Read-only red-team scope: all CSS candidates were checked for semantic role, distance, excluded blue/alpha/moderation/Discord styles, and correct shell/standalone loading. Full tests protect shared interaction behavior. Product source adds no writes, mention handling, permissions, destinations, external text execution, storage owner, retries or concurrent-edit path. Live notification delivery, physical devices and screen-reader speech are not assessed by fake GET fixtures. Vite's existing mixed-import/large-chunk warnings remain.

## Remaining before READY

Obtain the separate bounded refutation of the 631 stage, preserve a clean historical checkpoint, and rebase onto exact accepted main 7447d8d1fe6c402a335f4f259cbc8787e3e303b7. All 109 baseline CSS sources and App are byte-equal between646 and744, but Participation/Bonus/Exports runtime changes require fresh full frontend/tsc/build and current-main pixel proof. The 39-case coverage ledger identifies 32 populated initial states plus blocked/initial/partial/redirect/unauthenticated/probe limits. Correct private fixture identity/arrival-enum/deadline coherence and add populated declaration, ready-announcement and selected-weight-editor companions while keeping error states. Complete final independent refutation, scoped formatting/diff checks, detach only this checkout's node_modules link, and record clean local SHA plus current cache-only preview. No source/UI work is claimed complete until those bounds are recorded.

The 631 proof bundle is `rebase-646/stage-631-manifest.json`, `format-631-contract.json`, and `pixels/populated628/{staff-link-631,pixel-comparison-631,coverage-ledger-646,retained-preview-frozen}.json`. The only product-source change after the 626 frontend validation is the approved CSS whitespace correction; the other 79 changed source files remain byte-equal to the pre-631 manifest. All old failed checker/source/log receipts remain historical.

Independent historical-stage refutation: Terra verified all 80 listed product-source hashes and all 312 raw screenshot hashes, the narrow 16-field origin adaptation, 237-declaration whitespace proof, retained raw/RGB metrics, and bounded semantic exclusions/retirement ledger. The 631 stage is clear for a historical checkpoint and rebase; Terra ran no tests/browser/live reads and this is not final7447 acceptance. Terra previously supplied the separate 28-route private management DTO draft; the product implementation remains Sol’s work.

Dependency-cache correction632: the strict pre-checkpoint guard found one extra shared top-level entry, empty `.cache/prettier`, strongly correlated with Sol’s626 Prettier CLI. The CLI resolves/creates its default cache directory even without --cache. No historical package-file hashes were in the183-name snapshot, so no unsupported content-identity claim is made;12 package versions match the lockfile and22 declared entrypoints predate the snapshot. The approved repair recorded fresh directory metadata, used non-recursive rmdir only on the verified empty prettier directory and parent cache directory, then required the exact original183 names before unlinking only this checkout’s dependency symlink. Shared package files were untouched. Every future Prettier CLI uses an owned private CACHE_DIR. Receipt: `dependency-repair-632.json`; earlier guard failure/provenance remain retained.

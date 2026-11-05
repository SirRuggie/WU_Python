# Color tokens 1b review

Task 168 starts from accepted main `82400fbfafad39d003c85d64085b1473f5778c54`. Sol built the candidate; separate reviewers checked scope, source, launchers and boundary calculations. The final frozen package receives independent review before READY. Release requires Shaka's ACCEPT. This document records local frontend validation; public release/runtime state was not assessed.

## Final scope

The final ledger has **209 mappings across 41 CSS files: 196 intended shifts above 12 sRGB units and 13 quiet snaps**. There are **106 raw holds**: 34 ambiguous, 25 selection, 17 data, 7 brand, 6 contrast and 17 proof. Entry 681 permits the 59 ambiguous/selection holds to remain unchanged for a later Impeccable audit. The measured data-hold count is 17; the older 19 included two records in the now-excluded moderation history stylesheet.

| Declaration role | Target |
| --- | --- |
| Page background | `--wu-bg` |
| Card, panel, sidebar, topbar | `--wu-surface` |
| Raised menu or popover | `--wu-surface-raised` |
| Input, secondary button, pill | `--wu-surface-soft` |
| Roster card | `--wu-card` |
| Default / quiet border | `--wu-border` / `--wu-border-subtle` |
| Body / secondary text | `--wu-text` / `--wu-text-muted` |
| Informational notice | `--wu-info-surface` / `--wu-info-border` / `--wu-info` |
| Focus ring | `--wu-focus` |

Alpha replacements retain their alpha through `color-mix`. Every occurrence's baseline file/line, selector, role, view, before/after RGBA and distance is in `.local/color168/mapping-ledger-v5-683.json` and the review HTML. The canonical root file and every `--wu-*` value remain unchanged. Entries 657–658 accept the existing slightly cool canonical ramp through its variables. Accent/gold, warning/success/danger and the raw holds covered by entry 621 remain held. Layout, typography, spacing, behavior and runtime TypeScript are unchanged.

Entry 659 distinguishes the actual signed-out CTA from generic primary styling. The winning `.welcome-screen .primary` stays brand blue: `#2055aa` fill, `#80b5ff` border, white ink. Base `.primary` retains gold `#d9a628` fill/border, `#211b10` ink and `#e7b73f` hover. Tests pin both honestly; Chromium asserts the winning CTA's exact RGB values.

## Exact contrast and proof holds

Entry 668 retains `--roster-card-text-muted:#e2e4eb`. The rejected replacement had a conservative full-success-gradient bound of 3.244:1; the original has 4.889:1. Mapping 303 became a contrast hold. The unused geometry diagnostic was never executed; no glyph-position waiver or token-value change was used.

Entries 682–683 restore **22 complete declarations to exact 82400 bytes**, including `var()` fallbacks. The 20 boundary IDs are 38, 156, 327, 2, 67, 104, 130, 160, 171, 175, 191, 195, 227, 234, 239, 244, 271, 287, 292 and 296. The 17 unobserved states are proof holds, not rendered passes. Background IDs 37 and 155 were restored jointly with the home-statistics and carousel-jump borders: border-only restoration would have worsened their inner contrast. Their paired surfaces remain at pre-1b colors until a later audit.

Fresh captures confirm identical before/after border RGBA and **all inner/outer paint samples** for the three observed held controls:

| Held control | Inner minimum before = after | Outer minimum before = after |
| --- | --- | --- |
| 38: home statistics | 1.61917285 | 1.50486151 |
| 156: carousel clan jump | 2.67462622 | 2.88925273 |
| 327: signup pool choices | 2.72651772 | 2.59483984 |

These inherited values are below 3:1. Preservation does not repair them or establish compliance. They remain in the later Impeccable audit alongside the 59. No 3:1 waiver, unobserved PASS or all-UI compliance claim is made.

All 47 original default-boundary declarations receive separate adjacent-paint analysis. Now 27 remain mapped: 22 sampled grouping/dialog/popover frames and 5 captured winning-border overrides (140, 145, 168, 270, 275). Those five captured winning paints/ratios are unchanged. The other 20 are source holds. Changed potentially essential native-control boundaries still require 3:1; missing mapped-state evidence fails. Frame classifications apply to sampled states, not every future state. `pixels-v6/all-observed-boundary-ratios.json` lists all observed bounds, including unchanged paints; missing states have no invented ratio.

## Exclusions and consumers

Five complete files equal 82400 bytes: `DiscordPreview.css`, `MemberActivityHistory.css`, `ModerationPreviewCard.css`, `ModerationSettings.css`, `ModerationWorkspace.css`. The written DiscordPreview and ModerationWorkspace CSS bundles also equal baseline bytes, checked by module mapping/content. The history file's 18 family occurrences are excluded; its 15 provisional mappings and 3 eligible holds were removed. `RosterImageCarousel.css` is also wholly baseline-equal after its two explicit holds; it is not counted as an additional excluded bundle.

The corrected runtime graph omits erased type imports. `MemberPicker` does not render in Moderation through the type-only `MemberOption` edge. Of shared runtime styles reachable from Moderation, only `ConfirmDialog.css` changes; `DiscordIdentity.css` and `ChannelCombobox.css` do not. The actual moderation-confirmation companion opens the shared dialog through a keyboard toggle and preserves the dirty guard. A real non-moderation member-picker companion covers that component separately.

## Current validation

| Check | Final 682/683 source result |
| --- | --- |
| Full frontend discovery | 1,845 tests / 299 files passed, 26.67s |
| Contrast and CTA files in that run | 43 contrast tests and 2 actual-App/base-CTA tests passed |
| TypeScript | Original strict/noEmit project; private incremental build-info; passed |
| Scoped Prettier / diff | Same 46 files and `git diff --check` passed |
| CSS contract | 209 mappings / 41 files / 6,586 declarations; 12 numeric fixtures and 22 exact-declaration guards passed |
| Private production build | 6.01s; 114 outputs; five source/two built exclusions byte-equal |
| Fixture binding | Fresh after-fixture: all 42 CSS outputs equal production bytes; before: 137 files verified, 42 CSS equal 82400 |
| Browser capture | 54 cases × 4 widths × 2 phases = 432 snapshots / 864 PNGs passed |
| Computed comparison | 216 pairs, 0 issues; 912 paint pairs / 375,383 computed changes |
| Changed text contrast | 4,070 observations passed 4.5:1; minimum bound 6.6024:1 |
| Changed SVG fill/stroke and mapped focus outlines | 5,087 observations passed 3:1; minimum bound 8.0684:1 |
| Boundary evidence | All 47 original IDs analyzed; 27 mapped-state checks/22 source holds passed; inherited low-contrast pairs preserved, not compliant |

The original 7 contrast pairs and guards remain, plus accent/info on all 10 surfaces and the full-success-glow regression. Prior test-file bytes precede the appended 668 regression. TypeScript uses the original config with no references/extends/composite, the same include set, strictness and noEmit. Original ignored build-info bytes, owner/mode/device/inode/size/mtime/ctime remain unchanged; new output is private.

Source and written output agree at **114 literals: 24 navy, 20 slate and 70 blue = 106 holds + 8 canonical definitions**, across 109 source stylesheets/42 written CSS outputs. Static variable expansion still has 8 ambiguous and 4 unresolved names. It is not a cascade/compositing proof or global resolved-zero claim. Captured changes are restricted to declared mapping pairs with exact alpha, text, geometry and focus checks.

## Browser evidence and report recovery

All 42 original cases and 12 actual-App companions remain at 320/360/390/1440, with 800px narrow and 1000px desktop heights. Populated declaration, ready announcement and WeightTrial samples remain separate from error states. The legacy `manage` case retains its Home redirect; all three management indexes remain separate. Every capture checks route/title, required DOM, overflow, page errors, focus, exact GET responses, unmatched DTOs, egress and non-GET attempts. Sending/publishing controls were not clicked.

The browser process completed capture, comparison and text/SVG/focus checks, then exited 1 because the boundary-summary printer used an old field name after writing its complete data. Source, error, data and owned-child cleanup are preserved. Versioned report recovery exited 0, recalculated all 47 records, and asserted exact equality with that completed output except source identity. It ran the previously unexecuted boundary gate/HTML generator. No frontend suite, production build or capture was repeated for this correction. Original capture PID/origins/requests were not rewritten.

All 1,296 raw PNG/JSON hashes remain unchanged. Raw pixel percentages/RGB magnitudes remain in the comparator; no pixel threshold hides them. Only 24 verified staff-signup own-origin text fields are normalized. Sol inspected final narrow signup/carousel controls and earlier declaration, WeightTrial and shared-dialog captures. Inherited skip-link/focus placement and WeightTrial dock geometry remain unchanged.

The final HTML is `.local/color168/pixels-v6/intended-changes-review-final.html`, **39,907,742 bytes**, SHA256 `da873f06f8227f8a901bc58767249410e39d215b0dccd609c7b4e49114ab9138`. It embeds 216 before/after 360×800/1440×1000 viewport PNGs plus one full-page hold reference, all 209 mappings, all 106 hold roles, all 4,070 text ratios and boundary ratios. All 217 image URLs exactly match the initial generated page.

The hold ledger distinguishes **39 observed selectors / 67 source-held or unobserved states**. Within the 59 ambiguous/selection holds, 16 have selector references and 43 remain unobserved. References prefer fully visible viewports; the below-viewport case embeds its full-page image. Selector matches do not establish every declaration won. POST-only states were not opened; no screenshot or rendered pass is fabricated.

## Retained preview and receipts

The final GET-only preview is owned PID **2130599**, before `http://127.0.0.1:45383`, after `http://127.0.0.1:42193`, retained after recovery success. Its index hashes, DTOs, CSP, source and assets equal the capture fixture; new PID/origins are separate receipts. Capture PID 2088236 was cleaned up after the report failure. Cleanup touches only the exact owned `Popen`, not arbitrary PIDs/groups.

Data are fictional GET DTOs without backend/Mongo/Discord/provider access. CSP blocks egress, forms and workers. Identical owned-logo/sample-media substitution is not production-media proof. Captures use the same frozen browser date; the retained interactive preview may use its browser's current date for relative times.

| Artifact under `.local/color168/` | SHA256 |
| --- | --- |
| `validation682/run/validation-proof.json` | `236dcd6bb57e3977d3bd8ac7e3f28ea827e45db95f772920b5873c0d61b94ec2` |
| `pixels-v6/postprocess-v2/run/proof.json` | `cd88b133db243f61c83ed0c9cd78c3779db28cd74a08e8914a4e14f59f16eee1` |
| `pixels-v6/pixel-comparison.json` | `da2ce9b87e789a4acaa5560dd4bf6d3fb33cd427e23c0e55971baacdace86540` |
| `pixels-v6/changed-text-and-ui-contrast-v2.json` | `6c6321b584d244121bbc44808c488a0edc848658a46f896636bc233a43118b35` |
| `pixels-v6/boundary-contrast-proof-v2.json` | `f2f9441ce8cafd5e811cf8fe4878645c0ff161c937d7d7e55eb0f18449f414f7` |
| `pixels-v6/all-observed-boundary-ratios.json` | `439ae15211cb04a5d9adb92b976b5d78ed20c6b655b41b7dccbfa428a4cd8ce2` |

## Limits and follow-ups

Static Impeccable detection ran once on the then-changed 44 stylesheets: 11 warnings, no new suppression. Current 683 triage confirms the same flagged values: ten are exact 82400 state/notice stripes, transparent tab underlines or progress-width transition; the eleventh changes only the existing 3px Welcome notice border to its authorized info color. Geometry remains. Removing those markers exceeds this color-only batch. Existing file-scoped 1a/157 waivers remain unchanged.

The >500kB chunk warning remains; no warning-free claim is made. Historical bundled TSconfig loading likely touched shared `.vite-temp` despite cacheDir (code-path inference, not an OS audit). Final runs use explicit native loading/private caches. Dependency evidence is exact 183 top names and `.vite-temp` names/mtime/ctime at stage boundaries, not whole-tree byte immutability. No shared cleanup or deliberate package/cache mutation was made in response. Only the owned dependency link is removed before final freeze; its target is retained.

Evidence covers these fictional states, not every hidden disclosure, hover, screen reader, browser, occlusion or unchanged contrast pair. Unsupported image paint fails rather than invents contrast; gradient-stop/opacity bounds remain conservative. No notification mock proves delivery. No authorization, API, storage, policy, retry, schedule or notification runtime code changed.

Prior failed sources/logs/proofs remain historical: pre-write exclusion matching, numeric normalization, misplaced config, opaque color serialization, moderation-history scope, UsageLinks/provenance setup, native-switch pointer interception, rejected metadata contrast, HOST UID representation, phase-index receipt, owned-child cleanup, copied c02 path, unused case-transform assertion and renamed report field. Data/status/count/threshold assertions were retained. The withdrawn wrong-worktree scout map is not evidence; the glyph diagnostic was never run.

Gold retirement and the raw holds covered by entry 621 remain separate work in [the 1a review](color-tokens-1a-review.md). The 59 ambiguous/selection holds and inherited control-boundary issues remain for a later owner-directed Impeccable audit. No new different-valued alias or forced distance exception was introduced.

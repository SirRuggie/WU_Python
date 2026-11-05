# Color tokens1b review

Task168 maps eligible navy, slate and non-informational blue declarations to the accepted1a tokens by role. The exact baseline is82400fbfafad39d003c85d64085b1473f5778c54. Sol built this candidate; Terra provided separate bounded scope, source and launcher reviews. Final independent evidence review is required before READY. Release remains gated on Shaka acceptance. This workflow records local frontend validation; public runtime/release state was not assessed.

## Scope and decisions

The final ledger contains231 mappings across44 CSS files:215 intended shifts above12 sRGB units and16 quiet snaps. There are84 raw holds:34 ambiguous,25 selection,17 data,7 brand and1 contrast. Entry681 permits the59 ambiguous/selection holds to ship unchanged for a later Impeccable audit. The17 data holds are the measured post-moderation-exclusion total; the earlier19 included two records in the now-excluded history stylesheet. No count was invented to match an older estimate.

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

Alpha replacements use `color-mix` with the original alpha. Source selectors, baseline file/line, view, before/after RGBA, distance and role are recorded individually in `.local/color168/mapping-ledger-v3-668.json`. The self-contained HTML includes the complete231-row list, classifies every shift, and embeds all4146 actual changed-text contrast observations.

The canonical root token file and every `--wu-*` value remain unchanged. Entries657–658 explicitly accept the slightly cool1a neutral ramp when used through the canonical variables. The accent/gold family, warning, success, danger and the raw holds covered by entry 621 remain held. No layout, typography, spacing or application behavior changed.

Entry659 resolves the original CTA wording conflict: the actual winning signed-out `.welcome-screen .primary` remains brand blue (`#2055aa` fill, `#80b5ff` border, white ink). Separately, the generic base `.primary` retains gold `#d9a628` fill/border, `#211b10` ink and `#e7b73f` hover. Both are pinned honestly by the new tests; Chromium checks the actual winning CTA's exact RGB values.

Entry668 retains `--roster-card-text-muted:#e2e4eb` unchanged. The rejected neutral replacement had a conservative green success-gradient bound of3.244:1; the retained original has4.889:1. Mapping303 was removed and became a contrast hold. No glyph-position waiver, canonical-token change or threshold relaxation was used. The unused geometry-diagnostic proposal was never executed.

## Exclusions and actual consumers

Five complete source files equal82400 bytes: `DiscordPreview.css`, `MemberActivityHistory.css`, `ModerationPreviewCard.css`, `ModerationSettings.css` and `ModerationWorkspace.css`. The actual written DiscordPreview and ModerationWorkspace CSS bundles also equal their baseline bytes, using module mapping and content rather than guessing hash names.

The history file's18 family occurrences are excluded: its15 provisional mappings were restored and its3 holds removed from the eligible ledger. The initial filename-only inventory and pre-restoration proof are retained as historical evidence.

The corrected runtime import graph omits erased type imports. `MemberPicker` is not rendered in Moderation through its type-only `MemberOption` edge. Of shared runtime styles reachable from Moderation, only `ConfirmDialog.css` changes; `DiscordIdentity.css` and `ChannelCombobox.css` do not. The actual `moderation-confirmation` companion shows the dialog after a keyboard toggle and preserves the unsaved-change guard. The actual non-moderation `member-picker` companion covers that component separately.

## Current validation

The post668 chain ran once after its reviewed setup corrections. The source was frozen throughout; no unchanged full-suite or production-build repeat followed its success.

| Check | Current result |
| --- | --- |
| Full frontend discovery |1845 tests /299 files passed,27.69s |
| Contrast and CTA test files within that run |43 contrast tests plus2 actual-App/base-CTA tests passed |
| TypeScript |Original strict/noEmit single project passed; private incremental build-info |
| Scoped Prettier / diff |46 files and `git diff --check` passed |
| Ordered CSS contract |231 mappings /44 CSS /6906 declarations;12 numeric-equivalence fixtures passed |
| Private production build |5.99s;114 written outputs; five source/two built exclusions byte-equal |
| Fresh after-fixture binding |All42 CSS outputs equal the current production build's written CSS bytes |
| Baseline reuse |All137 retained fixture files verified; all42 CSS outputs equal82400 production bytes |
| Browser capture |54 cases ×4 widths ×2 phases =432 snapshots /864 PNGs passed |
| Element/paint comparison |216 pairs,0 issues;938 paint pairs /376131 computed changes |
| Changed text contrast |4146 observations passed4.5:1; minimum measured bound6.6024:1 |
| Changed essential UI contrast |5147 observations passed3:1; minimum measured bound8.0684:1 |

The contrast tests preserve the original7 pairs and existing guards, cover accent and info on all10 surface tokens, and add the full-success-glow regression. All prior test-file bytes remain before the appended668 regression. The TypeScript invocation uses the unchanged original `tsconfig.json`, no references/extends/composite, the same include set, strictness and noEmit. The original ignored `tsconfig.tsbuildinfo` bytes, ownership, mode, device/inode, size and modification/change times remained unchanged; the new output is private.

The current literal inventory agrees between109 source stylesheets and42 written CSS outputs:22 navy +17 slate +53 blue =92 occurrences, consisting of84 holds and8 accepted canonical definitions. Static variable expansion reports8 ambiguous and4 unresolved names. It is not a selector/media cascade or compositing proof and does not establish a global resolved-zero claim. Actual captured computed changes are constrained to the declared mapping pairs, with exact alpha, text, geometry and focus comparisons.

Capture widths are320/360/390/1440; heights are800px for narrow and1000px for desktop. All42 original cases and12 actual-App companions remain. Populated declaration, ready announcement and WeightTrial editor samples are distinct from retained unavailable/error samples. The legacy `manage` case retains its real Home redirect, and the three actual management index views remain separate cases. Every capture checks title/route identity, required DOM, zero page overflow, page errors, focus, exact GET responses, unmatched DTOs, external requests and non-GET attempts. No publishing/sending control was clicked.

The comparator retains all1296 raw PNG/JSON files unchanged.212 pairs have changed pixels; the maximum changed-pixel fraction is51.5987% (`bases`,390px), with mean absolute RGB deltas4.5976/3.5470/3.5016 and maximum channel delta20 for that pair. These raw percentages are not hidden behind a pass threshold. Only24 verified staff-signup own-origin text fields are normalized; original screenshots and RGB magnitudes remain intact.

Sol visually inspected the narrow declaration success cards, before/after narrow WeightTrial editor and wide moderation confirmation. The captured skip-link/focus placement and WeightTrial dock geometry are inherited and unchanged. This is not a redesign or an assertion that every pre-existing interaction or contrast pair is perfect.

## Review artifacts and retained preview

The final review is `.local/color168/pixels-v4/intended-changes-review-with-contrast.html` (39,654,568 bytes, SHA256 `aa24dad4269b41829faa7d3c53e7e6b78de2fffdae4c59f1e159b3631351ab64`). It embeds216 actual before/after viewport PNGs at360×800 and1440×1000 across all54 cases, the215 intended shifts,16 snaps, all84 hold roles and the4146 measured text ratios. The original chain-generated HTML and its manifest remain preserved.

`hold-observation-ledger.json` distinguishes34 observed holds from50 source-held/unobserved holds. Among the59 ambiguous/selection holds,16 have actual selector screenshot references and43 remain explicitly unobserved. No screenshot is fabricated; POST-only states were not opened under entry666. Each hold retains its role, file/line/selector and honest observation limitation. These deferred holds are unchanged source values, not completed role conversions.

The retained GET-only static fixture is owned PID2027004, baseline `http://127.0.0.1:45493` and candidate `http://127.0.0.1:40115`. Its HTML, CSS, media, JS and fictional GET DTOs are private assets; no backend, Mongo, Discord or provider was used. CSP blocks external connections, forms and workers. The owned logo/sample-media substitution is identical in both phases and does not prove production-media fidelity. Successful preview retention is intentional; failure cleanup targets only the exact `Popen` created by the runner.

Primary current receipts:

| Artifact under `.local/color168/` | SHA256 |
| --- | --- |
| `validation668/run/validation-proof.json` | `de3c6d1f33fa4f413c1bba3b411fc3dc71e7a4eb5fbc240fbb57d53debba7e0e` |
| `pixels-v4/run/proof.json` | `5073aefcf96bd8ac9cc463403096d8b9a9ee28ef6bd952037fb908b8020758da` |
| `pixels-v4/pixel-comparison.json` | `82b6f73b9969f580f4799c28756e8f6dfc01228997c44fe0861d20a08cceaf84` |
| `pixels-v4/changed-text-and-ui-contrast-v2.json` | `930b816d2c1edc6dd1f2a72d3fa5372560943b01e62dfa85142f91218465e6f2` |
| `pixels-v4/hold-observation-ledger.json` | `6d07ab52ed98cffe5d99789b03336aaf04721bd857870165f4ebcc1c680bdec2` |

## Design scan and scope limits

The final static Impeccable scan ran once on the44 changed stylesheets. It reports11 warnings, retained without a new suppression. Ten flagged declaration values exactly equal82400: existing state/notice stripes, transparent3px tab underlines and the existing progress-width transition. The eleventh is `.welcome-destination`'s existing3px notice border changing only its authorized info color. `.local/color168/impeccable-final-triage.json` records exact selector/property/before/after evidence. Removing those borders or changing the transition would violate this batch's color-only/no-layout scope. Existing1a/157 file-scoped waivers remain unchanged.

The build retains the >500kB chunk warning. Historical full tests can emit localhost connection diagnostics; no warning-free claim is made. The earlier bundled TSconfig loader likely wrote/unlinked shared `.vite-temp` files despite private cacheDir; this is code-path inference, not an OS audit. The final validation uses explicit native loading and private caches. Shared-dependency evidence is bounded to the exact183 top names plus `.vite-temp` names/mtime/ctime at stage boundaries, not whole-tree byte immutability. No cleanup or deliberate package/cache mutation was performed in response. Only this worktree's dependency symlink was removed after verifying the exact183 names; the target was retained.

Current evidence covers the declared fictional states and captured elements, not every hidden disclosure, hover, screen reader, browser, occlusion or unchanged contrast pair. The conservative contrast compositor fails unsupported image paint rather than inventing a background; gradient-stop extremes and opacity are retained. No mocked notification result is delivery evidence. No API, authorization, storage, policy, retry, schedule or notification runtime code changed.

## Preserved corrections and follow-ups

All failed sources, traces and outputs remain private and are not represented as current passes: the pre-write broad token-file matcher; formatter leading-zero equivalence; misplaced private Vitest config; happy-dom opaque color serialization; moderation-history scope correction; missing UsageLinks DTO; missing provenance build-script copy; custom-switch pointer interception; the rejected120-observation metadata contrast mapping; HOST root UID namespace mismatch; phase-index receipt mismatch; owned-listener failure cleanup review; and the copied guard's incorrect bundle-relative c02 path. The eventual setup corrections retained every assertion, status, data record, count and contrast threshold. The final corrected chains and old receipts are separately versioned and sealed.

The old gold retirement and the raw holds covered by entry 621 remain separate work, documented in [the1a review](color-tokens-1a-review.md). The59 ambiguous/selection holds remain for a later owner-directed Impeccable audit. No new alias with a different value, forced distance exception or scope expansion was introduced.

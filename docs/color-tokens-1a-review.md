# Color tokens 1a — independent foundation checkpoint

Task 165 started from `a1a8b9377d25799b43181c8eb25c20edf689396a`, verified
independently through GitHub's main-branch API before creating
`codex/color-tokens-165`. The existing checkouts and local main were unchanged.
This checkpoint covers only the independent work allowed before task 157 merges.
It is not final READY, pixel-parity acceptance, or a release artifact. Task 165's
release remains held for owner authorization.

## Implemented scope

- Added the 26 specified global colors in `src/tokens.css`, imported first by
  `main.tsx`; no dependency or theme switch was added.
- Changed the specified 17 roster colors to aliases. The other roster tokens
  retain their existing values; roster gold intentionally resolves to `#f4cd64`.
- Extended the existing contrast test to resolve aliases, preserving its seven
  pairs and adding the 13 requested global pairs. Two rollback guards protect
  the approved roster gold and the winning shell primary fill/ink.
- Folded the 28 winning contrast rules into the end of `style.css`, retaining
  their selectors, specificity, order, media queries, light-panel text fill,
  `color-scheme: only light`, forced-colors behavior, and navy pool rules. Later
  workflow/accessibility imports keep their existing order. Deleted the separate
  stylesheet and its three imports. The two standalone preview entries that
  imported that deleted stylesheet now import global tokens first.
- Applied 101 reviewed shell color bindings across style, sidebar, staff
  navigation, accessibility, and workflow controls. Each has a selector,
  property, old value, target token, distance, and any explicit exception in the
  final applied ledger. The four distance exceptions are the three specified
  global focus-ring declarations and the specified success-notice border.
- Updated the requested token documentation, decisions, and later-work list.

All 13 product paths changed by task 157 remain byte-identical to this branch's
base during this stage. Moderation and DiscordPreview styles remain unchanged.
No backend, authorization, destination, notification, storage, text, or interaction
behavior was changed. Prettier expanded previously compressed source; it did not
change the non-color CSS contract.

## Counts and audit method

Counts cover every CSS file under `web/cwl/src`, including comments and token
definitions. The regex counts 3-, 4-, 6-, and 8-digit hex literals; distinct values
are case-normalized. Lowercasing and expanding shorthand do not reduce the base's
738 distinct values. The prompt's 705 estimate is not reproduced by this method.
The exact substring `var(--` is counted separately from forms with whitespace.

| Measure                     | Exact base | Independent checkpoint |
| --------------------------- | ---------: | ---------------------: |
| CSS files                   |        109 |                    109 |
| Hex uses, all four lengths  |      1,400 |                  1,303 |
| Distinct literal hex values |        738 |                    715 |
| Eligible 3/6-digit uses     |      1,315 |                  1,218 |
| Distinct 3/6-digit values   |        699 |                    676 |
| Literal `var(--` uses       |        555 |                    673 |
| Files with no `var()`       |         58 |                     52 |
| 4-digit / 8-digit uses      |    29 / 56 |                29 / 56 |

These are intermediate counts. The broad mechanical sweep and counts against
the eventual post-157 integration base remain pending. No replacement target is
inferred from the prompt's approximate 550 estimate.

The first candidate ledger chose nearest distance among property-compatible
tokens. Selector review rejected inappropriate meanings: decorative gradients,
count fills, the error notice, and the generic channel border retain their
original values. Warning notices/acknowledgements use warning surface; pressed
filters use accent soft. Original candidate ledgers remain immutable historical
evidence; `applied-independent-bindings.json` is the reconciled final ledger, and
`independent-source-proof.json` asserts exact agreement with the actual CSS.

## Evidence retained privately

All paths below are under this worktree's `.local/color165/`.

| Check                             | Result / evidence                                                                                                          |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Contrast and rollback guards      | 22 passed: `contrast-independent-reviewed.log`                                                                             |
| TypeScript                        | exit 0: `tsc-independent.log`; later changes were CSS/docs only                                                            |
| Final stage private Vite build    | exit 0, 6.13s: `build-independent-reviewed.log`; output `build-independent-reviewed/`                                      |
| Prettier, scoped to changed files | exit 0: `prettier-check-independent.log`                                                                                   |
| Contrast fold AST proof           | 28 rules preserve order/selectors/declarations/media: `fold-proof.json`                                                    |
| Whole scoped CSS contract         | 1,595 declarations preserve selectors/order/non-color values; exactly 101 ledger bindings: `independent-source-proof.json` |
| Old roster gold mutation          | isolated actual mutant killed by the intended gold assertion, 1 failed / 21 passed: `mutation-proof.json`                  |
| Missing primary fold mutation     | isolated actual mutant killed by the intended primary assertion, 1 failed / 21 passed: same proof, separate source/log     |
| Source exclusions                 | exact task157, moderation, DiscordPreview checks: `independent-exclusions.json`                                            |
| Counts / per-item mappings        | `baseline-counts.json`, `counts-independent.json`, `applied-independent-bindings.json`                                     |

Existing Vite mixed-import and large-chunk warnings remain. These checks do not
claim physical-device, screen-reader speech, live notification, public asset, or
whole-dashboard pixel validation. This workflow performed no deployment or
production write; the public deployment state was not assessed.

## Preservation decisions and corrections

The signed-out primary is live outside `.shell`: `App.tsx` renders Continue with
Discord in `.center-screen.welcome-screen .login-card` as an anchor with
`button primary`. Therefore the old global `.primary` fill/border `#d9a628`, ink
`#211b10`, and hover `#e7b73f` remain intact pending review of the retirement versus
distance-12 rule. The shell's folded contrast primary stays the approved
`#f4cd64` / `#241b08`. The explicit dead sidebar-current and tabs-active base
rules were removed. Other live out-of-threshold old gold values remain held;
there is no blanket recoloring exception.

The AST fixture initially compared `.1em` and Prettier's equivalent `0.1em`
literally. The original checker and failed log were retained. Canonicalizing the
leading zero preserved the same strict selector, property, value, media, and
color-distance assertions; the unchanged semantic contract then passed. No
product behavior or assertion was relaxed to obtain a pass.

The design hook identified two pre-existing side borders in `style.css`:
`.roster-source-note` (3px `#d9a628`) and the folded `.shell .signup-guide` (5px
`#b57900`). Both border styles are unchanged from `a1a8b937`; the entire former
source-note block is unchanged, while the guide's aliases resolve to its exact
old fill/ink. The guide retains light-panel and forced-colors behavior.

The official Impeccable CLI persisted only a `side-tab = *` exception scoped to
`web/cwl/src/style.css`, with an agent-triage reason citing task165's explicit
render-preservation requirement and exact base evidence. This is a sanctioned
preservation exception for 1a; it does not claim that decorative side borders
are universally appropriate or individually confirmed by the owner. Raw report,
CLI success log, and configuration are retained. No CSS border was changed for
the hook, and no other rule/file suppression was added. Task157's separate weight
row waiver must be preserved when the configuration is integrated after its merge.

## Remaining before final review

Wait for task157's merge, then integrate that exact main revision and preserve its
features and design waiver. Complete the strictly bounded CSS sweep, including
task157's divider/danger styles, and reconcile all counts against the actual
integrated branch base. Standalone style-only fixtures need global-token bootstrap
before they can establish production-equivalent reference visuals.

Run the required full frontend, final TypeScript/build, four-width layouts, and
all-dashboard-view before/after screenshots at 360/1440 using fictional GET-only
data, with measured pixel percentages. Stop and report any unexpected visible
difference. An independent refuter, final red-team review, retained preview, and
reviewable provenance remain necessary. This checkpoint does not mark those
steps complete.

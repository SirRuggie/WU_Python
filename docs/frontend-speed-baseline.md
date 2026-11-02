# Frontend speed: baseline only

This is prompt 123's measurement phase before 118–122. Application source/runtime
are unchanged. Visibility timers, request coalescing, image attributes and any
chunk change remain future implementation work after those dependencies/review.
No deployment, production timing/API call or live notification occurred.

## Profile and fixture

Source 343fbf043c5e0f9b6df8f45a4f5f4776f9b5c45a; frontend tree
5bf16b2889a8311705404ab9d7a214bc1e4c6926. Copied verified clean3f assets and an
instrumented source-unchanged build reproduce index-DODYu6Hv.js SHA256
70ae891fce6403a70c8cbcee48863357a4a281615c93c9d461ac02762e009b1d.

Actual Google Chrome 156.0.8078.79, headless desktop engine,390×844 CSS px, DPR 1,
mobile viewport/touch, CDP 4× CPU slowdown,150 ms request latency,1.6 Mbps down and
750 kbps up. This is simulated, not a calibrated physical phone/mobile network.
Root held other builds/full backend suites/benchmarks; ordinary services/capture
could still run on the shared 16-thread host. No production performance inferred.

Three cold direct-navigation runs per page in three six-page rounds. Each used a
fresh Chrome process/context, cleared/disabled HTTP cache and blocked service
workers. Only the existing tour preference was seeded dismissed
(wu-member-tour-v1, skips 3 / dismissed true), defining a returning user. Authenticated
cases seeded a fixture session before timing; sign-in stayed signed out. Backend
fixtures/caches stayed persistent/warm. Four fictional accounts use owned
SQLite/Mongo 27168. Existing audit 124 was untouched; external connections were
blocked, with local avatars and unavailable external icons/fonts.

Cases: signed-out entry, open-member Home/Signup, two saved signups, four published
assignment rows and owner Build roster with 125 saved accounts. Existing initial
roster rendering is 50 cards, not a 125-card DOM test. Owner-specific optional code
also loads; these figures are not generalized to every staff account.

## Three-run medians

| Page | LCP s | Tap EventTiming ms | Painted proxy ms | Nav CLS | Completed bytes | Starts | After |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Sign-in | 3.788 | 24 | 938.3 | 0.0173 | 572,639 | 6 | Pending |
| Home | 4.340 | 56 | 58.7 | 0.0069 | 623,027 | 17 | Pending |
| Sign up | 3.880 | 40 | 43.7 | 0.0899 | 592,473 | 10 | Pending |
| My signups | 4.328 | 40 | 44.3 | 0.0924 | 577,910 | 11 | Pending |
| Assignments | 4.304 | 40 | 42.6 | 0.0000 | 592,692 | 13 | Pending |
| Build roster 125 | 7.876 | 232 | 242.6 | 0.0293 | 1,367,647 | 46 | Pending |

LCP is the last buffered largest-contentful-paint before first tap, after page
readiness plus 4s settling. Navigation CLS is the maximum 1s-gap/5s session sum,
excluding recent-input shifts, during that window; not lifetime/field CLS.
Single-tap EventTiming is the maximum recorded event duration with a positive
interaction ID for one trusted tap: **not field INP or a CrUX distribution**.

The painted-state proxy runs from pointerdown through two animation frames after
Navigation opens. Sign-in instead runs fixture login through painted Home, so
its 938 ms includes auth/network/route loading; it is not 938 ms frontend INP.
Its actual single-tap EventTiming is 24 ms. All local LCP medians miss 2.5s. Member
menu taps meet 200 ms; Build's 232 ms EventTiming / 243 ms painted proxy miss in all
three runs. Navigation CLS medians meet 0.1, with Signup/Saved near the limit.
No after result, production regression or improvement is claimed.

Transfer bytes sum completed same-origin CDP encodedDataLength, including HTTP
headers, not payload-only/billing/packet totals. Each case has a favicon start
without a completion event; its unknown bytes are not invented. Critical APIs
and assets completed. Counts are request starts. Blocked external/data resources
are not completed wire transfers. Navigation/interaction are separate, excluding
sign-in's subsequent Home fetches from its landing totals.

| Page | LCP ms, runs1/2/3 | Tap EventTiming ms, runs1/2/3 | CLS, runs1/2/3 |
| --- | --- | --- | --- |
| Sign-in | 3800 / 3788 / 3736 | 24 / 24 / 24 | 0.0173 / 0.0173 / 0.0173 |
| Home | 4356 / 4340 / 4324 | 48 / 56 / 56 | 0.0069 / 0.0069 / 0.0069 |
| Sign up | 3880 / 3884 / 3860 | 40 / 40 / 40 | 0.0899 / 0.0899 / 0.0899 |
| My signups | 4328 / 4356 / 4288 | 48 / 40 / 40 | 0.0924 / 0.0924 / 0.0924 |
| Assignments | 4304 / 4276 / 4312 | 48 / 40 / 40 | 0.0000 / 0.0000 / 0.0000 |
| Build roster 125 | 7872 / 7876 / 7940 | 232 / 232 / 240 | 0.0293 / 0.0293 / 0.0293 |

## What is in the entry

The actual body is 503246 bytes. Chrome observes no Content-Encoding and 503723
completed transfer bytes, with no disk/SW hit. Offline gzip gives 160918 bytes,
only an estimate: that compressed representation was not served. Production
compression was not probed; do not present fixture bytes as production costs.

Exact-hash Rollup graph: 380 entry modules. Largest pre-minification renderedLength
groups: React DOM 561402; React Aria 449080; application 243800; React Aria Components 49999;
React Stately 44036; Lucide 44924. These units are **not additive minified/wire byte
attribution**. App.tsx 104186; MemberTour 17045; SidebarNavigation 14001;
SavedSignups 11318. AccountMenu.tsx is the sole eager application import of
react-aria-components, retaining that menu stack even while signed out.

There are already 29 lazy route imports. Member traces do not fetch the major
RosterWorkspace/Strikes/Exports staff screens. Home's roster-DO4Xp3gX.js contains
shared helpers, not evidence of loading the staff editor. Eager staff-only
fragments unused by these member views are small: DashboardStorageStatus 1008,
StaffDetailsHost 1649 and its bridge 1326 pre-minification units. Shared
DashboardHistory retains strikeActivityFilters 12535 via filter-key configuration.
Most 503 kB must not be described as unused staff screens.

## Repeated paths observed

Middle run: Home GET/seasons twice; My signups GET/linked-accounts?background=1
twice. Build GET/seasons twice, GET/seasons/1/roster?background=1 twice (about 148 kB
each), and GET/seasons/1/publication twice (about 101 kB each). Sign-in/Signup/
Assignments show no repeated navigation path in that sample. These are startup
windows, not long-duration focus/visibility/timer traces. Identical paths alone
do not prove identical responses or redundant work; metadata refresh may
legitimately change later data. Verify before implementing coalescing.

## Concrete next proposal; no chunk implementation

First review/land 118–122, then repeat this exact returning-user profile. If LCP
still misses, first experiment with a local lazy/Suspense AccountMenu boundary
at authenticated-only render sites, keeping its ReactAria stack off signed-out
entry without replacing accessible controls. Preserve visible fallback behavior;
test keyboard opening, Escape, focus return and slow/failing chunks. No byte or
member-LCP saving is promised: signed-in pages may still need the same bytes.
A larger auth-bootstrap/App split needs review, not an unsolicited baseline edit.

Separately inspect Build's menu rerender cost and repeated roster/publication
reads. Any fix stays frontend-only, adds no polling and preserves live run/send
catch-up. Timer visibility/coalescing, image sizing/lazy attributes, full frontend/
TypeScript/build, layouts and adversarial review remain required later. This is
not feature READY/release approval; after results are pending.

## Evidence and limits

Retained under .local/frontend-speed-baseline/.local/: baseline-results.json,
baseline-summary.json, baseline-network-analysis.json, module-graph.json,
module-composition.json, source-proof.json, measurement-manifest.json,
MEASUREMENT-PLAN.md and scripts/logs. Six-page unthrottled smoke and all 18 valid
runs have no page errors; timing observers report no API errors. Source-unchanged
instrumented build passed 8.85s and reproduced the entry hash. No full feature
suite rerun was needed for measurement-only source; no application edits.

Initial Chrome launch hit a Unix socket path limit before any measurement; a
short /tmp/wu-p123-tmp symlink to workspace temp corrected it. Initial first-visit
campaign stopped when automatic onboarding blocked the Home tap. That one sign-in
result/log remains a separate first-visit diagnostic. All18 comparison runs
restarted under the declared preference, not an outlier exclusion. Earlier smoke
used an obsolete Saved selector, corrected before timing. Real OAuth, users,
hardware, production compression/latency and long-term INP/CLS remain unmeasured.
All older previews/Claude dependencies were preserved.

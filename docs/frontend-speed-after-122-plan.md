# Frontend speed after accepted 122: baseline and proposed work

This is a local baseline and a proposal for review, not an implementation or
release. Exact source ae89a10449fc880885c0b446019a97247f232ea2; the instrumented
build reproduces accepted entry index-B6heIuwp.js, SHA256
3873351b21b2732bf6350b6ee07cf8a439525d4e8b6d3144a09866111e0a7550.
The entry is now 514,774 bytes; the prompt's 503 kB description is historical.

## Profile and results

Three runs per page, all 18 retained without retries/exclusions. Installed Chrome
156 headless, 390×844 CSS pixels, DPR1, mobile/touch, CDP CPU slowdown4×,
150ms latency, 1.6Mbps download/750kbps upload. Each run starts a fresh Chrome
process/context, disables/clears HTTP cache and blocks service workers. Only the
existing dismissed-tour preference is preseeded: this measures a returning user,
not first-visit onboarding. Fixture session seeding precedes timed navigation.
Four newly owned SQLite/Mongo fixtures use fake providers and block external
backend connections. Their backend remains warm. Staff has 125 saved accounts;
members have three linked accounts, two saved signups, or four published accounts.
These are local lab numbers, not production, CrUX, real OAuth or a physical phone.
Root held other agent builds/tests during the measured window; ordinary services
and scheduled jobs were not changed. Host CPU/backup overlap was not independently
sampled, so the shared-host limitation remains.

LCP is the last buffered entry before the tap, after readiness plus four seconds.
CLS is the maximum valid session-window sum excluding recent input. The common
menu tap proxy measures trusted pointerdown through two animation frames after
the menu becomes visible. Sign-in instead measures fixture login to painted Home;
its asynchronous network work makes it a different interaction. EventTiming was
retained, but these few lab interactions are not field INP.

| Page | Median LCP ms | Tap proxy ms | CLS | Issued requests | Wire bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sign-in | 3888 | 964.6 | .01648 | 6 | 597318 |
| Home | 4460 | 59.1 | .00278 | 17 | 648257 |
| Sign up | 4044 | 43.9 | .05024 | 10 | 617152 |
| My signups | 4356 | 42.4 | .15685 | 11 | 602589 |
| My clan assignments | 4660 | 55.3 | .00887 | 13 | 618519 |
| Build roster125 | 7908 | 230.8 | .04309 | 46 | 1381710 |

All six miss LCP≤2500ms; Build and fixture sign-in miss the 200ms proxy target;
My signups misses CLS≤.1. The initial Build view renders its existing first50
cards, not all125 simultaneously. There were zero page errors or runner failures.
Expected signed-out auth401 occurred three times; owner-only prank/state404 also
occurred three times in this fixture. Favicon requests had no loadingFinished
record by capture and contribute no encoded-byte count. Counts are issued
same-origin requests; bytes sum completed CDP encodedDataLength including headers.
External images/fonts/connections were blocked consistently; the runner did not
count every externally aborted request, so these totals are not total attempted
internet requests and do not prove remote-image performance.

The local server sent no Content-Encoding for entry/CSS. Entry transfer was
515251bytes including headers, approximately3.14s under this network profile.
Offline gzip estimate164744bytes is not observed wire compression. No production
compression or backend policy change is proposed in this frontend-only batch.

## Entry composition and repeated requests

The exact-build graph contains396 entry modules. Pre-minification rendered lengths
are diagnostic attribution, not additive minified/transfer bytes: react-dom561402,
react-aria449080, application272358, react-aria-components49999,
lucide-react45277, react-stately44036, React20318. Largest application modules are
App105154, MemberTour17108, SidebarNavigation13991, SavedSignups13305,
strikeActivityFilters12535 and dashboardHistory6921. Members receive this entry,
including staff navigation/filter helpers and eagerly imported RosterMenu's Aria
menu dependency even when that page never opens such a menu. Most substantial
staff destinations (Roster, Members, Strikes, Server management, etc.) already have
lazy boundaries; they are not all bundled into the entry. Build loads its roster
and shared chunks plus the owner-only prank chunk; that owner path is not evidence
that ordinary members load staff destination chunks.

All three traces per page show the same repeated paths:

- Home: /api/cwl/seasons twice. App loads seasons; Home's refresh load also requests
  seasons. They are separate consumers, not an observed focus/timer race.
- My signups: linked-accounts?background=1 twice. The first returns a smaller
  pending snapshot, followed by an updated snapshot. Preserve freshness semantics;
  identical path does not establish a redundant response.
- Build: seasons, roster?background=1 and publication each twice. Roster's existing
  metadata-completion polling explains a second roster request; publication is
  also fetched through existing publication-awareness paths. Do not blindly remove
  them or change bounded metadata polling in this batch.
- Sign-in, Signup and Assignments: no repeated same-origin navigation path in the
  captured window. This short trace does not establish absence of later timer races.

## Proposed implementation order — awaits review

1. Add one small visibility-aware refresh scheduler used by the five named pages.
   Hidden tabs clear their intervals; visible return coalesces focus/visibility/
   timer signals into one check, retaining existing in-flight guards, stale-source
   protection and error handling. No new intervals or global data/authority cache.
   Existing visible send/restore jobs keep their current2.5/3s status updates;
   hidden tabs need no UI polling because delivery runs on the backend, and return
   performs one immediate catch-up. Declaration's countdown pauses while hidden,
   recomputes from Date.now on return, and does not extend its deadline. Home30s
   and Assignments30s retain their visible cadence. Check shell's existing60s
   access/seasons listeners for the same burst, preserving permission refresh.
2. Add regression tests for hidden/no request, visible immediate catch-up, three
   simultaneous signals→one request, pending request suppression, unmount/stale
   scope, and running send/restore success/failure/uncertain behavior. Trace Home's
   duplicate seasons consumers separately; share an in-flight request only where
   identity/parameters and freshness intent are identical, never a durable cache.
3. Images: AST audit finds17 sites missing at least one width/height/loading
   attribute. Supply correct existing slot dimensions or known source aspect ratio
   for badges, previews, cards and tour art; retain responsive CSS. Lazy-load
   offscreen gallery/rows only. Keep the brand and currently visible primary/modal
   image eager; do not lazily delay LCP content. Unknown source dimensions require
   explicit metadata/slot review, not fabricated natural sizes. Add geometry tests.
4. Since LCP misses, split by demand, not arbitrary vendor files: move the existing
   signup/SavedSignups/tour UI behind page/activation boundaries; put staff-only
   season-picker/management helpers behind staff destinations. Remove RosterMenu's
   eager import from the shell where only unopened staff controls need it, retaining
   the same approved RosterMenu/Aria behavior when opened. Preserve the eager
   request owner in StaffDetailsHost and its event registration semantics. Keep
   authentication, route ownership and confirmation authority in existing owners.
   Plain manualChunks would not prevent eager Aria preload and is insufficient.
   First verify graph/network that member Home no longer transfers unused staff
   helpers; do not promise a precise byte saving before that build.
5. Investigate My signups' .15685 CLS with layout-shift source attribution and a
   stable same-size loading region before making a focused fix. Current capture
   lacks attribution, so no image/loading cause is claimed. Profile Build's230.8ms
   menu proxy before changing rendering; no backend/polling/virtualization redesign.

After approval: important timer/burst/permission/cancel regressions first, same
18-run profile before/after (no selective reruns), full frontend/typecheck/build,
320/360/390/1440 layout and keyboard/confirmation review, running status catches up
on return, network/API/permission equivalence and genuine regressions/mutants.
Release remains held for Ruggie; no runtime edits, production reads, new polling,
backend change, send or deployment occurred in this baseline task.

## Evidence and cleanup

Evidence lives in .local/frontend-speed-after-122/.local: baseline-results.json,
baseline-summary.json, baseline-network-analysis.json, module-graph.json,
module-composition.json, images-audit.json, measurement plan and raw logs. Six-page
unthrottled smoke passed. Initial module-report build failed missing worktree
package resolution; a temporary owned dependency link fixed resolution and the
exact-entry build passed. No measured run failed. New fixturePID4191575 and owned
Mongo4191577 were gracefully stopped after measurement; data/evidence retained.
All prior121/122 review previews and assets were left unchanged.

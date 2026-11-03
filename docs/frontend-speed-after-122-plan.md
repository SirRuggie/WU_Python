# Frontend speed: local results after accepted 122

The five member pages meet the local compressed cold-load LCP target after this
batch. My signups' CLS improves from .15685 to .01399. Build remains a staff-only
miss: LCP 5.144 s and menu proxy 203.7 ms, versus targets 2.5 s / 200 ms. No entry split,
whole-list memoization, virtualization or polling redesign was added. Release is
held for review; these are local measurements, not production or CrUX results.

## Same-profile before and after

Each table uses three runs/page, 18 runs total, all retained with no retries or
exclusions. Before source is accepted ae89a104; after runtime source is 85c8570b.
Documentation-only followups do not change that runtime. All six pages remain in
the table, including Assignments' narrow margin under 2.5 s.

| Page | LCP before→after ms | Tap proxy before→after ms | CLS before→after |
| --- | ---: | ---: | ---: |
| Sign-in | 1692→1688 | 757.0→912.8 | .01648→.01648 |
| Home | 2168→2208 | 58.1→57.9 | .00278→.00278 |
| Sign up | 1808→1832 | 44.8→42.8 | .05024→.05024 |
| My signups | 2140→2152 | 40.9→42.9 | .15685→.01399 |
| My clan assignments | 2424→2440 | 57.4→56.7 | .00887→.00887 |
| Build roster125 | 5092→5144 | 227.1→203.7 | .04309→.04309 |

Sign-in's proxy includes fixture login and painting Home, not just a button
handler or real Discord OAuth. It still misses 200 ms and is a different action
from the other five pages' menu opening. Build's 203.7 ms is a near miss, not PASS;
there is no further rendering proposal or silent extra campaign. The source
profile before the approved formatter fix attributed 29.3 ms self time to repeated
Intl.NumberFormat construction and 57.6 ms to the mobile drawer's layout-reading
ancestor; profile/injected-test overhead prevents treating those as exact causal
subtractions. The measured menu median decreases 23.4 ms, without a promise that
all rendering cost is isolated. Build's remaining 46 requests / 752522 wire bytes and
5.144s LCP are retained honestly for review.

### Environment and transport

Installed Chrome 156 headless;390×844 CSS pixels, DPR 1,mobile/touch; CDP CPU 4×,
150ms latency, 1.6 Mbps download / 750 kbps upload. Fresh browser/context per run,
disabled/cleared HTTP cache, service workers blocked. Only the existing dismissed
member-tour preference is preseeded: returning-user pages, not first-visit tour.
Fixture session seeding precedes timed navigation. Four fresh, isolated SQLite/
owned-Mongo fixtures provide three linked accounts, two saved signups, four
published accounts or 125 saved staff accounts. Build naturally renders its first 50
cards. Backend caches stay warm; fake providers and a network guard prevent
external backend/Discord access. External browser resources are blocked as before.

Static assets alone use test-server brotli, with identical quality 11 compression
before/after; dynamic JSON stays unchanged/uncompressed. Actual Chrome responses
confirm Content-Encoding br on all 18 entry loads. Before entry 514774 decoded bytes,
140268body/140690wirebytes; after140782body/141204wirebytes. These are different
assets from Shaka's production observation, not a production transport replica.
Returning production members may reuse its immutable cached entry; this lab
intentionally keeps cold disabled cache. No production request/change was made.

LCP is the last buffered entry before the tap after readiness+4s. CLS uses maximum
session-window sums excluding recent input. The trusted-pointerdown→two animation
frames after visible menu proxy approximates painted state, not hardware latency
or field INP. EventTiming is retained without claiming a field percentile.

Root held other agent builds/tests during each measured window. Ordinary services
and scheduled backups/monitoring were left untouched. Partial /proc samples within
the campaign tails show aggregate host CPU busy 10.41% before / 10.30% after; load1
ranges 1.19–2.0 and .5–1.52. Sampling starts after campaign launch and does not
identify every job overlap or establish full CPU comparability. Samples after
campaign completion are retained but excluded from those tail summaries.

## What changed

- Five named pages use one visibility-aware scheduler. Hidden tabs remove their
  periodic timers; visible return catches up. A 32 ms settling window coalesces
  neighboring focus/visibility/interval tasks. Existing 30 s / 2.5 s / 3 s cadences,
  page-owned errors, stale-source protection and in-flight guards remain.
  Declaration's countdown recomputes from wall-clock time on return. Backend sends
  continue independently; visible send/restore status keeps updating, hidden UI
  catches up without replaying a write. No new polling/data/authority cache.
- SavedSignupStatus renders the same real summary component while assignments and
  links load. Unknown counts/actions are not invented; pending labels say checking.
  The settled all-signed-up case retains a truthful account-summary section.
  Closed-season policy, visible unavailable states and401 / 403 clearing remain.
  Only real heading/paragraph/action slots have responsive minimum block sizes;
  content grows without clipping or fixed total heights. The duplicate checking
  paragraph is removed when the component owns its loading state.
- Shaka 500's narrow Build fix reuses one fixed-options Intl.NumberFormat. Null,
  nonfinite,zero,.05/.95 rounding,negative and large outputs are equivalent.
- Known artwork dimensions are verified from resized WebP files; existing layout
  artAspect values stay unchanged. Current tour/walkthrough imagery remains eager;
  offscreen badges/rows/pages use lazy loading. Known 40 px badges, square BaseBank
  and gallery presentation slots receive dimensions without altering object-fit.
  Roster PNG dimensions derive from the existing renderer and already-returned
  counts: 1000 px wide,390+70×rows high, 15 rows/page. Malformed/absent pages do not get
  invented dimensions. Arbitrary variable-aspect uploads/Discord media lacking
  metadata remain a limitation; no guessed natural ratios or new metadata API.
  Current main/modal imagery is not delayed solely to satisfy a lazy flag.

### Loading geometry attribution

At 390 px, baseline account-list y moved555.015625→661.21875→777.421875 as assignments
and accounts settled. Candidate states all have summary 314 px/list y 804.421875.
The larger settled account-heading slot is intentional. Twelve 320/1440 cases cover
remaining/all-signed-up/closed/403/404 and text-inflation stress with no overflow,
clipping,writes or page errors. Text inflation is not calibrated browser zoom.
Narrow/wide screenshots were visually reviewed.

The controlled trace retains one large recent-input/style/layout event whose
source is unproven; it is not discarded or described as zero total shifts. No
post-phase non-recent-input shift is recorded, and actual DOM positions stay
identical through all three states. The separate natural18-run campaign confirms
CLS.01399. The fixture banner's earlier  .01391 contribution is not a production
CLS claim. Failures/errors may still change geometry to make information visible.

## Entry contents and repeated requests

The historical raw-server baseline was retained, but it overstated member load
relative to compression: raw entry transfer515251bytes/~3.14s. It is not pooled
with the compressed table. Exact before-entry graph has 396 modules. Diagnostic
pre-minification rendered lengths, not additive wire sizes: react-dom 561402,
react-aria 449080,application 272358,react-aria-components 49999,lucide 45277,
react-stately 44036. App,MemberTour,SavedSignups,navigation/filter helpers and eager
RosterMenu/Aria are in the shell; most substantial staff destinations already have
lazy boundaries. Members do not load all staff destination chunks. Per 499, member
entry splitting is not authorized or implemented.

After issued-request/complete-wire-byte medians: sign-in 6/157345,Home 18/177523,
Signup 10/177179,My signups 11/162616,Assignments 14/167313,Build 46/752522. Home and
Assignments each add one shared visibleRefresh JS chunk, not another API read.
Home still requests seasons twice through separate App/Home consumers. My signups
still has a pending then complete linked-account read. Build retains metadata
completion's second roster/publication reads. These are not blindly removed or
called duplicate identical responses. No request paths repeat on sign-in,Signup
or Assignments within the measured navigation window; this does not establish
absence of every later race.

All18 runs in each compressed campaign have zero page errors/runner failures.
Expected signed-out auth401 and fixture owner prank/state404 occur three times
per campaign. Favicon can lack loadingFinished at capture and contributes no
completed bytes. Totals count same-origin issued requests/CDP completed encoded
bytes including headers. Every external abort was not instrumented, so these are
not counts of all attempted internet requests or proof of remote-image latency.

## Validation, limits and provenance

1699 frontend tests / 289 files,typecheck/build pass; 52 four-width cases at
320/360/390/1440 with 26/65/125 accounts; 30 narrow/wide page/dialog cases; 12 targeted
status cases; two separately served review-preview smokes. Layout/served checks
record zero non-GET requests after fixture login and zero page errors. Semantic
API AST proof retains 60 calls in 22 owners against ae89a104. Nine scheduler tests
and an actual active-send panel regression prove hidden suspension, one catch-up,
visible completion and no sends. Six genuine assertion-killed mutants cover hidden
timers,burst coalescing,listener cleanup,pending publication,unknown account state
and repeated formatter construction, with exact source restoration.

Initial failures, the listener mutant survivor, invalid textual mutant attempt
and native-constructor spy TypeError remain in local logs; only assertion kills
are counted. Test waits were updated for 32 ms without dropping error/403/401 or
other behavior assertions. No full backend suite was needed for this frontend-only
batch. Authorization,URLs,selection,mention/external rendering,write/cancel scope,
partial/unknown data and stale responses were reviewed; storage/provider owners
remain unchanged. Mocked fixtures do not prove live Discord delivery.

Runtime source 85c8570b builds index-Brk8WtDH.js SHA256
4bbd003088a0fde2cd2add1c78a4a91c29e77425194bc11bbc5f2802af7bf2d6.
New separate staff/member previews are 32817/44381; old121/122 previews stay intact.
All measurement/profile Mongo/servers/Chrome were stopped after preserving data;
only those two SQLite review previews remain. Evidence is workspace-local under
.local/frontend-speed-after-122/.local: raw/compressed/after-results and summaries,
network traces,module graph,CPU profiles,geometry screenshots/status matrix,
mutant logs and ready evidence. Stacked on accepted 192/ae89; later main integration
must preserve accepted 185's filler queue and stop on behavior conflicts. No merge,
production read/write,notification,backend change or activation occurred.

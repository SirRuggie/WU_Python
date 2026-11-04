# Participation status review (160)

Development candidate on `codex/participation-status-160`, based on main
`9552757eae8ebb2c7bd5a779f058aab26cc75f97`. Frozen full backend and exact owned
boot are pending. Task159 is accepted separately and its release remains held.
No production writes, forced capture jobs, notifications or service changes
were performed for 160.

## Diagnosis and count scopes

One approved diagnostic (570), November4 10:12:15–10:12:32UTC, read the current
canonical dashboard checkpoint into RAM-only SQLite with query-only enabled.
It called the normal official provider's public group method once for Funnies,
W.U.Lazy.126, W.U.Lazy.128 and healthy W.U.Lazy.124, and the public war method
once for each of44 unique round war tags. No outer retry cycle, storage writer,
lease, index or job ran. Existing provider transport policy was unchanged.
Only numeric and clan/war metadata was retained, without member rows. The
private instrument was compiled and checked with a synthetic fixture first.

All four groups reported WAR and date-shaped month2026-11-02. The affected
three had round1 ENDED, round2 WAR, round3 PREPARATION; the healthy control had
round1 WAR, round2 PREPARATION. No current provider error, state regression or
month mismatch was reproduced. This does not prove historical provider replies.

Current signups:170 (147Lazy/23Main), with37stale,125partial,7no_data,
1unassigned. Saved history:162 (141Lazy/21Main), with37stale/125partial.
Eight current-only signups (6Lazy/2Main), zero history-only, explain the counts.
The page now labels the two sets and counts warnings only within the current
pool/search/clan filter, before pagination.

The capture intentionally skips final wars when fetch coverage includes all
current clans and allowance evidence was captured. Skipped wars are not added
to fresh_wars, so the unchanged aggregator marks accounts stale even when their
final round is safely retained and their active round refreshed. That code path
explains the three-clan correlation. The retained diagnostic did not include
the exact skip-coverage predicate; this is accepted code attribution, not a
second measurement or proof of each past capture. Do not repeat the diagnostic.

## Behavior and ownership

`utils/cwl_participation_status.py` owns the single effective display rule.
`cwl_web/participation_display.py` reads existing season group/war/fetch/allowance
metadata as one batch, without per-account queries or writes. Fresh group and
active-war evidence plus sealed final observations establish display health.
Only confirmed failed checks identify failed clans; an old check is distinct.
Unchecked signups cannot borrow another account's success or failure. Ended
incomplete and month mismatch remain distinct. A fresh ended-to-active fetch
regression is named even when the prior final side is retained.

`participation_sync.py` logs each unique failure with clan/name, round, war tag,
reason and available HTTP status/error class, and returns the same metadata in
`failures`. Unknown-side failures retain candidate group/round context. JSON
escapes external newlines; provider text and member rows are not logged. Existing
reason codes, fetch budgets, retries, capture schedule and storage values stay
unchanged. No schema or durable receipt fields were added.

Outgoing response copies receive `display_status` only after internal policy,
fingerprints and receipts are calculated. Each response path gets its own copy;
shared current/historical input objects cannot overwrite one another. Other
months cannot borrow the selected month's freshness. Raw source fields remain
available for every existing decision.

| Consumer | Final treatment |
| --- | --- |
| Participation capture/header/refresh | Neutral progress with round and scoped updated count; one named-failure warning; separately labelled current/history counts; completed check notice makes no blanket health claim |
| Participation row/details/reset hint | Shared effective label/warning; numeric values, corrections, revisions, reset/save behavior unchanged |
| Bonus medals capture warning | Shared summary restricted to selected pool/clan |
| BonusCandidateReview / bonusRaffle | Existing policy exclusions, staff flags, cooldowns and draw gates retained; no independent capture status rule added |
| Bonus/manual preview account copies | Effective status; generated warning status words rewritten only on the outgoing copy; warning count, acknowledgement and staff-reason gates retained |
| Export preview / CSV | Shared status/warning text, including prefixed account-export fields; same basis, filters, rows, columns, nulling and numbers |
| `_view`, `_preview`, `_fingerprint`, raffle eligibility | Original raw policy/fingerprint inputs unchanged |
| RaffleStore snapshots/manual candidates/receipts | Original persisted fields and values unchanged; outgoing copies only |

### End-of-CWL decision check (578/579)

An actual isolated sync saves rounds1–6 ended/sealed and round7 live. When round7
and the group end, only round7 is fetched again. Results become7attacks/21stars,
source_complete=true, raw source_status=stale. A third capture skips all seven
and retains completeness. General raffle eligibility(account,4) and Lazy
eligibility both return None (eligible) on both checks. No false raffle
exclusion was found. The separate manual `_preview` still requires a staff
reason when raw status is not complete, even with completeness true. That
behavior is deliberately unchanged pending Ruggie's decision, per579.

## Evidence and regression scope

- Final HTTP boundary suite:129 passed in43.52s, including sync, pure status,
  SQLite adapter, Bonus, Lazy API, Exports and raffle. Existing cached-ended
  stale/timestamp/attack/star contracts remain. Tests pin input identity/deep
  equality, output copy separation, raw policy/fingerprint preservation, no
  adapter writes, selected-clan ownership, initial missing groups, state
  regression, ended incomplete and month mismatch.
- Audit against955: all8 capture SQL write-call ASTs are identical. Store schema,
  raffle eligibility/store and allowance files are byte-identical. Bonus
  `_view`, `_preview`, `_fingerprint` function ASTs are identical. Private proof:
  `.local/status160/policy-write-invariants-160.json`.
- Full frontend:1778 passed in297files/25.99s. This branch starts from main955;
  task159's frontend count belongs to a different tree. TypeScript passed.
  Private Vite build completed in6.00s; entry `index-C4QPJEwE.js`, SHA256
  `a238c5e419ea995c91d129760f5c5d6bab04024e6ece9b01ec01b02b0724860a`.
- Required unchanged war checker:213 backend passed/1skipped24.74s;35 frontend
  passed in8files; tsc, diff check and private temporary build5.89s passed.
- Eight isolated Participation layouts at360/1440: progress, failed, ended and
  mismatch; zero document overflow/page errors; GET-only fake API, CSP and
  blocked external origins. Main stays healthy when only Lazy clans failed;
  Lazy names Alpha/Beta/Gamma and37affected accounts; healthy search removes
  that warning. Twenty visible paged rows; keyboard focus reachable. Inspected
  360progress and1440failed, then corrected fixture UTF-8 metadata matching the
  actual app. Proof: `.local/status160/layout-160c/proof.json`.

Retained sample preview: `http://127.0.0.1:40669/?phase=progress`, detached
PID839434. Static GET/HEAD-only component/sample170/fake browser API; no backend,
Mongo or provider connection. Executable/cwd and local200/CSP/index hash were
verified after the launcher exited. Fixture index SHA256
`5d2cc422dfdde31797a7e0c936b891987dbd85278f2344b5016be3fd0abf57ca`.
It is a separate sample bundle, not the deployable dashboard artifact.

## Corrections and preserved failures

| Review / location | Before → after; retained protections |
| --- | --- |
|580, participation_display.py / test_participation_display.py | deepcopy preserved a shared row alias, letting historical status overwrite current → independent dict/list copy per path; all strict assertions retained, plus input identity/deep equality and distinct output identity |
|581, private frontend launcher | cwd web/cwl with duplicated web/cwl paths → root-based link/test setup and separate compiler cwd/gates; original failure log retained; no product/assertion change |
|582, participation.ts:76 / bonusRaffle.ts:48 | full ParticipationSync required → only optional status/cycle actually read; then optional matching DTO type fields resolve weak-type TS2559; type-only, no casts/any/runtime/assertion change |
|583, ParticipationWaiting.test.tsx:53/112 | raw-only fixture and required obsolete incomplete phrase for normal progress → outgoing display metadata and exact neutral progress/named-failure count/mismatch checks; all GET/navigation/month/waiting protections retained |
|566, private layout160→160b | wait on first DOM row (hidden Lazy row in Main) → visible-list-item wait; initialize Main per page; no product/data/output assertion changed |
|566, private layout160b→160c | missing UTF-8 fixture metadata → HTML/HTTP UTF-8 matching actual app; same assertions and data |

Original failed logs, source hashes, fixture bundles and stop summaries remain
under `.local/status160`. No failed run is counted as a pass. Prior development
notes are retained privately in `review-draft-before-final-audit.md`.

## End-to-end review and remaining gates

Authorization remains at each original editor-required HTTP boundary. No new
route or Discord destination was introduced. Clan names render as React text
and journal JSON; CSV formula/identity escaping remains intact. Existing
concurrent-revision, stale-preview, draw/approval/replay, cancellation and
identity-loss protections remain; response metadata is excluded from internal
fingerprints, policy and saved receipts. No notification path or retry changed.
Mocked fixtures are not live Discord delivery evidence.

Remaining before READY: clean source freeze, one full backend on that exact
HEAD with reviewed startup network guard and empty production connections,
new exact-artifact owned boot, final provenance and remote-head verification.
No deployment, merge, tag or production service action is part of these checks.

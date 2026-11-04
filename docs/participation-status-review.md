# Participation status review (160 / rework164)

DRAFT: current work on `codex/participation-status-160` is not READY. PR199 began
on main955. PR198 is live as `strikes-activity-2` at maina1a8b937. Rework checkpoint
1323099f was merged locally with that exact released tree, without conflicts,
at54c7d745b662588ec4e9cfbdb4d5b261857320f4. No root pull/reset or production
change was involved. Final checks must bind this combined candidate before its
full backend freeze. The root checkout and production assets remain outside this development
work. No production writes, forced jobs, notifications or service changes were
performed for160/164. Earlier160 full/boot receipts are historical, not164 passes.

## Diagnosis and populations

The one approved570 diagnostic read a canonical checkpoint into RAM-only,
query-only SQLite, then called public official providers for four groups and44
unique wars once per key. Existing transport policy stayed unchanged; no outer
retry, writer, job, index or persisted member rows. Current170 signups were
147Lazy/23Main, versus162 saved-history rows (141Lazy/21Main); eight current-only,
zero history-only. Three affected clans had an ended first round and active
second round; healthy control's first round was active. No current API error,
regression or month mismatch was reproduced. Skipping sealed final fetches
without adding them to fresh_wars explains the raw stale classification in code.
The exact skip-coverage predicate was not retained; this is code attribution,
not proof of each historical reply. Do not repeat the production diagnostic.

The list count describes the current displayed pool and filters. The capture
box does not repeat that count or saved-history totals. History remains a
separate read-only disclosure/export scope. Warning counts use the displayed
pool/search/clan scope before pagination, never hidden accounts.

## Display and storage boundaries

One pure `utils/cwl_participation_status.py` helper interprets existing facts.
The HTTP read adapter batches existing group, war, fetch and allowance evidence;
it never writes or performs per-account queries. Fresh group/active-war evidence
and usable sealed final observations mean normal progress. Unknown/new accounts
cannot borrow success or failure. Actual failed checks name affected clans;
old checks, ended incomplete and mismatch remain distinct.

The selected sync month's mismatch outranks a saved raw stale/never account.
Historical paths do not borrow the current month. Real participation DTOs own
`source_complete`; weight-only `source_status` records are excluded from both
participation evidence and decoration. Accounts exports decorate only their
prefixed participation fields. Weight status, row basis, filters, columns,
roster-mismatch nulling and numeric values remain unchanged. Waiting CSV text is
retained when the display helper has no additional warning.

Decorate independent outgoing copies after internal calculations, fingerprints,
snapshots and receipts. Keep raw status and completeness fields. Shared object
aliases across current/history paths cannot overwrite one another.

Failures are JSON journal events and sync-result metadata, with clan/round/war,
reason and available HTTP/error class. Provider text/member rows stay out;
external newlines are escaped. Real sides come from existing final allowance
evidence or the fetched war body before normalization. A group round alone
cannot identify a failed war's sides: without identity evidence the journal
honestly says Unknown clans with a null clan tag, retaining war/round/reason.
It must not blame the hosting clan whose group merely listed another war.
No extra provider call, retry, capture schedule, schema or capture write change.

| Staff consumer | Treatment |
| --- | --- |
| Participation capture/refresh | Neutral progress, round and scoped updated count; one named-failure or mismatch warning; no duplicate population line |
| Participation row | Short shared label; full failure explanation remains in Details |
| Participation details/reset | Shared label/warning; corrections, values, revision checks and reset/save behavior retained |
| Bonus and raffle staff views | Same display interpretation, with existing pool/clan scope; eligibility changes only as owner588 below |
| Manual bonus preview | Raw policy/fingerprint first, outgoing display copies afterward |
| Export preview/CSV | Same display status for participation only; weight status and waiting explanations preserved |
| Raffle snapshots/manual candidates/receipts | Persisted fields and receipt semantics retained |

## Owner decision588: CWL completion before bonuses

Complete source results need no reason solely because raw status is stale.
Incomplete source results are a hard block, including saved draft selections,
filled reasons and warning acknowledgement. The message names the incomplete
player and points to Check Clash now where refreshing is useful. Other threshold,
cooldown, hosting and already-confirmed rules retain their existing behavior.

Lazy raffle previously allowed a reason to override incomplete results; it now
blocks them unconditionally. Keep the original flag list plus incomplete reason
visible together; complete accounts keep their old override behavior. General
raffle already hard-blocked incomplete results and is unchanged. Fingerprint,
revision, snapshot and receipt mechanisms are unchanged.

The actual seven-ended-round fixture still proves source_complete=true with raw
stale and7attacks/21stars after six sealed rounds plus one freshly ended round,
and on subsequent sealed reuse. Both raffle paths remain eligible with complete
results. This explicitly supersedes the earlier579 pending-policy note.

## Current evidence and final freeze

- Whole affected boundary/SeasonTrial run:149 passed49.19s. Includes auth,
  raw cached-ended status/timestamps, failures, alias/input invariants, Bonus,
  Lazy API, Exports, raffle and real old-selected-draft confirm rejection.
- All8 capture SQL write-call ASTs equal955. Store, raffle storage and allowance
  owner files remain byte-identical; bonus_view/fingerprint and general raffle
  eligibility ASTs unchanged. Approved588 preview/Lazy policy differences are
  explicit exceptions, not claimed old-policy equality.
- Frontend1780 passed297files29.16s; final TypeScript passed. Private build6.10s:
  index-3bWmt-hb.js, SHA256
  b8fedff7839f1a3dd902eb133e893c65757c32805ccc55ce1867ff25e234fec7.
  This is the pre-integration build; the combined checks below supersede it.
- Eight360/1440 sample layouts: progress, failed, ended, mismatch with saved
  attack/star values. No document overflow or page errors; fake GET-only API,
  external origins blocked, keyboard focus reachable. Healthy Main/search does
  not show Lazy's37-account/three-clan failure. No duplicate capture count or
  full inline row explanation. Inspected360progress and1440mismatch.
- New retained component-only preview: http://127.0.0.1:32955/?phase=progress,
  PID954588, index SHA256
  e571b0918127817de503bfd32a3760e1f4ec899b0053d71776dfa6aa98f489b3.
  Separate fixture bundle, not a deployable/full-backend artifact. Static
  GET/HEAD+CSP/sample170/fake browser API, no backend/Mongo/provider connection.
  Executable/cwd and200/CSP/hash verified after separate tool calls. Older
  previews/assets and failed outputs remain preserved.

These checks do not establish live Discord delivery, real-phone operation or a
complete assistive-technology/contrast audit. The optional Impeccable context
engine was unavailable (not installed/cache write denied); no retry/install.
Repository interaction rules and incumbent UI guided the read-only review.
No PRODUCT.md or DESIGN.md was invented.

## Corrections retained, with before/after contracts

| Review / fixture | Before → after; protection retained |
| --- | --- |
|580 alias regression | deepcopy preserved current/history alias → independent copies, strict input identity/deep equality and distinct output identity |
|581/582 launcher/types | wrong package cwd and overly broad sync type → correct cwd/paths and optional fields actually read; no casts/any or runtime workaround |
|583 waiting copy | obsolete normal-progress amber phrase → neutral progress/named real failures/mismatch, retaining GET/auth/navigation/month/waiting checks |
|588/591 owner decision | incomplete-with-reason can_confirm=true → hard block even acknowledgement/old selection; complete raw stale no participation-only reason; below threshold still requires reason/ack |
|592 source binding | complete fixture with null token ignored → actual working-account token, same totals/status/completeness; all assertions retained |
|594 reason priority | early hard return hid Left the family → original flags plus incomplete reason, unconditional incomplete block; complete override control retained |
|592 manual candidate fixture | no complete source yet expected2 eligible → first assert incomplete exclusion, seed bound complete source, then original2 eligible/no signup mutation/duplicate409/removal checks |
|164 count copy | duplicate capture population positive → current list count positive plus capture duplicate negative; GET/month/navigation/waiting checks retained |
|566/592 layout selector | full-row count included37 closed Details warnings → inline status-area count; same zero-inline-explanation assertion, full Details retained; new output prefix |
|597 integration audit | expected test.ts typo → actual test.tsx, preserving exact four-file membership and all159 byte assertions |
|598 disk temp environment | combined frontend EDQUOT → identical run with private disk TMPDIR,1785 passed; failed log retained |
|602 localhost test environment | sandbox denied socket creation → unchanged guarded host-scope war check; no product or assertion change |
|566 earlier layout setup | hidden first row/absent UTF-8 metadata → visible-row wait/Main initialization and real-app UTF-8; same data/behavior checks |

All failed sources/logs and private receipts remain under `.local/status160`;
none is counted as a passing run. Whole-run failures99/100 and the old unbound
fixture failure are preserved beside their reviewed corrections.


Combined main integration was audited under597: all31 released159 runtime/test
files match maina1a8 byte for byte, and the only four frontend imports are the
StrikeActivityRoster and useActivityIdentityRefresh source/test pairs. All43
changed Python files compiled. Participation layout sources remain unchanged.
Combined frontend:1785 passed297files26.02s; TypeScript passed; private build
6.13s, index-x4Dw9kB7.js, SHA256 02ee2c7c0ecff7b777effaf516dda812848fed82644481629149eb7944cd029c.
The first combined run hit EDQUOT in /tmp (232files passed,65failed); the598
reviewed rerun changed only TMPDIR to private disk and passed. Both logs remain.
Archive599 is a separate maintenance job and does not change this feature.

## Remaining gates

Released159 is integrated in this feature worktree. Its changed frontend files
are disjoint from the Participation layouts; their component fixture remains
valid. The combined full frontend, TypeScript and private build passed. Complete
clean freeze, ONE full backend
with the startup network guard/empty connections/private temp directory, NEW
exact-artifact owned boot and cleanup, final evidence/remote verification/READY.
No source edits/exports/boot/other suite during full architecture collection.
160 release remains separate from159 and requires its own review acceptance.


Owner593 documentation follow-through: after integration supplied the real
`docs/unused-code.md`, only sectionA's pending Cards decision was replaced with
the canonical ARCHIVED, keep paragraph. Card code stays disabled and present;
no runtime file was removed or reworded. All other backlog entries are unchanged.

Required unchanged war validation under602 passed:213 backend tests,1 skip
in25.82s;35 frontend tests across8files; TypeScript, diff check and private
Vite build passed. Failed sandbox run131passed/7failed is retained separately.

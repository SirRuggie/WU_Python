# Announcement in-place roster post editor (139)

Reviewed implementation. Release is held for owner preview; no production API,
provider call, post edit, send, deletion or campaign update was performed.

The sent pool card opens a separate text/link-button editor. Preview reads the
actual recorded bot-owned post through the existing publishing service and shows
that snapshot beside the proposed result. It changes neither the Discord post
nor saved campaign settings. The private owned scratch draft is excluded from
the normal resumable Manage editor and expires with a narrowly scoped TTL.

Update post names the observed channel and uses the same publishing service:
recorded destination, bot author check, both fingerprint checks, short edit lease,
NO_MENTIONS, in-place edit and audit receipt. The dashboard cannot submit a target
message ID or fingerprint. Observed galleries/attachments and the visible role
header are retained even when the saved template's media/roles have since changed.
Unsupported layouts fail without creating or deleting a post. A deleted result
has no update, fresh edit or replacement action in this feature.

After a confirmed edit, a cycle-document CAS saves only this pool's title/body/
link buttons. The review checkbox “Also use for future months” defaults ticked;
when checked, the same write records only this pool's recurring roster copy.
It does not replace a full recurring campaign or rewrite another message, role,
destination, activation state or original send ledger. The publishing service
appends its existing post-updated audit receipt without replacing the original
sent receipt/occurrence. A failed saved-copy CAS after a
confirmed external edit reports the edit plus an explicit saved-copy warning;
it never reports a failed edit or automatically repeats it.

Recurring field overlays use one canonical whole-template cutoff and
revision-bound local field markers. A field save preserves inherited other-pool
and general recurring settings without rewriting unrelated raw fields. Ordinary
whole-template saves invalidate the marker even at an equal timestamp. A cycle
with only delivery receipts retains its previously inherited sequence settings
when its first dotted roster-copy override is written. A normal older draft may
not overwrite a newer cross-cycle recurring pool copy.

The worker reuses the existing ten-second shared side-effect lane. A bounded,
partial-indexed one-workflow query is empty when idle; no scheduler poll is added.
Its protocol/readiness travels on the existing heartbeat with its own expiry, so
an old bot heartbeat cannot silently advertise the new editor. Private draft and
workflow TTL indexes have exact feature namespaces; ordinary drafts are excluded.
Interrupted edits become uncertain after restart and are never returned to the
pending queue. Closing the panel preserves only its opaque review identity in
session storage; reopening reads the receipt, without replaying a write.

Permissions match Announcements Send, including server-side CSRF and cwl_send
mapping. The worker rechecks current actor access and a secret-authenticated
loopback-only, read-only season/binding/workflow scope immediately before editing.
Archived/rebound/foreign work cannot pass that check. A fresh preview is required
after campaign generation or post fingerprint changes. Authentication denial
clears protected snapshots; ordinary read failures retain the last authorized
preview with a visible error.

A deployment needs backend/frontend and a bot restart. It edits nothing merely
by being released. First real use on the November Main/Lazy posts belongs to the
owner unless separately authorized. This batch supports roster posts only; the
existing publishing service could support other campaign messages, but this UI,
queue and routes do not expose them.

Original139 evidence (superseded by prompt146 below): 138 affected backend regressions pass, covering
publishing/worker, HTTP authorization, scopes, receipts, sequence preservation,
and current/future copy inheritance. The complete frontend suite passes 1497
checks across 263 files; TypeScript and the main frontend build pass. Required
war-reminder validation passes 213 backend checks (one skipped), 35 frontend
checks and its build. Four meaningful mutants are killed: constant fingerprints,
removing the final post-scope fingerprint check, enabling role mentions, and
skipping final effect authorization. Removing only the earlier redundant
fingerprint check survives because the final check still rejects the stale post;
it is not counted as a kill.

Actual owned Mongo checks prove three partial/TTL indexes, duplicate preview
identity, one concurrent update claim, interrupted-edit uncertainty, and stale
completion fencing. With 2000 terminal workflows, the hinted idle query examines
zero documents and keys. Natural TTL removed private workflow/scratch records
in nine seconds while preserving an ordinary draft. Temporary QA databases were
removed; the persistent review fixture remains alive.

A browser exercised a complete owned-fixture edit and current/future saved-copy
write through real HTTP, Mongo and the existing publishing service, with fake
Discord persisted locally. At 320/360/390/1440, review panels have no horizontal
overflow, controls meet the 44px target, Escape closes, and no external requests
or page errors occur. Narrow and wide screenshots were inspected. A wider panel
uses the existing ActionPanel width variable for readable desktop comparisons.
Previewed media are local samples; this proves no live Discord delivery.

A cross-cycle equal-clock regression records the reviewed whole-template source
identity for a per-pool future copy. A field save after the whole save inherits
at the same timestamp; a later ordinary whole save's revision invalidates that
exception even when its content and timestamp are identical. No clock is moved.

At runtime source freeze ad8cc9fa, the guarded full backend passes 6381 checks,
99 skipped, and 267 subtests in 583.58 seconds. The exact committed artifact's
production-shaped boot passes: 51 configured routes, native Mongo pool, real
owner on copied SQLite and owned Mongo, blocked external network, config 200,
unauthenticated auth 401, cleanup and source-hash proof. Its temporary Mongo and
source export were removed. The final frontend suite passes 1497 checks across
263 files; TypeScript and the final main build pass.

Owned browser negative cases prove a stale post and removed bot access each
make zero edits. A confirmed edit plus saved-copy race makes exactly one fake
edit, reports Done and a visible saved-copy warning, and is not retried. Native
Hikari Message/Attachment objects separately prove attachment list/description
changes affect the fingerprint while rotating Discord signatures do not.

Persistent preview: `http://127.0.0.1:44501/`, **Open local test session**. Main
and Lazy cards have sample posts; **Edit post** uses real owned HTTP, SQLite,
Mongo and workflow writes against persisted fake Discord. Local fixture controls
can simulate stale/deleted posts, access loss, worker pause, slow edit and saved-
copy races. Open post links stay on the local sample viewer. Test state is
retained; sample text may show earlier QA edits. No production request is made.
Entry `post-update-preview-BcmhL5SU.js`, SHA256
`d49f60ddb568cbd0e93a50970966ea574292ed8c7499208f28649ce1d8c33969`.
The server and its owned fixture databases remain alive for review.

An additional end-to-end review found that the preexisting message fingerprint
omitted attachments. A local callback added attachment 601 while the final scope
check awaited; the old worker edited with retained attachment 600 only. Three
worker/service regressions (added attachment, filename, description) each failed
before the fix. The same fingerprint now includes stable attachment identity and
relevant metadata, canonicalizing only Discord's rotating CDN signatures. Those
three races refuse the edit; a regression proves signature rotation stays equal
while another query change remains distinct. Removing attachment fingerprinting
is a sixth genuine killed mutant (four failing regressions). No other publishing
policy changed.

The full backend at the earlier 84a94b0a checkpoint passed 6377 checks, 99 skipped,
and 267 subtests in 589.73 seconds. That pass predates the attachment fix and is
not used as the final gate. The corrected source has the fresh full pass and
exact-artifact boot described above. Earlier failed reproducer and harness logs
are retained, including an initial local browser connection before the fixture
reported ready and the uncounted redundant-fingerprint mutation survivor.


## Storage and release boundary

No campaign backfill or saved-production rewrite occurs. The existing campaign
storage owner handles field-only copy CAS; the private workflow storage owner
uses kind `cwl_roster_post_update`. Release/archive queue gates must recognize
its active statuses `pending_preview`, `previewing`, `pending_update`, `updating`.
Indexes and private TTL namespaces are additive. A future release needs a bot
restart plus backend/frontend; no post changes simply because it is released.
The lease is cooperative and fingerprint reads remain separate from the edit
call; an unknown outcome requires checking the post, never an automatic retry.

## Completion review

- Authorization: HTTP uses Announcements' existing cwl_send permission and CSRF; workflow ownership includes actor, guild, season, cycle and pool. Worker authorization is checked again at the actual edit boundary against a secret-authenticated, loopback-only, fresh SQL binding/archive check. The public DTO omits private draft IDs, target IDs, fingerprints and worker epochs.
- Inputs and rendering: literal title/body and HTTPS link buttons have size/count limits; unknown target/layout/media shapes refuse the update. Candidate validation does not accept destination/role/target fields. Native observed media, attachments and visible role header are preserved; a changed saved template cannot silently replace them. Discord preview is approximate and its controls do not send anything.
- Concurrency and recovery: opaque nonce identity is idempotent, private workflow claim/completion use CAS/epochs, a reviewed update is consumed once, and stale completions cannot replace a terminal result. Both observed message and final post-scope fingerprint checks remain. A possible accepted edit is never automatically retried; startup reports interrupted work as uncertain. Session-storage recovery reads a receipt instead of replaying POST.
- Saved-copy scope: only the selected pool's current-cycle text/buttons, plus its recurring copy when the default-ticked checkbox is selected. Other pool/message/destination/role/activation/send-ledger fields retain their values. Existing publishing audit receipts append normally. Mixed-pool, whole-template inheritance, receipt-only sequence and same-clock ordering have regressions. An ordinary older draft cannot overwrite a new inherited pool copy.
- Failure truth: deleted/foreign/stale/permission-denied targets never create replacements. Confirmed external edit plus saved-copy CAS failure reports Done and a visible saved-copy warning. Ordinary read failure retains the last authorized preview; auth denial clears protected content and requires a reload. Closed panels neither poll nor fetch preview content.
- UI: 320/360/390/1440 review states, narrow/wide visual inspection, no horizontal overflow, 44px controls, Escape closure, named-channel confirmation and sticky actions. Existing ActionPanel history/focus handling is reused. Full frontend regression suite, TypeScript and build pass. Owned browser failure cases prove stale and denied edits stay at zero and saved-copy race makes exactly one fake edit plus warning.
- Evidence limits: local real HTTP/SQLite/Mongo and actual publishing/worker code, persisted fake Discord, real Hikari message objects. No live Discord edit, delivery, permissions, mobile client behavior, production API timing or production writes were tested. The first real November edits belong to Ruggie. The feature needs a bot restart as well as backend/frontend release, all held for owner approval.


## PR183 rework: prompt146

Release remains held for the owner's preview. Backend source c4330d58 fixes
pause/resume and other metadata writes so they do not supersede field-only future
roster copy. The real Mongo reproducer retains Updated body across pause and
resume. Pending updates expire atomically against claim at five minutes: the
299.999-second case claims once, the 300-second and 23-hour cases claim zero and
finish failed. Native galleries retain their exact positions, including before
the title divider; incompatible skeletons refuse without an edit. Member404 is
access changed. Failure before edit is Not updated; only a potentially applied
edit is uncertain. Previews resolve role names through actual fetch_roles and do
not show snowflake IDs.

The UI uses the shared gold link style, disables Update unless has_changes is
explicitly true, shows No changes for false and Preview again for missing data,
preserves an unticked future-month choice across status refresh, and uses the
requested short month/status wording. User-authored title/body text is not rewritten.

Actual native REST review uncovered two default-encoding mismatches missed by
the earlier builder-only fixture: REST separator SMALL spacing versus builder
UNDEFINED, and absent REST emoji versus builder UNDEFINED. Frozen source6cb7ac83
canonicalizes those semantic defaults only. Actual LARGE spacing and actual emoji
changes remain distinct. The native worker regression failed before and passes
after; the real local fixture now returns has_changes=false and its Update is
disabled. Before evidence: nochange-native-diagnostic.log and
native-regression-before.log. After: nochange-native-diagnostic-after.json,
native-focused-final.log and no-changes/proof.json. The diagnostic's initial JSON
was overwritten by the after run; the original before diff log and failing native
regressions remain the before evidence.

Final gates so far:1504 frontend tests/263files,20focusedfrontend,58focusedbackend,
TypeScript and main build;13 genuine rework mutants (8 backend protocol/storage,
3 UI,2 native-default). The required war-reminder check passes213backend/1skip and
35frontend plus build. Exact6cb boot uses51configured production routes, production
flags, native pool, real durability owner on owned Mongo/copiedSQLite, blocked
external network, config200/auth401, sourcehash and complete fixture cleanup.
The artifact/owned27169 were removed before the final full backend run.

Actual browser evidence at360/1440: legible gold Openpost link, @CWLplayers rather
than a role ID, no horizontal overflow or sub44px controls, Escape closure.
Native no-change review at360 is disabled. Fake-Discord edit completes once and
saves the requested current/future scope; stale and access-denied cases edit zero;
saved-copy race edits once plus honest warning. No actual Discord edit or
production write was tested. The gallery-stale-marker test initially contaminated
the next fixture layout; removing only the harness's exact injected marker between
cases corrected the harness. Initial failed logs remain.

The first sandboxed full run was interrupted after3socket PermissionErrors and
24passes. Fourteen identical HTTP cases pass with local-socket permissions. The
pre-native-fix escalated full passes6397/99skip/267subtests in626.95s and is retained
as pre-fix evidence. Final behavior source6cb7ac83 passes6400backend/99skip/267subtests in598.58seconds (.local/p146/full-be-final.log).
The first boot attempt used a temporary war-build path already cleaned by its
checker; it failed before app startup, cleaned Mongo/export, and is retained. The
corrected retained-build boot passes.

Persistent review: http://127.0.0.1:44501/ → Open local test session. Same owned
SQLite/Mongo27165/messages are retained; no reseed. Current serverPID3501935 uses
28ef backend; entrypost-update-preview-Dvi6sVHZ.js SHA256
3516e6753c6ce8ba4dc6c3f91fe8fad5b39035f1adc030c586337e3cf404ead1.
Earlier review assets are retained in .local/p146/previous-review-site. All flags
are reset to ordinary operation; QA edits remain in the local sample.

### Final response-copy delta and artifact proof

After that full pass, revision28efdf55 changes exactly four response literals:
three malformed-input400 messages and the stale-month409. The runtime byte/AST
proof confirms only those string constants changed; validators, schema and
control flow are identical to6cb. The focused followup passes79tests and3subtests,
including real store rejection,400error+issue_reference schema and409error-only
schema. An initial new test omitted the already-existing issue_reference field;
its failed log is retained and the corrected test checks that existing schema.
The full suite was not repeated solely for this four-literal copy delta, as
explicitly directed by the coordinator; it remains a full behavior pass at6cb,
with the final copy covered by focused checks and AST proof.

A case-insensitive bounded audit of public errors/warnings in the feature's store,
service, publishing, HTTP and bridge owners finds no prohibited UI vocabulary.
API field names and user-authored post content retain their existing values.
The exact28ef artifact boot passes51production routes/nativepool/realowner on
ownedMongo/copiedSQLite/config200/auth401/blocked external I/O and cleanup. Source
SHA256 is0196c09d0819578bfac3c9785a3ff0c2b72ea0df290e9575d8f2abc3a3ca5437.
Temporary bootMongo27169 and archive export are removed; persistent reviewMongo
27165 and all existing sample state remain. Before the final preview restart,
its active-workflow count was zero. All metadata/evidence is under.local/p146.

Release is held. Main integration must retain PR175's heartbeat behavior and
PR177's new-default copy marker; this branch has not merged or activated them.

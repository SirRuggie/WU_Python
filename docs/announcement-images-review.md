# Announcement and image sequence review

Prompt45 and its two addenda use one durable per-pool sequence: confirmed announcement receipt, sorted full-resolution clan attachments, then a closing note. New images use the announcement receipt's channel; prior image updates/recovery keep their saved channel. SQLite owns image/closing/TEST receipts and sequence state; native Mongo campaign receipts still gate announcement delivery. No PNG bytes are persisted.

The shared ordering is Lazy trailing number descending, then unnumbered names; Main capacity30 A–Z, capacity15 A–Z, then other capacities. Review shows roles, destination and ordered clans. Known429 delays resume serially. Failure stops at the named clan; uncertain delivery requires explicit duplicate-warning recovery. Restart skips confirmed receipts and does not retry unknown sends. Full TEST sends have their own durable receipts, no mentions, and do not mark production sends.

Only structured Discord10008 confirms deletion. Image updates then create a fresh same-channel no-ping copy with archived receipt linkage. Closing repair is queued durably after reviewed image updates; existing closing text remains unchanged. Announcement resend is always explicitly reviewed, checks10008 again, archives the old occurrence and image mappings, preserves old Discord posts, and uses a fresh nonce. No automatic November resend or live test is part of release.

Verification:
- Full isolated backend: 5,201 passed,21 skipped,218 subtests. Full frontend:1,072 passed. TypeScript/build and complete test:layout passed.
- Restored-source targeted54 tests/15 subtests pass after mutation runs. The first full backend failure was an old exact-response expectation; updated for the new read-only destinations/closings fields.
- All10 mutations killed: Lazy ascending; Main15 first; before announcement confirmation; continue after failure; image mentions; duplicate Resume; image10003 treated as deleted; announcement10003 treated as deleted; resend without deletion check; uncertain resend. Continue-after-failure initially survived because storage independently blocked the extra post; strengthened the test to require the original failing clan and reason, then killed it.
- Fake Discord browser:360/1440 review layouts,12 recorded messages across two channels, Main30→15 alphabetical groups and Lazy128→127→126→125. Each pool has one announcement, four clan messages, one closing; only the announcement allows its configured role. Multi-page images remain attachments in one message. No page errors or overflow. Screenshot renderer is approximate; JSON receipts are the order/payload evidence.
- Readiness, destination ownership, permission changes, duplicate requests, cancellation, restart, republish, frozen metadata and deleted/uncertain recovery are covered in sequence/store/transport/recovery regression suites. No mocked send is evidence of live Discord delivery.

Evidence: /tmp/wu-ann-full-backend-rerun.log, /tmp/wu-ann-full-frontend.log, /tmp/wu-ann-full-build.log, /tmp/wu-ann-full-layout.log, /tmp/wu-ann-mutation-results.json, /tmp/wu-ann-restored-final.log, /tmp/wu-announcement-sequence-browser-final.log, /tmp/wu-announcement-sequence-review/.

Tooling notes: browser startup initially preceded fixture readiness; final run waited for ready. The initial asynchronous browser poll returned before the fixture completed; explicit Node response polling verifies all12 receipts. Fake-channel rendering was corrected to omit empty metadata lines and display button labels. The full layout run used isolated networking and a disk-backed /tmp mount because the host tmpfs inode pool was exhausted. Required mutations restored all application source.

Remaining release gate: Claude ACCEPT, then integrated clean tagged backend/bot/frontend release with backup, counts, readiness and rollback. Preserve the carousel already accepted separately when merging. Staff, not release automation, chooses whether to resend a deleted November announcement.

Claude171 required-fix verification: archive preconditions are shared by a public
read-only preflight and the archive transaction, and checked before reopening the
native occurrence. Ready sequences and uncertain images reject resend without
changing native or SQLite state; resolving that state permits a valid resend.
Staff continuation requires the matching sent occurrence/channel and no message
ID, except a stopped unconfirmed sequence with its own matching receipt. Both
normal HTTP authorization and the explicit send gate are tested for staff lacking
cwl_send (the latter independently of the generic route permission map).

The UI waits five seconds or a stopped state before offering recovery, unlocks a
full-test destination after definite4xx rejection (408 remains ambiguous), reports
Checked moments ago for a rate-limited check, and tests pre-confirmation stopping
and the closing-message check copy. Full backend5213 passed,21 skipped,221
subtests; frontend1088 passed; TypeScript/build passed. Four mutations killed:
reopen before preflight, missing explicit send permission, wrong channel and wrong
occurrence. Evidence .local/ann171-mutation-results.json and per-mutation logs.

Isolated browser360/1440:12 fake messages preserve announcement/images/closing
order and allowed mentions; automatic deleted detection and frozen-body/channel
ambiguous full-test retry pass with no page errors. Evidence is in
.local/announcement171-review. The initial recovery browser started immediately
after sequence delivery and timed out; read-only diagnosis confirmed both completed
pools and automatic checks, then the rerun passed. No live Discord write occurred.
Scratch setup fixes corrected working-directory paths and the native-delivery test
fixture (complete its pending request before testing resend). The first explicit
send-gate mutation survived due to the separate generic route gate; the added
boundary test verifies the explicit gate independently and kills that mutation.

Claude entry 173 accepted the recovery fix after a diff check. Residual risk:
the archive preflight and archive run in separate transactions; a concurrent
staff state change between them can still make archive fail after native reopen.
This narrow staff-driven race remains accepted, rather than an atomicity guarantee.
Release does not initiate a send: November remains unchanged until staff explicitly
choose Review and send or Send again.

Integrated release verification after main 28e37f0: 5,313 backend tests passed
(21 skipped, 221 subtests); 1,135 frontend tests passed; TypeScript/build passed.
The synthetic two-pool browser sequence and deleted-message/frozen retry checks
passed at 360/1440, with no page errors. Complete layout verification is recorded
in the release handoff before activation.

## announcement-images-1 release and smoke

Released PR #98 as `47f5422f2541fed734f1ea86a7df59ded38194f5`, tagged
`announcement-images-1`, after Ruggie's explicit approval. Backend and bot run
that revision; frontend was built from its clean isolated tagged checkout.
Public `index-CHeFTl6l.js` SHA256
`27e8c37ef4bb1e230a2c611884d1707bb11d2474dfbc7cad20531516ee0fd5a0`
and affected feature assets match the immutable release manifest.

The integrated gates passed: 5,313 backend tests, 21 skipped, 221 subtests;
1,135 frontend tests; TypeScript, build and full layout. Synthetic 360/1440
checks exercised ordered two-pool delivery and deleted-post/frozen retry recovery.
Backups verified; 25 clans before and after; protected SQLite and native campaign
send receipts unchanged. Additive migration rehearsal preserved old rows. New
image tables stayed empty and no replacement was queued at startup. Runtime
imports, readiness and service journals passed. No live test messages were sent.

Claude handoff 176 records read-only production smoke passed at 360px: matching
frontend/backend/bot revision and public hash, no startup tracebacks or sequence
activity, no HTTP errors or overflow. Both November pools correctly report the
prior posts deleted, with Send again available. Nothing was pressed or sent.

Rollback retains frontend/backend `d1c670877b03ae8bf19f4ca1fa675af3edaa1cd0`
and bot `5d09708b8cdc6ac0349a20c75293bd8eae9153fc`; code rollback must not
restore data over legitimate staff changes. Release evidence is retained in
`.local/announcement-release-evidence` on the release host.

Follow-up prompt 50 covers completion confirmation, a saved shared test channel,
collapsed testing controls and the contradictory deleted-post resend copy.
The accepted preflight/archive concurrency race remains documented above.

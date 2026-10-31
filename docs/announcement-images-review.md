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

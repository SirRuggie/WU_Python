# Announcements polish review

Prompt 50 follows announcement-images-1. The pool cards keep status and their
primary action visible. More holds preview, editing, message checks and full-post
testing. Testing and images starts collapsed and mounts its image tools only when
opened. Confirmed deletion replaces the old resend explanation.

Send, send again and resume use the existing sequence and confirmation endpoints.
Their result dialog follows durable status through progress, stop and completion;
uncertain delivery keeps the existing explicit recovery review. The first-message
link comes from a confirmed sequence receipt, including when the older campaign
receipt has no URL. An assumed announcement is not described as a confirmed post
without a message link. Image updates and test jobs have separate completion
states; closing gives a short in-app status notice. No new send path was added.

The shared test destination belongs to RosterImageStore. Its GET/PUT require
cwl_send; writes validate the exact channel, server, text/announcement type and
revision. Full-post, single-clan and Test all load it, but a per-send override saves
only when staff check Make this the default and confirm. A revision conflict
retains the choice; permission/view changes during saving prevent the stale test.

Test content uses the production renderers and order. Discord messages have no TEST
prefix; only the dashboard identifies them as tests. Role mention text stays in the
content, while allowed_mentions explicitly forbids role/user/everyone pings.
Request nonces are separate transport identities. Tests retain separate tables and
never claim production sent marks or sequences.

## Rework 51

The test-clock prerequisite was merged separately as PR104. Stale TEST/mention
assertions and the decision record now follow production payload parity. Test link
buttons include the production emoji. Single-clan tests require cwl_send and do not
write production audit rows. Default-save conflicts expose Reload and clear after
a successful reload. Test all receives the actual send permission. Closed More
contents have an explicit visibility rule. Parent-level tests cover Send and Send
again through progress, completion and stopped states. The normal layout command
now runs the synthetic Send browser gate, requiring hidden secondary controls at
rest, two Done dialogs, 12 fake messages and no browser errors.

## Validation and limits

- Integrated frontend: 1,150 tests passed; TypeScript and Vite build passed.
- Full network-isolated backend: 5,343 tests and 221 subtests passed, 21 skipped. Coverage includes channel
  authorization/ownership/malformed inputs/revision conflicts, production renderer
  parity, no-ping enforcement, separate receipts, first-message links and restart
  handling. Existing aiohttp application-key warnings remain.
- Required mutations all killed in an isolated copy: success returns to review;
  default saved without the checkbox; test payload permits role pings; parent resultOpen
  forced false; parent queued-result state omitted. All five mutations were killed.
- Isolated fake Discord/browser at 360 and 1440: pool height below one phone screen,
  secondary actions collapsed, no horizontal overflow, full-test completion with
  a single Close and first-message link, shared default surviving reload, six test
  payloads without TEST/pings, and both production-style pools reaching Done.
  Production sent marks remained empty after tests. No browser script errors.
- End-to-end checking caught and fixed a missing completion URL when the sequence
  receipt held the message ID but the legacy campaign receipt omitted its URL.
- Before/after and completion screenshots are retained under
  `.local/polish50-browser` and `.local/p51-browser-final` on the review host. Synthetic preview uses port 8905.

These checks use isolated SQLite/Mongo fixtures and fake Discord, not live delivery.
No production data, messages or service state changed for this batch. Keyboard and
native dialog focus behavior use the existing components; this is not a complete
assistive-technology audit. Release requires Claude acceptance and the usual backup,
count, readiness, rollback and post-release smoke gates.

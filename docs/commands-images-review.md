# Commands and image tools workflow review

Reviewed October 23, 2026. Scope: Command triggers, reply builder entry flow,
preview, explicit test send, saved history entry point, Image Gallery, shared image
picker, upload/import, metadata editing, archive/restore and storage refresh.

## Interaction rules applied

- Directory → focused editor → save or return. Preserve search and unsaved work;
  the command directory steps out of the way on narrow layouts.
- One Edit/Preview switch and one Save control. Preview renders only when selected.
  Saving persists the reply and its enabled state; it does not post a message.
- Keep command name, reply and enabled status visible. Put mentions, appearance,
  test sends, deletion and history behind named disclosures. Remove transport
  terminology from the builder description.
- Image Gallery starts with available images. Search, category and availability
  are compact filters rather than a wall of category buttons. Copy/choose stays
  visible; metadata and archive actions are in Details. Archive does not delete
  the object or break an existing message link.
- File selection is a draft; Save images starts the upload. Show partial progress
  and retain unconfirmed files/selections. Validate the entire size-limited batch
  before starting. Bulk moves and gallery mutations have synchronous click guards.
- The picker uses a native modal, return focus and guarded Escape/close. Gallery
  drafts and in-flight operations participate in app navigation protection.
- Storage indexing is a deliberate maintenance action, never a page-load write.
  It uses a public MediaStore method; features no longer use its private client.

## Correctness and adversarial review

Command saves retain revision checks and drafts on conflict. The UI blocks a
second save after a conflict until the user reviews/reloads; revoked access clears
protected command/gallery data. Reads are sequenced and gallery writes invalidate
older pending reads. Existing permission and role-hierarchy enforcement remain.

Image updates from the new UI include expected name/category/archive values. The
server compares them, then uses an atomic Mongo precondition including the stored
update timestamp; an upsert collision becomes a conflict. Existing documents and
routes are preserved. Older clients without `expected` retain the old update
contract; refresh old tabs to use the new checks. Unsafe stored image URLs are
excluded from the public catalog, without deleting their documents.

Test sends require a channel-specific review. Duplicate local clicks are blocked;
uncertain delivery blocks further sends until the user explicitly acknowledges
checking Discord and prepares a new test. Backend receipts now bind the nonce to
the validated draft and destination, preventing a receipt for a different draft
from being presented as a new success. Old receipts lacking this fingerprint fail
closed on reuse. Existing Mongo majority-write receipts and inert test payloads
remain: no pings or interactive role controls, and no automatic retry.

## Validation

- 287 frontend tests: shared regressions plus closed test disclosure, duplicate
  send prevention, uncertain delivery acknowledgement, read-only gallery opening,
  partial bulk moves and whole-batch file-size validation.
- 186 backend tests: command validation/recipients, guild destinations, inert test
  rendering, duplicate and uncertain receipts, malformed/unsafe image inputs,
  catalog authorization, stale/racing metadata edits, upload/media signatures,
  backup coverage, shared clan/FWA media and architecture checks.
- Production frontend build passed; existing chunk-size warning remains.
- Isolated browser checks at 320, 390 and 1280 pixels: command selection, draft
  editing, preview, review/test failure, save conflict, image selection into a
  command and successful save; gallery search, filters, long names, rename failure
  and success, archive/restore, large catalog pagination controls, and revoked
  access clearing the gallery. No horizontal clipping observed. Native controls,
  labels, focus movement and visible errors were inspected.

## Limits and compatibility

No live Discord messages, role changes, command changes or R2 test uploads were
performed. Browser writes were isolated fixtures; backend media/Discord tests use
fakes. These checks do not establish live delivery or physical-device/screen-reader
coverage. Mongo receipts survive web restarts; browser drafts do not survive a
confirmed tab close. Cross-system upload/catalog completion is not transactional:
if indexing fails after storage succeeds, refresh/check storage before retrying.
Existing content-addressed image keys reuse identical bytes in the command-image
folder. Bulk moves are per-image operations, not a batch transaction; progress
reports explicitly identify partial completion.

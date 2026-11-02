# Announcement in-place roster post editor (139)

Source checkpoint only. Release is held for owner preview; no production API,
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

Current checkpoint evidence: 134 affected backend regressions pass, covering
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

Full backend, exact committed production-shaped boot, additional browser failure
cases and final preview manifest remain pending at this checkpoint. Release is
held for owner review. No production state or Discord post was changed.

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
not the final gate. The corrected source passes 138 affected regressions and
repeated owned-Mongo checks. A fresh full backend run and exact artifact boot are
still required; the global full-test slot is currently assigned to prompt 143.

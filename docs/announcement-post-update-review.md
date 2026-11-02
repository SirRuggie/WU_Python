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

Current checkpoint evidence: real publishing service through the worker with
fake Discord; scoped HTTP permission/ownership/CSRF/readiness/archive tests;
current/future-pool inheritance, ordinary draft/sequence and storage regressions;
focused announcement UI flow and TypeScript. Final full backend/frontend, owned
Mongo query-plan/TTL proof, mutation set, layouts, production-shaped boot and
persistent preview are still pending. Mock results are not live delivery proof.

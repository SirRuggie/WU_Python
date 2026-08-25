# Ticket status lifecycle: legacy channels and thread v2

The rollout deliberately runs two ticket authorities in parallel. Historical
legacy notes are retained below, but the current contract is:

| Runtime | Authority | Writable statuses | Resolution surface |
|---|---|---|---|
| Legacy channel tickets | `button_store` | `open`, `approved`, `denied` | `/ticket` |
| Thread-ticket v2 | `tickets` rows matching `venue: "thread"` and `runtime: "thread_v2"` | `open`, `approved`, `denied` | Private console and `/ticket-pilot` |

Normal ticket creation and resolution never copy, mirror, merge, or repoint a
document between these authorities. The explicit terminal-only
`/ticket-pilot migrate-legacy` workflow is the sole exception: it creates a
separate v2 clone while leaving the source legacy document and Discord objects
unchanged. The runtimes otherwise share only rollout state, one-open-ticket
slots, and ticket-number counters. See the
[operator source of truth](ticket-console-operations.md).

## The three writable statuses

| Status | Meaning |
|---|---|
| `open` | The ticket is awaiting a recruiter decision. |
| `approved` | A recruiter approved the applicant. |
| `denied` | A recruiter denied the applicant. |

There is no writable `new`, `closed`, or `abandoned` state. The console may
label an open ticket as **New / open**, but the stored value remains `open`.
After an approved or denied ticket releases its shared slot, the applicant may
open a later ticket; the guard prevents only a second simultaneous open ticket
of the same type.

## Why `closed` has exactly one document

`/ticket close` and `/ticket reopen` were **deleted** in `b3015f6`
(2025-07-24, *"update ticket system commands to singular, add role restrictions,
and improve workflow"*). They were the only writers of `status: "closed"` — and
`reopen` was the only writer of `reopened_at` / `reopened_by`.

Consequences, all historical artefacts rather than current product states:

- `closed = 1` forever. That single document predates the deletion.
- With no close path, tickets that were neither approved nor denied simply
  **stayed `open`**, which is why open tickets accumulated over time.
- Old commented-out close/reopen code is not a specification.
- A legacy clone with `closed` must be reviewed and explicitly classified as
  approved or denied. Never map it automatically to `denied`.

## Historical legacy cleanup and counts

Legacy maintenance once reconciled an open database row whose channel had gone,
or an open row whose channel looked denied, by writing `denied`. Those cleanup
denials lacked `denial_type`; that incidental distinction may still help when
reviewing historical `button_store` data. Thread v2 does not use that cleanup
path: its denial writers go through the audited resolution domain flow.

As of 2026-08-02, after the legacy cleanup, the historical collection contained
361 documents: `approved` 64, `denied` 273, `open` 23, and `closed` 1. All 23
open tickets then had live channels.

## Historical phase-2 experiment

On 2026-08-02, a pre-v2 experiment exercised legacy approve, deny, override,
and claim flows. Diagnostics reported two collections at 363 documents, with
`approved` 64, `closed` 1, `denied` 275, and `open` 23. That experiment used a
conditional primary write plus an unconditional secondary mirror.

That result is retained only as legacy history. The current parallel rollout
supersedes it: `button_store` and `tickets` are intentionally different
authorities, and matching collection counts are neither expected nor desired.

## Thread-v2 decision lifecycle

Every v2 approve, deny, and override action uses the same secure domain path:

1. Read the immutable ticket ID through the thread-only runtime filter.
2. Verify the actor is still a recruiter and refresh the applicant's linked
   accounts.
3. Apply the account, staff-context, Chocolate-review, and blacklist gates.
4. Compare and swap the expected status, decision revision, and linked-account
   revision in one Mongo write.
5. Only after that write wins, reconcile the durable decision effects.

The decision write cannot reopen a ticket or target a legacy channel row.

| Outcome | Meaning | Terminal decision effects |
|---|---|---|
| `won` | This caller committed the decision. | Run or resume from durable checkpoints. |
| `lost` | Status, decision revision, or account revision changed first. | Do not notify, archive, or publish a terminal refresh for this attempt. |
| `missing` | No matching thread-v2 ticket exists. | Do nothing; report that the record is gone. |
| `blocked` | An account, review, blacklist, identity-lock, or effect gate refused the decision. | Keep the current status. |
| `unauthorized` | The actor is not a recruiter at the authorization boundary. | Keep the current status. |
| `effect_failed` | The decision committed, but durable follow-up work is incomplete. | Preserve the terminal status and retry the pending checkpoints. |

Account and staff-context refreshes performed before the compare-and-swap may
remain useful if a race is lost. Applicant notification, terminal archive, and
terminal console effects never run for `lost` or `missing`.

### Approval and denial gates

Approve and deny both force-refresh linked accounts immediately before the
decision. Approval fails closed when the lookup fails, no account is currently
linked, flag identities are still refreshing, staff account context is pending,
or a new FWA identity still needs Chocolate review.

Approval also takes the identity guard, re-reads active blacklist flags against
the Discord ID and observed player tags, and checks recruiter authorization
again immediately before the compare-and-swap. An active blacklist blocks the
write. This prevents a concurrent flag or role change from slipping through a
stale panel.

Denial may proceed after a failed or confirmed-zero account lookup. A failed
lookup is recorded as durable retry work so staff context can converge later;
it is never interpreted as zero accounts.

### Overrides are conditional

A recruiter who loses a race may be offered an override only when the requested
outcome differs from the current decision. The saved action is bound to that
recruiter, recruiter authorization is checked again at click time, and approval
re-runs all current account and blacklist gates.

The override must still match the prior status, revision, and resolution marker,
and the prior decision's effects must be complete. Markerless terminal legacy
imports are eligible only while their audited import provenance remains intact.
If the ticket changes again, disappears, or still has pending effects, nothing
is overwritten. An override is another compare-and-swap transition; there is no
unconditional `expect=None` write.

### Durable effect completion and audit

A winning transition writes a unique resolution marker and pending checkpoints
for applicant notification, staff account context, thread-pair archive, and hub
refresh. The worker leases that exact marker, completes each idempotent step,
then marks the whole effect set complete.

Startup and the periodic reconciler retry terminal tickets whose marker is not
complete. Notification recovery checks the marker before posting, so retrying
does not intentionally send the applicant a duplicate. Archive reconciliation
always returns both terminal threads to locked and archived. A visible
**Decision recorded; updates retrying** result means the status is authoritative
and the remaining effects must be allowed to recover; it is not a failed or
rolled-back decision.

Every winning transition appends a `status_transition` audit entry with the
actor, old and new status, revisions, effect marker, linked-account snapshot,
and override provenance when applicable.

## Claim and close behavior

Legacy `/ticket claim` and `/ticket release` remain available only to operate
channel tickets during coexistence. They are advisory legacy behavior and are
not copied into v2.

Thread v2 has no recruiter claim, release, close, or reopen action. Its schema
removes old claim fields, resolution confirmations contain no claim note, and a
terminal thread remains approved or denied. The `ticket_open_slots` “claim” is
an internal intake lease enforcing one open ticket; it is not recruiter
ownership of a ticket.

## The v2 console never renders legacy `closed`

Normal v2 list, search, count, detail, and transition queries require the
thread-v2 runtime filter, so channel rows and the historical `closed` value are
outside the console. A migration preview must stop for manual approved/denied
classification instead of inventing a fourth v2 state.

## Related

- [Ticket pilot and console operations](ticket-console-operations.md) — current
  rollout, drain, and recovery authority.
- [Ticket data model](ticket-data-model.md) — historical storage context.
- [Ticket channel naming](ticket-channel-naming.md) — why a legacy channel name
  is a misleading proxy for status.
- [Ticket console](ticket-console.md) — the console design record.

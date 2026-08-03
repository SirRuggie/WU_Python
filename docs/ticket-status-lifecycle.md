# Ticket status — the real values, and why the data looks odd

## The status values that actually exist

Only three are ever written:

| Status | Written by |
|---|---|
| `open` | `handlers.py:368`, on creation |
| `approved` | `close.py:234` — with `approved_at`, `approved_by` |
| `denied` | `close.py:437`, `close.py:529`, `close.py:653` — with `denied_at`, `denied_by`, `denial_type` |

There is also a legacy `closed`, which nothing writes any more (see below).

**There is no `abandoned` status.** If a workflow needs one, it has to be
introduced along with a rule for backfilling existing rows — it cannot be
filtered on today.

## Why `closed` has exactly one document

`/ticket close` and `/ticket reopen` were **deleted** in `b3015f6`
(2025-07-24, *"update ticket system commands to singular, add role restrictions,
and improve workflow"*). They were the only writers of `status: "closed"` — and
`reopen` was the only writer of `reopened_at` / `reopened_by`.

Consequences, all of which are artefacts rather than signal:

- `closed = 1` forever. That single document predates the deletion.
- With no close path, tickets that were neither approved nor denied simply
  **stayed `open`**, which is why open tickets accumulated over time.
- A commented-out block survives at `close.py:314-372` from that removal. It is
  dead code, kept as a fossil; do not treat it as a specification.

## Ghost cleanup writes `denied`, not something distinct

`/ticket` maintenance commands that reconcile documents against reality —
`manage.py:467` (ghost rows: a document marked open with no live channel) and
`manage.py:586` (mismatched: a denied-looking channel with an open status) —
resolve the row by setting `status: "denied"`.

So **`denied` conflates two different things**: a recruiter actually denying a
candidate, and a janitorial fix-up. If you ever need to tell them apart, note
that a real denial also sets `denial_type`, and cleanup writes do not. That is
the only discriminator, and it is incidental.

## Counts as of 2026-08-02, post-cleanup

361 documents total: `approved` 64, `denied` 273, `open` 23, `closed` 1.
All 23 open tickets have live channels; 0 ghost rows, 0 orphaned channels.

## Phase 2 status — LIVE and soaking as of 2026-08-02

Verified on the running bot: approve, deny, the override path on both, and
claiming. `/ticket diagnostics` after the run showed both collections at 363 —
`approved` 64, `closed` 1, `denied` 275, `open` 23 — divergence none, reading
from `tickets`.

That distribution is **unchanged from the phase 1 final, and that is expected**:
the override tests were run against tickets already in their target state
(overriding a denied ticket to denied), which is the natural way to exercise the
path without disturbing live data. Transitions were confirmed to be moving status
independently — a ticket denied during the run dropped out of `/ticket list`.
Noted because identical before/after counts look like a no-op write at a glance,
and they are not.

**That is the thing phase 1 could not prove**: a conditional write against the
primary plus an unconditional mirror to the secondary keeps the two in sync.

**Verified as flows, not as individual cases.** The distinction matters for
anyone reading this later. Confirmed working end to end: approve, deny, override
on both, claim. Not separately exercised, and therefore *not* proven:

- a non-recruiter clicking an override button (should refuse)
- the `missing` outcome — a resolution against a deleted ticket document
- the custom-deny **modal** LOST branch specifically, which is the one path that
  responds with `ctx.respond` rather than `edit_initial_response`, because modal
  handlers are never deferred
- the claim note appearing when resolving someone else's claimed ticket

## Phase 2 — transitions are conditional, and losing is not a dead end

Status changes go through `store.transition`, which re-asserts the status it
believes it is moving *from* inside the filter. Mongo arbitrates, not the
network. The pattern is the one already proven in `manage.py`'s cleanup filter.

Three outcomes, and **side effects run only on `won`**:

| Outcome | Meaning | Applicant messaged / channel renamed |
|---|---|---|
| `won` | this caller caused the change | yes |
| `lost` | someone resolved it first | **no** — see override below |
| `missing` | no such ticket document | yes, with the existing warning |

### Why the ordering changed in the deny handlers

The three deny paths used to post the applicant-facing denial **before** writing
the status. Two recruiters denying the same ticket in the same second therefore
both succeeded, and **the applicant received two denial messages**. The message
now happens after Mongo has arbitrated, and only for the winner.

### `lost` offers an override, it does not block

A mistaken deny, an appeal, or a leader overruling are all normal in recruiting,
and none of them should require hand-editing Mongo. The loser gets an ephemeral
naming who resolved it and when, plus a button to overturn it.

- Gated on the **recruiter role** (`main_recruiter_role` / `fwa_recruiter_role`),
  not on Administrator — recruiters are the people who need it.
- **Re-checked at click time.** The dispatcher enforces nothing, so a button
  cannot inherit trust from the interaction that rendered it.
- Overriding calls `transition(expect=None)` — no precondition, deliberately.
- The audit entry records `override: true` and what it replaced.

Non-recruiters see the same explanation with no button.

⚠️ The override panel is **plain content plus an ActionRow, not a Container**.
`IS_COMPONENTS_V2` is a one-way latch: once set on a message, `content` is
rejected forever after, and this panel is edited with text when the override
completes. See [components-v2-in-hikari.md](components-v2-in-hikari.md).

### The audit array

Every transition pushes `{at, actor, actor_name, from, to, override}` onto
`audit`, plus `overrode: {status, by, at}` when it overturned someone. This is
what makes a disputed outcome reconstructible a week later, and it matters more
now that overrides are possible.

Small known TOCTOU: `overrode` records the prior resolution the actor was
**shown**, not a re-read at confirm time. A third write landing in that window
would not be reflected. Accepted deliberately — the audit records what the human
was told and acted on, which is the more useful record of a decision.

### Claiming is advisory

`claimed_by` / `claimed_at`, set by `/ticket claim`, cleared by `/ticket release`
(admins can `force` someone else's). The claim filter uses
`{"claimed_by": None}`, which matches missing fields, so it works against every
pre-existing ticket with no backfill.

**It does not gate approve or deny.** Discord cannot enforce per-user ownership
inside a thread — Tickets.bot disables claiming entirely in thread mode for this
reason — so a hard block would be theatre. Resolving a ticket someone else
claimed adds a note to your own confirmation and nothing more.

## Silent-write detection

`close.py` wraps status updates in `_status_write_warning(result, _id)`, which
surfaces the case where an update matched nothing. This exists because status
writes were previously failing silently — added in `ad2e980` (2026-08-02).
Keep that pattern on any new status writer.

## Related

- [ticket-data-model.md](ticket-data-model.md) — where these documents live.
- [ticket-channel-naming.md](ticket-channel-naming.md) — why channel name
  prefixes are a misleading proxy for status.

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

## Silent-write detection

`close.py` wraps status updates in `_status_write_warning(result, _id)`, which
surfaces the case where an update matched nothing. This exists because status
writes were previously failing silently — added in `ad2e980` (2026-08-02).
Keep that pattern on any new status writer.

## Related

- [ticket-data-model.md](ticket-data-model.md) — where these documents live.
- [ticket-channel-naming.md](ticket-channel-naming.md) — why channel name
  prefixes are a misleading proxy for status.

# Ticket data model — where the documents actually live

## The headline

Ticketing has two fixed authorities during the parallel rollout:

- Legacy channel tickets opened and managed through `/ticket` live in
  `button_store`.
- Thread-v2 tickets opened and managed through `/tickets` live in
  `tickets`. Completed terminal legacy clones also live there.

Ticket rows are not mirrored or dual-written between those collections, and
there is no configurable primary-store switch. Shared runtime slots and
counters coordinate duplicate-open prevention and ticket numbers without
moving ticket rows between authorities.

As of 2026-08-04, new interactive state no longer enters `button_store` at all.
It lives in `component_state`, where `expires_at` has a TTL index. Ticket history
never enters that TTL-backed collection.

`utils/mongo.py` declares both durable authorities, `ticket_automation_state`,
and the short-lived `ticket_creation_state` idempotency leases.

The namespaced legacy repository writes only to `button_store`; the thread-v2
repository in `tickets/store.py` writes only to `tickets`.
Component state reads go through `utils/component_state.py`. The dispatcher
checks `component_state` first and uses a guarded, non-ticket `button_store`
fallback only for older panels.

## The legacy channel-ticket document

Legacy `/ticket` creation stores this core shape in `button_store`:

```python
{
    "_id":           f"ticket_{channel.id}",   # string, prefixed
    "type":          "ticket",                 # discriminator
    "ticket_type":   "main" | "fwa",
    "ticket_number": int,                      # per-type counter
    "guild_id":      int,
    "channel_id":    int,
    "thread_id":     int,                      # the private recruiter thread
    "category_id":   int,
    "user_id":       int,
    "username":      str,                      # snapshot at creation
    "created_at":    datetime (BSON date, UTC),
    "status":        "open",
}
```

Legacy terminal writes add, depending on outcome:

- approve: `approved_at`, `approved_by`
- deny: `denied_at`, `denied_by`, `denial_type`

## How ticket documents and component state are told apart

The runtime markers and type discriminator separate durable ticket rows:

1. **Legacy:** `type: "ticket"`, with `venue: "channel"` and
   `runtime: "legacy_channel"` on new rows. The legacy repository also accepts
   older channel rows that predate those markers.
2. **Thread v2:** `type: "ticket"`, `venue: "thread"`, and
   `runtime: "thread_v2"` in `tickets`.
3. **Component state:** new interactive state lives in `component_state`, not
   either ticket authority. Older component rows may still use the guarded
   `button_store` fallback.

Legacy ticket IDs retain the `ticket_{channel_id}` prefix. Thread-v2 queries
also require the v2 runtime markers, so neither repository can claim the other
runtime's rows.

## Consequences worth knowing

- Historical `button_store` growth is bounded by a one-time guarded migration:
  known component rows are copied with a seven-day grace period, then removed
  from the legacy collection. Unknown shapes, tickets, and Goblin challenges are
  preserved rather than guessed at. New component sessions expire after 24
  hours in `component_state`.
- **Any count of `button_store` is not a count of tickets.** Always filter on
  `type: "ticket"`.
- Ticket creation is a cross-system compensating transaction, not a MongoDB
  transaction: a short-lived Mongo lease precedes Discord work, and an
  incomplete Discord channel is deleted before the lease is released.
- An uncertain primary MongoDB write is read back before Discord compensation.
  If confirmation is also unavailable, the channel and lease are retained for
  operator reconciliation rather than risking a durable orphan or duplicate.
- A lost Discord create response is reconciled by the atomically reserved ticket
  number embedded in the channel name. The bot removes the unique match; if
  Discord cannot be queried or the result is ambiguous, the creation lease stays
  blocked instead of allowing another channel.
- Ticket counters are allocated atomically before Discord creation. A failed
  Discord operation may leave a number gap; numbers remain unique.
- Fields useful for reporting are unevenly present: `username` is snapshotted at
  creation (so it goes stale if the user renames), and the handling recruiter is
  recorded as **either** `approved_by` **or** `denied_by` — there is no unified
  `handled_by`, so "filter by recruiter" needs an `$or` or a new normalised
  field.

## Counts as of 2026-08-02

361 ticket documents: `approved` 64, `denied` 273, `open` 23, `closed` 1.
All 23 open have live channels; 0 ghost rows, 0 orphaned channels.
Guild at 125/500 channels, 13 categories, the FWA category stranded at 50/50.

## Current authority and migration boundary

The two repositories are fixed rather than selected by configuration:

- `extensions/commands/tickets_legacy/store.py` constrains legacy `/ticket`
  reads and writes to channel-ticket rows in `button_store`.
- `extensions/commands/tickets/store.py` constrains `/tickets` reads and
  writes to `venue: "thread"`, `runtime: "thread_v2"` rows in `tickets`.

Rollout phases route **new intake only**. Promotion or rollback never copies,
repoints, or deletes an existing row; each ticket remains with the runtime that
created it.

The only supported legacy-to-v2 migration is the operator-paced terminal clone:

```text
/tickets migrate-legacy ... confirm:false
/tickets migrate-legacy ... confirm:true
```

It accepts one approved or denied source ticket at a time during `pilot`,
`thread_default`, or `thread_only`. The dry run previews the source. A confirmed
run creates or resumes an archived destination thread pair and a full v2 ticket
row in `tickets`; the source `button_store` row and source Discord objects remain
unchanged. The initial pilot permits 1–5 selected terminal tickets before
explicit pilot approval with:

```text
/tickets approve-migration-pilot confirm:true
```

### Thread-v2 and shared-runtime indexes

Thread-v2 indexes are partial to `venue: "thread"`, `runtime: "thread_v2"` rows:

| Index family | Why |
|---|---|
| Unique candidate and staff locations | One v2 ticket per Discord thread pair. |
| Unique ticket type and number | Prevent duplicate Main or FWA ticket numbers in v2. |
| Unique open applicant and type | Prevent two open v2 rows for one applicant/type; shared runtime slots enforce the same rule across both authorities. |
| Unique source guild and channel | Prevent two terminal clones of the same legacy source. |
| Status, type, date, user, player-tag, and username indexes | Back the console queue, history, and identity search. |
| Account-recovery flags | Find durable linked-account and staff-context retry work. |

Rollout readiness idempotently ensures these indexes plus the shared slot and
rollout indexes; shared counters use atomic records. Readiness preflights
conflicts and refuses to continue rather than dropping or weakening a
uniqueness constraint.

### ⚠️ No TTL index on `tickets` or `button_store`. Ever.

Ticket history is permanent and referred back to. Do not add a TTL "for
consistency" with whatever eventually prunes the ephemeral collection.

TTL indexes exist on ephemeral state only: `component_state.expires_at` and
`ticket_creation_state.expires_at`. The latter holds at most one current
creation lease per guild/user/ticket-type combination and retains it for no more
than 30 days. Durable v2 rows in `tickets` and legacy ticket rows in
`button_store` never receive an expiry.

`utils/component_state.py` owns the 24-hour fixed lifetime, immediate rejection
of expired rows (without waiting for Mongo's roughly minute-scale TTL sweep),
the seven-day legacy grace, and the component-state migration marker. Its index
creation happens before any older component-state copy or deletion; if index
creation fails, cleanup does not run.

Separating component state still stands on its own: durable ticket history must
not be interleaved with TTL-backed UI state.

## Related

- [ticket-status-lifecycle.md](ticket-status-lifecycle.md) — what the status
  values mean and why `closed` is 1.
- [component-dispatcher.md](component-dispatcher.md) — the other consumer of
  this collection.
- [ticket-console.md](ticket-console.md) — the v2 console reads thread-v2 and
  completed-clone rows in `tickets`, not live legacy rows in `button_store`.
- [legacy-ticket-migration.md](legacy-ticket-migration.md) — terminal cloning
  creates a full v2 destination row while leaving the legacy source unchanged.

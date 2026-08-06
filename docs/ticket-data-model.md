# Ticket data model — where the documents actually live

## The headline

Ticket documents historically lived in `button_store`, interleaved with
ephemeral interaction state. They now also live in the dedicated `tickets`
collection and production reads use that collection, but the legacy
`button_store` mirror remains during the reversible migration soak.

As of 2026-08-04, new interactive state no longer enters `button_store` at all.
It lives in `component_state`, where `expires_at` has a TTL index. Ticket history
never enters that TTL-backed collection.

`utils/mongo.py` declares the durable `tickets` collection, the transitional
`button_store` mirror, `ticket_automation_state`, and the short-lived
`ticket_creation_state` idempotency leases.

The write site calls `tickets/store.py`, which commits to the configured primary
collection and then best-effort mirrors the same document.
Component state reads go through `utils/component_state.py`. The dispatcher
checks `component_state` first and uses a guarded, non-ticket `button_store`
fallback only for panels rendered before the migration.

## The ticket document

Created at `handlers.py:357-369`:

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

Later writes add, depending on outcome:

- approve (`close.py:230-238`): `approved_at`, `approved_by`
- deny (`close.py:437`, `529`, `653`): `denied_at`, `denied_by`, `denial_type`

## How ticket documents and component state are told apart

Two mechanisms, both incidental but effective:

1. **`_id` prefix** — tickets are `ticket_{channel_id}`; component state is keyed
   by the `action_id` half of a `command_name:action_id` custom_id.
2. **`type: "ticket"`** — queries that mean tickets filter on it, e.g.
   `manage.py:413`, `manage.py:535`: `{"type": "ticket", "status": "open"}`.

Note the asymmetry: **ticket queries are namespaced, dispatcher reads are not.**
`components.py:86` looks up a bare `_id` with no `type` filter, so it is the
dispatcher that would load a ticket document if an id ever collided — not the
other way round. The `ticket_` prefix is what prevents this.

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

## Phase 1 status — LIVE as of 2026-08-02

`ticket_store` is flipped to **`"tickets"`**. Reads come from the new collection.
Both indexes built, no `channel_id` collisions found.

**Dual-write is still on, and must stay on until at least 2026-08-09.** It is the
only thing making the flag reversible: flip `ticket_store` back to
`"button_store"` and the legacy collection is still current. Remove dual-write
and that stops being true, permanently, with no warning at the moment it matters.

Phase 2 raised the stakes rather than lowering them. The mirror is now exercised
by `store.transition`'s conditional writes — **new code on the write path** — so
the soak is checking more than it was. Divergence held at none through the phase
2 verification run, but that is one session, not a week.

Verified end to end with the flag on — an update (denying an existing open
ticket) and an insert (a ticket created from the panel, then denied). Both landed
in both collections.

| | Total | approved | closed | denied | open |
|---|---|---|---|---|---|
| Baseline at plan time | 361 | 64 | 1 | 273 | 23 |
| Backfill (362 upserted) | 362 | 64 | 1 | 273 | 24 |
| After live write tests | **363** | 64 | 1 | 275 | 23 |

Identical in both collections, divergence none. The 361→362 gap is one real
ticket opened between the baseline reconciliation and the backfill — the drift
the command displays rather than blocks on, working as intended.

**The `BASELINE_*` constants in `migrate.py` are deliberately NOT updated.** They
record what was true when the migration was planned, and the drift line is what
makes that useful. Editing them to match today would delete the record.

## Phase 1: the `tickets` collection

Ticket documents now live in their own `tickets` collection. Every read and write
goes through `extensions/commands/tickets/store.py` — that module is the only
place that knows which collection is authoritative.

**The read switch is a config value, not a deploy.** `ticket_setup._id="config"`
carries `ticket_store: "button_store" | "tickets"`, defaulting to
`"button_store"`. The flag is read fresh on every call, never cached, so a flip
takes effect immediately with no restart. This is deliberate: it means the
backfill and the code repoint cannot land in the wrong order, and the moment of
risk is a Mongo write that reverses in a second rather than a deploy.

**Writes always target both collections** while the transition is live, ordered
so the collection currently being *read* from is written first. That primary
write is the creation commit point. A mirror insert failure is logged and shows
up as divergence in `/ticket diagnostics`; it does not make the caller retry a
ticket that already exists.

Migration is `/ticket migrate-store` — dry run by default, `confirm: true` to
write. Idempotent (upsert on the unchanged `_id`), and **nothing is ever deleted
from `button_store`**, so rollback is a flag flip, not a data restore.

The transform is purely additive: `schema_version: 2`, `venue: "channel"`, and
`channel_id` coerced to int. The inverse is a `$unset` of two keys.

### Indexes

| Index | Why |
|---|---|
| `channel_unique` — `{channel_id: 1}` unique | `close.py:107` and `:219` run this lookup on every approve/deny and it was a collection scan. Also a correctness constraint: one ticket per channel. |
| `status_created` — `{status: 1, created_at: -1}` | `/ticket list`, cleanup-ghosts, fix-mismatched, and the future queue view |

The unique index is the step most likely to surface a real problem. Because ids
have been stored as both `int` and `str` historically, two documents can coerce
to the same `channel_id`. `/ticket migrate-store` checks for that **in the dry
run, before writing anything**, and stops if it fires. **Do not drop the
uniqueness to get past a collision** — two documents pointing at one channel
means one of them is wrong, and burying it makes it permanent.

### ⚠️ No TTL index on `tickets` or `button_store`. Ever.

Ticket history is permanent and referred back to. Do not add a TTL "for
consistency" with whatever eventually prunes the ephemeral collection.

TTL indexes exist on ephemeral state only: `component_state.expires_at` and
`ticket_creation_state.expires_at`. The latter holds at most one current
creation lease per guild/user/ticket-type combination and retains it for no more
than 30 days. Durable `tickets` and the `button_store` mirror never receive an
expiry.

`utils/component_state.py` owns the 24-hour fixed lifetime, immediate rejection
of expired rows (without waiting for Mongo's roughly minute-scale TTL sweep),
the seven-day legacy grace, and the migration marker. Index creation happens
before any legacy copy or deletion; if index creation fails, cleanup does not
run.

The extraction still stands on its own: the unique index, the hot-path scan on
`close.py:107`/`:219`, and not interleaving durable records with throwaway UI
state.

## Related

- [ticket-status-lifecycle.md](ticket-status-lifecycle.md) — what the status
  values mean and why `closed` is 1.
- [component-dispatcher.md](component-dispatcher.md) — the other consumer of
  this collection.

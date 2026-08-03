# Ticket data model — where the documents actually live

## The headline

**Ticket documents live in the `button_store` collection**, interleaved with the
ephemeral component state the interaction dispatcher reads. There is no
`tickets` collection. This is an accident of history, not a design decision.

`utils/mongo.py` declares `button_store` alongside `ticket_setup` and
`ticket_automation_state` — which makes it look as though tickets have their own
home. They do not.

Write site: `handlers.py:370`, `await mongo.button_store.insert_one(ticket_data)`.
Read site for component state: `components.py:86`,
`await mongo.button_store.find_one({"_id": action_id}, {"_id": 0})`.

## The ticket document

Created at `handlers.py:357-369`:

```python
{
    "_id":           f"ticket_{channel.id}",   # string, prefixed
    "type":          "ticket",                 # discriminator
    "ticket_type":   "main" | "fwa",
    "ticket_number": int,                      # per-type counter
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

- **The collection is unindexed and unbounded.** Component state is never
  pruned, so `button_store` grows with every interaction, and the 361 ticket
  documents sit inside a collection whose real size is "361 plus every button
  ever pressed".
- **Any count of `button_store` is not a count of tickets.** Always filter on
  `type: "ticket"`.
- Fields useful for reporting are unevenly present: `username` is snapshotted at
  creation (so it goes stale if the user renames), and the handling recruiter is
  recorded as **either** `approved_by` **or** `denied_by` — there is no unified
  `handled_by`, so "filter by recruiter" needs an `$or` or a new normalised
  field.

## Counts as of 2026-08-02

361 ticket documents: `approved` 64, `denied` 273, `open` 23, `closed` 1.
All 23 open have live channels; 0 ghost rows, 0 orphaned channels.
Guild at 125/500 channels, 13 categories, the FWA category stranded at 50/50.

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

**Writes always go to both collections** while the transition is live, ordered so
the collection currently being *read* from is written first. A partial failure
therefore shows up as divergence in `/ticket diagnostics` rather than as a ticket
that appears not to exist.

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

### ⚠️ No TTL index on `tickets`. Ever.

Ticket history is permanent and referred back to. Do not add a TTL "for
consistency" with whatever eventually prunes the ephemeral collection.

It is also worth recording why **no TTL shipped in phase 1 on `button_store`
either**, since separating the two collections was partly motivated by making one
possible. It is possible now, but it would not do anything useful:

- A TTL index only expires documents that *have* the indexed date field.
- **The ~30 ephemeral write sites store no date at all** — checked at
  `war_plans.py:176`, `links.py:49`, `dashboard.py:58`, `lazy_cwl.py:167`. The
  only `button_store` documents carrying `created_at` are goblin challenges and
  the ticket copies.
- So a TTL on `button_store.created_at` would reap goblin challenges and nothing
  else — and would become actively dangerous the day a long-lived document like
  `war_message_*` gains a `created_at`.

Making pruning effective requires writing an `expires_at` at the ephemeral sites,
which belongs with the dispatcher's `component_state` work, not here. Roughly 16
of those sites key on `uuid4` and only ~5 on `str(interaction.id)`, so deriving
age from the `_id` covers a minority and is not a substitute.

The extraction still stands on its own: the unique index, the hot-path scan on
`close.py:107`/`:219`, and not interleaving durable records with throwaway UI
state.

## Related

- [ticket-status-lifecycle.md](ticket-status-lifecycle.md) — what the status
  values mean and why `closed` is 1.
- [component-dispatcher.md](component-dispatcher.md) — the other consumer of
  this collection.

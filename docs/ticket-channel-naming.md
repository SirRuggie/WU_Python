# Ticket channel naming — the ✅ → 🆕 prefix change

## The trap

**An old ticket channel whose name starts with ✅ is *open*, not closed.**

This is counter-intuitive enough that it cost real investigation time to
establish, and it will mislead anyone eyeballing the channel list or writing a
reconciliation script that infers status from a channel name.

## What happened

The original ticket implementation (`5be8ef8`, 2025-07-18) used ✅ as the
**creation** prefix:

```python
# Create the ticket channel with new naming format: ✅{type}-{number}-{username}
channel_name = f"✅{ticket_prefix}-{ticket_number}-{ctx.user.username}"
```

That was later changed to 🆕, which is the current format
(`handlers.py:291-292`):

```python
# Create the ticket channel with new naming format: 🆕{type}-{number}-{username}
channel_name = f"🆕{ticket_prefix}-{ticket_number}-{ctx.user.username}"
```

Both comments say "new naming format", which is its own small trap when reading
history.

So the guild contains ✅-prefixed channels from the early era that are perfectly
ordinary open tickets, sitting alongside a later convention in which ✅ reads
naturally as "done".

## The rule

**Status lives in MongoDB, not in the channel name.** The `status` field on the
ticket document is authoritative. Channel names are cosmetic, have changed
meaning over time, and are additionally mutated by close/deny flows that rename
channels.

`/ticket fix-mismatched` (`97f0c83`, 2026-08-02) exists precisely because
channel appearance and stored status had drifted apart — it targets denied-
looking channels carrying an open status.

## Related

- [ticket-status-lifecycle.md](ticket-status-lifecycle.md) — the authoritative
  status values.

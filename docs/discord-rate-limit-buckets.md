# REST rate-limit buckets: which routes compete with which

Written after `/todo` panels took 4.65 s to send to a DM and sometimes appeared
not to arrive at all. The useful part is not that story — it is **which calls
share a bucket**, because that is not guessable and it decides where a slow
route can be routed around.

## The rule

hikari keys a bucket on `(bucket_hash_from_Discord, major parameters of the
route)`. Different **route templates** get different bucket hashes, so they do
not compete. The major parameter is what makes `POST /channels/{a}/messages`
and `POST /channels/{b}/messages` separate buckets.

Verified in hikari 2.3.5, `hikari/internal/routes.py`:

| Call | Route template | Competes with |
|---|---|---|
| `bot.rest.create_message(channel=...)` | `POST /channels/{channel}/messages` | **anything else posting to that same channel** |
| `ctx.defer()` | `POST /interactions/{interaction}/{token}/callback` | nothing — see below |
| `ctx.respond()` after a defer | `POST /webhooks/{webhook}/{token}` (Discord treats the first followup as the original response) | nothing else in this bot |
| a followup | `POST /webhooks/{webhook}/{token}` | nothing else in this bot |
| deleting the ack | `DELETE /webhooks/{webhook}/{token}/messages/@original` | nothing else in this bot |

**`POST_INTERACTION_RESPONSE` is declared `has_ratelimits=False`**
(`routes.py:620-622`). A deferral is exempt from rate limiting entirely. It
cannot be delayed by a busy channel and it cannot contribute to one. If a
command is slow to acknowledge, the deferral is not the reason.

## The consequence that bit us

`POST /channels/{id}/messages` on a **user's DM channel** is one bucket shared
by everything the bot sends that user. Two known writers:

- `extensions/commands/todo.py` — the standalone DM `/todo` panel
- `extensions/tasks/band_sync_ical.py:268` — FWA sync alert DMs

**A burst of sync alerts and a `/todo` compete directly**, and either can be
throttled by the other. If a sync DM ever lands conspicuously late, this is the
first thing to check — it is expected behaviour, not a fault.

`extensions/commands/recruit/dashboard/server_walkthrough.py:443-445` posts two
messages back to back to one channel, which puts two writes into one bucket per
run by itself.

### What `/todo` does about it

The DM command defers first, then sends the panel with `create_message`, and
deletes the deferred placeholder only after the standalone message succeeds.
That removes the "X used /todo" response treatment and produces a normal
bot-authored message that the automatic checker can keep editing.

This deliberately accepts exposure to the shared DM-channel bucket. If the
standalone send raises, `/todo` falls back to editing the deferred interaction
response, so route choice cannot leave the user with no panel. A rate-limit
wait handled inside hikari may still make the standalone send slow without
raising; the early defer keeps the interaction valid while that wait occurs.
The fallback is marked manual-only and is not stored as an automatic session:
Discord interaction tokens expire after 15 minutes, while these panels may run
for 30 days. Only the latest standalone DM panel per user/channel is scheduled.

Guild `/todo` panels stay on the ephemeral interaction response and do not use
the standalone route or automatic checks.

`clan/dashboard/dashboard.py` still uses the defer → `create_message` → delete-ack
pattern and still carries this exposure.

## What we do NOT know

**The actual limit on a DM message bucket.** "5 per 5 seconds" is widely
repeated and was NOT what we observed: hikari logged this bucket resyncing its
slide period from **1 s to 10.0 s**, and waits of 4.65 s. Discord returns limits
in response headers and they are dynamic. Do not write "5 per 5 s" into code or
comments as though it were established.

**Why the slide period expands.** Same unexplained behaviour as
[incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md),
where it went 1 s → 60 s on guild channel-create and the root cause was never
found. That doc's warning stands: treat any confident explanation with
suspicion.

A *candidate* mechanism, unconfirmed: hikari tracked the period as 1 s, Discord
reported 10 s, and hikari resynced mid-window — `buckets.py:416-430` only warns
when its tracked period diverges by more than 0.7 s. On resync `increase_at`
jumps forward and the next acquire waits the remainder, which would put a 4.65 s
wait neatly inside a 10 s window. Plausible, not established.

## `max_rate_limit` is 120 seconds

`main.py` sets `max_rate_limit=120.0`, raised from 30 s after the 2026-07-29
incident so that long waits are waited out rather than raised as
`RateLimitTooLongError`.

That is right for background work. For an **interactive** command it means
hikari will silently sleep up to two minutes before the request goes out, with
no error anywhere and the user watching a spinner. There is no per-call
override. Anything user-facing that posts to a contended channel inherits this.

## Diagnosing

Capture the **full** rate-limit line — `is_global` changes the meaning
completely. A global limit is the whole bot against Discord; a bucket limit is
one route and one major parameter.

```bash
sudo journalctl -u wu-bot -o cat | grep -iE "ratelimit|slide period"
```

## Related

- [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md)
  — the guild channel-create version of the same unexplained behaviour, and the
  warning not to rebuild a custom REST client.
- [todo-dashboard.md](todo-dashboard.md) — the command that moved routes.

# Incident 2026-07-29 — channel-create rate limiting

Recorded so nobody re-investigates this from scratch. **Root cause was never
established.** Capacity was ruled out; the fix is a mitigation, not a cure.

## What happened

Ticket creation surfaced "Discord Rate Limit Active" to users **9 times in a
78-minute window** on 2026-07-29.

All failures were on `POST /guilds/{id}/channels` with `is_global=False`.
hikari logged that bucket increasing its slide period from 1s to 60s, so the
required wait landed in the (30, 60] range — just above the 30-second
`max_rate_limit` ceiling then in force. That turned a survivable wait into
`RateLimitTooLongError`, and a slower-but-successful ticket into a user-facing
error.

## Ruled out

- **Guild channel capacity.** The guild was well under the 500-channel limit
  (125 at the time of writing). Not a limit-exhaustion problem.

## Not established

Why the bucket's slide period expanded the way it did. Discord does not publish
this behaviour, and it was not reproducible on demand. Treat any confident
explanation with suspicion.

## What was actually done

1. **`max_rate_limit` raised 30s → 120s** (`856ad7c`, 2026-08-02) so waits in
   that range are waited out rather than thrown.
2. **Cooldown handling corrected** (`2d8754b`, 2026-08-02). Previously the
   per-user cooldown was *cleared* on a 429, which let users re-click the
   instant they read the error — and every re-click was another POST into the
   already-sliding bucket. That is what kept the incident alive for 78 minutes
   instead of a 60-second window. Now the cooldown is pushed *out* past the
   window by storing a future timestamp, so the elapsed-time check goes
   negative and the user stays blocked for `RATE_LIMIT_BACKOFF +
   COOLDOWN_DURATION`. The comment at `handlers.py:302-311` explains this at
   the call site — leave it there.
3. The generic error path also stopped clearing the cooldown, for the same
   reason (`handlers.py:436-440`).

## Prior related history

`956daae` (2025-09-12) attempted to fix channel-create rate limiting with a
hand-rolled REST client in `utils/rest_client.py`. It made things worse —
679-minute waits, a `TypeError` from incorrect `RateLimitTooLongError`
instantiation, and a global singleton that leaked rate-limit state across users.
It was deleted in `397e3ba` (2025-09-14) in favour of letting hikari handle it.

**Do not rebuild a custom REST client.** That road has been walked.

## Bearing on future work

Anything that creates channels in bulk inherits this exposure. Thread creation
uses a different endpoint and may not share the bucket — but that is an
assumption to verify against current Discord documentation, not a fact
established here.

If hikari is upgraded, re-check this: 2.4.x specifically changed sliding-window
rate limiting and bucket locks. See
[hikari-lightbulb-versions.md](hikari-lightbulb-versions.md).
